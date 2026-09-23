from datetime import date, datetime

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


async def fetch_events_for_user(
    db: Session,
    user_id: int,
    start: date,
    end: date,
) -> list[RawCalendarEvent]:
    conn = get_active_connection(db, user_id)
    if not conn:
        return []

    apple_id, password, calendar_name = _connection_credentials(conn)
    return await fetch_apple_calendar_events(
        apple_id,
        password,
        calendar_name,
        start,
        end,
    )


async def create_event_for_user(
    db: Session,
    user_id: int,
    *,
    title: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
) -> RawCalendarEvent:
    conn = get_active_connection(db, user_id)
    if not conn:
        raise CalendarWriteError("Apple Calendar is not connected. Connect it in Settings first.")
    apple_id, password, calendar_name = _connection_credentials(conn)
    return await create_apple_calendar_event(
        apple_id,
        password,
        calendar_name,
        title=title,
        description=description,
        location=location,
        start=start,
        end=end,
    )


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
    conn = get_active_connection(db, user_id)
    if not conn:
        raise CalendarWriteError("Apple Calendar is not connected. Connect it in Settings first.")
    apple_id, password, calendar_name = _connection_credentials(conn)
    return await update_apple_calendar_event(
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


async def get_event_for_user(db: Session, user_id: int, uid: str) -> RawCalendarEvent | None:
    conn = get_active_connection(db, user_id)
    if not conn:
        return None
    apple_id, password, calendar_name = _connection_credentials(conn)
    return await get_apple_calendar_event(apple_id, password, calendar_name, uid)


async def delete_event_for_user(db: Session, user_id: int, uid: str) -> bool:
    conn = get_active_connection(db, user_id)
    if not conn:
        raise CalendarWriteError("Apple Calendar is not connected. Connect it in Settings first.")
    apple_id, password, calendar_name = _connection_credentials(conn)
    return await delete_apple_calendar_event(apple_id, password, calendar_name, uid)


__all__ = [
    "CalendarFetchError",
    "CalendarWriteError",
    "create_event_for_user",
    "delete_event_for_user",
    "fetch_events_for_user",
    "get_active_connection",
    "get_event_for_user",
    "is_calendar_connected",
    "update_event_for_user",
]
