from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PayrollBatch(Base):
    __tablename__ = "payroll_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    pay_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_data_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="payroll_batches")
    jobs = relationship("Job", back_populates="payroll_batch", cascade="all, delete-orphan")
    payroll_results = relationship(
        "PayrollResult", back_populates="payroll_batch", cascade="all, delete-orphan"
    )
    payroll_job_results = relationship(
        "PayrollJobResult", back_populates="payroll_batch", cascade="all, delete-orphan"
    )


class PayrollResult(Base):
    __tablename__ = "payroll_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payroll_batch_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_batches.id", ondelete="CASCADE"), index=True
    )
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    total_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    labor_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    commission_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    hourly_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    adjustment_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    calculation_snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    payroll_batch = relationship("PayrollBatch", back_populates="payroll_results")
    worker = relationship("Worker")


class PayrollJobResult(Base):
    __tablename__ = "payroll_job_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payroll_batch_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_batches.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    ticket_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    labor_pool: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    hourly_component: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    percentage_component: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    commission_component: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    adjustment_component: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    final_worker_job_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    calculation_snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    payroll_batch = relationship("PayrollBatch", back_populates="payroll_job_results")
    job = relationship("Job")
    worker = relationship("Worker")
