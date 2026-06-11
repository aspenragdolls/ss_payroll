"""add tier 3 weight and update tier proportions

Revision ID: 005_add_tier_3_weight
Revises: 004_add_job_is_cash
Create Date: 2026-06-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_add_tier_3_weight"
down_revision: Union[str, None] = "004_add_job_is_cash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "payroll_configs",
        "tier_1_weight",
        existing_type=sa.Numeric(precision=5, scale=2),
        type_=sa.Numeric(precision=6, scale=3),
        existing_nullable=False,
    )
    op.alter_column(
        "payroll_configs",
        "tier_2_weight",
        existing_type=sa.Numeric(precision=5, scale=2),
        type_=sa.Numeric(precision=6, scale=3),
        existing_nullable=False,
    )
    op.add_column(
        "payroll_configs",
        sa.Column(
            "tier_3_weight",
            sa.Numeric(precision=6, scale=3),
            nullable=False,
            server_default="0.650",
        ),
    )
    op.alter_column("payroll_configs", "tier_3_weight", server_default=None)

    op.execute(
        """
        UPDATE payroll_configs
        SET tier_1_weight = 1.000,
            tier_2_weight = 0.825,
            tier_3_weight = 0.650
        """
    )


def downgrade() -> None:
    op.drop_column("payroll_configs", "tier_3_weight")
    op.alter_column(
        "payroll_configs",
        "tier_1_weight",
        existing_type=sa.Numeric(precision=6, scale=3),
        type_=sa.Numeric(precision=5, scale=2),
        existing_nullable=False,
    )
    op.alter_column(
        "payroll_configs",
        "tier_2_weight",
        existing_type=sa.Numeric(precision=6, scale=3),
        type_=sa.Numeric(precision=5, scale=2),
        existing_nullable=False,
    )
