from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.event_format import CLASSIFICATIONS, SERVICE_SCOPES
from app.services.job_timer_service import (
    compute_duration_minutes,
    format_duration_minutes,
    job_timer_view,
)


def test_format_duration_minutes():
    assert format_duration_minutes(0) == "0m"
    assert format_duration_minutes(45) == "45m"
    assert format_duration_minutes(60) == "1h"
    assert format_duration_minutes(135) == "2h 15m"
    assert format_duration_minutes(None) == ""


def test_compute_duration_minutes_rounds_up_partial_minute():
    start = datetime(2026, 9, 22, 10, 0, 0)
    end = start + timedelta(minutes=1, seconds=1)
    assert compute_duration_minutes(start, end) == 2


def test_compute_duration_minutes_exact():
    start = datetime(2026, 9, 22, 9, 0, 0)
    end = start + timedelta(hours=2, minutes=15)
    assert compute_duration_minutes(start, end) == 135


def test_job_timer_view_states():
    idle = job_timer_view(None)
    assert idle.status == "idle"
    assert idle.duration_label == ""

    in_progress = job_timer_view(
        SimpleNamespace(
            job_started_at=datetime(2026, 9, 22, 14, 5, 0),
            job_finished_at=None,
            job_duration_minutes=None,
        )
    )
    assert in_progress.status == "in_progress"
    assert in_progress.started_label == "2:05 PM"
    assert in_progress.can_finish is True

    finished = job_timer_view(
        SimpleNamespace(
            job_started_at=datetime(2026, 9, 22, 9, 0, 0),
            job_finished_at=datetime(2026, 9, 22, 11, 15, 0),
            job_duration_minutes=135,
        )
    )
    assert finished.status == "finished"
    assert finished.duration_label == "2h 15m"
    assert finished.can_finish is False


def _render_event_form(**overrides):
    templates_dir = Path(__file__).resolve().parents[2] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    values = {
        "customer_id": "1",
        "customer_name": "Parks Mangelson",
        "address": "1446 E 900 S",
        "phone": "801-376-7998",
        "price": "322",
        "classification": "windows",
        "service_scope": "inside_and_outside",
        "free_note": "",
        "starts_at": "2026-09-16T09:00",
        "ends_at": "2026-09-16T10:00",
        "title_preview": "Parks Mangelson ($322)",
    }
    ctx = {
        "static_version": "test",
        "uid": "abc-123",
        "calendar_name": "Work",
        "classifications": CLASSIFICATIONS,
        "service_scopes": SERVICE_SCOPES,
        "connected": True,
        "saved": False,
        "error": None,
        "job_message": None,
        "job_timer": job_timer_view(None),
        "values": values,
    }
    ctx.update(overrides)
    return env.get_template("events/form.html").render(**ctx)


def test_event_form_shows_start_job_and_duration_row():
    html = _render_event_form()
    assert "Job Duration" in html
    assert "Start Job" in html
    assert 'action="/events/abc-123/job/start"' in html
    assert 'action="/events/abc-123/job/finish"' not in html


def test_event_form_shows_finish_when_in_progress():
    timer = job_timer_view(
        SimpleNamespace(
            job_started_at=datetime(2026, 9, 22, 9, 30, 0),
            job_finished_at=None,
            job_duration_minutes=None,
        )
    )
    html = _render_event_form(job_timer=timer)
    assert "Restart Job" in html
    assert 'action="/events/abc-123/job/finish"' in html
    assert "Finish" in html
    assert "Started at 9:30 AM" in html
    assert "In progress" in html


def test_event_form_shows_finished_duration():
    timer = job_timer_view(
        SimpleNamespace(
            job_started_at=datetime(2026, 9, 22, 9, 0, 0),
            job_finished_at=datetime(2026, 9, 22, 10, 45, 0),
            job_duration_minutes=105,
        )
    )
    html = _render_event_form(job_timer=timer)
    assert "1h 45m" in html
    assert "Start Job" in html
    assert 'action="/events/abc-123/job/finish"' not in html
