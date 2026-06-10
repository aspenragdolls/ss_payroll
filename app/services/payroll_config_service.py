from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import Tier
from app.domain.schemas import PayrollRates
from app.models.payroll_config import PayrollConfig

DEFAULT_LABOR_PERCENT = Decimal("60")
DEFAULT_COMMISSION_PERCENT = Decimal("20")
DEFAULT_BUSINESS_PERCENT = Decimal("20")
DEFAULT_TIER_1_WEIGHT = Decimal("1.5")
DEFAULT_TIER_2_WEIGHT = Decimal("1.0")
PERCENT_TOTAL = Decimal("100")


@dataclass
class PayrollConfigValues:
    labor_pool_percent: Decimal
    commission_pool_percent: Decimal
    business_retained_percent: Decimal
    tier_1_weight: Decimal
    tier_2_weight: Decimal

    @property
    def percent_total(self) -> Decimal:
        return (
            self.labor_pool_percent
            + self.commission_pool_percent
            + self.business_retained_percent
        )

    def to_rates(self) -> PayrollRates:
        return PayrollRates(
            labor_pool_rate=self.labor_pool_percent / PERCENT_TOTAL,
            commission_pool_rate=self.commission_pool_percent / PERCENT_TOTAL,
            tier_weights={
                Tier.TIER_1.value: self.tier_1_weight,
                Tier.TIER_2.value: self.tier_2_weight,
            },
        )


def default_config_values() -> PayrollConfigValues:
    return PayrollConfigValues(
        labor_pool_percent=DEFAULT_LABOR_PERCENT,
        commission_pool_percent=DEFAULT_COMMISSION_PERCENT,
        business_retained_percent=DEFAULT_BUSINESS_PERCENT,
        tier_1_weight=DEFAULT_TIER_1_WEIGHT,
        tier_2_weight=DEFAULT_TIER_2_WEIGHT,
    )


def _from_model(config: PayrollConfig) -> PayrollConfigValues:
    return PayrollConfigValues(
        labor_pool_percent=config.labor_pool_percent,
        commission_pool_percent=config.commission_pool_percent,
        business_retained_percent=config.business_retained_percent,
        tier_1_weight=config.tier_1_weight,
        tier_2_weight=config.tier_2_weight,
    )


def get_payroll_config(db: Session, user_id: int) -> PayrollConfigValues:
    config = db.scalar(select(PayrollConfig).where(PayrollConfig.user_id == user_id))
    if not config:
        return default_config_values()
    return _from_model(config)


def get_payroll_rates(db: Session, user_id: int) -> PayrollRates:
    return get_payroll_config(db, user_id).to_rates()


def parse_decimal(value: str, field_name: str) -> tuple[Decimal | None, str | None]:
    cleaned = value.strip()
    if not cleaned:
        return None, f"{field_name} is required."
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        return None, f"{field_name} must be a valid number."
    if parsed < 0:
        return None, f"{field_name} cannot be negative."
    return parsed, None


def parse_config_form(
    *,
    labor_pool_percent: str,
    commission_pool_percent: str,
    business_retained_percent: str,
    tier_1_weight: str,
    tier_2_weight: str,
) -> tuple[PayrollConfigValues | None, list[str]]:
    errors: list[str] = []
    fields = [
        ("Labor pool", labor_pool_percent),
        ("Commission pool", commission_pool_percent),
        ("Business retained", business_retained_percent),
        ("Tier 1 weight", tier_1_weight),
        ("Tier 2 weight", tier_2_weight),
    ]
    parsed: dict[str, Decimal] = {}
    for label, raw in fields:
        value, error = parse_decimal(raw, label)
        if error:
            errors.append(error)
        elif value is not None:
            parsed[label] = value

    if errors:
        return None, errors

    values = PayrollConfigValues(
        labor_pool_percent=parsed["Labor pool"],
        commission_pool_percent=parsed["Commission pool"],
        business_retained_percent=parsed["Business retained"],
        tier_1_weight=parsed["Tier 1 weight"],
        tier_2_weight=parsed["Tier 2 weight"],
    )
    errors.extend(validate_config_values(values))
    if errors:
        return None, errors
    return values, []


def validate_config_values(values: PayrollConfigValues) -> list[str]:
    errors: list[str] = []
    total = values.percent_total
    if total != PERCENT_TOTAL:
        errors.append(
            f"Ticket breakdown must add up to 100% (currently {total.normalize()}%). "
            "Adjust labor, commission, and business retained percentages."
        )
    if values.tier_1_weight <= 0 or values.tier_2_weight <= 0:
        errors.append("Tier weights must be greater than zero.")
    return errors


def save_payroll_config(db: Session, user_id: int, values: PayrollConfigValues) -> PayrollConfig:
    config = db.scalar(select(PayrollConfig).where(PayrollConfig.user_id == user_id))
    if not config:
        config = PayrollConfig(user_id=user_id)
        db.add(config)

    config.labor_pool_percent = values.labor_pool_percent
    config.commission_pool_percent = values.commission_pool_percent
    config.business_retained_percent = values.business_retained_percent
    config.tier_1_weight = values.tier_1_weight
    config.tier_2_weight = values.tier_2_weight
    db.commit()
    db.refresh(config)
    return config
