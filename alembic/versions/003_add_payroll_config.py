"""add payroll config

Revision ID: 003_add_payroll_config
Revises: 002_add_job_tips
Create Date: 2026-06-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_add_payroll_config"
down_revision: Union[str, None] = "002_add_job_tips"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("labor_pool_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("commission_pool_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("business_retained_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("tier_1_weight", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("tier_2_weight", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("payroll_configs")
