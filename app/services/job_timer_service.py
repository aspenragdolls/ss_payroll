"""Start/Finish job timer for Apple Calendar event entries.

Stores actual on-site duration on the linked customer so payroll can later
compute crew dollars per hour from job price ÷ duration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.services.customer_service import get_customer_by_calendar_uid

_LOCAL_TZ = ZoneInfo("America/Denver")


class JobTimerError(Exception):
    """User-facing timer failure."""


def _now_local() -> datetime:
    """Naive local wall-clock time (America/Denver), matching event forms."""
    return datetime.now(_LOCAL_TZ).replace(tzinfo=None)


def compute_duration_minutes(started_at: datetime, finished_at: datetime) -> int:
    """Whole minutes between start and finish (minimum 1 when finish > start)."""
    delta = finished_at - started_at
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return 0
    minutes = seconds // 60
    if seconds % 60:
        minutes += 1
    return max(1, minutes)


def format_duration_minutes(minutes: int | None) -> str:
    """Format minutes as hours and minutes, e.g. '2h 15m' or '45m'."""
    if minutes is None:
        return ""
    total = max(0, int(minutes))
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


@dataclass(frozen=True)
class JobTimerView:
    """Template-facing timer state for an event entry."""

    status: str  # idle | in_progress | finished
    duration_label: str
    started_label: str
    can_start: bool
    can_finish: bool


def job_timer_view(customer: Customer | None) -> JobTimerView:
    if not customer:
        return JobTimerView(
            status="idle",
            duration_label="",
            started_label="",
            can_start=False,
            can_finish=False,
        )

    started = customer.job_started_at
    finished = customer.job_finished_at
    duration = customer.job_duration_minutes

    if started and not finished:
        return JobTimerView(
            status="in_progress",
            duration_label="",
            started_label=_format_clock(started),
            can_start=True,
            can_finish=True,
        )

    if duration is not None and started and finished:
        return JobTimerView(
            status="finished",
            duration_label=format_duration_minutes(duration),
            started_label="",
            can_start=True,
            can_finish=False,
        )

    return JobTimerView(
        status="idle",
        duration_label="",
        started_label="",
        can_start=True,
        can_finish=False,
    )


def _format_clock(value: datetime) -> str:
    hour = value.hour % 12 or 12
    ampm = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d} {ampm}"


def start_job_for_event(db: Session, user_id: int, calendar_event_uid: str) -> Customer:
    customer = get_customer_by_calendar_uid(db, user_id, calendar_event_uid)
    if not customer:
        raise JobTimerError(
            "No customer is linked to this event yet. Save the event (Done), then Start Job."
        )
    now = _now_local()
    customer.job_started_at = now
    customer.job_finished_at = None
    customer.job_duration_minutes = None
    db.commit()
    db.refresh(customer)
    return customer


def finish_job_for_event(db: Session, user_id: int, calendar_event_uid: str) -> Customer:
    customer = get_customer_by_calendar_uid(db, user_id, calendar_event_uid)
    if not customer:
        raise JobTimerError(
            "No customer is linked to this event yet. Save the event (Done), then try again."
        )
    if not customer.job_started_at:
        raise JobTimerError('Hit "Start Job" when you arrive before finishing.')
    if customer.job_finished_at and customer.job_duration_minutes is not None:
        raise JobTimerError("This job is already finished. Start Job again to retake the timer.")

    now = _now_local()
    minutes = compute_duration_minutes(customer.job_started_at, now)
    if minutes < 1:
        raise JobTimerError("Job duration is too short. Wait a moment, then Finish again.")

    customer.job_finished_at = now
    customer.job_duration_minutes = minutes
    db.commit()
    db.refresh(customer)
    return customer
