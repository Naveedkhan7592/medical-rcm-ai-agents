from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.denial import DenialCategory, DenialStatus
from app.schemas.payment import PaymentClassification


class ARBalanceState(StrEnum):
    CALCULATED = "CALCULATED"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class AgingBucket(StrEnum):
    CURRENT_0_30 = "CURRENT_0_30"
    DAYS_31_60 = "DAYS_31_60"
    DAYS_61_90 = "DAYS_61_90"
    DAYS_91_120 = "DAYS_91_120"
    DAYS_121_180 = "DAYS_121_180"
    DAYS_181_365 = "DAYS_181_365"
    DAYS_366_PLUS = "DAYS_366_PLUS"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class ARStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    NO_BALANCE = "NO_BALANCE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class ARPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class WorkQueueType(StrEnum):
    NO_ACTION = "NO_ACTION"
    MONITOR = "MONITOR"
    INVESTIGATE_PAYMENT = "INVESTIGATE_PAYMENT"
    INVESTIGATE_DENIAL = "INVESTIGATE_DENIAL"
    REVIEW_DOCUMENTATION = "REVIEW_DOCUMENTATION"
    REVIEW_ELIGIBILITY = "REVIEW_ELIGIBILITY"
    REVIEW_CODING = "REVIEW_CODING"
    REVIEW_CLAIM_HISTORY = "REVIEW_CLAIM_HISTORY"
    HUMAN_FINANCIAL_REVIEW = "HUMAN_FINANCIAL_REVIEW"
    UNKNOWN = "UNKNOWN"


class DenialContext(StrEnum):
    NO_DENIAL = "NO_DENIAL"
    DENIAL_PRESENT = "DENIAL_PRESENT"
    DENIAL_REQUIRES_REVIEW = "DENIAL_REQUIRES_REVIEW"
    UNKNOWN = "UNKNOWN"


class ARSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AREvidence(BaseModel):
    source: str
    field: str | None = None
    value: Any = None
    description: str


class ARIssue(BaseModel):
    rule: str
    severity: ARSeverity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ARExplanation(BaseModel):
    root_cause: str
    explanation: str
    recommendations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class ARAgentResult(BaseModel):
    claim_id: str | None = None
    billed_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    adjustment_amount: Decimal | None = None
    outstanding_balance: Decimal | None = None
    balance_state: ARBalanceState
    ar_age_days: int | None = None
    aging_bucket: AgingBucket
    ar_status: ARStatus
    status: str
    payment_classification: PaymentClassification | None = None
    denial_category: DenialCategory | None = None
    denial_status: DenialStatus | None = None
    denial_context: DenialContext
    priority: ARPriority
    priority_reasons: list[str] = Field(default_factory=list)
    recommended_work_type: WorkQueueType
    evidence: list[AREvidence] = Field(default_factory=list)
    issues: list[ARIssue] = Field(default_factory=list)
    root_cause: str
    recommendations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    risk_score: int = Field(ge=0, le=100)
    requires_human_review: bool
    policy_status: str = "UNKNOWN"
    source: str = "synthetic_demo"
