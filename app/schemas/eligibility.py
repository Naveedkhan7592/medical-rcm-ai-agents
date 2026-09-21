from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EligibilityState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


class EligibilityStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class EligibilityIssue(BaseModel):
    rule: str
    severity: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class EligibilityCheckResult(BaseModel):
    patient_id: str
    payer: str | None = None
    member_id: str | None = None
    eligible: bool | None = None
    eligibility_state: EligibilityState
    coverage_start: date | None = None
    coverage_end: date | None = None
    source: str


class EligibilityExplanation(BaseModel):
    explanation: str
    recommendation: str


class EligibilityAgentResult(BaseModel):
    claim_id: str | None = None
    patient_id: str | None = None
    payer: str | None = None
    member_id: str | None = None
    eligibility_status: EligibilityStatus
    eligibility_state: EligibilityState
    issues: list[EligibilityIssue] = Field(default_factory=list)
    recommendation: str
    explanation: str
    confidence: float | None = None
    requires_human_review: bool
    source: str = "synthetic_demo"
