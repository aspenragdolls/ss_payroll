"""Event edit should persist and reload crew selection."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.dependencies import get_current_user
from app.routers import events
from app.services.duration_service import DurationEstimate


_TZ = ZoneInfo("America/Denver")


def _app_with_overrides(db, user):
    app = FastAPI()
    app.include_router(events.router)
    app.state.templates = MagicMock()

    async def _user():
        return user

    def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return app


@pytest.mark.asyncio
async def test_edit_form_loads_crew_from_booking(monkeypatch):
    user = SimpleNamespace(id=1)
    db = MagicMock()
    conn = SimpleNamespace(calendar_id="Work")
    booking = SimpleNamespace(crew_id=42)
    event = SimpleNamespace(
        event_id="uid-1",
        title="Parks Mangelson ($322)",
        description="801-376-7998\n\nInside and outside",
        location="1446 E 900 S",
        start=datetime(2026, 9, 16, 9, 0, tzinfo=_TZ),
        end=datetime(2026, 9, 16, 10, 0, tzinfo=_TZ),
    )
    captured = {}

    class FakeResponse:
        def __init__(self, *args, **kwargs):
            captured["context"] = args[2] if len(args) > 2 else kwargs.get("context")

    monkeypatch.setattr(events, "get_active_connection", lambda db, user_id: conn)
    monkeypatch.setattr(events, "get_customer_by_calendar_uid", lambda *a, **k: None)
    monkeypatch.setattr(events, "get_booking_by_calendar_uid", lambda *a, **k: booking)
    monkeypatch.setattr(events, "get_event_for_user", AsyncMock(return_value=event))
    monkeypatch.setattr(events, "suggest_customers", lambda *a, **k: [])
    monkeypatch.setattr(events, "list_crews", lambda *a, **k: [])
    monkeypatch.setattr(events, "job_timer_view", lambda c: SimpleNamespace(status="idle"))
    monkeypatch.setattr(
        events,
        "parse_event_for_app",
        lambda e: {
            "customer_name": "Parks Mangelson",
            "address": "1446 E 900 S",
            "phone": "801-376-7998",
            "price": "322",
            "classification": "windows",
            "service_scope": "inside_and_outside",
            "free_note": "",
            "starts_at": e.start,
            "ends_at": e.end,
        },
    )

    app = _app_with_overrides(db, user)
    app.state.templates.TemplateResponse = FakeResponse

    client = TestClient(app)
    client.get("/events/uid-1/edit")

    assert captured["context"]["values"]["crew_id"] == "42"


def test_update_event_persists_crew_booking(monkeypatch):
    user = SimpleNamespace(id=1)
    db = MagicMock()
    conn = SimpleNamespace(calendar_id="Work")
    crew = SimpleNamespace(id=7, name="A", is_active=True)
    estimate = DurationEstimate(
        minutes=90,
        source="formula",
        crew_rate=Decimal("150"),
        price=Decimal("322"),
    )
    upsert_calls = []

    monkeypatch.setattr(events, "get_active_connection", lambda db, user_id: conn)
    monkeypatch.setattr(events, "list_crews", lambda *a, **k: [crew])
    monkeypatch.setattr(events, "get_crew", lambda *a, **k: crew)
    monkeypatch.setattr(events, "get_customer", lambda *a, **k: None)
    monkeypatch.setattr(events, "get_customer_by_calendar_uid", lambda *a, **k: None)
    monkeypatch.setattr(events, "resolve_duration", lambda *a, **k: estimate)
    monkeypatch.setattr(events, "update_event_for_user", AsyncMock())
    monkeypatch.setattr(events, "upsert_customer_from_event", MagicMock())
    monkeypatch.setattr(events, "_job_timer_for_uid", lambda *a, **k: SimpleNamespace(status="idle"))
    monkeypatch.setattr(
        events,
        "upsert_booking_for_calendar_event",
        lambda *args, **kwargs: upsert_calls.append(kwargs) or MagicMock(),
    )
    monkeypatch.setattr(events, "cancel_booking_for_calendar_event", MagicMock())

    app = _app_with_overrides(db, user)
    client = TestClient(app)
    response = client.post(
        "/events/uid-1/edit",
        data={
            "customer_name": "Parks Mangelson",
            "address": "1446 E 900 S",
            "phone": "801-376-7998",
            "price": "322",
            "classification": "windows",
            "service_scope": "inside_and_outside",
            "free_note": "",
            "starts_at": "2026-09-16T09:00",
            "ends_at": "2026-09-16T10:00",
            "crew_id": "7",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/events?saved=1"
    assert len(upsert_calls) == 1
    assert upsert_calls[0]["crew_id"] == 7
    assert upsert_calls[0]["calendar_event_uid"] == "uid-1"
    assert upsert_calls[0]["price"] == Decimal("322")
    assert upsert_calls[0]["duration_minutes"] == 90
