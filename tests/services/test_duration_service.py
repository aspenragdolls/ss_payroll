"""Tests for duration = price / sum(crew schedule $/hr)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.duration_service import (
    DurationError,
    crew_schedule_rate,
    estimate_duration,
    round_duration_minutes,
    worker_schedule_rate,
)


def test_worker_schedule_rate_ignores_missing():
    assert worker_schedule_rate(SimpleNamespace(schedule_dollars_per_hour=None)) == 0
    assert worker_schedule_rate(SimpleNamespace(schedule_dollars_per_hour=Decimal("75"))) == Decimal(
        "75"
    )


def test_crew_schedule_rate_sums_active_members():
    crew = SimpleNamespace(
        members=[
            SimpleNamespace(
                worker=SimpleNamespace(is_active=True, schedule_dollars_per_hour=Decimal("50"))
            ),
            SimpleNamespace(
                worker=SimpleNamespace(is_active=True, schedule_dollars_per_hour=Decimal("100"))
            ),
            SimpleNamespace(
                worker=SimpleNamespace(is_active=False, schedule_dollars_per_hour=Decimal("999"))
            ),
        ]
    )
    assert crew_schedule_rate(crew) == Decimal("150")


def test_estimate_duration_formula():
    # $300 / $150/hr = 2 hours = 120 minutes
    result = estimate_duration(Decimal("300"), Decimal("150"), grain_minutes=15)
    assert result.minutes == 120
    assert result.source == "formula"


def test_estimate_duration_rounds_up_to_grain():
    # $100 / $150/hr = 0.666... hr = 40 min → rounds up to 45
    result = estimate_duration(Decimal("100"), Decimal("150"), grain_minutes=15)
    assert result.minutes == 45


def test_estimate_duration_override_wins():
    result = estimate_duration(
        Decimal("300"),
        Decimal("150"),
        override_minutes=90,
        prior_job_minutes=200,
    )
    assert result.minutes == 90
    assert result.source == "override"


def test_estimate_duration_prior_job():
    result = estimate_duration(
        Decimal("300"),
        Decimal("150"),
        prior_job_minutes=75,
    )
    assert result.minutes == 75
    assert result.source == "prior_job"


def test_estimate_duration_rejects_zero_rate():
    with pytest.raises(DurationError):
        estimate_duration(Decimal("300"), Decimal("0"))


def test_round_duration_minutes_minimum_grain():
    assert round_duration_minutes(Decimal("1"), grain_minutes=30) == 30
