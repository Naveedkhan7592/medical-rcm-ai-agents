from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.agents.eligibility_agent import EligibilityAgent
from app.schemas import (
    ClaimCheckSummary,
    ClaimExplanation,
    ClaimIssue,
    ClaimSeverity,
    ClaimsAgentResult,
    ClaimStatus,
    EligibilityAgentResult,
    EligibilityStatus,
)
from app.services.llm_service import LLMService, LLMServiceError
from app.services.rules_engine import RulesEngine


ClaimLike = Mapping[str, Any] | Any
Lookup = Callable[[str], Any | None]
AuditSink = Callable[[str, dict[str, Any]], None]


class ClaimsAgent:
    """Aggregate deterministic claim validation and eligibility findings."""

    def __init__(
        self,
        *,
        claim_lookup: Lookup | None = None,
        patient_lookup: Lookup | None = None,
        rules_engine: RulesEngine | Any | None = None,
        eligibility_agent: EligibilityAgent | Any | None = None,
        llm_service: LLMService | Any | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.claim_lookup = claim_lookup
        self.patient_lookup = patient_lookup
        self.rules_engine = rules_engine or RulesEngine()
        self.eligibility_agent = eligibility_agent or EligibilityAgent(
            llm_service=None,
            patient_lookup=patient_lookup,
            claim_lookup=claim_lookup,
            audit_sink=audit_sink,
        )
        self.llm_service = llm_service
        self.audit_sink = audit_sink

    def run(self, claim_id: str) -> ClaimsAgentResult:
        if self.claim_lookup is None:
            raise ValueError("claim_lookup is required when running by claim ID")
        claim = self.claim_lookup(claim_id)
        if claim is None:
            raise LookupError("claim not found")
        return self.validate_claim(claim)

    def validate_claim(self, claim: ClaimLike, patient: ClaimLike | None = None) -> ClaimsAgentResult:
        claim_id = self._value(claim, "claim_id")
        patient_id = self._value(claim, "patient_id")
        self._audit("claims_check_started", claim_id, "started")

        if patient is None:
            patient = self._value(claim, "patient")
        if patient is None and patient_id and self.patient_lookup:
            patient = self.patient_lookup(patient_id)
        self._audit("claim_loaded", claim_id, "found" if patient is not None else "patient_unavailable")

        validation = self.rules_engine.validate_claim(claim)
        self._audit("claim_rules_validated", claim_id, validation.overall_status)
        eligibility = self.eligibility_agent.process_claim(claim, patient)
        self._audit("claim_eligibility_checked", claim_id, eligibility.eligibility_status.value)

        issues = [
            ClaimIssue(
                rule=issue.rule,
                severity=ClaimSeverity(issue.severity),
                message=issue.message,
                details=issue.details,
            )
            for issue in validation.issues
        ]
        issues.extend(self._eligibility_issues(eligibility))
        status = self._aggregate_status(validation.overall_status, eligibility, issues)
        explanation, recommendations = self._explain(claim, validation, eligibility, issues, status)
        self._audit("claims_result_generated", claim_id, status.value)

        return ClaimsAgentResult(
            claim_id=claim_id,
            patient_id=patient_id,
            payer=self._value(claim, "payer"),
            status=status,
            risk_score=validation.risk_score,
            rules_checked=validation.rules_checked,
            check_summaries=[
                ClaimCheckSummary(
                    rule=rule,
                    passed=rule in validation.passed,
                    issue_count=sum(issue.rule == rule for issue in validation.issues),
                )
                for rule in validation.rules_checked
            ],
            issues=issues,
            eligibility_result=eligibility,
            recommendations=recommendations,
            explanation=explanation,
            requires_human_review=status != ClaimStatus.PASS,
        )

    @staticmethod
    def _value(item: ClaimLike | None, name: str, default: Any = None) -> Any:
        if item is None:
            return default
        if isinstance(item, Mapping):
            return item.get(name, default)
        return getattr(item, name, default)

    @staticmethod
    def _eligibility_issues(result: EligibilityAgentResult) -> list[ClaimIssue]:
        def value(issue: Any, name: str) -> Any:
            return issue.get(name) if isinstance(issue, Mapping) else getattr(issue, name)

        return [
            ClaimIssue(
                rule=f"eligibility.{value(issue, 'rule')}",
                severity=ClaimSeverity(value(issue, "severity")),
                message=value(issue, "message"),
                details=value(issue, "details") or {},
            )
            for issue in result.issues
        ]

    @staticmethod
    def _aggregate_status(
        rules_status: str,
        eligibility: EligibilityAgentResult,
        issues: list[ClaimIssue],
    ) -> ClaimStatus:
        if rules_status == "FAIL" or eligibility.eligibility_status == EligibilityStatus.FAIL:
            return ClaimStatus.FAIL
        if rules_status == "REVIEW" or eligibility.eligibility_status == EligibilityStatus.REVIEW:
            return ClaimStatus.REVIEW
        if any(issue.severity in {ClaimSeverity.HIGH, ClaimSeverity.CRITICAL} for issue in issues):
            return ClaimStatus.REVIEW
        return ClaimStatus.PASS

    def _explain(self, claim: ClaimLike, validation: Any, eligibility: EligibilityAgentResult, issues: list[ClaimIssue], status: ClaimStatus) -> tuple[str, list[str]]:
        if not issues:
            return "Deterministic claim and eligibility checks passed.", []
        recommendations = self._recommendations(issues)
        if self.llm_service is None:
            return "; ".join(issue.message for issue in issues), recommendations

        self._audit("claims_llm_reasoning", self._value(claim, "claim_id"), "started")
        try:
            response = self.llm_service.generate_structured(
                system_instructions="Summarize only the supplied deterministic claim findings. Do not override status or invent codes, policies, coverage, or clinical facts.",
                user_prompt=self._reasoning_prompt(claim, validation, eligibility, issues, status),
                response_model=ClaimExplanation,
            )
            self._audit("claims_llm_reasoning", self._value(claim, "claim_id"), "completed")
            return response.response.explanation, response.response.recommendations or recommendations
        except LLMServiceError:
            self._audit("claims_llm_reasoning", self._value(claim, "claim_id"), "failed")
            return "; ".join(issue.message for issue in issues), recommendations

    @staticmethod
    def _reasoning_prompt(claim: ClaimLike, validation: Any, eligibility: EligibilityAgentResult, issues: list[ClaimIssue], status: ClaimStatus) -> str:
        return (
            f"Claim ID: {ClaimsAgent._value(claim, 'claim_id')}\n"
            f"Rules status: {validation.overall_status}\n"
            f"Failed rules: {validation.failed}\n"
            f"Warnings: {validation.warnings}\n"
            f"Eligibility: {eligibility.eligibility_status.value}\n"
            f"Aggregated status: {status.value}\n"
            f"Issues: {[issue.message for issue in issues]}"
        )

    @staticmethod
    def _recommendations(issues: list[ClaimIssue]) -> list[str]:
        recommendations: list[str] = []
        messages = {issue.rule for issue in issues}
        if "cpt_codes" in messages:
            recommendations.append("Verify and add the appropriate CPT code before submission.")
        if any(issue.rule == "eligibility.payer_mismatch" for issue in issues):
            recommendations.append("Verify the patient's payer information against the claim.")
        if any(issue.rule.startswith("eligibility.") for issue in issues):
            recommendations.append("Verify active coverage and payer/member information before submission.")
        if "timely_filing" in messages:
            recommendations.append("Review timely filing requirements and determine whether an exception or correction is appropriate.")
        if not recommendations:
            recommendations.append("Resolve the documented deterministic issues before submission.")
        return recommendations

    def _audit(self, action: str, claim_id: str | None, status: str) -> None:
        if self.audit_sink:
            self.audit_sink(action, {"claim_id": claim_id, "status": status, "source": "synthetic_demo"})
