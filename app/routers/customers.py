from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.customer_service import (
    CUSTOMER_STATUSES,
    LAST_SERVICE_OPTIONS,
    LEAD_SOURCES,
    NEIGHBORHOODS,
    NEXT_DUE_OPTIONS,
    REVENUE_METRIC_OPTIONS,
    SERVICE_TYPES,
    CustomerListFilters,
    create_customer,
    customer_status_label,
    export_customers_csv,
    get_customer,
    get_customer_job_history,
    label_for,
    list_customers,
    parse_services,
    update_customer,
)

router = APIRouter(prefix="/customers", tags=["customers"])


def _filters_from_query(
    q: str = "",
    neighborhood: str = "",
    zip_code: str = "",
    radius_lat: str = "",
    radius_lng: str = "",
    radius_miles: str = "",
    status_filter: str = "",
    last_service: str = "",
    revenue_metric: str = "",
    revenue_min: str = "",
    revenue_max: str = "",
    service: str = "",
    never_service: str = "",
    lead_source: str = "",
    next_due: str = "",
) -> CustomerListFilters:
    return CustomerListFilters(
        q=q,
        neighborhood=neighborhood,
        zip_code=zip_code,
        radius_lat=radius_lat,
        radius_lng=radius_lng,
        radius_miles=radius_miles,
        status=status_filter,
        last_service=last_service,
        revenue_metric=revenue_metric,
        revenue_min=revenue_min,
        revenue_max=revenue_max,
        service=service,
        never_service=never_service,
        lead_source=lead_source,
        next_due=next_due,
    )


def _filter_context(filters: CustomerListFilters) -> dict:
    return {
        "filters": filters,
        "statuses": CUSTOMER_STATUSES,
        "neighborhoods": NEIGHBORHOODS,
        "lead_sources": LEAD_SOURCES,
        "service_types": SERVICE_TYPES,
        "last_service_options": LAST_SERVICE_OPTIONS,
        "revenue_metric_options": REVENUE_METRIC_OPTIONS,
        "next_due_options": NEXT_DUE_OPTIONS,
    }


def _parse_optional_date(raw: str | None) -> date | None:
    if not raw or not raw.strip():
        return None
    return date.fromisoformat(raw.strip())


def _parse_optional_decimal(raw: str | None) -> Decimal | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None


def _form_options() -> dict:
    return {
        "statuses": CUSTOMER_STATUSES,
        "neighborhoods": NEIGHBORHOODS,
        "lead_sources": LEAD_SOURCES,
        "service_types": SERVICE_TYPES,
    }


@router.get("")
async def customers_list(
    request: Request,
    q: str = "",
    neighborhood: str = "",
    zip_code: str = "",
    radius_lat: str = "",
    radius_lng: str = "",
    radius_miles: str = "",
    status_filter: str = Query("", alias="status"),
    last_service: str = "",
    revenue_metric: str = "",
    revenue_min: str = "",
    revenue_max: str = "",
    service: str = "",
    never_service: str = "",
    lead_source: str = "",
    next_due: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = _filters_from_query(
        q=q,
        neighborhood=neighborhood,
        zip_code=zip_code,
        radius_lat=radius_lat,
        radius_lng=radius_lng,
        radius_miles=radius_miles,
        status_filter=status_filter,
        last_service=last_service,
        revenue_metric=revenue_metric,
        revenue_min=revenue_min,
        revenue_max=revenue_max,
        service=service,
        never_service=never_service,
        lead_source=lead_source,
        next_due=next_due,
    )
    items = list_customers(db, user.id, filters=filters)
    return request.app.state.templates.TemplateResponse(
        request,
        "customers/list.html",
        {
            "request": request,
            "user": user,
            "items": items,
            "status_label": label_for,
            "customer_status_label": customer_status_label,
            **_filter_context(filters),
        },
    )


@router.get("/export")
async def customers_export(
    q: str = "",
    neighborhood: str = "",
    zip_code: str = "",
    radius_lat: str = "",
    radius_lng: str = "",
    radius_miles: str = "",
    status_filter: str = Query("", alias="status"),
    last_service: str = "",
    revenue_metric: str = "",
    revenue_min: str = "",
    revenue_max: str = "",
    service: str = "",
    never_service: str = "",
    lead_source: str = "",
    next_due: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = _filters_from_query(
        q=q,
        neighborhood=neighborhood,
        zip_code=zip_code,
        radius_lat=radius_lat,
        radius_lng=radius_lng,
        radius_miles=radius_miles,
        status_filter=status_filter,
        last_service=last_service,
        revenue_metric=revenue_metric,
        revenue_min=revenue_min,
        revenue_max=revenue_max,
        service=service,
        never_service=never_service,
        lead_source=lead_source,
        next_due=next_due,
    )
    items = list_customers(db, user.id, filters=filters)
    csv_body = export_customers_csv(items, respect_marketing_prefs=True)
    filename = f"customers-{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/new")
async def customers_new(
    request: Request,
    user: User = Depends(get_current_user),
):
    return request.app.state.templates.TemplateResponse(
        request,
        "customers/form.html",
        {
            "request": request,
            "user": user,
            "customer": None,
            "error": None,
            "selected_services": [],
            **_form_options(),
        },
    )


@router.post("/new")
async def customers_create(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    notes: str = Form(""),
    aliases: str = Form(""),
    status_value: str = Form("active", alias="status"),
    neighborhood: str = Form(""),
    zip_code: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    lead_source: str = Form(""),
    next_service_due: str = Form(""),
    services: list[str] = Form(default=[]),
    allow_email: str | None = Form(None),
    allow_sms: str | None = Form(None),
    allow_mail: str | None = Form(None),
    do_not_contact: str | None = Form(None),
):
    if not name.strip():
        return request.app.state.templates.TemplateResponse(
            request,
            "customers/form.html",
            {
                "request": request,
                "user": user,
                "customer": None,
                "error": "Name is required.",
                "selected_services": parse_services(services),
                **_form_options(),
            },
            status_code=400,
        )
    customer = create_customer(
        db,
        user.id,
        name=name,
        address=address,
        phone=phone,
        email=email,
        notes=notes,
        aliases=aliases,
        status=status_value,
        neighborhood=neighborhood,
        zip_code=zip_code,
        latitude=_parse_optional_decimal(latitude),
        longitude=_parse_optional_decimal(longitude),
        lead_source=lead_source or None,
        services=services,
        next_service_due=_parse_optional_date(next_service_due),
        allow_email=allow_email == "on",
        allow_sms=allow_sms == "on",
        allow_mail=allow_mail == "on",
        do_not_contact=do_not_contact == "on",
    )
    return RedirectResponse(
        f"/customers/{customer.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{customer_id}")
async def customers_detail(
    request: Request,
    customer_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = get_customer(db, user.id, customer_id)
    if not customer:
        return RedirectResponse("/customers", status_code=status.HTTP_303_SEE_OTHER)
    history = get_customer_job_history(db, user.id, customer_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "customers/detail.html",
        {
            "request": request,
            "user": user,
            "customer": customer,
            "history": history,
            "status_label": customer_status_label(customer),
            "lead_source_label": label_for(LEAD_SOURCES, customer.lead_source),
            "service_labels": [
                label_for(SERVICE_TYPES, key) for key in (customer.services or [])
            ],
        },
    )


@router.get("/{customer_id}/edit")
async def customers_edit(
    request: Request,
    customer_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = get_customer(db, user.id, customer_id)
    if not customer:
        return RedirectResponse("/customers", status_code=status.HTTP_303_SEE_OTHER)
    return request.app.state.templates.TemplateResponse(
        request,
        "customers/form.html",
        {
            "request": request,
            "user": user,
            "customer": customer,
            "error": None,
            "selected_services": customer.services or [],
            **_form_options(),
        },
    )


@router.post("/{customer_id}/edit")
async def customers_update(
    request: Request,
    customer_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    notes: str = Form(""),
    aliases: str = Form(""),
    status_value: str = Form("active", alias="status"),
    neighborhood: str = Form(""),
    zip_code: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    lead_source: str = Form(""),
    next_service_due: str = Form(""),
    services: list[str] = Form(default=[]),
    allow_email: str | None = Form(None),
    allow_sms: str | None = Form(None),
    allow_mail: str | None = Form(None),
    do_not_contact: str | None = Form(None),
):
    customer = get_customer(db, user.id, customer_id)
    if not customer:
        return RedirectResponse("/customers", status_code=status.HTTP_303_SEE_OTHER)
    if not name.strip():
        return request.app.state.templates.TemplateResponse(
            request,
            "customers/form.html",
            {
                "request": request,
                "user": user,
                "customer": customer,
                "error": "Name is required.",
                "selected_services": parse_services(services),
                **_form_options(),
            },
            status_code=400,
        )
    update_customer(
        db,
        customer,
        name=name.strip(),
        address=address.strip() or None,
        phone=phone.strip() or None,
        email=email.strip() or None,
        notes=notes.strip() or None,
        aliases=aliases.strip() or None,
        status=status_value,
        neighborhood=neighborhood.strip() or None,
        zip_code=zip_code.strip() or None,
        latitude=_parse_optional_decimal(latitude),
        longitude=_parse_optional_decimal(longitude),
        lead_source=lead_source.strip() or None,
        services=services,
        next_service_due=_parse_optional_date(next_service_due),
        allow_email=allow_email == "on",
        allow_sms=allow_sms == "on",
        allow_mail=allow_mail == "on",
        do_not_contact=do_not_contact == "on",
    )
    return RedirectResponse(
        f"/customers/{customer_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
