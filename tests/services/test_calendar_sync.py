from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.calendar import CalendarConnection
from app.models.customer import Customer
from app.services.apple_calendar import delete_apple_calendar_event
from app.services.calendar_sync_service import sync_calendar_to_app
from app.services.event_format import build_event_description, build_event_title
from app.services.event_parse import parse_event_for_app, parse_title_name_price
from app.services.schemas import RawCalendarEvent


def test_parse_title_name_price():
    name, price = parse_title_name_price("Parks Mangelson ($322)")
    assert name == "Parks Mangelson"
    assert price == "322"


def test_parse_event_for_app_windows():
    event = RawCalendarEvent(
        event_id="uid-1",
        title=build_event_title("Parks Mangelson", 322),
        description=build_event_description("801-376-7998", "windows", "inside_and_outside"),
        location="1446 E 900 S",
        start=datetime(2026, 9, 16, 15, 0),
        end=datetime(2026, 9, 16, 16, 0),
        raw_text="",
    )
    parsed = parse_event_for_app(event)
    assert parsed["customer_name"] == "Parks Mangelson"
    assert parsed["price"] == "322"
    assert parsed["classification"] == "windows"
    assert parsed["service_scope"] == "inside_and_outside"
    assert parsed["phone"] == "801-376-7998"
    assert parsed["calendar_event_uid"] == "uid-1"


@pytest.mark.asyncio
async def test_delete_apple_calendar_event_issues_delete():
    mock_response = MagicMock()
    mock_response.status_code = 204
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.services.apple_calendar._auth_client", return_value=mock_client),
        patch(
            "app.services.apple_calendar._resolve_calendar_urls",
            new=AsyncMock(return_value=["https://caldav.icloud.com/calendars/work/"]),
        ),
    ):
        ok = await delete_apple_calendar_event(
            "user@icloud.com",
            "app-password",
            "Work",
            "fixed-uid",
        )

    assert ok is True
    mock_client.delete.assert_awaited_once()
    assert mock_client.delete.await_args.args[0].endswith("fixed-uid.ics")


@pytest.mark.asyncio
async def test_sync_calendar_to_app_upserts_and_clears():
    conn = CalendarConnection(
        id=1,
        user_id=1,
        provider="apple",
        external_account_id="user@icloud.com",
        access_token_encrypted="enc",
        calendar_id="Work",
        is_active=True,
        last_synced_at=None,
    )
    linked = Customer(
        id=10,
        user_id=1,
        name="Gone Customer",
        status="scheduled",
        calendar_event_uid="missing-uid",
        next_service_due=date.today(),
        is_active=True,
    )
    existing = Customer(
        id=11,
        user_id=1,
        name="Parks Mangelson",
        status="active",
        calendar_event_uid=None,
        is_active=True,
    )

    db = MagicMock()
    name_match = MagicMock()
    name_match.first.return_value = existing
    db.scalars.return_value = name_match

    event = RawCalendarEvent(
        event_id="uid-keep",
        title="Parks Mangelson ($322)",
        description="801-376-7998\n\nInside and outside",
        location="1446 E 900 S",
        start=datetime.now() + timedelta(days=2),
        end=datetime.now() + timedelta(days=2, hours=1),
        raw_text="",
    )

    with (
        patch(
            "app.services.calendar_sync_service.get_active_connection",
            return_value=conn,
        ),
        patch(
            "app.services.calendar_sync_service.fetch_events_for_user",
            new=AsyncMock(return_value=[event]),
        ),
        patch(
            "app.services.calendar_sync_service.get_customer_by_calendar_uid",
            return_value=None,
        ),
        patch(
            "app.services.calendar_sync_service.list_customers_with_calendar_uid",
            return_value=[linked],
        ),
        patch(
            "app.services.calendar_sync_service.upsert_customer_from_event",
            return_value=existing,
        ) as upsert,
    ):
        result = await sync_calendar_to_app(db, 1, force=True)

    assert result.upserted == 1
    assert result.cleared == 1
    assert linked.calendar_event_uid is None
    assert linked.status == "active"
    upsert.assert_called_once()
    kwargs = upsert.call_args.kwargs
    assert kwargs["calendar_event_uid"] == "uid-keep"
    assert kwargs["customer_id"] == 11
    assert kwargs["name"] == "Parks Mangelson"
    assert kwargs["usual_price"] == Decimal("322")
    assert conn.last_synced_at is not None
    db.commit.assert_called()


@pytest.mark.asyncio
async def test_sync_skips_when_recently_synced():
    conn = CalendarConnection(
        id=1,
        user_id=1,
        provider="apple",
        external_account_id="user@icloud.com",
        access_token_encrypted="enc",
        calendar_id="Work",
        is_active=True,
        last_synced_at=datetime.utcnow(),
    )
    db = MagicMock()
    with (
        patch(
            "app.services.calendar_sync_service.get_active_connection",
            return_value=conn,
        ),
        patch(
            "app.services.calendar_sync_service.fetch_events_for_user",
            new=AsyncMock(),
        ) as fetch,
    ):
        result = await sync_calendar_to_app(db, 1, force=False)

    assert result.skipped is True
    fetch.assert_not_awaited()
