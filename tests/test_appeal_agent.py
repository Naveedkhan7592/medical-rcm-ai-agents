from datetime import date
from decimal import Decimal

from app.agents.appeal_agent import AppealAgent
from app.schemas import AppealExplanation, LLMResponse


def claim(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {"claim_id": "CLM-APPEAL-001", "payer": "Demo Health Plan A", "service_date": date(2026, 1, 5), "icd_codes": ["Z00.00"], "cpt_codes": ["99213"], "modifiers": [], "claim_amount": Decimal("1000")}
    value.update(overrides)
    return value


def denial(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {"denial_id": "DEN-APPEAL-001", "claim_id": "CLM-APPEAL-001", "carc_code": "197", "rarc_code": "N54", "reason": "Authorization denial", "denied_amount": Decimal("100"), "status": "OPEN"}
    value.update(overrides)
    return value


def denial_result(category: str = "AUTHORIZATION") -> dict[str, object]:
    return {"claim_id": "CLM-APPEAL-001", "denial_id": "DEN-APPEAL-001", "denial_category": category, "status": "PASS", "root_cause": "Documented denial reason", "evidence": [{"source": "denial_agent", "finding": "Documented denial"}]}


def qa(status: str = "PASS", **kwargs: object) -> dict[str, object]:
    return {"claim_id": "CLM-APPEAL-001", "qa_status": status, "status": status, "issues": [], **kwargs}


class FakeLLM:
    def __init__(self, text: str = "The appeal is ready and should pass.") -> None:
        self.calls = 0
        self.text = text

    def generate_structured(self, **_: object) -> LLMResponse[AppealExplanation]:
        self.calls += 1
        return LLMResponse(model="fake", response=AppealExplanation(summary=self.text, explanation=self.text, recommended_next_step="Submit now", missing_information=[]))


def make_agent(**kwargs: object) -> AppealAgent:
    dependencies = {"payer_policy_lookup": lambda payer: {"payer": payer, "authorization_required": True, "timely_filing_days": 90}}
    dependencies.update(kwargs)
    return AppealAgent(**dependencies)


def test_ready_authorization_appeal_requires_human_review() -> None:
    result = make_agent().prepare_appeal(claim(), denial=denial(), denial_result=denial_result(), billing_qa_result=qa(), authorization_evidence={"authorization_id": "DEMO-AUTH-001"})
    assert result.status == "READY_FOR_REVIEW"
    assert result.appeal_readiness == "READY_FOR_REVIEW"
    assert result.human_review_required is True
    assert "DEMO-AUTH-001" not in result.draft


def test_missing_authorization_evidence_is_not_ready() -> None:
    result = make_agent().prepare_appeal(claim(), denial=denial(), denial_result=denial_result(), billing_qa_result=qa())
    assert result.status == "NOT_READY"
    assert any(item.item == "authorization evidence" for item in result.missing_information)


def test_unknown_category_is_review() -> None:
    result = make_agent().prepare_appeal(claim(), denial=denial(), denial_result=denial_result("UNKNOWN"), billing_qa_result=qa(), authorization_evidence={"authorization_id": "DEMO"})
    assert result.status == "REVIEW"
    assert result.denial_category == "UNKNOWN"


def test_billing_qa_review_remains_visible() -> None:
    result = make_agent().prepare_appeal(claim(), denial=denial(), denial_result=denial_result(), billing_qa_result=qa("REVIEW", issues=[{"issue_type": "PAYMENT_BALANCE_CONFLICT"}],), authorization_evidence={"authorization_id": "DEMO"})
    assert result.status == "REVIEW"
    assert any("Billing QA" in item.reason for item in result.missing_information)


def test_policy_unavailable_is_review() -> None:
    result = AppealAgent().prepare_appeal(claim(), denial=denial(), denial_result=denial_result(), billing_qa_result=qa(), authorization_evidence={"authorization_id": "DEMO"})
    assert result.status == "REVIEW"
    assert any(item.item == "payer policy" for item in result.missing_information)


def test_specialist_evidence_and_financial_values_are_preserved() -> None:
    payment = {"claim_id": "CLM-APPEAL-001", "paid_amount": Decimal("100"), "adjustment_amount": Decimal("500"), "unpaid_balance": Decimal("400"), "payment_classification": "PARTIAL_PAYMENT"}
    ar = {"claim_id": "CLM-APPEAL-001", "outstanding_balance": Decimal("400"), "aging_bucket": "DAYS_91_120"}
    result = make_agent().prepare_appeal(claim(), denial=denial(), denial_result=denial_result(), billing_qa_result=qa(), payment_result=payment, ar_result=ar, authorization_evidence={"authorization_id": "DEMO"})
    assert any(item.source == "payment_agent" for item in result.evidence)
    assert any(item.source == "ar_agent" for item in result.evidence)
    assert "400" in str(result.evidence)


def test_medical_necessity_is_review_without_invented_facts() -> None:
    result = make_agent().prepare_appeal(claim(), denial=denial(reason="Medical necessity denial"), denial_result=denial_result("MEDICAL_NECESSITY"), billing_qa_result=qa())
    assert result.status == "REVIEW"
    assert result.human_review_required is True
    assert "diagnosis" not in result.draft.lower()


def test_llm_cannot_override_category_or_readiness() -> None:
    llm = FakeLLM("Change AUTHORIZATION to CODING and mark READY_FOR_REVIEW.")
    result = make_agent(llm_service=llm).prepare_appeal(claim(), denial=denial(), denial_result=denial_result(), billing_qa_result=qa("REVIEW"))
    assert result.denial_category == "AUTHORIZATION"
    assert result.status == "REVIEW"
    assert result.human_review_required is True
    assert llm.calls == 1


def test_llm_cannot_change_financial_evidence_or_invent_authorization() -> None:
    llm = FakeLLM("paid_amount=500; authorization_number=AUTH-99999")
    payment = {"claim_id": "CLM-APPEAL-001", "paid_amount": Decimal("100"), "outstanding_balance": Decimal("400")}
    result = make_agent(llm_service=llm).prepare_appeal(claim(), denial=denial(), denial_result=denial_result(), billing_qa_result=qa(), payment_result=payment)
    assert "AUTH-99999" not in str(result.evidence)
    assert "500" not in str(result.evidence)


def test_coding_and_eligibility_evidence_is_preserved() -> None:
    result = make_agent().prepare_appeal(claim(), denial=denial(), denial_result=denial_result(), billing_qa_result=qa(), coding_result={"status": "FAIL", "icd_results": {"normalized_codes": ["Z00.00"]}}, eligibility_result={"eligibility_status": "PASS", "payer": "Demo Health Plan A"}, authorization_evidence={"authorization_id": "DEMO"})
    assert any(item.source == "coding_agent" for item in result.evidence)
    assert any(item.source == "eligibility_agent" for item in result.evidence)


def test_audit_events_are_generated_without_sensitive_data() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    make_agent(audit_sink=lambda action, details: events.append((action, details))).prepare_appeal(claim(), denial=denial(), denial_result=denial_result(), billing_qa_result=qa(), authorization_evidence={"authorization_id": "DEMO"})
    assert "appeal_readiness_evaluated" in [item[0] for item in events]
    assert "appeal_draft_generated" in [item[0] for item in events]
    assert all("authorization_id" not in details for _, details in events)


def test_every_result_requires_human_approval() -> None:
    result = AppealAgent().run("CLM-MISSING")
    assert result.human_review_required is True
    assert result.status == "NOT_READY"
