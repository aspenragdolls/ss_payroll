from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class RawCalendarEvent:
    event_id: str
    title: str
    description: str
    location: str
    start: datetime
    end: datetime
    raw_text: str


@dataclass
class DraftJob:
    customer_name: str | None
    address: str | None
    service_description: str | None
    final_ticket_price: str | None
    job_date: date | None
    confidence_customer: float | None = None
    confidence_address: float | None = None
    confidence_price: float | None = None
    notes: str | None = None
    ambiguity_flags: list[str] | None = None
    raw_source_text: str = ""
