from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SupervisorTaskType(StrEnum):
    CLAIM_REVIEW = "CLAIM_REVIEW"
    DENIAL_REVIEW = "DENIAL_REVIEW"
    PAYMENT_REVIEW = "PAYMENT_REVIEW"
    AR_REVIEW = "AR_REVIEW"
    BILLING_QA = "BILLING_QA"
    APPEAL_REVIEW = "APPEAL_REVIEW"
    FULL_RCM_REVIEW = "FULL_RCM_REVIEW"


class SupervisorStatus(StrEnum):
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING = "WAITING"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"


class SupervisorPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SupervisorTask(BaseModel):
    task_id: str
    claim_id: str
    task_type: SupervisorTaskType
    priority: SupervisorPriority = SupervisorPriority.MEDIUM
    input_data: dict[str, Any] = Field(default_factory=dict)
    requested_action: str | None = None


class SupervisorAgentSummary(BaseModel):
    agent_name: str
    status: str
    result_available: bool
    error: str | None = None


class SupervisorDecision(BaseModel):
    task_id: str
    claim_id: str
    status: SupervisorStatus
    current_stage: str
    next_action: str
    agents_required: list[str]
    completed_agents: list[str]
    pending_agents: list[str]
    failed_agents: list[str]
    human_review_required: bool
    priority: SupervisorPriority
    risk_score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    agent_results: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    audit_reference: str | None = None


class SupervisorResult(SupervisorDecision):
    workflow_stage: str
    next_action: str
    agent_execution_summary: list[SupervisorAgentSummary] = Field(default_factory=list)
    specialist_results: dict[str, Any] = Field(default_factory=dict)
    explanation: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
