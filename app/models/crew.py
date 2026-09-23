from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Crew(Base):
    __tablename__ = "crews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    apple_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_bookable_online: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="crews")
    members = relationship(
        "CrewMember", back_populates="crew", cascade="all, delete-orphan"
    )
    bookings = relationship("Booking", back_populates="crew")


class CrewMember(Base):
    __tablename__ = "crew_members"
    __table_args__ = (UniqueConstraint("crew_id", "worker_id", name="uq_crew_worker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crew_id: Mapped[int] = mapped_column(ForeignKey("crews.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    crew = relationship("Crew", back_populates="members")
    worker = relationship("Worker", back_populates="crew_memberships")
