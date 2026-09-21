from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.schemas import (
    CodingCheckResult,
    CodingIssue,
    CodingIssueCategory,
    CodingSeverity,
    CodingStatus,
    CodingValidationResult,
)


SEVERITY_SCORES = {"CRITICAL": 40, "HIGH": 25, "MEDIUM": 15, "LOW": 5}
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ICD_PATTERN = re.compile(r"^[A-Z][0-9]{2}(?:\.[A-Z0-9]{1,4})?$")
CPT_PATTERN = re.compile(r"^[0-9]{5}$")
MODIFIER_PATTERN = re.compile(r"^[A-Z0-9]{2}$")


class CodingValidationService:
    """Deterministic validation against small synthetic coding references."""

    def __init__(self, data_dir: str | Path = DEFAULT_DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.icd_codes = self._load_code_set("icd10_codes.json")
        self.cpt_codes = self._load_code_set("cpt_codes.json")
        self.coding_rules = self._load_json("coding_rules.json")
        self.supported_modifiers = {
            str(value).strip().upper() for value in self.coding_rules.get("supported_modifiers", [])
        }
        self.payer_modifier_rules = {
            str(payer): [str(value).strip().upper() for value in values]
            for payer, values in self.coding_rules.get("payer_modifier_rules", {}).items()
        }

    def validate_claim_codes(self, claim: Mapping[str, Any] | Any) -> CodingValidationResult:
        icd_results = self._validate_codes(claim, "icd_codes", "ICD", ICD_PATTERN, self.icd_codes)
        cpt_results = self._validate_codes(claim, "cpt_codes", "CPT", CPT_PATTERN, self.cpt_codes)
        modifier_results = self._validate_modifiers(claim)
        issues = icd_results.issues + cpt_results.issues + modifier_results.issues
        status = self._status(issues)
        risk_score = min(sum(SEVERITY_SCORES[issue.severity.value] for issue in issues), 100)
        return CodingValidationResult(
            icd_results=icd_results,
            cpt_results=cpt_results,
            modifier_results=modifier_results,
            status=status,
            risk_score=risk_score,
            issues=issues,
        )

    def _load_json(self, filename: str) -> dict[str, Any]:
        with (self.data_dir / filename).open(encoding="utf-8") as data_file:
            return json.load(data_file)

    def _load_code_set(self, filename: str) -> set[str]:
        return {str(code).strip().upper() for code in self._load_json(filename).get("codes", [])}

    @staticmethod
    def _value(claim: Mapping[str, Any] | Any, name: str, default: Any = None) -> Any:
        if isinstance(claim, Mapping):
            return claim.get(name, default)
        return getattr(claim, name, default)

    def _validate_codes(
        self,
        claim: Mapping[str, Any] | Any,
        field: str,
        code_type: str,
        pattern: re.Pattern[str],
        reference: set[str],
    ) -> CodingCheckResult:
        raw_codes = self._value(claim, field)
        issues: list[CodingIssue] = []
        normalized: list[str] = []
        if raw_codes is None or raw_codes == []:
            issues.append(
                CodingIssue(
                    rule=f"{field}_required",
                    category=CodingIssueCategory.MISSING_CODE,
                    severity=CodingSeverity.HIGH,
                    message=f"At least one {code_type} code is required",
                )
            )
            return CodingCheckResult(code_type=code_type, checked=True, passed=False, issues=issues)
        if not isinstance(raw_codes, list):
            raw_codes = [raw_codes]
        for raw_code in raw_codes:
            if not isinstance(raw_code, str) or not raw_code.strip():
                issues.append(
                    CodingIssue(
                        rule=f"{field}_format",
                        category=CodingIssueCategory.INVALID_FORMAT,
                        severity=CodingSeverity.HIGH,
                        message=f"{code_type} code must be a non-empty string",
                    )
                )
                continue
            code = raw_code.strip().upper()
            normalized.append(code)
            if not pattern.fullmatch(code):
                issues.append(
                    CodingIssue(
                        rule=f"{field}_format",
                        category=CodingIssueCategory.INVALID_FORMAT,
                        severity=CodingSeverity.HIGH,
                        message=f"{code_type} code has an invalid demo format",
                        code=code,
                    )
                )
            elif code not in reference:
                issues.append(
                    CodingIssue(
                        rule=f"{field}_reference",
                        category=CodingIssueCategory.UNKNOWN_CODE,
                        severity=CodingSeverity.MEDIUM,
                        message=f"{code_type} code is not in the synthetic demo reference",
                        code=code,
                    )
                )
        for duplicate in self._duplicates(normalized):
            issues.append(
                CodingIssue(
                    rule=f"{field}_duplicates",
                    category=CodingIssueCategory.DUPLICATE_CODE,
                    severity=CodingSeverity.MEDIUM,
                    message=f"Duplicate {code_type} code detected",
                    code=duplicate,
                )
            )
        return CodingCheckResult(code_type=code_type, checked=True, passed=not issues, normalized_codes=normalized, issues=issues)

    def _validate_modifiers(self, claim: Mapping[str, Any] | Any) -> CodingCheckResult:
        raw_modifiers = self._value(claim, "modifiers")
        issues: list[CodingIssue] = []
        normalized: list[str] = []
        if raw_modifiers is None:
            raw_modifiers = []
        if not isinstance(raw_modifiers, list):
            raw_modifiers = [raw_modifiers]
        for raw_modifier in raw_modifiers:
            if not isinstance(raw_modifier, str) or not raw_modifier.strip():
                issues.append(CodingIssue(rule="modifier_format", category=CodingIssueCategory.INVALID_MODIFIER, severity=CodingSeverity.HIGH, message="Modifier must be a non-empty string"))
                continue
            modifier = raw_modifier.strip().upper()
            normalized.append(modifier)
            if not MODIFIER_PATTERN.fullmatch(modifier):
                issues.append(CodingIssue(rule="modifier_format", category=CodingIssueCategory.INVALID_MODIFIER, severity=CodingSeverity.HIGH, message="Modifier has an invalid demo format", code=modifier))
            elif modifier not in self.supported_modifiers:
                issues.append(CodingIssue(rule="modifier_reference", category=CodingIssueCategory.UNSUPPORTED_MODIFIER, severity=CodingSeverity.MEDIUM, message="Modifier is not supported by the synthetic demo rules", code=modifier))
        for duplicate in self._duplicates(normalized):
            issues.append(CodingIssue(rule="modifier_duplicates", category=CodingIssueCategory.DUPLICATE_CODE, severity=CodingSeverity.MEDIUM, message="Duplicate modifier detected", code=duplicate))
        payer = self._value(claim, "payer")
        required_modifiers = self.payer_modifier_rules.get(str(payer), [])
        if required_modifiers and not any(modifier in normalized for modifier in required_modifiers):
            issues.append(CodingIssue(rule="payer_modifier_policy", category=CodingIssueCategory.CODING_POLICY_ISSUE, severity=CodingSeverity.MEDIUM, message="Claim does not include a modifier listed by the configured synthetic payer rule", details={"required_modifiers": required_modifiers}))
        return CodingCheckResult(code_type="MODIFIER", checked=True, passed=not issues, normalized_codes=normalized, issues=issues)

    @staticmethod
    def _duplicates(values: list[str]) -> set[str]:
        return {value for value in values if values.count(value) > 1}

    @staticmethod
    def _status(issues: list[CodingIssue]) -> CodingStatus:
        if any(issue.severity in {CodingSeverity.HIGH, CodingSeverity.CRITICAL} for issue in issues):
            return CodingStatus.FAIL
        return CodingStatus.REVIEW if issues else CodingStatus.PASS
