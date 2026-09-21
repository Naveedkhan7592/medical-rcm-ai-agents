from datetime import date, timedelta
from decimal import Decimal

from app.services.rules_engine import RulesEngine


def make_claim(**overrides: object) -> dict[str, object]:
    claim: dict[str, object] = {
        "claim_id": "CLM-TEST-001",
        "patient_id": "PAT-TEST-001",
        "payer": "Demo Health Plan B",
        "provider_id": "DEMO-PROV-001",
        "service_date": date.today() - timedelta(days=5),
        "icd_codes": ["Z00.00"],
        "cpt_codes": ["99213"],
        "modifiers": [],
        "claim_amount": Decimal("125.00"),
    }
    claim.update(overrides)
    return claim


def test_valid_claim_passes() -> None:
    result = RulesEngine().validate_claim(make_claim())
    assert result.overall_status == "PASS"
    assert result.issues == []


def test_missing_patient_id_fails() -> None:
    result = RulesEngine().validate_claim(make_claim(patient_id=None))
    assert result.overall_status == "FAIL"
    assert "patient_id" in result.issues[0].details["missing_fields"]


def test_missing_payer_fails() -> None:
    result = RulesEngine().validate_claim(make_claim(payer=None))
    assert result.overall_status == "FAIL"


def test_missing_cpt_fails() -> None:
    result = RulesEngine().validate_claim(make_claim(cpt_codes=[]))
    assert result.overall_status == "FAIL"
    assert any(issue.rule == "cpt_codes" for issue in result.issues)


def test_missing_icd_fails() -> None:
    result = RulesEngine().validate_claim(make_claim(icd_codes=[]))
    assert result.overall_status == "FAIL"
    assert any(issue.rule == "icd_codes" for issue in result.issues)


def test_zero_claim_amount_fails() -> None:
    result = RulesEngine().validate_claim(make_claim(claim_amount=0))
    assert result.overall_status == "FAIL"
    assert any(issue.rule == "claim_amount" for issue in result.issues)


def test_unknown_payer_produces_review() -> None:
    result = RulesEngine().validate_claim(make_claim(payer="Unknown Demo Payer"))
    assert result.overall_status == "REVIEW"
    assert any(issue.rule == "payer_policy" for issue in result.issues)
    assert result.issues[-1].message == "Payer policy unavailable for deterministic validation"


def test_timely_filing_violation_produces_issue() -> None:
    result = RulesEngine().validate_claim(
        make_claim(service_date=date(2025, 1, 1)),
        submission_date=date(2026, 1, 1),
    )
    issue = next(issue for issue in result.issues if issue.rule == "timely_filing")
    assert issue.severity == "HIGH"
    assert result.overall_status == "REVIEW"


def test_duplicate_claim_is_detected() -> None:
    claim = make_claim()
    existing = make_claim(claim_id="CLM-EXISTING-001")
    result = RulesEngine().validate_claim(claim, existing_claims=[existing])
    issue = next(issue for issue in result.issues if issue.rule == "duplicate_claim")
    assert issue.severity == "HIGH"
    assert issue.details["matching_claim_id"] == "CLM-EXISTING-001"
    assert result.overall_status == "REVIEW"


def test_ineligible_result_produces_review() -> None:
    result = RulesEngine().validate_claim(make_claim(), eligibility=False)
    assert result.overall_status == "REVIEW"
    assert any(issue.rule == "eligibility" for issue in result.issues)


def test_risk_score_is_deterministic() -> None:
    claim = make_claim(patient_id=None, icd_codes=[], cpt_codes=[], claim_amount=0)
    first = RulesEngine().validate_claim(claim)
    second = RulesEngine().validate_claim(claim)
    assert first.risk_score == second.risk_score == 100
    assert first.model_dump() == second.model_dump()


def test_engine_does_not_require_postgresql() -> None:
    result = RulesEngine().validate_claim(make_claim())
    assert result.claim_id == "CLM-TEST-001"
