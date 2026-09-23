"""Bidirectional sync between Apple Calendar events and customer CRM records.

Sync runs in the background on a timer and after app→Apple writes finish — never
on page load. App→Apple create/update/delete are also queued in the background
so the UI can redirect immediately.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.calendar import CalendarConnection
from app.models.customer import Customer
from app.services.calendar_service import (
    CalendarFetchError,
    fetch_events_for_user,
    get_active_connection,
)
from app.services.customer_service import (
    get_customer_by_calendar_uid,
    list_customers_with_calendar_uid,
    upsert_customer_from_event,
)
from app.services.event_parse import parse_event_for_app
from app.services.openrouter_job_parser import safe_decimal

logger = logging.getLogger(__name__)

# How far back/forward to pull events when mirroring calendar → app.
SYNC_LOOKBACK_DAYS = 14
SYNC_LOOKAHEAD_DAYS = 180

# Skip non-forced CalDAV pulls if we synced recently (periodic debounce).
MIN_SYNC_INTERVAL = timedelta(minutes=5)

# How often the background loop checks for connections due to sync.
PERIODIC_SYNC_TICK_SECONDS = 60


@dataclass
class CalendarSyncResult:
    upserted: int = 0
    cleared: int = 0
    skipped: bool = False
    error: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _should_skip_sync(conn: CalendarConnection) -> bool:
    if not conn.last_synced_at:
        return False
    last = conn.last_synced_at
    if last.tzinfo is not None:
        last = last.astimezone(timezone.utc).replace(tzinfo=None)
    return _utc_now() - last < MIN_SYNC_INTERVAL


def _clear_calendar_link(db: Session, customer: Customer) -> None:
    """Event removed from calendar — drop the link and schedule status."""
    fields: dict = {
        "calendar_event_uid": None,
        "next_service_due": None,
    }
    if customer.status in {"scheduled", "estimate"}:
        fields["status"] = "active"
    for key, value in fields.items():
        setattr(customer, key, value)
    db.commit()


def list_active_calendar_user_ids(db: Session) -> list[int]:
    rows = db.scalars(
        select(CalendarConnection.user_id).where(
            CalendarConnection.is_active.is_(True),
            CalendarConnection.access_token_encrypted.is_not(None),
            CalendarConnection.external_account_id.is_not(None),
            CalendarConnection.calendar_id.is_not(None),
        )
    ).all()
    return list(dict.fromkeys(int(uid) for uid in rows))


async def sync_calendar_to_app(
    db: Session,
    user_id: int,
    *,
    force: bool = False,
) -> CalendarSyncResult:
    """
    Pull events from Apple Calendar and mirror them onto customers.

    - Present events → upsert customer (status, price, address, phone, UID, due date)
    - Linked customers whose UID is gone from the window → clear schedule link
    """
    conn = get_active_connection(db, user_id)
    if not conn:
        return CalendarSyncResult(skipped=True)

    if not force and _should_skip_sync(conn):
        return CalendarSyncResult(skipped=True)

    today = date.today()
    start = today - timedelta(days=SYNC_LOOKBACK_DAYS)
    end = today + timedelta(days=SYNC_LOOKAHEAD_DAYS)

    try:
        events = await fetch_events_for_user(db, user_id, start, end)
    except CalendarFetchError as exc:
        logger.warning("Calendar sync fetch failed for user %s: %s", user_id, exc)
        return CalendarSyncResult(error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Calendar sync unexpected error for user %s: %s", user_id, exc)
        return CalendarSyncResult(error=str(exc))

    seen_uids: set[str] = set()
    upserted = 0

    for event in events:
        if not event.event_id:
            continue
        seen_uids.add(event.event_id)
        parsed = parse_event_for_app(event)
        name = (parsed["customer_name"] or "").strip()
        if not name:
            continue

        existing = get_customer_by_calendar_uid(db, user_id, event.event_id)
        customer_id = existing.id if existing else None
        if not customer_id:
            # Prefer exact name match so calendar-only creates don't duplicate.
            matches = (
                db.scalars(
                    select(Customer)
                    .where(
                        Customer.user_id == user_id,
                        Customer.name.ilike(name),
                    )
                    .order_by(Customer.id.asc())
                    .limit(1)
                ).first()
            )
            if matches:
                customer_id = matches.id

        event_day = event.start.date() if event.start else None
        upsert_customer_from_event(
            db,
            user_id,
            customer_id=customer_id,
            name=name,
            address=parsed["address"],
            phone=parsed["phone"],
            classification=parsed["classification"],
            service_scope=parsed["service_scope"],
            usual_price=safe_decimal(parsed["price"]),
            calendar_event_uid=event.event_id,
            next_service_due=event_day,
        )
        upserted += 1

    cleared = 0
    for customer in list_customers_with_calendar_uid(db, user_id):
        uid = customer.calendar_event_uid
        if not uid or uid in seen_uids:
            continue
        # Only clear if the linked due date falls inside the sync window
        # (or is missing) — avoids nuking far-future links we didn't fetch.
        due = customer.next_service_due
        if due is not None and (due < start or due > end):
            continue
        _clear_calendar_link(db, customer)
        cleared += 1

    conn = get_active_connection(db, user_id)
    if conn:
        conn.last_synced_at = _utc_now()
        db.commit()

    return CalendarSyncResult(upserted=upserted, cleared=cleared)


async def _run_sync_safe(user_id: int, *, force: bool) -> None:
    db = SessionLocal()
    try:
        await sync_calendar_to_app(db, user_id, force=force)
    except Exception:  # noqa: BLE001
        logger.exception("Background calendar sync failed for user %s", user_id)
    finally:
        db.close()


def schedule_calendar_sync(user_id: int, *, force: bool = True) -> None:
    """Fire-and-forget pull sync — used after app→Apple writes and on connect."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_run_sync_safe(user_id, force=force))


async def sync_due_connections() -> int:
    """Sync every active connection that is past MIN_SYNC_INTERVAL. Returns count attempted."""
    db = SessionLocal()
    try:
        user_ids = list_active_calendar_user_ids(db)
    finally:
        db.close()

    attempted = 0
    for user_id in user_ids:
        db = SessionLocal()
        try:
            result = await sync_calendar_to_app(db, user_id, force=False)
            if not result.skipped:
                attempted += 1
        except Exception:  # noqa: BLE001
            logger.exception("Periodic calendar sync failed for user %s", user_id)
        finally:
            db.close()
    return attempted


async def run_periodic_calendar_sync(stop: asyncio.Event) -> None:
    """Background loop: pull Apple → app for due connections until stop is set."""
    while not stop.is_set():
        try:
            await sync_due_connections()
        except Exception:  # noqa: BLE001
            logger.exception("Periodic calendar sync tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=PERIODIC_SYNC_TICK_SECONDS)
            break
        except asyncio.TimeoutError:
            continue
