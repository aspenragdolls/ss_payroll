from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.customer_service import SERVICE_TYPES, get_customer
from app.services.quote_service import (
    QUOTE_STATUSES,
    accept_quote,
    create_package,
    create_quote,
    get_package,
    get_quote,
    list_packages,
    list_quotes,
    update_package,
    update_quote_status,
)
from sqlalchemy import select

from app.models.customer import Customer

router = APIRouter(tags=["packages_quotes"])


def _customer_options(db: Session, user_id: int) -> list[Customer]:
    return list(
        db.scalars(
            select(Customer)
            .where(Customer.user_id == user_id, Customer.is_active.is_(True))
            .order_by(Customer.name)
            .limit(500)
        )
    )


def _parse_decimal(value: str) -> Decimal | None:
    if not value or not str(value).strip():
        return None
    try:
        return Decimal(str(value).strip().replace("$", "").replace(",", ""))
    except InvalidOperation:
        return None


# ---- Packages ----

@router.get("/packages")
async def packages_list(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    packages = list_packages(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "packages/list.html",
        {"request": request, "user": user, "packages": packages},
    )


@router.get("/packages/new")
async def packages_new(request: Request, user: User = Depends(get_current_user)):
    return request.app.state.templates.TemplateResponse(
        request,
        "packages/form.html",
        {
            "request": request,
            "user": user,
            "package": None,
            "service_types": SERVICE_TYPES,
            "error": None,
        },
    )


@router.post("/packages/new")
async def packages_create(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    service_type: str = Form(...),
    base_price: str = Form(...),
    description: str = Form(""),
    is_active: str = Form("on"),
):
    price = _parse_decimal(base_price)
    if price is None or price <= 0:
        return request.app.state.templates.TemplateResponse(
            request,
            "packages/form.html",
            {
                "request": request,
                "user": user,
                "package": None,
                "service_types": SERVICE_TYPES,
                "error": "Enter a valid base price.",
            },
            status_code=400,
        )
    create_package(
        db,
        user.id,
        name=name,
        service_type=service_type,
        base_price=price,
        description=description or None,
        is_active=is_active == "on",
    )
    return RedirectResponse("/packages", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/packages/{package_id}/edit")
async def packages_edit(
    request: Request,
    package_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    package = get_package(db, user.id, package_id)
    if not package:
        return RedirectResponse("/packages", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request,
        "packages/form.html",
        {
            "request": request,
            "user": user,
            "package": package,
            "service_types": SERVICE_TYPES,
            "error": None,
        },
    )


@router.post("/packages/{package_id}/edit")
async def packages_update(
    request: Request,
    package_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    service_type: str = Form(...),
    base_price: str = Form(...),
    description: str = Form(""),
    is_active: str = Form(""),
):
    package = get_package(db, user.id, package_id)
    if not package:
        return RedirectResponse("/packages", status_code=303)
    price = _parse_decimal(base_price)
    if price is None or price <= 0:
        return request.app.state.templates.TemplateResponse(
            request,
            "packages/form.html",
            {
                "request": request,
                "user": user,
                "package": package,
                "service_types": SERVICE_TYPES,
                "error": "Enter a valid base price.",
            },
            status_code=400,
        )
    update_package(
        db,
        package,
        name=name.strip(),
        service_type=service_type,
        base_price=price,
        description=description or None,
        is_active=is_active == "on",
    )
    return RedirectResponse(f"/packages/{package_id}/edit?saved=1", status_code=303)


# ---- Quotes ----

@router.get("/quotes")
async def quotes_list(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quotes = list_quotes(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "quotes/list.html",
        {"request": request, "user": user, "quotes": quotes},
    )


@router.get("/quotes/new")
async def quotes_new(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customers = _customer_options(db, user.id)
    packages = list_packages(db, user.id, active_only=True)
    return request.app.state.templates.TemplateResponse(
        request,
        "quotes/form.html",
        {
            "request": request,
            "user": user,
            "customers": customers,
            "packages": packages,
            "statuses": QUOTE_STATUSES,
            "error": None,
        },
    )


@router.post("/quotes/new")
async def quotes_create(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    customer_id: int = Form(...),
    package_id: str = Form(""),
    amount: str = Form(...),
    status_value: str = Form("draft"),
    notes: str = Form(""),
):
    if not get_customer(db, user.id, customer_id):
        return RedirectResponse("/quotes/new", status_code=303)
    price = _parse_decimal(amount)
    if price is None or price <= 0:
        customers = _customer_options(db, user.id)
        packages = list_packages(db, user.id, active_only=True)
        return request.app.state.templates.TemplateResponse(
            request,
            "quotes/form.html",
            {
                "request": request,
                "user": user,
                "customers": customers,
                "packages": packages,
                "statuses": QUOTE_STATUSES,
                "error": "Enter a valid amount.",
            },
            status_code=400,
        )
    pkg = int(package_id) if package_id.strip().isdigit() else None
    create_quote(
        db,
        user.id,
        customer_id=customer_id,
        package_id=pkg,
        amount=price,
        status=status_value,
        notes=notes or None,
    )
    return RedirectResponse("/quotes", status_code=303)


@router.post("/quotes/{quote_id}/accept")
async def quotes_accept(
    quote_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        accept_quote(db, user.id, quote_id)
    except ValueError:
        pass
    return RedirectResponse("/quotes", status_code=303)


@router.post("/quotes/{quote_id}/status")
async def quotes_set_status(
    quote_id: int,
    status_value: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quote = get_quote(db, user.id, quote_id)
    if quote:
        try:
            update_quote_status(db, quote, status_value)
        except ValueError:
            pass
    return RedirectResponse("/quotes", status_code=303)
