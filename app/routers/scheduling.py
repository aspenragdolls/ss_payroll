"""Staff booking list + scheduling settings + rate feedback reports."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.booking_service import (
    BookingError,
    create_booking,
    get_scheduling_settings,
    list_bookings,
    resolve_duration,
    save_scheduling_settings,
)
from app.services.crew_service import get_crew, list_crews
from app.services.customer_service import get_customer
from app.services.duration_service import DurationError
from app.services.openrouter_job_parser import safe_decimal
from app.services.rate_feedback_service import (
    payroll_hours_vs_bookings,
    schedule_rate_feedback,
    worker_rate_suggestions,
)
from sqlalchemy import select

from app.models.customer import Customer

router = APIRouter(tags=["scheduling"])


def _customer_options(db: Session, user_id: int) -> list[Customer]:
    return list(
        db.scalars(
            select(Customer)
            .where(Customer.user_id == user_id, Customer.is_active.is_(True))
            .order_by(Customer.name)
            .limit(500)
        )
    )


@router.get("/bookings")
async def bookings_list(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bookings = list_bookings(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "bookings/list.html",
        {"request": request, "user": user, "bookings": bookings},
    )


@router.get("/bookings/new")
async def bookings_new(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return request.app.state.templates.TemplateResponse(
        request,
        "bookings/form.html",
        {
            "request": request,
            "user": user,
            "crews": list_crews(db, user.id, active_only=True),
            "customers": _customer_options(db, user.id),
            "error": None,
            "duration_preview": None,
        },
    )


@router.post("/bookings/new")
async def bookings_create(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    crew_id: int = Form(...),
    customer_id: str = Form(""),
    price: str = Form(...),
    starts_at: str = Form(...),
    notes: str = Form(""),
):
    crews = list_crews(db, user.id, active_only=True)
    customers = _customer_options(db, user.id)

    def fail(message: str, duration_preview=None):
        return request.app.state.templates.TemplateResponse(
            request,
            "bookings/form.html",
            {
                "request": request,
                "user": user,
                "crews": crews,
                "customers": customers,
                "error": message,
                "duration_preview": duration_preview,
            },
            status_code=400,
        )

    ticket = safe_decimal(price)
    if ticket is None or ticket <= 0:
        return fail("Enter a valid price.")

    crew = get_crew(db, user.id, crew_id)
    if not crew:
        return fail("Select a valid crew.")

    cid = int(customer_id) if customer_id.strip().isdigit() else None
    customer = get_customer(db, user.id, cid) if cid else None

    settings = get_scheduling_settings(db, user.id)
    tz = ZoneInfo(settings.timezone or "America/Denver")
    try:
        start = datetime.fromisoformat(starts_at)
    except ValueError:
        return fail("Invalid start time.")
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)

    try:
        estimate = resolve_duration(db, user.id, crew, ticket, customer)
    except DurationError as exc:
        return fail(str(exc))

    try:
        await create_booking(
            db,
            user.id,
            crew_id=crew_id,
            customer_id=cid,
            price=ticket,
            starts_at=start,
            notes=notes or None,
            customer_name=customer.name if customer else None,
            address=customer.address if customer else None,
            phone=customer.phone if customer else None,
            write_apple=True,
        )
    except BookingError as exc:
        return fail(str(exc), duration_preview=estimate.minutes)

    return RedirectResponse("/bookings", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/settings/scheduling")
async def scheduling_settings_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_scheduling_settings(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "settings/scheduling.html",
        {
            "request": request,
            "user": user,
            "settings": settings,
            "saved": request.query_params.get("saved") == "1",
            "error": None,
        },
    )


@router.post("/settings/scheduling")
async def scheduling_settings_save(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    business_hours_start: str = Form(...),
    business_hours_end: str = Form(...),
    slot_grain_minutes: int = Form(30),
    buffer_minutes: int = Form(15),
    timezone: str = Form("America/Denver"),
):
    def parse_time(raw: str) -> time | None:
        try:
            return datetime.strptime(raw.strip(), "%H:%M").time()
        except ValueError:
            return None

    start_t = parse_time(business_hours_start)
    end_t = parse_time(business_hours_end)
    if not start_t or not end_t:
        settings = get_scheduling_settings(db, user.id)
        return request.app.state.templates.TemplateResponse(
            request,
            "settings/scheduling.html",
            {
                "request": request,
                "user": user,
                "settings": settings,
                "saved": False,
                "error": "Use HH:MM for business hours.",
            },
            status_code=400,
        )
    save_scheduling_settings(
        db,
        user.id,
        business_hours_start=start_t,
        business_hours_end=end_t,
        slot_grain_minutes=slot_grain_minutes,
        buffer_minutes=buffer_minutes,
        timezone=timezone,
    )
    return RedirectResponse("/settings/scheduling?saved=1", status_code=303)


@router.get("/reports/schedule-rates")
async def schedule_rates_report(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return request.app.state.templates.TemplateResponse(
        request,
        "reports/schedule_rates.html",
        {
            "request": request,
            "user": user,
            "booking_rows": schedule_rate_feedback(db, user.id),
            "worker_rows": worker_rate_suggestions(db, user.id),
            "payroll_rows": payroll_hours_vs_bookings(db, user.id),
        },
    )
