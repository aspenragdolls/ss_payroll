"""add customers table and jobs.customer_id

Revision ID: 006_add_customers
Revises: 005_add_tier_3_weight
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_add_customers"
down_revision: Union[str, None] = "005_add_tier_3_weight"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=512), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("aliases", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customers_user_id"), "customers", ["user_id"], unique=False)
    op.alter_column("customers", "is_active", server_default=None)

    op.add_column("jobs", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_jobs_customer_id"), "jobs", ["customer_id"], unique=False)
    op.create_foreign_key(
        "fk_jobs_customer_id_customers",
        "jobs",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_jobs_customer_id_customers", "jobs", type_="foreignkey")
    op.drop_index(op.f("ix_jobs_customer_id"), table_name="jobs")
    op.drop_column("jobs", "customer_id")
    op.drop_index(op.f("ix_customers_user_id"), table_name="customers")
    op.drop_table("customers")
