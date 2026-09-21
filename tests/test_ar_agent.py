from datetime import date, timedelta
from decimal import Decimal

from app.agents.ar_agent import ARAgent
from app.schemas import (
    DenialCategory,
    DenialStatus,
    PaymentExplanation,
    PaymentStatus,
    LLMResponse,
    ARExplanation,
)
from app.agents.payment_agent import PaymentAgent


CURRENT_DATE = date(2026, 1, 31)


def claim(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "claim_id": "CLM-AR-001",
        "claim_amount": Decimal("1000.00"),
        "payer": "Demo Health Plan A",
        "service_date": date(2026, 1, 21),
        "status": "SUBMITTED",
    }
    value.update(overrides)
    return value


def payment(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "payment_id": "PAY-AR-001",
        "claim_id": "CLM-AR-001",
        "payer": "Demo Health Plan A",
        "allowed_amount": Decimal("1000.00"),
        "paid_amount": Decimal("1000.00"),
        "adjustment_amount": Decimal("0.00"),
        "patient_responsibility": Decimal("0.00"),
        "status": "POSTED",
    }
    value.update(overrides)
    return value


def payment_agent_for(payment_record: dict[str, object]) -> PaymentAgent:
    return PaymentAgent(claim_lookup=lambda claim_id: claim(claim_id=claim_id))


def make_agent(payment_record: dict[str, object] | None = None, **kwargs: object) -> ARAgent:
    dependencies: dict[str, object] = {
        "claim_lookup": lambda claim_id: claim(claim_id=claim_id),
        "payment_lookup": lambda claim_id: payment_record,
        "payment_agent": payment_agent_for(payment_record) if payment_record else None,
        "current_date_provider": lambda: CURRENT_DATE,
    }
    dependencies.update(kwargs)
    return ARAgent(**dependencies)


class FakeLLM:
    def __init__(self, text: str = "LLM suggestion.") -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.text = text

    def generate_structured(self, *, user_prompt: str, **_: object) -> LLMResponse[ARExplanation]:
        self.calls += 1
        self.prompts.append(user_prompt)
        return LLMResponse(model="fake-model", response=ARExplanation(root_cause="LLM root cause", explanation=self.text, recommendations=["Review evidence."], missing_information=[]))


class FakeDenialAgent:
    def __init__(self, category: DenialCategory = DenialCategory.TIMELY_FILING, status: DenialStatus = DenialStatus.REVIEW) -> None:
        self.category = category
        self.status = status

    def analyze_denial(self, denial: object) -> object:
        return type("DenialResult", (), {"denial_category": self.category, "status": self.status, "requires_human_review": True})()


def test_outstanding_balance_uses_payment_agent_decimal_result() -> None:
    result = make_agent(payment(paid_amount=Decimal("500"), adjustment_amount=Decimal("200"), patient_responsibility=Decimal("300"))).analyze_ar(claim())
    assert result.outstanding_balance == Decimal("300")
    assert result.balance_state == "CALCULATED"
    assert result.ar_status == "OPEN"


def test_resolved_balance_is_pass() -> None:
    result = make_agent(payment()).analyze_ar(claim())
    assert result.outstanding_balance == Decimal("0.00")
    assert result.ar_status == "RESOLVED"
    assert result.status == "PASS"
    assert result.requires_human_review is False


def test_missing_payment_data_is_incomplete_review() -> None:
    result = make_agent(None).analyze_ar(claim())
    assert result.balance_state == "INCOMPLETE"
    assert result.ar_status == "INCOMPLETE"
    assert result.requires_human_review is True
    assert "payment_data" in {issue.rule for issue in result.issues}


def test_age_uses_injected_current_date() -> None:
    result = make_agent(payment()).analyze_ar(claim(service_date=date(2025, 10, 23)))
    assert result.ar_age_days == 100
    assert result.aging_bucket == "DAYS_91_120"


def test_all_aging_boundaries() -> None:
    expected = {
        0: "CURRENT_0_30", 30: "CURRENT_0_30", 31: "DAYS_31_60", 60: "DAYS_31_60",
        61: "DAYS_61_90", 90: "DAYS_61_90", 91: "DAYS_91_120", 120: "DAYS_91_120",
        121: "DAYS_121_180", 180: "DAYS_121_180", 181: "DAYS_181_365", 365: "DAYS_181_365", 366: "DAYS_366_PLUS",
    }
    for age, bucket in expected.items():
        result = make_agent(payment()).analyze_ar(claim(service_date=CURRENT_DATE - timedelta(days=age)))
        assert result.ar_age_days == age
        assert result.aging_bucket.value == bucket


def test_future_service_date_is_review_and_invalid_bucket() -> None:
    result = make_agent(payment()).analyze_ar(claim(service_date=date(2026, 2, 1)))
    assert result.ar_age_days == -1
    assert result.aging_bucket == "INVALID"
    assert result.status == "REVIEW"
    assert any(issue.rule == "future_service_date" for issue in result.issues)


def test_denial_category_and_review_state_are_preserved() -> None:
    agent = make_agent(payment(), denial_lookup=lambda claim_id: {"denial_id": "DEN-AR-001"}, denial_agent=FakeDenialAgent())
    result = agent.analyze_ar(claim())
    assert result.denial_category == DenialCategory.TIMELY_FILING
    assert result.denial_status == DenialStatus.REVIEW
    assert result.denial_context.value == "DENIAL_REQUIRES_REVIEW"
    assert any(item.source == "denial_agent" for item in result.evidence)


def test_payment_classification_is_preserved() -> None:
    result = make_agent(payment(paid_amount=Decimal("500"), adjustment_amount=Decimal("200"), patient_responsibility=Decimal("300"))).analyze_ar(claim())
    assert result.payment_classification == "PARTIAL_PAYMENT"
    assert any(item.source == "payment_agent" for item in result.evidence)


def test_history_and_policy_evidence_are_present() -> None:
    result = make_agent(payment(), claim_history_lookup=lambda claim_id: [{"status": "SUBMITTED"}, {"status": "PAID"}]).analyze_ar(claim())
    assert any(item.source == "claim_history" for item in result.evidence)
    assert any(item.source == "payer_policy" for item in result.evidence)


def test_unknown_payer_policy_is_review() -> None:
    result = make_agent(payment(payer="Unknown Payer")).analyze_ar(claim(payer="Unknown Payer"))
    assert result.policy_status == "UNKNOWN"
    assert result.status == "REVIEW"


def test_priority_is_deterministic_and_explained() -> None:
    result = make_agent(payment(paid_amount=Decimal("500"), adjustment_amount=Decimal("200"), patient_responsibility=Decimal("300"))).analyze_ar(claim(service_date=date(2025, 8, 1)))
    assert result.priority == "HIGH"
    assert result.priority_reasons
    assert any("age" in reason.lower() for reason in result.priority_reasons)


def test_work_queue_recommendations() -> None:
    denial = make_agent(payment(), denial_lookup=lambda claim_id: {"denial_id": "DEN-1"}, denial_agent=FakeDenialAgent(DenialCategory.CODING)).analyze_ar(claim())
    assert denial.recommended_work_type == "REVIEW_CODING"
    payment_result = make_agent(payment(paid_amount=Decimal("500"), adjustment_amount=Decimal("200"), patient_responsibility=Decimal("300"))).analyze_ar(claim())
    assert payment_result.recommended_work_type == "INVESTIGATE_PAYMENT"
    incomplete = make_agent(None).analyze_ar(claim())
    assert incomplete.recommended_work_type == "HUMAN_FINANCIAL_REVIEW"


def test_llm_cannot_change_balance_age_bucket_or_priority() -> None:
    llm = FakeLLM("Balance 0, age 30, CURRENT_0_30, priority LOW")
    result = make_agent(payment(paid_amount=Decimal("500"), adjustment_amount=Decimal("200"), patient_responsibility=Decimal("300")), llm_service=llm).analyze_ar(claim(service_date=date(2025, 10, 23)))
    assert result.outstanding_balance == Decimal("300")
    assert result.ar_age_days == 100
    assert result.aging_bucket == "DAYS_91_120"
    assert result.priority == "MEDIUM"
    assert llm.calls == 1


def test_llm_cannot_override_denial_or_payment_context() -> None:
    llm = FakeLLM("Denial is eligibility and payment is PAID")
    result = make_agent(payment(paid_amount=Decimal("0"), adjustment_amount=Decimal("0"), patient_responsibility=Decimal("1000")), denial_lookup=lambda claim_id: {"denial_id": "DEN-1"}, denial_agent=FakeDenialAgent(), llm_service=llm).analyze_ar(claim())
    assert result.denial_category == DenialCategory.TIMELY_FILING
    assert result.payment_classification == "ZERO_PAYMENT"


def test_llm_cannot_invent_policy_and_no_network_required() -> None:
    llm = FakeLLM("Payer requires follow-up after 45 days")
    result = make_agent(payment(), llm_service=llm).analyze_ar(claim())
    assert result.policy_status == "FOUND"
    assert all("45" not in str(item.value) for item in result.evidence if item.source == "payer_policy")


def test_audit_events_are_concise() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    make_agent(payment(), audit_sink=lambda action, details: events.append((action, details))).analyze_ar(claim())
    assert "ar_check_started" == events[0][0]
    assert "ar_balance_calculated" in [action for action, _ in events]
    assert "ar_result_generated" == events[-1][0]
    assert all("member_id" not in details for _, details in events)


def test_run_uses_claim_lookup_and_fixed_clock() -> None:
    result = ARAgent(claim_lookup=lambda claim_id: claim(claim_id=claim_id), payment_lookup=lambda claim_id: payment(), payment_agent=payment_agent_for(payment()), current_date_provider=lambda: CURRENT_DATE).run("CLM-RUN")
    assert result.claim_id == "CLM-RUN"
