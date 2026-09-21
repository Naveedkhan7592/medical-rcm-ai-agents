from typing import Any, Literal

from pydantic import BaseModel, Field


Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
OverallStatus = Literal["PASS", "REVIEW", "FAIL"]


class RuleIssue(BaseModel):
    rule: str
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class RuleResult(BaseModel):
    rule: str
    passed: bool
    issues: list[RuleIssue] = Field(default_factory=list)


class ClaimValidationResult(BaseModel):
    claim_id: str | None = None
    overall_status: OverallStatus
    risk_score: int = Field(ge=0, le=100)
    rules_checked: list[str]
    passed: list[str]
    failed: list[str]
    warnings: list[str]
    issues: list[RuleIssue]
