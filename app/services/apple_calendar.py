from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote, urljoin

import httpx
from icalendar import Calendar

from app.services.schemas import RawCalendarEvent

ICLOUD_BASE = "https://caldav.icloud.com/"
NS = {
    "D": "DAV:",
    "C": "urn:ietf:params:xml:ns:caldav",
    "CS": "http://calendarserver.org/ns/",
}


class CalendarFetchError(Exception):
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


def _propfind(client: httpx.AsyncClient, url: str, body: str, depth: str = "0") -> ET.Element:
    response = client.request(
        "PROPFIND",
        url,
        content=body,
        headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
    )
    response.raise_for_status()
    return ET.fromstring(response.content)


def _report(client: httpx.AsyncClient, url: str, body: str) -> ET.Element:
    response = client.request(
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


async def fetch_apple_calendar_events(
    apple_id: str,
    app_password: str,
    calendar_name: str,
    start: date,
    end: date,
) -> list[RawCalendarEvent]:
    auth = httpx.BasicAuth(apple_id, app_password)
    principal_body = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:current-user-principal />
  </D:prop>
</D:propfind>"""
    home_body = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <C:calendar-home-set />
  </D:prop>
</D:propfind>"""
    list_calendars_body = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">
  <D:prop>
    <D:displayname />
    <D:resourcetype />
  </D:prop>
</D:propfind>"""

    async with httpx.AsyncClient(auth=auth, timeout=30.0, follow_redirects=True) as client:
        try:
            principal_root = _propfind(client, ICLOUD_BASE, principal_body)
            principal_href = _find_first_href(principal_root, "D", "current-user-principal")
            if not principal_href:
                raise CalendarFetchError("Could not locate your iCloud calendar account.")

            principal_url = urljoin(ICLOUD_BASE, principal_href)
            home_root = _propfind(client, principal_url, home_body)
            home_href = _find_first_href(home_root, "C", "calendar-home-set")
            if not home_href:
                raise CalendarFetchError("Could not locate your iCloud calendars.")

            home_url = urljoin(ICLOUD_BASE, home_href)
            calendars_root = _propfind(client, home_url, list_calendars_body, depth="1")
            calendar_href = _find_calendar_href(calendars_root, calendar_name)
            if not calendar_href:
                raise CalendarFetchError(
                    f'Calendar "{calendar_name}" was not found in your iCloud account.'
                )

            calendar_url = urljoin(ICLOUD_BASE, calendar_href)
            events_root = _report(client, calendar_url, _calendar_query_body(start, end))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise CalendarFetchError(
                    "Could not sign in to iCloud. Check your Apple ID and app-specific password."
                ) from exc
            raise CalendarFetchError("Failed to fetch calendar events from iCloud.") from exc
        except httpx.HTTPError as exc:
            raise CalendarFetchError("Could not reach iCloud calendar service.") from exc

    return _parse_calendar_report(events_root, start)


def _find_calendar_href(root: ET.Element, calendar_name: str) -> str | None:
    target = calendar_name.strip().casefold()
    for response in root.findall(f".//{_ns_tag('D', 'response')}"):
        displayname = response.find(f".//{_ns_tag('D', 'displayname')}")
        href = response.find(f"{_ns_tag('D', 'href')}")
        if displayname is None or href is None or not displayname.text or not href.text:
            continue
        if displayname.text.strip().casefold() == target:
            return href.text
    return None


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
