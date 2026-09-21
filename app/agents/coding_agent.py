from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.schemas import (
    CodingAgentResult,
    CodingExplanation,
    CodingIssue,
    CodingIssueCategory,
    CodingSeverity,
    CodingStatus,
)
from app.services.coding_validation import CodingValidationService
from app.services.llm_service import LLMService, LLMServiceError


ClaimLike = Mapping[str, Any] | Any
Lookup = Callable[[str], Any | None]
AuditSink = Callable[[str, dict[str, Any]], None]


class CodingAgent:
    """Orchestrate deterministic coding validation and safe explanation."""

    def __init__(
        self,
        *,
        claim_lookup: Lookup | None = None,
        patient_lookup: Lookup | None = None,
        coding_validation_service: CodingValidationService | Any | None = None,
        llm_service: LLMService | Any | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.claim_lookup = claim_lookup
        self.patient_lookup = patient_lookup
        self.coding_validation_service = coding_validation_service or CodingValidationService()
        self.llm_service = llm_service
        self.audit_sink = audit_sink

    def run(self, claim_id: str) -> CodingAgentResult:
        if self.claim_lookup is None:
            raise ValueError("claim_lookup is required when running by claim ID")
        claim = self.claim_lookup(claim_id)
        if claim is None:
            raise LookupError("claim not found")
        return self.validate_coding(claim)

    def validate_coding(self, claim: ClaimLike) -> CodingAgentResult:
        claim_id = self._value(claim, "claim_id")
        self._audit("coding_check_started", claim_id, "started")
        self._audit("coding_claim_loaded", claim_id, "found")
        validation = self.coding_validation_service.validate_claim_codes(claim)
        self._audit("icd_codes_validated", claim_id, validation.icd_results.status if hasattr(validation.icd_results, "status") else ("PASS" if validation.icd_results.passed else "ISSUE"))
        self._audit("cpt_codes_validated", claim_id, "PASS" if validation.cpt_results.passed else "ISSUE")
        self._audit("modifiers_validated", claim_id, "PASS" if validation.modifier_results.passed else "ISSUE")

        explanation, recommendations = self._explain(claim, validation.status, validation.issues)
        self._audit("coding_result_generated", claim_id, validation.status.value)
        return CodingAgentResult(
            claim_id=claim_id,
            icd_results=validation.icd_results,
            cpt_results=validation.cpt_results,
            modifier_results=validation.modifier_results,
            status=validation.status,
            risk_score=validation.risk_score,
            issues=validation.issues,
            recommendations=recommendations,
            explanation=explanation,
            requires_human_review=validation.status != CodingStatus.PASS,
            source=validation.source,
        )

    @staticmethod
    def _value(claim: ClaimLike, name: str, default: Any = None) -> Any:
        if isinstance(claim, Mapping):
            return claim.get(name, default)
        return getattr(claim, name, default)

    def _explain(self, claim: ClaimLike, status: CodingStatus, issues: list[CodingIssue]) -> tuple[str, list[str]]:
        if not issues:
            return "Deterministic coding reference and format checks passed.", []
        recommendations = self._recommendations(issues)
        if self.llm_service is None:
            return "; ".join(issue.message for issue in issues), recommendations
        self._audit("coding_llm_reasoning", self._value(claim, "claim_id"), "started")
        try:
            response = self.llm_service.generate_structured(
                system_instructions="Explain only the supplied deterministic coding findings. Do not invent, replace, or assign ICD, CPT, modifier, diagnosis, or clinical codes.",
                user_prompt=self._reasoning_prompt(claim, status, issues),
                response_model=CodingExplanation,
            )
            self._audit("coding_llm_reasoning", self._value(claim, "claim_id"), "completed")
            return response.response.explanation, response.response.recommendations or recommendations
        except LLMServiceError:
            self._audit("coding_llm_reasoning", self._value(claim, "claim_id"), "failed")
            return "; ".join(issue.message for issue in issues), recommendations

    @staticmethod
    def _reasoning_prompt(claim: ClaimLike, status: CodingStatus, issues: list[CodingIssue]) -> str:
        return (
            f"Claim ID: {CodingAgent._value(claim, 'claim_id')}\n"
            f"ICD validation: deterministic\n"
            f"CPT validation: deterministic\n"
            f"Modifier validation: deterministic\n"
            f"Coding status: {status.value}\n"
            f"Documented findings: {[issue.model_dump() for issue in issues]}"
        )

    @staticmethod
    def _recommendations(issues: list[CodingIssue]) -> list[str]:
        recommendations: list[str] = []
        categories = {issue.category for issue in issues}
        if CodingIssueCategory.MISSING_CODE in categories:
            recommendations.append("Provide the missing required code for qualified coding review before submission.")
        if CodingIssueCategory.INVALID_FORMAT in categories:
            recommendations.append("Have a qualified coding professional verify the code format before submission.")
        if CodingIssueCategory.UNKNOWN_CODE in categories:
            recommendations.append("Have a qualified coding professional verify the code against an authoritative reference.")
        if CodingIssueCategory.DUPLICATE_CODE in categories:
            recommendations.append("Review duplicate codes and confirm the intended coding before submission.")
        if CodingIssueCategory.UNSUPPORTED_MODIFIER in categories or CodingIssueCategory.INVALID_MODIFIER in categories:
            recommendations.append("Review modifiers against the configured payer and coding rules.")
        if CodingIssueCategory.CODING_POLICY_ISSUE in categories:
            recommendations.append("Review the configured synthetic payer coding rule before submission.")
        return recommendations or ["Resolve the documented deterministic coding findings before submission."]

    def _audit(self, action: str, claim_id: str | None, status: str) -> None:
        if self.audit_sink:
            self.audit_sink(action, {"claim_id": claim_id, "status": status, "source": "synthetic_demo"})
