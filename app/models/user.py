from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    workers = relationship("Worker", back_populates="user", cascade="all, delete-orphan")
    customers = relationship("Customer", back_populates="user", cascade="all, delete-orphan")
    payroll_batches = relationship("PayrollBatch", back_populates="user", cascade="all, delete-orphan")
    calendar_connections = relationship(
        "CalendarConnection", back_populates="user", cascade="all, delete-orphan"
    )
    accounting_records = relationship(
        "AccountingRecord", back_populates="user", cascade="all, delete-orphan"
    )
    payroll_config = relationship(
        "PayrollConfig", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    business_goals = relationship(
        "BusinessGoals", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    crews = relationship("Crew", back_populates="user", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="user", cascade="all, delete-orphan")
    service_packages = relationship(
        "ServicePackage", back_populates="user", cascade="all, delete-orphan"
    )
    quotes = relationship("Quote", back_populates="user", cascade="all, delete-orphan")
    customer_accounts = relationship(
        "CustomerAccount", back_populates="user", cascade="all, delete-orphan"
    )
    scheduling_settings = relationship(
        "SchedulingSettings", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
