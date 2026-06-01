from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    payroll_batch_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_batches.id", ondelete="CASCADE"), index=True
    )
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    service_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticket_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    job_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    validation_flags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    payroll_batch = relationship("PayrollBatch", back_populates="jobs")
    assignments = relationship(
        "JobWorkerAssignment", back_populates="job", cascade="all, delete-orphan"
    )


class JobWorkerAssignment(Base):
    __tablename__ = "job_worker_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    roles: Mapped[list] = mapped_column(JSONB, default=lambda: [])
    effective_pay_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    effective_percentage_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    effective_hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    hours_assigned: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    fixed_adjustment_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    was_globally_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    job = relationship("Job", back_populates="assignments")
    worker = relationship("Worker", back_populates="assignments")
