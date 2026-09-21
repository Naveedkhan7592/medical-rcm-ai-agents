from enum import StrEnum
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class BillingQAStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"


class BillingQAPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class BillingQAIssueType(StrEnum):
    MISSING_AGENT_RESULT = "MISSING_AGENT_RESULT"
    CLAIM_ID_MISMATCH = "CLAIM_ID_MISMATCH"
    PATIENT_ID_MISMATCH = "PATIENT_ID_MISMATCH"
    PAYER_MISMATCH = "PAYER_MISMATCH"
    STATUS_CONFLICT = "STATUS_CONFLICT"
    ELIGIBILITY_CONFLICT = "ELIGIBILITY_CONFLICT"
    CODING_CONFLICT = "CODING_CONFLICT"
    DENIAL_CATEGORY_CONFLICT = "DENIAL_CATEGORY_CONFLICT"
    PAYMENT_CLASSIFICATION_CONFLICT = "PAYMENT_CLASSIFICATION_CONFLICT"
    PAYMENT_AMOUNT_CONFLICT = "PAYMENT_AMOUNT_CONFLICT"
    PAYMENT_BALANCE_CONFLICT = "PAYMENT_BALANCE_CONFLICT"
    AR_BALANCE_CONFLICT = "AR_BALANCE_CONFLICT"
    AR_AGING_BUCKET_CONFLICT = "AR_AGING_BUCKET_CONFLICT"
    AR_STATUS_CONFLICT = "AR_STATUS_CONFLICT"
    POLICY_EVIDENCE_CONFLICT = "POLICY_EVIDENCE_CONFLICT"
    HISTORY_CONFLICT = "HISTORY_CONFLICT"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"


class BillingQASeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class QACheckStatus(StrEnum):
    PASS = "PASS"
    CONFLICT = "CONFLICT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_RUN = "NOT_RUN"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


class BillingQAEvidence(BaseModel):
    source: str
    field: str | None = None
    value: Any = None
    description: str


class BillingQAIssue(BaseModel):
    issue_type: BillingQAIssueType
    severity: BillingQASeverity
    message: str
    source_agents: list[str] = Field(default_factory=list)
    evidence: list[BillingQAEvidence] = Field(default_factory=list)
    recommended_action: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class BillingQAConsistencyCheck(BaseModel):
    check: str
    status: QACheckStatus
    description: str
    evidence: list[BillingQAEvidence] = Field(default_factory=list)


class BillingQAExplanation(BaseModel):
    root_cause: str
    explanation: str
    recommendations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class BillingQAResult(BaseModel):
    claim_id: str | None = None
    qa_status: BillingQAStatus
    qa_priority: BillingQAPriority
    status: BillingQAStatus
    priority: BillingQAPriority
    risk_score: int = Field(ge=0, le=100)
    issues: list[BillingQAIssue] = Field(default_factory=list)
    evidence: list[BillingQAEvidence] = Field(default_factory=list)
    agent_results_checked: list[str] = Field(default_factory=list)
    consistency_checks: list[BillingQAConsistencyCheck] = Field(default_factory=list)
    checks_performed: list[str] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    agent_results_summary: dict[str, str] = Field(default_factory=dict)
    root_cause: str
    recommendations: list[str] = Field(default_factory=list)
    requires_human_review: bool
    human_review_required: bool
    llm_explanation: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "synthetic_demo"
