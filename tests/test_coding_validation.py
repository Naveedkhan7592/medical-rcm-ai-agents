from app.services.coding_validation import CodingValidationService


def claim(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "claim_id": "CLM-CODING-001",
        "payer": "Demo Health Plan A",
        "icd_codes": ["Z00.00"],
        "cpt_codes": ["99213"],
        "modifiers": ["25"],
    }
    value.update(overrides)
    return value


def test_valid_demo_codes_pass() -> None:
    result = CodingValidationService().validate_claim_codes(claim())
    assert result.status == "PASS"
    assert result.issues == []


def test_missing_icd_codes_fails() -> None:
    result = CodingValidationService().validate_claim_codes(claim(icd_codes=[]))
    assert result.status == "FAIL"
    assert result.icd_results.issues[0].category == "MISSING_CODE"


def test_invalid_icd_format_fails() -> None:
    result = CodingValidationService().validate_claim_codes(claim(icd_codes=["bad-code"]))
    assert result.status == "FAIL"
    assert any(issue.category == "INVALID_FORMAT" for issue in result.issues)


def test_unknown_icd_code_is_review() -> None:
    result = CodingValidationService().validate_claim_codes(claim(icd_codes=["Z99.99"]))
    assert result.status == "REVIEW"
    assert any(issue.category == "UNKNOWN_CODE" for issue in result.issues)


def test_duplicate_icd_code_is_review() -> None:
    result = CodingValidationService().validate_claim_codes(claim(icd_codes=["Z00.00", "Z00.00"]))
    assert result.status == "REVIEW"
    assert any(issue.category == "DUPLICATE_CODE" for issue in result.issues)


def test_valid_demo_cpt_code_passes() -> None:
    result = CodingValidationService().validate_claim_codes(claim())
    assert result.cpt_results.passed is True


def test_missing_cpt_codes_fails() -> None:
    result = CodingValidationService().validate_claim_codes(claim(cpt_codes=[]))
    assert result.status == "FAIL"
    assert result.cpt_results.issues[0].category == "MISSING_CODE"


def test_invalid_cpt_format_fails() -> None:
    result = CodingValidationService().validate_claim_codes(claim(cpt_codes=["123"]))
    assert result.status == "FAIL"
    assert any(issue.category == "INVALID_FORMAT" for issue in result.issues)


def test_unknown_cpt_code_is_review() -> None:
    result = CodingValidationService().validate_claim_codes(claim(cpt_codes=["99999"]))
    assert result.status == "REVIEW"
    assert any(issue.category == "UNKNOWN_CODE" for issue in result.issues)


def test_duplicate_cpt_code_is_review() -> None:
    result = CodingValidationService().validate_claim_codes(claim(cpt_codes=["99213", "99213"]))
    assert result.status == "REVIEW"
    assert any(issue.category == "DUPLICATE_CODE" for issue in result.issues)


def test_valid_modifier_passes() -> None:
    result = CodingValidationService().validate_claim_codes(claim(modifiers=["25"]))
    assert result.modifier_results.passed is True


def test_invalid_modifier_fails() -> None:
    result = CodingValidationService().validate_claim_codes(claim(modifiers=["bad"]))
    assert result.status == "FAIL"
    assert any(issue.category == "INVALID_MODIFIER" for issue in result.issues)


def test_unsupported_modifier_is_review() -> None:
    result = CodingValidationService().validate_claim_codes(claim(modifiers=["59"]))
    assert result.status == "REVIEW"
    assert any(issue.category == "UNSUPPORTED_MODIFIER" for issue in result.issues)


def test_duplicate_modifier_is_review() -> None:
    result = CodingValidationService().validate_claim_codes(claim(modifiers=["25", "25"]))
    assert result.status == "REVIEW"
    assert any(issue.category == "DUPLICATE_CODE" for issue in result.issues)


def test_configured_payer_modifier_rule_is_used() -> None:
    result = CodingValidationService().validate_claim_codes(
        claim(payer="Demo Health Plan C", modifiers=[])
    )
    assert any(issue.category == "CODING_POLICY_ISSUE" for issue in result.issues)
