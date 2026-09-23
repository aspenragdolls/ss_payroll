"""add job timer fields on customers for crew duration tracking

Revision ID: 011_job_timer_fields
Revises: 010_business_goals
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_job_timer_fields"
down_revision: Union[str, None] = "010_business_goals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("job_started_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "customers",
        sa.Column("job_finished_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "customers",
        sa.Column("job_duration_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customers", "job_duration_minutes")
    op.drop_column("customers", "job_finished_at")
    op.drop_column("customers", "job_started_at")
