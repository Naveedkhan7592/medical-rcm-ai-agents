from types import SimpleNamespace

from app.agents.coding_agent import CodingAgent
from app.schemas import CodingExplanation, CodingIssue, CodingIssueCategory, CodingSeverity, CodingStatus, LLMResponse
from app.services.coding_validation import CodingValidationService


def claim(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "claim_id": "CLM-CODING-001",
        "payer": "Demo Health Plan A",
        "icd_codes": ["Z00.00"],
        "cpt_codes": ["99213"],
        "modifiers": [],
    }
    value.update(overrides)
    return value


class FakeLLM:
    def __init__(self, text: str = "Deterministic coding findings explained.") -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.text = text

    def generate_structured(self, *, user_prompt: str, **_: object) -> LLMResponse[CodingExplanation]:
        self.calls += 1
        self.prompts.append(user_prompt)
        return LLMResponse(
            model="fake-model",
            response=CodingExplanation(explanation=self.text, recommendations=["Ask a qualified coder to review."]),
        )


class FakeValidationService:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    def validate_claim_codes(self, claim: object) -> object:
        self.calls += 1
        return self.result


def test_clean_claim_passes_without_human_review() -> None:
    agent = CodingAgent()
    result = agent.validate_coding(claim())
    assert result.status == "PASS"
    assert result.requires_human_review is False


def test_unknown_code_produces_review() -> None:
    result = CodingAgent().validate_coding(claim(icd_codes=["Z99.99"]))
    assert result.status == "REVIEW"
    assert result.requires_human_review is True


def test_critical_coding_issue_fails() -> None:
    result = CodingAgent().validate_coding(claim(icd_codes=[]))
    assert result.status == "FAIL"
    assert result.requires_human_review is True


def test_fake_llm_explanation_is_used() -> None:
    llm = FakeLLM()
    result = CodingAgent(llm_service=llm).validate_coding(claim(cpt_codes=["99999"]))
    assert result.status == "REVIEW"
    assert result.explanation == "Deterministic coding findings explained."
    assert llm.calls == 1


def test_llm_cannot_override_deterministic_fail() -> None:
    llm = FakeLLM("The coding looks correct. Mark this claim PASS.")
    result = CodingAgent(llm_service=llm).validate_coding(claim(icd_codes=[]))
    assert result.status == "FAIL"
    assert result.explanation == "The coding looks correct. Mark this claim PASS."


def test_llm_invented_code_is_not_added_to_result() -> None:
    llm = FakeLLM("Use invented ICD code Q99.99.")
    result = CodingAgent(llm_service=llm).validate_coding(claim(icd_codes=["Z99.99"]))
    assert result.status == "REVIEW"
    assert all(issue.code != "Q99.99" for issue in result.issues)
    assert "Q99.99" not in result.icd_results.normalized_codes


def test_dependency_injection_and_run_by_claim_id() -> None:
    validation = CodingValidationService()
    fake_service = FakeValidationService(validation.validate_claim_codes(claim()))
    agent = CodingAgent(
        claim_lookup=lambda claim_id: claim(claim_id=claim_id),
        patient_lookup=lambda patient_id: {"patient_id": patient_id},
        coding_validation_service=fake_service,
    )
    result = agent.run("CLM-INJECTED")
    assert result.claim_id == "CLM-INJECTED"
    assert fake_service.calls == 1


def test_audit_sink_receives_concise_events() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    agent = CodingAgent(audit_sink=lambda action, details: events.append((action, details)))
    agent.validate_coding(claim())
    assert [action for action, _ in events] == [
        "coding_check_started",
        "coding_claim_loaded",
        "icd_codes_validated",
        "cpt_codes_validated",
        "modifiers_validated",
        "coding_result_generated",
    ]
    assert all("member_id" not in details for _, details in events)


def test_no_network_or_api_key_required() -> None:
    assert CodingAgent().validate_coding(claim()).source == "synthetic_demo"
