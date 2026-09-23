from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import get_db
from app.domain.payroll_stages import PAYROLL_STEP_LABELS, get_stage_url
from app.services.payroll_service import get_batch_stage, list_in_progress_batches
from app.template_utils import job_label

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_FAVICON_PATH = _STATIC_DIR / "favicon.ico"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ss_payroll", version="0.1.3")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age,
    )
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory="app/templates")
    templates.env.filters["job_label"] = job_label
    templates.env.globals["static_version"] = app.version
    app.state.templates = templates

    from app.routers import auth, calendar, customers, events, payroll, workers

    app.include_router(auth.router)
    app.include_router(workers.router)
    app.include_router(customers.router)
    app.include_router(events.router)
    app.include_router(calendar.router)
    app.include_router(payroll.router)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(_FAVICON_PATH, media_type="image/x-icon")

    @app.get("/")
    async def root(request: Request, db: Session = Depends(get_db)):
        if not request.session.get("user_id"):
            return RedirectResponse("/auth/login", status_code=303)
        user = request.session.get("user")
        drafts = list_in_progress_batches(db, user["id"])
        draft_sessions = [
            {
                "batch": batch,
                "stage_label": PAYROLL_STEP_LABELS.get(get_batch_stage(db, batch), "Jobs"),
                "resume_url": get_stage_url(batch.id, get_batch_stage(db, batch)),
            }
            for batch in drafts[:3]
        ]
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "user": user,
                "draft_sessions": draft_sessions,
            },
        )

    return app


app = create_app()
