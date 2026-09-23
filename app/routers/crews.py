from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.calendar_service import get_active_connection
from app.services.crew_service import (
    create_crew,
    crew_rate_display,
    get_crew,
    list_crews,
    update_crew,
)
from app.services.duration_service import crew_schedule_rate
from app.services.worker_service import list_workers

router = APIRouter(prefix="/crews", tags=["crews"])


@router.get("")
async def crews_list(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    crews = list_crews(db, user.id)
    rates = {c.id: crew_schedule_rate(c) for c in crews}
    return request.app.state.templates.TemplateResponse(
        request,
        "crews/list.html",
        {"request": request, "user": user, "crews": crews, "rates": rates},
    )


@router.get("/new")
async def crews_new(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workers = list_workers(db, user.id, active_only=True)
    conn = get_active_connection(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "crews/form.html",
        {
            "request": request,
            "user": user,
            "crew": None,
            "workers": workers,
            "selected_worker_ids": [],
            "default_calendar": conn.calendar_id if conn else "",
            "error": None,
        },
    )


@router.post("/new")
async def crews_create(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    apple_calendar_id: str = Form(""),
    is_bookable_online: str = Form("on"),
    is_active: str = Form("on"),
):
    form = await request.form()
    worker_ids = [int(v) for v in form.getlist("worker_ids") if str(v).isdigit()]
    create_crew(
        db,
        user.id,
        name=name,
        apple_calendar_id=apple_calendar_id,
        is_bookable_online=is_bookable_online == "on",
        is_active=is_active == "on",
        worker_ids=worker_ids,
    )
    return RedirectResponse("/crews", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{crew_id}/edit")
async def crews_edit(
    request: Request,
    crew_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    crew = get_crew(db, user.id, crew_id)
    if not crew:
        return RedirectResponse("/crews", status_code=status.HTTP_303_SEE_OTHER)
    workers = list_workers(db, user.id, active_only=False)
    conn = get_active_connection(db, user.id)
    return request.app.state.templates.TemplateResponse(
        request,
        "crews/form.html",
        {
            "request": request,
            "user": user,
            "crew": crew,
            "workers": workers,
            "selected_worker_ids": [m.worker_id for m in crew.members],
            "default_calendar": conn.calendar_id if conn else "",
            "crew_rate": crew_rate_display(crew),
            "error": None,
        },
    )


@router.post("/{crew_id}/edit")
async def crews_update(
    request: Request,
    crew_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    apple_calendar_id: str = Form(""),
    is_bookable_online: str = Form(""),
    is_active: str = Form(""),
):
    crew = get_crew(db, user.id, crew_id)
    if not crew:
        return RedirectResponse("/crews", status_code=status.HTTP_303_SEE_OTHER)
    form = await request.form()
    worker_ids = [int(v) for v in form.getlist("worker_ids") if str(v).isdigit()]
    update_crew(
        db,
        crew,
        name=name,
        apple_calendar_id=apple_calendar_id,
        is_bookable_online=is_bookable_online == "on",
        is_active=is_active == "on",
        worker_ids=worker_ids,
    )
    return RedirectResponse(
        f"/crews/{crew_id}/edit?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )
