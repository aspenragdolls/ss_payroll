from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.calendar import CalendarConnection
from app.models.user import User
from app.services.credential_crypto import encrypt_credential
from app.services.payroll_config_service import (
    PayrollConfigValues,
    get_payroll_config,
    parse_config_form,
    parse_decimal,
    save_payroll_config,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_connection(db: Session, user_id: int) -> CalendarConnection | None:
    return db.scalar(select(CalendarConnection).where(CalendarConnection.user_id == user_id))


@router.get("/calendar")
async def calendar_settings(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = _get_connection(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "settings/calendar.html",
        {"request": request, "user": user, "connection": conn, "error": None},
    )


@router.post("/calendar/connect")
async def calendar_connect(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    apple_id: str = Form(...),
    app_password: str = Form(""),
    calendar_name: str = Form(...),
):
    apple_id = apple_id.strip()
    calendar_name = calendar_name.strip()
    app_password = app_password.strip()

    conn = _get_connection(db, user.id)
    has_saved_password = bool(conn and conn.access_token_encrypted)

    if not apple_id or not calendar_name:
        error = "Apple ID and calendar name are required."
    elif not app_password and not has_saved_password:
        error = "App-specific password is required."
    else:
        error = None

    if error:
        return request.app.state.templates.TemplateResponse(
            request,
            "settings/calendar.html",
            {"request": request, "user": user, "connection": conn, "error": error},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not conn:
        conn = CalendarConnection(user_id=user.id, provider="apple")
        db.add(conn)

    conn.provider = "apple"
    conn.external_account_id = apple_id
    conn.calendar_id = calendar_name
    conn.is_active = True
    if app_password:
        conn.access_token_encrypted = encrypt_credential(app_password)

    db.commit()
    return RedirectResponse(
        "/settings/calendar?saved=1&saved_form=connect",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/calendar/disconnect")
async def calendar_disconnect(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = _get_connection(db, user.id)
    if conn:
        conn.is_active = False
        conn.access_token_encrypted = None
        conn.refresh_token_encrypted = None
        db.commit()
    return RedirectResponse(
        "/settings/calendar?saved=1&saved_form=disconnect",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/accounting")
async def accounting_settings(request: Request, user: User = Depends(get_current_user)):
    return request.app.state.templates.TemplateResponse(
        request,
        "settings/accounting.html",
        {"request": request, "user": user},
    )


@router.get("/payroll")
async def payroll_settings(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = get_payroll_config(db, user.id)
    saved = request.query_params.get("saved") == "1"
    return request.app.state.templates.TemplateResponse(
        request,
        "settings/payroll.html",
        {"request": request, "user": user, "config": config, "errors": None, "saved": saved},
    )


def _config_from_form(
    *,
    labor_pool_percent: str,
    commission_pool_percent: str,
    business_retained_percent: str,
    tier_1_weight: str,
    tier_2_weight: str,
    tier_3_weight: str,
    fallback: PayrollConfigValues,
) -> PayrollConfigValues:
    """Build display values from form input, falling back where parsing fails."""
    fields = [
        ("labor_pool_percent", labor_pool_percent),
        ("commission_pool_percent", commission_pool_percent),
        ("business_retained_percent", business_retained_percent),
        ("tier_1_weight", tier_1_weight),
        ("tier_2_weight", tier_2_weight),
        ("tier_3_weight", tier_3_weight),
    ]
    values = {}
    for attr, raw in fields:
        parsed, _ = parse_decimal(raw, attr)
        values[attr] = parsed if parsed is not None else getattr(fallback, attr)
    return PayrollConfigValues(**values)


@router.post("/payroll/review")
async def payroll_settings_review(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    labor_pool_percent: str = Form(...),
    commission_pool_percent: str = Form(...),
    business_retained_percent: str = Form(...),
    tier_1_weight: str = Form(...),
    tier_2_weight: str = Form(...),
    tier_3_weight: str = Form(...),
):
    current = get_payroll_config(db, user.id)
    proposed, errors = parse_config_form(
        labor_pool_percent=labor_pool_percent,
        commission_pool_percent=commission_pool_percent,
        business_retained_percent=business_retained_percent,
        tier_1_weight=tier_1_weight,
        tier_2_weight=tier_2_weight,
        tier_3_weight=tier_3_weight,
    )
    if errors or proposed is None:
        display = _config_from_form(
            labor_pool_percent=labor_pool_percent,
            commission_pool_percent=commission_pool_percent,
            business_retained_percent=business_retained_percent,
            tier_1_weight=tier_1_weight,
            tier_2_weight=tier_2_weight,
            tier_3_weight=tier_3_weight,
            fallback=current,
        )
        return request.app.state.templates.TemplateResponse(
            request,
            "settings/payroll.html",
            {
                "request": request,
                "user": user,
                "config": display,
                "errors": errors,
                "saved": False,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return request.app.state.templates.TemplateResponse(
        request,
        "settings/payroll_confirm.html",
        {"request": request, "user": user, "current": current, "proposed": proposed},
    )


@router.post("/payroll/save")
async def payroll_settings_save(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    labor_pool_percent: str = Form(...),
    commission_pool_percent: str = Form(...),
    business_retained_percent: str = Form(...),
    tier_1_weight: str = Form(...),
    tier_2_weight: str = Form(...),
    tier_3_weight: str = Form(...),
):
    proposed, errors = parse_config_form(
        labor_pool_percent=labor_pool_percent,
        commission_pool_percent=commission_pool_percent,
        business_retained_percent=business_retained_percent,
        tier_1_weight=tier_1_weight,
        tier_2_weight=tier_2_weight,
        tier_3_weight=tier_3_weight,
    )
    if errors or proposed is None:
        current = get_payroll_config(db, user.id)
        display = _config_from_form(
            labor_pool_percent=labor_pool_percent,
            commission_pool_percent=commission_pool_percent,
            business_retained_percent=business_retained_percent,
            tier_1_weight=tier_1_weight,
            tier_2_weight=tier_2_weight,
            tier_3_weight=tier_3_weight,
            fallback=current,
        )
        return request.app.state.templates.TemplateResponse(
            request,
            "settings/payroll.html",
            {
                "request": request,
                "user": user,
                "config": display,
                "errors": errors,
                "saved": False,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    save_payroll_config(db, user.id, proposed)
    return RedirectResponse("/settings/payroll?saved=1", status_code=status.HTTP_303_SEE_OTHER)
