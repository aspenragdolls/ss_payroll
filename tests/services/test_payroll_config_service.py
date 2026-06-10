from decimal import Decimal

import pytest

from app.services.payroll_config_service import (
    PayrollConfigValues,
    default_config_values,
    parse_config_form,
    validate_config_values,
)


def test_default_config_adds_to_100():
    config = default_config_values()
    assert config.percent_total == Decimal("100")
    assert not validate_config_values(config)


def test_parse_config_form_valid():
    values, errors = parse_config_form(
        labor_pool_percent="55",
        commission_pool_percent="25",
        business_retained_percent="20",
        tier_1_weight="2",
        tier_2_weight="1",
    )
    assert not errors
    assert values is not None
    assert values.labor_pool_percent == Decimal("55")
    assert values.commission_pool_percent == Decimal("25")


def test_parse_config_form_rejects_invalid_total():
    values, errors = parse_config_form(
        labor_pool_percent="50",
        commission_pool_percent="20",
        business_retained_percent="20",
        tier_1_weight="1.5",
        tier_2_weight="1",
    )
    assert values is None
    assert any("100%" in e for e in errors)


def test_parse_config_form_rejects_non_numeric():
    values, errors = parse_config_form(
        labor_pool_percent="abc",
        commission_pool_percent="20",
        business_retained_percent="20",
        tier_1_weight="1.5",
        tier_2_weight="1",
    )
    assert values is None
    assert errors


def test_validate_rejects_zero_tier_weight():
    values = PayrollConfigValues(
        labor_pool_percent=Decimal("60"),
        commission_pool_percent=Decimal("20"),
        business_retained_percent=Decimal("20"),
        tier_1_weight=Decimal("0"),
        tier_2_weight=Decimal("1"),
    )
    errors = validate_config_values(values)
    assert any("greater than zero" in e for e in errors)
