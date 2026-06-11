from datetime import date
from decimal import Decimal

from app.domain.enums import PayType, Role, Tier
from app.domain.payroll_calculator import calculate
from app.domain.schemas import CalcAssignment, CalcInput, CalcJob


def _job(job_id: str, price: str, day: str = "2025-05-01", tips: str = "0") -> CalcJob:
    return CalcJob(
        job_id=job_id,
        ticket_price=Decimal(price),
        job_date=date.fromisoformat(day),
        tips=Decimal(tips),
    )


def _assign(
    job_id: str,
    worker_id: str,
    *,
    roles: set[Role] | None = None,
    pay_type: PayType | None = None,
    tier: Tier | None = None,
    hourly_rate: str | None = None,
    adjustment: str = "0",
) -> CalcAssignment:
    return CalcAssignment(
        job_id=job_id,
        worker_id=worker_id,
        roles=roles or {Role.LABOR},
        pay_type=pay_type,
        tier=tier,
        hourly_rate=Decimal(hourly_rate) if hourly_rate else None,
        adjustment=Decimal(adjustment),
    )


def _worker_total(result, worker_id: str):
    return next(w for w in result.worker_totals if w.worker_id == worker_id)


def _job_result(result, job_id: str, worker_id: str):
    return next(
        r for r in result.job_results if r.job_id == job_id and r.worker_id == worker_id
    )


def test_labor_pool_is_sixty_percent_of_ticket():
    """Labor pool must be 60% of ticket price, not 80%."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "500")],
            assignments=[
                _assign("j1", "w1", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
            ],
            daily_hours={},
        )
    )
    jr = _job_result(result, "j1", "w1")
    assert jr.labor_pool == Decimal("300.00")
    assert jr.percentage_component == Decimal("300.00")


def test_commission_only_no_labor_workers():
    """Commission only (no workers) — defaults to owner."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "500")],
            assignments=[],
            daily_hours={},
            owner_worker_id="owner",
        )
    )
    owner = _worker_total(result, "owner")
    assert owner.commission_total == Decimal("100.00")
    assert owner.labor_total == Decimal("0")
    assert owner.total_pay == Decimal("100.00")
    assert any(w.code == "no_labor_assigned" for w in result.warnings)


def test_commission_plus_worker_labor():
    """Commission + worker labor on same job."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "500")],
            assignments=[
                _assign("j1", "w1", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                CalcAssignment(job_id="j1", worker_id="s1", roles={Role.SALES}),
            ],
            daily_hours={},
        )
    )
    w1 = _worker_total(result, "w1")
    s1 = _worker_total(result, "s1")
    assert w1.percentage_total == Decimal("300.00")
    assert s1.commission_total == Decimal("100.00")


def test_worker_and_salesman_dual_pay():
    """Worker + salesman dual pay on same job."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "500")],
            assignments=[
                _assign(
                    "j1",
                    "dual",
                    roles={Role.LABOR, Role.SALES},
                    pay_type=PayType.PERCENTAGE,
                    tier=Tier.TIER_2,
                ),
            ],
            daily_hours={},
        )
    )
    dual = _worker_total(result, "dual")
    assert dual.percentage_total == Decimal("300.00")
    assert dual.commission_total == Decimal("100.00")
    assert dual.total_pay == Decimal("400.00")


def test_mixed_hourly_percentage_and_commission():
    """Mixed hourly/percentage + commission."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "500")],
            assignments=[
                _assign("j1", "hourly", pay_type=PayType.HOURLY, hourly_rate="20"),
                _assign("j1", "pct", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                CalcAssignment(job_id="j1", worker_id="sales", roles={Role.SALES}),
            ],
            daily_hours={("hourly", date(2025, 5, 1)): Decimal("3")},
        )
    )
    hourly = _worker_total(result, "hourly")
    pct = _worker_total(result, "pct")
    sales = _worker_total(result, "sales")
    assert hourly.hourly_total == Decimal("60.00")
    assert pct.percentage_total == Decimal("240.00")
    assert sales.commission_total == Decimal("100.00")


def test_daily_hours_split_across_multiple_jobs():
    """Daily hours split evenly across assigned jobs."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "300"), _job("j2", "300")],
            assignments=[
                _assign("j1", "hourly", pay_type=PayType.HOURLY, hourly_rate="20"),
                _assign("j2", "hourly", pay_type=PayType.HOURLY, hourly_rate="20"),
            ],
            daily_hours={("hourly", date(2025, 5, 1)): Decimal("6")},
        )
    )
    r1 = _job_result(result, "j1", "hourly")
    r2 = _job_result(result, "j2", "hourly")
    assert r1.hours_assigned == Decimal("3")
    assert r2.hours_assigned == Decimal("3")
    assert r1.hourly_component == Decimal("60.00")
    assert r2.hourly_component == Decimal("60.00")
    hourly = _worker_total(result, "hourly")
    assert hourly.hourly_total == Decimal("120.00")


def test_hourly_pay_exceeds_labor_pool():
    """Hourly pay exceeding labor pool triggers warning."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "100")],
            assignments=[
                _assign("j1", "hourly", pay_type=PayType.HOURLY, hourly_rate="50"),
            ],
            daily_hours={("hourly", date(2025, 5, 1)): Decimal("2")},
        )
    )
    assert any(w.code == "hourly_exceeds_labor_pool" for w in result.warnings)
    hourly = _worker_total(result, "hourly")
    assert hourly.hourly_total == Decimal("100.00")


def test_overrides_via_adjustment():
    """Manual adjustment amounts applied to worker pay."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "500")],
            assignments=[
                _assign(
                    "j1",
                    "w1",
                    pay_type=PayType.PERCENTAGE,
                    tier=Tier.TIER_1,
                    adjustment="25.50",
                ),
            ],
            daily_hours={},
        )
    )
    w1 = _worker_total(result, "w1")
    assert w1.percentage_total == Decimal("300.00")
    assert w1.adjustment_total == Decimal("25.50")
    assert w1.total_pay == Decimal("325.50")


def test_edge_rounding():
    """Tier split with rounding remainder assigned deterministically."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "100")],
            assignments=[
                _assign("j1", "t1", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                _assign("j1", "t2", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_2),
            ],
            daily_hours={},
        )
    )
    t1 = _worker_total(result, "t1")
    t2 = _worker_total(result, "t2")
    assert t1.percentage_total + t2.percentage_total == Decimal("60.00")
    assert t1.percentage_total == Decimal("32.88")
    assert t2.percentage_total == Decimal("27.12")


def test_multiple_jobs_per_day():
    """Multiple jobs per day aggregate worker totals correctly."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "200"), _job("j2", "300"), _job("j3", "500")],
            assignments=[
                _assign("j1", "w1", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                _assign("j2", "w1", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                _assign("j3", "w1", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                CalcAssignment(job_id="j1", worker_id="s1", roles={Role.SALES}),
                CalcAssignment(job_id="j2", worker_id="s1", roles={Role.SALES}),
            ],
            daily_hours={},
        )
    )
    w1 = _worker_total(result, "w1")
    s1 = _worker_total(result, "s1")
    assert w1.percentage_total == Decimal("600.00")  # 120 + 180 + 300
    assert s1.commission_total == Decimal("100.00")  # 40 + 60 from j1 and j2


def test_tier_distribution_with_mixed_pay():
    """Tier distribution after hourly subtraction."""
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "500")],
            assignments=[
                _assign("j1", "hourly", pay_type=PayType.HOURLY, hourly_rate="20"),
                _assign("j1", "t1", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                _assign("j1", "t2", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_2),
            ],
            daily_hours={("hourly", date(2025, 5, 1)): Decimal("6")},
        )
    )
    hourly = _worker_total(result, "hourly")
    t1 = _worker_total(result, "t1")
    t2 = _worker_total(result, "t2")
    assert hourly.hourly_total == Decimal("120.00")
    assert t1.percentage_total == Decimal("98.63")
    assert t2.percentage_total == Decimal("81.37")
    assert t1.percentage_total + t2.percentage_total + hourly.hourly_total == Decimal("300.00")


def test_tips_split_evenly_among_labor_workers():
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "500", tips="30")],
            assignments=[
                _assign("j1", "w1", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                _assign("j1", "w2", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
            ],
            daily_hours={},
        )
    )
    w1 = _job_result(result, "j1", "w1")
    w2 = _job_result(result, "j1", "w2")
    assert w1.tips_component == Decimal("15.00")
    assert w2.tips_component == Decimal("15.00")
    assert w1.final_worker_job_pay == Decimal("165.00")  # 150 pct + 15 tips
    t1 = _worker_total(result, "w1")
    t2 = _worker_total(result, "w2")
    assert t1.tips_total == Decimal("15.00")
    assert t2.tips_total == Decimal("15.00")
    assert t1.labor_total == Decimal("165.00")


def test_tips_not_given_to_sales_only():
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "300", tips="20")],
            assignments=[
                _assign("j1", "labor", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                CalcAssignment(job_id="j1", worker_id="sales", roles={Role.SALES}),
            ],
            daily_hours={},
        )
    )
    labor = _job_result(result, "j1", "labor")
    sales = _job_result(result, "j1", "sales")
    assert labor.tips_component == Decimal("20.00")
    assert sales.tips_component == Decimal("0")


def test_tips_rounding_remainder_on_last_worker():
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "100", tips="10")],
            assignments=[
                _assign("j1", "w1", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                _assign("j1", "w2", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
                _assign("j1", "w3", pay_type=PayType.PERCENTAGE, tier=Tier.TIER_1),
            ],
            daily_hours={},
        )
    )
    tips = sum(
        _job_result(result, "j1", w).tips_component for w in ("w1", "w2", "w3")
    )
    assert tips == Decimal("10.00")


def test_multiple_salesmen_split_commission():
    result = calculate(
        CalcInput(
            jobs=[_job("j1", "300")],
            assignments=[
                CalcAssignment(job_id="j1", worker_id="s1", roles={Role.SALES}),
                CalcAssignment(job_id="j1", worker_id="s2", roles={Role.SALES}),
            ],
            daily_hours={},
            owner_worker_id="owner",
        )
    )
    s1 = _worker_total(result, "s1")
    s2 = _worker_total(result, "s2")
    assert s1.commission_total == Decimal("30.00")
    assert s2.commission_total == Decimal("30.00")
