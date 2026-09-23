from decimal import Decimal

from app.services.event_format import (
    build_event_description,
    build_event_title,
    infer_customer_status,
    merge_services,
    scope_for_classification,
    service_description_line,
    status_display_label,
)


def test_build_event_title_integer_price():
    assert build_event_title("Parks Mangelson", Decimal("322")) == "Parks Mangelson ($322)"


def test_build_event_title_decimal_price():
    assert build_event_title("Smith", "450.50") == "Smith ($450.50)"


def test_build_event_description_phone_then_service():
    text = build_event_description(
        "801-376-7998",
        "windows",
        "inside_and_outside",
    )
    assert text == "801-376-7998\n\nInside and outside"


def test_build_event_description_estimate_with_note():
    text = build_event_description("801-555-0100", "estimate", free_note="Gate code 12")
    assert text == "801-555-0100\n\nEstimate\n\nGate code 12"


def test_infer_customer_status():
    assert infer_customer_status("estimate") == "estimate"
    assert infer_customer_status("windows") == "scheduled"
    assert infer_customer_status("gutters") == "scheduled"


def test_status_display_scheduled_includes_scope():
    label = status_display_label(
        "scheduled",
        service_scope="outside_only",
        classification="windows",
    )
    assert label == "Scheduled (Outside only)"


def test_status_display_estimate():
    assert status_display_label("estimate") == "Estimate"


def test_merge_services_keeps_existing():
    merged = merge_services(["lights"], "gutters")
    assert merged == ["lights", "gutters"]


def test_scope_cleared_for_non_windows():
    assert scope_for_classification("gutters", "inside_only") is None
    assert scope_for_classification("windows", "partial") == "partial"


def test_service_description_line_gutters():
    assert service_description_line("gutters") == "Gutters"
