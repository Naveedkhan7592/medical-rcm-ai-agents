from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

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
from app.schemas import BillingQAStatus, SupervisorPriority, SupervisorResult, SupervisorTask, SupervisorTaskType

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return getattr(value, "__dict__", {})


def _value(item: Any, name: str, default: Any = None) -> Any:
    if item is None:
        return default
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _ensure_date(value: Any, default: date | None = None) -> date | None:
    if value is None:
        return default
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return default
    return default


def _load_policy_records() -> dict[str, dict[str, Any]]:
    path = DATA_DIR / "payer_policies.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    records = payload.get("records", [])
    return {str(record.get("payer")): record for record in records if record.get("payer") is not None}


def _claim_history_lookup(claim_index: dict[str, dict[str, Any]], claim_id: str) -> list[dict[str, Any]]:
    claim = claim_index.get(str(claim_id))
    if claim is None:
        return []
    patient_id = str(claim.get("patient_id", ""))
    return [entry for entry in claim_index.values() if str(entry.get("patient_id", "")) == patient_id]


def _build_lookup_index(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(record.get(key)): record for record in records if record.get(key) is not None}


def _normalize_claim(claim: Any) -> dict[str, Any]:
    payload = _as_mapping(claim)
    if not payload:
        raise ValueError("Claim data is required for patient RCM workflow.")
    if not payload.get("claim_id"):
        raise ValueError("Synthetic claim requires a claim_id.")
    if not payload.get("patient_id"):
        raise ValueError("Synthetic claim requires a patient_id.")
    if not payload.get("payer"):
        raise ValueError("Synthetic claim requires a payer.")
    if not payload.get("service_date"):
        raise ValueError("Synthetic claim requires a service_date.")
    if payload.get("icd_codes") is None:
        payload["icd_codes"] = []
    if payload.get("cpt_codes") is None:
        payload["cpt_codes"] = []
    if payload.get("modifiers") is None:
        payload["modifiers"] = []
    if payload.get("status") is None:
        payload["status"] = "SUBMITTED"
    return payload


def _normalize_patient(patient: Any) -> dict[str, Any]:
    payload = _as_mapping(patient)
    if not payload:
        raise ValueError("Patient data is required for patient RCM workflow.")
    if not payload.get("patient_id"):
        raise ValueError("Synthetic patient requires a patient_id.")
    if not payload.get("name"):
        raise ValueError("Synthetic patient requires a name.")
    if not payload.get("date_of_birth"):
        raise ValueError("Synthetic patient requires a date_of_birth.")
    if not payload.get("payer"):
        raise ValueError("Synthetic patient requires a payer.")
    if not payload.get("member_id"):
        raise ValueError("Synthetic patient requires a member_id.")
    return payload


def _normalize_denial(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    denial = _as_mapping(value)
    if not denial:
        return None
    if not denial.get("denial_id"):
        denial["denial_id"] = f"DEMO-DEN-{denial.get('claim_id', 'CASE')}"
    if not denial.get("claim_id"):
        raise ValueError("Denial evidence requires a claim_id.")
    if not denial.get("reason"):
        denial["reason"] = "Synthetic denial evidence reviewed for workflow simulation."
    denial.setdefault("status", "OPEN")
    return denial


def _normalize_payment(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    payment = _as_mapping(value)
    if not payment:
        return None
    if not payment.get("payment_id"):
        payment["payment_id"] = f"DEMO-PAY-{payment.get('claim_id', 'CASE')}"
    if not payment.get("claim_id"):
        raise ValueError("Payment evidence requires a claim_id.")
    payment.setdefault("payer", "DEMO PAYOR")
    payment.setdefault("paid_amount", 0)
    payment.setdefault("status", "POSTED")
    return payment


def make_synthetic_patient(patient_id: str = "DEMO-P-101", *, name: str = "Demo Patient 101", date_of_birth: str | date = "1985-06-15", payer: str = "Demo Health Plan A", member_id: str = "DEMO-MEMBER-101") -> dict[str, Any]:
    return {
        "patient_id": patient_id,
        "name": name,
        "date_of_birth": date.fromisoformat(str(date_of_birth)) if not isinstance(date_of_birth, date) else date_of_birth,
        "payer": payer,
        "member_id": member_id,
    }


def make_synthetic_claim(
    *,
    patient_id: str = "DEMO-P-101",
    claim_id: str = "DEMO-CLM-101",
    payer: str = "Demo Health Plan A",
    provider_id: str = "DEMO-PROVIDER-01",
    service_date: str | date = "2026-02-14",
    icd_codes: list[str] | None = None,
    cpt_codes: list[str] | None = None,
    modifiers: list[str] | None = None,
    claim_amount: float = 1250.00,
    status: str = "PENDING",
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "patient_id": patient_id,
        "payer": payer,
        "provider_id": provider_id,
        "service_date": date.fromisoformat(str(service_date)) if not isinstance(service_date, date) else service_date,
        "icd_codes": icd_codes or ["Z00.00"],
        "cpt_codes": cpt_codes or ["99213"],
        "modifiers": modifiers or [],
        "claim_amount": float(claim_amount),
        "status": status,
    }


class WorkflowStep(BaseModel):
    step_name: str
    status: str = "NOT_APPLICABLE"
    executed: bool = False
    summary: str = ""
    risk: int | None = None
    requires_human_review: bool = False


class PatientRCMWorkflowResult(BaseModel):
    patient: dict[str, Any] = Field(default_factory=dict)
    claim: dict[str, Any] = Field(default_factory=dict)
    workflow_status: str = "NOT_STARTED"
    steps: list[WorkflowStep] = Field(default_factory=list)
    supervisor_result: dict[str, Any] = Field(default_factory=dict)
    billing_qa_result: dict[str, Any] = Field(default_factory=dict)
    human_review_required: bool = False
    risk_score: int = 0
    priority: str = "MEDIUM"
    next_action: str = ""
    audit_trace: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    agent_results: dict[str, Any] = Field(default_factory=dict)


def reset_demo_case() -> dict[str, Any]:
    return {
        "synthetic_patient": None,
        "synthetic_claim": None,
        "workflow_result": None,
        "human_review_decision": None,
    }


def run_patient_rcm_workflow(
    patient: Any,
    claim: Any,
    *,
    denial: Any | None = None,
    payment: Any | None = None,
    task_type: str | SupervisorTaskType | None = None,
    requested_action: str | None = None,
) -> PatientRCMWorkflowResult:
    patient_payload = _normalize_patient(patient)
    claim_payload = _normalize_claim(claim)
    claim_payload["patient_id"] = claim_payload.get("patient_id") or patient_payload["patient_id"]
    patient_payload["patient_id"] = patient_payload.get("patient_id") or claim_payload["patient_id"]
    denial_payload = _normalize_denial(denial)
    payment_payload = _normalize_payment(payment)

    patient_lookup = {str(patient_payload["patient_id"]): patient_payload}
    claim_index = {str(claim_payload["claim_id"]): claim_payload}
    claim_lookup = lambda claim_id: claim_index.get(str(claim_id))
    patient_lookup_fn = lambda patient_id: patient_lookup.get(str(patient_id))

    denial_lookup = lambda denial_id: {str(denial_payload["denial_id"]): denial_payload}.get(str(denial_id)) if denial_payload else None
    denial_by_claim = lambda claim_id: [denial_payload] if denial_payload and str(denial_payload.get("claim_id")) == str(claim_id) else []
    payment_lookup = lambda payment_id: {str(payment_payload["payment_id"]): payment_payload}.get(str(payment_id)) if payment_payload else None
    payment_by_claim = lambda claim_id: [payment_payload] if payment_payload and str(payment_payload.get("claim_id")) == str(claim_id) else []

    payer_policies = _load_policy_records()
    policy_lookup = lambda payer: payer_policies.get(str(payer))
    claim_history_lookup = lambda claim_id: _claim_history_lookup(claim_index, claim_id)

    audit_trace: list[dict[str, Any]] = []
    stacked_agent_arguments = {
        "claim_lookup": claim_lookup,
        "patient_lookup": patient_lookup_fn,
        "claim_history_lookup": claim_history_lookup,
        "payer_policy_lookup": policy_lookup,
        "eligibility_agent": EligibilityAgent(
            patient_lookup=patient_lookup_fn,
            claim_lookup=claim_lookup,
        ),
        "claims_agent": ClaimsAgent(
            claim_lookup=claim_lookup,
            patient_lookup=patient_lookup_fn,
            eligibility_agent=EligibilityAgent(
                patient_lookup=patient_lookup_fn,
                claim_lookup=claim_lookup,
            ),
        ),
        "coding_agent": CodingAgent(claim_lookup=claim_lookup),
        "denial_agent": DenialAgent(
            claim_lookup=claim_lookup,
            denial_lookup=denial_lookup,
            patient_lookup=patient_lookup_fn,
            claim_history_lookup=claim_history_lookup,
            payer_policy_lookup=policy_lookup,
            eligibility_agent=EligibilityAgent(
                patient_lookup=patient_lookup_fn,
                claim_lookup=claim_lookup,
            ),
            coding_agent=CodingAgent(claim_lookup=claim_lookup),
        ),
        "payment_agent": PaymentAgent(
            claim_lookup=claim_lookup,
            payment_lookup=payment_lookup,
            claim_history_lookup=claim_history_lookup,
            payer_policy_lookup=policy_lookup,
            denial_lookup=denial_by_claim,
        ),
        "ar_agent": ARAgent(
            claim_lookup=claim_lookup,
            payment_lookup=payment_by_claim,
            payment_agent=PaymentAgent(
                claim_lookup=claim_lookup,
                payment_lookup=payment_lookup,
                claim_history_lookup=claim_history_lookup,
                payer_policy_lookup=policy_lookup,
                denial_lookup=denial_by_claim,
            ),
            denial_lookup=denial_by_claim,
            denial_agent=DenialAgent(
                claim_lookup=claim_lookup,
                denial_lookup=denial_lookup,
                patient_lookup=patient_lookup_fn,
                claim_history_lookup=claim_history_lookup,
                payer_policy_lookup=policy_lookup,
                eligibility_agent=EligibilityAgent(
                    patient_lookup=patient_lookup_fn,
                    claim_lookup=claim_lookup,
                ),
                coding_agent=CodingAgent(claim_lookup=claim_lookup),
            ),
        ),
        "billing_qa_agent": BillingQAAgent(
            claim_lookup=claim_lookup,
            patient_lookup=patient_lookup_fn,
            payment_lookup=payment_lookup,
            denial_lookup=denial_by_claim,
            claim_history_lookup=claim_history_lookup,
            payer_policy_lookup=policy_lookup,
            eligibility_agent=EligibilityAgent(
                patient_lookup=patient_lookup_fn,
                claim_lookup=claim_lookup,
            ),
            claims_agent=ClaimsAgent(
                claim_lookup=claim_lookup,
                patient_lookup=patient_lookup_fn,
                eligibility_agent=EligibilityAgent(
                    patient_lookup=patient_lookup_fn,
                    claim_lookup=claim_lookup,
                ),
            ),
            coding_agent=CodingAgent(claim_lookup=claim_lookup),
            denial_agent=DenialAgent(
                claim_lookup=claim_lookup,
                denial_lookup=denial_lookup,
                patient_lookup=patient_lookup_fn,
                claim_history_lookup=claim_history_lookup,
                payer_policy_lookup=policy_lookup,
                eligibility_agent=EligibilityAgent(
                    patient_lookup=patient_lookup_fn,
                    claim_lookup=claim_lookup,
                ),
                coding_agent=CodingAgent(claim_lookup=claim_lookup),
            ),
            payment_agent=PaymentAgent(
                claim_lookup=claim_lookup,
                payment_lookup=payment_lookup,
                claim_history_lookup=claim_history_lookup,
                payer_policy_lookup=policy_lookup,
                denial_lookup=denial_by_claim,
            ),
            ar_agent=ARAgent(
                claim_lookup=claim_lookup,
                payment_lookup=payment_by_claim,
                payment_agent=PaymentAgent(
                    claim_lookup=claim_lookup,
                    payment_lookup=payment_lookup,
                    claim_history_lookup=claim_history_lookup,
                    payer_policy_lookup=policy_lookup,
                    denial_lookup=denial_by_claim,
                ),
                denial_lookup=denial_by_claim,
                denial_agent=DenialAgent(
                    claim_lookup=claim_lookup,
                    denial_lookup=denial_lookup,
                    patient_lookup=patient_lookup_fn,
                    claim_history_lookup=claim_history_lookup,
                    payer_policy_lookup=policy_lookup,
                    eligibility_agent=EligibilityAgent(
                        patient_lookup=patient_lookup_fn,
                        claim_lookup=claim_lookup,
                    ),
                    coding_agent=CodingAgent(claim_lookup=claim_lookup),
                ),
            ),
        ),
        "appeal_agent": AppealAgent(claim_lookup=claim_lookup, denial_lookup=denial_by_claim),
    }

    if task_type is None:
        if denial_payload and payment_payload:
            chosen_type = SupervisorTaskType.FULL_RCM_REVIEW
        elif denial_payload:
            chosen_type = SupervisorTaskType.DENIAL_REVIEW
        elif payment_payload:
            chosen_type = SupervisorTaskType.PAYMENT_REVIEW
        else:
            chosen_type = SupervisorTaskType.CLAIM_REVIEW
    else:
        chosen_type = SupervisorTaskType(str(task_type))

    input_data: dict[str, Any] = {
        "patient_id": patient_payload.get("patient_id"),
        "claim_id": claim_payload.get("claim_id"),
        "has_denial": bool(denial_payload),
        "has_payment": bool(payment_payload),
        "review_mode": "synthetic_patient_workflow",
    }
    if denial_payload:
        input_data["denial_category"] = str(denial_payload.get("reason", "")).split(":", 1)[0].upper() if denial_payload.get("reason") else "UNKNOWN"
    if requested_action is None:
        requested_action = "EVALUATE SYNTHETIC CLAIM FOR DETERMINISTIC RCM REVIEW"

    task = SupervisorTask(
        task_id=f"TASK-{str(claim_payload['claim_id']).upper().replace('-', '_')}",
        claim_id=str(claim_payload["claim_id"]),
        task_type=chosen_type,
        priority=SupervisorPriority.HIGH if chosen_type == SupervisorTaskType.FULL_RCM_REVIEW else SupervisorPriority.MEDIUM,
        input_data=input_data,
        requested_action=requested_action,
    )

    result = RCMSupervisorAgent(
        claim_lookup=claim_lookup,
        patient_lookup=patient_lookup_fn,
        claim_history_lookup=claim_history_lookup,
        payer_policy_lookup=policy_lookup,
        eligibility_agent=stacked_agent_arguments["eligibility_agent"],
        claims_agent=stacked_agent_arguments["claims_agent"],
        coding_agent=stacked_agent_arguments["coding_agent"],
        denial_agent=stacked_agent_arguments["denial_agent"],
        payment_agent=stacked_agent_arguments["payment_agent"],
        ar_agent=stacked_agent_arguments["ar_agent"],
        billing_qa_agent=stacked_agent_arguments["billing_qa_agent"],
        appeal_agent=stacked_agent_arguments["appeal_agent"],
        audit_sink=lambda action, details: audit_trace.append({"action": action, **details}),
    ).run(task)

    result_payload = result.model_dump()
    agent_results = result_payload.get("agent_results", {})
    workflow_status = result_payload.get("status") or "UNKNOWN"
    steps: list[WorkflowStep] = []

    def add_step(name: str, *, value: Any, executed: bool, summary: str = "", risk: int | None = None, requires_human_review: bool = False) -> None:
        status = str(value).upper() if value is not None else "NOT_APPLICABLE"
        steps.append(
            WorkflowStep(
                step_name=name,
                status=status,
                executed=executed,
                summary=summary or "No additional review was required for this synthetic workflow step.",
                risk=risk,
                requires_human_review=requires_human_review,
            )
        )

    add_step("PATIENT_CREATED", value="PASS", executed=True, summary="Synthetic patient record was created in the interactive demo session.", risk=0)
    add_step("CLAIM_CREATED", value="PASS", executed=True, summary="Synthetic claim record was created without external submission.", risk=0)

    if patient_payload:
        eligibility_result = agent_results.get("eligibility")
        eligibility_status = _value(eligibility_result, "eligibility_status", _value(eligibility_result, "status", "NOT_APPLICABLE"))
        add_step(
            "ELIGIBILITY",
            value=eligibility_status,
            executed=eligibility_result is not None,
            summary="Synthetic eligibility and benefit checks were run for the patient and claim.",
            risk=_value(eligibility_result, "risk_score", 0) if eligibility_result is not None else 0,
            requires_human_review=_value(eligibility_result, "requires_human_review", False) if eligibility_result is not None else False,
        )

    if claim_payload:
        coding_result = agent_results.get("coding")
        coding_status = _value(coding_result, "status", _value(coding_result, "coding_status", "NOT_APPLICABLE"))
        add_step(
            "CODING",
            value=coding_status,
            executed=coding_result is not None,
            summary="Deterministic coding validation checked the selected ICD/CPT and modifier evidence.",
            risk=_value(coding_result, "risk_score", 0) if coding_result is not None else 0,
            requires_human_review=_value(coding_result, "requires_human_review", False) if coding_result is not None else False,
        )

        claims_result = agent_results.get("claims")
        claims_status = _value(claims_result, "status", "NOT_APPLICABLE")
        add_step(
            "CLAIM_VALIDATION",
            value=claims_status,
            executed=claims_result is not None,
            summary="Deterministic claim validation checked required fields, payer details, and eligibility consistency.",
            risk=_value(claims_result, "risk_score", 0) if claims_result is not None else 0,
            requires_human_review=_value(claims_result, "requires_human_review", False) if claims_result is not None else False,
        )

    if denial_payload:
        denial_result = agent_results.get("denial")
        denial_status = _value(denial_result, "status", _value(denial_result, "denial_status", "NOT_APPLICABLE"))
        add_step(
            "DENIAL",
            value=denial_status,
            executed=denial_result is not None,
            summary="Denial evidence was reviewed and classified by the deterministic denial agent.",
            risk=_value(denial_result, "risk_score", 0) if denial_result is not None else 0,
            requires_human_review=_value(denial_result, "requires_human_review", False) if denial_result is not None else False,
        )

    if payment_payload:
        payment_result = agent_results.get("payment")
        payment_status = _value(payment_result, "status", _value(payment_result, "payment_status", "NOT_APPLICABLE"))
        add_step(
            "PAYMENT",
            value=payment_status,
            executed=payment_result is not None,
            summary="The synthetic payment record was evaluated for reconciliation and classification.",
            risk=_value(payment_result, "risk_score", 0) if payment_result is not None else 0,
            requires_human_review=_value(payment_result, "requires_human_review", False) if payment_result is not None else False,
        )

        ar_result = agent_results.get("ar")
        ar_status = _value(ar_result, "status", _value(ar_result, "ar_status", "NOT_APPLICABLE"))
        add_step(
            "AR",
            value=ar_status,
            executed=ar_result is not None,
            summary="A/R aging and balance context were assessed for the synthetic claim.",
            risk=_value(ar_result, "risk_score", 0) if ar_result is not None else 0,
            requires_human_review=_value(ar_result, "requires_human_review", False) if ar_result is not None else False,
        )

    billing_result = agent_results.get("billing_qa")
    if billing_result is not None:
        billing_status = _value(billing_result, "qa_status", _value(billing_result, "status", "NOT_APPLICABLE"))
        add_step(
            "BILLING_QA",
            value=billing_status,
            executed=True,
            summary="Cross-agent consistency checks were performed to validate the selected workflow route.",
            risk=_value(billing_result, "risk_score", 0),
            requires_human_review=_value(billing_result, "requires_human_review", False),
        )
    else:
        add_step("BILLING_QA", value="NOT_APPLICABLE", executed=False, summary="Billing QA only runs when the route has relevant evidence to validate.")

    supervisor_status = result_payload.get("status", "UNKNOWN")
    add_step(
        "SUPERVISOR",
        value=supervisor_status,
        executed=True,
        summary="Supervisor routed the claim through the selected deterministic workflow branch.",
        risk=result_payload.get("risk_score", 0),
        requires_human_review=result_payload.get("human_review_required", False),
    )

    appeal_result = agent_results.get("appeal")
    if appeal_result is not None:
        appeal_status = _value(appeal_result, "appeal_readiness", _value(appeal_result, "status", "NOT_APPLICABLE"))
        add_step(
            "APPEAL",
            value=appeal_status,
            executed=True,
            summary="Appeal readiness was evaluated only when denial evidence required it.",
            risk=_value(appeal_result, "risk_score", 0),
            requires_human_review=_value(appeal_result, "human_review_required", True),
        )
    else:
        add_step("APPEAL", value="NOT_APPLICABLE", executed=False, summary="Appeal review is only relevant when a denial requires appeal preparation.")

    add_step(
        "HUMAN_REVIEW",
        value="REQUIRED" if result_payload.get("human_review_required") else "NOT_REQUIRED",
        executed=True,
        summary="Human review is required only when the deterministic route flags unresolved or high-risk conditions.",
        risk=result_payload.get("risk_score", 0),
        requires_human_review=result_payload.get("human_review_required", False),
    )

    warnings = list(result_payload.get("warnings") or [])
    if not warnings:
        warnings.append("Synthetic workflow only; no external payer communication, submission, or payment posting occurred.")

    return PatientRCMWorkflowResult(
        patient=patient_payload,
        claim=claim_payload,
        workflow_status=str(workflow_status),
        steps=steps,
        supervisor_result=result_payload,
        billing_qa_result=billing_result or {},
        human_review_required=bool(result_payload.get("human_review_required", False)),
        risk_score=int(result_payload.get("risk_score", 0) or 0),
        priority=str(result_payload.get("priority") or "MEDIUM"),
        next_action=str(result_payload.get("next_action") or "NO_ACTION_REQUIRED"),
        audit_trace=audit_trace,
        warnings=warnings,
        agent_results=agent_results,
    )
