"""add customer CRM marketing and filter fields

Revision ID: 007_customer_crm_fields
Revises: 006_add_customers
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007_customer_crm_fields"
down_revision: Union[str, None] = "006_add_customers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
    )
    op.add_column("customers", sa.Column("neighborhood", sa.String(length=128), nullable=True))
    op.add_column("customers", sa.Column("zip_code", sa.String(length=16), nullable=True))
    op.add_column("customers", sa.Column("latitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("customers", sa.Column("longitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("customers", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("customers", sa.Column("lead_source", sa.String(length=64), nullable=True))
    op.add_column(
        "customers",
        sa.Column(
            "services",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column("customers", sa.Column("next_service_due", sa.Date(), nullable=True))
    op.add_column(
        "customers",
        sa.Column("allow_email", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "customers",
        sa.Column("allow_sms", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "customers",
        sa.Column("allow_mail", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "customers",
        sa.Column(
            "do_not_contact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.execute(
        """
        UPDATE customers
        SET status = CASE WHEN is_active THEN 'active' ELSE 'past_customer' END
        """
    )
    op.create_index("ix_customers_status", "customers", ["status"], unique=False)
    op.create_index("ix_customers_neighborhood", "customers", ["neighborhood"], unique=False)
    op.create_index("ix_customers_zip_code", "customers", ["zip_code"], unique=False)
    op.create_index("ix_customers_lead_source", "customers", ["lead_source"], unique=False)
    op.create_index(
        "ix_customers_next_service_due", "customers", ["next_service_due"], unique=False
    )

    op.alter_column("customers", "status", server_default=None)
    op.alter_column("customers", "allow_email", server_default=None)
    op.alter_column("customers", "allow_sms", server_default=None)
    op.alter_column("customers", "allow_mail", server_default=None)
    op.alter_column("customers", "do_not_contact", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_customers_next_service_due", table_name="customers")
    op.drop_index("ix_customers_lead_source", table_name="customers")
    op.drop_index("ix_customers_zip_code", table_name="customers")
    op.drop_index("ix_customers_neighborhood", table_name="customers")
    op.drop_index("ix_customers_status", table_name="customers")
    op.drop_column("customers", "do_not_contact")
    op.drop_column("customers", "allow_mail")
    op.drop_column("customers", "allow_sms")
    op.drop_column("customers", "allow_email")
    op.drop_column("customers", "next_service_due")
    op.drop_column("customers", "services")
    op.drop_column("customers", "lead_source")
    op.drop_column("customers", "email")
    op.drop_column("customers", "longitude")
    op.drop_column("customers", "latitude")
    op.drop_column("customers", "zip_code")
    op.drop_column("customers", "neighborhood")
    op.drop_column("customers", "status")
