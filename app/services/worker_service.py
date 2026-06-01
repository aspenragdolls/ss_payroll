from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import Role
from app.models.worker import Worker


def list_workers(db: Session, user_id: int, active_only: bool = False) -> list[Worker]:
    stmt = select(Worker).where(Worker.user_id == user_id).order_by(Worker.name)
    if active_only:
        stmt = stmt.where(Worker.is_active.is_(True))
    return list(db.scalars(stmt))


def get_worker(db: Session, user_id: int, worker_id: int) -> Worker | None:
    return db.scalar(
        select(Worker).where(Worker.user_id == user_id, Worker.id == worker_id)
    )


def create_worker(
    db: Session,
    user_id: int,
    *,
    name: str,
    roles: list[str],
    is_active: bool = True,
    labor_pay_type: str | None = None,
    labor_percentage_tier: str | None = None,
    hourly_rate: Decimal | None = None,
    notes: str | None = None,
) -> Worker:
    worker = Worker(
        user_id=user_id,
        name=name.strip(),
        is_active=is_active,
        roles=roles,
        labor_pay_type=labor_pay_type,
        labor_percentage_tier=labor_percentage_tier,
        hourly_rate=hourly_rate,
        notes=notes,
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def update_worker(db: Session, worker: Worker, **fields) -> Worker:
    for key, value in fields.items():
        setattr(worker, key, value)
    db.commit()
    db.refresh(worker)
    return worker


def workers_with_role(workers: list[Worker], role: Role) -> list[Worker]:
    return [w for w in workers if w.is_active and role.value in (w.roles or [])]
