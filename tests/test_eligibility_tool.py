from datetime import date

from app.schemas import EligibilityState
from app.tools.eligibility_tool import EligibilityTool


def test_existing_eligible_patient() -> None:
    result = EligibilityTool().check_eligibility("PAT-001", "Demo Health Plan A", "DEMO-MBR-001")
    assert result.eligibility_state == EligibilityState.ELIGIBLE
    assert result.eligible is True
    assert result.source == "synthetic_demo"


def test_existing_ineligible_patient() -> None:
    result = EligibilityTool().check_eligibility("PAT-002", "Demo Health Plan B", "DEMO-MBR-002")
    assert result.eligibility_state == EligibilityState.INELIGIBLE
    assert result.eligible is False
    assert result.coverage_start is None


def test_unknown_patient() -> None:
    result = EligibilityTool().check_eligibility("PAT-999", "Demo Health Plan A", "DEMO-MBR-999")
    assert result.eligibility_state == EligibilityState.UNKNOWN
    assert result.eligible is None


def test_missing_member_id() -> None:
    result = EligibilityTool().check_eligibility("PAT-001", "Demo Health Plan A", None)
    assert result.eligibility_state == EligibilityState.UNKNOWN


def test_payer_mismatch_is_unknown_without_inventing_facts() -> None:
    result = EligibilityTool().check_eligibility("PAT-001", "Demo Health Plan B", "DEMO-MBR-001")
    assert result.eligibility_state == EligibilityState.UNKNOWN
    assert result.eligible is None


def test_coverage_date_boundaries() -> None:
    result = EligibilityTool().check_eligibility("PAT-004", "Demo Health Plan D", "DEMO-MBR-004")
    assert result.coverage_start == date(2026, 1, 1)
    assert result.coverage_end == date(2026, 6, 30)
    assert result.coverage_start <= date(2026, 1, 1) <= result.coverage_end
    assert result.coverage_start <= date(2026, 6, 30) <= result.coverage_end


def test_service_date_outside_coverage_is_available_to_agent() -> None:
    result = EligibilityTool().check_eligibility("PAT-004", "Demo Health Plan D", "DEMO-MBR-004")
    assert date(2026, 7, 1) > result.coverage_end
