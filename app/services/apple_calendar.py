from __future__ import annotations

import time
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote, urljoin

import httpx
from icalendar import Calendar, Event, vText

from app.services.schemas import RawCalendarEvent

ICLOUD_BASE = "https://caldav.icloud.com/"
NS = {
    "D": "DAV:",
    "C": "urn:ietf:params:xml:ns:caldav",
    "CS": "http://calendarserver.org/ns/",
}

# Resolve calendar collection URLs once per account+name (PROPFIND chain is slow).
_CALENDAR_URL_CACHE: dict[tuple[str, str], tuple[float, list[str]]] = {}
_CALENDAR_URL_TTL_SECONDS = 600.0


def _cached_calendar_urls(apple_id: str, calendar_name: str) -> list[str] | None:
    key = (apple_id.lower(), calendar_name)
    hit = _CALENDAR_URL_CACHE.get(key)
    if not hit:
        return None
    expires_at, urls = hit
    if time.monotonic() > expires_at:
        _CALENDAR_URL_CACHE.pop(key, None)
        return None
    return list(urls)


def _store_calendar_urls(apple_id: str, calendar_name: str, urls: list[str]) -> None:
    key = (apple_id.lower(), calendar_name)
    _CALENDAR_URL_CACHE[key] = (time.monotonic() + _CALENDAR_URL_TTL_SECONDS, list(urls))


def clear_calendar_url_cache(apple_id: str | None = None) -> None:
    if apple_id is None:
        _CALENDAR_URL_CACHE.clear()
        return
    prefix = apple_id.lower()
    for key in list(_CALENDAR_URL_CACHE):
        if key[0] == prefix:
            _CALENDAR_URL_CACHE.pop(key, None)


class CalendarFetchError(Exception):
    pass


class CalendarWriteError(CalendarFetchError):
    pass


def _ns_tag(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def _find_first_href(root: ET.Element, tag_prefix: str, tag_local: str) -> str | None:
    container = root.find(f".//{_ns_tag(tag_prefix, tag_local)}")
    if container is None:
        return None
    href = container.find(_ns_tag("D", "href"))
    if href is None or not href.text:
        return None
    return href.text


async def _propfind(client: httpx.AsyncClient, url: str, body: str, depth: str = "0") -> ET.Element:
    response = await client.request(
        "PROPFIND",
        url,
        content=body,
        headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
    )
    response.raise_for_status()
    return ET.fromstring(response.content)


async def _report(client: httpx.AsyncClient, url: str, body: str) -> ET.Element:
    response = await client.request(
        "REPORT",
        url,
        content=body,
        headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
    )
    response.raise_for_status()
    return ET.fromstring(response.content)


def _format_caldav_time(day: date) -> str:
    return day.strftime("%Y%m%d") + "T000000Z"


def _parse_ical_datetime(value: Any, fallback_date: date) -> datetime:
    if hasattr(value, "dt"):
        parsed = value.dt
        if isinstance(parsed, datetime):
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        if isinstance(parsed, date):
            return datetime.combine(parsed, datetime.min.time(), tzinfo=timezone.utc)
    return datetime.combine(fallback_date, datetime.min.time(), tzinfo=timezone.utc)


def _event_to_raw(event_id: str, component: Any, fallback_date: date) -> RawCalendarEvent:
    title = str(component.get("summary", "") or "")
    description = str(component.get("description", "") or "")
    location = str(component.get("location", "") or "")
    start = _parse_ical_datetime(component.get("dtstart"), fallback_date)
    end_value = component.get("dtend")
    end = _parse_ical_datetime(end_value, fallback_date) if end_value else start + timedelta(hours=1)
    raw_parts = [part for part in (title, location, description) if part]
    raw_text = "\n".join(raw_parts)
    return RawCalendarEvent(
        event_id=event_id,
        title=title,
        description=description,
        location=location,
        start=start,
        end=end,
        raw_text=raw_text,
    )


def _calendar_query_body(start: date, end: date) -> str:
    return f"""<?xml version="1.0" encoding="utf-8" ?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="{_format_caldav_time(start)}" end="{_format_caldav_time(end)}"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""


_PRINCIPAL_BODY = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:current-user-principal />
  </D:prop>
</D:propfind>"""

_HOME_BODY = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <C:calendar-home-set />
  </D:prop>
</D:propfind>"""

_LIST_CALENDARS_BODY = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">
  <D:prop>
    <D:displayname />
    <D:resourcetype />
  </D:prop>
</D:propfind>"""


async def _resolve_calendar_urls(
    client: httpx.AsyncClient,
    calendar_name: str,
    *,
    apple_id: str | None = None,
) -> list[str]:
    if apple_id:
        cached = _cached_calendar_urls(apple_id, calendar_name)
        if cached is not None:
            return cached

    principal_root = await _propfind(client, ICLOUD_BASE, _PRINCIPAL_BODY)
    principal_href = _find_first_href(principal_root, "D", "current-user-principal")
    if not principal_href:
        raise CalendarFetchError("Could not locate your iCloud calendar account.")

    principal_url = urljoin(ICLOUD_BASE, principal_href)
    home_root = await _propfind(client, principal_url, _HOME_BODY)
    home_href = _find_first_href(home_root, "C", "calendar-home-set")
    if not home_href:
        raise CalendarFetchError("Could not locate your iCloud calendars.")

    home_url = urljoin(ICLOUD_BASE, home_href)
    calendars_root = await _propfind(client, home_url, _LIST_CALENDARS_BODY, depth="1")
    calendar_hrefs = _find_all_calendar_hrefs(calendars_root, calendar_name)
    if not calendar_hrefs:
        raise CalendarFetchError(
            f'Calendar "{calendar_name}" was not found in your iCloud account.'
        )
    urls = [urljoin(home_url, href) for href in calendar_hrefs]
    if apple_id:
        _store_calendar_urls(apple_id, calendar_name, urls)
    return urls


def _auth_client(apple_id: str, app_password: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=httpx.BasicAuth(apple_id, app_password),
        timeout=30.0,
        follow_redirects=True,
    )


def _map_http_error(exc: Exception, *, write: bool = False) -> CalendarFetchError:
    action = "write" if write else "fetch"
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (401, 403):
            return CalendarFetchError(
                "Could not sign in to iCloud. Check your Apple ID and app-specific password."
            )
        return CalendarWriteError(f"Failed to {action} calendar events on iCloud.") if write else CalendarFetchError(
            "Failed to fetch calendar events from iCloud."
        )
    if isinstance(exc, httpx.HTTPError):
        return CalendarFetchError("Could not reach iCloud calendar service.")
    return CalendarFetchError(str(exc))


def _build_vevent_ics(
    *,
    uid: str,
    title: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//ss_payroll//EN")
    calendar.add("version", "2.0")
    event = Event()
    event.add("uid", uid)
    event.add("summary", title)
    if description:
        event.add("description", description)
    if location:
        event.add("location", location)
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", datetime.now(timezone.utc))
    event.add("transp", vText("OPAQUE"))
    calendar.add_component(event)
    return calendar.to_ical()


async def fetch_apple_calendar_events(
    apple_id: str,
    app_password: str,
    calendar_name: str,
    start: date,
    end: date,
) -> list[RawCalendarEvent]:
    async with _auth_client(apple_id, app_password) as client:
        try:
            calendar_urls = await _resolve_calendar_urls(client, calendar_name, apple_id=apple_id)
            query_body = _calendar_query_body(start, end)
            all_events: list[RawCalendarEvent] = []
            seen_ids: set[str] = set()
            for calendar_url in calendar_urls:
                events_root = await _report(client, calendar_url, query_body)
                calendar_events = _parse_calendar_report(events_root, start)
                for event in calendar_events:
                    if event.event_id in seen_ids:
                        continue
                    seen_ids.add(event.event_id)
                    all_events.append(event)
        except CalendarFetchError:
            raise
        except httpx.HTTPError as exc:
            raise _map_http_error(exc) from exc

    all_events.sort(key=lambda event: event.start)
    return all_events


async def create_apple_calendar_event(
    apple_id: str,
    app_password: str,
    calendar_name: str,
    *,
    title: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
    uid: str | None = None,
) -> RawCalendarEvent:
    event_uid = uid or str(uuid.uuid4())
    ics = _build_vevent_ics(
        uid=event_uid,
        title=title,
        description=description,
        location=location,
        start=start,
        end=end,
    )
    async with _auth_client(apple_id, app_password) as client:
        try:
            calendar_urls = await _resolve_calendar_urls(client, calendar_name, apple_id=apple_id)
            calendar_url = calendar_urls[0]
            if not calendar_url.endswith("/"):
                calendar_url += "/"
            event_url = urljoin(calendar_url, f"{event_uid}.ics")
            response = await client.put(
                event_url,
                content=ics,
                headers={"Content-Type": "text/calendar; charset=utf-8"},
            )
            if response.status_code not in (200, 201, 204):
                response.raise_for_status()
        except CalendarFetchError:
            raise
        except httpx.HTTPError as exc:
            raise _map_http_error(exc, write=True) from exc

    return RawCalendarEvent(
        event_id=event_uid,
        title=title,
        description=description,
        location=location,
        start=start if start.tzinfo else start.replace(tzinfo=timezone.utc),
        end=end if end.tzinfo else end.replace(tzinfo=timezone.utc),
        raw_text="\n".join(part for part in (title, location, description) if part),
    )


async def update_apple_calendar_event(
    apple_id: str,
    app_password: str,
    calendar_name: str,
    uid: str,
    *,
    title: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
) -> RawCalendarEvent:
    return await create_apple_calendar_event(
        apple_id,
        app_password,
        calendar_name,
        title=title,
        description=description,
        location=location,
        start=start,
        end=end,
        uid=uid,
    )


async def get_apple_calendar_event(
    apple_id: str,
    app_password: str,
    calendar_name: str,
    uid: str,
) -> RawCalendarEvent | None:
    async with _auth_client(apple_id, app_password) as client:
        try:
            calendar_urls = await _resolve_calendar_urls(client, calendar_name, apple_id=apple_id)
            for calendar_url in calendar_urls:
                if not calendar_url.endswith("/"):
                    calendar_url += "/"
                event_url = urljoin(calendar_url, f"{uid}.ics")
                response = await client.get(event_url)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                calendar = Calendar.from_ical(response.content)
                for component in calendar.walk("VEVENT"):
                    event_uid = str(component.get("uid", uid))
                    return _event_to_raw(event_uid, component, date.today())
        except CalendarFetchError:
            raise
        except httpx.HTTPError as exc:
            raise _map_http_error(exc) from exc
    return None


async def delete_apple_calendar_event(
    apple_id: str,
    app_password: str,
    calendar_name: str,
    uid: str,
) -> bool:
    """Delete a VEVENT by UID. Returns True if deleted (or already gone)."""
    deleted = False
    async with _auth_client(apple_id, app_password) as client:
        try:
            calendar_urls = await _resolve_calendar_urls(client, calendar_name, apple_id=apple_id)
            for calendar_url in calendar_urls:
                if not calendar_url.endswith("/"):
                    calendar_url += "/"
                event_url = urljoin(calendar_url, f"{uid}.ics")
                response = await client.delete(event_url)
                if response.status_code in (200, 204, 404):
                    deleted = True
                    continue
                response.raise_for_status()
                deleted = True
        except CalendarFetchError:
            raise
        except httpx.HTTPError as exc:
            raise _map_http_error(exc, write=True) from exc
    return deleted


def _is_calendar_collection(response: ET.Element) -> bool:
    resourcetype = response.find(f".//{_ns_tag('D', 'resourcetype')}")
    if resourcetype is None:
        return True
    return resourcetype.find(_ns_tag("C", "calendar")) is not None


def _find_calendar_href(root: ET.Element, calendar_name: str) -> str | None:
    hrefs = _find_all_calendar_hrefs(root, calendar_name)
    return hrefs[0] if hrefs else None


def _find_all_calendar_hrefs(root: ET.Element, calendar_name: str) -> list[str]:
    target = calendar_name.strip().casefold()
    hrefs: list[str] = []
    for response in root.findall(f".//{_ns_tag('D', 'response')}"):
        if not _is_calendar_collection(response):
            continue
        displayname = response.find(f".//{_ns_tag('D', 'displayname')}")
        href = response.find(f"{_ns_tag('D', 'href')}")
        if displayname is None or href is None or not displayname.text or not href.text:
            continue
        if displayname.text.strip().casefold() == target:
            hrefs.append(href.text)
    return hrefs


def _parse_calendar_report(root: ET.Element, fallback_date: date) -> list[RawCalendarEvent]:
    events: list[RawCalendarEvent] = []
    seen: set[str] = set()

    for response in root.findall(f".//{_ns_tag('D', 'response')}"):
        href_elem = response.find(f"{_ns_tag('D', 'href')}")
        calendar_data = response.find(f".//{_ns_tag('C', 'calendar-data')}")
        if calendar_data is None or not calendar_data.text:
            continue

        event_id = unquote(href_elem.text) if href_elem is not None and href_elem.text else ""
        try:
            calendar = Calendar.from_ical(calendar_data.text)
        except Exception:
            continue

        for component in calendar.walk("VEVENT"):
            uid = str(component.get("uid", event_id))
            if uid in seen:
                continue
            seen.add(uid)
            events.append(_event_to_raw(uid, component, fallback_date))

    events.sort(key=lambda event: event.start)
    return events
