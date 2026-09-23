from datetime import datetime, time

from sqlalchemy import DateTime, ForeignKey, Integer, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SchedulingSettings(Base):
    __tablename__ = "scheduling_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    business_hours_start: Mapped[time] = mapped_column(Time, default=time(8, 0))
    business_hours_end: Mapped[time] = mapped_column(Time, default=time(17, 0))
    slot_grain_minutes: Mapped[int] = mapped_column(Integer, default=30)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=15)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Denver")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="scheduling_settings")
