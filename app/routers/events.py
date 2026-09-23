from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.calendar_service import (
    CalendarFetchError,
    CalendarWriteError,
    create_event_for_user,
    get_active_connection,
    get_event_for_user,
    update_event_for_user,
)
from app.services.customer_service import (
    get_customer,
    suggest_customers,
    upsert_customer_from_event,
)
from app.services.event_format import (
    CLASSIFICATIONS,
    SERVICE_SCOPES,
    build_event_description,
    build_event_title,
    service_description_line,
)
from app.services.openrouter_job_parser import safe_decimal
from app.services.schemas import RawCalendarEvent

router = APIRouter(tags=["events"])

_LOCAL_TZ = ZoneInfo("America/Denver")


def _parse_local_datetime(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        if "T" in value:
            dt = datetime.fromisoformat(value)
        else:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_LOCAL_TZ)
    return dt.astimezone(_LOCAL_TZ)


def _to_datetime_local(value: datetime | None) -> str:
    if not value:
        return ""
    local = value.astimezone(_LOCAL_TZ) if value.tzinfo else value.replace(tzinfo=_LOCAL_TZ)
    return local.strftime("%Y-%m-%dT%H:%M")


def _guess_classification_from_event(event: RawCalendarEvent) -> tuple[str, str | None]:
    text = f"{event.description or ''}\n{event.title or ''}".lower()
    if "estimate" in text or "quote" in text:
        return "estimate", None
    if "gutter" in text:
        return "gutters", None
    scope_map = [
        ("inside and outside", "inside_and_outside"),
        ("outside only", "outside_only"),
        ("inside only", "inside_only"),
        ("partial", "partial"),
    ]
    for needle, key in scope_map:
        if needle in text:
            return "windows", key
    return "windows", "inside_and_outside"


def _parse_title_name_price(title: str) -> tuple[str, str]:
    import re

    match = re.match(r"^(.*?)\s*\(\s*\$\s*([\d.,]+)\s*\)\s*$", (title or "").strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return (title or "").strip(), ""


def _form_defaults() -> dict:
    now = datetime.now(_LOCAL_TZ).replace(minute=0, second=0, microsecond=0)
    if now.hour < 8:
        now = now.replace(hour=9)
    end = now + timedelta(hours=1)
    return {
        "customer_id": "",
        "customer_name": "",
        "address": "",
        "phone": "",
        "price": "",
        "classification": "windows",
        "service_scope": "inside_and_outside",
        "free_note": "",
        "starts_at": _to_datetime_local(now),
        "ends_at": _to_datetime_local(end),
        "title_preview": "",
    }


@router.get("/api/customers/suggest")
async def customers_suggest(
    q: str = Query(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = suggest_customers(db, user.id, q)
    return JSONResponse(
        [
            {
                "id": c.id,
                "name": c.name,
                "address": c.address or "",
                "phone": c.phone or "",
                "usual_price": str(c.usual_price) if c.usual_price is not None else "",
                "status": c.status,
                "service_scope": c.service_scope or "",
                "services": c.services or [],
            }
            for c in rows
        ]
    )


def _template_context(
    request: Request,
    user: User,
    *,
    values: dict,
    uid: str | None,
    calendar_name: str,
    connected: bool,
    error: str | None = None,
    saved: bool = False,
) -> dict:
    return {
        "request": request,
        "user": user,
        "values": values,
        "error": error,
        "uid": uid,
        "calendar_name": calendar_name,
        "classifications": CLASSIFICATIONS,
        "service_scopes": SERVICE_SCOPES,
        "connected": connected,
        "saved": saved,
    }


@router.get("/events/new")
async def new_event_form(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = get_active_connection(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "events/form.html",
        _template_context(
            request,
            user,
            values=_form_defaults(),
            uid=None,
            calendar_name=conn.calendar_id if conn else "Work",
            connected=conn is not None,
            error=None
            if conn
            else "Apple Calendar is not connected. Connect it under Settings → Calendar.",
        ),
    )


@router.post("/events/new")
async def create_event(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    customer_id: str = Form(""),
    customer_name: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    price: str = Form(""),
    classification: str = Form("windows"),
    service_scope: str = Form(""),
    free_note: str = Form(""),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
):
    conn = get_active_connection(db, user.id)
    values = {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "address": address,
        "phone": phone,
        "price": price,
        "classification": classification,
        "service_scope": service_scope,
        "free_note": free_note,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "title_preview": build_event_title(customer_name, safe_decimal(price)),
    }

    def fail(message: str):
        return request.app.state.templates.TemplateResponse(
            request,
            "events/form.html",
            _template_context(
                request,
                user,
                values=values,
                uid=None,
                calendar_name=conn.calendar_id if conn else "Work",
                connected=conn is not None,
                error=message,
            ),
        )

    name = customer_name.strip()
    if not name:
        return fail("Customer name is required.")

    if classification not in {key for key, _ in CLASSIFICATIONS}:
        return fail("Choose a valid classification.")

    if classification == "windows" and service_scope not in {key for key, _ in SERVICE_SCOPES}:
        return fail("Choose a service scope for windows.")

    start = _parse_local_datetime(starts_at)
    end = _parse_local_datetime(ends_at)
    if not start or not end:
        return fail("Start and end times are required.")
    if end <= start:
        return fail("End time must be after start time.")

    ticket = safe_decimal(price)
    cid = None
    if customer_id.strip().isdigit():
        cid = int(customer_id.strip())
        if not get_customer(db, user.id, cid):
            cid = None

    try:
        upsert_customer_from_event(
            db,
            user.id,
            customer_id=cid,
            name=name,
            address=address,
            phone=phone,
            classification=classification,
            service_scope=service_scope or None,
            usual_price=ticket,
        )
        event = await create_event_for_user(
            db,
            user.id,
            title=build_event_title(name, ticket),
            description=build_event_description(
                phone,
                classification,
                service_scope or None,
                free_note,
            ),
            location=address.strip(),
            start=start,
            end=end,
        )
    except (CalendarWriteError, CalendarFetchError) as exc:
        return fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        return fail(f"Could not save event: {exc}")

    return RedirectResponse(f"/events/{event.event_id}/edit?saved=1", status_code=303)


@router.get("/events/{uid}/edit")
async def edit_event_form(
    request: Request,
    uid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    saved: str | None = None,
):
    conn = get_active_connection(db, user.id)
    values = _form_defaults()
    error = None if conn else "Apple Calendar is not connected."
    if conn:
        try:
            event = await get_event_for_user(db, user.id, uid)
            if event:
                name, price = _parse_title_name_price(event.title)
                classification, scope = _guess_classification_from_event(event)
                phone = ""
                free_note = ""
                desc_lines = (event.description or "").splitlines()
                if desc_lines:
                    first = desc_lines[0].strip()
                    if any(ch.isdigit() for ch in first) and len(first) <= 24:
                        phone = first
                        rest = "\n".join(desc_lines[1:]).strip()
                    else:
                        rest = (event.description or "").strip()
                    service_line = service_description_line(classification, scope)
                    if rest.startswith(service_line):
                        free_note = rest[len(service_line) :].strip()
                    elif "\n\n" in rest:
                        parts = rest.split("\n\n", 1)
                        free_note = parts[1].strip() if len(parts) > 1 else ""
                    else:
                        # Drop the service line if present as a single line
                        lines = [ln for ln in rest.splitlines() if ln.strip()]
                        if lines and lines[0].strip().lower() == service_line.lower():
                            free_note = "\n".join(lines[1:]).strip()
                        else:
                            free_note = rest
                values = {
                    "customer_id": "",
                    "customer_name": name,
                    "address": event.location or "",
                    "phone": phone,
                    "price": price,
                    "classification": classification,
                    "service_scope": scope or "inside_and_outside",
                    "free_note": free_note,
                    "starts_at": _to_datetime_local(event.start),
                    "ends_at": _to_datetime_local(event.end),
                    "title_preview": event.title,
                }
                matches = suggest_customers(db, user.id, name, limit=1)
                if matches and matches[0].name.strip().lower() == name.strip().lower():
                    values["customer_id"] = str(matches[0].id)
            else:
                error = "Event not found in Apple Calendar."
        except (CalendarFetchError, CalendarWriteError) as exc:
            error = str(exc)

    return request.app.state.templates.TemplateResponse(
        request,
        "events/form.html",
        {
            "request": request,
            "user": user,
            "values": values,
            "error": error,
            "uid": uid,
            "calendar_name": conn.calendar_id if conn else "Work",
            "classifications": CLASSIFICATIONS,
            "service_scopes": SERVICE_SCOPES,
            "connected": conn is not None,
            "saved": saved == "1",
        },
    )


@router.post("/events/{uid}/edit")
async def update_event(
    request: Request,
    uid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    customer_id: str = Form(""),
    customer_name: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    price: str = Form(""),
    classification: str = Form("windows"),
    service_scope: str = Form(""),
    free_note: str = Form(""),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
):
    conn = get_active_connection(db, user.id)
    values = {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "address": address,
        "phone": phone,
        "price": price,
        "classification": classification,
        "service_scope": service_scope,
        "free_note": free_note,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "title_preview": build_event_title(customer_name, safe_decimal(price)),
    }

    def fail(message: str):
        return request.app.state.templates.TemplateResponse(
            request,
            "events/form.html",
            _template_context(
                request,
                user,
                values=values,
                uid=uid,
                calendar_name=conn.calendar_id if conn else "Work",
                connected=conn is not None,
                error=message,
            ),
        )

    name = customer_name.strip()
    if not name:
        return fail("Customer name is required.")

    start = _parse_local_datetime(starts_at)
    end = _parse_local_datetime(ends_at)
    if not start or not end or end <= start:
        return fail("Valid start and end times are required.")

    if classification == "windows" and service_scope not in {key for key, _ in SERVICE_SCOPES}:
        return fail("Choose a service scope for windows.")

    ticket = safe_decimal(price)
    cid = int(customer_id) if customer_id.strip().isdigit() else None
    if cid and not get_customer(db, user.id, cid):
        cid = None

    try:
        upsert_customer_from_event(
            db,
            user.id,
            customer_id=cid,
            name=name,
            address=address,
            phone=phone,
            classification=classification,
            service_scope=service_scope or None,
            usual_price=ticket,
        )
        await update_event_for_user(
            db,
            user.id,
            uid,
            title=build_event_title(name, ticket),
            description=build_event_description(
                phone, classification, service_scope or None, free_note
            ),
            location=address.strip(),
            start=start,
            end=end,
        )
    except (CalendarWriteError, CalendarFetchError) as exc:
        return fail(str(exc))

    return RedirectResponse(f"/events/{uid}/edit?saved=1", status_code=303)
