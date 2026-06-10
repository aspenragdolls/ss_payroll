from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.domain.enums import Role
from app.models.user import User
from app.services.payroll_config_service import get_payroll_config
from app.services.worker_service import (
    create_worker,
    get_worker,
    list_workers,
    update_worker,
)

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("")
async def workers_list(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workers = list_workers(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "workers/list.html",
        {"request": request, "user": user, "workers": workers},
    )


@router.get("/new")
async def workers_new(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payroll_config = get_payroll_config(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "workers/form.html",
        {"request": request, "user": user, "worker": None, "error": None, "payroll_config": payroll_config},
    )


@router.post("/new")
async def workers_create(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    role_labor: str | None = Form(None),
    role_sales: str | None = Form(None),
    labor_pay_type: str = Form(""),
    labor_percentage_tier: str = Form(""),
    hourly_rate: str = Form(""),
    notes: str = Form(""),
    is_active: str = Form("on"),
):
    roles = []
    if role_labor:
        roles.append(Role.LABOR.value)
    if role_sales:
        roles.append(Role.SALES.value)
    rate = _parse_decimal(hourly_rate)
    create_worker(
        db,
        user.id,
        name=name,
        roles=roles,
        is_active=is_active == "on",
        labor_pay_type=labor_pay_type or None,
        labor_percentage_tier=labor_percentage_tier or None,
        hourly_rate=rate,
        notes=notes or None,
    )
    return RedirectResponse("/workers", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{worker_id}/edit")
async def workers_edit(
    request: Request,
    worker_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    worker = get_worker(db, user.id, worker_id)
    if not worker:
        return RedirectResponse("/workers", status_code=status.HTTP_303_SEE_OTHER)
    payroll_config = get_payroll_config(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "workers/form.html",
        {"request": request, "user": user, "worker": worker, "error": None, "payroll_config": payroll_config},
    )


@router.post("/{worker_id}/edit")
async def workers_update(
    request: Request,
    worker_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    role_labor: str | None = Form(None),
    role_sales: str | None = Form(None),
    labor_pay_type: str = Form(""),
    labor_percentage_tier: str = Form(""),
    hourly_rate: str = Form(""),
    notes: str = Form(""),
    is_active: str = Form("on"),
):
    worker = get_worker(db, user.id, worker_id)
    if not worker:
        return RedirectResponse("/workers", status_code=status.HTTP_303_SEE_OTHER)
    roles = []
    if role_labor:
        roles.append(Role.LABOR.value)
    if role_sales:
        roles.append(Role.SALES.value)
    update_worker(
        db,
        worker,
        name=name.strip(),
        roles=roles,
        is_active=is_active == "on",
        labor_pay_type=labor_pay_type or None,
        labor_percentage_tier=labor_percentage_tier or None,
        hourly_rate=_parse_decimal(hourly_rate),
        notes=notes or None,
    )
    return RedirectResponse("/workers", status_code=status.HTTP_303_SEE_OTHER)


def _parse_decimal(value: str) -> Decimal | None:
    if not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None
