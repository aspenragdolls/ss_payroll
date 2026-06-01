import json
import re
from decimal import Decimal, InvalidOperation

import httpx

from app.config import get_settings
from app.services.schemas import DraftJob, RawCalendarEvent


SYSTEM_PROMPT = """You extract window cleaning job data from calendar event text.
Return ONLY valid JSON with these fields:
{
  "customer_name": string or null,
  "address": string or null,
  "service_description": string or null,
  "final_ticket_price": string number or null,
  "job_date": "YYYY-MM-DD" or null,
  "confidence_customer": 0.0-1.0,
  "confidence_address": 0.0-1.0,
  "confidence_price": 0.0-1.0,
  "notes": string or null,
  "ambiguity_flags": [string]
}"""


async def parse_calendar_event(event: RawCalendarEvent) -> DraftJob:
    settings = get_settings()
    raw_text = event.raw_text or f"{event.title}\n{event.description}\n{event.location}"

    if not settings.openrouter_api_key:
        return _fallback_parse(event, raw_text)

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return DraftJob(
                customer_name=parsed.get("customer_name"),
                address=parsed.get("address") or event.location or None,
                service_description=parsed.get("service_description") or event.description,
                final_ticket_price=parsed.get("final_ticket_price"),
                job_date=_parse_date(parsed.get("job_date")) or event.start.date(),
                confidence_customer=parsed.get("confidence_customer"),
                confidence_address=parsed.get("confidence_address"),
                confidence_price=parsed.get("confidence_price"),
                notes=parsed.get("notes"),
                ambiguity_flags=parsed.get("ambiguity_flags") or [],
                raw_source_text=raw_text,
            )
    except (httpx.HTTPError, KeyError, json.JSONDecodeError, IndexError):
        return _fallback_parse(event, raw_text)


def _parse_date(value: str | None):
    if not value:
        return None
    from datetime import date

    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _fallback_parse(event: RawCalendarEvent, raw_text: str) -> DraftJob:
    price_match = re.search(r"\$\s*(\d+(?:\.\d{2})?)", raw_text)
    if not price_match:
        price_match = re.search(r"(?:ticket|price)[:\s]*\$?\s*(\d+(?:\.\d{2})?)", raw_text, re.I)
    price = price_match.group(1) if price_match else None
    return DraftJob(
        customer_name=event.title.split("-")[0].strip() if event.title else None,
        address=event.location or None,
        service_description=event.description or None,
        final_ticket_price=price,
        job_date=event.start.date(),
        confidence_customer=0.5,
        confidence_address=0.5 if event.location else 0.2,
        confidence_price=0.6 if price else 0.1,
        notes="Parsed locally (OpenRouter unavailable)",
        ambiguity_flags=["openrouter_unavailable"] if not get_settings().openrouter_api_key else ["parse_error"],
        raw_source_text=raw_text,
    )


def safe_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    cleaned = re.sub(r"[^\d.]", "", str(value))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None
