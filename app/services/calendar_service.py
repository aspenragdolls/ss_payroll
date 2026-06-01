from datetime import date, datetime, timedelta
from typing import Protocol

from app.services.schemas import RawCalendarEvent


class CalendarProvider(Protocol):
    async def fetch_raw_events(
        self, user_id: int, start: date, end: date
    ) -> list[RawCalendarEvent]: ...


class MockCalendarProvider:
    async def fetch_raw_events(
        self, user_id: int, start: date, end: date
    ) -> list[RawCalendarEvent]:
        base = datetime.combine(start, datetime.min.time())
        return [
            RawCalendarEvent(
                event_id=f"mock-{user_id}-1",
                title="Smith Residence - Window Cleaning",
                description="Full exterior window clean. Ticket: $450. Contact: John Smith",
                location="123 Oak St, Springfield",
                start=base + timedelta(hours=9),
                end=base + timedelta(hours=11),
                raw_text=(
                    "Smith Residence - Window Cleaning\n"
                    "123 Oak St, Springfield\n"
                    "Full exterior window clean. Ticket: $450"
                ),
            ),
            RawCalendarEvent(
                event_id=f"mock-{user_id}-2",
                title="Johnson Office Building",
                description="Commercial windows, 2nd floor. Price $800",
                location="456 Main Ave",
                start=base + timedelta(hours=13),
                end=base + timedelta(hours=16),
                raw_text=(
                    "Johnson Office Building\n456 Main Ave\nCommercial windows $800"
                ),
            ),
        ]


def get_calendar_provider() -> CalendarProvider:
    return MockCalendarProvider()
