"""Phase 6: compare booked duration estimates vs actual job timers / payroll hours."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.booking import Booking
from app.models.crew import Crew, CrewMember
from app.models.customer import Customer
from app.models.job import Job, JobWorkerAssignment
from app.services.duration_service import crew_schedule_rate, worker_schedule_rate


@dataclass(frozen=True)
class RateFeedbackRow:
    label: str
    booked_minutes: int | None
    actual_minutes: int | None
    price: Decimal | None
    estimated_dph: Decimal | None
    actual_dph: Decimal | None
    schedule_rate: Decimal | None
    note: str


def _dph(price: Decimal | None, minutes: int | None) -> Decimal | None:
    if price is None or not minutes or minutes <= 0:
        return None
    hours = Decimal(minutes) / Decimal(60)
    if hours <= 0:
        return None
    return (price / hours).quantize(Decimal("0.01"))


def schedule_rate_feedback(db: Session, user_id: int, limit: int = 50) -> list[RateFeedbackRow]:
    """Rows comparing booking estimates to customer job timer actuals."""
    bookings = list(
        db.scalars(
            select(Booking)
            .where(Booking.user_id == user_id, Booking.status == "confirmed")
            .options(
                selectinload(Booking.customer),
                selectinload(Booking.crew).selectinload(Crew.members).selectinload(CrewMember.worker),
            )
            .order_by(Booking.starts_at.desc())
            .limit(limit)
        )
    )
    rows: list[RateFeedbackRow] = []
    for booking in bookings:
        customer = booking.customer
        actual = customer.job_duration_minutes if customer else None
        schedule = crew_schedule_rate(booking.crew) if booking.crew else None
        rows.append(
            RateFeedbackRow(
                label=(
                    f"{customer.name if customer else 'Booking'} "
                    f"({booking.starts_at.date().isoformat() if booking.starts_at else '?'})"
                ),
                booked_minutes=booking.duration_minutes,
                actual_minutes=actual,
                price=booking.price,
                estimated_dph=_dph(booking.price, booking.duration_minutes),
                actual_dph=_dph(booking.price, actual),
                schedule_rate=schedule,
                note=booking.duration_source or "",
            )
        )
    return rows


def worker_rate_suggestions(db: Session, user_id: int) -> list[RateFeedbackRow]:
    """Per-worker view: current schedule rate vs implied from recent timed jobs.

    Uses customers with job_duration_minutes and usual_price, attributed evenly
    across active workers as a coarse suggestion signal (not auto-applied).
    """
    from app.models.worker import Worker

    workers = list(
        db.scalars(
            select(Worker).where(Worker.user_id == user_id, Worker.is_active.is_(True))
        )
    )
    timed = list(
        db.scalars(
            select(Customer).where(
                Customer.user_id == user_id,
                Customer.job_duration_minutes.is_not(None),
                Customer.usual_price.is_not(None),
            ).limit(100)
        )
    )
    rows: list[RateFeedbackRow] = []
    if not timed:
        for worker in workers:
            rows.append(
                RateFeedbackRow(
                    label=worker.name,
                    booked_minutes=None,
                    actual_minutes=None,
                    price=None,
                    estimated_dph=None,
                    actual_dph=None,
                    schedule_rate=worker_schedule_rate(worker),
                    note="No timed jobs yet",
                )
            )
        return rows

    # Average actual $/hr across timed jobs (property-level, not per-worker).
    total_price = sum((c.usual_price or Decimal("0")) for c in timed)
    total_minutes = sum((c.job_duration_minutes or 0) for c in timed)
    avg_dph = _dph(total_price, total_minutes)

    for worker in workers:
        rows.append(
            RateFeedbackRow(
                label=worker.name,
                booked_minutes=None,
                actual_minutes=total_minutes,
                price=total_price,
                estimated_dph=worker_schedule_rate(worker),
                actual_dph=avg_dph,
                schedule_rate=worker_schedule_rate(worker),
                note="Suggested from property timer average (review before changing)",
            )
        )
    return rows


def payroll_hours_vs_bookings(db: Session, user_id: int, limit: int = 30) -> list[RateFeedbackRow]:
    """Compare job ticket + assignment hours to nearby bookings when linkable by customer."""
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.user_id == user_id, Job.ticket_price.is_not(None))
            .options(selectinload(Job.assignments), selectinload(Job.customer))
            .order_by(Job.job_date.desc().nullslast(), Job.id.desc())
            .limit(limit)
        )
    )
    rows: list[RateFeedbackRow] = []
    for job in jobs:
        hours = sum(
            (a.hours_assigned or Decimal("0")) for a in (job.assignments or [])
        )
        minutes = int(hours * 60) if hours else None
        customer = job.customer
        booked = None
        if customer:
            booked = db.scalar(
                select(Booking)
                .where(
                    Booking.user_id == user_id,
                    Booking.customer_id == customer.id,
                    Booking.status == "confirmed",
                )
                .order_by(Booking.starts_at.desc())
                .limit(1)
            )
        rows.append(
            RateFeedbackRow(
                label=f"{job.customer_name or (customer.name if customer else 'Job')} ({job.job_date})",
                booked_minutes=booked.duration_minutes if booked else None,
                actual_minutes=minutes,
                price=job.ticket_price,
                estimated_dph=_dph(job.ticket_price, booked.duration_minutes if booked else None),
                actual_dph=_dph(job.ticket_price, minutes),
                schedule_rate=None,
                note="payroll hours_assigned",
            )
        )
    return rows
