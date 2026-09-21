from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from app.schemas import (
    EligibilityAgentResult,
    EligibilityCheckResult,
    EligibilityExplanation,
    EligibilityIssue,
    EligibilityState,
    EligibilityStatus,
)
from app.services.llm_service import LLMService, LLMServiceError
from app.tools.eligibility_tool import EligibilityTool


ClaimLike = Mapping[str, Any] | Any
PatientLike = Mapping[str, Any] | Any
Lookup = Callable[[str], Any | None]
AuditSink = Callable[[str, dict[str, Any]], None]


def _value(item: ClaimLike | PatientLike, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class EligibilityAgent:
    """Coordinates synthetic eligibility lookup and deterministic checks."""

    def __init__(
        self,
        *,
        eligibility_tool: EligibilityTool | None = None,
        llm_service: LLMService | None = None,
        patient_lookup: Lookup | None = None,
        claim_lookup: Lookup | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.eligibility_tool = eligibility_tool or EligibilityTool()
        self.llm_service = llm_service
        self.patient_lookup = patient_lookup
        self.claim_lookup = claim_lookup
        self.audit_sink = audit_sink

    def process_claim(self, claim: ClaimLike, patient: PatientLike | None = None) -> EligibilityAgentResult:
        claim_id = _value(claim, "claim_id")
        patient_id = _value(claim, "patient_id")
        self._audit("eligibility_check_started", claim_id, "started")

        if patient is None:
            patient = self._patient_from_claim(claim)
        if patient is None and patient_id and self.patient_lookup:
            patient = self.patient_lookup(patient_id)

        if patient is None:
            issue = EligibilityIssue(
                rule="patient_exists",
                severity="HIGH",
                message="Patient could not be found for eligibility verification",
                details={"patient_id": patient_id},
            )
            self._audit("eligibility_result_generated", claim_id, "fail")
            return self._result(claim, None, EligibilityState.UNKNOWN, [issue], "FAIL", False)

        patient_payer = _value(patient, "payer")
        member_id = _value(patient, "member_id")
        claim_payer = _value(claim, "payer")
        self._audit("eligibility_tool_called", claim_id, "started")
        check = self.eligibility_tool.check_eligibility(patient_id, patient_payer, member_id)
        self._audit("eligibility_tool_called", claim_id, "completed")
        issues = self._evaluate(claim, patient, check)
        status = self._status(issues, check)
        self._audit("eligibility_rules_evaluated", claim_id, status)

        explanation, recommendation = self._explain(claim, check, issues, status)
        self._audit("eligibility_result_generated", claim_id, status)
        return EligibilityAgentResult(
            claim_id=claim_id,
            patient_id=patient_id,
            payer=claim_payer or patient_payer,
            member_id=member_id,
            eligibility_status=status,
            eligibility_state=check.eligibility_state,
            issues=issues,
            recommendation=recommendation,
            explanation=explanation,
            requires_human_review=status != EligibilityStatus.PASS,
            source=check.source,
        )

    def process_claim_id(self, claim_id: str) -> EligibilityAgentResult:
        if self.claim_lookup is None:
            raise ValueError("claim_lookup is required when processing a claim ID")
        claim = self.claim_lookup(claim_id)
        if claim is None:
            raise LookupError("claim not found")
        return self.process_claim(claim)

    def _patient_from_claim(self, claim: ClaimLike) -> PatientLike | None:
        patient = _value(claim, "patient")
        return patient if patient is not None else None

    def _evaluate(
        self,
        claim: ClaimLike,
        patient: PatientLike,
        check: EligibilityCheckResult,
    ) -> list[EligibilityIssue]:
        issues: list[EligibilityIssue] = []
        claim_payer = _value(claim, "payer")
        patient_payer = _value(patient, "payer")
        if not claim_payer:
            issues.append(EligibilityIssue(rule="payer_exists", severity="MEDIUM", message="Claim payer is missing"))
        if not patient_payer:
            issues.append(EligibilityIssue(rule="payer_exists", severity="MEDIUM", message="Patient payer is missing"))
        if not _value(patient, "member_id"):
            issues.append(EligibilityIssue(rule="member_id_exists", severity="MEDIUM", message="Patient member ID is missing"))
        if claim_payer and patient_payer and claim_payer != patient_payer:
            issues.append(EligibilityIssue(rule="payer_mismatch", severity="MEDIUM", message="Claim payer differs from patient payer", details={"claim_payer": claim_payer, "patient_payer": patient_payer}))
        if check.eligibility_state == EligibilityState.UNKNOWN:
            issues.append(EligibilityIssue(rule="eligibility_known", severity="MEDIUM", message="Eligibility information is unavailable from the synthetic tool"))
        elif check.eligibility_state == EligibilityState.INELIGIBLE:
            issues.append(EligibilityIssue(rule="eligibility_status", severity="HIGH", message="Synthetic eligibility result is ineligible"))

        service_date = _as_date(_value(claim, "service_date"))
        if check.coverage_start is None or check.coverage_end is None:
            issues.append(EligibilityIssue(rule="coverage_dates", severity="MEDIUM", message="Coverage dates are unavailable; coverage cannot be assumed"))
        elif service_date is None:
            issues.append(EligibilityIssue(rule="service_date", severity="HIGH", message="Claim service date is missing or invalid"))
        elif not check.coverage_start <= service_date <= check.coverage_end:
            issues.append(EligibilityIssue(rule="coverage_dates", severity="HIGH", message="Service date falls outside recorded synthetic coverage dates", details={"service_date": service_date.isoformat(), "coverage_start": check.coverage_start.isoformat(), "coverage_end": check.coverage_end.isoformat()}))
        return issues

    @staticmethod
    def _status(issues: list[EligibilityIssue], check: EligibilityCheckResult) -> EligibilityStatus:
        if any(issue.rule == "patient_exists" for issue in issues):
            return EligibilityStatus.FAIL
        if any(issue.rule == "coverage_dates" and issue.severity == "HIGH" for issue in issues):
            return EligibilityStatus.FAIL
        if check.eligibility_state == EligibilityState.INELIGIBLE:
            return EligibilityStatus.REVIEW
        return EligibilityStatus.REVIEW if issues else EligibilityStatus.PASS

    def _explain(
        self,
        claim: ClaimLike,
        check: EligibilityCheckResult,
        issues: list[EligibilityIssue],
        status: EligibilityStatus,
    ) -> tuple[str, str]:
        if not issues:
            return "Synthetic eligibility and coverage checks passed.", "Proceed with the next deterministic claim checks."
        if self.llm_service is not None:
            self._audit("eligibility_llm_reasoning", _value(claim, "claim_id"), "started")
            prompt = self._reasoning_prompt(claim, check, issues, status)
            try:
                response = self.llm_service.generate_structured(
                    system_instructions="Explain only the supplied synthetic eligibility facts. Do not invent coverage, benefits, payer responses, or member status.",
                    user_prompt=prompt,
                    response_model=EligibilityExplanation,
                )
                self._audit("eligibility_llm_reasoning", _value(claim, "claim_id"), "completed")
                return response.response.explanation, response.response.recommendation
            except LLMServiceError:
                self._audit("eligibility_llm_reasoning", _value(claim, "claim_id"), "failed")
        return self._fallback_explanation(issues)

    @staticmethod
    def _reasoning_prompt(claim: ClaimLike, check: EligibilityCheckResult, issues: list[EligibilityIssue], status: EligibilityStatus) -> str:
        return f"Eligibility status: {check.eligibility_state.value}\nPayer: {_value(claim, 'payer')}\nService date: {_value(claim, 'service_date')}\nCoverage start: {check.coverage_start}\nCoverage end: {check.coverage_end}\nOverall status: {status.value}\nIssues: {[issue.message for issue in issues]}"

    @staticmethod
    def _fallback_explanation(issues: list[EligibilityIssue]) -> tuple[str, str]:
        return "; ".join(issue.message for issue in issues), "Verify the recorded eligibility information and payer details before claim submission."

    def _result(self, claim: ClaimLike, patient: PatientLike | None, state: EligibilityState, issues: list[EligibilityIssue], status: str, review: bool) -> EligibilityAgentResult:
        explanation, recommendation = self._fallback_explanation(issues)
        return EligibilityAgentResult(
            claim_id=_value(claim, "claim_id"),
            patient_id=_value(claim, "patient_id"),
            payer=_value(claim, "payer"),
            member_id=_value(patient, "member_id") if patient else None,
            eligibility_status=EligibilityStatus(status),
            eligibility_state=state,
            issues=issues,
            recommendation=recommendation,
            explanation=explanation,
            requires_human_review=review,
        )

    def _audit(self, action: str, claim_id: str | None, status: str) -> None:
        if self.audit_sink:
            self.audit_sink(action, {"claim_id": claim_id, "status": status, "source": "synthetic_demo"})
