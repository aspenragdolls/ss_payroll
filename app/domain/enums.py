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
    TIER_3 = "tier_3"

    @property
    def weight(self) -> Decimal:
        return {
            Tier.TIER_1: Decimal("1.00"),
            Tier.TIER_2: Decimal("0.825"),
            Tier.TIER_3: Decimal("0.65"),
        }[self]

    @property
    def label(self) -> str:
        return {
            Tier.TIER_1: "Full contractor",
            Tier.TIER_2: "Supplemental contractor",
            Tier.TIER_3: "Supplied skilled worker",
        }[self]


class PayrollStatus(str, Enum):
    DRAFT = "draft"
    REVIEW = "review"
    FINALIZED = "finalized"


class JobReviewStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
