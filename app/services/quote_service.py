"""Service packages, quotes, estimates, and self-schedule eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.customer import Customer
from app.models.job import Job
from app.models.quote import Quote
from app.models.service_package import ServicePackage

QUOTE_STATUSES = (
    ("draft", "Draft"),
    ("sent", "Sent"),
    ("accepted", "Accepted"),
    ("expired", "Expired"),
    ("declined", "Declined"),
)


@dataclass(frozen=True)
class InstantEstimate:
    amount: Decimal
    package_id: int
    package_name: str
    service_type: str
    bookable: bool
    reason: str


@dataclass(frozen=True)
class ScheduleEligibility:
    can_schedule: bool
    price: Decimal | None
    reason: str
    quote_id: int | None = None
    source: str = ""  # quote | history | usual_price


def list_packages(
    db: Session, user_id: int, *, active_only: bool = False
) -> list[ServicePackage]:
    stmt = (
        select(ServicePackage)
        .where(ServicePackage.user_id == user_id)
        .order_by(ServicePackage.name)
    )
    if active_only:
        stmt = stmt.where(ServicePackage.is_active.is_(True))
    return list(db.scalars(stmt))


def get_package(db: Session, user_id: int, package_id: int) -> ServicePackage | None:
    return db.scalar(
        select(ServicePackage).where(
            ServicePackage.user_id == user_id, ServicePackage.id == package_id
        )
    )


def create_package(
    db: Session,
    user_id: int,
    *,
    name: str,
    service_type: str,
    base_price: Decimal,
    description: str | None = None,
    is_active: bool = True,
) -> ServicePackage:
    pkg = ServicePackage(
        user_id=user_id,
        name=name.strip(),
        service_type=service_type,
        base_price=base_price,
        description=description,
        is_active=is_active,
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return pkg


def update_package(db: Session, package: ServicePackage, **fields) -> ServicePackage:
    for key, value in fields.items():
        setattr(package, key, value)
    db.commit()
    db.refresh(package)
    return package


def instant_estimate(
    db: Session,
    user_id: int,
    *,
    package_id: int,
    zip_code: str | None = None,
    neighborhood: str | None = None,
) -> InstantEstimate:
    """Simple estimate: package base price (zip/neighborhood hooks for later)."""
    package = get_package(db, user_id, package_id)
    if not package or not package.is_active:
        raise ValueError("Package not found.")
    amount = Decimal(package.base_price)
    # Placeholder adjustments — keep deterministic and simple.
    _ = (zip_code, neighborhood)
    return InstantEstimate(
        amount=amount,
        package_id=package.id,
        package_name=package.name,
        service_type=package.service_type,
        bookable=False,
        reason="Instant estimates require staff quote acceptance before booking.",
    )


def list_quotes(
    db: Session, user_id: int, *, customer_id: int | None = None
) -> list[Quote]:
    stmt = (
        select(Quote)
        .where(Quote.user_id == user_id)
        .options(selectinload(Quote.customer), selectinload(Quote.package))
        .order_by(Quote.created_at.desc())
    )
    if customer_id:
        stmt = stmt.where(Quote.customer_id == customer_id)
    return list(db.scalars(stmt))


def get_quote(db: Session, user_id: int, quote_id: int) -> Quote | None:
    return db.scalar(
        select(Quote)
        .where(Quote.user_id == user_id, Quote.id == quote_id)
        .options(selectinload(Quote.customer), selectinload(Quote.package))
    )


def create_quote(
    db: Session,
    user_id: int,
    *,
    customer_id: int,
    amount: Decimal,
    package_id: int | None = None,
    status: str = "draft",
    services: list | None = None,
    notes: str | None = None,
    expires_at: date | None = None,
) -> Quote:
    quote = Quote(
        user_id=user_id,
        customer_id=customer_id,
        package_id=package_id,
        amount=amount,
        status=status if status in {k for k, _ in QUOTE_STATUSES} else "draft",
        services=services,
        notes=notes,
        expires_at=expires_at or (date.today() + timedelta(days=30)),
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return quote


def accept_quote(db: Session, user_id: int, quote_id: int) -> Quote:
    quote = get_quote(db, user_id, quote_id)
    if not quote:
        raise ValueError("Quote not found.")
    quote.status = "accepted"
    customer = db.get(Customer, quote.customer_id)
    if customer and customer.user_id == user_id:
        customer.status = "quoted"
        customer.usual_price = quote.amount
        if quote.services:
            customer.services = quote.services
    db.commit()
    db.refresh(quote)
    return quote


def update_quote_status(db: Session, quote: Quote, status: str) -> Quote:
    if status not in {k for k, _ in QUOTE_STATUSES}:
        raise ValueError("Invalid quote status.")
    quote.status = status
    db.commit()
    db.refresh(quote)
    return quote


def _accepted_quote(db: Session, user_id: int, customer_id: int) -> Quote | None:
    today = date.today()
    return db.scalar(
        select(Quote)
        .where(
            Quote.user_id == user_id,
            Quote.customer_id == customer_id,
            Quote.status == "accepted",
            or_(Quote.expires_at.is_(None), Quote.expires_at >= today),
        )
        .order_by(Quote.updated_at.desc())
        .limit(1)
    )


def _has_job_history(db: Session, user_id: int, customer_id: int) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.user_id == user_id, Job.customer_id == customer_id)
    )
    return bool(count and count > 0)


def _last_ticket_price(db: Session, user_id: int, customer_id: int) -> Decimal | None:
    job = db.scalar(
        select(Job)
        .where(
            Job.user_id == user_id,
            Job.customer_id == customer_id,
            Job.ticket_price.is_not(None),
        )
        .order_by(Job.job_date.desc().nullslast(), Job.id.desc())
        .limit(1)
    )
    return job.ticket_price if job else None


def can_self_schedule(db: Session, user_id: int, customer: Customer) -> ScheduleEligibility:
    """Eligible with an accepted quote OR prior property work with a known price."""
    quote = _accepted_quote(db, user_id, customer.id)
    if quote:
        return ScheduleEligibility(
            can_schedule=True,
            price=quote.amount,
            reason="Accepted quote on file.",
            quote_id=quote.id,
            source="quote",
        )

    if _has_job_history(db, user_id, customer.id):
        price = customer.usual_price or _last_ticket_price(db, user_id, customer.id)
        if price and price > 0:
            return ScheduleEligibility(
                can_schedule=True,
                price=price,
                reason="Prior service history with a known price.",
                source="history",
            )
        return ScheduleEligibility(
            can_schedule=False,
            price=None,
            reason="Prior work found, but no price on file. Request a quote.",
            source="history",
        )

    if customer.status == "quoted" and customer.usual_price and customer.usual_price > 0:
        return ScheduleEligibility(
            can_schedule=True,
            price=customer.usual_price,
            reason="Quoted price on customer record.",
            source="usual_price",
        )

    return ScheduleEligibility(
        can_schedule=False,
        price=None,
        reason="Need an accepted quote or prior service history to schedule online.",
    )


def past_services_for_customer(
    db: Session, user_id: int, customer_id: int
) -> list[dict]:
    """Services a portal customer can reselect."""
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.user_id == user_id, Job.customer_id == customer_id)
            .order_by(Job.job_date.desc().nullslast(), Job.id.desc())
            .limit(20)
        )
    )
    result = []
    for job in jobs:
        result.append(
            {
                "job_id": job.id,
                "date": job.job_date.isoformat() if job.job_date else None,
                "description": job.service_description or "",
                "price": job.ticket_price,
                "address": job.address or "",
            }
        )
    quotes = list_quotes(db, user_id, customer_id=customer_id)
    for quote in quotes:
        if quote.status != "accepted":
            continue
        result.append(
            {
                "quote_id": quote.id,
                "date": quote.created_at.date().isoformat() if quote.created_at else None,
                "description": (quote.package.name if quote.package else "Quote"),
                "price": quote.amount,
                "address": quote.customer.address if quote.customer else "",
            }
        )
    return result
