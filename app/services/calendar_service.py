from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timezone
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.calendar import CalendarConnection
from app.services.apple_calendar import (
    CalendarFetchError,
    CalendarWriteError,
    create_apple_calendar_event,
    delete_apple_calendar_event,
    fetch_apple_calendar_events,
    get_apple_calendar_event,
    update_apple_calendar_event,
)
from app.services.credential_crypto import decrypt_credential
from app.services.schemas import RawCalendarEvent

logger = logging.getLogger(__name__)

# Short in-memory cache so list ↔ edit navigation does not re-hit CalDAV every time.
_EVENT_LIST_CACHE: dict[tuple[int, str, str], tuple[float, list[RawCalendarEvent]]] = {}
_EVENT_BY_ID_CACHE: dict[tuple[int, str], tuple[float, RawCalendarEvent]] = {}
_EVENT_CACHE_TTL_SECONDS = 90.0

# In-flight app→Apple writes, merged into reads until CalDAV confirms.
_PENDING_UPSERTS: dict[tuple[int, str], RawCalendarEvent] = {}
_PENDING_DELETES: set[tuple[int, str]] = set()


def get_active_connection(db: Session, user_id: int) -> CalendarConnection | None:
    conn = db.scalar(
        select(CalendarConnection).where(
            CalendarConnection.user_id == user_id,
            CalendarConnection.is_active.is_(True),
        )
    )
    if not conn or not conn.access_token_encrypted:
        return None
    if not conn.external_account_id or not conn.calendar_id:
        return None
    return conn


def is_calendar_connected(db: Session, user_id: int) -> bool:
    return get_active_connection(db, user_id) is not None


def _connection_credentials(conn: CalendarConnection) -> tuple[str, str, str]:
    password = decrypt_credential(conn.access_token_encrypted)
    return conn.external_account_id, password, conn.calendar_id


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _local_event(
    *,
    event_id: str,
    title: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
) -> RawCalendarEvent:
    return RawCalendarEvent(
        event_id=event_id,
        title=title,
        description=description,
        location=location,
        start=_as_aware(start),
        end=_as_aware(end),
        raw_text="\n".join(part for part in (title, location, description) if part),
    )


def _cache_list(user_id: int, start: date, end: date, events: list[RawCalendarEvent]) -> None:
    key = (user_id, start.isoformat(), end.isoformat())
    expires = monotonic() + _EVENT_CACHE_TTL_SECONDS
    _EVENT_LIST_CACHE[key] = (expires, list(events))
    for event in events:
        _EVENT_BY_ID_CACHE[(user_id, event.event_id)] = (expires, event)


def _cached_list(user_id: int, start: date, end: date) -> list[RawCalendarEvent] | None:
    key = (user_id, start.isoformat(), end.isoformat())
    hit = _EVENT_LIST_CACHE.get(key)
    if not hit:
        return None
    expires, events = hit
    if monotonic() > expires:
        _EVENT_LIST_CACHE.pop(key, None)
        return None
    return list(events)


def _cached_event(user_id: int, uid: str) -> RawCalendarEvent | None:
    hit = _EVENT_BY_ID_CACHE.get((user_id, uid))
    if not hit:
        # Fall back to any still-valid list cache entry.
        now = monotonic()
        for (cached_user, _s, _e), (expires, events) in list(_EVENT_LIST_CACHE.items()):
            if cached_user != user_id:
                continue
            if now > expires:
                _EVENT_LIST_CACHE.pop((cached_user, _s, _e), None)
                continue
            for event in events:
                if event.event_id == uid:
                    return event
        return None
    expires, event = hit
    if monotonic() > expires:
        _EVENT_BY_ID_CACHE.pop((user_id, uid), None)
        return None
    return event


def invalidate_event_cache(user_id: int | None = None) -> None:
    if user_id is None:
        _EVENT_LIST_CACHE.clear()
        _EVENT_BY_ID_CACHE.clear()
        _PENDING_UPSERTS.clear()
        _PENDING_DELETES.clear()
        return
    for key in list(_EVENT_LIST_CACHE):
        if key[0] == user_id:
            _EVENT_LIST_CACHE.pop(key, None)
    for key in list(_EVENT_BY_ID_CACHE):
        if key[0] == user_id:
            _EVENT_BY_ID_CACHE.pop(key, None)
    for key in list(_PENDING_UPSERTS):
        if key[0] == user_id:
            _PENDING_UPSERTS.pop(key, None)
    for key in list(_PENDING_DELETES):
        if key[0] == user_id:
            _PENDING_DELETES.discard(key)


def _mark_pending_upsert(user_id: int, event: RawCalendarEvent) -> None:
    key = (user_id, event.event_id)
    _PENDING_DELETES.discard(key)
    _PENDING_UPSERTS[key] = event


def _mark_pending_delete(user_id: int, uid: str) -> None:
    key = (user_id, uid)
    _PENDING_UPSERTS.pop(key, None)
    _PENDING_DELETES.add(key)


def _clear_pending(user_id: int, uid: str) -> None:
    key = (user_id, uid)
    _PENDING_UPSERTS.pop(key, None)
    _PENDING_DELETES.discard(key)


def _merge_pending(user_id: int, start: date, end: date, events: list[RawCalendarEvent]) -> list[RawCalendarEvent]:
    by_id = {e.event_id: e for e in events}
    for (pending_user, uid), event in _PENDING_UPSERTS.items():
        if pending_user != user_id:
            continue
        day = event.start.date()
        if start <= day <= end:
            by_id[uid] = event
    for pending_user, uid in _PENDING_DELETES:
        if pending_user == user_id:
            by_id.pop(uid, None)
    merged = list(by_id.values())
    merged.sort(key=lambda e: e.start)
    return merged


def _seed_event_cache(user_id: int, event: RawCalendarEvent) -> None:
    """Optimistically show a write in the UI before CalDAV finishes."""
    _mark_pending_upsert(user_id, event)
    expires = monotonic() + _EVENT_CACHE_TTL_SECONDS
    _EVENT_BY_ID_CACHE[(user_id, event.event_id)] = (expires, event)
    event_day = event.start.date().isoformat()
    for (cached_user, start_s, end_s), (_exp, events) in list(_EVENT_LIST_CACHE.items()):
        if cached_user != user_id:
            continue
        if not (start_s <= event_day <= end_s):
            continue
        updated = [e for e in events if e.event_id != event.event_id]
        updated.append(event)
        updated.sort(key=lambda e: e.start)
        _EVENT_LIST_CACHE[(cached_user, start_s, end_s)] = (expires, updated)


def _remove_event_from_cache(user_id: int, uid: str) -> None:
    _mark_pending_delete(user_id, uid)
    _EVENT_BY_ID_CACHE.pop((user_id, uid), None)
    for key, (expires, events) in list(_EVENT_LIST_CACHE.items()):
        if key[0] != user_id:
            continue
        filtered = [e for e in events if e.event_id != uid]
        if len(filtered) != len(events):
            _EVENT_LIST_CACHE[key] = (expires, filtered)


def _schedule_post_write_sync(user_id: int) -> None:
    from app.services.calendar_sync_service import schedule_calendar_sync

    schedule_calendar_sync(user_id, force=True)


def _schedule_background(coro) -> None:
    """Fire-and-forget on the running event loop (no-op outside async context)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(coro)


async def _run_create_write(
    user_id: int,
    apple_id: str,
    password: str,
    calendar_name: str,
    *,
    uid: str,
    title: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
) -> None:
    try:
        await create_apple_calendar_event(
            apple_id,
            password,
            calendar_name,
            title=title,
            description=description,
            location=location,
            start=start,
            end=end,
            uid=uid,
        )
        _clear_pending(user_id, uid)
        _schedule_post_write_sync(user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Background Apple Calendar create failed for user %s uid %s", user_id, uid)
        invalidate_event_cache(user_id)


async def _run_update_write(
    user_id: int,
    apple_id: str,
    password: str,
    calendar_name: str,
    uid: str,
    *,
    title: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
) -> None:
    try:
        await update_apple_calendar_event(
            apple_id,
            password,
            calendar_name,
            uid,
            title=title,
            description=description,
            location=location,
            start=start,
            end=end,
        )
        _clear_pending(user_id, uid)
        _schedule_post_write_sync(user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Background Apple Calendar update failed for user %s uid %s", user_id, uid)
        invalidate_event_cache(user_id)


async def _run_delete_write(
    user_id: int,
    apple_id: str,
    password: str,
    calendar_name: str,
    uid: str,
) -> None:
    try:
        await delete_apple_calendar_event(apple_id, password, calendar_name, uid)
        _clear_pending(user_id, uid)
        _schedule_post_write_sync(user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Background Apple Calendar delete failed for user %s uid %s", user_id, uid)
        invalidate_event_cache(user_id)


async def fetch_events_for_user(
    db: Session,
    user_id: int,
    start: date,
    end: date,
) -> list[RawCalendarEvent]:
    conn = get_active_connection(db, user_id)
    if not conn:
        return []

    cached = _cached_list(user_id, start, end)
    if cached is not None:
        return _merge_pending(user_id, start, end, cached)

    apple_id, password, calendar_name = _connection_credentials(conn)
    events = await fetch_apple_calendar_events(
        apple_id,
        password,
        calendar_name,
        start,
        end,
    )
    _cache_list(user_id, start, end, events)
    return _merge_pending(user_id, start, end, events)


async def create_event_for_user(
    db: Session,
    user_id: int,
    *,
    title: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
    calendar_name: str | None = None,
) -> RawCalendarEvent:
    """Queue an Apple write in the background; return a local event immediately."""
    conn = get_active_connection(db, user_id)
    if not conn:
        raise CalendarWriteError("Apple Calendar is not connected. Connect it in Settings first.")
    apple_id, password, default_calendar = _connection_credentials(conn)
    calendar_name = (calendar_name or "").strip() or default_calendar
    event = _local_event(
        event_id=str(uuid.uuid4()),
        title=title,
        description=description,
        location=location,
        start=start,
        end=end,
    )
    _seed_event_cache(user_id, event)
    _schedule_background(
        _run_create_write(
            user_id,
            apple_id,
            password,
            calendar_name,
            uid=event.event_id,
            title=title,
            description=description,
            location=location,
            start=start,
            end=end,
        )
    )
    return event


async def update_event_for_user(
    db: Session,
    user_id: int,
    uid: str,
    *,
    title: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
) -> RawCalendarEvent:
    """Queue an Apple write in the background; return a local event immediately."""
    conn = get_active_connection(db, user_id)
    if not conn:
        raise CalendarWriteError("Apple Calendar is not connected. Connect it in Settings first.")
    apple_id, password, calendar_name = _connection_credentials(conn)
    event = _local_event(
        event_id=uid,
        title=title,
        description=description,
        location=location,
        start=start,
        end=end,
    )
    _seed_event_cache(user_id, event)
    _schedule_background(
        _run_update_write(
            user_id,
            apple_id,
            password,
            calendar_name,
            uid,
            title=title,
            description=description,
            location=location,
            start=start,
            end=end,
        )
    )
    return event


async def get_event_for_user(db: Session, user_id: int, uid: str) -> RawCalendarEvent | None:
    conn = get_active_connection(db, user_id)
    if not conn:
        return None
    if (user_id, uid) in _PENDING_DELETES:
        return None
    pending = _PENDING_UPSERTS.get((user_id, uid))
    if pending is not None:
        return pending
    cached = _cached_event(user_id, uid)
    if cached is not None:
        return cached
    apple_id, password, calendar_name = _connection_credentials(conn)
    event = await get_apple_calendar_event(apple_id, password, calendar_name, uid)
    if event is not None:
        _EVENT_BY_ID_CACHE[(user_id, uid)] = (
            monotonic() + _EVENT_CACHE_TTL_SECONDS,
            event,
        )
    return event


async def delete_event_for_user(db: Session, user_id: int, uid: str) -> bool:
    """Queue an Apple delete in the background; update local cache immediately."""
    conn = get_active_connection(db, user_id)
    if not conn:
        raise CalendarWriteError("Apple Calendar is not connected. Connect it in Settings first.")
    apple_id, password, calendar_name = _connection_credentials(conn)
    _remove_event_from_cache(user_id, uid)
    _schedule_background(
        _run_delete_write(user_id, apple_id, password, calendar_name, uid)
    )
    return True


__all__ = [
    "CalendarFetchError",
    "CalendarWriteError",
    "create_event_for_user",
    "delete_event_for_user",
    "fetch_events_for_user",
    "get_active_connection",
    "get_event_for_user",
    "invalidate_event_cache",
    "is_calendar_connected",
    "update_event_for_user",
]
