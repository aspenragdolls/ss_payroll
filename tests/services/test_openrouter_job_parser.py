import pytest
from datetime import datetime

from app.services.openrouter_job_parser import _fallback_parse
from app.services.schemas import RawCalendarEvent


@pytest.mark.asyncio
async def test_fallback_parse_extracts_price():
    event = RawCalendarEvent(
        event_id="1",
        title="Smith - Windows",
        description="Clean all windows $450",
        location="123 Oak St",
        start=datetime(2025, 5, 1, 9, 0),
        end=datetime(2025, 5, 1, 11, 0),
        raw_text="Smith - Windows\n123 Oak St\nClean all windows $450",
    )
    draft = _fallback_parse(event, event.raw_text)
    assert draft.final_ticket_price == "450"
    assert draft.customer_name == "Smith"
