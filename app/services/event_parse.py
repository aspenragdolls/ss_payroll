"""Parse Apple Calendar event fields back into app form / CRM values."""

from __future__ import annotations

import re

from app.services.event_format import service_description_line
from app.services.schemas import RawCalendarEvent

_TITLE_PRICE_RE = re.compile(r"^(.*?)\s*\(\s*\$\s*([\d.,]+)\s*\)\s*$")


def parse_title_name_price(title: str) -> tuple[str, str]:
    match = _TITLE_PRICE_RE.match((title or "").strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return (title or "").strip(), ""


def guess_classification_from_event(event: RawCalendarEvent) -> tuple[str, str | None]:
    text = f"{event.description or ''}\n{event.title or ''}".lower()
    if "estimate" in text or "quote" in text:
        return "estimate", None
    if "gutter" in text:
        return "gutters", None
    scope_map = [
        ("inside and outside", "inside_and_outside"),
        ("outside only", "outside_only"),
        ("inside only", "inside_only"),
        ("partial", "partial"),
    ]
    for needle, key in scope_map:
        if needle in text:
            return "windows", key
    return "windows", "inside_and_outside"


def parse_description_phone_note(
    description: str | None,
    classification: str,
    service_scope: str | None,
) -> tuple[str, str]:
    """Return (phone, free_note) from a calendar description."""
    phone = ""
    free_note = ""
    desc_lines = (description or "").splitlines()
    if not desc_lines:
        return phone, free_note

    first = desc_lines[0].strip()
    if any(ch.isdigit() for ch in first) and len(first) <= 24:
        phone = first
        rest = "\n".join(desc_lines[1:]).strip()
    else:
        rest = (description or "").strip()

    service_line = service_description_line(classification, service_scope)
    if rest.startswith(service_line):
        free_note = rest[len(service_line) :].strip()
    elif "\n\n" in rest:
        parts = rest.split("\n\n", 1)
        free_note = parts[1].strip() if len(parts) > 1 else ""
    else:
        lines = [ln for ln in rest.splitlines() if ln.strip()]
        if lines and lines[0].strip().lower() == service_line.lower():
            free_note = "\n".join(lines[1:]).strip()
        else:
            free_note = rest
    return phone, free_note


def parse_event_for_app(event: RawCalendarEvent) -> dict:
    """Structured fields derived from a RawCalendarEvent for forms / CRM sync."""
    name, price = parse_title_name_price(event.title)
    classification, scope = guess_classification_from_event(event)
    phone, free_note = parse_description_phone_note(event.description, classification, scope)
    return {
        "customer_name": name,
        "price": price,
        "classification": classification,
        "service_scope": scope or "inside_and_outside",
        "phone": phone,
        "free_note": free_note,
        "address": event.location or "",
        "starts_at": event.start,
        "ends_at": event.end,
        "calendar_event_uid": event.event_id,
    }
