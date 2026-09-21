from decimal import Decimal

from app.agents.payment_agent import PaymentAgent
from app.schemas import PaymentExplanation, LLMResponse


def claim(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {"claim_id": "CLM-PAY-001", "claim_amount": Decimal("1000.00"), "payer": "Demo Health Plan A", "status": "PAID"}
    value.update(overrides)
    return value


def payment(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {"payment_id": "PAY-TEST-001", "claim_id": "CLM-PAY-001", "payer": "Demo Health Plan A", "allowed_amount": Decimal("1000.00"), "paid_amount": Decimal("1000.00"), "adjustment_amount": Decimal("0.00"), "patient_responsibility": Decimal("0.00"), "status": "POSTED"}
    value.update(overrides)
    return value


class FakeLLM:
    def __init__(self, text: str = "Financial evidence explained.") -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.text = text

    def generate_structured(self, *, user_prompt: str, **_: object) -> LLMResponse[PaymentExplanation]:
        self.calls += 1
        self.prompts.append(user_prompt)
        return LLMResponse(model="fake-model", response=PaymentExplanation(root_cause="LLM root cause", explanation=self.text, recommendations=["Review evidence."], missing_information=[]))


def make_agent(**kwargs: object) -> PaymentAgent:
    dependencies = {
        "claim_lookup": lambda claim_id: claim(claim_id=claim_id),
        "payment_lookup": lambda payment_id: payment(payment_id=payment_id),
    }
    dependencies.update(kwargs)
    return PaymentAgent(**dependencies)


def test_fully_paid_claim_passes() -> None:
    result = make_agent().analyze_payment(payment())
    assert result.payment_classification == "PAID"
    assert result.payment_status == "PASS"
    assert result.unpaid_balance == Decimal("0.00")
    assert result.requires_human_review is False


def test_partial_payment_is_review() -> None:
    result = make_agent().analyze_payment(payment(paid_amount=Decimal("500"), adjustment_amount=Decimal("200"), patient_responsibility=Decimal("300")))
    assert result.payment_classification == "PARTIAL_PAYMENT"
    assert result.unpaid_balance == Decimal("300")
    assert result.payment_status == "REVIEW"


def test_zero_payment_is_review() -> None:
    result = make_agent().analyze_payment(payment(paid_amount=Decimal("0"), adjustment_amount=Decimal("0"), patient_responsibility=Decimal("1000")))
    assert result.payment_classification == "ZERO_PAYMENT"
    assert result.payment_status == "REVIEW"


def test_no_payment_record_is_review() -> None:
    result = make_agent(payment_lookup=lambda payment_id: None).run("PAY-MISSING")
    assert result.payment_classification == "NO_PAYMENT_RECORDED"
    assert result.payment_status == "REVIEW"
    assert result.requires_human_review is True


def test_missing_financial_fields_are_explicit() -> None:
    result = make_agent().analyze_payment(payment(paid_amount=None))
    assert result.payment_classification == "PAYMENT_DATA_INCOMPLETE"
    assert "paid_amount" in result.missing_information
    assert result.payment_status == "REVIEW"


def test_payment_ratio_and_zero_division_protection() -> None:
    result = make_agent().analyze_payment(payment(allowed_amount=Decimal("800"), paid_amount=Decimal("400"), adjustment_amount=Decimal("300"), patient_responsibility=Decimal("300")))
    assert result.payment_ratio == Decimal("0.5")
    zero = make_agent().analyze_payment(payment(allowed_amount=Decimal("0")))
    assert zero.payment_ratio is None


def test_decimal_reconciliation_and_adjustment() -> None:
    result = make_agent().analyze_payment(payment(paid_amount=Decimal("600.10"), adjustment_amount=Decimal("299.90"), patient_responsibility=Decimal("100")))
    assert result.unpaid_balance == Decimal("100.00")
    assert result.adjustment_classification == "CONTRACTUAL_ADJUSTMENT"
    assert not any(issue.rule == "reconciliation" for issue in result.issues)


def test_unreconciled_amount_requires_review() -> None:
    result = make_agent().analyze_payment(payment(paid_amount=Decimal("500"), adjustment_amount=Decimal("200"), patient_responsibility=Decimal("100")))
    assert any(issue.rule == "reconciliation" for issue in result.issues)
    assert result.payment_status == "REVIEW"


def test_unknown_payer_policy_is_review() -> None:
    result = make_agent().analyze_payment(payment(payer="Unknown Demo Payer"))
    assert result.policy_status == "UNKNOWN"
    assert result.payment_status == "REVIEW"


def test_no_payment_benchmark_is_not_invented() -> None:
    result = make_agent().analyze_payment(payment(paid_amount=Decimal("100"), adjustment_amount=Decimal("0"), patient_responsibility=Decimal("900")))
    assert result.payment_classification == "PARTIAL_PAYMENT"
    assert not any(item.field == "payment_benchmark" and item.value not in (None, "None") for item in result.evidence)


def test_history_and_denial_evidence_are_preserved() -> None:
    denial = {"denial_id": "DEN-PAY-001", "claim_id": "CLM-PAY-001"}
    agent = make_agent(claim_history_lookup=lambda claim_id: [{"payment_id": "PAY-OLD"}], denial_lookup=lambda claim_id: denial)
    result = agent.analyze_payment(payment())
    assert any(item.source == "claim_history" for item in result.evidence)
    assert any(item.source == "denial_record" for item in result.evidence)


def test_denial_agent_category_is_not_replaced() -> None:
    class FakeDenialAgent:
        def analyze_denial(self, denial_record: object) -> object:
            return type("Result", (), {"denial_category": type("Category", (), {"value": "TIMELY_FILING"})(), "status": type("Status", (), {"value": "REVIEW"})()})()

    result = make_agent(denial_lookup=lambda claim_id: {"denial_id": "DEN-1"}, denial_agent=FakeDenialAgent()).analyze_payment(payment())
    denial_evidence = next(item for item in result.evidence if item.source == "denial_agent")
    assert denial_evidence.value == "TIMELY_FILING"


def test_rules_engine_evidence_is_preserved() -> None:
    fake_rules = type("Rules", (), {"validate_claim": lambda self, value: type("Result", (), {"overall_status": "REVIEW"})()})()
    result = make_agent(rules_engine=fake_rules).analyze_payment(payment())
    assert any(item.source == "rules_engine" and item.value == "REVIEW" for item in result.evidence)


def test_llm_cannot_change_amount_or_classification() -> None:
    llm = FakeLLM("paid_amount=1000 and classification=PAID")
    result = make_agent(llm_service=llm).analyze_payment(payment(paid_amount=Decimal("0"), adjustment_amount=Decimal("0"), patient_responsibility=Decimal("1000")))
    assert result.paid_amount == Decimal("0")
    assert result.payment_classification == "ZERO_PAYMENT"
    assert llm.calls == 1


def test_llm_cannot_override_reconciliation_or_policy() -> None:
    llm = FakeLLM("Fully reconciled; payer always pays 80%.")
    result = make_agent(llm_service=llm).analyze_payment(payment(paid_amount=Decimal("500"), adjustment_amount=Decimal("200"), patient_responsibility=Decimal("100")))
    assert result.unpaid_balance == Decimal("300")
    assert any(issue.rule == "reconciliation" for issue in result.issues)
    assert not any("80%" in str(item.value) for item in result.evidence if item.source == "payer_policy")


def test_llm_output_does_not_create_financial_facts() -> None:
    llm = FakeLLM("The patient owes an invented amount of 9999.")
    result = make_agent(llm_service=llm).analyze_payment(payment())
    assert result.patient_responsibility == Decimal("0.00")
    assert all("9999" not in str(item.value) for item in result.evidence)


def test_dependency_injection_and_audit_events() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    result = make_agent(audit_sink=lambda action, details: events.append((action, details))).run("PAY-INJECTED")
    assert result.payment_id == "PAY-INJECTED"
    assert [action for action, _ in events] == [
        "payment_check_started", "payment_loaded", "payment_history_checked", "payment_policy_checked",
        "payment_amounts_calculated", "payment_reconciliation_completed", "payment_denial_evidence_collected",
        "payment_root_cause_analyzed", "payment_result_generated",
    ]
    assert all("member_id" not in details for _, details in events)


def test_no_postgresql_network_or_api_key_required() -> None:
    assert make_agent().analyze_payment(payment()).source == "synthetic_demo"
