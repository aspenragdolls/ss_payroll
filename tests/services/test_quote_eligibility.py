"""Tests for can_self_schedule eligibility and instant estimates."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.quote_service import ScheduleEligibility, can_self_schedule, instant_estimate


def test_instant_estimate_uses_base_price():
    package = SimpleNamespace(
        id=1,
        name="Windows Basic",
        service_type="windows",
        base_price=Decimal("250.00"),
        is_active=True,
    )
    db = MagicMock()
    # get_package is called inside — patch via return of scalar path is heavy;
    # call the logic by monkeypatching get_package.
    from app.services import quote_service

    original = quote_service.get_package
    quote_service.get_package = lambda db, user_id, package_id: package
    try:
        estimate = instant_estimate(db, 1, package_id=1, zip_code="84106")
    finally:
        quote_service.get_package = original

    assert estimate.amount == Decimal("250.00")
    assert estimate.bookable is False
    assert "quote" in estimate.reason.lower()


def test_can_self_schedule_with_accepted_quote(monkeypatch):
    customer = SimpleNamespace(id=10, status="lead", usual_price=None)
    quote = SimpleNamespace(id=5, amount=Decimal("320.00"))

    monkeypatch.setattr(
        "app.services.quote_service._accepted_quote",
        lambda db, user_id, customer_id: quote,
    )
    result = can_self_schedule(MagicMock(), 1, customer)
    assert result.can_schedule is True
    assert result.price == Decimal("320.00")
    assert result.source == "quote"
    assert result.quote_id == 5


def test_can_self_schedule_with_history(monkeypatch):
    customer = SimpleNamespace(id=10, status="active", usual_price=Decimal("280"))

    monkeypatch.setattr(
        "app.services.quote_service._accepted_quote",
        lambda db, user_id, customer_id: None,
    )
    monkeypatch.setattr(
        "app.services.quote_service._has_job_history",
        lambda db, user_id, customer_id: True,
    )
    result = can_self_schedule(MagicMock(), 1, customer)
    assert result.can_schedule is True
    assert result.price == Decimal("280")
    assert result.source == "history"


def test_can_self_schedule_denied_without_quote_or_history(monkeypatch):
    customer = SimpleNamespace(id=10, status="lead", usual_price=None)

    monkeypatch.setattr(
        "app.services.quote_service._accepted_quote",
        lambda db, user_id, customer_id: None,
    )
    monkeypatch.setattr(
        "app.services.quote_service._has_job_history",
        lambda db, user_id, customer_id: False,
    )
    result = can_self_schedule(MagicMock(), 1, customer)
    assert isinstance(result, ScheduleEligibility)
    assert result.can_schedule is False
