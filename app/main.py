from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ss_payroll", version="0.1.0")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age,
    )
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    templates = Jinja2Templates(directory="app/templates")
    app.state.templates = templates

    from app.routers import auth, calendar, payroll, workers

    app.include_router(auth.router)
    app.include_router(workers.router)
    app.include_router(calendar.router)
    app.include_router(payroll.router)

    @app.get("/")
    async def root(request: Request):
        if not request.session.get("user_id"):
            return RedirectResponse("/auth/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"request": request, "user": request.session.get("user")},
        )

    return app


app = create_app()
