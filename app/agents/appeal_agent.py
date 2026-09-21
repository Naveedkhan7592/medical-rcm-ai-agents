from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas import (
    AppealEvidence,
    AppealExplanation,
    AppealMissingInformation,
    AppealPriority,
    AppealReadiness,
    AppealResult,
    AppealSeverity,
    AppealStatus,
    BillingQAStatus,
    DenialCategory,
    DenialStatus,
)
from app.services.llm_service import LLMService, LLMServiceError


Lookup = Callable[[str], Any | None]
HistoryLookup = Callable[[str], Iterable[Any]]
AuditSink = Callable[[str, dict[str, Any]], None]
SCORES = {AppealSeverity.CRITICAL: 40, AppealSeverity.HIGH: 25, AppealSeverity.MEDIUM: 15, AppealSeverity.LOW: 5}


def _value(item: Mapping[str, Any] | Any | None, name: str, default: Any = None) -> Any:
    if item is None:
        return default
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


class AppealAgent:
    """Prepare deterministic, evidence-based appeal drafts for human review."""

    def __init__(
        self,
        *,
        claim_lookup: Lookup | None = None,
        denial_lookup: Lookup | None = None,
        patient_lookup: Lookup | None = None,
        claim_history_lookup: HistoryLookup | None = None,
        payer_policy_lookup: Lookup | None = None,
        rules_engine: Any | None = None,
        denial_agent: Any | None = None,
        coding_agent: Any | None = None,
        eligibility_agent: Any | None = None,
        payment_agent: Any | None = None,
        ar_agent: Any | None = None,
        billing_qa_agent: Any | None = None,
        llm_service: LLMService | Any | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.claim_lookup = claim_lookup
        self.denial_lookup = denial_lookup
        self.patient_lookup = patient_lookup
        self.claim_history_lookup = claim_history_lookup
        self.payer_policy_lookup = payer_policy_lookup
        self.rules_engine = rules_engine
        self.denial_agent = denial_agent
        self.coding_agent = coding_agent
        self.eligibility_agent = eligibility_agent
        self.payment_agent = payment_agent
        self.ar_agent = ar_agent
        self.billing_qa_agent = billing_qa_agent
        self.llm_service = llm_service
        self.audit_sink = audit_sink

    def run(self, claim_id: str) -> AppealResult:
        if self.claim_lookup is None:
            return self.prepare_appeal(None, claim_id=claim_id)
        claim = self.claim_lookup(claim_id)
        if claim is None:
            return self.prepare_appeal(None, claim_id=claim_id)
        return self.prepare_appeal(claim)

    def prepare_appeal(
        self,
        claim: Any | None,
        *,
        claim_id: str | None = None,
        denial: Any | None = None,
        denial_result: Any | None = None,
        billing_qa_result: Any | None = None,
        coding_result: Any | None = None,
        eligibility_result: Any | None = None,
        payment_result: Any | None = None,
        ar_result: Any | None = None,
        rules_result: Any | None = None,
        authorization_evidence: Any | None = None,
        documentation_evidence: Any | None = None,
    ) -> AppealResult:
        resolved_claim_id = claim_id or _value(claim, "claim_id")
        self._audit("appeal_check_started", resolved_claim_id, "started")
        if denial is None and self.denial_lookup and resolved_claim_id:
            denial = self.denial_lookup(resolved_claim_id)
            if isinstance(denial, (list, tuple)):
                denial = denial[-1] if denial else None
        if denial_result is None and denial is not None and self.denial_agent:
            denial_result = self.denial_agent.analyze_denial(denial)
        if billing_qa_result is None and claim is not None and self.billing_qa_agent:
            billing_qa_result = self.billing_qa_agent.run_qa(claim)
        if coding_result is None and claim is not None and self.coding_agent:
            coding_result = self.coding_agent.validate_coding(claim)
        if eligibility_result is None and claim is not None and self.eligibility_agent:
            eligibility_result = self.eligibility_agent.process_claim(claim)
        if payment_result is None and claim is not None and self.payment_agent and self.payment_agent.payment_lookup:
            payment = self.payment_agent.payment_lookup(resolved_claim_id)
            if isinstance(payment, (list, tuple)):
                payment = payment[-1] if payment else None
            if payment is not None:
                payment_result = self.payment_agent.analyze_payment(payment)
        if ar_result is None and claim is not None and self.ar_agent:
            ar_result = self.ar_agent.analyze_ar(claim)
        if rules_result is None and claim is not None and self.rules_engine:
            rules_result = self.rules_engine.validate_claim(claim)

        self._audit("appeal_claim_loaded", resolved_claim_id, "found" if claim else "missing")
        self._audit("appeal_denial_loaded", resolved_claim_id, "found" if denial else "missing")
        evidence = self._collect_evidence(claim, denial, denial_result, coding_result, eligibility_result, payment_result, ar_result, billing_qa_result, rules_result)
        self._audit("appeal_evidence_collected", resolved_claim_id, str(len(evidence)))
        policy = self._policy(_value(claim, "payer"))
        self._audit("appeal_policy_checked", resolved_claim_id, "FOUND" if policy else "UNKNOWN")

        missing: list[AppealMissingInformation] = []
        warnings: list[str] = []
        category = self._category(denial_result, denial)
        if claim is None:
            missing.append(self._missing("claim", "Claim record was not found", "appeal_identity", "claim_lookup", AppealSeverity.CRITICAL))
        if denial is None:
            missing.append(self._missing("denial record", "No denial record was found", "appeal_basis", "denial_lookup", AppealSeverity.CRITICAL))
        if category == DenialCategory.UNKNOWN:
            missing.append(self._missing("known denial category", "Denial category is unknown or unsupported", "appeal_basis", "denial_agent", AppealSeverity.HIGH))
        if policy is None:
            missing.append(self._missing("payer policy", "Synthetic payer policy is unavailable", "policy_lookup", "payer_policy", AppealSeverity.MEDIUM))
        if billing_qa_result is None:
            missing.append(self._missing("Billing QA result", "Cross-agent QA evidence is unavailable", "qa_gate", "billing_qa_agent", AppealSeverity.HIGH))
        elif _value(billing_qa_result, "qa_status", _value(billing_qa_result, "status")) != BillingQAStatus.PASS:
            warnings.append("Billing QA requires review; unresolved QA findings remain visible.")
            missing.append(self._missing("Billing QA conflicts", "Billing QA did not pass", "qa_gate", "billing_qa_agent", AppealSeverity.HIGH))

        self._category_checks(category, denial, denial_result, policy, coding_result, eligibility_result, authorization_evidence, documentation_evidence, missing)
        if category == DenialCategory.MEDICAL_NECESSITY:
            warnings.append("Medical necessity is high risk and requires qualified human review.")
        status = self._status(claim, denial, category, policy, billing_qa_result, missing, warnings)
        self._audit("appeal_readiness_evaluated", resolved_claim_id, status.value)
        self._audit("appeal_missing_information_identified", resolved_claim_id, str(len(missing)))
        draft = self._draft(claim, denial, category, evidence, missing)
        self._audit("appeal_draft_generated", resolved_claim_id, status.value)
        llm_explanation = self._llm_explanation(claim, category, status, evidence, missing, resolved_claim_id)
        risk = min(sum(SCORES[item.severity] for item in missing), 100)
        priority = self._priority(missing)
        self._audit("appeal_result_generated", resolved_claim_id, status.value)
        return AppealResult(
            claim_id=resolved_claim_id,
            denial_id=_value(denial, "denial_id"),
            status=status,
            appeal_readiness=AppealReadiness(status.value),
            denial_category=category,
            evidence=evidence,
            missing_information=missing,
            recommended_actions=self._actions(category, missing),
            draft=draft,
            human_review_required=True,
            risk_score=risk,
            priority=priority,
            warnings=warnings,
            audit_reference=f"appeal:{resolved_claim_id or 'unknown'}",
            llm_explanation=llm_explanation,
        )

    def _category(self, denial_result: Any, denial: Any) -> DenialCategory:
        raw = _value(denial_result, "denial_category") or _value(denial, "denial_category")
        if isinstance(raw, DenialCategory):
            return raw
        try:
            return DenialCategory(raw) if raw else DenialCategory.UNKNOWN
        except ValueError:
            return DenialCategory.UNKNOWN

    def _policy(self, payer: str | None) -> Any:
        return self.payer_policy_lookup(payer) if self.payer_policy_lookup and payer else None

    @staticmethod
    def _missing(item: str, reason: str, required_for: str, source_check: str, severity: AppealSeverity) -> AppealMissingInformation:
        return AppealMissingInformation(item=item, reason=reason, required_for=required_for, source_check=source_check, severity=severity)

    def _category_checks(self, category: DenialCategory, denial: Any, denial_result: Any, policy: Any, coding: Any, eligibility: Any, authorization: Any, documentation: Any, missing: list[AppealMissingInformation]) -> None:
        if category == DenialCategory.AUTHORIZATION and not authorization:
            missing.append(self._missing("authorization evidence", "No authorization evidence was provided", "authorization appeal support", "authorization_check", AppealSeverity.HIGH))
        if category == DenialCategory.CODING and coding is None:
            missing.append(self._missing("coding validation result", "Coding evidence is unavailable", "coding appeal support", "coding_agent", AppealSeverity.HIGH))
        if category == DenialCategory.ELIGIBILITY and eligibility is None:
            missing.append(self._missing("eligibility result", "Eligibility evidence is unavailable", "eligibility appeal support", "eligibility_agent", AppealSeverity.HIGH))
        if category == DenialCategory.MISSING_DOCUMENTATION and not documentation:
            missing.append(self._missing("supporting documentation", "No documentation evidence was provided", "documentation appeal support", "documentation_check", AppealSeverity.HIGH))
        if category == DenialCategory.TIMELY_FILING and (not policy or "timely_filing_days" not in policy):
            missing.append(self._missing("timely filing policy", "Synthetic filing limit is unavailable", "timely-filing appeal support", "payer_policy", AppealSeverity.MEDIUM))

    @staticmethod
    def _status(claim: Any, denial: Any, category: DenialCategory, policy: Any, qa: Any, missing: list[AppealMissingInformation], warnings: list[str]) -> AppealStatus:
        if claim is None or denial is None:
            return AppealStatus.NOT_READY
        if category == DenialCategory.UNKNOWN:
            return AppealStatus.REVIEW
        if policy is None:
            return AppealStatus.REVIEW
        if qa is not None and _value(qa, "qa_status", _value(qa, "status")) != BillingQAStatus.PASS:
            return AppealStatus.REVIEW
        not_ready_requirements = {"appeal_identity", "appeal_basis", "authorization appeal support", "coding appeal support", "eligibility appeal support", "documentation appeal support", "timely-filing appeal support"}
        if any(item.required_for in not_ready_requirements for item in missing):
            return AppealStatus.NOT_READY
        if category == DenialCategory.MEDICAL_NECESSITY or warnings:
            return AppealStatus.REVIEW
        return AppealStatus.READY_FOR_REVIEW

    def _collect_evidence(self, claim: Any, denial: Any, denial_result: Any, coding: Any, eligibility: Any, payment: Any, ar: Any, qa: Any, rules: Any) -> list[AppealEvidence]:
        evidence: list[AppealEvidence] = []
        if claim is not None:
            evidence.append(AppealEvidence(evidence_type="claim", source="claim", claim_id=_value(claim, "claim_id"), description="Synthetic claim record.", details={key: _value(claim, key) for key in ("payer", "service_date", "icd_codes", "cpt_codes", "modifiers", "claim_amount", "status")}))
        if denial is not None:
            evidence.append(AppealEvidence(evidence_type="denial", source="denial", claim_id=_value(denial, "claim_id"), description="Synthetic denial record.", details={key: _value(denial, key) for key in ("denial_id", "carc_code", "rarc_code", "reason", "denied_amount", "status")}))
        for name, result in (("denial_agent", denial_result), ("coding_agent", coding), ("eligibility_agent", eligibility), ("payment_agent", payment), ("ar_agent", ar), ("billing_qa_agent", qa), ("rules_engine", rules)):
            if result is not None:
                evidence.append(AppealEvidence(evidence_type=name, source=name, claim_id=_value(result, "claim_id"), description=f"Deterministic {name} result.", details=self._safe_result_details(name, result)))
        return evidence

    @staticmethod
    def _safe_result_details(name: str, result: Any) -> dict[str, Any]:
        fields = {"denial_category", "status", "eligibility_status", "payment_classification", "paid_amount", "adjustment_amount", "unpaid_balance", "outstanding_balance", "aging_bucket", "qa_status", "risk_score"}
        return {field: _value(result, field) for field in fields if _value(result, field) is not None}

    @staticmethod
    def _draft(claim: Any, denial: Any, category: DenialCategory, evidence: list[AppealEvidence], missing: list[AppealMissingInformation]) -> str:
        claim_id = _value(claim, "claim_id") or "UNKNOWN"
        lines = [f"Subject: Appeal Request - Claim {claim_id}", "", "Claim Information:", f"- Claim ID: {claim_id}", f"- Payer: {_value(claim, 'payer')}", f"- Service Date: {_value(claim, 'service_date')}", f"- Denial ID: {_value(denial, 'denial_id')}", "", "Denial:", f"- Category: {category.value}", f"- Reason: {_value(denial, 'reason')}", "", "Supporting Evidence:"]
        lines.extend(f"- {item.source}: {item.description}" for item in evidence)
        lines.extend(["", "Requested Review:", "- Please review the documented evidence and denial record.", "", "Attachments / Missing Information:"])
        lines.extend(f"- {item.item}: {item.reason}" for item in missing) or lines.append("- None identified by deterministic checks.")
        lines.extend(["", "Human Review:", "- Required before any external communication or submission."])
        return "\n".join(lines)

    @staticmethod
    def _actions(category: DenialCategory, missing: list[AppealMissingInformation]) -> list[str]:
        actions = ["Have a qualified human reviewer verify the deterministic evidence before submission."]
        if missing:
            actions.append("Obtain and validate the listed missing information before treating the draft as supported.")
        if category == DenialCategory.MEDICAL_NECESSITY:
            actions.append("Obtain qualified clinical review; do not infer or add medical facts automatically.")
        return actions

    def _llm_explanation(self, claim: Any, category: DenialCategory, status: AppealStatus, evidence: list[AppealEvidence], missing: list[AppealMissingInformation], claim_id: str | None) -> str | None:
        if self.llm_service is None:
            return None
        self._audit("appeal_llm_reasoning", claim_id, "started")
        try:
            response = self.llm_service.generate_structured(system_instructions="Explain only the supplied deterministic appeal evidence. Do not change readiness, denial category, financial values, policy, or invent authorization, documentation, or medical facts.", user_prompt=f"Status: {status.value}\nDenial category: {category.value}\nEvidence: {[item.model_dump() for item in evidence]}\nMissing: {[item.model_dump() for item in missing]}", response_model=AppealExplanation)
            self._audit("appeal_llm_reasoning", claim_id, "completed")
            return response.response.explanation
        except LLMServiceError:
            self._audit("appeal_llm_reasoning", claim_id, "failed")
            return None

    @staticmethod
    def _priority(missing: list[AppealMissingInformation]) -> AppealPriority:
        highest = max((SCORES[item.severity] for item in missing), default=5)
        return AppealPriority.CRITICAL if highest == 40 else AppealPriority.HIGH if highest == 25 else AppealPriority.MEDIUM if highest == 15 else AppealPriority.LOW

    def _audit(self, action: str, claim_id: str | None, status: str) -> None:
        if self.audit_sink:
            self.audit_sink(action, {"claim_id": claim_id, "status": status, "source": "synthetic_demo"})
