from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas import (
    AgingBucket,
    BillingQAEvidence,
    BillingQAConsistencyCheck,
    BillingQAExplanation,
    BillingQAIssue,
    BillingQAIssueType,
    BillingQAPriority,
    BillingQAResult,
    BillingQASeverity,
    BillingQAStatus,
    DenialCategory,
    LLMResponse,
    PaymentClassification,
    QACheckStatus,
)
from app.services.llm_service import LLMService, LLMServiceError


Lookup = Callable[[str], Any | None]
HistoryLookup = Callable[[str], Iterable[Any]]
DateProvider = Callable[[], date]
AuditSink = Callable[[str, dict[str, Any]], None]

SCORES = {BillingQASeverity.CRITICAL: 40, BillingQASeverity.HIGH: 25, BillingQASeverity.MEDIUM: 15, BillingQASeverity.LOW: 5}


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


class BillingQAAgent:
    """Verify consistency among existing deterministic RCM results."""

    def __init__(
        self,
        *,
        claim_lookup: Lookup | None = None,
        patient_lookup: Lookup | None = None,
        payment_lookup: Lookup | None = None,
        denial_lookup: Lookup | None = None,
        claim_history_lookup: HistoryLookup | None = None,
        payer_policy_lookup: Lookup | None = None,
        rules_engine: Any | None = None,
        eligibility_agent: Any | None = None,
        claims_agent: Any | None = None,
        coding_agent: Any | None = None,
        denial_agent: Any | None = None,
        payment_agent: Any | None = None,
        ar_agent: Any | None = None,
        llm_service: LLMService | Any | None = None,
        audit_sink: AuditSink | None = None,
        current_date_provider: DateProvider = date.today,
        expected_agents: Iterable[str] | None = None,
    ) -> None:
        self.claim_lookup = claim_lookup
        self.patient_lookup = patient_lookup
        self.payment_lookup = payment_lookup
        self.denial_lookup = denial_lookup
        self.claim_history_lookup = claim_history_lookup
        self.payer_policy_lookup = payer_policy_lookup
        self.rules_engine = rules_engine
        self.eligibility_agent = eligibility_agent
        self.claims_agent = claims_agent
        self.coding_agent = coding_agent
        self.denial_agent = denial_agent
        self.payment_agent = payment_agent
        self.ar_agent = ar_agent
        self.llm_service = llm_service
        self.audit_sink = audit_sink
        self.current_date_provider = current_date_provider
        self.expected_agents = set(expected_agents or [])

    def run(self, claim_id: str) -> BillingQAResult:
        if self.claim_lookup is None:
            raise ValueError("claim_lookup is required when running by claim ID")
        claim = self.claim_lookup(claim_id)
        if claim is None:
            raise LookupError("claim not found")
        return self.run_qa(claim)

    def run_qa(
        self,
        claim: Any,
        *,
        rules_result: Any | None = None,
        eligibility_result: Any | None = None,
        claims_result: Any | None = None,
        coding_result: Any | None = None,
        denial_result: Any | None = None,
        payment_result: Any | None = None,
        ar_result: Any | None = None,
    ) -> BillingQAResult:
        claim_id = _value(claim, "claim_id")
        self._audit("billing_qa_check_started", claim_id, "started")
        results = {
            "rules": rules_result or self._call_rules(claim),
            "eligibility": eligibility_result or self._call_eligibility(claim),
            "claims": claims_result or self._call_claims(claim),
            "coding": coding_result or self._call_coding(claim),
            "denial": denial_result or self._call_denial(claim),
            "payment": payment_result or self._call_payment(claim),
            "ar": ar_result or self._call_ar(claim),
        }
        self._audit("billing_qa_claim_loaded", claim_id, "found")
        checked = [name for name, result in results.items() if result is not None]
        issues: list[BillingQAIssue] = []
        checks: list[BillingQAConsistencyCheck] = []
        evidence: list[BillingQAEvidence] = []
        missing: list[str] = []

        for name in self.expected_agents:
            if results.get(name) is None:
                missing.append(name)
                issue = self._issue(BillingQAIssueType.MISSING_AGENT_RESULT, BillingQASeverity.HIGH, f"Required {name} result is missing", source="claim_record", field=name, value=None)
                issues.append(issue)
                checks.append(BillingQAConsistencyCheck(check=f"{name}_result", status=QACheckStatus.MISSING, description=f"Required {name} result was not available", evidence=issue.evidence))

        self._audit("billing_qa_rules_checked", claim_id, "checked" if results["rules"] else "missing")
        self._audit("billing_qa_eligibility_checked", claim_id, "checked" if results["eligibility"] else "missing")
        self._audit("billing_qa_claims_checked", claim_id, "checked" if results["claims"] else "missing")
        self._audit("billing_qa_coding_checked", claim_id, "checked" if results["coding"] else "missing")
        self._audit("billing_qa_denial_checked", claim_id, "checked" if results["denial"] else "missing")
        self._audit("billing_qa_payment_checked", claim_id, "checked" if results["payment"] else "missing")
        self._audit("billing_qa_ar_checked", claim_id, "checked" if results["ar"] else "missing")

        for name, result in results.items():
            if result is not None:
                result_claim_id = _value(result, "claim_id")
                if result_claim_id is not None:
                    evidence.append(BillingQAEvidence(source=f"{name}_agent", field="claim_id", value=result_claim_id, description=f"{name} result claim identity."))
                    if result_claim_id != claim_id:
                        issue = self._issue(BillingQAIssueType.CLAIM_ID_MISMATCH, BillingQASeverity.HIGH, f"{name} result refers to a different claim", source=f"{name}_agent", field="claim_id", value=result_claim_id)
                        issues.append(issue)
                        checks.append(BillingQAConsistencyCheck(check=f"claim_vs_{name}_id", status=QACheckStatus.CONFLICT, description=issue.message, evidence=issue.evidence))

        issues.extend(self._check_payer(claim, results, checks))
        issues.extend(self._check_statuses(results, checks))
        issues.extend(self._check_coding_claim(claim, results, checks))
        issues.extend(self._check_denial(results, checks))
        issues.extend(self._check_payment(claim, results, checks))
        issues.extend(self._check_ar(claim, results, checks))
        issues.extend(self._check_history_and_policy(claim, results, checks))
        evidence.extend(self._result_evidence(results))
        self._audit("billing_qa_cross_agent_checks_completed", claim_id, str(len(checks)))
        if issues:
            self._audit("billing_qa_conflicts_detected", claim_id, str(len(issues)))

        unique_issues = self._unique_issues(issues)
        priority = self._priority(unique_issues)
        risk_score = min(sum(SCORES[issue.severity] for issue in unique_issues), 100)
        qa_status = BillingQAStatus.REVIEW if unique_issues else BillingQAStatus.PASS
        root_cause, recommendations, llm_explanation = self._explain(claim, qa_status, priority, unique_issues, checks)
        passed_checks = [check.check for check in checks if check.status == QACheckStatus.PASS]
        failed_checks = [check.check for check in checks if check.status == QACheckStatus.CONFLICT]
        agent_summary = {name: "available" if result is not None else "missing" for name, result in results.items()}
        self._audit("billing_qa_result_generated", claim_id, qa_status.value)
        return BillingQAResult(
            claim_id=claim_id,
            qa_status=qa_status,
            qa_priority=priority,
            status=qa_status,
            priority=priority,
            risk_score=risk_score,
            issues=unique_issues,
            evidence=evidence,
            agent_results_checked=checked,
            consistency_checks=checks,
            checks_performed=[check.check for check in checks],
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            warnings=[issue.message for issue in unique_issues if issue.severity == BillingQASeverity.MEDIUM],
            missing_evidence=missing,
            agent_results_summary=agent_summary,
            root_cause=root_cause,
            recommendations=recommendations,
            requires_human_review=qa_status == BillingQAStatus.REVIEW,
            human_review_required=qa_status == BillingQAStatus.REVIEW,
            llm_explanation=llm_explanation,
        )

    def _call_rules(self, claim: Any) -> Any | None:
        return self.rules_engine.validate_claim(claim) if self.rules_engine else None

    def _call_eligibility(self, claim: Any) -> Any | None:
        return self.eligibility_agent.process_claim(claim) if self.eligibility_agent else None

    def _call_claims(self, claim: Any) -> Any | None:
        return self.claims_agent.validate_claim(claim) if self.claims_agent else None

    def _call_coding(self, claim: Any) -> Any | None:
        return self.coding_agent.validate_coding(claim) if self.coding_agent else None

    def _call_denial(self, claim: Any) -> Any | None:
        if not self.denial_agent or not self.denial_lookup:
            return None
        denial = self.denial_lookup(_value(claim, "claim_id"))
        if isinstance(denial, (list, tuple)):
            denial = denial[-1] if denial else None
        return self.denial_agent.analyze_denial(denial) if denial else None

    def _call_payment(self, claim: Any) -> Any | None:
        if not self.payment_agent or not self.payment_lookup:
            return None
        payment = self.payment_lookup(_value(claim, "claim_id"))
        if isinstance(payment, (list, tuple)):
            payment = payment[-1] if payment else None
        return self.payment_agent.analyze_payment(payment) if payment else None

    def _call_ar(self, claim: Any) -> Any | None:
        return self.ar_agent.analyze_ar(claim) if self.ar_agent else None

    def _check_payer(self, claim: Any, results: dict[str, Any], checks: list[BillingQAConsistencyCheck]) -> list[BillingQAIssue]:
        issues: list[BillingQAIssue] = []
        claim_payer = _value(claim, "payer")
        for name in ("eligibility", "claims", "payment", "ar"):
            payer = _value(results.get(name), "payer")
            if payer is not None and claim_payer is not None and payer != claim_payer:
                issue = self._issue(BillingQAIssueType.PAYER_MISMATCH, BillingQASeverity.HIGH, f"Claim payer differs from {name} payer", source=f"{name}_agent", field="payer", value=payer, details={"claim_payer": claim_payer})
                issues.append(issue)
                checks.append(BillingQAConsistencyCheck(check=f"claim_vs_{name}_payer", status=QACheckStatus.CONFLICT, description=issue.message, evidence=issue.evidence))
        return issues

    def _check_statuses(self, results: dict[str, Any], checks: list[BillingQAConsistencyCheck]) -> list[BillingQAIssue]:
        issues: list[BillingQAIssue] = []
        rules_status = _value(results.get("rules"), "overall_status")
        claims_status = _value(results.get("claims"), "status")
        if rules_status and claims_status and rules_status != claims_status:
            issue = self._issue(BillingQAIssueType.STATUS_CONFLICT, BillingQASeverity.HIGH, "Rules Engine and Claims Agent statuses conflict", source="rules_engine", field="overall_status", value=rules_status, details={"claims_status": str(claims_status)})
            issues.append(issue)
            checks.append(BillingQAConsistencyCheck(check="rules_vs_claims_status", status=QACheckStatus.CONFLICT, description=issue.message, evidence=issue.evidence))
        elif rules_status and claims_status:
            checks.append(BillingQAConsistencyCheck(check="rules_vs_claims_status", status=QACheckStatus.PASS, description="Rules Engine and Claims Agent statuses agree"))
        eligibility_status = _value(results.get("eligibility"), "eligibility_status")
        claims_eligibility = _value(_value(results.get("claims"), "eligibility_result"), "eligibility_status")
        if eligibility_status and claims_eligibility and str(eligibility_status) != str(claims_eligibility):
            issues.append(self._issue(BillingQAIssueType.ELIGIBILITY_CONFLICT, BillingQASeverity.HIGH, "Eligibility Agent and Claims Agent eligibility statuses conflict", source="eligibility_agent", field="eligibility_status", value=str(eligibility_status), details={"claims_eligibility": str(claims_eligibility)}))
        coding_status = _value(results.get("coding"), "status")
        if str(coding_status) == "FAIL" and str(claims_status) == "PASS":
            issues.append(self._issue(BillingQAIssueType.CODING_CONFLICT, BillingQASeverity.HIGH, "Coding Agent failed while Claims Agent reported PASS", source="coding_agent", field="status", value="FAIL"))
        return issues

    def _check_coding_claim(self, claim: Any, results: dict[str, Any], checks: list[BillingQAConsistencyCheck]) -> list[BillingQAIssue]:
        result = results.get("coding")
        if result is None:
            return []
        issues: list[BillingQAIssue] = []
        icd = _value(_value(result, "icd_results"), "normalized_codes", None)
        cpt = _value(_value(result, "cpt_results"), "normalized_codes", None)
        for field, reported, claim_field in (("icd_codes", icd, "icd_codes"), ("cpt_codes", cpt, "cpt_codes")):
            if reported is not None and [str(item).upper() for item in (_value(claim, claim_field) or [])] != reported:
                issues.append(self._issue(BillingQAIssueType.CODING_CONFLICT, BillingQASeverity.MEDIUM, f"Coding Agent {field} differ from claim record", source="coding_agent", field=field, value=reported, details={"claim_value": _value(claim, claim_field)}))
        return issues

    def _check_denial(self, results: dict[str, Any], checks: list[BillingQAConsistencyCheck]) -> list[BillingQAIssue]:
        denial = results.get("denial")
        ar = results.get("ar")
        if denial is not None and _value(denial, "denial_category") is None:
            return [self._issue(BillingQAIssueType.INCOMPLETE_EVIDENCE, BillingQASeverity.MEDIUM, "Denial result does not contain a denial category", source="denial_agent", field="denial_category", value=None)]
        if denial is None or ar is None:
            return []
        category = _value(denial, "denial_category")
        ar_category = _value(ar, "denial_category")
        if category and ar_category and str(category) != str(ar_category):
            return [self._issue(BillingQAIssueType.DENIAL_CATEGORY_CONFLICT, BillingQASeverity.HIGH, "Denial Agent and A/R Agent denial categories conflict", source="denial_agent", field="denial_category", value=str(category), details={"ar_category": str(ar_category)})]
        return []

    def _check_payment(self, claim: Any, results: dict[str, Any], checks: list[BillingQAConsistencyCheck]) -> list[BillingQAIssue]:
        payment = results.get("payment")
        ar = results.get("ar")
        raw = self.payment_lookup(_value(claim, "claim_id")) if self.payment_lookup else None
        if isinstance(raw, (list, tuple)):
            raw = raw[-1] if raw else None
        issues: list[BillingQAIssue] = []
        if payment and raw:
            raw_paid = _decimal(_value(raw, "paid_amount"))
            result_paid = _decimal(_value(payment, "paid_amount"))
            if raw_paid is not None and result_paid is not None and raw_paid != result_paid:
                issues.append(self._issue(BillingQAIssueType.PAYMENT_AMOUNT_CONFLICT, BillingQASeverity.HIGH, "Payment Agent paid amount conflicts with payment record", source="payment_agent", field="paid_amount", value=str(result_paid), details={"payment_record": str(raw_paid)}))
            raw_adjustment = _decimal(_value(raw, "adjustment_amount"))
            raw_billed = _decimal(_value(claim, "claim_amount"))
            raw_balance = _decimal(_value(payment, "unpaid_balance"))
            if raw_billed is not None and raw_paid is not None and raw_adjustment is not None and raw_balance is not None:
                expected_balance = raw_billed - raw_paid - raw_adjustment
                if expected_balance != raw_balance:
                    issues.append(self._issue(BillingQAIssueType.PAYMENT_BALANCE_CONFLICT, BillingQASeverity.HIGH, "Payment Agent balance does not match deterministic financial arithmetic", source="payment_agent", field="unpaid_balance", value=str(raw_balance), details={"expected_balance": str(expected_balance)}))
        if payment and ar:
            payment_balance = _decimal(_value(payment, "unpaid_balance"))
            ar_balance = _decimal(_value(ar, "outstanding_balance"))
            if payment_balance is not None and ar_balance is not None and payment_balance != ar_balance:
                issues.append(self._issue(BillingQAIssueType.PAYMENT_BALANCE_CONFLICT, BillingQASeverity.HIGH, "Payment Agent and A/R Agent balances conflict", source="payment_agent", field="unpaid_balance", value=str(payment_balance), details={"ar_balance": str(ar_balance)}))
            payment_class = _value(payment, "payment_classification")
            ar_class = _value(ar, "payment_classification")
            if payment_class and ar_class and str(payment_class) != str(ar_class):
                issues.append(self._issue(BillingQAIssueType.PAYMENT_CLASSIFICATION_CONFLICT, BillingQASeverity.HIGH, "Payment Agent and A/R Agent classifications conflict", source="payment_agent", field="payment_classification", value=str(payment_class), details={"ar_classification": str(ar_class)}))
        return issues

    def _check_ar(self, claim: Any, results: dict[str, Any], checks: list[BillingQAConsistencyCheck]) -> list[BillingQAIssue]:
        ar = results.get("ar")
        if ar is None:
            return []
        service_date = _value(claim, "service_date")
        if isinstance(service_date, str):
            try:
                service_date = date.fromisoformat(service_date)
            except ValueError:
                service_date = None
        issues: list[BillingQAIssue] = []
        if _value(ar, "aging_bucket") is None:
            issues.append(self._issue(BillingQAIssueType.INCOMPLETE_EVIDENCE, BillingQASeverity.MEDIUM, "A/R result does not contain an aging bucket", source="ar_agent", field="aging_bucket", value=None))
        ar_balance = _decimal(_value(ar, "outstanding_balance"))
        ar_status = str(_value(ar, "ar_status"))
        if ar_balance is not None and ar_balance == 0 and ar_status == "ARStatus.OPEN":
            issues.append(self._issue(BillingQAIssueType.AR_STATUS_CONFLICT, BillingQASeverity.HIGH, "A/R status is OPEN despite a zero outstanding balance", source="ar_agent", field="ar_status", value=ar_status))
        if service_date:
            age = (self.current_date_provider() - service_date).days
            if age >= 0:
                expected = self._aging_bucket(age)
                reported = _value(ar, "aging_bucket")
                if reported and str(reported) != expected.value:
                    issues.append(self._issue(BillingQAIssueType.AR_AGING_BUCKET_CONFLICT, BillingQASeverity.HIGH, "A/R aging bucket conflicts with deterministic age", source="ar_agent", field="aging_bucket", value=str(reported), details={"expected": expected.value, "age_days": age}))
        return issues

    @staticmethod
    def _aging_bucket(age: int) -> AgingBucket:
        if age <= 30: return AgingBucket.CURRENT_0_30
        if age <= 60: return AgingBucket.DAYS_31_60
        if age <= 90: return AgingBucket.DAYS_61_90
        if age <= 120: return AgingBucket.DAYS_91_120
        if age <= 180: return AgingBucket.DAYS_121_180
        if age <= 365: return AgingBucket.DAYS_181_365
        return AgingBucket.DAYS_366_PLUS

    def _check_history_and_policy(self, claim: Any, results: dict[str, Any], checks: list[BillingQAConsistencyCheck]) -> list[BillingQAIssue]:
        issues: list[BillingQAIssue] = []
        if self.claim_history_lookup and not list(self.claim_history_lookup(_value(claim, "claim_id"))):
            checks.append(BillingQAConsistencyCheck(check="claim_history", status=QACheckStatus.NOT_APPLICABLE, description="No synthetic claim history records were provided"))
        return issues

    def _result_evidence(self, results: dict[str, Any]) -> list[BillingQAEvidence]:
        evidence: list[BillingQAEvidence] = []
        for name, result in results.items():
            if result is not None:
                evidence.append(BillingQAEvidence(source=f"{name}_agent", field="result", value="available", description=f"{name} deterministic result was available for QA."))
        return evidence

    @staticmethod
    def _issue(issue_type: BillingQAIssueType, severity: BillingQASeverity, message: str, *, source: str, field: str, value: Any, details: dict[str, Any] | None = None) -> BillingQAIssue:
        return BillingQAIssue(issue_type=issue_type, severity=severity, message=message, source_agents=[source], evidence=[BillingQAEvidence(source=source, field=field, value=value, description="Deterministic QA evidence." )], recommended_action="Review the conflicting or incomplete deterministic evidence.", details=details or {})

    @staticmethod
    def _unique_issues(issues: list[BillingQAIssue]) -> list[BillingQAIssue]:
        seen: set[BillingQAIssueType] = set()
        unique: list[BillingQAIssue] = []
        for issue in issues:
            if issue.issue_type not in seen:
                seen.add(issue.issue_type)
                unique.append(issue)
        return unique

    @staticmethod
    def _priority(issues: list[BillingQAIssue]) -> BillingQAPriority:
        if not issues: return BillingQAPriority.LOW
        highest = max((SCORES[issue.severity] for issue in issues), default=5)
        return BillingQAPriority.CRITICAL if highest == 40 else BillingQAPriority.HIGH if highest == 25 else BillingQAPriority.MEDIUM if highest == 15 else BillingQAPriority.LOW

    def _explain(self, claim: Any, status: BillingQAStatus, priority: BillingQAPriority, issues: list[BillingQAIssue], checks: list[BillingQAConsistencyCheck]) -> tuple[str, list[str], str | None]:
        root = "No material deterministic QA inconsistency was detected." if not issues else "; ".join(issue.message for issue in issues)
        fallback = ["Review the documented deterministic QA findings before modifying any billing or financial record."] if issues else ["No QA follow-up is indicated by the available synthetic evidence."]
        if self.llm_service:
            self._audit("billing_qa_llm_reasoning", _value(claim, "claim_id"), "started")
            try:
                response = self.llm_service.generate_structured(system_instructions="Explain only deterministic QA findings. Do not resolve conflicts or change authoritative evidence, status, priority, financial values, codes, denial categories, or aging.", user_prompt=f"QA status: {status.value}\nPriority: {priority.value}\nIssues: {[issue.model_dump() for issue in issues]}\nChecks: {[check.model_dump() for check in checks]}", response_model=BillingQAExplanation)
                self._audit("billing_qa_llm_reasoning", _value(claim, "claim_id"), "completed")
                return root, response.response.recommendations or fallback, response.response.explanation
            except LLMServiceError:
                self._audit("billing_qa_llm_reasoning", _value(claim, "claim_id"), "failed")
        return root, fallback, None

    def _audit(self, action: str, claim_id: str | None, status: str) -> None:
        if self.audit_sink:
            self.audit_sink(action, {"claim_id": claim_id, "status": status, "source": "synthetic_demo"})
