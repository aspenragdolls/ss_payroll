"""add calendar_event_uid and last_synced_at for bidirectional sync

Revision ID: 009_calendar_sync_fields
Revises: 008_customer_event_fields
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_calendar_sync_fields"
down_revision: Union[str, None] = "008_customer_event_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("calendar_event_uid", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_customers_calendar_event_uid",
        "customers",
        ["calendar_event_uid"],
        unique=False,
    )
    op.add_column(
        "calendar_connections",
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("calendar_connections", "last_synced_at")
    op.drop_index("ix_customers_calendar_event_uid", table_name="customers")
    op.drop_column("customers", "calendar_event_uid")
