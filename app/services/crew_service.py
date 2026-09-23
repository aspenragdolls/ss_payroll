from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.crew import Crew, CrewMember
from app.models.worker import Worker
from app.services.duration_service import crew_schedule_rate


def list_crews(db: Session, user_id: int, active_only: bool = False) -> list[Crew]:
    stmt = (
        select(Crew)
        .where(Crew.user_id == user_id)
        .options(selectinload(Crew.members).selectinload(CrewMember.worker))
        .order_by(Crew.name)
    )
    if active_only:
        stmt = stmt.where(Crew.is_active.is_(True))
    return list(db.scalars(stmt))


def get_crew(db: Session, user_id: int, crew_id: int) -> Crew | None:
    return db.scalar(
        select(Crew)
        .where(Crew.user_id == user_id, Crew.id == crew_id)
        .options(selectinload(Crew.members).selectinload(CrewMember.worker))
    )


def create_crew(
    db: Session,
    user_id: int,
    *,
    name: str,
    apple_calendar_id: str | None = None,
    is_bookable_online: bool = True,
    is_active: bool = True,
    worker_ids: list[int] | None = None,
) -> Crew:
    crew = Crew(
        user_id=user_id,
        name=name.strip(),
        apple_calendar_id=(apple_calendar_id or "").strip() or None,
        is_bookable_online=is_bookable_online,
        is_active=is_active,
    )
    db.add(crew)
    db.flush()
    _sync_members(db, user_id, crew, worker_ids or [])
    db.commit()
    return get_crew(db, user_id, crew.id)  # type: ignore[return-value]


def update_crew(
    db: Session,
    crew: Crew,
    *,
    name: str,
    apple_calendar_id: str | None,
    is_bookable_online: bool,
    is_active: bool,
    worker_ids: list[int] | None,
) -> Crew:
    crew.name = name.strip()
    crew.apple_calendar_id = (apple_calendar_id or "").strip() or None
    crew.is_bookable_online = is_bookable_online
    crew.is_active = is_active
    if worker_ids is not None:
        _sync_members(db, crew.user_id, crew, worker_ids)
    db.commit()
    return get_crew(db, crew.user_id, crew.id)  # type: ignore[return-value]


def _sync_members(db: Session, user_id: int, crew: Crew, worker_ids: list[int]) -> None:
    if worker_ids:
        valid_ids = set(
            db.scalars(
                select(Worker.id).where(Worker.user_id == user_id, Worker.id.in_(worker_ids))
            )
        )
    else:
        valid_ids = set()

    existing = {m.worker_id: m for m in list(crew.members)}
    for worker_id, membership in list(existing.items()):
        if worker_id not in valid_ids:
            db.delete(membership)

    for worker_id in valid_ids:
        if worker_id not in existing:
            db.add(CrewMember(crew_id=crew.id, worker_id=worker_id))


def crew_rate_display(crew: Crew) -> str:
    rate = crew_schedule_rate(crew)
    return f"${rate:.2f}/hr"
