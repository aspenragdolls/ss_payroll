import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.calendar import CalendarConnection
from app.services.calendar_service import (
    create_event_for_user,
    delete_event_for_user,
    fetch_events_for_user,
    invalidate_event_cache,
    is_calendar_connected,
    update_event_for_user,
)
from app.services.schemas import RawCalendarEvent


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


def _active_conn() -> CalendarConnection:
    return CalendarConnection(
        user_id=1,
        provider="apple",
        external_account_id="user@icloud.com",
        access_token_encrypted="encrypted-token",
        calendar_id="Work",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_create_event_returns_immediately_and_writes_in_background():
    db = MagicMock()
    start = datetime(2026, 9, 16, 15, 0)
    end = datetime(2026, 9, 16, 16, 0)
    create_mock = AsyncMock(
        return_value=RawCalendarEvent(
            event_id="ignored",
            title="Test",
            description="",
            location="",
            start=start,
            end=end,
            raw_text="",
        )
    )
    with (
        patch("app.services.calendar_service.get_active_connection", return_value=_active_conn()),
        patch("app.services.calendar_service.decrypt_credential", return_value="pw"),
        patch("app.services.calendar_service.create_apple_calendar_event", new=create_mock),
        patch("app.services.calendar_service._schedule_post_write_sync") as schedule,
    ):
        result = await create_event_for_user(
            db,
            1,
            title="Test",
            description="",
            location="",
            start=start,
            end=end,
        )
        # Response should not wait on CalDAV.
        assert create_mock.await_count == 0
        assert result.event_id
        assert result.title == "Test"

        await asyncio.sleep(0)
        create_mock.assert_awaited_once()
        assert create_mock.await_args.kwargs["uid"] == result.event_id
        schedule.assert_called_once_with(1)

    invalidate_event_cache(1)


@pytest.mark.asyncio
async def test_update_event_returns_immediately_and_writes_in_background():
    db = MagicMock()
    start = datetime(2026, 9, 16, 15, 0)
    end = datetime(2026, 9, 16, 16, 0)
    update_mock = AsyncMock(
        return_value=RawCalendarEvent(
            event_id="uid-1",
            title="Test",
            description="",
            location="",
            start=start,
            end=end,
            raw_text="",
        )
    )
    with (
        patch("app.services.calendar_service.get_active_connection", return_value=_active_conn()),
        patch("app.services.calendar_service.decrypt_credential", return_value="pw"),
        patch("app.services.calendar_service.update_apple_calendar_event", new=update_mock),
        patch("app.services.calendar_service._schedule_post_write_sync") as schedule,
    ):
        result = await update_event_for_user(
            db,
            1,
            "uid-1",
            title="Test",
            description="",
            location="",
            start=start,
            end=end,
        )
        assert update_mock.await_count == 0
        assert result.event_id == "uid-1"

        await asyncio.sleep(0)
        update_mock.assert_awaited_once()
        schedule.assert_called_once_with(1)

    invalidate_event_cache(1)


@pytest.mark.asyncio
async def test_delete_event_returns_immediately_and_writes_in_background():
    db = MagicMock()
    delete_mock = AsyncMock(return_value=True)
    with (
        patch("app.services.calendar_service.get_active_connection", return_value=_active_conn()),
        patch("app.services.calendar_service.decrypt_credential", return_value="pw"),
        patch("app.services.calendar_service.delete_apple_calendar_event", new=delete_mock),
        patch("app.services.calendar_service._schedule_post_write_sync") as schedule,
    ):
        assert await delete_event_for_user(db, 1, "uid-1") is True
        assert delete_mock.await_count == 0

        await asyncio.sleep(0)
        delete_mock.assert_awaited_once()
        schedule.assert_called_once_with(1)

    invalidate_event_cache(1)
