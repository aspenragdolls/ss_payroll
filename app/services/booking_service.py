"""Local bookings and availability slot generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, time
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.booking import Booking
from app.models.crew import Crew
from app.models.customer import Customer
from app.models.scheduling_settings import SchedulingSettings
from app.services.crew_service import get_crew
from app.services.duration_service import (
    DurationError,
    DurationEstimate,
    estimate_duration_for_crew,
)


class BookingError(Exception):
    """User-facing booking failure."""


@dataclass(frozen=True)
class TimeSlot:
    starts_at: datetime
    ends_at: datetime


def get_scheduling_settings(db: Session, user_id: int) -> SchedulingSettings:
    settings = db.scalar(
        select(SchedulingSettings).where(SchedulingSettings.user_id == user_id)
    )
    if settings:
        return settings
    settings = SchedulingSettings(
        user_id=user_id,
        business_hours_start=time(8, 0),
        business_hours_end=time(17, 0),
        slot_grain_minutes=30,
        buffer_minutes=15,
        timezone="America/Denver",
    )
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def save_scheduling_settings(
    db: Session,
    user_id: int,
    *,
    business_hours_start: time,
    business_hours_end: time,
    slot_grain_minutes: int,
    buffer_minutes: int,
    timezone: str,
) -> SchedulingSettings:
    settings = get_scheduling_settings(db, user_id)
    settings.business_hours_start = business_hours_start
    settings.business_hours_end = business_hours_end
    settings.slot_grain_minutes = max(5, int(slot_grain_minutes))
    settings.buffer_minutes = max(0, int(buffer_minutes))
    settings.timezone = timezone.strip() or "America/Denver"
    db.commit()
    db.refresh(settings)
    return settings


def resolve_duration(
    db: Session,
    user_id: int,
    crew: Crew,
    price: Decimal,
    customer: Customer | None = None,
) -> DurationEstimate:
    settings = get_scheduling_settings(db, user_id)
    override = None
    prior = None
    if customer:
        if customer.duration_override_minutes and customer.duration_override_minutes > 0:
            override = customer.duration_override_minutes
        elif customer.job_duration_minutes and customer.job_duration_minutes > 0:
            prior = customer.job_duration_minutes
    return estimate_duration_for_crew(
        price,
        crew,
        override_minutes=override,
        prior_job_minutes=prior,
        grain_minutes=settings.slot_grain_minutes,
    )


def list_bookings_for_crew(
    db: Session,
    user_id: int,
    crew_id: int,
    start: datetime,
    end: datetime,
) -> list[Booking]:
    return list(
        db.scalars(
            select(Booking).where(
                Booking.user_id == user_id,
                Booking.crew_id == crew_id,
                Booking.status != "cancelled",
                Booking.starts_at < end,
                Booking.ends_at > start,
            ).order_by(Booking.starts_at)
        )
    )


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def available_slots(
    db: Session,
    user_id: int,
    crew_id: int,
    day: date,
    duration_minutes: int,
) -> list[TimeSlot]:
    settings = get_scheduling_settings(db, user_id)
    grain = max(5, settings.slot_grain_minutes or 30)
    buffer = max(0, settings.buffer_minutes or 0)
    start_t = settings.business_hours_start or time(8, 0)
    end_t = settings.business_hours_end or time(17, 0)

    day_start = datetime.combine(day, start_t)
    day_end = datetime.combine(day, end_t)
    if day_end <= day_start:
        return []

    busy = list_bookings_for_crew(db, user_id, crew_id, day_start, day_end)
    slots: list[TimeSlot] = []
    cursor = day_start
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=grain)
    pad = timedelta(minutes=buffer)

    while cursor + duration <= day_end:
        slot_end = cursor + duration
        conflict = False
        for booking in busy:
            padded_start = booking.starts_at - pad
            padded_end = booking.ends_at + pad
            if _overlaps(cursor, slot_end, padded_start, padded_end):
                conflict = True
                break
        if not conflict:
            slots.append(TimeSlot(starts_at=cursor, ends_at=slot_end))
        cursor += step
    return slots


async def create_booking(
    db: Session,
    user_id: int,
    *,
    crew_id: int,
    customer_id: int | None,
    price: Decimal,
    starts_at: datetime,
    quote_id: int | None = None,
    notes: str | None = None,
    customer_name: str | None = None,
    address: str | None = None,
    phone: str | None = None,
    classification: str = "windows",
    service_scope: str | None = None,
    write_apple: bool = True,
) -> Booking:
    from app.services.calendar_service import create_event_for_user
    from app.services.customer_service import get_customer, upsert_customer_from_event
    from app.services.event_format import build_event_description, build_event_title

    crew = get_crew(db, user_id, crew_id)
    if not crew or not crew.is_active:
        raise BookingError("Crew not found or inactive.")

    customer = get_customer(db, user_id, customer_id) if customer_id else None
    try:
        estimate = resolve_duration(db, user_id, crew, price, customer)
    except DurationError as exc:
        raise BookingError(str(exc)) from exc

    ends_at = starts_at + timedelta(minutes=estimate.minutes)
    settings = get_scheduling_settings(db, user_id)
    buffer = timedelta(minutes=settings.buffer_minutes or 0)
    existing = list_bookings_for_crew(
        db, user_id, crew_id, starts_at - buffer, ends_at + buffer
    )
    for booking in existing:
        if _overlaps(
            starts_at,
            ends_at,
            booking.starts_at - buffer,
            booking.ends_at + buffer,
        ):
            raise BookingError("That time slot is no longer available.")

    name = (customer_name or (customer.name if customer else "") or "Customer").strip()
    loc = address if address is not None else (customer.address if customer else "")
    ph = phone if phone is not None else (customer.phone if customer else "")

    event_uid = None
    if write_apple:
        calendar_name = crew.apple_calendar_id
        event = await create_event_for_user(
            db,
            user_id,
            title=build_event_title(name, price),
            description=build_event_description(
                ph or "",
                classification,
                service_scope,
                notes or "",
            ),
            location=(loc or "").strip(),
            start=starts_at,
            end=ends_at,
            calendar_name=calendar_name,
        )
        event_uid = event.event_id
        upsert_customer_from_event(
            db,
            user_id,
            customer_id=customer_id,
            name=name,
            address=loc or "",
            phone=ph or "",
            classification=classification,
            service_scope=service_scope,
            usual_price=price,
            calendar_event_uid=event_uid,
            next_service_due=starts_at.date(),
        )
        if customer_id:
            customer = get_customer(db, user_id, customer_id)
            if customer:
                customer.status = "scheduled"
                db.commit()

    booking = Booking(
        user_id=user_id,
        crew_id=crew_id,
        customer_id=customer_id,
        quote_id=quote_id,
        price=price,
        duration_minutes=estimate.minutes,
        starts_at=starts_at.replace(tzinfo=None) if starts_at.tzinfo else starts_at,
        ends_at=ends_at.replace(tzinfo=None) if ends_at.tzinfo else ends_at,
        calendar_event_uid=event_uid,
        status="confirmed",
        duration_source=estimate.source,
        notes=notes,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def list_bookings(
    db: Session,
    user_id: int,
    *,
    crew_id: int | None = None,
    customer_id: int | None = None,
    limit: int = 100,
) -> list[Booking]:
    stmt = (
        select(Booking)
        .where(Booking.user_id == user_id)
        .options(selectinload(Booking.crew), selectinload(Booking.customer))
        .order_by(Booking.starts_at.desc())
        .limit(limit)
    )
    if crew_id:
        stmt = stmt.where(Booking.crew_id == crew_id)
    if customer_id:
        stmt = stmt.where(Booking.customer_id == customer_id)
    return list(db.scalars(stmt))


def cancel_booking(db: Session, user_id: int, booking_id: int) -> Booking | None:
    booking = db.scalar(
        select(Booking).where(Booking.user_id == user_id, Booking.id == booking_id)
    )
    if not booking:
        return None
    booking.status = "cancelled"
    db.commit()
    db.refresh(booking)
    return booking
