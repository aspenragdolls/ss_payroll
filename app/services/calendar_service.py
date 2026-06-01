from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.calendar import CalendarConnection
from app.services.apple_calendar import CalendarFetchError, fetch_apple_calendar_events
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


async def fetch_events_for_user(
    db: Session,
    user_id: int,
    start: date,
    end: date,
) -> list[RawCalendarEvent]:
    conn = get_active_connection(db, user_id)
    if not conn:
        return []

    password = decrypt_credential(conn.access_token_encrypted)
    return await fetch_apple_calendar_events(
        conn.external_account_id,
        password,
        conn.calendar_id,
        start,
        end,
    )


__all__ = ["CalendarFetchError", "fetch_events_for_user", "get_active_connection", "is_calendar_connected"]
