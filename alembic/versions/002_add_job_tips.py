"""add job tips and payroll tips component

Revision ID: 002_add_job_tips
Revises: 001_initial
Create Date: 2026-06-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_add_job_tips"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("tips", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "payroll_job_results",
        sa.Column(
            "tips_component",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("payroll_job_results", "tips_component", server_default=None)


def downgrade() -> None:
    op.drop_column("payroll_job_results", "tips_component")
    op.drop_column("jobs", "tips")
