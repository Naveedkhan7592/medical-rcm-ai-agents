from datetime import date
from types import SimpleNamespace

from app.schemas import EligibilityExplanation, EligibilityState, LLMResponse
from app.services.llm_service import LLMService
from app.agents.eligibility_agent import EligibilityAgent
from app.tools.eligibility_tool import EligibilityTool


def claim(claim_id: str = "CLM-001", patient_id: str = "PAT-001", payer: str = "Demo Health Plan A", service_date: date = date(2026, 1, 5)) -> dict[str, object]:
    return {"claim_id": claim_id, "patient_id": patient_id, "payer": payer, "service_date": service_date}


def patient(patient_id: str = "PAT-001", payer: str = "Demo Health Plan A", member_id: str | None = "DEMO-MBR-001") -> dict[str, object]:
    return {"patient_id": patient_id, "payer": payer, "member_id": member_id}


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate_structured(self, **_: object) -> LLMResponse[EligibilityExplanation]:
        self.calls += 1
        return LLMResponse(
            model="fake-model",
            response=EligibilityExplanation(explanation="Synthetic explanation.", recommendation="Review synthetic facts."),
        )


def test_eligible_claim_passes_without_llm_call() -> None:
    llm = FakeLLM()
    result = EligibilityAgent(llm_service=llm).process_claim(claim(), patient())
    assert result.eligibility_status == "PASS"
    assert result.eligibility_state == EligibilityState.ELIGIBLE
    assert result.requires_human_review is False
    assert llm.calls == 0


def test_ineligible_claim_is_reviewed() -> None:
    result = EligibilityAgent().process_claim(
        claim("CLM-002", "PAT-002", "Demo Health Plan B", date(2026, 1, 6)),
        patient("PAT-002", "Demo Health Plan B", "DEMO-MBR-002"),
    )
    assert result.eligibility_state == EligibilityState.INELIGIBLE
    assert result.eligibility_status == "REVIEW"
    assert result.requires_human_review is True


def test_missing_eligibility_information_is_reviewed() -> None:
    result = EligibilityAgent().process_claim(
        claim("CLM-UNKNOWN", "PAT-999", "Demo Health Plan A"),
        patient("PAT-999", "Demo Health Plan A", "DEMO-MBR-999"),
    )
    assert result.eligibility_state == EligibilityState.UNKNOWN
    assert result.eligibility_status == "REVIEW"
    assert any(issue.rule == "eligibility_known" for issue in result.issues)


def test_missing_patient_fails_without_llm() -> None:
    llm = FakeLLM()
    result = EligibilityAgent(llm_service=llm).process_claim(claim("CLM-MISSING", "PAT-404"))
    assert result.eligibility_status == "FAIL"
    assert any(issue.rule == "patient_exists" for issue in result.issues)
    assert llm.calls == 0


def test_payer_mismatch_is_reviewed_and_explained() -> None:
    llm = FakeLLM()
    result = EligibilityAgent(llm_service=llm).process_claim(
        claim(payer="Demo Health Plan B"),
        patient(),
    )
    assert result.eligibility_status == "REVIEW"
    assert any(issue.rule == "payer_mismatch" for issue in result.issues)
    assert llm.calls == 1
    assert result.explanation == "Synthetic explanation."


def test_expired_coverage_fails() -> None:
    result = EligibilityAgent().process_claim(
        claim("CLM-EXPIRED", "PAT-004", "Demo Health Plan D", date(2026, 7, 1)),
        patient("PAT-004", "Demo Health Plan D", "DEMO-MBR-004"),
    )
    assert result.eligibility_status == "FAIL"
    assert any(issue.rule == "coverage_dates" for issue in result.issues)


def test_missing_member_id_is_reviewed() -> None:
    result = EligibilityAgent().process_claim(
        claim(),
        patient(member_id=None),
    )
    assert result.eligibility_status == "REVIEW"
    assert any(issue.rule == "member_id_exists" for issue in result.issues)


def test_missing_claim_payer_is_reviewed() -> None:
    result = EligibilityAgent().process_claim(
        claim(payer=None),
        patient(),
    )
    assert result.eligibility_status == "REVIEW"
    assert any(issue.rule == "payer_exists" for issue in result.issues)


def test_audit_events_do_not_contain_full_patient_data() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    agent = EligibilityAgent(audit_sink=lambda action, details: events.append((action, details)))
    agent.process_claim(claim(), patient())
    actions = [action for action, _ in events]
    assert actions == [
        "eligibility_check_started",
        "eligibility_tool_called",
        "eligibility_tool_called",
        "eligibility_rules_evaluated",
        "eligibility_result_generated",
    ]
    assert all("member_id" not in details for _, details in events)
