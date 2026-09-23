from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.apple_calendar import _build_vevent_ics, create_apple_calendar_event
from app.services.event_format import build_event_description, build_event_title
from app.services.openrouter_job_parser import _fallback_parse
from app.services.schemas import RawCalendarEvent


def test_payroll_fallback_parses_name_price_title_format():
    title = build_event_title("Parks Mangelson", 322)
    description = build_event_description(
        "801-376-7998",
        "windows",
        "inside_and_outside",
    )
    location = "1446 E 900 S, Salt Lake City, UT, United States"
    raw_text = "\n".join(part for part in (title, location, description) if part)
    event = RawCalendarEvent(
        event_id="evt-1",
        title=title,
        description=description,
        location=location,
        start=datetime(2026, 9, 16, 15, 0),
        end=datetime(2026, 9, 16, 16, 0),
        raw_text=raw_text,
    )
    draft = _fallback_parse(event, raw_text)
    assert draft.final_ticket_price == "322"
    assert draft.address == location
    assert "Parks Mangelson" in (draft.customer_name or "")
    assert draft.service_description == description


def test_payroll_fallback_parses_estimate_event():
    title = build_event_title("Jane Doe", "150")
    description = build_event_description("801-555-0199", "estimate")
    event = RawCalendarEvent(
        event_id="evt-2",
        title=title,
        description=description,
        location="100 Main St",
        start=datetime(2026, 9, 20, 9, 0),
        end=datetime(2026, 9, 20, 10, 0),
        raw_text=f"{title}\n100 Main St\n{description}",
    )
    draft = _fallback_parse(event, event.raw_text)
    assert draft.final_ticket_price == "150"
    assert "Estimate" in (draft.service_description or "")


def test_build_vevent_ics_contains_summary_and_description():
    payload = _build_vevent_ics(
        uid="test-uid-1",
        title="Parks Mangelson ($322)",
        description="801-376-7998\n\nInside and outside",
        location="1446 E 900 S",
        start=datetime(2026, 9, 16, 15, 0),
        end=datetime(2026, 9, 16, 16, 0),
    )
    text = payload.decode("utf-8")
    assert "SUMMARY:Parks Mangelson ($322)" in text
    assert "LOCATION:1446 E 900 S" in text
    assert "UID:test-uid-1" in text
    assert "801-376-7998" in text


@pytest.mark.asyncio
async def test_create_apple_calendar_event_puts_ics():
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.services.apple_calendar._auth_client", return_value=mock_client),
        patch(
            "app.services.apple_calendar._resolve_calendar_urls",
            new=AsyncMock(return_value=["https://caldav.icloud.com/calendars/work/"]),
        ),
    ):
        event = await create_apple_calendar_event(
            "user@icloud.com",
            "app-password",
            "Work",
            title="Parks Mangelson ($322)",
            description="801-376-7998\n\nInside and outside",
            location="1446 E 900 S",
            start=datetime(2026, 9, 16, 15, 0),
            end=datetime(2026, 9, 16, 16, 0),
            uid="fixed-uid",
        )

    assert event.event_id == "fixed-uid"
    assert event.title == "Parks Mangelson ($322)"
    mock_client.put.assert_awaited_once()
    args, kwargs = mock_client.put.await_args
    assert args[0].endswith("fixed-uid.ics")
    assert b"SUMMARY:Parks Mangelson ($322)" in kwargs["content"]
