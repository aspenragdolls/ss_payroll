from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.customer import ACTIVE_STATUSES, Customer
from app.models.job import Job

CUSTOMER_STATUSES = (
    ("lead", "Lead"),
    ("estimate", "Estimate"),
    ("quoted", "Quoted"),
    ("scheduled", "Scheduled"),
    ("active", "Active"),
    ("past_customer", "Past customer"),
    ("lost", "Lost"),
)

NEIGHBORHOODS = (
    "Sugar House",
    "Millcreek",
    "East Millcreek",
    "Holladay",
    "Murray",
    "Midvale",
    "Sandy",
    "Draper",
    "Cottonwood Heights",
    "Avenues",
    "Downtown",
    "Capitol Hill",
    "Liberty Wells",
    "Ballpark",
    "Rose Park",
    "Glendale",
    "West Valley",
    "Taylorsville",
    "South Jordan",
    "Other",
)

LEAD_SOURCES = (
    ("referral", "Referral"),
    ("door_knock", "Door knock"),
    ("yard_sign", "Yard sign"),
    ("google", "Google"),
    ("paid_ad", "Paid ad"),
    ("other", "Other"),
)

SERVICE_TYPES = (
    ("windows", "Windows"),
    ("gutters", "Gutters"),
    ("pressure_washing", "Pressure washing"),
    ("lights", "Lights"),
    ("screens", "Screens"),
)

LAST_SERVICE_OPTIONS = (
    ("", "Any"),
    ("within_6m", "Within 6 months"),
    ("6_12m", "6–12 months ago"),
    ("over_12m", "Over 12 months ago"),
    ("never", "Never serviced"),
)

REVENUE_METRIC_OPTIONS = (
    ("", "Any"),
    ("lifetime", "Lifetime spend"),
    ("year", "Spent this year"),
)

NEXT_DUE_OPTIONS = (
    ("", "Any"),
    ("due_now", "Due now"),
    ("due_30", "Due in 30 days"),
    ("due_60", "Due in 60 days"),
    ("due_90", "Due in 90 days"),
    ("no_schedule", "No schedule"),
)

_SERVICE_ALIASES = {
    "windows": ("window", "windows", "int/ext", "interior", "exterior"),
    "gutters": ("gutter", "gutters"),
    "pressure_washing": ("pressure", "power wash", "powerwash", "soft wash"),
    "lights": ("light", "lights", "christmas", "holiday light"),
    "screens": ("screen", "screens"),
}

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


@dataclass
class CustomerListFilters:
    q: str = ""
    neighborhood: str = ""
    zip_code: str = ""
    radius_lat: str = ""
    radius_lng: str = ""
    radius_miles: str = ""
    status: str = ""
    last_service: str = ""
    revenue_metric: str = ""
    revenue_min: str = ""
    revenue_max: str = ""
    service: str = ""
    never_service: str = ""
    lead_source: str = ""
    next_due: str = ""

    def has_active(self) -> bool:
        return any(
            [
                self.q.strip(),
                self.neighborhood.strip(),
                self.zip_code.strip(),
                self.radius_lat.strip() and self.radius_lng.strip() and self.radius_miles.strip(),
                self.status.strip(),
                self.last_service.strip(),
                self.revenue_metric.strip(),
                self.revenue_min.strip(),
                self.revenue_max.strip(),
                self.service.strip(),
                self.never_service.strip(),
                self.lead_source.strip(),
                self.next_due.strip(),
            ]
        )


@dataclass
class CustomerListItem:
    customer: Customer
    visit_count: int
    last_visit: date | None
    lifetime_spend: Decimal
    year_spend: Decimal


@dataclass
class CustomerJobHistory:
    jobs: list[Job]
    visit_count: int
    first_visit: date | None
    last_visit: date | None
    total_tickets: Decimal
    total_tips: Decimal
    cash_jobs: int


def status_is_active(status: str) -> bool:
    return status in ACTIVE_STATUSES


def parse_services(raw: list[str] | None) -> list[str]:
    valid = {key for key, _ in SERVICE_TYPES}
    if not raw:
        return []
    return [value for value in raw if value in valid]


def _parse_decimal(raw: str | None) -> Decimal | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return Decimal(str(raw).strip().replace(",", "").replace("$", ""))
    except (InvalidOperation, ValueError):
        return None


def _parse_float(raw: str | None) -> float | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _service_job_match(service_key: str):
    aliases = _SERVICE_ALIASES.get(service_key, (service_key,))
    return or_(
        *[Job.service_description.ilike(f"%{alias}%") for alias in aliases],
        *[Job.source_text.ilike(f"%{alias}%") for alias in aliases],
    )


def list_customers(
    db: Session,
    user_id: int,
    *,
    filters: CustomerListFilters | None = None,
) -> list[CustomerListItem]:
    filters = filters or CustomerListFilters()
    today = date.today()
    year_start = date(today.year, 1, 1)

    visit_count = func.count(Job.id).label("visit_count")
    last_visit = func.max(Job.job_date).label("last_visit")
    lifetime_spend = func.coalesce(func.sum(Job.ticket_price), 0).label("lifetime_spend")
    year_spend = func.coalesce(
        func.sum(Job.ticket_price).filter(Job.job_date >= year_start),
        0,
    ).label("year_spend")

    stmt = (
        select(
            Customer,
            visit_count,
            last_visit,
            lifetime_spend,
            year_spend,
        )
        .outerjoin(Job, Job.customer_id == Customer.id)
        .where(Customer.user_id == user_id)
        .group_by(Customer.id)
        .order_by(Customer.name)
    )

    if filters.q.strip():
        pattern = f"%{filters.q.strip()}%"
        stmt = stmt.where(
            or_(
                Customer.name.ilike(pattern),
                Customer.address.ilike(pattern),
                Customer.phone.ilike(pattern),
                Customer.email.ilike(pattern),
                Customer.aliases.ilike(pattern),
                Customer.neighborhood.ilike(pattern),
                Customer.zip_code.ilike(pattern),
            )
        )

    if filters.neighborhood.strip():
        stmt = stmt.where(Customer.neighborhood == filters.neighborhood.strip())

    if filters.zip_code.strip():
        zip_code = filters.zip_code.strip()[:5]
        stmt = stmt.where(
            or_(
                Customer.zip_code.startswith(zip_code),
                Customer.address.ilike(f"%{zip_code}%"),
            )
        )

    if filters.status.strip() in {key for key, _ in CUSTOMER_STATUSES}:
        stmt = stmt.where(Customer.status == filters.status.strip())

    if filters.lead_source.strip() in {key for key, _ in LEAD_SOURCES}:
        stmt = stmt.where(Customer.lead_source == filters.lead_source.strip())

    if filters.next_due == "due_now":
        stmt = stmt.where(Customer.next_service_due.is_not(None), Customer.next_service_due <= today)
    elif filters.next_due == "due_30":
        stmt = stmt.where(
            Customer.next_service_due.is_not(None),
            Customer.next_service_due > today,
            Customer.next_service_due <= today + timedelta(days=30),
        )
    elif filters.next_due == "due_60":
        stmt = stmt.where(
            Customer.next_service_due.is_not(None),
            Customer.next_service_due > today,
            Customer.next_service_due <= today + timedelta(days=60),
        )
    elif filters.next_due == "due_90":
        stmt = stmt.where(
            Customer.next_service_due.is_not(None),
            Customer.next_service_due > today,
            Customer.next_service_due <= today + timedelta(days=90),
        )
    elif filters.next_due == "no_schedule":
        stmt = stmt.where(Customer.next_service_due.is_(None))

    if filters.last_service == "never":
        stmt = stmt.having(visit_count == 0)
    elif filters.last_service == "within_6m":
        stmt = stmt.having(last_visit >= today - timedelta(days=183))
    elif filters.last_service == "6_12m":
        stmt = stmt.having(
            last_visit < today - timedelta(days=183),
            last_visit >= today - timedelta(days=365),
        )
    elif filters.last_service == "over_12m":
        stmt = stmt.having(last_visit.is_not(None), last_visit < today - timedelta(days=365))

    revenue_min = _parse_decimal(filters.revenue_min)
    revenue_max = _parse_decimal(filters.revenue_max)
    if filters.revenue_metric == "year":
        revenue_col = year_spend
    else:
        revenue_col = lifetime_spend
    if filters.revenue_metric in {"lifetime", "year"} or revenue_min is not None or revenue_max is not None:
        if revenue_min is not None:
            stmt = stmt.having(revenue_col >= revenue_min)
        if revenue_max is not None:
            stmt = stmt.having(revenue_col <= revenue_max)

    if filters.service.strip() in _SERVICE_ALIASES:
        service_key = filters.service.strip()
        has_tagged = Customer.services.contains([service_key])
        job_ids = (
            select(Job.customer_id)
            .where(Job.user_id == user_id, _service_job_match(service_key))
            .distinct()
        )
        stmt = stmt.where(or_(has_tagged, Customer.id.in_(job_ids)))

    if filters.never_service.strip() in _SERVICE_ALIASES:
        service_key = filters.never_service.strip()
        has_tagged = Customer.services.contains([service_key])
        job_ids = (
            select(Job.customer_id)
            .where(Job.user_id == user_id, _service_job_match(service_key))
            .distinct()
        )
        stmt = stmt.where(
            or_(Customer.services.is_(None), ~has_tagged),
            ~Customer.id.in_(job_ids),
        )

    rows = db.execute(stmt).all()
    items = [
        CustomerListItem(
            customer=customer,
            visit_count=int(count or 0),
            last_visit=last,
            lifetime_spend=Decimal(str(life or 0)),
            year_spend=Decimal(str(year or 0)),
        )
        for customer, count, last, life, year in rows
    ]

    center_lat = _parse_float(filters.radius_lat)
    center_lng = _parse_float(filters.radius_lng)
    radius_miles = _parse_float(filters.radius_miles)
    if center_lat is not None and center_lng is not None and radius_miles is not None:
        filtered: list[CustomerListItem] = []
        for item in items:
            if item.customer.latitude is None or item.customer.longitude is None:
                continue
            distance = _haversine_miles(
                center_lat,
                center_lng,
                float(item.customer.latitude),
                float(item.customer.longitude),
            )
            if distance <= radius_miles:
                filtered.append(item)
        items = filtered

    return items


def get_customer(db: Session, user_id: int, customer_id: int) -> Customer | None:
    return db.scalar(
        select(Customer).where(Customer.user_id == user_id, Customer.id == customer_id)
    )


def get_customer_by_calendar_uid(
    db: Session, user_id: int, calendar_event_uid: str
) -> Customer | None:
    uid = (calendar_event_uid or "").strip()
    if not uid:
        return None
    return db.scalar(
        select(Customer).where(
            Customer.user_id == user_id,
            Customer.calendar_event_uid == uid,
        )
    )


def list_customers_with_calendar_uid(db: Session, user_id: int) -> list[Customer]:
    return list(
        db.scalars(
            select(Customer).where(
                Customer.user_id == user_id,
                Customer.calendar_event_uid.is_not(None),
            )
        )
    )


def suggest_customers(db: Session, user_id: int, q: str, *, limit: int = 12) -> list[Customer]:
    query = (q or "").strip()
    if not query:
        return []
    pattern = f"%{query}%"
    return list(
        db.scalars(
            select(Customer)
            .where(
                Customer.user_id == user_id,
                or_(
                    Customer.name.ilike(pattern),
                    Customer.address.ilike(pattern),
                    Customer.phone.ilike(pattern),
                    Customer.aliases.ilike(pattern),
                ),
            )
            .order_by(Customer.name.asc())
            .limit(limit)
        )
    )


def upsert_customer_from_event(
    db: Session,
    user_id: int,
    *,
    customer_id: int | None,
    name: str,
    address: str | None,
    phone: str | None,
    classification: str,
    service_scope: str | None,
    usual_price: Decimal | None,
    calendar_event_uid: str | None = None,
    next_service_due: date | None = None,
) -> Customer:
    from app.services.event_format import (
        infer_customer_status,
        merge_services,
        scope_for_classification,
    )

    status = infer_customer_status(classification)
    scope = scope_for_classification(classification, service_scope)
    customer = get_customer(db, user_id, customer_id) if customer_id else None
    if not customer and calendar_event_uid:
        customer = get_customer_by_calendar_uid(db, user_id, calendar_event_uid)

    extra: dict = {}
    if calendar_event_uid is not None:
        extra["calendar_event_uid"] = calendar_event_uid.strip() or None
    if next_service_due is not None:
        extra["next_service_due"] = next_service_due

    if customer:
        merged = merge_services(customer.services, classification)
        return update_customer(
            db,
            customer,
            name=name.strip(),
            address=(address or "").strip() or None,
            phone=(phone or "").strip() or None,
            status=status,
            services=merged,
            service_scope=scope,
            usual_price=usual_price if usual_price is not None else customer.usual_price,
            **extra,
        )
    return create_customer(
        db,
        user_id,
        name=name,
        address=address,
        phone=phone,
        status=status,
        services=merge_services(None, classification),
        service_scope=scope,
        usual_price=usual_price,
        calendar_event_uid=extra.get("calendar_event_uid"),
        next_service_due=extra.get("next_service_due"),
    )


def create_customer(
    db: Session,
    user_id: int,
    *,
    name: str,
    address: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    notes: str | None = None,
    aliases: str | None = None,
    status: str = "active",
    neighborhood: str | None = None,
    zip_code: str | None = None,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
    lead_source: str | None = None,
    services: list[str] | None = None,
    usual_price: Decimal | None = None,
    service_scope: str | None = None,
    next_service_due: date | None = None,
    calendar_event_uid: str | None = None,
    allow_email: bool = True,
    allow_sms: bool = True,
    allow_mail: bool = True,
    do_not_contact: bool = False,
) -> Customer:
    status_value = status if status in {key for key, _ in CUSTOMER_STATUSES} else "active"
    zip_value = (zip_code or "").strip() or None
    if not zip_value and address:
        match = _ZIP_RE.search(address)
        if match:
            zip_value = match.group(1)
    customer = Customer(
        user_id=user_id,
        name=name.strip(),
        address=(address or "").strip() or None,
        phone=(phone or "").strip() or None,
        email=(email or "").strip() or None,
        notes=(notes or "").strip() or None,
        aliases=(aliases or "").strip() or None,
        status=status_value,
        neighborhood=(neighborhood or "").strip() or None,
        zip_code=zip_value,
        latitude=latitude,
        longitude=longitude,
        lead_source=(lead_source or "").strip() or None,
        services=parse_services(services) or None,
        usual_price=usual_price,
        service_scope=(service_scope or "").strip() or None,
        next_service_due=next_service_due,
        calendar_event_uid=(calendar_event_uid or "").strip() or None,
        allow_email=allow_email,
        allow_sms=allow_sms,
        allow_mail=allow_mail,
        do_not_contact=do_not_contact,
        is_active=status_is_active(status_value),
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def update_customer(db: Session, customer: Customer, **fields) -> Customer:
    if "services" in fields:
        fields["services"] = parse_services(fields["services"]) or None
    if "status" in fields:
        status_value = fields["status"]
        if status_value not in {key for key, _ in CUSTOMER_STATUSES}:
            status_value = customer.status
        fields["status"] = status_value
        fields["is_active"] = status_is_active(status_value)
    if "zip_code" in fields and not fields["zip_code"] and fields.get("address"):
        match = _ZIP_RE.search(fields["address"] or "")
        if match:
            fields["zip_code"] = match.group(1)
    for key, value in fields.items():
        setattr(customer, key, value)
    db.commit()
    db.refresh(customer)
    return customer


def get_customer_job_history(
    db: Session, user_id: int, customer_id: int
) -> CustomerJobHistory:
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.user_id == user_id, Job.customer_id == customer_id)
            .order_by(Job.job_date.desc().nullslast(), Job.id.desc())
        )
    )
    dated = [job.job_date for job in jobs if job.job_date]
    total_tickets = sum((job.ticket_price or Decimal("0")) for job in jobs)
    total_tips = sum((job.tips or Decimal("0")) for job in jobs)
    return CustomerJobHistory(
        jobs=jobs,
        visit_count=len(jobs),
        first_visit=min(dated) if dated else None,
        last_visit=max(dated) if dated else None,
        total_tickets=total_tickets,
        total_tips=total_tips,
        cash_jobs=sum(1 for job in jobs if job.is_cash),
    )


def label_for(options: tuple[tuple[str, str], ...], key: str | None, default: str = "—") -> str:
    if not key:
        return default
    for value, label in options:
        if value == key:
            return label
    return key


def customer_status_label(customer: Customer) -> str:
    from app.services.event_format import status_display_label

    classification = None
    if customer.status == "scheduled":
        if customer.service_scope:
            classification = "windows"
        elif customer.services and "gutters" in customer.services:
            classification = "gutters"
        elif customer.services and "windows" in customer.services:
            classification = "windows"
    return status_display_label(
        customer.status,
        service_scope=customer.service_scope,
        classification=classification,
    )


def export_customers_csv(
    items: list[CustomerListItem],
    *,
    respect_marketing_prefs: bool = True,
) -> str:
    """Export filtered customers, honoring marketing contact preferences."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "name",
            "status",
            "address",
            "neighborhood",
            "zip_code",
            "phone",
            "email",
            "lead_source",
            "services",
            "last_visit",
            "next_service_due",
            "lifetime_spend",
            "year_spend",
            "visit_count",
            "export_phone",
            "export_email",
            "export_mail_address",
            "marketing_notes",
        ],
    )
    writer.writeheader()
    for item in items:
        customer = item.customer
        if respect_marketing_prefs and customer.do_not_contact:
            continue

        export_phone = ""
        export_email = ""
        export_mail = ""
        notes: list[str] = []
        if respect_marketing_prefs:
            if customer.allow_sms and customer.phone:
                export_phone = customer.phone
            elif customer.phone:
                notes.append("SMS/phone outreach not allowed")
            if customer.allow_email and customer.email:
                export_email = customer.email
            elif customer.email:
                notes.append("Email outreach not allowed")
            if customer.allow_mail and customer.address:
                export_mail = customer.address
            elif customer.address:
                notes.append("Mail outreach not allowed")
            if not any([export_phone, export_email, export_mail]):
                notes.append("No permitted contact channels")
                # Still include the row for campaign planning, without contact fields.
        else:
            export_phone = customer.phone or ""
            export_email = customer.email or ""
            export_mail = customer.address or ""

        writer.writerow(
            {
                "name": customer.name,
                "status": customer.status,
                "address": customer.address or "",
                "neighborhood": customer.neighborhood or "",
                "zip_code": customer.zip_code or "",
                "phone": customer.phone or "",
                "email": customer.email or "",
                "lead_source": customer.lead_source or "",
                "services": ";".join(customer.services or []),
                "last_visit": item.last_visit or "",
                "next_service_due": customer.next_service_due or "",
                "lifetime_spend": f"{item.lifetime_spend:.2f}",
                "year_spend": f"{item.year_spend:.2f}",
                "visit_count": item.visit_count,
                "export_phone": export_phone,
                "export_email": export_email,
                "export_mail_address": export_mail,
                "marketing_notes": "; ".join(notes),
            }
        )
    return buffer.getvalue()
