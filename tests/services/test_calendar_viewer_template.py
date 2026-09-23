from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def test_calendar_viewer_template_matches_apple_list_chrome():
    templates_dir = Path(__file__).resolve().parents[2] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("events/calendar.html")
    html = template.render(
        static_version="test",
        connected=True,
        calendar_name="Work",
        user={"business_name": "Test Co", "id": 1},
    )
    assert 'class="ios-cal-page"' in html
    assert 'id="btn-today"' in html
    assert 'id="nav-back"' in html
    assert 'href="/events/new"' in html
    assert 'id="btn-list"' in html
    assert "/api/events" in html
    assert "viewport" in html
    assert "apple-touch-icon" in html


def test_base_nav_links_to_apple_calendar():
    templates_dir = Path(__file__).resolve().parents[2] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    html = env.get_template("base.html").render(
        static_version="test",
        user={"business_name": "Test Co", "id": 1},
    )
    assert 'href="/events"' in html
    assert "Apple Calendar" in html
    assert 'hx-boost="false"' in html
    assert 'id="app-shell"' in html
    assert 'hx-target="#app-shell"' in html
    assert "/static/nav-perf.js" in html
    assert "/static/vendor/htmx.min.js" in html
    assert "New Event" not in html
    assert 'id="theme-toggle"' in html
    assert "ss-payroll-theme" in html
    assert 'data-theme="light"' in html


def test_calendar_viewer_has_theme_toggle():
    templates_dir = Path(__file__).resolve().parents[2] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    html = env.get_template("events/calendar.html").render(
        static_version="test",
        connected=True,
        calendar_name="Work",
        user={"business_name": "Test Co", "id": 1},
    )
    assert 'id="theme-toggle"' in html
    assert "ss-payroll-theme" in html
    assert 'data-theme="light"' in html
