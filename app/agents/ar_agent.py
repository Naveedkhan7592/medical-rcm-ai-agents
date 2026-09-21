from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any

from app.schemas import (
    ARAgentResult,
    ARBalanceState,
    AREvidence,
    ARExplanation,
    ARIssue,
    ARPriority,
    ARSeverity,
    ARStatus,
    AgingBucket,
    DenialCategory,
    DenialContext,
    DenialStatus,
    PaymentClassification,
    PaymentStatus,
    WorkQueueType,
)
from app.services.llm_service import LLMService, LLMServiceError


Lookup = Callable[[str], Any | None]
HistoryLookup = Callable[[str], Iterable[Any]]
DateProvider = Callable[[], date]
AuditSink = Callable[[str, dict[str, Any]], None]

SCORES = {ARSeverity.CRITICAL: 40, ARSeverity.HIGH: 25, ARSeverity.MEDIUM: 15, ARSeverity.LOW: 5}


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


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class ARAgent:
    """Aggregate deterministic payment, denial, history, and aging evidence."""

    def __init__(
        self,
        *,
        claim_lookup: Lookup | None = None,
        payment_lookup: Lookup | None = None,
        denial_lookup: Lookup | None = None,
        patient_lookup: Lookup | None = None,
        claim_history_lookup: HistoryLookup | None = None,
        payer_policy_lookup: Lookup | None = None,
        payment_agent: Any | None = None,
        denial_agent: Any | None = None,
        rules_engine: Any | None = None,
        llm_service: LLMService | Any | None = None,
        audit_sink: AuditSink | None = None,
        current_date_provider: DateProvider = date.today,
        ar_policy: Mapping[str, Any] | None = None,
    ) -> None:
        self.claim_lookup = claim_lookup
        self.payment_lookup = payment_lookup
        self.denial_lookup = denial_lookup
        self.patient_lookup = patient_lookup
        self.claim_history_lookup = claim_history_lookup
        self.payer_policy_lookup = payer_policy_lookup or self._default_payer_policy
        self.payment_agent = payment_agent
        self.denial_agent = denial_agent
        self.rules_engine = rules_engine
        self.llm_service = llm_service
        self.audit_sink = audit_sink
        self.current_date_provider = current_date_provider
        self.ar_policy = dict(ar_policy or self._load_ar_policy())

    def run(self, claim_id: str) -> ARAgentResult:
        if self.claim_lookup is None:
            raise ValueError("claim_lookup is required when running by claim ID")
        claim = self.claim_lookup(claim_id)
        if claim is None:
            raise LookupError("claim not found")
        return self.analyze_ar(claim)

    def analyze_ar(self, claim: Any) -> ARAgentResult:
        claim_id = _value(claim, "claim_id")
        self._audit("ar_check_started", claim_id, "started")
        self._audit("ar_claim_loaded", claim_id, "found")
        history = list(self.claim_history_lookup(claim_id)) if self.claim_history_lookup else []
        self._audit("ar_history_checked", claim_id, str(len(history)))

        payment_result = self._payment_context(claim)
        self._audit("ar_payment_evidence_collected", claim_id, "available" if payment_result else "unavailable")
        denial_result = self._denial_context(claim)
        self._audit("ar_denial_evidence_collected", claim_id, "available" if denial_result else "unavailable")
        payer_policy = self.payer_policy_lookup(_value(claim, "payer")) if self.payer_policy_lookup else None
        self._audit("ar_policy_checked", claim_id, "FOUND" if payer_policy else "UNKNOWN")

        billed = _decimal(_value(payment_result, "billed_amount")) if payment_result else _decimal(_value(claim, "claim_amount"))
        paid = _decimal(_value(payment_result, "paid_amount")) if payment_result else None
        adjustment = _decimal(_value(payment_result, "adjustment_amount")) if payment_result else None
        balance = _decimal(_value(payment_result, "unpaid_balance")) if payment_result else None
        balance_state = ARBalanceState.CALCULATED if balance is not None else ARBalanceState.INCOMPLETE
        issues = self._financial_issues(payment_result, billed, paid, adjustment, balance_state)
        self._audit("ar_balance_calculated", claim_id, str(balance) if balance is not None else "incomplete")

        current_date = self.current_date_provider()
        service_date = _as_date(_value(claim, "service_date"))
        age, aging_bucket = self._age(service_date, current_date)
        if service_date is None:
            issues.append(ARIssue(rule="service_date", severity=ARSeverity.MEDIUM, message="Service date is missing or invalid"))
        elif service_date > current_date:
            issues.append(ARIssue(rule="future_service_date", severity=ARSeverity.HIGH, message="Service date is in the future relative to the analysis date", details={"service_date": service_date.isoformat(), "current_date": current_date.isoformat()}))
        self._audit("ar_age_calculated", claim_id, str(age) if age is not None else "invalid")
        self._audit("ar_aging_bucket_assigned", claim_id, aging_bucket.value)

        denial_category, denial_status, denial_context = self._denial_values(denial_result)
        if denial_status == DenialStatus.REVIEW:
            issues.append(ARIssue(rule="denial_review", severity=ARSeverity.HIGH, message="Denial evidence requires human review"))
        payment_classification = self._payment_classification(payment_result)
        payment_status = _value(payment_result, "payment_status")
        if payment_status == PaymentStatus.REVIEW or payment_status == PaymentStatus.REVIEW.value:
            issues.append(ARIssue(rule="payment_review", severity=ARSeverity.MEDIUM, message="Payment analysis requires human review"))
        if payer_policy is None and _value(claim, "payer"):
            issues.append(ARIssue(rule="payer_policy", severity=ARSeverity.MEDIUM, message="Payer policy is unavailable for A/R analysis"))

        ar_status = self._ar_status(balance, balance_state, issues)
        priority, priority_reasons = self._priority(age, balance, denial_status, payment_classification, issues)
        issues.extend(self._priority_issue(priority))
        work_type = self._work_queue(denial_category, payment_classification, balance_state, issues)
        self._audit("ar_priority_assigned", claim_id, priority.value)
        self._audit("ar_work_queue_recommendation_generated", claim_id, work_type.value)
        risk_score = min(sum(SCORES[issue.severity] for issue in self._unique_issues(issues)), 100)
        status = self._overall_status(ar_status, issues, priority)
        self._audit("ar_root_cause_analyzed", claim_id, status)
        root_cause, recommendations, missing = self._explain(claim, status, balance, age, aging_bucket, priority, work_type, payment_classification, denial_category, issues)
        self._audit("ar_result_generated", claim_id, status)

        evidence = self._evidence(claim, payment_result, denial_result, history, payer_policy, billed, paid, adjustment, balance, age, aging_bucket, priority)
        return ARAgentResult(
            claim_id=claim_id,
            billed_amount=billed,
            paid_amount=paid,
            adjustment_amount=adjustment,
            outstanding_balance=balance,
            balance_state=balance_state,
            ar_age_days=age,
            aging_bucket=aging_bucket,
            ar_status=ar_status,
            status=status,
            payment_classification=payment_classification,
            denial_category=denial_category,
            denial_status=denial_status,
            denial_context=denial_context,
            priority=priority,
            priority_reasons=priority_reasons,
            recommended_work_type=work_type,
            evidence=evidence,
            issues=issues,
            root_cause=root_cause,
            recommendations=recommendations,
            missing_information=missing,
            risk_score=risk_score,
            requires_human_review=status == "REVIEW",
            policy_status="FOUND" if payer_policy else "UNKNOWN",
        )

    def _payment_context(self, claim: Any) -> Any | None:
        if self.payment_lookup is None:
            return None
        raw = self.payment_lookup(_value(claim, "claim_id"))
        if isinstance(raw, (list, tuple)):
            raw = raw[-1] if raw else None
        if raw is None:
            return None
        if self.payment_agent is not None:
            return self.payment_agent.analyze_payment(raw)
        return None

    def _denial_context(self, claim: Any) -> Any | None:
        if not self.denial_lookup:
            return None
        raw = self.denial_lookup(_value(claim, "claim_id"))
        if isinstance(raw, (list, tuple)):
            raw = raw[-1] if raw else None
        if raw is None:
            return None
        return self.denial_agent.analyze_denial(raw) if self.denial_agent else raw

    @staticmethod
    def _payment_classification(result: Any) -> PaymentClassification | None:
        value = _value(result, "payment_classification")
        if value is None:
            return None
        return value if isinstance(value, PaymentClassification) else PaymentClassification(value)

    @staticmethod
    def _denial_values(result: Any) -> tuple[DenialCategory | None, DenialStatus | None, DenialContext]:
        if result is None:
            return None, None, DenialContext.NO_DENIAL
        category_value = _value(result, "denial_category")
        status_value = _value(result, "status")
        category = category_value if isinstance(category_value, DenialCategory) else DenialCategory(category_value) if category_value else None
        status = status_value if isinstance(status_value, DenialStatus) else DenialStatus(status_value) if status_value else None
        context = DenialContext.DENIAL_REQUIRES_REVIEW if _value(result, "requires_human_review") or status == DenialStatus.REVIEW else DenialContext.DENIAL_PRESENT
        return category, status, context

    @staticmethod
    def _age(service_date: date | None, current_date: date) -> tuple[int | None, AgingBucket]:
        if service_date is None:
            return None, AgingBucket.UNKNOWN
        age = (current_date - service_date).days
        if age < 0:
            return age, AgingBucket.INVALID
        if age <= 30:
            return age, AgingBucket.CURRENT_0_30
        if age <= 60:
            return age, AgingBucket.DAYS_31_60
        if age <= 90:
            return age, AgingBucket.DAYS_61_90
        if age <= 120:
            return age, AgingBucket.DAYS_91_120
        if age <= 180:
            return age, AgingBucket.DAYS_121_180
        if age <= 365:
            return age, AgingBucket.DAYS_181_365
        return age, AgingBucket.DAYS_366_PLUS

    @staticmethod
    def _financial_issues(payment: Any, billed: Decimal | None, paid: Decimal | None, adjustment: Decimal | None, balance_state: ARBalanceState) -> list[ARIssue]:
        if payment is None:
            return [ARIssue(rule="payment_data", severity=ARSeverity.MEDIUM, message="Payment evidence is unavailable for A/R calculation")]
        missing = [name for name, value in (("billed_amount", billed), ("paid_amount", paid), ("adjustment_amount", adjustment), ("outstanding_balance", _value(payment, "unpaid_balance"))) if value is None]
        if missing or balance_state == ARBalanceState.INCOMPLETE:
            return [ARIssue(rule="payment_data", severity=ARSeverity.MEDIUM, message="Required financial data is incomplete for A/R calculation", details={"missing_fields": missing})]
        return []

    @staticmethod
    def _ar_status(balance: Decimal | None, state: ARBalanceState, issues: list[ARIssue]) -> ARStatus:
        if state == ARBalanceState.INCOMPLETE:
            return ARStatus.INCOMPLETE
        if balance is None:
            return ARStatus.UNKNOWN
        if balance == 0:
            return ARStatus.RESOLVED
        if balance > 0:
            return ARStatus.OPEN
        return ARStatus.UNKNOWN

    def _priority(self, age: int | None, balance: Decimal | None, denial_status: DenialStatus | None, payment_classification: PaymentClassification | None, issues: list[ARIssue]) -> tuple[ARPriority, list[str]]:
        reasons: list[str] = []
        critical_age = int(self.ar_policy["critical_age_days"])
        critical_balance = _decimal(self.ar_policy["critical_balance"]) or Decimal("0")
        high_age = int(self.ar_policy["high_age_days"])
        high_balance = _decimal(self.ar_policy["high_balance"]) or Decimal("0")
        medium_age = int(self.ar_policy["medium_age_days"])
        medium_balance = _decimal(self.ar_policy["medium_balance"]) or Decimal("0")
        if age is not None and age >= critical_age:
            reasons.append(f"A/R age is {age} days")
        if balance is not None and balance >= critical_balance:
            reasons.append(f"outstanding balance is {balance}")
        if reasons:
            return ARPriority.CRITICAL, reasons
        if age is not None and age >= high_age:
            reasons.append(f"A/R age is {age} days")
        if balance is not None and balance >= high_balance:
            reasons.append(f"outstanding balance is {balance}")
        if denial_status == DenialStatus.REVIEW:
            reasons.append("denial requires human review")
        if payment_classification in {PaymentClassification.ZERO_PAYMENT, PaymentClassification.UNDERPAYMENT, PaymentClassification.OVERPAYMENT}:
            reasons.append(f"payment classification is {payment_classification.value}")
        if reasons:
            return ARPriority.HIGH, reasons
        if age is not None and age >= medium_age:
            reasons.append(f"A/R age is {age} days")
        if balance is not None and balance >= medium_balance:
            reasons.append(f"outstanding balance is {balance}")
        if issues:
            reasons.append("deterministic A/R issue requires review")
        if reasons:
            return ARPriority.MEDIUM, reasons
        return ARPriority.LOW, ["A/R age and balance are within the synthetic low-priority thresholds"]

    @staticmethod
    def _priority_issue(priority: ARPriority) -> list[ARIssue]:
        if priority == ARPriority.CRITICAL:
            return [ARIssue(rule="ar_priority", severity=ARSeverity.CRITICAL, message="A/R meets the synthetic critical priority criteria")]
        if priority == ARPriority.HIGH:
            return [ARIssue(rule="ar_priority", severity=ARSeverity.HIGH, message="A/R meets the synthetic high priority criteria")]
        if priority == ARPriority.MEDIUM:
            return [ARIssue(rule="ar_priority", severity=ARSeverity.MEDIUM, message="A/R meets the synthetic medium priority criteria")]
        return []

    @staticmethod
    def _overall_status(ar_status: ARStatus, issues: list[ARIssue], priority: ARPriority) -> str:
        if ar_status in {ARStatus.INCOMPLETE, ARStatus.UNKNOWN} or issues or priority in {ARPriority.HIGH, ARPriority.CRITICAL}:
            return "REVIEW"
        return "PASS"

    @staticmethod
    def _work_queue(denial_category: DenialCategory | None, payment_classification: PaymentClassification | None, balance_state: ARBalanceState, issues: list[ARIssue]) -> WorkQueueType:
        if balance_state == ARBalanceState.INCOMPLETE:
            return WorkQueueType.HUMAN_FINANCIAL_REVIEW
        if denial_category in {DenialCategory.ELIGIBILITY}:
            return WorkQueueType.REVIEW_ELIGIBILITY
        if denial_category in {DenialCategory.CODING}:
            return WorkQueueType.REVIEW_CODING
        if denial_category in {DenialCategory.MISSING_DOCUMENTATION}:
            return WorkQueueType.REVIEW_DOCUMENTATION
        if denial_category is not None:
            return WorkQueueType.INVESTIGATE_DENIAL
        if payment_classification in {PaymentClassification.PARTIAL_PAYMENT, PaymentClassification.ZERO_PAYMENT, PaymentClassification.UNDERPAYMENT, PaymentClassification.OVERPAYMENT}:
            return WorkQueueType.INVESTIGATE_PAYMENT
        if any(issue.rule == "future_service_date" for issue in issues):
            return WorkQueueType.REVIEW_CLAIM_HISTORY
        return WorkQueueType.NO_ACTION

    @staticmethod
    def _unique_issues(issues: list[ARIssue]) -> list[ARIssue]:
        seen: set[str] = set()
        unique: list[ARIssue] = []
        for issue in issues:
            if issue.rule not in seen:
                seen.add(issue.rule)
                unique.append(issue)
        return unique

    def _evidence(self, claim: Any, payment: Any, denial: Any, history: list[Any], policy: Any, billed: Decimal | None, paid: Decimal | None, adjustment: Decimal | None, balance: Decimal | None, age: int | None, bucket: AgingBucket, priority: ARPriority) -> list[AREvidence]:
        evidence = [AREvidence(source="claim_record", field="claim_id", value=_value(claim, "claim_id"), description="Synthetic claim identifies the A/R account."), AREvidence(source="claim_record", field="service_date", value=str(_value(claim, "service_date")), description="Claim service date is the deterministic A/R start date.")]
        if payment is not None:
            for field in ("payment_classification", "unpaid_balance", "payment_status", "adjustment_classification"):
                evidence.append(AREvidence(source="payment_agent", field=field, value=str(_value(payment, field)), description="Payment Agent result is consumed as financial evidence."))
        if denial is not None:
            evidence.append(AREvidence(source="denial_agent", field="denial_category", value=str(_value(_value(denial, "denial_category"), "value", _value(denial, "denial_category"))), description="Denial Agent classification is preserved as A/R context."))
        evidence.extend([AREvidence(source="ar_policy", field="priority", value=priority.value, description="Priority was assigned using the synthetic A/R policy."), AREvidence(source="ar_policy", field="aging_bucket", value=bucket.value, description="Aging bucket was assigned using deterministic calendar-day boundaries.")])
        if history:
            evidence.append(AREvidence(source="claim_history", field="record_count", value=len(history), description="Synthetic claim history records were provided."))
        if policy is not None:
            evidence.append(AREvidence(source="payer_policy", field="payer", value=_value(claim, "payer"), description="Synthetic payer policy was available."))
        return evidence

    def _explain(self, claim: Any, status: str, balance: Decimal | None, age: int | None, bucket: AgingBucket, priority: ARPriority, work_type: WorkQueueType, payment_classification: PaymentClassification | None, denial_category: DenialCategory | None, issues: list[ARIssue]) -> tuple[str, list[str], list[str]]:
        root = f"Deterministic A/R status is {status}; balance is {balance} and age is {age} days in bucket {bucket.value}."
        fallback = [f"Recommended work type: {work_type.value}."]
        missing = [field for issue in issues for field in issue.details.get("missing_fields", [])]
        if self.llm_service:
            self._audit("ar_llm_reasoning", _value(claim, "claim_id"), "started")
            try:
                response = self.llm_service.generate_structured(system_instructions="Explain only deterministic A/R evidence. Do not change balance, age, bucket, priority, payment classification, denial category, or payer policy.", user_prompt=f"A/R status: {status}\nBalance: {balance}\nAge: {age}\nBucket: {bucket.value}\nPriority: {priority.value}\nWork type: {work_type.value}\nPayment: {payment_classification}\nDenial: {denial_category}\nIssues: {[item.model_dump() for item in issues]}", response_model=ARExplanation)
                self._audit("ar_llm_reasoning", _value(claim, "claim_id"), "completed")
                return root, response.response.recommendations or fallback, response.response.missing_information
            except LLMServiceError:
                self._audit("ar_llm_reasoning", _value(claim, "claim_id"), "failed")
        return root, fallback, missing

    @staticmethod
    def _load_ar_policy() -> dict[str, Any]:
        path = Path(__file__).resolve().parents[2] / "data" / "ar_policy.json"
        with path.open(encoding="utf-8") as policy_file:
            return json.load(policy_file)

    @staticmethod
    def _default_payer_policy(payer: str) -> dict[str, Any] | None:
        path = Path(__file__).resolve().parents[2] / "data" / "payer_policies.json"
        with path.open(encoding="utf-8") as policy_file:
            policies = json.load(policy_file).get("policies", [])
        return next((policy for policy in policies if policy.get("payer") == payer), None)

    def _audit(self, action: str, claim_id: str | None, status: str) -> None:
        if self.audit_sink:
            self.audit_sink(action, {"claim_id": claim_id, "status": status, "source": "synthetic_demo"})
