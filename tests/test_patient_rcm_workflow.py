from __future__ import annotations

import pytest

from app.services.patient_rcm_workflow import (
    make_synthetic_claim,
    make_synthetic_patient,
    reset_demo_case,
    run_patient_rcm_workflow,
)


def test_synthetic_patient_creation() -> None:
    patient = make_synthetic_patient()
    assert patient["patient_id"].startswith("DEMO-P-")
    assert patient["member_id"].startswith("DEMO-MEMBER-")
    assert patient["payer"]


def test_synthetic_claim_creation() -> None:
    claim = make_synthetic_claim()
    assert claim["claim_id"].startswith("DEMO-CLM-")
    assert claim["provider_id"].startswith("DEMO-PROVIDER-")
    assert claim["claim_amount"] > 0


def test_claim_only_workflow() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-201")
    claim = make_synthetic_claim(patient_id="DEMO-P-201", claim_id="DEMO-CLM-201")

    result = run_patient_rcm_workflow(patient, claim)

    assert result.patient["patient_id"] == "DEMO-P-201"
    assert result.claim["claim_id"] == "DEMO-CLM-201"
    assert result.workflow_status in {"REVIEW", "COMPLETED", "WAITING", "READY"}
    assert any(step.step_name == "CLAIM_VALIDATION" for step in result.steps)
    assert any(step.step_name == "BILLING_QA" for step in result.steps)


def test_eligibility_workflow_runs_for_claim_review() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-202", payer="Demo Health Plan A")
    claim = make_synthetic_claim(patient_id="DEMO-P-202", claim_id="DEMO-CLM-202", payer="Demo Health Plan A")

    result = run_patient_rcm_workflow(patient, claim)

    assert any(step.step_name == "ELIGIBILITY" for step in result.steps)
    assert result.steps[0].step_name == "PATIENT_CREATED"


def test_coding_review_workflow() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-203")
    claim = make_synthetic_claim(patient_id="DEMO-P-203", claim_id="DEMO-CLM-203", icd_codes=["M54.5"], cpt_codes=["97110"], modifiers=[])

    result = run_patient_rcm_workflow(patient, claim)

    assert any(step.step_name == "CODING" for step in result.steps)
    assert result.agent_results.get("coding") is not None


def test_denial_workflow_when_denial_evidence_exists() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-204")
    claim = make_synthetic_claim(patient_id="DEMO-P-204", claim_id="DEMO-CLM-204", payer="Demo Health Plan D")
    denial = {
        "denial_id": "DEMO-DEN-204",
        "claim_id": "DEMO-CLM-204",
        "reason": "Eligibility denial: synthetic coverage mismatch detected.",
        "denied_amount": 120.00,
        "status": "OPEN",
    }

    result = run_patient_rcm_workflow(patient, claim, denial=denial)

    assert any(step.step_name == "DENIAL" for step in result.steps)
    assert any(step.step_name == "APPEAL" for step in result.steps)
    assert result.human_review_required is True


def test_payment_workflow_when_payment_evidence_exists() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-205")
    claim = make_synthetic_claim(patient_id="DEMO-P-205", claim_id="DEMO-CLM-205")
    payment = {
        "payment_id": "DEMO-PAY-205",
        "claim_id": "DEMO-CLM-205",
        "payer": "Demo Health Plan A",
        "paid_amount": 850.00,
        "status": "POSTED",
    }

    result = run_patient_rcm_workflow(patient, claim, payment=payment)

    assert any(step.step_name == "PAYMENT" for step in result.steps)
    assert any(step.step_name == "AR" for step in result.steps)
    assert result.agent_results.get("payment") is not None


def test_billing_qa_routing_and_supervisor_result_preservation() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-206")
    claim = make_synthetic_claim(patient_id="DEMO-P-206", claim_id="DEMO-CLM-206")
    result = run_patient_rcm_workflow(patient, claim)

    assert result.billing_qa_result
    assert result.supervisor_result.get("claim_id") == "DEMO-CLM-206"
    assert result.workflow_status == result.supervisor_result.get("status")
    assert result.risk_score == result.supervisor_result.get("risk_score")


def test_human_review_propagates_and_not_applicable_agents_are_not_fabricated() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-207")
    claim = make_synthetic_claim(patient_id="DEMO-P-207", claim_id="DEMO-CLM-207")
    denial = {
        "denial_id": "DEMO-DEN-207",
        "claim_id": "DEMO-CLM-207",
        "reason": "Medical necessity denial: synthetic policy mismatch.",
        "denied_amount": 200.00,
        "status": "OPEN",
    }

    result = run_patient_rcm_workflow(patient, claim, denial=denial)

    assert result.human_review_required is True
    assert any(step.step_name == "HUMAN_REVIEW" for step in result.steps)
    assert not any(step.step_name == "PAYMENT" for step in result.steps)


def test_risk_comes_from_authoritative_backend() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-208")
    claim = make_synthetic_claim(patient_id="DEMO-P-208", claim_id="DEMO-CLM-208")
    result = run_patient_rcm_workflow(patient, claim)

    assert result.risk_score == result.supervisor_result["risk_score"]
    assert result.priority == result.supervisor_result["priority"]


def test_reset_demo_case_behavior() -> None:
    reset_state = reset_demo_case()
    assert reset_state["synthetic_patient"] is None
    assert reset_state["synthetic_claim"] is None
    assert reset_state["human_review_decision"] is None


def test_no_external_action_is_recorded() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-209")
    claim = make_synthetic_claim(patient_id="DEMO-P-209", claim_id="DEMO-CLM-209")
    result = run_patient_rcm_workflow(patient, claim)

    warnings_text = " ".join(result.warnings).lower()
    assert "payment" not in warnings_text or "no external payer communication" in warnings_text
    assert "submit" not in warnings_text or "no external payer communication" in warnings_text


def test_deterministic_repeated_execution_is_stable() -> None:
    patient = make_synthetic_patient(patient_id="DEMO-P-210")
    claim = make_synthetic_claim(patient_id="DEMO-P-210", claim_id="DEMO-CLM-210")

    first = run_patient_rcm_workflow(patient, claim)
    second = run_patient_rcm_workflow(patient, claim)

    assert first.workflow_status == second.workflow_status
    assert first.risk_score == second.risk_score
    assert [step.step_name for step in first.steps] == [step.step_name for step in second.steps]


def test_malformed_synthetic_input_is_rejected_safely() -> None:
    with pytest.raises(ValueError):
        run_patient_rcm_workflow({}, {"claim_id": "BAD"})

    with pytest.raises(ValueError):
        run_patient_rcm_workflow(make_synthetic_patient(patient_id="DEMO-P-211"), {"patient_id": "DEMO-P-211"})
