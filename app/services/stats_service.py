from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.domain.enums import PayrollStatus
from app.models.business_goals import BusinessGoals
from app.models.customer import ACTIVE_STATUSES, Customer
from app.models.job import Job
from app.models.payroll import PayrollBatch, PayrollResult
from app.services.customer_service import CUSTOMER_STATUSES, LEAD_SOURCES

ZERO = Decimal("0.00")
UNLINKED_JOB_WARN_RATIO = Decimal("0.20")
TOP_NEIGHBORHOODS = 8
REBOOK_SOON_DAYS = 30


@dataclass
class BusinessGoalValues:
    monthly_revenue_goal: Decimal | None = None
    yearly_revenue_goal: Decimal | None = None


@dataclass
class NamedAmount:
    key: str
    label: str
    count: int = 0
    revenue: Decimal = ZERO


@dataclass
class RebookItem:
    customer_id: int
    name: str
    next_service_due: date
    usual_price: Decimal | None
    overdue: bool


@dataclass
class StatsDashboard:
    today: date
    month_start: date
    year_start: date
    window_start: date

    monthly_revenue_goal: Decimal | None
    yearly_revenue_goal: Decimal | None

    mtd_revenue: Decimal
    ytd_revenue: Decimal
    mtd_job_count: int
    ytd_job_count: int
    mtd_avg_ticket: Decimal | None
    ytd_avg_ticket: Decimal | None
    mtd_goal_pct: Decimal | None
    ytd_goal_pct: Decimal | None
    mtd_labor_pay: Decimal | None
    mtd_labor_pct: Decimal | None

    month_labels: list[str] = field(default_factory=list)
    month_revenues: list[float] = field(default_factory=list)
    month_goal: float | None = None

    lead_sources: list[NamedAmount] = field(default_factory=list)
    neighborhoods: list[NamedAmount] = field(default_factory=list)
    pipeline: list[NamedAmount] = field(default_factory=list)

    rebook_items: list[RebookItem] = field(default_factory=list)
    rebook_opportunity: Decimal = ZERO
    rebook_overdue_count: int = 0
    rebook_soon_count: int = 0

    unlinked_job_ratio: Decimal = ZERO
    show_unlinked_warning: bool = False

    def to_template_dict(self) -> dict[str, Any]:
        """JSON-friendly payload for charts + template display."""
        return {
            "today": self.today.isoformat(),
            "month_start": self.month_start.isoformat(),
            "year_start": self.year_start.isoformat(),
            "window_start": self.window_start.isoformat(),
            "monthly_revenue_goal": _money_or_none(self.monthly_revenue_goal),
            "yearly_revenue_goal": _money_or_none(self.yearly_revenue_goal),
            "mtd_revenue": _money(self.mtd_revenue),
            "ytd_revenue": _money(self.ytd_revenue),
            "mtd_job_count": self.mtd_job_count,
            "ytd_job_count": self.ytd_job_count,
            "mtd_avg_ticket": _money_or_none(self.mtd_avg_ticket),
            "ytd_avg_ticket": _money_or_none(self.ytd_avg_ticket),
            "mtd_goal_pct": _pct_or_none(self.mtd_goal_pct),
            "ytd_goal_pct": _pct_or_none(self.ytd_goal_pct),
            "mtd_labor_pay": _money_or_none(self.mtd_labor_pay),
            "mtd_labor_pct": _pct_or_none(self.mtd_labor_pct),
            "charts": {
                "month_labels": self.month_labels,
                "month_revenues": self.month_revenues,
                "month_goal": self.month_goal,
                "lead_source_labels": [s.label for s in self.lead_sources],
                "lead_source_revenues": [float(s.revenue) for s in self.lead_sources],
                "lead_source_counts": [s.count for s in self.lead_sources],
                "neighborhood_labels": [n.label for n in self.neighborhoods],
                "neighborhood_revenues": [float(n.revenue) for n in self.neighborhoods],
                "neighborhood_counts": [n.count for n in self.neighborhoods],
                "pipeline_labels": [p.label for p in self.pipeline],
                "pipeline_counts": [p.count for p in self.pipeline],
            },
            "rebook_opportunity": _money(self.rebook_opportunity),
            "rebook_overdue_count": self.rebook_overdue_count,
            "rebook_soon_count": self.rebook_soon_count,
            "rebook_items": [
                {
                    "customer_id": item.customer_id,
                    "name": item.name,
                    "next_service_due": item.next_service_due.isoformat(),
                    "usual_price": _money_or_none(item.usual_price),
                    "overdue": item.overdue,
                }
                for item in self.rebook_items
            ],
            "unlinked_job_ratio": float(self.unlinked_job_ratio),
            "show_unlinked_warning": self.show_unlinked_warning,
        }


def _money(value: Decimal) -> str:
    return f"{value.quantize(ZERO, rounding=ROUND_HALF_UP):.2f}"


def _money_or_none(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _money(value)


def _pct_or_none(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _as_decimal(value: Any) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def today_for_timezone(tz_name: str | None, *, now: datetime | None = None) -> date:
    try:
        tz = ZoneInfo(tz_name or "America/New_York")
    except Exception:
        tz = ZoneInfo("America/New_York")
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)
    return current.date()


def month_window_start(today: date) -> date:
    """First day of the month that starts the trailing 12-month window."""
    year = today.year
    month = today.month - 11
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def iter_month_starts(window_start: date, today: date) -> list[date]:
    months: list[date] = []
    year, month = window_start.year, window_start.month
    end_year, end_month = today.year, today.month
    while (year, month) <= (end_year, end_month):
        months.append(date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def goal_progress_pct(actual: Decimal, goal: Decimal | None) -> Decimal | None:
    if goal is None or goal <= 0:
        return None
    return (actual / goal * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def average_ticket(revenue: Decimal, job_count: int) -> Decimal | None:
    if job_count <= 0:
        return None
    return (revenue / Decimal(job_count)).quantize(ZERO, rounding=ROUND_HALF_UP)


def _revenue_between(db: Session, user_id: int, start: date, end: date) -> tuple[Decimal, int]:
    stmt = (
        select(
            func.coalesce(func.sum(Job.ticket_price), 0),
            func.count(Job.id),
        )
        .select_from(Job)
        .join(PayrollBatch, Job.payroll_batch_id == PayrollBatch.id)
        .where(
            Job.user_id == user_id,
            PayrollBatch.status == PayrollStatus.FINALIZED.value,
            Job.job_date >= start,
            Job.job_date <= end,
        )
    )
    row = db.execute(stmt).one()
    return _as_decimal(row[0]), int(row[1] or 0)


def _monthly_revenue_series(
    db: Session, user_id: int, window_start: date, today: date
) -> dict[date, Decimal]:
    month_expr = func.date_trunc("month", Job.job_date)
    stmt = (
        select(
            month_expr.label("month"),
            func.coalesce(func.sum(Job.ticket_price), 0).label("revenue"),
        )
        .select_from(Job)
        .join(PayrollBatch, Job.payroll_batch_id == PayrollBatch.id)
        .where(
            Job.user_id == user_id,
            PayrollBatch.status == PayrollStatus.FINALIZED.value,
            Job.job_date >= window_start,
            Job.job_date <= today,
        )
        .group_by(month_expr)
        .order_by(month_expr)
    )
    series: dict[date, Decimal] = {m: ZERO for m in iter_month_starts(window_start, today)}
    for month_val, revenue in db.execute(stmt):
        if month_val is None:
            continue
        if isinstance(month_val, datetime):
            key = date(month_val.year, month_val.month, 1)
        elif isinstance(month_val, date):
            key = date(month_val.year, month_val.month, 1)
        else:
            continue
        if key in series:
            series[key] = _as_decimal(revenue)
    return series


def _mtd_labor_pay(db: Session, user_id: int, month_start: date, today: date) -> Decimal | None:
    count_stmt = select(func.count(PayrollBatch.id)).where(
        PayrollBatch.user_id == user_id,
        PayrollBatch.status == PayrollStatus.FINALIZED.value,
        PayrollBatch.pay_date >= month_start,
        PayrollBatch.pay_date <= today,
    )
    if int(db.scalar(count_stmt) or 0) == 0:
        return None

    stmt = (
        select(func.coalesce(func.sum(PayrollResult.total_pay), 0))
        .select_from(PayrollResult)
        .join(PayrollBatch, PayrollResult.payroll_batch_id == PayrollBatch.id)
        .where(
            PayrollBatch.user_id == user_id,
            PayrollBatch.status == PayrollStatus.FINALIZED.value,
            PayrollBatch.pay_date >= month_start,
            PayrollBatch.pay_date <= today,
        )
    )
    return _as_decimal(db.scalar(stmt))


def _unlinked_ratio(db: Session, user_id: int, window_start: date, today: date) -> Decimal:
    stmt = (
        select(
            func.count(Job.id),
            func.coalesce(
                func.sum(case((Job.customer_id.is_(None), 1), else_=0)),
                0,
            ),
        )
        .select_from(Job)
        .join(PayrollBatch, Job.payroll_batch_id == PayrollBatch.id)
        .where(
            Job.user_id == user_id,
            PayrollBatch.status == PayrollStatus.FINALIZED.value,
            Job.job_date >= window_start,
            Job.job_date <= today,
        )
    )
    total, unlinked = db.execute(stmt).one()
    total_n = int(total or 0)
    if total_n == 0:
        return ZERO
    return (Decimal(int(unlinked or 0)) / Decimal(total_n)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _customer_spend_by_field(
    db: Session,
    user_id: int,
    *,
    field_name: str,
    window_start: date,
    today: date,
) -> list[tuple[str | None, int, Decimal]]:
    field_col = getattr(Customer, field_name)
    spend = func.coalesce(
        func.sum(
            case(
                (
                    and_(
                        PayrollBatch.status == PayrollStatus.FINALIZED.value,
                        Job.job_date >= window_start,
                        Job.job_date <= today,
                    ),
                    Job.ticket_price,
                ),
                else_=None,
            )
        ),
        0,
    )
    stmt = (
        select(
            field_col,
            func.count(func.distinct(Customer.id)),
            spend,
        )
        .select_from(Customer)
        .outerjoin(Job, Job.customer_id == Customer.id)
        .outerjoin(PayrollBatch, Job.payroll_batch_id == PayrollBatch.id)
        .where(Customer.user_id == user_id, Customer.is_active.is_(True))
        .group_by(field_col)
    )
    rows = db.execute(stmt).all()
    return [(row[0], int(row[1] or 0), _as_decimal(row[2])) for row in rows]


def _lead_source_breakdown(
    db: Session, user_id: int, window_start: date, today: date
) -> list[NamedAmount]:
    by_key: dict[str, NamedAmount] = {
        key: NamedAmount(key=key, label=label) for key, label in LEAD_SOURCES
    }
    unknown = NamedAmount(key="", label="Unspecified")

    for raw_key, count, revenue in _customer_spend_by_field(
        db, user_id, field_name="lead_source", window_start=window_start, today=today
    ):
        key = (raw_key or "").strip()
        if key in by_key:
            by_key[key].count = count
            by_key[key].revenue = revenue
        else:
            unknown.count += count
            unknown.revenue += revenue

    results = [item for item in by_key.values() if item.count > 0 or item.revenue > 0]
    if unknown.count > 0 or unknown.revenue > 0:
        results.append(unknown)
    results.sort(key=lambda item: (item.revenue, item.count), reverse=True)
    return results


def _neighborhood_breakdown(
    db: Session, user_id: int, window_start: date, today: date
) -> list[NamedAmount]:
    items: list[NamedAmount] = []
    for raw_key, count, revenue in _customer_spend_by_field(
        db, user_id, field_name="neighborhood", window_start=window_start, today=today
    ):
        label = (raw_key or "").strip() or "Unspecified"
        items.append(NamedAmount(key=label, label=label, count=count, revenue=revenue))
    items.sort(key=lambda item: (item.revenue, item.count), reverse=True)
    return items[:TOP_NEIGHBORHOODS]


def _pipeline_breakdown(db: Session, user_id: int) -> list[NamedAmount]:
    stmt = (
        select(Customer.status, func.count(Customer.id))
        .where(Customer.user_id == user_id, Customer.is_active.is_(True))
        .group_by(Customer.status)
    )
    counts = {row[0]: int(row[1] or 0) for row in db.execute(stmt)}
    return [
        NamedAmount(key=key, label=label, count=counts.get(key, 0))
        for key, label in CUSTOMER_STATUSES
    ]


def _rebook_opportunities(db: Session, user_id: int, today: date) -> list[RebookItem]:
    soon_end = today + timedelta(days=REBOOK_SOON_DAYS)
    stmt = (
        select(Customer)
        .where(
            Customer.user_id == user_id,
            Customer.is_active.is_(True),
            Customer.do_not_contact.is_(False),
            Customer.status.in_(tuple(ACTIVE_STATUSES)),
            Customer.next_service_due.is_not(None),
            Customer.next_service_due <= soon_end,
        )
        .order_by(Customer.next_service_due, Customer.name)
    )
    items: list[RebookItem] = []
    for customer in db.scalars(stmt):
        due = customer.next_service_due
        if due is None:
            continue
        items.append(
            RebookItem(
                customer_id=customer.id,
                name=customer.name,
                next_service_due=due,
                usual_price=customer.usual_price,
                overdue=due < today,
            )
        )
    return items


def get_business_goals(db: Session, user_id: int) -> BusinessGoalValues:
    row = db.scalar(select(BusinessGoals).where(BusinessGoals.user_id == user_id))
    if not row:
        return BusinessGoalValues()
    return BusinessGoalValues(
        monthly_revenue_goal=row.monthly_revenue_goal,
        yearly_revenue_goal=row.yearly_revenue_goal,
    )


def parse_goal_amount(raw: str, field_name: str) -> tuple[Decimal | None, str | None]:
    cleaned = raw.strip().replace(",", "").replace("$", "")
    if not cleaned:
        return None, None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None, f"{field_name} must be a valid number."
    if value < 0:
        return None, f"{field_name} cannot be negative."
    return value.quantize(ZERO, rounding=ROUND_HALF_UP), None


def parse_goals_form(
    *,
    monthly_revenue_goal: str,
    yearly_revenue_goal: str,
) -> tuple[BusinessGoalValues | None, list[str]]:
    errors: list[str] = []
    monthly, monthly_err = parse_goal_amount(monthly_revenue_goal, "Monthly goal")
    yearly, yearly_err = parse_goal_amount(yearly_revenue_goal, "Yearly goal")
    if monthly_err:
        errors.append(monthly_err)
    if yearly_err:
        errors.append(yearly_err)
    if errors:
        return None, errors
    return BusinessGoalValues(
        monthly_revenue_goal=monthly,
        yearly_revenue_goal=yearly,
    ), []


def save_business_goals(
    db: Session, user_id: int, values: BusinessGoalValues
) -> BusinessGoals:
    row = db.scalar(select(BusinessGoals).where(BusinessGoals.user_id == user_id))
    if not row:
        row = BusinessGoals(user_id=user_id)
        db.add(row)
    row.monthly_revenue_goal = values.monthly_revenue_goal
    row.yearly_revenue_goal = values.yearly_revenue_goal
    db.commit()
    db.refresh(row)
    return row


def get_dashboard_stats(
    db: Session,
    user_id: int,
    *,
    today: date | None = None,
    timezone_name: str | None = None,
) -> StatsDashboard:
    today = today or today_for_timezone(timezone_name)
    month_start = date(today.year, today.month, 1)
    year_start = date(today.year, 1, 1)
    window_start = month_window_start(today)

    goals = get_business_goals(db, user_id)
    mtd_revenue, mtd_job_count = _revenue_between(db, user_id, month_start, today)
    ytd_revenue, ytd_job_count = _revenue_between(db, user_id, year_start, today)

    monthly_series = _monthly_revenue_series(db, user_id, window_start, today)
    month_starts = iter_month_starts(window_start, today)
    month_labels = [m.strftime("%b %Y") for m in month_starts]
    month_revenues = [float(monthly_series[m]) for m in month_starts]

    mtd_labor = _mtd_labor_pay(db, user_id, month_start, today)
    mtd_labor_pct: Decimal | None = None
    if mtd_labor is not None and mtd_revenue > 0:
        mtd_labor_pct = (mtd_labor / mtd_revenue * Decimal("100")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )

    rebook_items = _rebook_opportunities(db, user_id, today)
    rebook_opportunity = sum(
        (item.usual_price for item in rebook_items if item.usual_price is not None),
        ZERO,
    )
    overdue_count = sum(1 for item in rebook_items if item.overdue)
    soon_count = len(rebook_items) - overdue_count

    unlinked_ratio = _unlinked_ratio(db, user_id, window_start, today)

    return StatsDashboard(
        today=today,
        month_start=month_start,
        year_start=year_start,
        window_start=window_start,
        monthly_revenue_goal=goals.monthly_revenue_goal,
        yearly_revenue_goal=goals.yearly_revenue_goal,
        mtd_revenue=mtd_revenue,
        ytd_revenue=ytd_revenue,
        mtd_job_count=mtd_job_count,
        ytd_job_count=ytd_job_count,
        mtd_avg_ticket=average_ticket(mtd_revenue, mtd_job_count),
        ytd_avg_ticket=average_ticket(ytd_revenue, ytd_job_count),
        mtd_goal_pct=goal_progress_pct(mtd_revenue, goals.monthly_revenue_goal),
        ytd_goal_pct=goal_progress_pct(ytd_revenue, goals.yearly_revenue_goal),
        mtd_labor_pay=mtd_labor,
        mtd_labor_pct=mtd_labor_pct,
        month_labels=month_labels,
        month_revenues=month_revenues,
        month_goal=(
            float(goals.monthly_revenue_goal)
            if goals.monthly_revenue_goal is not None
            else None
        ),
        lead_sources=_lead_source_breakdown(db, user_id, window_start, today),
        neighborhoods=_neighborhood_breakdown(db, user_id, window_start, today),
        pipeline=_pipeline_breakdown(db, user_id),
        rebook_items=rebook_items,
        rebook_opportunity=_as_decimal(rebook_opportunity),
        rebook_overdue_count=overdue_count,
        rebook_soon_count=soon_count,
        unlinked_job_ratio=unlinked_ratio,
        show_unlinked_warning=unlinked_ratio > UNLINKED_JOB_WARN_RATIO,
    )
