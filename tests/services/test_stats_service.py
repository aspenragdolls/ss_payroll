from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.customer import Customer
from app.services.stats_service import (
    average_ticket,
    goal_progress_pct,
    iter_month_starts,
    month_window_start,
    parse_goals_form,
    today_for_timezone,
    _rebook_opportunities,
)


def test_month_window_start_trailing_twelve():
    assert month_window_start(date(2026, 9, 22)) == date(2025, 10, 1)
    assert month_window_start(date(2026, 1, 5)) == date(2025, 2, 1)


def test_iter_month_starts_count():
    months = iter_month_starts(date(2025, 10, 1), date(2026, 9, 22))
    assert len(months) == 12
    assert months[0] == date(2025, 10, 1)
    assert months[-1] == date(2026, 9, 1)


def test_goal_progress_pct():
    assert goal_progress_pct(Decimal("5000"), Decimal("10000")) == Decimal("50.0")
    assert goal_progress_pct(Decimal("5000"), None) is None
    assert goal_progress_pct(Decimal("5000"), Decimal("0")) is None


def test_average_ticket():
    assert average_ticket(Decimal("900.00"), 3) == Decimal("300.00")
    assert average_ticket(Decimal("0"), 0) is None


def test_parse_goals_form_accepts_currency_chars():
    values, errors = parse_goals_form(
        monthly_revenue_goal="$12,000",
        yearly_revenue_goal="140000.5",
    )
    assert not errors
    assert values is not None
    assert values.monthly_revenue_goal == Decimal("12000.00")
    assert values.yearly_revenue_goal == Decimal("140000.50")


def test_parse_goals_form_allows_blank():
    values, errors = parse_goals_form(monthly_revenue_goal="", yearly_revenue_goal="")
    assert not errors
    assert values is not None
    assert values.monthly_revenue_goal is None
    assert values.yearly_revenue_goal is None


def test_parse_goals_form_rejects_negative():
    values, errors = parse_goals_form(
        monthly_revenue_goal="-100",
        yearly_revenue_goal="1000",
    )
    assert values is None
    assert any("negative" in e for e in errors)


def test_today_for_timezone():
    now = datetime(2026, 9, 22, 2, 0, tzinfo=ZoneInfo("UTC"))
    assert today_for_timezone("America/Denver", now=now) == date(2026, 9, 21)
    assert today_for_timezone("America/New_York", now=now) == date(2026, 9, 21)
    assert today_for_timezone("Invalid/Zone", now=now) == date(2026, 9, 21)


def test_rebook_opportunities_overdue_and_soon():
    today = date(2026, 9, 22)
    overdue = Customer(
        id=1,
        user_id=1,
        name="Overdue Co",
        status="active",
        is_active=True,
        do_not_contact=False,
        next_service_due=date(2026, 9, 1),
        usual_price=Decimal("200.00"),
    )
    soon = Customer(
        id=2,
        user_id=1,
        name="Soon Co",
        status="scheduled",
        is_active=True,
        do_not_contact=False,
        next_service_due=date(2026, 10, 5),
        usual_price=Decimal("150.00"),
    )
    ignored_far = Customer(
        id=3,
        user_id=1,
        name="Far Co",
        status="active",
        is_active=True,
        do_not_contact=False,
        next_service_due=date(2026, 12, 1),
        usual_price=Decimal("100.00"),
    )
    dnc = Customer(
        id=4,
        user_id=1,
        name="DNC Co",
        status="active",
        is_active=True,
        do_not_contact=True,
        next_service_due=date(2026, 9, 10),
        usual_price=Decimal("90.00"),
    )

    db = MagicMock()
    # Filter in Python to mirror the query intent under unit test.
    candidates = [overdue, soon, ignored_far, dnc]
    filtered = [
        c
        for c in candidates
        if c.is_active
        and not c.do_not_contact
        and c.status in {"lead", "quoted", "active", "estimate", "scheduled"}
        and c.next_service_due is not None
        and c.next_service_due <= date(2026, 10, 22)
    ]
    db.scalars.return_value = filtered

    items = _rebook_opportunities(db, 1, today)
    assert len(items) == 2
    assert items[0].name == "Overdue Co"
    assert items[0].overdue is True
    assert items[1].name == "Soon Co"
    assert items[1].overdue is False


def test_revenue_between_uses_finalized_batches_only():
    from app.services import stats_service

    db = MagicMock()
    result = MagicMock()
    result.one.return_value = (Decimal("750.00"), 2)
    db.execute.return_value = result

    revenue, count = stats_service._revenue_between(
        db, 1, date(2026, 9, 1), date(2026, 9, 22)
    )
    assert revenue == Decimal("750.00")
    assert count == 2
    stmt = db.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "payroll_batches" in compiled.lower() or "payroll_batch" in compiled.lower()


def test_dashboard_stats_template_has_tabs_and_charts():
    templates_dir = Path(__file__).resolve().parents[2] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    from app.services.stats_service import NamedAmount, RebookItem, StatsDashboard

    stats = StatsDashboard(
        today=date(2026, 9, 22),
        month_start=date(2026, 9, 1),
        year_start=date(2026, 1, 1),
        window_start=date(2025, 10, 1),
        monthly_revenue_goal=Decimal("10000"),
        yearly_revenue_goal=Decimal("120000"),
        mtd_revenue=Decimal("4500.00"),
        ytd_revenue=Decimal("52000.00"),
        mtd_job_count=12,
        ytd_job_count=140,
        mtd_avg_ticket=Decimal("375.00"),
        ytd_avg_ticket=Decimal("371.43"),
        mtd_goal_pct=Decimal("45.0"),
        ytd_goal_pct=Decimal("43.3"),
        mtd_labor_pay=Decimal("1800.00"),
        mtd_labor_pct=Decimal("40.0"),
        month_labels=["Oct 2025", "Sep 2026"],
        month_revenues=[1000.0, 4500.0],
        month_goal=10000.0,
        lead_sources=[NamedAmount(key="referral", label="Referral", count=5, revenue=Decimal("2000"))],
        neighborhoods=[NamedAmount(key="Millcreek", label="Millcreek", count=3, revenue=Decimal("900"))],
        pipeline=[NamedAmount(key="active", label="Active", count=20)],
        rebook_items=[
            RebookItem(
                customer_id=9,
                name="Jane",
                next_service_due=date(2026, 9, 10),
                usual_price=Decimal("250.00"),
                overdue=True,
            )
        ],
        rebook_opportunity=Decimal("250.00"),
        rebook_overdue_count=1,
        rebook_soon_count=0,
        unlinked_job_ratio=Decimal("0.05"),
        show_unlinked_warning=False,
    )

    html = env.get_template("dashboard.html").render(
        static_version="test",
        user={"business_name": "Test Co", "id": 1},
        tab="stats",
        stats=stats,
        draft_sessions=[],
        event_deleted=False,
        goal_errors=[],
        goals_saved=False,
    )
    assert 'href="/?tab=stats"' in html
    assert 'href="/?tab=overview"' in html
    assert "Revenue goals" in html
    assert 'id="chart-revenue"' in html
    assert 'id="chart-lead-source"' in html
    assert 'id="chart-neighborhood"' in html
    assert 'id="chart-pipeline"' in html
    assert "chart.js" in html
    assert "Rebook opportunities" in html
    assert 'href="/customers/9"' in html
    assert 'action="/stats/goals"' in html


def test_dashboard_overview_tab_keeps_welcome():
    templates_dir = Path(__file__).resolve().parents[2] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    html = env.get_template("dashboard.html").render(
        static_version="test",
        user={"business_name": "Test Co", "id": 1},
        tab="overview",
        stats=None,
        draft_sessions=[],
        event_deleted=False,
        goal_errors=[],
        goals_saved=False,
    )
    assert "Welcome, Test Co." in html
    assert "Begin Payroll" in html
    assert 'id="chart-revenue"' not in html
