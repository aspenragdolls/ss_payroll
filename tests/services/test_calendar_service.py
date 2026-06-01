from datetime import date
from unittest.mock import MagicMock

import pytest

from app.models.calendar import CalendarConnection
from app.services.calendar_service import fetch_events_for_user, is_calendar_connected


def test_is_calendar_connected_false_without_connection():
    db = MagicMock()
    db.scalar.return_value = None
    assert is_calendar_connected(db, 1) is False


def test_is_calendar_connected_true_with_active_connection():
    db = MagicMock()
    db.scalar.return_value = CalendarConnection(
        user_id=1,
        provider="apple",
        external_account_id="user@icloud.com",
        access_token_encrypted="encrypted-token",
        calendar_id="Work",
        is_active=True,
    )
    assert is_calendar_connected(db, 1) is True


@pytest.mark.asyncio
async def test_fetch_events_for_user_returns_empty_without_connection():
    db = MagicMock()
    db.scalar.return_value = None
    events = await fetch_events_for_user(db, 1, date(2024, 5, 1), date(2024, 5, 2))
    assert events == []
