from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.agents import (
    ARAgent,
    AppealAgent,
    BillingQAAgent,
    ClaimsAgent,
    CodingAgent,
    DenialAgent,
    EligibilityAgent,
    PaymentAgent,
    RCMSupervisorAgent,
)
from app.schemas import SupervisorPriority, SupervisorTask, SupervisorTaskType

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

SCENARIO_LIBRARY: list[dict[str, Any]] = [
    {
        "id": "eligibility-denial",
        "title": "Eligibility Coverage Gap",
        "description": "A payer denies a claim because the member's active coverage did not align with the service date.",
        "claim_id": "CLM-004",
        "task_type": "DENIAL_REVIEW",
        "priority": "HIGH",
        "input_data": {"denial_category": "ELIGIBILITY", "priority": "HIGH"},
        "next_action": "VERIFY COVERAGE AND MEMBER ACTIVE DATE",
        "agents_required": ["denial", "eligibility", "billing_qa"],
        "expected_statuses": ["REVIEW"],
        "expected_human_review": True,
        "expected_agents": ["denial", "eligibility", "billing_qa"],
        "exact_routing": True,
        "expected_external_action": False,
    },
    {
        "id": "coding-denial",
        "title": "Coding Correction Required",
        "description": "A denied claim indicates a coding mismatch between the registered diagnosis and procedure combination.",
        "claim_id": "CLM-010",
        "task_type": "DENIAL_REVIEW",
        "priority": "MEDIUM",
        "input_data": {"denial_category": "CODING"},
        "next_action": "REVIEW CPT/ICD MATCH AND UPDATE BILLING CODE",
        "agents_required": ["denial", "coding", "billing_qa"],
        "expected_statuses": ["REVIEW"],
        "expected_human_review": True,
        "expected_agents": ["denial", "coding", "billing_qa"],
        "exact_routing": True,
        "expected_external_action": False,
    },
    {
        "id": "full-rcm-review",
        "title": "Full Portfolio Review",
        "description": "A combined portfolio review checks claims, eligibility, coding, denial, payment, A/R, and billing QA together.",
        "claim_id": "CLM-034",
        "task_type": "FULL_RCM_REVIEW",
        "priority": "CRITICAL",
        "input_data": {"has_denial": True, "review_mode": "portfolio"},
        "next_action": "ESCALATE TO HUMAN REVIEW WITH AUDIT TRAIL",
        "agents_required": ["claims", "eligibility", "coding", "denial", "payment", "ar", "billing_qa"],
        "expected_statuses": ["REVIEW"],
        "expected_human_review": True,
        "expected_agents": ["claims", "eligibility", "coding", "denial", "payment", "ar", "billing_qa"],
        "exact_routing": True,
        "expected_external_action": False,
    },
]


def _load_records(filename: str) -> list[dict[str, Any]]:
    with (DATA_DIR / filename).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("records", [])


def _build_index(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(record.get(key)): record for record in records if record.get(key) is not None}


def _build_claim_lookups() -> dict[str, Any]:
    claims = _load_records("claims.json")
    patients = _load_records("patients.json")
    denials = _load_records("denials.json")
    payments = _load_records("payments.json")
    policies = _load_records("payer_policies.json")

    claim_by_id = _build_index(claims, "claim_id")
    patient_by_id = _build_index(patients, "patient_id")
    denial_by_id = _build_index(denials, "denial_id")
    payment_by_id = _build_index(payments, "payment_id")
    denial_by_claim: dict[str, list[dict[str, Any]]] = {}
    payment_by_claim: dict[str, list[dict[str, Any]]] = {}
    for denial in denials:
        claim_id = denial.get("claim_id")
        if claim_id:
            denial_by_claim.setdefault(str(claim_id), []).append(denial)
    for payment in payments:
        claim_id = payment.get("claim_id")
        if claim_id:
            payment_by_claim.setdefault(str(claim_id), []).append(payment)
    policy_by_payer = {str(policy.get("payer")): policy for policy in policies if policy.get("payer") is not None}

    def denial_lookup(identifier: str) -> dict[str, Any] | None:
        direct = denial_by_id.get(str(identifier))
        if direct is not None:
            return direct
        related = denial_by_claim.get(str(identifier), [])
        return related[0] if related else None

    return {
        "claim_by_id": claim_by_id,
        "patient_by_id": patient_by_id,
        "denial_by_id": denial_by_id,
        "denial_lookup": denial_lookup,
        "payment_by_id": payment_by_id,
        "denial_by_claim": denial_by_claim,
        "payment_by_claim": payment_by_claim,
        "policy_by_payer": policy_by_payer,
    }


def _build_agent_stack() -> dict[str, Any]:
    data = _build_claim_lookups()

    def claim_lookup(claim_id: str) -> dict[str, Any] | None:
        return data["claim_by_id"].get(str(claim_id))

    def patient_lookup(patient_id: str) -> dict[str, Any] | None:
        return data["patient_by_id"].get(str(patient_id))

    def denial_lookup(denial_id: str) -> dict[str, Any] | None:
        return data["denial_lookup"](str(denial_id))

    def payment_lookup(payment_id: str) -> dict[str, Any] | None:
        return data["payment_by_id"].get(str(payment_id))

    def denial_lookup_by_claim(claim_id: str) -> list[dict[str, Any]]:
        return data["denial_by_claim"].get(str(claim_id), [])

    def payment_lookup_by_claim(claim_id: str) -> list[dict[str, Any]]:
        return data["payment_by_claim"].get(str(claim_id), [])

    def claim_history_lookup(claim_id: str) -> list[dict[str, Any]]:
        return [entry for entry in data["claim_by_id"].values() if str(entry.get("patient_id")) == str(claim_id)]

    def payer_policy_lookup(payer: str) -> dict[str, Any] | None:
        return data["policy_by_payer"].get(str(payer))

    return {
        "claim_lookup": claim_lookup,
        "patient_lookup": patient_lookup,
        "claim_history_lookup": claim_history_lookup,
        "payer_policy_lookup": payer_policy_lookup,
        "denial_lookup": denial_lookup,
        "payment_lookup": payment_lookup,
        "denial_lookup_by_claim": denial_lookup_by_claim,
        "payment_lookup_by_claim": payment_lookup_by_claim,
    }


def _scenario_by_id(scenario_id: str) -> dict[str, Any]:
    for scenario in SCENARIO_LIBRARY:
        if scenario["id"] == scenario_id:
            return deepcopy(scenario)
    raise KeyError(f"Unknown demo scenario: {scenario_id}")


def _as_display_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return getattr(value, "__dict__", {})


def get_demo_scenarios() -> list[dict[str, Any]]:
    return [deepcopy(scenario) for scenario in SCENARIO_LIBRARY]


def run_demo_scenario(scenario_id: str) -> dict[str, Any]:
    scenario = _scenario_by_id(scenario_id)
    stack = _build_agent_stack()
    task = SupervisorTask(
        task_id=f"TASK-{scenario['id'].upper().replace('-', '_')}",
        claim_id=scenario["claim_id"],
        task_type=SupervisorTaskType(scenario["task_type"]),
        priority=SupervisorPriority(scenario.get("priority", "MEDIUM")),
        input_data=scenario.get("input_data", {}),
        requested_action=scenario.get("next_action"),
    )

    audit_trace: list[dict[str, Any]] = []

    result = RCMSupervisorAgent(
        claim_lookup=stack["claim_lookup"],
        patient_lookup=stack["patient_lookup"],
        claim_history_lookup=stack["claim_history_lookup"],
        payer_policy_lookup=stack["payer_policy_lookup"],
        eligibility_agent=EligibilityAgent(
            patient_lookup=stack["patient_lookup"],
            claim_lookup=stack["claim_lookup"],
        ),
        claims_agent=ClaimsAgent(
            claim_lookup=stack["claim_lookup"],
            patient_lookup=stack["patient_lookup"],
            eligibility_agent=EligibilityAgent(patient_lookup=stack["patient_lookup"], claim_lookup=stack["claim_lookup"]),
        ),
        coding_agent=CodingAgent(claim_lookup=stack["claim_lookup"]),
        denial_agent=DenialAgent(
            claim_lookup=stack["claim_lookup"],
            denial_lookup=lambda denial_id: stack["denial_lookup"](denial_id),
            patient_lookup=stack["patient_lookup"],
            claim_history_lookup=stack["claim_history_lookup"],
            payer_policy_lookup=stack["payer_policy_lookup"],
            eligibility_agent=EligibilityAgent(patient_lookup=stack["patient_lookup"], claim_lookup=stack["claim_lookup"]),
            coding_agent=CodingAgent(claim_lookup=stack["claim_lookup"]),
        ),
        payment_agent=PaymentAgent(
            claim_lookup=stack["claim_lookup"],
            payment_lookup=lambda payment_id: stack["payment_lookup"](payment_id),
            claim_history_lookup=stack["claim_history_lookup"],
            payer_policy_lookup=stack["payer_policy_lookup"],
            denial_lookup=lambda claim_id: stack["denial_lookup_by_claim"](claim_id),
        ),
        ar_agent=ARAgent(
            claim_lookup=stack["claim_lookup"],
            payment_lookup=stack["payment_lookup_by_claim"],
            payment_agent=PaymentAgent(
                claim_lookup=stack["claim_lookup"],
                payment_lookup=lambda payment_id: stack["payment_lookup"](payment_id),
                claim_history_lookup=stack["claim_history_lookup"],
                payer_policy_lookup=stack["payer_policy_lookup"],
                denial_lookup=lambda claim_id: stack["denial_lookup_by_claim"](claim_id),
            ),
            denial_lookup=stack["denial_lookup_by_claim"],
            denial_agent=DenialAgent(
                claim_lookup=stack["claim_lookup"],
                denial_lookup=lambda denial_id: stack["denial_lookup"](denial_id),
                patient_lookup=stack["patient_lookup"],
                claim_history_lookup=stack["claim_history_lookup"],
                payer_policy_lookup=stack["payer_policy_lookup"],
                eligibility_agent=EligibilityAgent(patient_lookup=stack["patient_lookup"], claim_lookup=stack["claim_lookup"]),
                coding_agent=CodingAgent(claim_lookup=stack["claim_lookup"]),
            ),
        ),
        billing_qa_agent=BillingQAAgent(
            claim_lookup=stack["claim_lookup"],
            patient_lookup=stack["patient_lookup"],
            payment_lookup=lambda payment_id: stack["payment_lookup"](payment_id),
            denial_lookup=lambda claim_id: stack["denial_lookup_by_claim"](claim_id),
            claim_history_lookup=stack["claim_history_lookup"],
            payer_policy_lookup=stack["payer_policy_lookup"],
            eligibility_agent=EligibilityAgent(patient_lookup=stack["patient_lookup"], claim_lookup=stack["claim_lookup"]),
            claims_agent=ClaimsAgent(
                claim_lookup=stack["claim_lookup"],
                patient_lookup=stack["patient_lookup"],
                eligibility_agent=EligibilityAgent(patient_lookup=stack["patient_lookup"], claim_lookup=stack["claim_lookup"]),
            ),
            coding_agent=CodingAgent(claim_lookup=stack["claim_lookup"]),
            denial_agent=DenialAgent(
                claim_lookup=stack["claim_lookup"],
                denial_lookup=lambda denial_id: stack["denial_lookup"](denial_id),
                patient_lookup=stack["patient_lookup"],
                claim_history_lookup=stack["claim_history_lookup"],
                payer_policy_lookup=stack["payer_policy_lookup"],
                eligibility_agent=EligibilityAgent(patient_lookup=stack["patient_lookup"], claim_lookup=stack["claim_lookup"]),
                coding_agent=CodingAgent(claim_lookup=stack["claim_lookup"]),
            ),
            payment_agent=PaymentAgent(
                claim_lookup=stack["claim_lookup"],
                payment_lookup=lambda payment_id: stack["payment_lookup"](payment_id),
                claim_history_lookup=stack["claim_history_lookup"],
                payer_policy_lookup=stack["payer_policy_lookup"],
                denial_lookup=lambda claim_id: stack["denial_lookup_by_claim"](claim_id),
            ),
            ar_agent=ARAgent(
                claim_lookup=stack["claim_lookup"],
                payment_lookup=stack["payment_lookup_by_claim"],
                payment_agent=PaymentAgent(
                    claim_lookup=stack["claim_lookup"],
                    payment_lookup=lambda payment_id: stack["payment_lookup"](payment_id),
                    claim_history_lookup=stack["claim_history_lookup"],
                    payer_policy_lookup=stack["payer_policy_lookup"],
                    denial_lookup=lambda claim_id: stack["denial_lookup_by_claim"](claim_id),
                ),
                denial_lookup=stack["denial_lookup_by_claim"],
                denial_agent=DenialAgent(
                    claim_lookup=stack["claim_lookup"],
                    denial_lookup=lambda denial_id: stack["denial_lookup"](denial_id),
                    patient_lookup=stack["patient_lookup"],
                    claim_history_lookup=stack["claim_history_lookup"],
                    payer_policy_lookup=stack["payer_policy_lookup"],
                    eligibility_agent=EligibilityAgent(patient_lookup=stack["patient_lookup"], claim_lookup=stack["claim_lookup"]),
                    coding_agent=CodingAgent(claim_lookup=stack["claim_lookup"]),
                ),
            ),
            expected_agents=scenario.get("agents_required", []),
        ),
        appeal_agent=AppealAgent(claim_lookup=stack["claim_lookup"], denial_lookup=stack["denial_lookup_by_claim"]),
        audit_sink=lambda action, details: audit_trace.append({"action": action, **details}),
    ).run(task)

    result_payload = json.loads(result.model_dump_json())
    result_payload["scenario_id"] = scenario["id"]
    result_payload["scenario_title"] = scenario["title"]
    result_payload["description"] = scenario["description"]
    result_payload["expected_next_action"] = scenario.get("next_action")
    result_payload["audit_trace"] = audit_trace
    result_payload["deterministic_findings"] = []
    for name, item in (result.agent_results or {}).items():
        payload = _as_display_dict(item)
        status = (
            payload.get("status")
            or payload.get("qa_status")
            or payload.get("eligibility_status")
            or getattr(item, "status", None)
            or getattr(item, "qa_status", None)
            or getattr(item, "eligibility_status", None)
            or "UNKNOWN"
        )
        risk_score = payload.get("risk_score", getattr(item, "risk_score", 0))
        summary = (
            payload.get("root_cause")
            or payload.get("explanation")
            or payload.get("denial_reason")
            or payload.get("message")
            or getattr(item, "root_cause", None)
            or getattr(item, "explanation", None)
            or getattr(item, "denial_reason", None)
            or getattr(item, "message", None)
            or "Deterministic review completed."
        )
        result_payload["deterministic_findings"].append({
            "agent": name,
            "status": status,
            "risk_score": risk_score,
            "summary": summary,
        })
    return result_payload
