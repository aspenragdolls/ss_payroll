from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.domain.enums import PayrollStatus
from app.domain.payroll_stages import PAYROLL_STAGES, stage_index
from app.models.payroll import PayrollBatch
from app.services import payroll_service


def test_stage_index_order():
    assert stage_index("jobs") < stage_index("assign")
    assert stage_index("assign") < stage_index("hours")
    assert stage_index("hours") < stage_index("calculate")
    assert stage_index("calculate") < stage_index("finalize")
    assert len(PAYROLL_STAGES) == 5


def test_infer_batch_stage_from_session_hours():
    batch = PayrollBatch(
        id=1,
        user_id=1,
        status=PayrollStatus.DRAFT.value,
        session_data_json={"daily_hours": {"1|2026-06-01": "8"}},
    )
    db = MagicMock()
    db.scalar.return_value = 0
    with patch.object(payroll_service, "get_assignments_for_batch", return_value=[]):
        assert payroll_service.infer_batch_stage(db, batch) == "hours"


def test_infer_batch_stage_from_assignments():
    batch = PayrollBatch(id=1, user_id=1, status=PayrollStatus.DRAFT.value)
    db = MagicMock()
    db.scalar.return_value = 0
    with patch.object(payroll_service, "get_assignments_for_batch", return_value=[object()]):
        assert payroll_service.infer_batch_stage(db, batch) == "assign"


def test_navigate_back_resets_later_progress():
    batch = PayrollBatch(
        id=1,
        user_id=1,
        status=PayrollStatus.REVIEW.value,
        session_data_json={"stage": "calculate", "daily_hours": {"1|2026-06-01": "8"}},
    )
    db = MagicMock()
    db.scalar.return_value = 1

    with (
        patch.object(payroll_service, "reset_progress_after") as reset_mock,
        patch.object(payroll_service, "set_batch_stage") as set_stage_mock,
    ):
        result = payroll_service.navigate_to_stage(db, batch, "assign")

    assert result == "assign"
    reset_mock.assert_called_once_with(db, batch, "assign")
    set_stage_mock.assert_called_once_with(db, batch, "assign")


def test_navigate_forward_one_step():
    batch = PayrollBatch(
        id=1,
        user_id=1,
        status=PayrollStatus.DRAFT.value,
        session_data_json={"stage": "jobs"},
    )
    db = MagicMock()

    with (
        patch.object(payroll_service, "reset_progress_after") as reset_mock,
        patch.object(payroll_service, "set_batch_stage") as set_stage_mock,
        patch.object(payroll_service, "get_batch_stage", return_value="jobs"),
    ):
        result = payroll_service.navigate_to_stage(db, batch, "assign")

    assert result == "assign"
    reset_mock.assert_not_called()
    set_stage_mock.assert_called_once_with(db, batch, "assign")


def test_navigate_skip_ahead_blocked():
    batch = PayrollBatch(
        id=1,
        user_id=1,
        status=PayrollStatus.DRAFT.value,
        session_data_json={"stage": "jobs"},
    )
    db = MagicMock()

    with (
        patch.object(payroll_service, "reset_progress_after") as reset_mock,
        patch.object(payroll_service, "set_batch_stage") as set_stage_mock,
        patch.object(payroll_service, "get_batch_stage", return_value="jobs"),
    ):
        result = payroll_service.navigate_to_stage(db, batch, "calculate")

    assert result == "jobs"
    reset_mock.assert_not_called()
    set_stage_mock.assert_not_called()


def test_reset_progress_after_jobs_clears_assignments_and_results():
    batch = PayrollBatch(id=1, user_id=1, status=PayrollStatus.REVIEW.value)
    job = MagicMock(id=10)
    assignment = MagicMock(hours_assigned=Decimal("4"))
    db = MagicMock()

    with (
        patch.object(payroll_service, "get_jobs_for_batch", return_value=[job]),
        patch.object(payroll_service, "clear_assignments_for_job") as clear_mock,
        patch.object(payroll_service, "get_assignments_for_batch", return_value=[assignment]),
    ):
        payroll_service.reset_progress_after(db, batch, "jobs")

    clear_mock.assert_called_once_with(db, 10)
    assert assignment.hours_assigned is None
    assert batch.status == PayrollStatus.DRAFT.value
    db.execute.assert_called()
    db.commit.assert_called()


def test_delete_in_progress_batch_rejects_finalized():
    batch = PayrollBatch(id=1, user_id=1, status=PayrollStatus.FINALIZED.value)
    db = MagicMock()

    with pytest.raises(PermissionError):
        payroll_service.delete_in_progress_batch(db, batch)

    db.delete.assert_not_called()


def test_delete_in_progress_batch_deletes_draft():
    batch = PayrollBatch(id=1, user_id=1, status=PayrollStatus.DRAFT.value)
    db = MagicMock()

    payroll_service.delete_in_progress_batch(db, batch)

    db.delete.assert_called_once_with(batch)
    db.commit.assert_called_once()
