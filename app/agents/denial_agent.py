from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date
from typing import Any

from app.schemas import (
    DenialAgentResult,
    DenialCategory,
    DenialEvidence,
    DenialExplanation,
    DenialIssue,
    DenialSeverity,
    DenialStatus,
)
from app.services.denial_analysis import DenialAnalysisService, value
from app.services.llm_service import LLMService, LLMServiceError


Lookup = Callable[[str], Any | None]
HistoryLookup = Callable[[str], Iterable[Any]]
AuditSink = Callable[[str, dict[str, Any]], None]

REASON_CATEGORIES = {
    "eligibility": DenialCategory.ELIGIBILITY,
    "authorization": DenialCategory.AUTHORIZATION,
    "coding": DenialCategory.CODING,
    "medical necessity": DenialCategory.MEDICAL_NECESSITY,
    "duplicate": DenialCategory.DUPLICATE,
    "timely filing": DenialCategory.TIMELY_FILING,
    "missing documentation": DenialCategory.MISSING_DOCUMENTATION,
    "coordination of benefits": DenialCategory.COORDINATION_OF_BENEFITS,
    "payer processing": DenialCategory.PAYER_PROCESSING,
}
JUDGMENT_CATEGORIES = {DenialCategory.MEDICAL_NECESSITY, DenialCategory.PAYER_PROCESSING, DenialCategory.UNKNOWN}
SEVERITY_BY_CATEGORY = {
    DenialCategory.MEDICAL_NECESSITY: DenialSeverity.HIGH,
    DenialCategory.PAYER_PROCESSING: DenialSeverity.MEDIUM,
    DenialCategory.UNKNOWN: DenialSeverity.MEDIUM,
}


class DenialAgent:
    """Analyze synthetic denials using deterministic evidence and optional explanation."""

    def __init__(
        self,
        *,
        claim_lookup: Lookup | None = None,
        denial_lookup: Lookup | None = None,
        patient_lookup: Lookup | None = None,
        claim_history_lookup: HistoryLookup | None = None,
        payer_policy_lookup: Lookup | None = None,
        denial_analysis_service: DenialAnalysisService | Any | None = None,
        eligibility_agent: Any | None = None,
        coding_agent: Any | None = None,
        llm_service: LLMService | Any | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.claim_lookup = claim_lookup
        self.denial_lookup = denial_lookup
        self.patient_lookup = patient_lookup
        self.claim_history_lookup = claim_history_lookup
        self.payer_policy_lookup = payer_policy_lookup
        self.analysis_service = denial_analysis_service or DenialAnalysisService()
        self.eligibility_agent = eligibility_agent
        self.coding_agent = coding_agent
        self.llm_service = llm_service
        self.audit_sink = audit_sink

    def run(self, denial_id: str) -> DenialAgentResult:
        if self.denial_lookup is None:
            raise ValueError("denial_lookup is required when running by denial ID")
        denial = self.denial_lookup(denial_id)
        if denial is None:
            raise LookupError("denial not found")
        return self.analyze_denial(denial)

    def analyze_denial(self, denial: Any) -> DenialAgentResult:
        denial_id = value(denial, "denial_id")
        claim_id = value(denial, "claim_id")
        self._audit("denial_check_started", denial_id, "started")
        claim = self.claim_lookup(claim_id) if self.claim_lookup and claim_id else None
        self._audit("denial_loaded", denial_id, "found" if denial is not None else "missing")
        claim_history = list(self.claim_history_lookup(claim_id)) if self.claim_history_lookup and claim_id else []
        policy = self._policy_for_claim(claim)

        carc_code = value(denial, "carc_code")
        rarc_code = value(denial, "rarc_code")
        reason = str(value(denial, "reason") or "")
        code_category = self.analysis_service.classify_codes(carc_code, rarc_code)
        reason_category = self._classify_reason(reason)
        category = self._resolve_category(code_category, reason_category)
        self._audit("denial_codes_evaluated", denial_id, category.value)

        evidence = self._collect_evidence(denial, claim, claim_history, policy, category, code_category)
        evidence.extend(self._agent_evidence(claim, category))
        self._audit("denial_evidence_collected", denial_id, str(len(evidence)))
        policy_status = "FOUND" if policy else "UNKNOWN"
        self._audit("denial_policy_checked", denial_id, policy_status)
        issues = self._issues(category, code_category, reason_category, policy, claim)
        status = self._status(category, issues)
        self._audit("denial_root_cause_analyzed", denial_id, status.value)
        root_cause, recommendations, missing_information = self._explain(
            denial, category, status, evidence, issues
        )
        self._audit("denial_result_generated", denial_id, status.value)
        risk_score = min(sum(self._score(issue.severity) for issue in issues), 100)
        if not issues and category in JUDGMENT_CATEGORIES:
            risk_score = self._score(SEVERITY_BY_CATEGORY[category])
        return DenialAgentResult(
            claim_id=claim_id,
            denial_id=denial_id,
            denial_category=category,
            carc_code=carc_code,
            rarc_code=rarc_code,
            denial_reason=value(denial, "reason"),
            denied_amount=float(value(denial, "denied_amount")) if value(denial, "denied_amount") is not None else None,
            evidence=evidence,
            issues=issues,
            root_cause=root_cause,
            recommendations=recommendations,
            status=status,
            risk_score=risk_score,
            requires_human_review=status != DenialStatus.PASS or category in JUDGMENT_CATEGORIES,
            policy_status=policy_status,
            missing_information=missing_information,
        )

    def _agent_evidence(self, claim: Any, category: DenialCategory) -> list[DenialEvidence]:
        evidence: list[DenialEvidence] = []
        if category == DenialCategory.ELIGIBILITY and self.eligibility_agent and claim is not None:
            result = self.eligibility_agent.process_claim(claim)
            evidence.append(DenialEvidence(type="eligibility", source="eligibility_agent", finding=result.explanation, details={"status": result.eligibility_status.value}))
        if category == DenialCategory.CODING and self.coding_agent and claim is not None:
            result = self.coding_agent.validate_coding(claim)
            evidence.append(DenialEvidence(type="coding", source="coding_agent", finding=result.explanation, details={"status": result.status.value, "risk_score": result.risk_score}))
        return evidence

    def _policy_for_claim(self, claim: Any) -> dict[str, Any] | None:
        payer = value(claim, "payer")
        if self.payer_policy_lookup:
            return self.payer_policy_lookup(payer)
        return self.analysis_service.policy_for(payer)

    @staticmethod
    def _classify_reason(reason: str) -> DenialCategory | None:
        lowered = reason.lower()
        for phrase, category in REASON_CATEGORIES.items():
            if phrase in lowered:
                return category
        return None

    @staticmethod
    def _resolve_category(code_category: DenialCategory | None, reason_category: DenialCategory | None) -> DenialCategory:
        if code_category and reason_category and code_category != reason_category:
            return DenialCategory.UNKNOWN
        return code_category or reason_category or DenialCategory.UNKNOWN

    def _collect_evidence(
        self,
        denial: Any,
        claim: Any,
        history: list[Any],
        policy: dict[str, Any] | None,
        category: DenialCategory,
        code_category: DenialCategory | None,
    ) -> list[DenialEvidence]:
        evidence = [
            DenialEvidence(
                type="denial_record",
                source="synthetic_denial_data",
                finding=str(value(denial, "reason") or "Documented synthetic denial reason"),
                details={"carc_code": value(denial, "carc_code"), "rarc_code": value(denial, "rarc_code")},
            )
        ]
        if code_category is None:
            evidence.append(DenialEvidence(type="denial_code", source="synthetic_denial_code_reference", finding="CARC/RARC code is not mapped in the synthetic reference", details={"carc_code": value(denial, "carc_code"), "rarc_code": value(denial, "rarc_code")}))
        if policy is not None and category in {DenialCategory.AUTHORIZATION, DenialCategory.TIMELY_FILING, DenialCategory.MISSING_DOCUMENTATION, DenialCategory.PAYER_PROCESSING}:
            details = {key: policy[key] for key in ("authorization_required", "timely_filing_days", "documentation_required") if key in policy}
            evidence.append(DenialEvidence(type="payer_policy", source="synthetic_payer_policy", finding="Synthetic payer policy was available for deterministic review", details=details))
        if history:
            evidence.append(DenialEvidence(type="claim_history", source="synthetic_claim_history", finding=f"{len(history)} related synthetic claim history record(s) were provided", details={"record_count": len(history)}))
        if claim is not None:
            evidence.append(DenialEvidence(type="claim", source="synthetic_claim_data", finding="Related synthetic claim was found", details={"claim_id": value(claim, "claim_id"), "status": value(claim, "status")}))
        return evidence

    @staticmethod
    def _issues(category: DenialCategory, code_category: DenialCategory | None, reason_category: DenialCategory | None, policy: dict[str, Any] | None, claim: Any) -> list[DenialIssue]:
        issues: list[DenialIssue] = []
        if code_category is None:
            issues.append(DenialIssue(rule="denial_code_mapping", severity=DenialSeverity.MEDIUM, message="Denial code is not mapped in the synthetic reference"))
        if code_category and reason_category and code_category != reason_category:
            issues.append(DenialIssue(rule="conflicting_evidence", severity=DenialSeverity.HIGH, message="Denial code and documented reason indicate different categories"))
        if policy is None and category in {DenialCategory.AUTHORIZATION, DenialCategory.TIMELY_FILING, DenialCategory.MISSING_DOCUMENTATION}:
            issues.append(DenialIssue(rule="payer_policy", severity=DenialSeverity.MEDIUM, message="Payer policy is unavailable for deterministic denial analysis"))
        if claim is None:
            issues.append(DenialIssue(rule="claim_lookup", severity=DenialSeverity.MEDIUM, message="Related claim was not found"))
        return issues

    @staticmethod
    def _status(category: DenialCategory, issues: list[DenialIssue]) -> DenialStatus:
        if any(issue.rule == "claim_lookup" for issue in issues) and category == DenialCategory.UNKNOWN:
            return DenialStatus.REVIEW
        if any(issue.rule == "conflicting_evidence" for issue in issues):
            return DenialStatus.REVIEW
        if category in JUDGMENT_CATEGORIES or issues:
            return DenialStatus.REVIEW
        return DenialStatus.PASS

    def _explain(self, denial: Any, category: DenialCategory, status: DenialStatus, evidence: list[DenialEvidence], issues: list[DenialIssue]) -> tuple[str, list[str], list[str]]:
        fallback_recommendations = self._recommendations(category)
        missing = [issue.message for issue in issues if issue.rule in {"denial_code_mapping", "payer_policy", "claim_lookup"}]
        deterministic_root_cause = next((item.finding for item in evidence if item.type == "denial_record"), "Deterministic denial evidence requires review")
        if self.llm_service:
            self._audit("denial_llm_reasoning", value(denial, "denial_id"), "started")
            try:
                response = self.llm_service.generate_structured(
                    system_instructions="Explain only the supplied deterministic denial evidence. Do not invent code meanings, payer policies, eligibility, coding facts, medical facts, or appeal outcomes.",
                    user_prompt=self._reasoning_prompt(category, status, evidence, issues),
                    response_model=DenialExplanation,
                )
                self._audit("denial_llm_reasoning", value(denial, "denial_id"), "completed")
                return deterministic_root_cause, response.response.recommendations or fallback_recommendations, response.response.missing_information
            except LLMServiceError:
                self._audit("denial_llm_reasoning", value(denial, "denial_id"), "failed")
        return deterministic_root_cause, fallback_recommendations, missing

    @staticmethod
    def _reasoning_prompt(category: DenialCategory, status: DenialStatus, evidence: list[DenialEvidence], issues: list[DenialIssue]) -> str:
        return f"Denial category: {category.value}\nStatus: {status.value}\nEvidence: {[item.model_dump() for item in evidence]}\nIssues: {[item.model_dump() for item in issues]}"

    @staticmethod
    def _recommendations(category: DenialCategory) -> list[str]:
        return {
            DenialCategory.ELIGIBILITY: ["Verify active coverage and payer/member information."],
            DenialCategory.AUTHORIZATION: ["Verify whether required authorization documentation exists."],
            DenialCategory.CODING: ["Have a qualified coding professional review the identified coding issue."],
            DenialCategory.TIMELY_FILING: ["Review the filing timeline and determine whether an applicable exception or correction exists."],
            DenialCategory.MISSING_DOCUMENTATION: ["Identify and obtain the documentation required by the configured demo policy."],
            DenialCategory.UNKNOWN: ["Human review is required because the denial evidence is not mapped in the configured reference data."],
        }.get(category, ["Review the documented denial evidence with a qualified human reviewer."])

    @staticmethod
    def _score(severity: DenialSeverity) -> int:
        return {DenialSeverity.CRITICAL: 40, DenialSeverity.HIGH: 25, DenialSeverity.MEDIUM: 15, DenialSeverity.LOW: 5}[severity]

    def _audit(self, action: str, denial_id: str | None, status: str) -> None:
        if self.audit_sink:
            self.audit_sink(action, {"denial_id": denial_id, "status": status, "source": "synthetic_demo"})
