from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.denial import DenialCategory


class AppealStatus(StrEnum):
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    NOT_READY = "NOT_READY"
    REVIEW = "REVIEW"


class AppealReadiness(StrEnum):
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    NOT_READY = "NOT_READY"
    REVIEW = "REVIEW"


class AppealPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AppealSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AppealEvidence(BaseModel):
    evidence_type: str
    source: str
    description: str
    claim_id: str | None = None
    reliability: str = "deterministic"
    details: dict[str, Any] = Field(default_factory=dict)


class AppealMissingInformation(BaseModel):
    item: str
    reason: str
    required_for: str
    source_check: str
    severity: AppealSeverity


class AppealExplanation(BaseModel):
    summary: str
    explanation: str
    recommended_next_step: str
    missing_information: list[str] = Field(default_factory=list)


class AppealResult(BaseModel):
    claim_id: str | None = None
    denial_id: str | None = None
    status: AppealStatus
    appeal_readiness: AppealReadiness
    denial_category: DenialCategory
    evidence: list[AppealEvidence] = Field(default_factory=list)
    missing_information: list[AppealMissingInformation] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    draft: str
    human_review_required: bool = True
    risk_score: int = Field(ge=0, le=100)
    priority: AppealPriority
    warnings: list[str] = Field(default_factory=list)
    audit_reference: str | None = None
    llm_explanation: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "synthetic_demo"
