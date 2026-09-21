import json
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.schemas import ClaimValidationResult, RuleIssue, RuleResult


SEVERITY_SCORES = {"CRITICAL": 40, "HIGH": 25, "MEDIUM": 15, "LOW": 5}
ESSENTIAL_FAILURE_RULES = {"required_fields", "claim_amount", "icd_codes", "cpt_codes", "service_date"}
DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "data" / "payer_policies.json"


ClaimLike = Mapping[str, Any] | Any
RuleFunction = Callable[[ClaimLike, dict[str, Any]], RuleResult]


def _value(claim: ClaimLike, name: str, default: Any = None) -> Any:
    if isinstance(claim, Mapping):
        return claim.get(name, default)
    return getattr(claim, name, default)


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _has_field(claim: ClaimLike, name: str) -> bool:
    if isinstance(claim, Mapping):
        return name in claim
    return hasattr(claim, name)


def evaluate_timely_filing(
    service_date: date | str | None,
    submission_date: date | str | None,
    payer_policy: Mapping[str, Any],
) -> RuleIssue | None:
    service = _as_date(service_date)
    submission = _as_date(submission_date)
    filing_days = payer_policy.get("timely_filing_days")
    if service is None or submission is None or filing_days is None:
        return None

    elapsed_days = (submission - service).days
    if elapsed_days > int(filing_days):
        return RuleIssue(
            rule="timely_filing",
            severity="HIGH",
            message="Claim exceeds the synthetic payer timely filing limit",
            details={"elapsed_days": elapsed_days, "timely_filing_days": int(filing_days)},
        )
    return None


def find_duplicate_claim(claim: ClaimLike, existing_claims: Iterable[ClaimLike]) -> ClaimLike | None:
    signature = (
        _value(claim, "patient_id"),
        _value(claim, "provider_id"),
        _as_date(_value(claim, "service_date")),
        tuple(_value(claim, "cpt_codes") or []),
    )
    claim_id = _value(claim, "claim_id")
    for existing in existing_claims:
        if _value(existing, "claim_id") == claim_id:
            continue
        existing_signature = (
            _value(existing, "patient_id"),
            _value(existing, "provider_id"),
            _as_date(_value(existing, "service_date")),
            tuple(_value(existing, "cpt_codes") or []),
        )
        if signature == existing_signature:
            return existing
    return None


class RulesEngine:
    """Deterministic validation for synthetic RCM claims."""

    def __init__(self, policy_path: str | Path = DEFAULT_POLICY_PATH) -> None:
        self.policy_path = Path(policy_path)
        self.payer_policies = self._load_policies()
        self.rules: list[tuple[str, RuleFunction]] = [
            ("required_fields", self._required_fields_rule),
            ("claim_amount", self._claim_amount_rule),
            ("icd_codes", self._icd_rule),
            ("cpt_codes", self._cpt_rule),
            ("modifiers", self._modifier_rule),
            ("service_date", self._service_date_rule),
            ("payer_policy", self._payer_policy_rule),
            ("timely_filing", self._timely_filing_rule),
            ("duplicate_claim", self._duplicate_claim_rule),
            ("eligibility", self._eligibility_rule),
        ]

    def _load_policies(self) -> dict[str, dict[str, Any]]:
        with self.policy_path.open(encoding="utf-8") as policy_file:
            document = json.load(policy_file)
        return {policy["payer"]: policy for policy in document.get("policies", [])}

    def validate_claim(
        self,
        claim: ClaimLike,
        *,
        submission_date: date | str | None = None,
        existing_claims: Iterable[ClaimLike] | None = None,
        eligibility: bool | None = None,
    ) -> ClaimValidationResult:
        context = {
            "submission_date": submission_date,
            "existing_claims": existing_claims or [],
            "eligibility": eligibility,
        }
        results = [rule(claim, context) for _, rule in self.rules]
        issues = [issue for result in results for issue in result.issues]
        failed = [result.rule for result in results if not result.passed]
        passed = [result.rule for result in results if result.passed]
        risk_score = min(sum(SEVERITY_SCORES[issue.severity] for issue in issues), 100)
        has_essential_failure = any(issue.rule in ESSENTIAL_FAILURE_RULES for issue in issues)
        has_review_issue = any(
            issue.rule in {"payer_policy", "timely_filing", "duplicate_claim", "eligibility"}
            for issue in issues
        )
        if has_essential_failure:
            overall_status = "FAIL"
        elif issues or has_review_issue:
            overall_status = "REVIEW"
        else:
            overall_status = "PASS"

        return ClaimValidationResult(
            claim_id=_value(claim, "claim_id"),
            overall_status=overall_status,
            risk_score=risk_score,
            rules_checked=[name for name, _ in self.rules],
            passed=passed,
            failed=failed,
            warnings=[issue.message for issue in issues if issue.severity in {"LOW", "MEDIUM"}],
            issues=issues,
        )

    def _required_fields_rule(self, claim: ClaimLike, _: dict[str, Any]) -> RuleResult:
        required = ["patient_id", "payer", "provider_id", "service_date", "icd_codes", "cpt_codes", "claim_amount"]
        missing = [field for field in required if not _has_value(_value(claim, field))]
        issues = [
            RuleIssue(
                rule="required_fields",
                severity="HIGH",
                message="Claim is missing required field values",
                details={"missing_fields": missing},
            )
        ] if missing else []
        return RuleResult(rule="required_fields", passed=not issues, issues=issues)

    def _claim_amount_rule(self, claim: ClaimLike, _: dict[str, Any]) -> RuleResult:
        amount = _value(claim, "claim_amount")
        try:
            valid = amount is not None and Decimal(str(amount)) > 0
        except (ArithmeticError, ValueError):
            valid = False
        issues = [] if valid else [RuleIssue(rule="claim_amount", severity="HIGH", message="Claim amount must be greater than zero", details={})]
        return RuleResult(rule="claim_amount", passed=not issues, issues=issues)

    def _icd_rule(self, claim: ClaimLike, _: dict[str, Any]) -> RuleResult:
        issues = [] if _has_value(_value(claim, "icd_codes")) else [RuleIssue(rule="icd_codes", severity="HIGH", message="At least one ICD code is required", details={})]
        return RuleResult(rule="icd_codes", passed=not issues, issues=issues)

    def _cpt_rule(self, claim: ClaimLike, _: dict[str, Any]) -> RuleResult:
        issues = [] if _has_value(_value(claim, "cpt_codes")) else [RuleIssue(rule="cpt_codes", severity="HIGH", message="At least one CPT code is required", details={})]
        return RuleResult(rule="cpt_codes", passed=not issues, issues=issues)

    def _modifier_rule(self, claim: ClaimLike, _: dict[str, Any]) -> RuleResult:
        policy = self.payer_policies.get(_value(claim, "payer"), {})
        if policy.get("modifier_required") and not _has_value(_value(claim, "modifiers")):
            issue = RuleIssue(rule="modifiers", severity="HIGH", message="Payer policy requires a modifier", details={})
            return RuleResult(rule="modifiers", passed=False, issues=[issue])
        return RuleResult(rule="modifiers", passed=True)

    def _service_date_rule(self, claim: ClaimLike, _: dict[str, Any]) -> RuleResult:
        service_date = _as_date(_value(claim, "service_date"))
        if service_date is None:
            issue = RuleIssue(rule="service_date", severity="HIGH", message="Service date is missing or invalid", details={})
        elif service_date > date.today():
            issue = RuleIssue(rule="service_date", severity="HIGH", message="Service date cannot be in the future", details={"service_date": service_date.isoformat()})
        else:
            issue = None
        return RuleResult(rule="service_date", passed=issue is None, issues=[] if issue is None else [issue])

    def _payer_policy_rule(self, claim: ClaimLike, _: dict[str, Any]) -> RuleResult:
        payer = _value(claim, "payer")
        policy = self.payer_policies.get(payer)
        if policy is None:
            issue = RuleIssue(rule="payer_policy", severity="MEDIUM", message="Payer policy unavailable for deterministic validation", details={"payer": payer})
            return RuleResult(rule="payer_policy", passed=False, issues=[issue])
        issues: list[RuleIssue] = []
        for requirement, field in (("authorization_required", "authorization"), ("documentation_required", "documentation")):
            if policy.get(requirement) and _has_field(claim, field):
                if not _has_value(_value(claim, field)):
                    issues.append(RuleIssue(rule="payer_policy", severity="MEDIUM", message=f"Payer policy requires {field} evidence", details={"requirement": requirement}))
        return RuleResult(rule="payer_policy", passed=not issues, issues=issues)

    def _timely_filing_rule(self, claim: ClaimLike, context: dict[str, Any]) -> RuleResult:
        policy = self.payer_policies.get(_value(claim, "payer"))
        issue = evaluate_timely_filing(_value(claim, "service_date"), context["submission_date"], policy or {}) if policy else None
        return RuleResult(rule="timely_filing", passed=issue is None, issues=[] if issue is None else [issue])

    def _duplicate_claim_rule(self, claim: ClaimLike, context: dict[str, Any]) -> RuleResult:
        duplicate = find_duplicate_claim(claim, context["existing_claims"])
        if duplicate is None:
            return RuleResult(rule="duplicate_claim", passed=True)
        issue = RuleIssue(rule="duplicate_claim", severity="HIGH", message="Matching existing claim detected", details={"matching_claim_id": _value(duplicate, "claim_id")})
        return RuleResult(rule="duplicate_claim", passed=False, issues=[issue])

    def _eligibility_rule(self, _: ClaimLike, context: dict[str, Any]) -> RuleResult:
        if context["eligibility"] is False:
            issue = RuleIssue(rule="eligibility", severity="HIGH", message="Eligibility result is not eligible", details={})
            return RuleResult(rule="eligibility", passed=False, issues=[issue])
        return RuleResult(rule="eligibility", passed=True)
