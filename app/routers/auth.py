from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, get_optional_user
from app.models.user import User
from app.services.auth_service import authenticate_user, create_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return request.app.state.templates.TemplateResponse(
        request, "auth/login.html", {"request": request, "error": None}
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, email, password)
    if not user:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/login.html",
            {"request": request, "error": "Invalid email or password"},
            status_code=400,
        )
    request.session["user_id"] = user.id
    request.session["user"] = {"id": user.id, "email": user.email, "business_name": user.business_name}
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/register")
async def register_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return request.app.state.templates.TemplateResponse(
        request, "auth/register.html", {"request": request, "error": None}
    )


@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    business_name: str = Form(...),
    timezone: str = Form("America/New_York"),
    db: Session = Depends(get_db),
):
    from app.services.auth_service import get_user_by_email

    if get_user_by_email(db, email):
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "Email already registered"},
            status_code=400,
        )
    user = create_user(db, email=email, password=password, business_name=business_name, timezone=timezone)
    request.session["user_id"] = user.id
    request.session["user"] = {"id": user.id, "email": user.email, "business_name": user.business_name}
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=status.HTTP_303_SEE_OTHER)
