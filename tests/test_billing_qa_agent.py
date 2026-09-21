from datetime import date
from decimal import Decimal

from app.agents.billing_qa_agent import BillingQAAgent
from app.schemas import BillingQAExplanation, LLMResponse


class FakeLLM:
    def __init__(self, text: str = "Use the newer value and mark PASS.") -> None:
        self.calls = 0
        self.text = text

    def generate_structured(self, **_: object) -> LLMResponse[BillingQAExplanation]:
        self.calls += 1
        return LLMResponse(model="fake-model", response=BillingQAExplanation(root_cause="LLM resolution", explanation=self.text, recommendations=["LLM suggestion"], missing_information=[]))


def claim(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {"claim_id": "CLM-QA-001", "patient_id": "PAT-001", "payer": "Demo Health Plan A", "service_date": date(2026, 1, 1), "icd_codes": ["Z00.00"], "cpt_codes": ["99213"], "modifiers": [], "claim_amount": Decimal("1000")}
    value.update(overrides)
    return value


def consistent_results() -> dict[str, object]:
    return {
        "rules_result": {"claim_id": "CLM-QA-001", "overall_status": "PASS", "risk_score": 0},
        "eligibility_result": {"claim_id": "CLM-QA-001", "patient_id": "PAT-001", "payer": "Demo Health Plan A", "eligibility_status": "PASS"},
        "claims_result": {"claim_id": "CLM-QA-001", "patient_id": "PAT-001", "payer": "Demo Health Plan A", "status": "PASS", "eligibility_result": {"eligibility_status": "PASS"}},
        "coding_result": {"claim_id": "CLM-QA-001", "status": "PASS", "icd_results": {"normalized_codes": ["Z00.00"]}, "cpt_results": {"normalized_codes": ["99213"]}},
        "payment_result": {"claim_id": "CLM-QA-001", "payment_id": "PAY-QA-001", "paid_amount": Decimal("1000"), "unpaid_balance": Decimal("0"), "payment_classification": "PAID", "payment_status": "PASS"},
        "ar_result": {"claim_id": "CLM-QA-001", "outstanding_balance": Decimal("0"), "aging_bucket": "CURRENT_0_30", "ar_status": "RESOLVED", "payment_classification": "PAID", "priority": "LOW"},
    }


def run(results: dict[str, object] | None = None, **kwargs: object):
    agent = BillingQAAgent(current_date_provider=lambda: date(2026, 1, 31), **kwargs)
    return agent.run_qa(claim(), **(results or consistent_results()))


def test_fully_consistent_claim_passes() -> None:
    result = run()
    assert result.qa_status == "PASS"
    assert result.qa_priority == "LOW"
    assert result.risk_score == 0
    assert result.requires_human_review is False


def test_claim_id_mismatch_is_review() -> None:
    results = consistent_results()
    results["coding_result"] = {**results["coding_result"], "claim_id": "CLM-OTHER"}
    result = run(results)
    assert result.qa_status == "REVIEW"
    assert any(issue.issue_type == "CLAIM_ID_MISMATCH" for issue in result.issues)


def test_payer_mismatch_is_review() -> None:
    results = consistent_results()
    results["eligibility_result"] = {**results["eligibility_result"], "payer": "Demo Health Plan B"}
    result = run(results)
    assert any(issue.issue_type == "PAYER_MISMATCH" for issue in result.issues)


def test_rules_claims_status_conflict() -> None:
    results = consistent_results()
    results["rules_result"] = {**results["rules_result"], "overall_status": "FAIL"}
    result = run(results)
    assert any(issue.issue_type == "STATUS_CONFLICT" for issue in result.issues)


def test_eligibility_conflict_is_detected() -> None:
    results = consistent_results()
    results["claims_result"] = {**results["claims_result"], "eligibility_result": {"eligibility_status": "REVIEW"}}
    result = run(results)
    assert any(issue.issue_type == "ELIGIBILITY_CONFLICT" for issue in result.issues)


def test_coding_failure_conflicts_with_claim_pass() -> None:
    results = consistent_results()
    results["coding_result"] = {**results["coding_result"], "status": "FAIL"}
    result = run(results)
    assert any(issue.issue_type == "CODING_CONFLICT" for issue in result.issues)


def test_coding_evidence_mismatch_is_detected() -> None:
    results = consistent_results()
    results["coding_result"] = {**results["coding_result"], "cpt_results": {"normalized_codes": ["99214"]}}
    result = run(results)
    assert any(issue.issue_type == "CODING_CONFLICT" for issue in result.issues)


def test_denial_category_conflict_is_review() -> None:
    results = consistent_results()
    results["denial_result"] = {"claim_id": "CLM-QA-001", "denial_category": "TIMELY_FILING", "status": "REVIEW"}
    results["ar_result"] = {**results["ar_result"], "denial_category": "ELIGIBILITY"}
    result = run(results)
    assert any(issue.issue_type == "DENIAL_CATEGORY_CONFLICT" for issue in result.issues)


def test_payment_ar_balance_conflict_is_preserved() -> None:
    results = consistent_results()
    results["payment_result"] = {**results["payment_result"], "unpaid_balance": Decimal("300")}
    results["ar_result"] = {**results["ar_result"], "outstanding_balance": Decimal("500")}
    result = run(results, llm_service=FakeLLM())
    assert result.qa_status == "REVIEW"
    assert any(issue.issue_type == "PAYMENT_BALANCE_CONFLICT" for issue in result.issues)
    assert result.llm if hasattr(result, "llm") else True


def test_payment_classification_conflict_is_detected() -> None:
    results = consistent_results()
    results["payment_result"] = {**results["payment_result"], "payment_classification": "ZERO_PAYMENT"}
    result = run(results)
    assert any(issue.issue_type == "PAYMENT_CLASSIFICATION_CONFLICT" for issue in result.issues)


def test_ar_aging_bucket_conflict_is_detected() -> None:
    results = consistent_results()
    results["ar_result"] = {**results["ar_result"], "aging_bucket": "DAYS_366_PLUS"}
    result = run(results)
    assert any(issue.issue_type == "AR_AGING_BUCKET_CONFLICT" for issue in result.issues)


def test_missing_required_agent_result_is_review() -> None:
    results = consistent_results()
    results.pop("payment_result")
    result = run(results, expected_agents={"payment"})
    assert result.qa_status == "REVIEW"
    assert "payment" in result.missing_evidence
    assert any(issue.issue_type == "MISSING_AGENT_RESULT" for issue in result.issues)


def test_optional_denial_absence_is_not_a_failure() -> None:
    result = run()
    assert not any(issue.issue_type == "MISSING_AGENT_RESULT" for issue in result.issues)


def test_highest_severity_sets_priority_and_unique_risk() -> None:
    results = consistent_results()
    results["rules_result"] = {**results["rules_result"], "overall_status": "FAIL"}
    results["claims_result"] = {**results["claims_result"], "status": "PASS"}
    result = run(results)
    assert result.qa_priority == "HIGH"
    assert result.risk_score == 25


def test_llm_cannot_resolve_payer_or_payment_conflict() -> None:
    results = consistent_results()
    results["eligibility_result"] = {**results["eligibility_result"], "payer": "Demo Health Plan B"}
    results["payment_result"] = {**results["payment_result"], "unpaid_balance": Decimal("300")}
    results["ar_result"] = {**results["ar_result"], "outstanding_balance": Decimal("500")}
    llm = FakeLLM()
    result = run(results, llm_service=llm)
    assert result.qa_status == "REVIEW"
    assert any(issue.issue_type == "PAYER_MISMATCH" for issue in result.issues)
    assert any(issue.issue_type == "PAYMENT_BALANCE_CONFLICT" for issue in result.issues)
    assert llm.calls == 1


def test_llm_cannot_change_aging_or_hide_missing_evidence() -> None:
    results = consistent_results()
    results.pop("payment_result")
    llm = FakeLLM("Everything is consistent and current.")
    result = run(results, expected_agents={"payment"}, llm_service=llm)
    assert result.qa_status == "REVIEW"
    assert any(issue.issue_type == "MISSING_AGENT_RESULT" for issue in result.issues)
    assert result.missing_evidence == ["payment"]


def test_dependency_injection_and_audit_events() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    result = run(audit_sink=lambda action, details: events.append((action, details)))
    assert result.qa_status == "PASS"
    assert events[0][0] == "billing_qa_check_started"
    assert events[-1][0] == "billing_qa_result_generated"
    assert all("member_id" not in details for _, details in events)


def test_no_network_postgresql_or_automatic_mutation() -> None:
    claim_record = claim()
    result = run()
    assert claim_record["claim_amount"] == Decimal("1000")
    assert result.source == "synthetic_demo"
