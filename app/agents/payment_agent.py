from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any

from app.schemas import (
    AdjustmentClassification,
    PaymentAgentResult,
    PaymentClassification,
    PaymentEvidence,
    PaymentExplanation,
    PaymentIssue,
    PaymentSeverity,
    PaymentStatus,
)
from app.services.llm_service import LLMService, LLMServiceError


Lookup = Callable[[str], Any | None]
HistoryLookup = Callable[[str], Iterable[Any]]
AuditSink = Callable[[str, dict[str, Any]], None]

SCORES = {
    PaymentSeverity.CRITICAL: 40,
    PaymentSeverity.HIGH: 25,
    PaymentSeverity.MEDIUM: 15,
    PaymentSeverity.LOW: 5,
}


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


class PaymentAgent:
    """Analyze synthetic payment records without changing financial data."""

    def __init__(
        self,
        *,
        claim_lookup: Lookup | None = None,
        payment_lookup: Lookup | None = None,
        claim_history_lookup: HistoryLookup | None = None,
        payer_policy_lookup: Lookup | None = None,
        denial_lookup: Lookup | None = None,
        denial_agent: Any | None = None,
        rules_engine: Any | None = None,
        llm_service: LLMService | Any | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.claim_lookup = claim_lookup
        self.payment_lookup = payment_lookup
        self.claim_history_lookup = claim_history_lookup
        self.payer_policy_lookup = payer_policy_lookup or self._default_policy_lookup
        self.denial_lookup = denial_lookup
        self.denial_agent = denial_agent
        self.rules_engine = rules_engine
        self.llm_service = llm_service
        self.audit_sink = audit_sink

    def run(self, payment_id: str) -> PaymentAgentResult:
        if self.payment_lookup is None:
            raise ValueError("payment_lookup is required when running by payment ID")
        payment = self.payment_lookup(payment_id)
        if payment is None:
            return self.analyze_payment(None, payment_id=payment_id)
        return self.analyze_payment(payment)

    def analyze_payment(self, payment: Any | None, *, payment_id: str | None = None) -> PaymentAgentResult:
        resolved_payment_id = payment_id or _value(payment, "payment_id")
        claim_id = _value(payment, "claim_id")
        self._audit("payment_check_started", resolved_payment_id, "started")
        if payment is None:
            issue = PaymentIssue(
                rule="payment_record",
                severity=PaymentSeverity.MEDIUM,
                message="No payment record was found for the requested payment ID",
            )
            self._audit("payment_result_generated", resolved_payment_id, PaymentStatus.REVIEW.value)
            return PaymentAgentResult(
                payment_id=resolved_payment_id,
                payment_classification=PaymentClassification.NO_PAYMENT_RECORDED,
                adjustment_classification=AdjustmentClassification.UNKNOWN,
                payment_status=PaymentStatus.REVIEW,
                risk_score=SCORES[issue.severity],
                issues=[issue],
                evidence=[],
                root_cause=issue.message,
                recommendations=["Verify whether a payment record exists before taking financial action."],
                missing_information=["payment record"],
                requires_human_review=True,
            )

        claim = self.claim_lookup(claim_id) if self.claim_lookup and claim_id else None
        self._audit("payment_loaded", resolved_payment_id, "found")
        history = list(self.claim_history_lookup(claim_id)) if self.claim_history_lookup and claim_id else []
        policy = self._policy_for(payment, claim)
        self._audit("payment_history_checked", resolved_payment_id, str(len(history)))
        self._audit("payment_policy_checked", resolved_payment_id, "FOUND" if policy else "UNKNOWN")

        billed = _decimal(_value(claim, "claim_amount"))
        allowed = _decimal(_value(payment, "allowed_amount"))
        paid = _decimal(_value(payment, "paid_amount"))
        adjustment = _decimal(_value(payment, "adjustment_amount"))
        responsibility = _decimal(_value(payment, "patient_responsibility"))
        amounts = {"billed_amount": billed, "allowed_amount": allowed, "paid_amount": paid, "adjustment_amount": adjustment, "patient_responsibility": responsibility}
        self._audit("payment_amounts_calculated", resolved_payment_id, "complete")

        issues = self._financial_issues(amounts)
        unpaid = billed - paid - adjustment if billed is not None and paid is not None and adjustment is not None else None
        ratio = paid / allowed if paid is not None and allowed is not None and allowed > 0 else None
        if unpaid is not None and responsibility is not None and unpaid != responsibility:
            issues.append(PaymentIssue(rule="reconciliation", severity=PaymentSeverity.MEDIUM, message="Recorded payment components do not reconcile to patient responsibility", details={"unpaid_balance": str(unpaid), "patient_responsibility": str(responsibility)}))
        adjustment_classification = self._adjustment_classification(adjustment, responsibility, unpaid)
        classification = self._classify(paid, billed, unpaid, issues, policy)
        issues.extend(self._classification_issues(classification))
        self._audit("payment_reconciliation_completed", resolved_payment_id, "reconciled" if not any(issue.rule == "reconciliation" for issue in issues) else "unreconciled")

        evidence = self._evidence(payment, claim, history, policy, amounts, unpaid, ratio)
        denial_evidence = self._denial_evidence(claim_id)
        evidence.extend(denial_evidence)
        self._audit("payment_denial_evidence_collected", resolved_payment_id, str(len(denial_evidence)))
        rules_evidence = self._rules_evidence(claim)
        evidence.extend(rules_evidence)
        status = PaymentStatus.REVIEW if issues or classification not in {PaymentClassification.PAID} or not policy else PaymentStatus.PASS
        if any(issue.rule == "payment_data" for issue in issues):
            status = PaymentStatus.REVIEW
        self._audit("payment_root_cause_analyzed", resolved_payment_id, status.value)
        root_cause, recommendations, missing = self._explain(payment, classification, status, evidence, issues)
        self._audit("payment_result_generated", resolved_payment_id, status.value)
        return PaymentAgentResult(
            claim_id=claim_id,
            payment_id=resolved_payment_id,
            billed_amount=billed,
            allowed_amount=allowed,
            paid_amount=paid,
            adjustment_amount=adjustment,
            patient_responsibility=responsibility,
            unpaid_balance=unpaid,
            payment_ratio=ratio,
            payment_classification=classification,
            adjustment_classification=adjustment_classification,
            payment_status=status,
            risk_score=min(sum(SCORES[issue.severity] for issue in issues), 100),
            evidence=evidence,
            issues=issues,
            root_cause=root_cause,
            recommendations=recommendations,
            missing_information=missing,
            requires_human_review=status == PaymentStatus.REVIEW,
            policy_status="FOUND" if policy else "UNKNOWN",
        )

    def _policy_for(self, payment: Any, claim: Any) -> dict[str, Any] | None:
        payer = _value(payment, "payer") or _value(claim, "payer")
        return self.payer_policy_lookup(payer) if self.payer_policy_lookup and payer else None

    @staticmethod
    def _default_policy_lookup(payer: str) -> dict[str, Any] | None:
        policy_path = Path(__file__).resolve().parents[2] / "data" / "payer_policies.json"
        with policy_path.open(encoding="utf-8") as policy_file:
            policies = json.load(policy_file).get("policies", [])
        return next((policy for policy in policies if policy.get("payer") == payer), None)

    @staticmethod
    def _financial_issues(amounts: dict[str, Decimal | None]) -> list[PaymentIssue]:
        missing = [name for name, value in amounts.items() if value is None]
        if not missing:
            return []
        return [PaymentIssue(rule="payment_data", severity=PaymentSeverity.MEDIUM, message="Required financial payment data is incomplete", details={"missing_fields": missing})]

    @staticmethod
    def _classify(paid: Decimal | None, billed: Decimal | None, unpaid: Decimal | None, issues: list[PaymentIssue], policy: dict[str, Any] | None) -> PaymentClassification:
        if paid is None:
            return PaymentClassification.PAYMENT_DATA_INCOMPLETE
        if paid == 0:
            return PaymentClassification.ZERO_PAYMENT
        benchmark = _decimal(policy.get("payment_benchmark")) if policy else None
        if benchmark is not None and paid < benchmark:
            return PaymentClassification.UNDERPAYMENT
        if benchmark is not None and paid > benchmark:
            return PaymentClassification.OVERPAYMENT
        if billed is None or unpaid is None:
            return PaymentClassification.PAYMENT_DATA_INCOMPLETE
        if unpaid > 0:
            return PaymentClassification.PARTIAL_PAYMENT
        if unpaid == 0:
            return PaymentClassification.PAID
        return PaymentClassification.UNKNOWN

    @staticmethod
    def _adjustment_classification(adjustment: Decimal | None, responsibility: Decimal | None, unpaid: Decimal | None) -> AdjustmentClassification:
        if adjustment is None:
            return AdjustmentClassification.MISSING_ADJUSTMENT_DATA
        if adjustment == 0:
            return AdjustmentClassification.PATIENT_RESPONSIBILITY if responsibility and responsibility > 0 else AdjustmentClassification.NO_ADJUSTMENT
        if unpaid is not None and responsibility is not None and unpaid == responsibility:
            return AdjustmentClassification.CONTRACTUAL_ADJUSTMENT
        return AdjustmentClassification.UNRECONCILED_AMOUNT

    @staticmethod
    def _classification_issues(classification: PaymentClassification) -> list[PaymentIssue]:
        if classification == PaymentClassification.PARTIAL_PAYMENT:
            return [PaymentIssue(rule="partial_payment", severity=PaymentSeverity.MEDIUM, message="A positive deterministic unpaid balance remains")]
        if classification == PaymentClassification.ZERO_PAYMENT:
            return [PaymentIssue(rule="zero_payment", severity=PaymentSeverity.HIGH, message="A payment record exists with zero paid amount")]
        if classification in {PaymentClassification.UNDERPAYMENT, PaymentClassification.OVERPAYMENT}:
            return [PaymentIssue(rule="payment_benchmark", severity=PaymentSeverity.HIGH, message="Payment differs from the configured synthetic benchmark")]
        return []

    def _evidence(self, payment: Any, claim: Any, history: list[Any], policy: dict[str, Any] | None, amounts: dict[str, Decimal | None], unpaid: Decimal | None, ratio: Decimal | None) -> list[PaymentEvidence]:
        evidence = [PaymentEvidence(source="payment_record", field=field, value=str(_value(payment, field)), description="Synthetic payment record reports this value.") for field in ("payment_id", "allowed_amount", "paid_amount", "adjustment_amount", "patient_responsibility", "status")]
        if claim is not None:
            evidence.append(PaymentEvidence(source="claim_record", field="claim_amount", value=str(amounts["billed_amount"]), description="Synthetic claim amount is used as billed amount."))
        evidence.append(PaymentEvidence(source="payment_record", field="unpaid_balance", value=str(unpaid), description="Deterministically calculated as billed minus paid minus adjustment."))
        evidence.append(PaymentEvidence(source="payment_record", field="payment_ratio", value=str(ratio), description="Deterministically calculated only when allowed amount is positive."))
        if policy is not None:
            evidence.append(PaymentEvidence(source="payer_policy", field="payment_benchmark", value=policy.get("payment_benchmark"), description="No payment benchmark is configured unless explicitly present in the synthetic payer policy."))
        if history:
            evidence.append(PaymentEvidence(source="claim_history", field="record_count", value=len(history), description="Synthetic claim history records were provided."))
        return evidence

    def _denial_evidence(self, claim_id: str | None) -> list[PaymentEvidence]:
        if not self.denial_lookup or not claim_id:
            return []
        denial = self.denial_lookup(claim_id)
        if denial is None:
            return []
        result = self.denial_agent.analyze_denial(denial) if self.denial_agent else None
        details = {"denial_id": _value(denial, "denial_id"), "denial_category": getattr(result, "denial_category", None).value if result else None, "status": getattr(result, "status", None).value if result else None}
        return [PaymentEvidence(source="denial_agent" if result else "denial_record", field="denial_category", value=details["denial_category"], description="Synthetic denial evidence is preserved as supporting payment context.",)]

    def _rules_evidence(self, claim: Any) -> list[PaymentEvidence]:
        if self.rules_engine is None or claim is None:
            return []
        result = self.rules_engine.validate_claim(claim)
        return [PaymentEvidence(source="rules_engine", field="overall_status", value=result.overall_status, description="Existing deterministic Rules Engine result is preserved as payment context.")]

    def _explain(self, payment: Any, classification: PaymentClassification, status: PaymentStatus, evidence: list[PaymentEvidence], issues: list[PaymentIssue]) -> tuple[str, list[str], list[str]]:
        fallback = self._recommendations(classification)
        missing = [field for issue in issues for field in issue.details.get("missing_fields", [])]
        root = f"Payment data was classified deterministically as {classification.value}."
        if self.llm_service:
            self._audit("payment_llm_reasoning", _value(payment, "payment_id"), "started")
            try:
                response = self.llm_service.generate_structured(system_instructions="Explain only deterministic payment evidence. Do not change amounts, classification, policy, denial evidence, or reconciliation.", user_prompt=f"Payment classification: {classification.value}\nStatus: {status.value}\nEvidence: {[item.model_dump() for item in evidence]}\nIssues: {[item.model_dump() for item in issues]}", response_model=PaymentExplanation)
                self._audit("payment_llm_reasoning", _value(payment, "payment_id"), "completed")
                return root, response.response.recommendations or fallback, response.response.missing_information
            except LLMServiceError:
                self._audit("payment_llm_reasoning", _value(payment, "payment_id"), "failed")
        return root, fallback, missing

    @staticmethod
    def _recommendations(classification: PaymentClassification) -> list[str]:
        return {
            PaymentClassification.PAID: ["No automatic financial modification is recommended; retain the payment evidence."],
            PaymentClassification.PARTIAL_PAYMENT: ["Review the outstanding balance and supporting payment evidence with a financial reviewer."],
            PaymentClassification.ZERO_PAYMENT: ["Investigate the zero payment and review related denial or remittance evidence."],
            PaymentClassification.NO_PAYMENT_RECORDED: ["Verify whether a payment record exists before taking financial action."],
            PaymentClassification.PAYMENT_DATA_INCOMPLETE: ["Obtain the missing payment fields before determining the financial outcome."],
            PaymentClassification.UNDERPAYMENT: ["Review the configured synthetic benchmark and payment evidence with a financial reviewer."],
            PaymentClassification.OVERPAYMENT: ["Review the configured synthetic benchmark and payment evidence with a financial reviewer."],
        }.get(classification, ["Human review is required because payment evidence is insufficient or unresolved."])

    def _audit(self, action: str, payment_id: str | None, status: str) -> None:
        if self.audit_sink:
            self.audit_sink(action, {"payment_id": payment_id, "status": status, "source": "synthetic_demo"})
