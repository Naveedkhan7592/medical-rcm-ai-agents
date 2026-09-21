from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DenialStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class DenialCategory(StrEnum):
    ELIGIBILITY = "ELIGIBILITY"
    AUTHORIZATION = "AUTHORIZATION"
    CODING = "CODING"
    MEDICAL_NECESSITY = "MEDICAL_NECESSITY"
    DUPLICATE = "DUPLICATE"
    TIMELY_FILING = "TIMELY_FILING"
    MISSING_DOCUMENTATION = "MISSING_DOCUMENTATION"
    COORDINATION_OF_BENEFITS = "COORDINATION_OF_BENEFITS"
    PAYER_PROCESSING = "PAYER_PROCESSING"
    UNKNOWN = "UNKNOWN"


class DenialSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DenialEvidence(BaseModel):
    type: str
    source: str
    finding: str
    details: dict[str, Any] = Field(default_factory=dict)


class DenialIssue(BaseModel):
    rule: str
    severity: DenialSeverity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DenialClassification(BaseModel):
    category: DenialCategory
    status: DenialStatus
    evidence: list[DenialEvidence] = Field(default_factory=list)
    policy_status: str = "UNKNOWN"


class DenialRecommendation(BaseModel):
    recommendation: str
    requires_human_review: bool = True


class DenialExplanation(BaseModel):
    root_cause: str
    explanation: str
    recommendations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class DenialAgentResult(BaseModel):
    claim_id: str | None = None
    denial_id: str | None = None
    denial_category: DenialCategory
    carc_code: str | None = None
    rarc_code: str | None = None
    denial_reason: str | None = None
    denied_amount: float | None = None
    evidence: list[DenialEvidence] = Field(default_factory=list)
    issues: list[DenialIssue] = Field(default_factory=list)
    root_cause: str
    recommendations: list[str] = Field(default_factory=list)
    status: DenialStatus
    risk_score: int = Field(ge=0, le=100)
    requires_human_review: bool
    source: str = "synthetic_demo"
    policy_status: str = "UNKNOWN"
    missing_information: list[str] = Field(default_factory=list)
