"""scheduling foundation: crews, rates, bookings, packages, quotes, portal accounts

Revision ID: 012_scheduling_foundation
Revises: 011_job_timer_fields
Create Date: 2026-09-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012_scheduling_foundation"
down_revision: Union[str, None] = "011_job_timer_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workers",
        sa.Column("schedule_dollars_per_hour", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "customers",
        sa.Column("duration_override_minutes", sa.Integer(), nullable=True),
    )

    op.create_table(
        "crews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("apple_calendar_id", sa.String(length=255), nullable=True),
        sa.Column("is_bookable_online", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_crews_user_id"), "crews", ["user_id"], unique=False)

    op.create_table(
        "crew_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crew_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["crew_id"], ["crews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crew_id", "worker_id", name="uq_crew_worker"),
    )
    op.create_index(op.f("ix_crew_members_crew_id"), "crew_members", ["crew_id"], unique=False)
    op.create_index(op.f("ix_crew_members_worker_id"), "crew_members", ["worker_id"], unique=False)

    op.create_table(
        "service_packages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("service_type", sa.String(length=64), nullable=False),
        sa.Column("base_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_service_packages_user_id"), "service_packages", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_service_packages_service_type"), "service_packages", ["service_type"], unique=False
    )

    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("services", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["package_id"], ["service_packages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quotes_user_id"), "quotes", ["user_id"], unique=False)
    op.create_index(op.f("ix_quotes_customer_id"), "quotes", ["customer_id"], unique=False)
    op.create_index(op.f("ix_quotes_package_id"), "quotes", ["package_id"], unique=False)
    op.create_index(op.f("ix_quotes_status"), "quotes", ["status"], unique=False)

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("crew_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("quote_id", sa.Integer(), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("calendar_event_uid", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("duration_source", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["crew_id"], ["crews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bookings_user_id"), "bookings", ["user_id"], unique=False)
    op.create_index(op.f("ix_bookings_crew_id"), "bookings", ["crew_id"], unique=False)
    op.create_index(op.f("ix_bookings_customer_id"), "bookings", ["customer_id"], unique=False)
    op.create_index(op.f("ix_bookings_quote_id"), "bookings", ["quote_id"], unique=False)
    op.create_index(op.f("ix_bookings_starts_at"), "bookings", ["starts_at"], unique=False)
    op.create_index(op.f("ix_bookings_ends_at"), "bookings", ["ends_at"], unique=False)
    op.create_index(
        op.f("ix_bookings_calendar_event_uid"), "bookings", ["calendar_event_uid"], unique=False
    )
    op.create_index(op.f("ix_bookings_status"), "bookings", ["status"], unique=False)

    op.create_table(
        "customer_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_index(op.f("ix_customer_accounts_user_id"), "customer_accounts", ["user_id"], unique=False)
    op.create_index(op.f("ix_customer_accounts_email"), "customer_accounts", ["email"], unique=False)
    op.create_index(
        op.f("ix_customer_accounts_customer_id"), "customer_accounts", ["customer_id"], unique=True
    )

    op.create_table(
        "scheduling_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("business_hours_start", sa.Time(), nullable=True),
        sa.Column("business_hours_end", sa.Time(), nullable=True),
        sa.Column("slot_grain_minutes", sa.Integer(), nullable=True),
        sa.Column("buffer_minutes", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_scheduling_settings_user_id"), "scheduling_settings", ["user_id"], unique=True
    )


def downgrade() -> None:
    op.drop_table("scheduling_settings")
    op.drop_table("customer_accounts")
    op.drop_table("bookings")
    op.drop_table("quotes")
    op.drop_table("service_packages")
    op.drop_table("crew_members")
    op.drop_table("crews")
    op.drop_column("customers", "duration_override_minutes")
    op.drop_column("workers", "schedule_dollars_per_hour")
