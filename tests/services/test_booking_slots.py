"""Availability slot generation tests."""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.booking_service import available_slots


def test_available_slots_skips_busy(monkeypatch):
    settings = SimpleNamespace(
        business_hours_start=time(9, 0),
        business_hours_end=time(12, 0),
        slot_grain_minutes=60,
        buffer_minutes=0,
    )
    busy = [
        SimpleNamespace(
            starts_at=datetime(2026, 9, 23, 10, 0),
            ends_at=datetime(2026, 9, 23, 11, 0),
        )
    ]
    monkeypatch.setattr(
        "app.services.booking_service.get_scheduling_settings",
        lambda db, user_id: settings,
    )
    monkeypatch.setattr(
        "app.services.booking_service.list_bookings_for_crew",
        lambda db, user_id, crew_id, start, end: busy,
    )

    slots = available_slots(MagicMock(), 1, 1, date(2026, 9, 23), duration_minutes=60)
    starts = [s.starts_at.hour for s in slots]
    assert 9 in starts
    assert 10 not in starts
    assert 11 in starts
