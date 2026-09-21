from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PaymentClassification(StrEnum):
    PAID = "PAID"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    ZERO_PAYMENT = "ZERO_PAYMENT"
    UNDERPAYMENT = "UNDERPAYMENT"
    OVERPAYMENT = "OVERPAYMENT"
    NO_PAYMENT_RECORDED = "NO_PAYMENT_RECORDED"
    PAYMENT_DATA_INCOMPLETE = "PAYMENT_DATA_INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class AdjustmentClassification(StrEnum):
    NO_ADJUSTMENT = "NO_ADJUSTMENT"
    CONTRACTUAL_ADJUSTMENT = "CONTRACTUAL_ADJUSTMENT"
    PATIENT_RESPONSIBILITY = "PATIENT_RESPONSIBILITY"
    UNRECONCILED_AMOUNT = "UNRECONCILED_AMOUNT"
    MISSING_ADJUSTMENT_DATA = "MISSING_ADJUSTMENT_DATA"
    UNKNOWN = "UNKNOWN"


class PaymentStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"


class PaymentSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PaymentEvidence(BaseModel):
    source: str
    field: str | None = None
    value: Any = None
    description: str


class PaymentIssue(BaseModel):
    rule: str
    severity: PaymentSeverity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PaymentExplanation(BaseModel):
    root_cause: str
    explanation: str
    recommendations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class PaymentAgentResult(BaseModel):
    claim_id: str | None = None
    payment_id: str | None = None
    billed_amount: Decimal | None = None
    allowed_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    adjustment_amount: Decimal | None = None
    patient_responsibility: Decimal | None = None
    unpaid_balance: Decimal | None = None
    payment_ratio: Decimal | None = None
    payment_classification: PaymentClassification
    adjustment_classification: AdjustmentClassification
    payment_status: PaymentStatus
    risk_score: int = Field(ge=0, le=100)
    evidence: list[PaymentEvidence] = Field(default_factory=list)
    issues: list[PaymentIssue] = Field(default_factory=list)
    root_cause: str
    recommendations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    requires_human_review: bool
    policy_status: str = "UNKNOWN"
    source: str = "synthetic_demo"
