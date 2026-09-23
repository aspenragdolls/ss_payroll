"""add customer usual_price and service_scope for event entry

Revision ID: 008_customer_event_fields
Revises: 007_customer_crm_fields
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_customer_event_fields"
down_revision: Union[str, None] = "007_customer_crm_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("usual_price", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "customers",
        sa.Column("service_scope", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customers", "service_scope")
    op.drop_column("customers", "usual_price")
