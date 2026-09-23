from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Statuses where the customer is still in the active book of business.
ACTIVE_STATUSES = frozenset({"lead", "quoted", "active", "estimate", "scheduled"})


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    neighborhood: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    zip_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    lead_source: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    services: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    usual_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    service_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_service_due: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    allow_email: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_sms: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_mail: Mapped[bool] = mapped_column(Boolean, default=True)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="customers")
    jobs = relationship("Job", back_populates="customer")
