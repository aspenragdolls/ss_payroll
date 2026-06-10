"""add job is_cash flag

Revision ID: 004_add_job_is_cash
Revises: 003_add_payroll_config
Create Date: 2026-06-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_add_job_is_cash"
down_revision: Union[str, None] = "003_add_payroll_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("is_cash", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("jobs", "is_cash", server_default=None)


def downgrade() -> None:
    op.drop_column("jobs", "is_cash")
