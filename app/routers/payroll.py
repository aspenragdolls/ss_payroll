from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.dependencies import get_current_user
from app.domain.enums import PayType, PayrollStatus, Role
from app.models.payroll import PayrollBatch, PayrollJobResult, PayrollResult
from app.models.user import User
from app.services.calendar_service import CalendarFetchError, fetch_events_for_user, is_calendar_connected
from app.services.job_validation import validate_draft_job
from app.services.openrouter_job_parser import parse_calendar_event, safe_decimal
from app.services.payroll_service import (
    clear_assignments_for_job,
    compute_hours_assigned,
    create_batch,
    create_job_from_draft,
    ensure_editable,
    finalize_batch,
    get_assignments_for_batch,
    get_batch,
    get_job,
    get_jobs_for_batch,
    get_owner_worker,
    list_batches,
    run_calculation,
    save_assignment,
    update_job,
)
from app.services.worker_service import list_workers, workers_with_role
from app.template_utils import job_label

router = APIRouter(prefix="/payroll", tags=["payroll"])


def _enrich_warning_messages(
    warnings: list[dict],
    workers_by_id: dict[str, str],
    jobs_by_id: dict[str, str],
) -> list[dict]:
    enriched: list[dict] = []
    for w in warnings:
        msg = w.get("message", "")
        for wid in sorted(workers_by_id.keys(), key=len, reverse=True):
            msg = msg.replace(f"worker {wid}", f"worker {workers_by_id[wid]}")
        for jid in sorted(jobs_by_id.keys(), key=len, reverse=True):
            label = jobs_by_id[jid]
            msg = msg.replace(f"Job {jid}", label)
            msg = msg.replace(f"job {jid}", label)
        enriched.append({**w, "message": msg})
    return enriched


@router.get("/history")
async def payroll_history(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batches = list_batches(db, user.id, finalized_only=True)
    return request.app.state.templates.TemplateResponse(
        request,
        "payroll/history.html",
        {"request": request, "user": user, "batches": batches},
    )


@router.get("/begin")
async def begin_payroll_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return request.app.state.templates.TemplateResponse(
        request,
        "payroll/begin.html",
        {
            "request": request,
            "user": user,
            "default_date": date.today().isoformat(),
            "calendar_connected": is_calendar_connected(db, user.id),
        },
    )


@router.post("/begin")
async def begin_payroll(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pay_date: str = Form(...),
):
    batch = create_batch(db, user.id, pay_date=date.fromisoformat(pay_date))
    start = date.fromisoformat(pay_date)
    import_error: str | None = None
    try:
        events = await fetch_events_for_user(db, user.id, start, start + timedelta(days=1))
    except CalendarFetchError as exc:
        events = []
        import_error = str(exc)

    for event in events:
        draft = await parse_calendar_event(event)
        draft, flags = validate_draft_job(draft)
        create_job_from_draft(
            db,
            user.id,
            batch.id,
            customer_name=draft.customer_name,
            address=draft.address,
            service_description=draft.service_description,
            ticket_price=safe_decimal(draft.final_ticket_price),
            job_date=draft.job_date,
            source_text=draft.raw_source_text,
            validation_flags=flags,
        )

    redirect_url = f"/payroll/{batch.id}/jobs"
    if import_error:
        redirect_url = f"{redirect_url}?import_error={quote(import_error)}"
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{batch_id}/jobs")
async def review_jobs(
    request: Request,
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    import_error: str | None = None,
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)
    jobs = get_jobs_for_batch(db, user.id, batch_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "payroll/jobs.html",
        {
            "request": request,
            "user": user,
            "batch": batch,
            "jobs": jobs,
            "readonly": batch.status == PayrollStatus.FINALIZED.value,
            "calendar_connected": is_calendar_connected(db, user.id),
            "import_error": import_error,
        },
    )


@router.post("/{batch_id}/jobs/{job_id}/edit")
async def edit_job(
    batch_id: int,
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    customer_name: str = Form(""),
    address: str = Form(""),
    service_description: str = Form(""),
    ticket_price: str = Form(""),
    job_date: str = Form(""),
    review_status: str = Form("pending"),
):
    batch = get_batch(db, user.id, batch_id)
    job = get_job(db, user.id, job_id)
    if not batch or not job or job.payroll_batch_id != batch_id:
        return RedirectResponse(f"/payroll/{batch_id}/jobs", status_code=status.HTTP_303_SEE_OTHER)
    try:
        ensure_editable(batch)
    except PermissionError:
        return RedirectResponse(f"/payroll/{batch_id}/jobs", status_code=status.HTTP_303_SEE_OTHER)

    update_job(
        db,
        job,
        customer_name=customer_name or None,
        address=address or None,
        service_description=service_description or None,
        ticket_price=safe_decimal(ticket_price),
        job_date=date.fromisoformat(job_date) if job_date else None,
        review_status=review_status,
    )
    return RedirectResponse(f"/payroll/{batch_id}/jobs", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{batch_id}/jobs/manual")
async def add_manual_job(
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    customer_name: str = Form(...),
    address: str = Form(""),
    ticket_price: str = Form(...),
    job_date: str = Form(...),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)
    try:
        ensure_editable(batch)
    except PermissionError:
        return RedirectResponse(f"/payroll/{batch_id}/jobs", status_code=status.HTTP_303_SEE_OTHER)

    create_job_from_draft(
        db,
        user.id,
        batch_id,
        customer_name=customer_name,
        address=address or None,
        service_description="Manual entry",
        ticket_price=safe_decimal(ticket_price),
        job_date=date.fromisoformat(job_date),
        source_text="Manual entry",
        validation_flags=[],
    )
    return RedirectResponse(f"/payroll/{batch_id}/jobs", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{batch_id}/assign")
async def assign_workers(
    request: Request,
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)
    jobs = get_jobs_for_batch(db, user.id, batch_id)
    workers = list_workers(db, user.id, active_only=True)
    labor_workers = workers_with_role(workers, Role.LABOR)
    sales_workers = workers_with_role(workers, Role.SALES)
    assignments = get_assignments_for_batch(db, batch_id)
    assignment_map: dict[int, list] = {}
    for a in assignments:
        assignment_map.setdefault(a.job_id, []).append(a)

    return request.app.state.templates.TemplateResponse(
        request,
        "payroll/assign.html",
        {
            "request": request,
            "user": user,
            "batch": batch,
            "jobs": jobs,
            "labor_workers": labor_workers,
            "sales_workers": sales_workers,
            "assignment_map": assignment_map,
            "readonly": batch.status == PayrollStatus.FINALIZED.value,
        },
    )


@router.post("/{batch_id}/assign")
async def save_assignments(
    request: Request,
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)
    try:
        ensure_editable(batch)
    except PermissionError:
        return RedirectResponse(f"/payroll/{batch_id}/assign", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    jobs = get_jobs_for_batch(db, user.id, batch_id)
    workers = {w.id: w for w in list_workers(db, user.id, active_only=True)}

    for job in jobs:
        clear_assignments_for_job(db, job.id)
        labor_ids = form.getlist(f"labor_{job.id}")
        sales_ids = form.getlist(f"sales_{job.id}")

        assigned: dict[int, set[str]] = {}
        for wid in labor_ids:
            if wid.isdigit():
                assigned.setdefault(int(wid), set()).add(Role.LABOR.value)
        for wid in sales_ids:
            if wid.isdigit():
                assigned.setdefault(int(wid), set()).add(Role.SALES.value)

        for worker_id, roles in assigned.items():
            worker = workers.get(worker_id)
            if not worker:
                continue
            pay_type = form.get(f"pay_type_{job.id}_{worker_id}") or worker.labor_pay_type
            tier = form.get(f"tier_{job.id}_{worker_id}") or worker.labor_percentage_tier
            rate_str = form.get(f"rate_{job.id}_{worker_id}") or ""
            rate = safe_decimal(rate_str) if rate_str else worker.hourly_rate
            adj_str = form.get(f"adjustment_{job.id}_{worker_id}") or "0"
            try:
                adjustment = Decimal(adj_str)
            except InvalidOperation:
                adjustment = Decimal("0")

            save_assignment(
                db,
                job.id,
                worker_id,
                sorted(roles),
                effective_pay_type=pay_type if Role.LABOR.value in roles else None,
                effective_percentage_tier=tier if pay_type == PayType.PERCENTAGE.value else None,
                effective_hourly_rate=rate if pay_type == PayType.HOURLY.value else None,
                fixed_adjustment_amount=adjustment,
            )
    db.commit()
    return RedirectResponse(f"/payroll/{batch_id}/hours", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{batch_id}/hours")
async def hours_input(
    request: Request,
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)

    assignments = get_assignments_for_batch(db, batch_id)
    hourly_needs: dict[tuple[int, date], dict] = {}
    for a in assignments:
        if Role.LABOR.value not in (a.roles or []):
            continue
        if a.effective_pay_type != PayType.HOURLY.value:
            continue
        jd = a.job.job_date
        if not jd:
            continue
        key = (a.worker_id, jd)
        hourly_needs.setdefault(
            key,
            {"worker": a.worker, "date": jd, "jobs": 0},
        )
        hourly_needs[key]["jobs"] += 1

    saved_hours = (batch.session_data_json or {}).get("daily_hours", {})

    return request.app.state.templates.TemplateResponse(
        request,
        "payroll/hours.html",
        {
            "request": request,
            "user": user,
            "batch": batch,
            "hourly_needs": hourly_needs,
            "saved_hours": saved_hours,
            "readonly": batch.status == PayrollStatus.FINALIZED.value,
        },
    )


@router.post("/{batch_id}/hours/save")
async def save_hours_form(
    request: Request,
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)
    try:
        ensure_editable(batch)
    except PermissionError:
        return RedirectResponse(f"/payroll/{batch_id}/hours", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    daily_hours: dict[tuple[int, date], Decimal] = {}
    saved: dict[str, str] = {}

    for key, value in form.items():
        if key.startswith("hours_") and value:
            rest = key.replace("hours_", "", 1)
            if "|" in rest:
                worker_id_str, day_str = rest.split("|", 1)
                worker_id = int(worker_id_str)
                day = date.fromisoformat(day_str)
                try:
                    hours = Decimal(value)
                except InvalidOperation:
                    hours = Decimal("0")
                daily_hours[(worker_id, day)] = hours
                saved[f"{worker_id}|{day.isoformat()}"] = str(hours)

    batch.session_data_json = {"daily_hours": saved}
    db.commit()
    compute_hours_assigned(db, user.id, batch_id, daily_hours)
    return RedirectResponse(f"/payroll/{batch_id}/calculate", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{batch_id}/calculate")
async def calculate_page(
    request: Request,
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)

    job_results = list(
        db.scalars(
            select(PayrollJobResult)
            .where(PayrollJobResult.payroll_batch_id == batch_id)
            .options(joinedload(PayrollJobResult.worker), joinedload(PayrollJobResult.job))
            .order_by(PayrollJobResult.job_id)
        )
    )
    worker_results = list(
        db.scalars(
            select(PayrollResult)
            .where(PayrollResult.payroll_batch_id == batch_id)
            .options(joinedload(PayrollResult.worker))
        )
    )
    workers_by_id = {str(w.id): w.name for w in list_workers(db, user.id)}
    jobs_by_id = {str(j.id): job_label(j) for j in get_jobs_for_batch(db, user.id, batch_id)}
    warnings: list[dict] = []
    for wr in worker_results:
        snap = wr.calculation_snapshot_json or {}
        warnings.extend(_enrich_warning_messages(snap.get("warnings", []), workers_by_id, jobs_by_id))

    return request.app.state.templates.TemplateResponse(
        request,
        "payroll/calculate.html",
        {
            "request": request,
            "user": user,
            "batch": batch,
            "job_results": job_results,
            "worker_results": worker_results,
            "warnings": warnings,
            "readonly": batch.status == PayrollStatus.FINALIZED.value,
        },
    )


@router.post("/{batch_id}/calculate")
async def run_calculate(
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)
    try:
        ensure_editable(batch)
    except PermissionError:
        return RedirectResponse(f"/payroll/{batch_id}/calculate", status_code=status.HTTP_303_SEE_OTHER)

    saved = (batch.session_data_json or {}).get("daily_hours", {})
    daily_hours: dict[tuple[int, date], Decimal] = {}
    for key, val in saved.items():
        worker_id_str, day_str = key.split("|", 1)
        daily_hours[(int(worker_id_str), date.fromisoformat(day_str))] = Decimal(val)

    owner = get_owner_worker(db, user.id)
    run_calculation(db, user.id, batch, daily_hours, owner.id if owner else None)
    return RedirectResponse(f"/payroll/{batch_id}/calculate", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{batch_id}/finalize")
async def finalize_page(
    request: Request,
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)
    worker_results = list(
        db.scalars(
            select(PayrollResult)
            .where(PayrollResult.payroll_batch_id == batch_id)
            .options(joinedload(PayrollResult.worker))
        )
    )
    return request.app.state.templates.TemplateResponse(
        request,
        "payroll/finalize.html",
        {
            "request": request,
            "user": user,
            "batch": batch,
            "worker_results": worker_results,
        },
    )


@router.post("/{batch_id}/finalize")
async def finalize_payroll(
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/begin", status_code=status.HTTP_303_SEE_OTHER)
    try:
        finalize_batch(db, batch)
    except PermissionError:
        pass
    return RedirectResponse("/payroll/history", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{batch_id}/detail")
async def batch_detail(
    request: Request,
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = get_batch(db, user.id, batch_id)
    if not batch:
        return RedirectResponse("/payroll/history", status_code=status.HTTP_303_SEE_OTHER)
    job_results = list(
        db.scalars(
            select(PayrollJobResult)
            .where(PayrollJobResult.payroll_batch_id == batch_id)
            .options(joinedload(PayrollJobResult.worker), joinedload(PayrollJobResult.job))
        )
    )
    worker_results = list(
        db.scalars(
            select(PayrollResult)
            .where(PayrollResult.payroll_batch_id == batch_id)
            .options(joinedload(PayrollResult.worker))
        )
    )
    jobs = get_jobs_for_batch(db, user.id, batch_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "payroll/detail.html",
        {
            "request": request,
            "user": user,
            "batch": batch,
            "jobs": jobs,
            "job_results": job_results,
            "worker_results": worker_results,
        },
    )
