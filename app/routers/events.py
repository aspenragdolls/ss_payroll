from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import quote
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
    delete_event_for_user,
    fetch_events_for_user,
    get_active_connection,
    get_event_for_user,
    update_event_for_user,
)
from app.services.customer_service import (
    get_customer,
    get_customer_by_calendar_uid,
    suggest_customers,
    upsert_customer_from_event,
)
from app.services.job_timer_service import (
    JobTimerError,
    finish_job_for_event,
    job_timer_view,
    start_job_for_event,
)
from app.services.event_format import (
    CLASSIFICATIONS,
    SERVICE_SCOPES,
    build_event_description,
    build_event_title,
)
from app.services.event_parse import parse_event_for_app
from app.services.openrouter_job_parser import safe_decimal

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


def _resolve_event_times(starts_at: str, ends_at: str) -> tuple[datetime | None, datetime | None, str | None]:
    """Parse start/end; if end blank or invalid, default to start + 1 hour same day."""
    start = _parse_local_datetime(starts_at)
    if not start:
        return None, None, "Start date and time are required."
    end = _parse_local_datetime(ends_at)
    if not end:
        end = start + timedelta(hours=1)
    if end <= start:
        end = start + timedelta(hours=1)
    return start, end, None


def _to_datetime_local(value: datetime | None) -> str:
    if not value:
        return ""
    local = value.astimezone(_LOCAL_TZ) if value.tzinfo else value.replace(tzinfo=_LOCAL_TZ)
    return local.strftime("%Y-%m-%dT%H:%M")


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


def _values_from_parsed(parsed: dict, customer_id: str = "") -> dict:
    return {
        "customer_id": customer_id,
        "customer_name": parsed["customer_name"],
        "address": parsed["address"],
        "phone": parsed["phone"],
        "price": parsed["price"],
        "classification": parsed["classification"],
        "service_scope": parsed["service_scope"],
        "free_note": parsed["free_note"],
        "starts_at": _to_datetime_local(parsed["starts_at"]),
        "ends_at": _to_datetime_local(parsed["ends_at"]),
        "title_preview": build_event_title(parsed["customer_name"], safe_decimal(parsed["price"])),
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


def _job_timer_for_uid(db: Session, user_id: int, uid: str | None):
    if not uid:
        return job_timer_view(None)
    return job_timer_view(get_customer_by_calendar_uid(db, user_id, uid))


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
    deleted: bool = False,
    job_timer=None,
    job_message: str | None = None,
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
        "deleted": deleted,
        "job_timer": job_timer if job_timer is not None else job_timer_view(None),
        "job_message": job_message,
    }


@router.get("/events")
async def calendar_viewer(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = get_active_connection(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "events/calendar.html",
        {
            "request": request,
            "user": user,
            "connected": conn is not None,
            "calendar_name": conn.calendar_id if conn else "Work",
        },
    )


@router.get("/api/events")
async def list_events_api(
    start: str = Query(""),
    end: str = Query(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return JSONResponse({"error": "start and end must be YYYY-MM-DD"}, status_code=400)
    if end_date < start_date:
        return JSONResponse({"error": "end must be on or after start"}, status_code=400)
    # Cap range to keep CalDAV queries bounded
    if (end_date - start_date).days > 400:
        return JSONResponse({"error": "range too large"}, status_code=400)

    conn = get_active_connection(db, user.id)
    if not conn:
        return JSONResponse({"events": [], "connected": False})

    try:
        events = await fetch_events_for_user(db, user.id, start_date, end_date)
    except CalendarFetchError as exc:
        return JSONResponse({"error": str(exc), "events": [], "connected": True}, status_code=502)

    payload = []
    for event in events:
        start_local = event.start.astimezone(_LOCAL_TZ) if event.start.tzinfo else event.start.replace(tzinfo=_LOCAL_TZ)
        end_local = event.end.astimezone(_LOCAL_TZ) if event.end.tzinfo else event.end.replace(tzinfo=_LOCAL_TZ)
        payload.append(
            {
                "id": event.event_id,
                "title": event.title,
                "location": event.location or "",
                "start": start_local.isoformat(),
                "end": end_local.isoformat(),
            }
        )
    return JSONResponse({"events": payload, "connected": True})


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
            job_timer=job_timer_view(None),
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

    start, end, time_error = _resolve_event_times(starts_at, ends_at)
    if time_error:
        return fail(time_error)

    ticket = safe_decimal(price)
    cid = None
    if customer_id.strip().isdigit():
        cid = int(customer_id.strip())
        if not get_customer(db, user.id, cid):
            cid = None

    try:
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
            calendar_event_uid=event.event_id,
            next_service_due=start.date(),
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
    job: str | None = None,
    job_error: str | None = None,
):
    conn = get_active_connection(db, user.id)
    values = _form_defaults()
    error = None if conn else "Apple Calendar is not connected."
    linked = get_customer_by_calendar_uid(db, user.id, uid) if conn else None
    if conn:
        try:
            event = await get_event_for_user(db, user.id, uid)
            if event:
                parsed = parse_event_for_app(event)
                customer_id = str(linked.id) if linked else ""
                if not customer_id:
                    matches = suggest_customers(db, user.id, parsed["customer_name"], limit=1)
                    if (
                        matches
                        and matches[0].name.strip().lower()
                        == parsed["customer_name"].strip().lower()
                    ):
                        customer_id = str(matches[0].id)
                values = _values_from_parsed(parsed, customer_id=customer_id)
            else:
                error = "Event not found in Apple Calendar."
        except (CalendarFetchError, CalendarWriteError) as exc:
            error = str(exc)

    job_message = None
    if job == "started":
        job_message = "Job started. Hit Finish when the crew is done."
    elif job == "finished":
        timer = job_timer_view(linked)
        job_message = (
            f"Job finished. Duration: {timer.duration_label}."
            if timer.duration_label
            else "Job finished."
        )
    elif job_error:
        error = job_error

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
            error=error,
            saved=saved == "1",
            job_timer=job_timer_view(linked),
            job_message=job_message,
        ),
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
                job_timer=_job_timer_for_uid(db, user.id, uid),
            ),
        )

    name = customer_name.strip()
    if not name:
        return fail("Customer name is required.")

    start, end, time_error = _resolve_event_times(starts_at, ends_at)
    if time_error:
        return fail(time_error)

    if classification == "windows" and service_scope not in {key for key, _ in SERVICE_SCOPES}:
        return fail("Choose a service scope for windows.")

    ticket = safe_decimal(price)
    cid = int(customer_id) if customer_id.strip().isdigit() else None
    if cid and not get_customer(db, user.id, cid):
        cid = None
    if not cid:
        linked = get_customer_by_calendar_uid(db, user.id, uid)
        if linked:
            cid = linked.id

    try:
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
            calendar_event_uid=uid,
            next_service_due=start.date(),
        )
    except (CalendarWriteError, CalendarFetchError) as exc:
        return fail(str(exc))

    return RedirectResponse("/events?saved=1", status_code=303)


@router.post("/events/{uid}/job/start")
async def start_job_timer(
    uid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        start_job_for_event(db, user.id, uid)
    except JobTimerError as exc:
        return RedirectResponse(
            f"/events/{uid}/edit?job_error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(f"/events/{uid}/edit?job=started", status_code=303)


@router.post("/events/{uid}/job/finish")
async def finish_job_timer(
    uid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        finish_job_for_event(db, user.id, uid)
    except JobTimerError as exc:
        return RedirectResponse(
            f"/events/{uid}/edit?job_error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(f"/events/{uid}/edit?job=finished", status_code=303)


@router.post("/events/{uid}/delete")
async def delete_event(
    request: Request,
    uid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = get_active_connection(db, user.id)
    if not conn:
        return RedirectResponse("/events", status_code=303)

    try:
        await delete_event_for_user(db, user.id, uid)
    except (CalendarWriteError, CalendarFetchError):
        return RedirectResponse(f"/events/{uid}/edit?error=delete", status_code=303)

    customer = get_customer_by_calendar_uid(db, user.id, uid)
    if customer:
        customer.calendar_event_uid = None
        customer.next_service_due = None
        if customer.status in {"scheduled", "estimate"}:
            customer.status = "active"
            customer.is_active = True
        db.commit()

    return RedirectResponse("/events?deleted=1", status_code=303)
