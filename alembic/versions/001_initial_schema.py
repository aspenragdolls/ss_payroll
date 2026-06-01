"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-05-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("business_name", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "workers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("labor_pay_type", sa.String(length=32), nullable=True),
        sa.Column("labor_percentage_tier", sa.String(length=32), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workers_user_id"), "workers", ["user_id"], unique=False)

    op.create_table(
        "calendar_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("calendar_id", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_calendar_connections_user_id"), "calendar_connections", ["user_id"], unique=False)

    op.create_table(
        "payroll_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("session_data_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payroll_batches_user_id"), "payroll_batches", ["user_id"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("payroll_batch_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=512), nullable=True),
        sa.Column("service_description", sa.Text(), nullable=True),
        sa.Column("ticket_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("job_date", sa.Date(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("validation_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payroll_batch_id"], ["payroll_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_payroll_batch_id"), "jobs", ["payroll_batch_id"], unique=False)
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"], unique=False)

    op.create_table(
        "accounting_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("payroll_batch_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payroll_batch_id"], ["payroll_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_accounting_records_user_id"), "accounting_records", ["user_id"], unique=False)

    op.create_table(
        "job_worker_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("effective_pay_type", sa.String(length=32), nullable=True),
        sa.Column("effective_percentage_tier", sa.String(length=32), nullable=True),
        sa.Column("effective_hourly_rate", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("hours_assigned", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("fixed_adjustment_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("was_globally_selected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_worker_assignments_job_id"), "job_worker_assignments", ["job_id"], unique=False)
    op.create_index(op.f("ix_job_worker_assignments_worker_id"), "job_worker_assignments", ["worker_id"], unique=False)

    op.create_table(
        "payroll_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payroll_batch_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("total_pay", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("labor_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("commission_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("hourly_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("adjustment_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("calculation_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payroll_batch_id"], ["payroll_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payroll_results_payroll_batch_id"), "payroll_results", ["payroll_batch_id"], unique=False)
    op.create_index(op.f("ix_payroll_results_worker_id"), "payroll_results", ["worker_id"], unique=False)

    op.create_table(
        "payroll_job_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payroll_batch_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("ticket_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("labor_pool", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("hourly_component", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("percentage_component", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("commission_component", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("adjustment_component", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("final_worker_job_pay", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("calculation_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payroll_batch_id"], ["payroll_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payroll_job_results_job_id"), "payroll_job_results", ["job_id"], unique=False)
    op.create_index(op.f("ix_payroll_job_results_payroll_batch_id"), "payroll_job_results", ["payroll_batch_id"], unique=False)
    op.create_index(op.f("ix_payroll_job_results_worker_id"), "payroll_job_results", ["worker_id"], unique=False)


def downgrade() -> None:
    op.drop_table("payroll_job_results")
    op.drop_table("payroll_results")
    op.drop_table("job_worker_assignments")
    op.drop_table("accounting_records")
    op.drop_table("jobs")
    op.drop_table("payroll_batches")
    op.drop_table("calendar_connections")
    op.drop_table("workers")
    op.drop_table("users")
