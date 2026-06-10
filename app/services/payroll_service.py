from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.domain.enums import PayType, PayrollStatus, Role, Tier
from app.domain.payroll_calculator import calculate
from app.domain.schemas import CalcAssignment, CalcInput, CalcJob
from app.models.job import Job, JobWorkerAssignment
from app.models.payroll import PayrollBatch, PayrollJobResult, PayrollResult
from app.models.worker import Worker
from app.services.payroll_config_service import get_payroll_rates


def get_batch(db: Session, user_id: int, batch_id: int) -> PayrollBatch | None:
    return db.scalar(
        select(PayrollBatch).where(
            PayrollBatch.id == batch_id, PayrollBatch.user_id == user_id
        )
    )


def get_batch_or_404(db: Session, user_id: int, batch_id: int) -> PayrollBatch:
    batch = get_batch(db, user_id, batch_id)
    if not batch:
        raise ValueError("Payroll batch not found")
    return batch


def ensure_editable(batch: PayrollBatch) -> None:
    if batch.status == PayrollStatus.FINALIZED.value:
        raise PermissionError("Payroll batch is finalized and cannot be edited")


def create_batch(db: Session, user_id: int, pay_date: date | None = None) -> PayrollBatch:
    batch = PayrollBatch(user_id=user_id, status=PayrollStatus.DRAFT.value, pay_date=pay_date)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def list_batches(db: Session, user_id: int, finalized_only: bool = False) -> list[PayrollBatch]:
    stmt = select(PayrollBatch).where(PayrollBatch.user_id == user_id).order_by(PayrollBatch.id.desc())
    if finalized_only:
        stmt = stmt.where(PayrollBatch.status == PayrollStatus.FINALIZED.value)
    return list(db.scalars(stmt))


def get_jobs_for_batch(db: Session, user_id: int, batch_id: int) -> list[Job]:
    return list(
        db.scalars(
            select(Job)
            .where(Job.user_id == user_id, Job.payroll_batch_id == batch_id)
            .order_by(Job.job_date, Job.id)
        )
    )


def get_job(db: Session, user_id: int, job_id: int) -> Job | None:
    return db.scalar(select(Job).where(Job.user_id == user_id, Job.id == job_id))


def create_job_from_draft(
    db: Session,
    user_id: int,
    batch_id: int,
    *,
    customer_name: str | None,
    address: str | None,
    service_description: str | None,
    ticket_price: Decimal | None,
    job_date: date | None,
    source_text: str | None,
    validation_flags: list[str] | None,
    tips: Decimal | None = None,
    is_cash: bool = False,
) -> Job:
    job = Job(
        user_id=user_id,
        payroll_batch_id=batch_id,
        customer_name=customer_name,
        address=address,
        service_description=service_description,
        ticket_price=ticket_price,
        tips=tips,
        is_cash=is_cash,
        job_date=job_date,
        source_text=source_text,
        validation_flags=validation_flags,
        review_status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(db: Session, job: Job, **fields) -> Job:
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    return job


def get_assignments_for_batch(db: Session, batch_id: int) -> list[JobWorkerAssignment]:
    return list(
        db.scalars(
            select(JobWorkerAssignment)
            .join(Job)
            .where(Job.payroll_batch_id == batch_id)
            .options(joinedload(JobWorkerAssignment.worker), joinedload(JobWorkerAssignment.job))
        )
    )


def clear_assignments_for_job(db: Session, job_id: int) -> None:
    db.execute(delete(JobWorkerAssignment).where(JobWorkerAssignment.job_id == job_id))


def save_assignment(
    db: Session,
    job_id: int,
    worker_id: int,
    roles: list[str],
    *,
    effective_pay_type: str | None = None,
    effective_percentage_tier: str | None = None,
    effective_hourly_rate: Decimal | None = None,
    fixed_adjustment_amount: Decimal = Decimal("0"),
    override_reason: str | None = None,
    was_globally_selected: bool = False,
) -> JobWorkerAssignment:
    assignment = JobWorkerAssignment(
        job_id=job_id,
        worker_id=worker_id,
        roles=roles,
        effective_pay_type=effective_pay_type,
        effective_percentage_tier=effective_percentage_tier,
        effective_hourly_rate=effective_hourly_rate,
        fixed_adjustment_amount=fixed_adjustment_amount,
        override_reason=override_reason,
        was_globally_selected=was_globally_selected,
    )
    db.add(assignment)
    return assignment


def compute_hours_assigned(
    db: Session, user_id: int, batch_id: int, daily_hours: dict[tuple[int, date], Decimal]
) -> None:
    jobs = get_jobs_for_batch(db, user_id, batch_id)
    assignments = get_assignments_for_batch(db, batch_id)

    job_dates: dict[int, date | None] = {j.id: j.job_date for j in jobs}
    counts: dict[tuple[int, date], int] = defaultdict(int)

    for a in assignments:
        if Role.LABOR.value not in (a.roles or []):
            continue
        if a.effective_pay_type != PayType.HOURLY.value:
            continue
        jd = job_dates.get(a.job_id)
        if jd:
            counts[(a.worker_id, jd)] += 1

    for a in assignments:
        if Role.LABOR.value not in (a.roles or []):
            a.hours_assigned = None
            continue
        if a.effective_pay_type != PayType.HOURLY.value:
            a.hours_assigned = None
            continue
        jd = job_dates.get(a.job_id)
        if not jd:
            a.hours_assigned = Decimal("0")
            continue
        total = daily_hours.get((a.worker_id, jd), Decimal("0"))
        n = counts.get((a.worker_id, jd), 0)
        a.hours_assigned = total / Decimal(n) if n else Decimal("0")

    db.commit()


def build_calc_input(
    db: Session,
    user_id: int,
    batch_id: int,
    daily_hours: dict[tuple[int, date], Decimal],
    owner_worker_id: int | None,
) -> CalcInput:
    jobs = get_jobs_for_batch(db, user_id, batch_id)
    assignments = get_assignments_for_batch(db, batch_id)

    calc_jobs = [
        CalcJob(
            job_id=str(j.id),
            ticket_price=j.ticket_price or Decimal("0"),
            job_date=j.job_date or date.today(),
            tips=j.tips or Decimal("0"),
        )
        for j in jobs
    ]

    calc_assignments: list[CalcAssignment] = []
    for a in assignments:
        roles = {Role(r) for r in (a.roles or []) if r in {Role.LABOR.value, Role.SALES.value}}
        pay_type = PayType(a.effective_pay_type) if a.effective_pay_type else None
        tier = Tier(a.effective_percentage_tier) if a.effective_percentage_tier else None
        calc_assignments.append(
            CalcAssignment(
                job_id=str(a.job_id),
                worker_id=str(a.worker_id),
                roles=roles,
                pay_type=pay_type,
                tier=tier,
                hourly_rate=a.effective_hourly_rate,
                adjustment=a.fixed_adjustment_amount or Decimal("0"),
            )
        )

    calc_daily = {
        (str(worker_id), day): hours for (worker_id, day), hours in daily_hours.items()
    }

    return CalcInput(
        jobs=calc_jobs,
        assignments=calc_assignments,
        daily_hours=calc_daily,
        owner_worker_id=str(owner_worker_id) if owner_worker_id else None,
        rates=get_payroll_rates(db, user_id),
    )


def run_calculation(
    db: Session,
    user_id: int,
    batch: PayrollBatch,
    daily_hours: dict[tuple[int, date], Decimal],
    owner_worker_id: int | None,
) -> None:
    ensure_editable(batch)
    calc_input = build_calc_input(db, user_id, batch.id, daily_hours, owner_worker_id)
    result = calculate(calc_input)

    db.execute(delete(PayrollResult).where(PayrollResult.payroll_batch_id == batch.id))
    db.execute(delete(PayrollJobResult).where(PayrollJobResult.payroll_batch_id == batch.id))

    for jr in result.job_results:
        db.add(
            PayrollJobResult(
                payroll_batch_id=batch.id,
                job_id=int(jr.job_id),
                worker_id=int(jr.worker_id),
                ticket_price=jr.ticket_price,
                labor_pool=jr.labor_pool,
                hourly_component=jr.hourly_component,
                percentage_component=jr.percentage_component,
                commission_component=jr.commission_component,
                adjustment_component=jr.adjustment_component,
                tips_component=jr.tips_component,
                final_worker_job_pay=jr.final_worker_job_pay,
                calculation_snapshot_json={"hours_assigned": str(jr.hours_assigned)},
            )
        )

    for wt in result.worker_totals:
        db.add(
            PayrollResult(
                payroll_batch_id=batch.id,
                worker_id=int(wt.worker_id),
                total_pay=wt.total_pay,
                labor_total=wt.labor_total,
                commission_total=wt.commission_total,
                hourly_total=wt.hourly_total,
                adjustment_total=wt.adjustment_total,
                calculation_snapshot_json={
                    "percentage_total": str(wt.percentage_total),
                    "tips_total": str(wt.tips_total),
                    "warnings": [
                        {"code": w.code, "message": w.message, "job_id": w.job_id}
                        for w in result.warnings
                    ],
                },
            )
        )

    batch.status = PayrollStatus.REVIEW.value
    db.commit()


def finalize_batch(db: Session, batch: PayrollBatch) -> PayrollBatch:
    if batch.status == PayrollStatus.FINALIZED.value:
        raise PermissionError("Already finalized")
    from datetime import datetime

    batch.status = PayrollStatus.FINALIZED.value
    batch.finalized_at = datetime.utcnow()
    db.commit()
    db.refresh(batch)
    return batch


def get_owner_worker(db: Session, user_id: int) -> Worker | None:
    workers = list(
        db.scalars(
            select(Worker).where(Worker.user_id == user_id, Worker.is_active.is_(True))
        )
    )
    for w in workers:
        if Role.SALES.value in (w.roles or []):
            return w
    return workers[0] if workers else None
