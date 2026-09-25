from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.routers.events import _values_from_parsed
from app.services.event_format import CLASSIFICATIONS, SERVICE_SCOPES
from app.services.job_timer_service import job_timer_view


def _render_event_form(**overrides):
    templates_dir = Path(__file__).resolve().parents[2] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    values = {
        "customer_id": "",
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
        "crew_id": "",
    }
    values.update(overrides.pop("values", {}))
    context = {
        "static_version": "test",
        "uid": None,
        "calendar_name": "Work",
        "classifications": CLASSIFICATIONS,
        "service_scopes": SERVICE_SCOPES,
        "connected": True,
        "saved": False,
        "error": None,
        "job_message": None,
        "job_timer": job_timer_view(None),
        "crews": [],
        "values": values,
    }
    context.update(overrides)
    return env.get_template("events/form.html").render(**context)


def test_event_form_template_is_iphone_oriented():
    html = _render_event_form()
    assert 'class="ios-event-page"' in html or "ios-event-page" in html
    assert "ios-notes-stack" in html
    assert 'name="classification"' in html
    assert 'name="service_scope"' in html
    assert 'name="price"' in html
    assert "viewport" in html
    assert "apple-touch-icon" in html
    assert "/favicon.ico" in html
    assert "ios-when-date" in html
    assert "ios-when-time" in html
    assert 'id="theme-toggle"' in html
    assert "ss-payroll-theme" in html
    assert 'data-theme="light"' in html
    assert 'name="starts_at"' in html
    assert 'name="ends_at"' in html
    assert "Parks Mangelson ($322)" in html
    # Notes-area fields appear after identity / phone groups
    notes_idx = html.index("ios-notes-stack")
    assert html.index('name="classification"') > notes_idx


def test_event_edit_done_skips_save_when_unchanged():
    html = _render_event_form(
        uid="abc-123",
        values={"customer_id": "1"},
    )
    assert "isDirty" in html
    assert 'window.location.href = "/events"' in html
    assert "snapshotForm" in html
    assert "crew_id: crewSelect" in html
    assert "Done" in html
    assert "Start Job" in html
    assert "Job Duration" in html
    assert 'id="address-link"' in html
    assert 'id="phone-link"' in html
    assert "maps.apple.com/?daddr=" in html
    assert "tel:" in html
    assert "navigationHref" in html
    assert "telHref" in html


def test_event_form_keeps_selected_crew():
    crews = [SimpleNamespace(id=7, name="Crew A"), SimpleNamespace(id=9, name="Crew B")]
    html = _render_event_form(crews=crews, values={"crew_id": "9"})
    assert 'name="crew_id"' in html
    assert 'value="9" selected' in html or 'value="9" selected=' in html
    assert "Crew B" in html


def test_values_from_parsed_includes_crew_id():
    parsed = {
        "customer_name": "Parks Mangelson",
        "address": "1446 E 900 S",
        "phone": "801-376-7998",
        "price": "322",
        "classification": "windows",
        "service_scope": "inside_and_outside",
        "free_note": "",
        "starts_at": None,
        "ends_at": None,
    }
    values = _values_from_parsed(parsed, customer_id="3", crew_id="12")
    assert values["crew_id"] == "12"
    assert values["customer_id"] == "3"