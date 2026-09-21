from decimal import Decimal

from app.agents.denial_agent import DenialAgent
from app.schemas import DenialExplanation, LLMResponse


def denial(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "denial_id": "DEN-TEST-001",
        "claim_id": "CLM-TEST-001",
        "carc_code": "27",
        "rarc_code": "N30",
        "reason": "Eligibility denial: synthetic coverage requires verification.",
        "denied_amount": Decimal("100.00"),
        "status": "OPEN",
    }
    record.update(overrides)
    return record


def claim(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "claim_id": "CLM-TEST-001",
        "payer": "Demo Health Plan A",
        "service_date": "2026-01-05",
        "status": "DENIED",
    }
    record.update(overrides)
    return record


class FakeLLM:
    def __init__(self, root_cause: str = "Deterministic root cause.") -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.root_cause = root_cause

    def generate_structured(self, *, user_prompt: str, **_: object) -> LLMResponse[DenialExplanation]:
        self.calls += 1
        self.prompts.append(user_prompt)
        return LLMResponse(
            model="fake-model",
            response=DenialExplanation(
                root_cause=self.root_cause,
                explanation="Evidence was summarized.",
                recommendations=["Review the documented evidence."],
                missing_information=[],
            ),
        )


def make_agent(**kwargs: object) -> DenialAgent:
    return DenialAgent(
        claim_lookup=lambda claim_id: claim(claim_id=claim_id),
        denial_lookup=lambda denial_id: denial(denial_id=denial_id),
        claim_history_lookup=lambda claim_id: [{"claim_id": claim_id, "status": "DENIED"}],
        **kwargs,
    )


def test_denial_categories_are_classified_deterministically() -> None:
    cases = [
        ("27", "N30", "Eligibility denial", "ELIGIBILITY"),
        ("197", "N54", "Authorization denial", "AUTHORIZATION"),
        ("11", "N56", "Coding denial", "CODING"),
        ("50", "N386", "Medical necessity denial", "MEDICAL_NECESSITY"),
        ("18", "N111", "Duplicate claim", "DUPLICATE"),
        ("29", "N29", "Timely filing denial", "TIMELY_FILING"),
        ("16", "N265", "Missing documentation", "MISSING_DOCUMENTATION"),
        ("96", "N211", "Payer processing issue", "PAYER_PROCESSING"),
    ]
    for carc, rarc, reason, expected in cases:
        result = make_agent().analyze_denial(denial(carc_code=carc, rarc_code=rarc, reason=reason))
        assert result.denial_category == expected


def test_coordination_of_benefits_reason_is_supported() -> None:
    result = make_agent().analyze_denial(denial(carc_code="X-DEMO", rarc_code="Y-DEMO", reason="Coordination of benefits requires review"))
    assert result.denial_category == "COORDINATION_OF_BENEFITS"
    assert result.status == "REVIEW"


def test_unknown_code_and_reason_remain_unknown() -> None:
    result = make_agent().analyze_denial(denial(carc_code="UNKNOWN", rarc_code="UNKNOWN", reason="Unmapped synthetic denial"))
    assert result.denial_category == "UNKNOWN"
    assert result.status == "REVIEW"
    assert any("not mapped" in issue for issue in result.missing_information)


def test_carc_rarc_facts_are_preserved_as_evidence() -> None:
    result = make_agent().analyze_denial(denial(carc_code="27", rarc_code="N30"))
    assert result.carc_code == "27"
    assert result.rarc_code == "N30"
    evidence = next(item for item in result.evidence if item.type == "denial_record")
    assert evidence.source == "synthetic_denial_data"
    assert evidence.details == {"carc_code": "27", "rarc_code": "N30"}


def test_claim_history_and_policy_evidence_are_traceable() -> None:
    result = make_agent().analyze_denial(denial(carc_code="197", rarc_code="N54", reason="Authorization denial"))
    assert any(item.source == "synthetic_claim_history" for item in result.evidence)
    assert any(item.source == "synthetic_payer_policy" for item in result.evidence)


def test_medical_necessity_requires_review() -> None:
    result = make_agent().analyze_denial(denial(carc_code="50", rarc_code="N386", reason="Medical necessity denial"))
    assert result.status == "REVIEW"
    assert result.requires_human_review is True


def test_mapped_deterministic_denial_analysis_can_pass() -> None:
    result = make_agent().analyze_denial(denial(carc_code="27", rarc_code="N30", reason="Eligibility denial"))
    assert result.status == "PASS"
    assert result.requires_human_review is False


def test_conflicting_evidence_is_review() -> None:
    result = make_agent().analyze_denial(denial(carc_code="29", rarc_code="N29", reason="Eligibility denial"))
    assert result.denial_category == "UNKNOWN"
    assert result.status == "REVIEW"
    assert any(issue.rule == "conflicting_evidence" for issue in result.issues)


def test_llm_cannot_override_category() -> None:
    llm = FakeLLM("This is actually an eligibility denial.")
    result = make_agent(llm_service=llm).analyze_denial(denial(carc_code="29", rarc_code="N29", reason="Timely filing denial"))
    assert result.denial_category == "TIMELY_FILING"
    assert llm.calls == 1


def test_llm_receives_deterministic_evidence_for_review() -> None:
    llm = FakeLLM()
    result = make_agent(llm_service=llm).analyze_denial(denial(carc_code="50", rarc_code="N386", reason="Medical necessity denial"))
    assert result.status == "REVIEW"
    assert llm.calls == 1
    assert "MEDICAL_NECESSITY" in llm.prompts[0]
    assert "synthetic" in llm.prompts[0].lower()


def test_llm_cannot_invent_policy_or_code_meaning() -> None:
    llm = FakeLLM("The payer allows 365 days and UNKNOWN means authorization.")
    result = make_agent(llm_service=llm).analyze_denial(denial(carc_code="UNKNOWN", rarc_code="UNKNOWN", reason="Unmapped synthetic denial"))
    assert result.denial_category == "UNKNOWN"
    assert not any("365" in item.details.get("timely_filing_days", "") for item in result.evidence)
    assert all(item.details.get("carc_code") == "UNKNOWN" for item in result.evidence if item.type == "denial_code")


def test_llm_cannot_invent_clinical_facts() -> None:
    llm = FakeLLM("The patient has an invented diagnosis.")
    result = make_agent(llm_service=llm).analyze_denial(denial(carc_code="50", rarc_code="N386", reason="Medical necessity denial"))
    assert all("diagnosis" not in item.finding.lower() for item in result.evidence)


def test_llm_cannot_replace_deterministic_root_cause() -> None:
    llm = FakeLLM("Invented deterministic root cause.")
    result = make_agent(llm_service=llm).analyze_denial(denial(carc_code="29", rarc_code="N29", reason="Timely filing denial"))
    assert result.root_cause == "Timely filing denial"


def test_dependency_injection_and_audit_events() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    result = make_agent(audit_sink=lambda action, details: events.append((action, details))).run("DEN-INJECTED")
    assert result.denial_id == "DEN-INJECTED"
    assert [action for action, _ in events] == [
        "denial_check_started",
        "denial_loaded",
        "denial_codes_evaluated",
        "denial_evidence_collected",
        "denial_policy_checked",
        "denial_root_cause_analyzed",
        "denial_result_generated",
    ]
    assert all("member_id" not in details for _, details in events)


def test_missing_claim_is_review_not_fabricated() -> None:
    agent = DenialAgent(denial_lookup=lambda denial_id: denial(carc_code="27", rarc_code="N30"), claim_lookup=lambda claim_id: None)
    result = agent.run("DEN-MISSING-CLAIM")
    assert result.status == "REVIEW"
    assert any("claim" in info.lower() for info in result.missing_information)
