from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class BusinessGoals(Base):
    __tablename__ = "business_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    monthly_revenue_goal: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    yearly_revenue_goal: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="business_goals")
