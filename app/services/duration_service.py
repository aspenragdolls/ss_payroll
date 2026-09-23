"""Duration estimation for crew calendar bookings.

duration_hours = job_price / sum(crew schedule_dollars_per_hour)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from app.models.crew import Crew
from app.models.worker import Worker


class DurationError(Exception):
    """Cannot estimate duration (e.g. zero crew rate)."""


@dataclass(frozen=True)
class DurationEstimate:
    minutes: int
    source: str  # formula | override | prior_job
    crew_rate: Decimal
    price: Decimal


def _as_decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def worker_schedule_rate(worker: Worker) -> Decimal:
    rate = _as_decimal(worker.schedule_dollars_per_hour)
    if rate is None or rate <= 0:
        return Decimal("0")
    return rate


def crew_schedule_rate(crew: Crew, workers: list[Worker] | None = None) -> Decimal:
    """Sum of active members' schedule $/hr."""
    if workers is not None:
        return sum((worker_schedule_rate(w) for w in workers), Decimal("0"))

    total = Decimal("0")
    for membership in crew.members or []:
        worker = membership.worker
        if worker is None or not worker.is_active:
            continue
        total += worker_schedule_rate(worker)
    return total


def round_duration_minutes(raw_minutes: Decimal, grain_minutes: int = 15) -> int:
    """Round up to the next slot grain (minimum one grain)."""
    grain = max(1, int(grain_minutes))
    if raw_minutes <= 0:
        return grain
    grains = (raw_minutes / Decimal(grain)).to_integral_value(rounding=ROUND_CEILING)
    minutes = int(grains) * grain
    return max(grain, minutes)


def estimate_duration(
    price: Decimal | int | float | str,
    crew_rate: Decimal | int | float | str,
    *,
    override_minutes: int | None = None,
    prior_job_minutes: int | None = None,
    grain_minutes: int = 15,
) -> DurationEstimate:
    """Estimate calendar duration for a job price on a crew.

    Preference: explicit override → prior job duration → price/crew_rate formula.
    """
    price_dec = _as_decimal(price)
    if price_dec is None or price_dec <= 0:
        raise DurationError("Job price must be greater than zero.")

    if override_minutes is not None and override_minutes > 0:
        return DurationEstimate(
            minutes=int(override_minutes),
            source="override",
            crew_rate=_as_decimal(crew_rate) or Decimal("0"),
            price=price_dec,
        )

    if prior_job_minutes is not None and prior_job_minutes > 0:
        return DurationEstimate(
            minutes=int(prior_job_minutes),
            source="prior_job",
            crew_rate=_as_decimal(crew_rate) or Decimal("0"),
            price=price_dec,
        )

    rate = _as_decimal(crew_rate)
    if rate is None or rate <= 0:
        raise DurationError(
            "Crew schedule rate is zero. Set schedule $/hr on each crew member."
        )

    hours = price_dec / rate
    minutes = round_duration_minutes(hours * Decimal(60), grain_minutes=grain_minutes)
    return DurationEstimate(
        minutes=minutes,
        source="formula",
        crew_rate=rate,
        price=price_dec,
    )


def estimate_duration_for_crew(
    price: Decimal | int | float | str,
    crew: Crew,
    *,
    override_minutes: int | None = None,
    prior_job_minutes: int | None = None,
    grain_minutes: int = 15,
) -> DurationEstimate:
    return estimate_duration(
        price,
        crew_schedule_rate(crew),
        override_minutes=override_minutes,
        prior_job_minutes=prior_job_minutes,
        grain_minutes=grain_minutes,
    )
