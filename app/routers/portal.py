"""Customer self-scheduling portal."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.customer_account import CustomerAccount
from app.services.booking_service import (
    BookingError,
    available_slots,
    create_booking,
    get_scheduling_settings,
    resolve_duration,
)
from app.services.crew_service import list_crews
from app.services.duration_service import DurationError
from app.services.portal_auth_service import (
    authenticate_customer_account,
    get_account_by_id,
    get_business_by_slug_or_id,
    register_customer_account,
)
from app.services.quote_service import (
    can_self_schedule,
    instant_estimate,
    list_packages,
    past_services_for_customer,
)

router = APIRouter(prefix="/portal", tags=["portal"])

_SESSION_KEY = "customer_account_id"


def get_current_portal_account(
    request: Request, db: Session = Depends(get_db)
) -> CustomerAccount:
    account_id = request.session.get(_SESSION_KEY)
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Not authenticated",
            headers={"Location": "/portal"},
        )
    account = get_account_by_id(db, account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Invalid session",
            headers={"Location": "/portal"},
        )
    return account


def get_optional_portal_account(
    request: Request, db: Session = Depends(get_db)
) -> CustomerAccount | None:
    account_id = request.session.get(_SESSION_KEY)
    if not account_id:
        return None
    return get_account_by_id(db, account_id)


@router.get("")
async def portal_home(request: Request, db: Session = Depends(get_db)):
    account = get_optional_portal_account(request, db)
    if account:
        return RedirectResponse("/portal/schedule", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request,
        "portal/home.html",
        {"request": request, "user": None, "account": None},
    )


@router.get("/{business_key}/register")
async def portal_register_page(
    request: Request,
    business_key: str,
    db: Session = Depends(get_db),
):
    business = get_business_by_slug_or_id(db, business_key)
    if not business:
        return request.app.state.templates.TemplateResponse(
            request,
            "portal/home.html",
            {"request": request, "user": None, "error": "Business not found."},
            status_code=404,
        )
    return request.app.state.templates.TemplateResponse(
        request,
        "portal/register.html",
        {"request": request, "user": None, "business": business, "error": None},
    )


@router.post("/{business_key}/register")
async def portal_register(
    request: Request,
    business_key: str,
    db: Session = Depends(get_db),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    zip_code: str = Form(""),
):
    business = get_business_by_slug_or_id(db, business_key)
    if not business:
        return RedirectResponse("/portal", status_code=303)
    try:
        account = register_customer_account(
            db,
            business,
            name=name,
            email=email,
            password=password,
            phone=phone or None,
            address=address or None,
            zip_code=zip_code or None,
        )
    except ValueError as exc:
        return request.app.state.templates.TemplateResponse(
            request,
            "portal/register.html",
            {"request": request, "user": None, "business": business, "error": str(exc)},
            status_code=400,
        )
    request.session.pop("user_id", None)
    request.session.pop("user", None)
    request.session[_SESSION_KEY] = account.id
    return RedirectResponse("/portal/schedule", status_code=303)


@router.get("/{business_key}/login")
async def portal_login_page(
    request: Request,
    business_key: str,
    db: Session = Depends(get_db),
):
    business = get_business_by_slug_or_id(db, business_key)
    if not business:
        return RedirectResponse("/portal", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request,
        "portal/login.html",
        {"request": request, "user": None, "business": business, "error": None},
    )


@router.post("/{business_key}/login")
async def portal_login(
    request: Request,
    business_key: str,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
):
    business = get_business_by_slug_or_id(db, business_key)
    if not business:
        return RedirectResponse("/portal", status_code=303)
    account = authenticate_customer_account(db, business, email, password)
    if not account:
        return request.app.state.templates.TemplateResponse(
            request,
            "portal/login.html",
            {
                "request": request,
                "user": None,
                "business": business,
                "error": "Invalid email or password",
            },
            status_code=400,
        )
    request.session.pop("user_id", None)
    request.session.pop("user", None)
    request.session[_SESSION_KEY] = account.id
    return RedirectResponse("/portal/schedule", status_code=303)


@router.post("/logout")
async def portal_logout(request: Request):
    request.session.pop(_SESSION_KEY, None)
    return RedirectResponse("/portal", status_code=303)


@router.get("/schedule")
async def portal_schedule(
    request: Request,
    db: Session = Depends(get_db),
    account: CustomerAccount = Depends(get_current_portal_account),
):
    customer = account.customer
    eligibility = can_self_schedule(db, account.user_id, customer)
    packages = list_packages(db, account.user_id, active_only=True)
    past = past_services_for_customer(db, account.user_id, customer.id)
    crews = [c for c in list_crews(db, account.user_id, active_only=True) if c.is_bookable_online]
    return request.app.state.templates.TemplateResponse(
        request,
        "portal/schedule.html",
        {
            "request": request,
            "user": None,
            "account": account,
            "customer": customer,
            "business": account.user,
            "eligibility": eligibility,
            "packages": packages,
            "past_services": past,
            "crews": crews,
            "error": None,
            "message": None,
        },
    )


@router.post("/estimate")
async def portal_estimate(
    request: Request,
    db: Session = Depends(get_db),
    account: CustomerAccount = Depends(get_current_portal_account),
    package_id: int = Form(...),
):
    customer = account.customer
    try:
        estimate = instant_estimate(
            db,
            account.user_id,
            package_id=package_id,
            zip_code=customer.zip_code,
            neighborhood=customer.neighborhood,
        )
    except ValueError as exc:
        ctx = _schedule_context(db, account, error=str(exc))
        ctx["request"] = request
        return request.app.state.templates.TemplateResponse(
            request,
            "portal/schedule.html",
            ctx,
            status_code=400,
        )
    ctx = _schedule_context(db, account)
    ctx["request"] = request
    ctx["estimate"] = estimate
    ctx["message"] = (
        f"Estimated ${estimate.amount:.2f} for {estimate.package_name}. "
        f"{estimate.reason}"
    )
    return request.app.state.templates.TemplateResponse(
        request,
        "portal/schedule.html",
        ctx,
    )


def _schedule_context(db: Session, account: CustomerAccount, error: str | None = None) -> dict:
    customer = account.customer
    return {
        "request": None,  # filled by caller
        "user": None,
        "account": account,
        "customer": customer,
        "business": account.user,
        "eligibility": can_self_schedule(db, account.user_id, customer),
        "packages": list_packages(db, account.user_id, active_only=True),
        "past_services": past_services_for_customer(db, account.user_id, customer.id),
        "crews": [
            c for c in list_crews(db, account.user_id, active_only=True) if c.is_bookable_online
        ],
        "error": error,
        "message": None,
    }


@router.get("/slots")
async def portal_slots(
    request: Request,
    db: Session = Depends(get_db),
    account: CustomerAccount = Depends(get_current_portal_account),
    crew_id: int = Query(...),
    day: str = Query(""),
):
    customer = account.customer
    eligibility = can_self_schedule(db, account.user_id, customer)
    if not eligibility.can_schedule or not eligibility.price:
        return request.app.state.templates.TemplateResponse(
            request,
            "portal/slots.html",
            {
                "request": request,
                "user": None,
                "account": account,
                "slots": [],
                "error": eligibility.reason,
                "crew_id": crew_id,
                "day": day,
                "duration_minutes": None,
            },
        )

    crews = {c.id: c for c in list_crews(db, account.user_id, active_only=True)}
    crew = crews.get(crew_id)
    if not crew or not crew.is_bookable_online:
        return request.app.state.templates.TemplateResponse(
            request,
            "portal/slots.html",
            {
                "request": request,
                "user": None,
                "account": account,
                "slots": [],
                "error": "Crew not available.",
                "crew_id": crew_id,
                "day": day,
                "duration_minutes": None,
            },
        )

    try:
        day_date = datetime.strptime(day, "%Y-%m-%d").date() if day else date.today()
    except ValueError:
        day_date = date.today()

    try:
        estimate = resolve_duration(db, account.user_id, crew, eligibility.price, customer)
    except DurationError as exc:
        return request.app.state.templates.TemplateResponse(
            request,
            "portal/slots.html",
            {
                "request": request,
                "user": None,
                "account": account,
                "slots": [],
                "error": str(exc),
                "crew_id": crew_id,
                "day": day_date.isoformat(),
                "duration_minutes": None,
            },
        )

    slots = available_slots(db, account.user_id, crew_id, day_date, estimate.minutes)
    return request.app.state.templates.TemplateResponse(
        request,
        "portal/slots.html",
        {
            "request": request,
            "user": None,
            "account": account,
            "slots": slots,
            "error": None,
            "crew_id": crew_id,
            "crew_name": crew.name,
            "day": day_date.isoformat(),
            "duration_minutes": estimate.minutes,
            "price": eligibility.price,
            "prev_day": (day_date - timedelta(days=1)).isoformat(),
            "next_day": (day_date + timedelta(days=1)).isoformat(),
        },
    )


@router.post("/book")
async def portal_book(
    request: Request,
    db: Session = Depends(get_db),
    account: CustomerAccount = Depends(get_current_portal_account),
    crew_id: int = Form(...),
    starts_at: str = Form(...),
):
    customer = account.customer
    eligibility = can_self_schedule(db, account.user_id, customer)
    if not eligibility.can_schedule or not eligibility.price:
        return RedirectResponse("/portal/schedule", status_code=303)

    settings = get_scheduling_settings(db, account.user_id)
    tz = ZoneInfo(settings.timezone or "America/Denver")
    try:
        start = datetime.fromisoformat(starts_at)
    except ValueError:
        return RedirectResponse("/portal/schedule", status_code=303)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)

    try:
        booking = await create_booking(
            db,
            account.user_id,
            crew_id=crew_id,
            customer_id=customer.id,
            price=eligibility.price,
            starts_at=start,
            quote_id=eligibility.quote_id,
            customer_name=customer.name,
            address=customer.address,
            phone=customer.phone,
            write_apple=True,
        )
    except BookingError as exc:
        ctx = _schedule_context(db, account, error=str(exc))
        ctx["request"] = request
        return request.app.state.templates.TemplateResponse(
            request,
            "portal/schedule.html",
            ctx,
            status_code=400,
        )

    return request.app.state.templates.TemplateResponse(
        request,
        "portal/confirmed.html",
        {
            "request": request,
            "user": None,
            "account": account,
            "booking": booking,
            "business": account.user,
        },
    )
