"""Booking helpers that link crews to Apple Calendar event entries."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

from app.models.booking import Booking
from app.services.booking_service import (
    cancel_booking_for_calendar_event,
    get_booking_by_calendar_uid,
    upsert_booking_for_calendar_event,
)


def test_get_booking_by_calendar_uid_returns_none_for_blank():
    db = MagicMock()
    assert get_booking_by_calendar_uid(db, 1, "  ") is None
    db.scalar.assert_not_called()


def test_get_booking_by_calendar_uid_queries_active_booking():
    db = MagicMock()
    booking = MagicMock()
    db.scalar.return_value = booking
    assert get_booking_by_calendar_uid(db, 5, "evt-9") is booking
    db.scalar.assert_called_once()


def test_upsert_booking_for_calendar_event_updates_existing():
    db = MagicMock()
    existing = Booking(
        user_id=1,
        crew_id=2,
        customer_id=3,
        price=Decimal("100"),
        duration_minutes=60,
        starts_at=datetime(2026, 9, 16, 9, 0),
        ends_at=datetime(2026, 9, 16, 10, 0),
        calendar_event_uid="evt-1",
        status="confirmed",
        duration_source="formula",
    )
    db.scalar.return_value = existing

    result = upsert_booking_for_calendar_event(
        db,
        1,
        calendar_event_uid="evt-1",
        crew_id=8,
        customer_id=3,
        price=Decimal("322"),
        starts_at=datetime(2026, 9, 16, 9, 0),
        ends_at=datetime(2026, 9, 16, 11, 0),
        duration_minutes=120,
        duration_source="formula",
        notes="inside",
    )

    assert result is existing
    assert existing.crew_id == 8
    assert existing.price == Decimal("322")
    assert existing.duration_minutes == 120
    assert existing.ends_at == datetime(2026, 9, 16, 11, 0)
    assert existing.notes == "inside"
    db.add.assert_not_called()
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(existing)


def test_upsert_booking_for_calendar_event_creates_when_missing():
    db = MagicMock()
    db.scalar.return_value = None

    result = upsert_booking_for_calendar_event(
        db,
        1,
        calendar_event_uid="evt-new",
        crew_id=4,
        customer_id=None,
        price=Decimal("200"),
        starts_at=datetime(2026, 9, 16, 9, 0),
        ends_at=datetime(2026, 9, 16, 10, 30),
        duration_minutes=90,
        duration_source="override",
    )

    db.add.assert_called_once()
    created = db.add.call_args[0][0]
    assert isinstance(created, Booking)
    assert created.calendar_event_uid == "evt-new"
    assert created.crew_id == 4
    assert created.duration_minutes == 90
    assert created.status == "confirmed"
    db.commit.assert_called_once()
    assert result is created


def test_cancel_booking_for_calendar_event_marks_cancelled():
    db = MagicMock()
    booking = MagicMock(status="confirmed")
    db.scalar.return_value = booking

    result = cancel_booking_for_calendar_event(db, 1, "evt-1")
    assert result is booking
    assert booking.status == "cancelled"
    db.commit.assert_called_once()
