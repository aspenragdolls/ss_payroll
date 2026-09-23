"""Builders for Apple Calendar event fields used by payroll import."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

Classification = Literal["estimate", "windows", "gutters"]
ServiceScope = Literal["inside_and_outside", "outside_only", "inside_only", "partial"]

CLASSIFICATIONS: tuple[tuple[str, str], ...] = (
    ("estimate", "Estimate"),
    ("windows", "Windows"),
    ("gutters", "Gutters"),
)

SERVICE_SCOPES: tuple[tuple[str, str], ...] = (
    ("inside_and_outside", "Inside and outside"),
    ("outside_only", "Outside only"),
    ("inside_only", "Inside only"),
    ("partial", "Partial"),
)

_SCOPE_LABELS = dict(SERVICE_SCOPES)
_CLASSIFICATION_LABELS = dict(CLASSIFICATIONS)


def format_price_for_title(price: Decimal | str | float | int | None) -> str:
    """Format a dollar amount for titles, e.g. $322 or $322.50."""
    if price is None or str(price).strip() == "":
        return ""
    try:
        value = Decimal(str(price).strip().replace(",", "").replace("$", ""))
    except (InvalidOperation, ValueError):
        return ""
    if value == value.to_integral_value():
        return f"${int(value)}"
    return f"${value.quantize(Decimal('0.01'))}"


def build_event_title(customer_name: str, price: Decimal | str | float | int | None) -> str:
    name = (customer_name or "").strip()
    price_text = format_price_for_title(price)
    if name and price_text:
        return f"{name} ({price_text})"
    if name:
        return name
    if price_text:
        return f"({price_text})"
    return ""


def service_description_line(
    classification: str,
    service_scope: str | None = None,
) -> str:
    """Human-readable service line stored in calendar notes / CRM display."""
    if classification == "estimate":
        return "Estimate"
    if classification == "gutters":
        return "Gutters"
    if classification == "windows":
        if service_scope and service_scope in _SCOPE_LABELS:
            return _SCOPE_LABELS[service_scope]
        return "Windows"
    return _CLASSIFICATION_LABELS.get(classification, classification.replace("_", " ").title())


def build_event_description(
    phone: str | None,
    classification: str,
    service_scope: str | None = None,
    free_note: str | None = None,
) -> str:
    """
    Phone first (payroll / export compatible), then blank line, then service line,
    then optional free-text note.
    """
    lines: list[str] = []
    phone_text = (phone or "").strip()
    if phone_text:
        lines.append(phone_text)
        lines.append("")
    lines.append(service_description_line(classification, service_scope))
    note = (free_note or "").strip()
    if note:
        lines.append("")
        lines.append(note)
    return "\n".join(lines)


def infer_customer_status(classification: str) -> str:
    if classification == "estimate":
        return "estimate"
    return "scheduled"


def status_display_label(
    status: str,
    *,
    service_scope: str | None = None,
    classification: str | None = None,
) -> str:
    if status == "estimate" or status == "quoted":
        return "Estimate"
    if status == "scheduled":
        desc = None
        if classification:
            desc = service_description_line(classification, service_scope)
        elif service_scope and service_scope in _SCOPE_LABELS:
            desc = _SCOPE_LABELS[service_scope]
        if desc:
            return f"Scheduled ({desc})"
        return "Scheduled"
    labels = {
        "lead": "Lead",
        "quoted": "Quoted",
        "active": "Active",
        "past_customer": "Past customer",
        "lost": "Lost",
    }
    return labels.get(status, status.replace("_", " ").title())


def services_for_classification(classification: str) -> list[str]:
    if classification == "windows":
        return ["windows"]
    if classification == "gutters":
        return ["gutters"]
    return []


def merge_services(existing: list[str] | None, classification: str) -> list[str]:
    merged = list(existing or [])
    for key in services_for_classification(classification):
        if key not in merged:
            merged.append(key)
    return merged


def scope_for_classification(classification: str, service_scope: str | None) -> str | None:
    if classification != "windows":
        return None
    if service_scope in _SCOPE_LABELS:
        return service_scope
    return None
