from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.event_format import CLASSIFICATIONS, SERVICE_SCOPES


def test_event_form_template_is_iphone_oriented():
    templates_dir = Path(__file__).resolve().parents[2] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("events/form.html")
    html = template.render(
        static_version="test",
        uid=None,
        calendar_name="Work",
        classifications=CLASSIFICATIONS,
        service_scopes=SERVICE_SCOPES,
        connected=True,
        saved=False,
        error=None,
        values={
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
        },
    )
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
    assert "ss-payroll-ios-theme" in html
    assert 'name="starts_at"' in html
    assert 'name="ends_at"' in html
    assert "Parks Mangelson ($322)" in html
    # Notes-area fields appear after identity / phone groups
    notes_idx = html.index("ios-notes-stack")
    assert html.index('name="classification"') > notes_idx


def test_event_edit_done_skips_save_when_unchanged():
    templates_dir = Path(__file__).resolve().parents[2] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    html = env.get_template("events/form.html").render(
        static_version="test",
        uid="abc-123",
        calendar_name="Work",
        classifications=CLASSIFICATIONS,
        service_scopes=SERVICE_SCOPES,
        connected=True,
        saved=False,
        error=None,
        values={
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
        },
    )
    assert "isDirty" in html
    assert 'window.location.href = "/events"' in html
    assert "snapshotForm" in html
    assert "Done" in html
