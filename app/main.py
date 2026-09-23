from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import get_db
from app.domain.payroll_stages import PAYROLL_STEP_LABELS, get_stage_url
from app.services.auth_service import get_user_by_id
from app.services.payroll_service import get_batch_stage, list_in_progress_batches
from app.services.stats_service import (
    get_dashboard_stats,
    parse_goals_form,
    save_business_goals,
    today_for_timezone,
)
from app.template_utils import job_label

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_FAVICON_PATH = _STATIC_DIR / "favicon.ico"


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from app.services.calendar_sync_service import run_periodic_calendar_sync

    stop = asyncio.Event()
    sync_task = asyncio.create_task(run_periodic_calendar_sync(stop))
    try:
        yield
    finally:
        stop.set()
        await sync_task


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ss_payroll", version="0.2.0", lifespan=lifespan)
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

    # Assets are cache-busted via ?v={{ static_version }}; allow long-lived browser cache.
    @app.middleware("http")
    async def cache_static_assets(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") or path == "/favicon.ico":
            response.headers.setdefault(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        return response

    from app.routers import (
        auth,
        calendar,
        crews,
        customers,
        events,
        packages,
        payroll,
        portal,
        scheduling,
        workers,
    )

    app.include_router(auth.router)
    app.include_router(workers.router)
    app.include_router(crews.router)
    app.include_router(customers.router)
    app.include_router(events.router)
    app.include_router(calendar.router)
    app.include_router(payroll.router)
    app.include_router(packages.router)
    app.include_router(scheduling.router)
    app.include_router(portal.router)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(_FAVICON_PATH, media_type="image/x-icon")

    @app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
    async def health():
        return Response(status_code=200)

    @app.get("/")
    async def root(request: Request, db: Session = Depends(get_db)):
        if not request.session.get("user_id"):
            return RedirectResponse("/auth/login", status_code=303)
        user = request.session.get("user")
        tab = request.query_params.get("tab", "stats")
        if tab not in {"stats", "overview"}:
            tab = "stats"

        drafts = list_in_progress_batches(db, user["id"])
        draft_sessions = []
        for batch in drafts[:3]:
            stage = get_batch_stage(db, batch)
            draft_sessions.append(
                {
                    "batch": batch,
                    "stage_label": PAYROLL_STEP_LABELS.get(stage, "Jobs"),
                    "resume_url": get_stage_url(batch.id, stage),
                }
            )
        deleted = request.query_params.get("deleted") == "1"

        stats = None
        goal_errors = request.session.pop("goal_errors", None)
        goals_saved = request.session.pop("goals_saved", False)
        if tab == "stats":
            db_user = get_user_by_id(db, user["id"])
            tz_name = db_user.timezone if db_user else None
            stats = get_dashboard_stats(
                db,
                user["id"],
                today=today_for_timezone(tz_name),
                timezone_name=tz_name,
            )

        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "user": user,
                "tab": tab,
                "draft_sessions": draft_sessions,
                "event_deleted": deleted,
                "stats": stats,
                "goal_errors": goal_errors or [],
                "goals_saved": goals_saved,
            },
        )

    @app.post("/stats/goals")
    async def save_stats_goals(
        request: Request,
        db: Session = Depends(get_db),
        monthly_revenue_goal: str = Form(""),
        yearly_revenue_goal: str = Form(""),
    ):
        if not request.session.get("user_id"):
            return RedirectResponse("/auth/login", status_code=303)
        user = request.session.get("user")
        values, errors = parse_goals_form(
            monthly_revenue_goal=monthly_revenue_goal,
            yearly_revenue_goal=yearly_revenue_goal,
        )
        if errors or values is None:
            request.session["goal_errors"] = errors
            return RedirectResponse("/?tab=stats", status_code=303)
        save_business_goals(db, user["id"], values)
        request.session["goals_saved"] = True
        return RedirectResponse("/?tab=stats", status_code=303)

    return app


app = create_app()
