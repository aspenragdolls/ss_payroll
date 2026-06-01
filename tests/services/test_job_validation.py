from decimal import Decimal

import pytest

from app.services.job_validation import validate_draft_job
from app.services.schemas import DraftJob


def test_validate_flags_missing_customer():
    draft = DraftJob(
        customer_name=None,
        address="123 Main",
        service_description=None,
        final_ticket_price="100",
        job_date=None,
    )
    _, flags = validate_draft_job(draft)
    assert "missing_customer_name" in flags


def test_validate_flags_invalid_price():
    draft = DraftJob(
        customer_name="Test",
        address="123 Main",
        service_description=None,
        final_ticket_price="-50",
        job_date=None,
    )
    _, flags = validate_draft_job(draft)
    assert "invalid_ticket_price" in flags


def test_validate_flags_missing_price():
    draft = DraftJob(
        customer_name="Test",
        address="123 Main",
        service_description=None,
        final_ticket_price=None,
        job_date=None,
    )
    _, flags = validate_draft_job(draft)
    assert "missing_ticket_price" in flags
