from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.eligibility import EligibilityAgentResult


class ClaimStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class ClaimSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ClaimIssue(BaseModel):
    rule: str
    severity: ClaimSeverity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ClaimCheckSummary(BaseModel):
    rule: str
    passed: bool
    issue_count: int = 0


class ClaimExplanation(BaseModel):
    explanation: str
    recommendations: list[str] = Field(default_factory=list)


class ClaimsAgentResult(BaseModel):
    claim_id: str | None = None
    patient_id: str | None = None
    payer: str | None = None
    status: ClaimStatus
    risk_score: int = Field(ge=0, le=100)
    rules_checked: list[str] = Field(default_factory=list)
    check_summaries: list[ClaimCheckSummary] = Field(default_factory=list)
    issues: list[ClaimIssue] = Field(default_factory=list)
    eligibility_result: EligibilityAgentResult | None = None
    recommendations: list[str] = Field(default_factory=list)
    explanation: str
    requires_human_review: bool
    source: str = "synthetic_demo"
