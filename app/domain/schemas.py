from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.domain.enums import PayType, Role, Tier


@dataclass
class CalcJob:
    job_id: str
    ticket_price: Decimal
    job_date: date
    tips: Decimal = Decimal("0")


@dataclass
class CalcAssignment:
    job_id: str
    worker_id: str
    roles: set[Role]
    pay_type: PayType | None = None
    tier: Tier | None = None
    hourly_rate: Decimal | None = None
    adjustment: Decimal = Decimal("0")


@dataclass
class CalcInput:
    jobs: list[CalcJob]
    assignments: list[CalcAssignment]
    daily_hours: dict[tuple[str, date], Decimal]
    owner_worker_id: str | None = None


@dataclass
class CalcJobWorkerResult:
    job_id: str
    worker_id: str
    ticket_price: Decimal
    labor_pool: Decimal
    hourly_component: Decimal
    percentage_component: Decimal
    commission_component: Decimal
    adjustment_component: Decimal
    tips_component: Decimal
    final_worker_job_pay: Decimal
    hours_assigned: Decimal = Decimal("0")


@dataclass
class CalcWorkerTotal:
    worker_id: str
    total_pay: Decimal
    labor_total: Decimal
    commission_total: Decimal
    hourly_total: Decimal
    percentage_total: Decimal
    tips_total: Decimal
    adjustment_total: Decimal


@dataclass
class CalcWarning:
    code: str
    message: str
    job_id: str | None = None
    worker_id: str | None = None


@dataclass
class CalcResult:
    job_results: list[CalcJobWorkerResult] = field(default_factory=list)
    worker_totals: list[CalcWorkerTotal] = field(default_factory=list)
    warnings: list[CalcWarning] = field(default_factory=list)
    calculation_snapshot: dict = field(default_factory=dict)
