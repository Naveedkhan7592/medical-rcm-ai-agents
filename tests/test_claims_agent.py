from datetime import date
from types import SimpleNamespace

from app.agents.claims_agent import ClaimsAgent
from app.schemas import (
    ClaimExplanation,
    ClaimValidationResult,
    EligibilityAgentResult,
    EligibilityState,
    EligibilityStatus,
    LLMResponse,
)


def make_claim(**overrides: object) -> dict[str, object]:
    claim: dict[str, object] = {
        "claim_id": "CLM-CLAIMS-001",
        "patient_id": "PAT-001",
        "payer": "Demo Health Plan A",
        "provider_id": "DEMO-PROV-001",
        "service_date": date(2026, 1, 5),
        "icd_codes": ["Z00.00"],
        "cpt_codes": ["99213"],
        "modifiers": [],
        "claim_amount": 125,
    }
    claim.update(overrides)
    return claim


def make_patient(**overrides: object) -> dict[str, object]:
    patient: dict[str, object] = {
        "patient_id": "PAT-001",
        "payer": "Demo Health Plan A",
        "member_id": "DEMO-MBR-001",
    }
    patient.update(overrides)
    return patient


def eligibility(status: EligibilityStatus = EligibilityStatus.PASS) -> EligibilityAgentResult:
    return EligibilityAgentResult(
        claim_id="CLM-CLAIMS-001",
        patient_id="PAT-001",
        payer="Demo Health Plan A",
        member_id="DEMO-MBR-001",
        eligibility_status=status,
        eligibility_state=EligibilityState.ELIGIBLE if status == EligibilityStatus.PASS else EligibilityState.UNKNOWN,
        recommendation="No action needed.",
        explanation="Synthetic eligibility result.",
        requires_human_review=status != EligibilityStatus.PASS,
    )


def validation(status: str = "PASS", *, issues: list[dict[str, object]] | None = None) -> ClaimValidationResult:
    issue_models = issues or []
    return ClaimValidationResult(
        claim_id="CLM-CLAIMS-001",
        overall_status=status,
        risk_score=25 if issue_models else 0,
        rules_checked=["required_fields", "claim_amount", "icd_codes", "cpt_codes"],
        passed=[] if issue_models else ["required_fields", "claim_amount", "icd_codes", "cpt_codes"],
        failed=[str(issue["rule"]) for issue in issue_models],
        warnings=[str(issue["message"]) for issue in issue_models if issue["severity"] == "MEDIUM"],
        issues=issue_models,
    )


class FakeRulesEngine:
    def __init__(self, result: ClaimValidationResult) -> None:
        self.result = result
        self.calls = 0

    def validate_claim(self, claim: object) -> ClaimValidationResult:
        self.calls += 1
        return self.result


class FakeEligibilityAgent:
    def __init__(self, result: EligibilityAgentResult) -> None:
        self.result = result
        self.calls = 0

    def process_claim(self, claim: object, patient: object) -> EligibilityAgentResult:
        self.calls += 1
        return self.result


class FakeLLM:
    def __init__(self, explanation: str = "Deterministic findings explained.") -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.explanation = explanation

    def generate_structured(self, *, user_prompt: str, **_: object) -> LLMResponse[ClaimExplanation]:
        self.calls += 1
        self.prompts.append(user_prompt)
        return LLMResponse(
            model="fake-model",
            response=ClaimExplanation(explanation=self.explanation, recommendations=["Resolve documented issues."]),
        )


def build_agent(
    *,
    rules: ClaimValidationResult | None = None,
    eligibility_result: EligibilityAgentResult | None = None,
    llm: FakeLLM | None = None,
    audit: list[tuple[str, dict[str, object]]] | None = None,
) -> tuple[ClaimsAgent, FakeRulesEngine, FakeEligibilityAgent]:
    fake_rules = FakeRulesEngine(rules or validation())
    fake_eligibility = FakeEligibilityAgent(eligibility_result or eligibility())
    agent = ClaimsAgent(
        rules_engine=fake_rules,
        eligibility_agent=fake_eligibility,
        llm_service=llm,
        claim_lookup=lambda claim_id: make_claim(claim_id=claim_id),
        patient_lookup=lambda patient_id: make_patient(patient_id=patient_id),
        audit_sink=(lambda action, details: audit.append((action, details))) if audit is not None else None,
    )
    return agent, fake_rules, fake_eligibility


def test_valid_claim_and_eligible_patient_pass() -> None:
    agent, rules, eligibility_agent = build_agent()
    result = agent.validate_claim(make_claim(), make_patient())
    assert result.status == "PASS"
    assert result.requires_human_review is False
    assert rules.calls == 1
    assert eligibility_agent.calls == 1


def test_eligibility_review_aggregates_to_review() -> None:
    agent, _, _ = build_agent(eligibility_result=eligibility(EligibilityStatus.REVIEW))
    result = agent.validate_claim(make_claim(), make_patient())
    assert result.status == "REVIEW"
    assert result.requires_human_review is True


def test_unknown_payer_policy_review_aggregates_to_review() -> None:
    issue = {"rule": "payer_policy", "severity": "MEDIUM", "message": "Payer policy unavailable for deterministic validation", "details": {}}
    agent, _, _ = build_agent(rules=validation("REVIEW", issues=[issue]))
    result = agent.validate_claim(make_claim(payer="Unknown Demo Payer"), make_patient())
    assert result.status == "REVIEW"
    assert any(item.rule == "payer_policy" for item in result.issues)


def test_missing_member_information_is_review() -> None:
    review = eligibility(EligibilityStatus.REVIEW)
    review.issues = [{"rule": "member_id_exists", "severity": "MEDIUM", "message": "Patient member ID is missing", "details": {}}]
    agent, _, _ = build_agent(eligibility_result=review)
    result = agent.validate_claim(make_claim(), make_patient(member_id=None))
    assert result.status == "REVIEW"


def test_payer_mismatch_is_review() -> None:
    review = eligibility(EligibilityStatus.REVIEW)
    review.issues = [{"rule": "payer_mismatch", "severity": "MEDIUM", "message": "Claim payer differs from patient payer", "details": {}}]
    agent, _, _ = build_agent(eligibility_result=review)
    result = agent.validate_claim(make_claim(payer="Demo Health Plan B"), make_patient())
    assert result.status == "REVIEW"


def test_missing_required_data_fails() -> None:
    issue = {"rule": "required_fields", "severity": "HIGH", "message": "Claim is missing required field values", "details": {}}
    agent, _, _ = build_agent(rules=validation("FAIL", issues=[issue]))
    result = agent.validate_claim(make_claim(cpt_codes=[]), make_patient())
    assert result.status == "FAIL"
    assert result.requires_human_review is True


def test_invalid_amount_fails() -> None:
    issue = {"rule": "claim_amount", "severity": "HIGH", "message": "Claim amount must be greater than zero", "details": {}}
    agent, _, _ = build_agent(rules=validation("FAIL", issues=[issue]))
    assert agent.validate_claim(make_claim(claim_amount=0), make_patient()).status == "FAIL"


def test_missing_icd_fails() -> None:
    issue = {"rule": "icd_codes", "severity": "HIGH", "message": "At least one ICD code is required", "details": {}}
    agent, _, _ = build_agent(rules=validation("FAIL", issues=[issue]))
    assert agent.validate_claim(make_claim(icd_codes=[]), make_patient()).status == "FAIL"


def test_missing_cpt_fails() -> None:
    issue = {"rule": "cpt_codes", "severity": "HIGH", "message": "At least one CPT code is required", "details": {}}
    agent, _, _ = build_agent(rules=validation("FAIL", issues=[issue]))
    assert agent.validate_claim(make_claim(cpt_codes=[]), make_patient()).status == "FAIL"


def test_eligibility_fail_aggregates_to_fail() -> None:
    agent, _, _ = build_agent(eligibility_result=eligibility(EligibilityStatus.FAIL))
    assert agent.validate_claim(make_claim(), make_patient()).status == "FAIL"


def test_critical_rules_failure_aggregates_to_fail() -> None:
    issue = {"rule": "service_date", "severity": "CRITICAL", "message": "Critical validation failure", "details": {}}
    agent, _, _ = build_agent(rules=validation("FAIL", issues=[issue]))
    assert agent.validate_claim(make_claim(), make_patient()).status == "FAIL"


def test_llm_explains_findings_but_cannot_override_fail() -> None:
    issue = {"rule": "required_fields", "severity": "HIGH", "message": "Required claim data is missing", "details": {}}
    llm = FakeLLM("Claim looks valid and should pass.")
    agent, _, _ = build_agent(rules=validation("FAIL", issues=[issue]), llm=llm)
    result = agent.validate_claim(make_claim(), make_patient())
    assert result.status == "FAIL"
    assert result.explanation == "Claim looks valid and should pass."
    assert llm.calls == 1
    assert "Required claim data is missing" in llm.prompts[0]


def test_llm_is_not_called_for_clean_pass() -> None:
    llm = FakeLLM()
    agent, _, _ = build_agent(llm=llm)
    result = agent.validate_claim(make_claim(), make_patient())
    assert result.status == "PASS"
    assert llm.calls == 0


def test_risk_score_reuses_rules_engine_score() -> None:
    agent, _, _ = build_agent(rules=validation("REVIEW", issues=[{"rule": "timely_filing", "severity": "HIGH", "message": "Late", "details": {}}]))
    result = agent.validate_claim(make_claim(), make_patient())
    assert result.risk_score == 25


def test_dependency_injection_and_audit_events() -> None:
    audit: list[tuple[str, dict[str, object]]] = []
    agent, rules, eligibility_agent = build_agent(audit=audit)
    result = agent.run("CLM-INJECTED")
    assert result.status == "PASS"
    assert rules.calls == 1
    assert eligibility_agent.calls == 1
    assert [event[0] for event in audit] == [
        "claims_check_started",
        "claim_loaded",
        "claim_rules_validated",
        "claim_eligibility_checked",
        "claims_result_generated",
    ]
    assert all("member_id" not in details for _, details in audit)


def test_no_postgresql_or_network_required() -> None:
    agent, _, _ = build_agent()
    assert agent.validate_claim(make_claim(), make_patient()).source == "synthetic_demo"
