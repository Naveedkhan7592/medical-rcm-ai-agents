from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CodingStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class CodingSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CodingIssueCategory(StrEnum):
    MISSING_CODE = "MISSING_CODE"
    INVALID_FORMAT = "INVALID_FORMAT"
    UNKNOWN_CODE = "UNKNOWN_CODE"
    DUPLICATE_CODE = "DUPLICATE_CODE"
    INVALID_MODIFIER = "INVALID_MODIFIER"
    UNSUPPORTED_MODIFIER = "UNSUPPORTED_MODIFIER"
    CODING_POLICY_ISSUE = "CODING_POLICY_ISSUE"


class CodingIssue(BaseModel):
    rule: str
    category: CodingIssueCategory
    severity: CodingSeverity
    message: str
    code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CodingCheckResult(BaseModel):
    code_type: str
    checked: bool
    passed: bool
    normalized_codes: list[str] = Field(default_factory=list)
    issues: list[CodingIssue] = Field(default_factory=list)


class CodingValidationResult(BaseModel):
    icd_results: CodingCheckResult
    cpt_results: CodingCheckResult
    modifier_results: CodingCheckResult
    status: CodingStatus
    risk_score: int = Field(ge=0, le=100)
    issues: list[CodingIssue] = Field(default_factory=list)
    source: str = "synthetic_demo"


class CodingExplanation(BaseModel):
    explanation: str
    recommendations: list[str] = Field(default_factory=list)


class CodingAgentResult(BaseModel):
    claim_id: str | None = None
    icd_results: CodingCheckResult
    cpt_results: CodingCheckResult
    modifier_results: CodingCheckResult
    status: CodingStatus
    risk_score: int = Field(ge=0, le=100)
    issues: list[CodingIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    explanation: str
    requires_human_review: bool
    source: str = "synthetic_demo"
