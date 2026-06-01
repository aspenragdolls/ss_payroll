from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from app.domain.enums import PayType, Role, Tier
from app.domain.schemas import (
    CalcAssignment,
    CalcInput,
    CalcJob,
    CalcJobWorkerResult,
    CalcResult,
    CalcWarning,
    CalcWorkerTotal,
)

LABOR_POOL_RATE = Decimal("0.60")
COMMISSION_POOL_RATE = Decimal("0.20")
CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def _split_by_weight(amount: Decimal, items: list[tuple[str, Decimal]]) -> dict[str, Decimal]:
    if not items:
        return {}
    total_weight = sum(weight for _, weight in items)
    if total_weight == 0:
        return {worker_id: Decimal("0") for worker_id, _ in items}

    raw = {worker_id: amount * weight / total_weight for worker_id, weight in items}
    rounded = {worker_id: _money(value) for worker_id, value in raw.items()}
    remainder = _money(amount) - sum(rounded.values())
    if remainder != 0:
        # Assign rounding remainder to highest-weight worker for determinism.
        top_worker = max(items, key=lambda item: item[1])[0]
        rounded[top_worker] += remainder
    return rounded


def _jobs_by_id(jobs: list[CalcJob]) -> dict[str, CalcJob]:
    return {job.job_id: job for job in jobs}


def _assignments_for_job(assignments: list[CalcAssignment], job_id: str) -> list[CalcAssignment]:
    return [a for a in assignments if a.job_id == job_id]


def _labor_assignments(assignments: list[CalcAssignment]) -> list[CalcAssignment]:
    return [a for a in assignments if Role.LABOR in a.roles]


def _sales_assignments(assignments: list[CalcAssignment]) -> list[CalcAssignment]:
    return [a for a in assignments if Role.SALES in a.roles]


def _hourly_job_counts(
    jobs: list[CalcJob],
    assignments: list[CalcAssignment],
    daily_hours: dict[tuple[str, date], Decimal],
) -> dict[tuple[str, str, date], Decimal]:
    """Return hours per (worker_id, job_id, date) for hourly labor workers."""
    jobs_by_date: dict[tuple[str, date], list[str]] = defaultdict(list)
    for assignment in _labor_assignments(assignments):
        if assignment.pay_type != PayType.HOURLY:
            continue
        job = next(j for j in jobs if j.job_id == assignment.job_id)
        jobs_by_date[(assignment.worker_id, job.job_date)].append(assignment.job_id)

    hours_map: dict[tuple[str, str, date], Decimal] = {}
    for (worker_id, job_date), job_ids in jobs_by_date.items():
        unique_jobs = sorted(set(job_ids))
        total_hours = daily_hours.get((worker_id, job_date), Decimal("0"))
        if not unique_jobs:
            continue
        per_job = total_hours / Decimal(len(unique_jobs))
        for job_id in unique_jobs:
            hours_map[(worker_id, job_id, job_date)] = per_job
    return hours_map


def calculate(calc_input: CalcInput) -> CalcResult:
    jobs = calc_input.jobs
    assignments = calc_input.assignments
    daily_hours = calc_input.daily_hours
    owner_worker_id = calc_input.owner_worker_id

    warnings: list[CalcWarning] = []
    job_results: list[CalcJobWorkerResult] = []
    jobs_lookup = _jobs_by_id(jobs)
    hours_map = _hourly_job_counts(jobs, assignments, daily_hours)

    per_worker_totals: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {
            "total_pay": Decimal("0"),
            "labor_total": Decimal("0"),
            "commission_total": Decimal("0"),
            "hourly_total": Decimal("0"),
            "percentage_total": Decimal("0"),
            "adjustment_total": Decimal("0"),
        }
    )

    for job in jobs:
        job_assignments = _assignments_for_job(assignments, job.job_id)
        labor_assignments = [a for a in job_assignments if Role.LABOR in a.roles]
        sales_assignments = [a for a in job_assignments if Role.SALES in a.roles]

        if job.ticket_price <= 0:
            warnings.append(
                CalcWarning(
                    code="missing_ticket_price",
                    message=f"Job {job.job_id} has invalid or missing ticket price.",
                    job_id=job.job_id,
                )
            )

        labor_pool = _money(job.ticket_price * LABOR_POOL_RATE)
        commission_pool = _money(job.ticket_price * COMMISSION_POOL_RATE)

        if not labor_assignments:
            warnings.append(
                CalcWarning(
                    code="no_labor_assigned",
                    message=f"No labor workers assigned to job {job.job_id}.",
                    job_id=job.job_id,
                )
            )

        hourly_payments: dict[str, Decimal] = {}
        total_hourly = Decimal("0")

        for assignment in labor_assignments:
            if assignment.pay_type == PayType.HOURLY:
                if assignment.hourly_rate is None:
                    warnings.append(
                        CalcWarning(
                            code="missing_hourly_rate",
                            message=f"Hourly worker {assignment.worker_id} missing rate on job {job.job_id}.",
                            job_id=job.job_id,
                            worker_id=assignment.worker_id,
                        )
                    )
                    continue
                hours = hours_map.get(
                    (assignment.worker_id, job.job_id, job.job_date), Decimal("0")
                )
                pay = _money(hours * assignment.hourly_rate)
                hourly_payments[assignment.worker_id] = pay
                total_hourly += pay

        total_hourly = _money(total_hourly)
        if total_hourly > labor_pool:
            warnings.append(
                CalcWarning(
                    code="hourly_exceeds_labor_pool",
                    message=(
                        f"Hourly pay (${total_hourly}) exceeds labor pool (${labor_pool}) "
                        f"for job {job.job_id}."
                    ),
                    job_id=job.job_id,
                )
            )

        remaining_labor = _money(max(labor_pool - total_hourly, Decimal("0")))

        percentage_workers: list[tuple[str, Decimal]] = []
        for assignment in labor_assignments:
            if assignment.pay_type == PayType.PERCENTAGE:
                if assignment.tier is None:
                    warnings.append(
                        CalcWarning(
                            code="missing_tier",
                            message=(
                                f"Percentage worker {assignment.worker_id} missing tier "
                                f"on job {job.job_id}."
                            ),
                            job_id=job.job_id,
                            worker_id=assignment.worker_id,
                        )
                    )
                    continue
                percentage_workers.append((assignment.worker_id, assignment.tier.weight))

        percentage_payments = _split_by_weight(remaining_labor, percentage_workers)

        commission_payments: dict[str, Decimal] = {}
        if sales_assignments:
            per_sales = _money(commission_pool / Decimal(len(sales_assignments)))
            allocated = Decimal("0")
            for i, assignment in enumerate(sales_assignments):
                if i == len(sales_assignments) - 1:
                    pay = _money(commission_pool - allocated)
                else:
                    pay = per_sales
                    allocated += pay
                commission_payments[assignment.worker_id] = pay
        elif owner_worker_id:
            commission_payments[owner_worker_id] = commission_pool
        else:
            warnings.append(
                CalcWarning(
                    code="no_commission_assignee",
                    message=f"No salesman or owner assigned for commission on job {job.job_id}.",
                    job_id=job.job_id,
                )
            )

        processed_workers: set[str] = set()

        for assignment in job_assignments:
            worker_id = assignment.worker_id
            hourly = hourly_payments.get(worker_id, Decimal("0"))
            percentage = percentage_payments.get(worker_id, Decimal("0"))
            commission = commission_payments.get(worker_id, Decimal("0"))
            adjustment = _money(assignment.adjustment)
            hours_assigned = Decimal("0")

            if Role.LABOR in assignment.roles and assignment.pay_type == PayType.HOURLY:
                hours_assigned = hours_map.get(
                    (worker_id, job.job_id, job.job_date), Decimal("0")
                )

            labor_component = _money(hourly + percentage)
            final_pay = _money(hourly + percentage + commission + adjustment)

            job_results.append(
                CalcJobWorkerResult(
                    job_id=job.job_id,
                    worker_id=worker_id,
                    ticket_price=job.ticket_price,
                    labor_pool=labor_pool,
                    hourly_component=hourly,
                    percentage_component=percentage,
                    commission_component=commission,
                    adjustment_component=adjustment,
                    final_worker_job_pay=final_pay,
                    hours_assigned=hours_assigned,
                )
            )
            processed_workers.add(worker_id)

            per_worker_totals[worker_id]["hourly_total"] += hourly
            per_worker_totals[worker_id]["percentage_total"] += percentage
            per_worker_totals[worker_id]["commission_total"] += commission
            per_worker_totals[worker_id]["adjustment_total"] += adjustment
            per_worker_totals[worker_id]["labor_total"] += labor_component
            per_worker_totals[worker_id]["total_pay"] += final_pay

        # Owner commission when not already in job_assignments
        for worker_id, commission in commission_payments.items():
            if worker_id in processed_workers:
                continue
            job_results.append(
                CalcJobWorkerResult(
                    job_id=job.job_id,
                    worker_id=worker_id,
                    ticket_price=job.ticket_price,
                    labor_pool=labor_pool,
                    hourly_component=Decimal("0"),
                    percentage_component=Decimal("0"),
                    commission_component=commission,
                    adjustment_component=Decimal("0"),
                    final_worker_job_pay=commission,
                    hours_assigned=Decimal("0"),
                )
            )
            per_worker_totals[worker_id]["commission_total"] += commission
            per_worker_totals[worker_id]["total_pay"] += commission

    worker_totals = [
        CalcWorkerTotal(
            worker_id=worker_id,
            total_pay=_money(totals["total_pay"]),
            labor_total=_money(totals["labor_total"]),
            commission_total=_money(totals["commission_total"]),
            hourly_total=_money(totals["hourly_total"]),
            percentage_total=_money(totals["percentage_total"]),
            adjustment_total=_money(totals["adjustment_total"]),
        )
        for worker_id, totals in sorted(per_worker_totals.items())
    ]

    snapshot = {
        "jobs": [
            {
                "job_id": j.job_id,
                "ticket_price": str(j.ticket_price),
                "job_date": j.job_date.isoformat(),
            }
            for j in jobs
        ],
        "assignments": [
            {
                "job_id": a.job_id,
                "worker_id": a.worker_id,
                "roles": [r.value for r in a.roles],
                "pay_type": a.pay_type.value if a.pay_type else None,
                "tier": a.tier.value if a.tier else None,
                "hourly_rate": str(a.hourly_rate) if a.hourly_rate is not None else None,
                "adjustment": str(a.adjustment),
            }
            for a in assignments
        ],
        "daily_hours": {
            f"{worker_id}:{day.isoformat()}": str(hours)
            for (worker_id, day), hours in daily_hours.items()
        },
        "owner_worker_id": owner_worker_id,
        "job_results": [
            {
                "job_id": r.job_id,
                "worker_id": r.worker_id,
                "final_worker_job_pay": str(r.final_worker_job_pay),
                "hourly_component": str(r.hourly_component),
                "percentage_component": str(r.percentage_component),
                "commission_component": str(r.commission_component),
                "adjustment_component": str(r.adjustment_component),
                "hours_assigned": str(r.hours_assigned),
            }
            for r in job_results
        ],
    }

    return CalcResult(
        job_results=job_results,
        worker_totals=worker_totals,
        warnings=warnings,
        calculation_snapshot=snapshot,
    )
