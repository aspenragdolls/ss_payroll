"""Rate feedback helpers."""

from decimal import Decimal

from app.services.rate_feedback_service import _dph


def test_dph_from_price_and_minutes():
    # $300 in 2 hours = $150/hr
    assert _dph(Decimal("300"), 120) == Decimal("150.00")


def test_dph_handles_missing():
    assert _dph(None, 120) is None
    assert _dph(Decimal("300"), 0) is None
