from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.calendar import CalendarConnection
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/calendar")
async def calendar_settings(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = db.scalar(select(CalendarConnection).where(CalendarConnection.user_id == user.id))
    return request.app.state.templates.TemplateResponse(
        request,
        "settings/calendar.html",
        {"request": request, "user": user, "connection": conn},
    )


@router.post("/calendar/connect")
async def calendar_connect(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = db.scalar(select(CalendarConnection).where(CalendarConnection.user_id == user.id))
    if not conn:
        conn = CalendarConnection(user_id=user.id, provider="apple", is_active=True)
        db.add(conn)
    else:
        conn.is_active = True
        conn.provider = "apple"
    db.commit()
    return RedirectResponse("/settings/calendar", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/calendar/disconnect")
async def calendar_disconnect(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = db.scalar(select(CalendarConnection).where(CalendarConnection.user_id == user.id))
    if conn:
        conn.is_active = False
        db.commit()
    return RedirectResponse("/settings/calendar", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/accounting")
async def accounting_settings(request: Request, user: User = Depends(get_current_user)):
    return request.app.state.templates.TemplateResponse(
        request,
        "settings/accounting.html",
        {"request": request, "user": user},
    )
