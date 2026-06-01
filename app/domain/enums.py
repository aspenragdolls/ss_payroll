from decimal import Decimal
from enum import Enum


class Role(str, Enum):
    LABOR = "labor"
    SALES = "sales"


class PayType(str, Enum):
    HOURLY = "hourly"
    PERCENTAGE = "percentage"


class Tier(str, Enum):
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"

    @property
    def weight(self) -> Decimal:
        return Decimal("1.5") if self == Tier.TIER_1 else Decimal("1.0")


class PayrollStatus(str, Enum):
    DRAFT = "draft"
    REVIEW = "review"
    FINALIZED = "finalized"


class JobReviewStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
