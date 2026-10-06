from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import streamlit as st

from app.services.demo_scenarios import run_demo_scenario
from app.services.patient_rcm_workflow import (
    make_synthetic_claim,
    make_synthetic_patient,
    run_patient_rcm_workflow,
)
from dashboard.components import ar_table, claims_table, denials_table, format_currency, metric_card, payments_table
from dashboard.data_service import load_dashboard_data, load_demo_scenarios, load_evaluation_summary
from dashboard.metrics import compute_overview_metrics


st.set_page_config(page_title="RCM Operations Dashboard", layout="wide")


def _safe_decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def _claim_payment_totals(claims: list[dict], payments: list[dict]) -> tuple[Decimal, Decimal, Decimal]:
    billed = sum(_safe_decimal(item.get("claim_amount", 0)) or Decimal("0") for item in claims)
    paid = sum(_safe_decimal(item.get("paid_amount", 0)) or Decimal("0") for item in payments)
    denied_total = sum(_safe_decimal(item.get("denied_amount", 0)) or Decimal("0") for item in load_dashboard_data()["denials"])
    return billed, paid, denied_total


def _calculate_ar_rows(claims: list[dict], payments: list[dict]) -> list[dict]:
    payment_by_claim: dict[str, Decimal] = {}
    for payment in payments:
        claim_id = payment.get("claim_id")
        if not claim_id:
            continue
        payment_by_claim[claim_id] = payment_by_claim.get(claim_id, Decimal("0")) + (_safe_decimal(payment.get("paid_amount", 0)) or Decimal("0"))

    rows: list[dict] = []
    for claim in claims:
        claim_id = claim.get("claim_id")
        billed = _safe_decimal(claim.get("claim_amount", 0)) or Decimal("0")
        paid = payment_by_claim.get(claim_id, Decimal("0"))
        outstanding = max(billed - paid, Decimal("0"))
        service_date = claim.get("service_date")
        age_days = 0
        if service_date:
            service_dt = date.fromisoformat(str(service_date))
            age_days = (datetime.now(timezone.utc).date() - service_dt).days
        bucket = "CURRENT_0_30"
        if age_days > 365:
            bucket = "DAYS_366_PLUS"
        elif age_days > 181:
            bucket = "DAYS_181_365"
        elif age_days > 121:
            bucket = "DAYS_121_180"
        elif age_days > 91:
            bucket = "DAYS_91_120"
        elif age_days > 61:
            bucket = "DAYS_61_90"
        elif age_days > 31:
            bucket = "DAYS_31_60"
        rows.append(
            {
                "claim_id": claim_id,
                "outstanding_balance": outstanding,
                "ar_age_days": age_days,
                "aging_bucket": bucket,
                "ar_status": "OPEN" if outstanding > 0 else "NO_BALANCE",
                "recommended_work_type": "MONITOR" if outstanding > 0 else "NO_ACTION",
            }
        )
    return rows


def _human_review_queue(denials: list[dict]) -> list[dict]:
    queue = []
    for denial in denials:
        if str(denial.get("status", "OPEN")).upper() in {"OPEN", "PENDING", "REVIEW"}:
            queue.append(
                {
                    "claim_id": denial.get("claim_id"),
                    "denial_id": denial.get("denial_id"),
                    "reason": denial.get("reason", "Pending review"),
                    "status": denial.get("status", "OPEN"),
                    "risk_score": min(int(float(denial.get("denied_amount", 0)) // 10), 100),
                }
            )
    return queue[:10]


def _default_patient() -> dict:
    return make_synthetic_patient()


def _default_claim(patient_id: str | None = None) -> dict:
    patient_key = patient_id or "DEMO-P-101"
    return make_synthetic_claim(patient_id=patient_key, claim_id="DEMO-CLM-101")


with st.sidebar:
    st.title("RCM Portfolio")
    page = st.radio("Navigation", ["Executive Overview", "Claims", "Denials", "Payments", "A/R", "Human Review", "Patient RCM Workflow", "Demo Scenarios", "Agent Evaluation"])

if "synthetic_patient" not in st.session_state:
    st.session_state.synthetic_patient = _default_patient()
if "synthetic_claim" not in st.session_state:
    st.session_state.synthetic_claim = _default_claim(st.session_state.synthetic_patient["patient_id"])
if "workflow_result" not in st.session_state:
    st.session_state.workflow_result = None
if "human_review_decision" not in st.session_state:
    st.session_state.human_review_decision = None


data = load_dashboard_data()
claims = data["claims"]
denials = data["denials"]
payments = data["payments"]

if page == "Executive Overview":
    st.title("Executive Overview")
    total_billed, total_paid, total_denied = _claim_payment_totals(claims, payments)
    metrics = compute_overview_metrics(
        total_claims=len(claims),
        total_billed_amount=total_billed,
        total_paid_amount=total_paid,
        total_denials=len(denials),
        outstanding_ar=sum((_safe_decimal(row["outstanding_balance"]) or Decimal("0")) for row in _calculate_ar_rows(claims, payments)),
        human_review_queue=len(_human_review_queue(denials)),
        high_risk_items=sum(1 for row in _human_review_queue(denials) if row["risk_score"] >= 50),
    )

    cards = [
        metric_card("Total Claims", metrics["total_claims"]),
        metric_card("Total Billed Amount", format_currency(metrics["total_billed_amount"])),
        metric_card("Total Paid Amount", format_currency(metrics["total_paid_amount"])),
        metric_card("Outstanding A/R", format_currency(metrics["outstanding_ar"])),
        metric_card("Total Denials", metrics["total_denials"]),
        metric_card("Denial Rate", f"{metrics['denial_rate']}%" if metrics["denial_rate"] is not None else "N/A"),
        metric_card("Human Review Queue", metrics["human_review_queue"]),
        metric_card("High/Critical Risk Items", metrics["high_risk_items"]),
    ]

    cols = st.columns(len(cards))
    for column, item in zip(cols, cards):
        with column:
            st.metric(item["title"], item["value"])

    st.subheader("Synthetic Portfolio Summary")
    summary_df = pd.DataFrame(
        [
            {"Metric": "Claims", "Value": str(metrics["total_claims"])},
            {"Metric": "Billed", "Value": str(metrics["total_billed_amount"])},
            {"Metric": "Paid", "Value": str(metrics["total_paid_amount"])},
            {"Metric": "Outstanding A/R", "Value": str(metrics["outstanding_ar"])},
            {"Metric": "Denials", "Value": str(metrics["total_denials"])},
            {"Metric": "Denial Rate %", "Value": str(metrics["denial_rate"]) if metrics["denial_rate"] is not None else "N/A"},
        ]
    )
    st.dataframe(summary_df, width="stretch")

elif page == "Claims":
    st.title("Claims Operations")
    claim_df = claims_table(claims)
    status_filter = st.selectbox("Status", ["ALL", *sorted({claim.get("status", "UNKNOWN") for claim in claims})])
    payer_filter = st.selectbox("Payer", ["ALL", *sorted({claim.get("payer", "UNKNOWN") for claim in claims})])
    filtered = claim_df.copy()
    if status_filter != "ALL":
        filtered = filtered[filtered["status"] == status_filter]
    if payer_filter != "ALL":
        filtered = filtered[filtered["payer"] == payer_filter]
    st.dataframe(filtered, width="stretch")

elif page == "Denials":
    st.title("Denial Management")
    denial_df = denials_table(denials)
    denial_status = st.selectbox("Status", ["ALL", *sorted({row.get("status", "UNKNOWN") for row in denials})])
    if denial_status != "ALL":
        denial_df = denial_df[denial_df["status"] == denial_status]
    st.dataframe(denial_df, width="stretch")

    if not denial_df.empty:
        category_counts = denial_df["reason"].str.extract(r"([A-Za-z ]+):")[0].value_counts().head()
        st.subheader("Reason Distribution")
        st.bar_chart(category_counts)

elif page == "Payments":
    st.title("Payment Operations")
    payment_df = payments_table(payments)
    payer_filter = st.selectbox("Payer", ["ALL", *sorted({row.get("payer", "UNKNOWN") for row in payments})])
    if payer_filter != "ALL":
        payment_df = payment_df[payment_df["payer"] == payer_filter]
    st.dataframe(payment_df, width="stretch")

elif page == "A/R":
    st.title("Accounts Receivable")
    ar_rows = _calculate_ar_rows(claims, payments)
    ar_df = ar_table(ar_rows)
    st.dataframe(ar_df, width="stretch")

elif page == "Patient RCM Workflow":
    st.title("Patient RCM Workflow")
    st.markdown("<div style='padding: 0.75rem; background: #fff3cd; border: 1px solid #ffe69c; border-radius: 0.5rem; color: #664d03; font-weight: 600;'>Synthetic Demo Only — Do not enter real patient information or PHI.</div>", unsafe_allow_html=True)
    st.caption("This simulator does not submit claims, appeals, or payments. No payer communication occurs. No patient account is modified externally.")

    col1, col2 = st.columns([1.2, 1.2])
    with col1:
        patient_form = st.form("synthetic_patient_form")
        with patient_form:
            st.subheader("Synthetic Patient")
            patient_data = {
                "patient_id": st.text_input("Patient ID", value=st.session_state.synthetic_patient.get("patient_id", "DEMO-P-101"), help="Synthetic identifier only."),
                "name": st.text_input("Name", value=st.session_state.synthetic_patient.get("name", "Demo Patient 101"), help="Synthetic demo name only."),
                "date_of_birth": st.date_input("Date of birth", value=_safe_decimal(st.session_state.synthetic_patient.get("date_of_birth", date.today())) if False else st.session_state.synthetic_patient.get("date_of_birth", date(1985, 6, 15)), help="Synthetic demo date only."),
                "payer": st.text_input("Payer", value=st.session_state.synthetic_patient.get("payer", "Demo Health Plan A"), help="Synthetic payer label only."),
                "member_id": st.text_input("Member ID", value=st.session_state.synthetic_patient.get("member_id", "DEMO-MEMBER-101"), help="Synthetic member identifier only."),
            }
            st.caption("Synthetic identifiers are used only in this demo. Do not enter SSN, real addresses, or PHI.")
            st.subheader("Synthetic Claim")
            claim_data = {
                "claim_id": st.text_input("Claim ID", value=st.session_state.synthetic_claim.get("claim_id", "DEMO-CLM-101"), help="Synthetic claim identifier only."),
                "patient_id": st.text_input("Patient ID (claim)", value=st.session_state.synthetic_claim.get("patient_id", patient_data["patient_id"]), help="Matches the synthetic patient record."),
                "payer": st.text_input("Claim payer", value=st.session_state.synthetic_claim.get("payer", patient_data["payer"]), help="Synthetic payer label only."),
                "provider_id": st.text_input("Provider ID", value=st.session_state.synthetic_claim.get("provider_id", "DEMO-PROVIDER-01")),
                "service_date": st.date_input("Service date", value=st.session_state.synthetic_claim.get("service_date", date(2026, 2, 14))),
                "icd_codes": st.text_input("ICD codes", value=", ".join(st.session_state.synthetic_claim.get("icd_codes", ["Z00.00"]))),
                "cpt_codes": st.text_input("CPT codes", value=", ".join(st.session_state.synthetic_claim.get("cpt_codes", ["99213"]))),
                "modifiers": st.text_input("Modifiers", value=", ".join(st.session_state.synthetic_claim.get("modifiers", []))),
                "claim_amount": st.number_input("Claim amount", min_value=0.0, value=float(st.session_state.synthetic_claim.get("claim_amount", 1250.00)), step=25.0),
                "status": st.selectbox("Status", ["PENDING", "SUBMITTED", "REVIEW", "DENIED", "PAID"], index=["PENDING", "SUBMITTED", "REVIEW", "DENIED", "PAID"].index(st.session_state.synthetic_claim.get("status", "PENDING"))),
            }
            with st.expander("Optional synthetic evidence"):
                has_denial = st.checkbox("Add denial evidence", value=False)
                has_payment = st.checkbox("Add payment evidence", value=False)
                denial_reason = st.text_input("Denial reason", value="Eligibility denial: synthetic coverage mismatch detected.") if has_denial else ""
                denial_amount = st.number_input("Denied amount", value=100.0, step=10.0) if has_denial else 0.0
                payment_amount = st.number_input("Paid amount", value=850.0, step=25.0) if has_payment else 0.0
            submitted = st.form_submit_button("Run synthetic workflow")
            if submitted:
                patient_payload = {
                    "patient_id": patient_data["patient_id"],
                    "name": patient_data["name"],
                    "date_of_birth": patient_data["date_of_birth"],
                    "payer": patient_data["payer"],
                    "member_id": patient_data["member_id"],
                }
                claim_payload = {
                    "claim_id": claim_data["claim_id"],
                    "patient_id": claim_data["patient_id"],
                    "payer": claim_data["payer"],
                    "provider_id": claim_data["provider_id"],
                    "service_date": claim_data["service_date"],
                    "icd_codes": [value.strip() for value in str(claim_data["icd_codes"]).split(",") if value.strip()],
                    "cpt_codes": [value.strip() for value in str(claim_data["cpt_codes"]).split(",") if value.strip()],
                    "modifiers": [value.strip() for value in str(claim_data["modifiers"]).split(",") if value.strip()],
                    "claim_amount": float(claim_data["claim_amount"]),
                    "status": claim_data["status"],
                }
                denial_payload = None
                if has_denial:
                    denial_payload = {
                        "denial_id": f"DEMO-DEN-{claim_payload['claim_id']}",
                        "claim_id": claim_payload["claim_id"],
                        "reason": denial_reason or "Eligibility denial: synthetic coverage mismatch detected.",
                        "denied_amount": float(denial_amount),
                        "status": "OPEN",
                    }
                payment_payload = None
                if has_payment:
                    payment_payload = {
                        "payment_id": f"DEMO-PAY-{claim_payload['claim_id']}",
                        "claim_id": claim_payload["claim_id"],
                        "payer": claim_payload["payer"],
                        "paid_amount": float(payment_amount),
                        "status": "POSTED",
                    }
                result = run_patient_rcm_workflow(patient_payload, claim_payload, denial=denial_payload, payment=payment_payload)
                st.session_state.synthetic_patient = patient_payload
                st.session_state.synthetic_claim = claim_payload
                st.session_state.workflow_result = result.model_dump()
                st.session_state.human_review_decision = None
                st.rerun()

    if st.session_state.workflow_result:
        workflow_result = st.session_state.workflow_result
        st.subheader("Case Summary")
        summary_columns = st.columns(5)
        with summary_columns[0]:
            st.metric("Patient ID", workflow_result["patient"]["patient_id"])
        with summary_columns[1]:
            st.metric("Claim ID", workflow_result["claim"]["claim_id"])
        with summary_columns[2]:
            st.metric("Payer", workflow_result["claim"]["payer"])
        with summary_columns[3]:
            st.metric("Claim amount", format_currency(workflow_result["claim"]["claim_amount"]))
        with summary_columns[4]:
            st.metric("Workflow status", workflow_result["workflow_status"])

        st.markdown("**Risk score**: " + str(workflow_result["risk_score"]))
        st.markdown("**Priority**: " + str(workflow_result["priority"]))
        st.markdown("**Human review**: " + ("Required" if workflow_result["human_review_required"] else "Not required"))
        st.markdown("**Next action**: " + str(workflow_result["next_action"]))

        st.subheader("Workflow progress")
        for step in workflow_result["steps"]:
            status_label = "PASS" if step["status"] == "PASS" else step["status"]
            st.write(f"{step['step_name']}: {status_label}")

        st.subheader("Agent details")
        agent_results = workflow_result.get("agent_results", {})
        if "eligibility" in agent_results:
            with st.expander("Eligibility Findings"):
                st.json(agent_results["eligibility"])
        if "coding" in agent_results:
            with st.expander("Coding Findings"):
                st.json(agent_results["coding"])
        if "claims" in agent_results:
            with st.expander("Claim Validation"):
                st.json(agent_results["claims"])
        if "denial" in agent_results:
            with st.expander("Denial Analysis"):
                st.json(agent_results["denial"])
        if "payment" in agent_results:
            with st.expander("Payment Analysis"):
                st.json(agent_results["payment"])
        if "ar" in agent_results:
            with st.expander("A/R Analysis"):
                st.json(agent_results["ar"])
        if "billing_qa" in agent_results:
            with st.expander("Billing QA"):
                st.json(agent_results["billing_qa"])
        with st.expander("Supervisor Decision"):
            st.json(workflow_result["supervisor_result"])
        if "appeal" in agent_results:
            with st.expander("Appeal Readiness"):
                st.json(agent_results["appeal"])

        if workflow_result["human_review_required"]:
            st.subheader("Human Review")
            st.info("Demo Human Review Decision")
            st.write(f"Reason: {workflow_result['supervisor_result'].get('reasons', ['Deterministic review requires human oversight.'])}")
            st.write(f"Risk: {workflow_result['risk_score']}")
            st.write(f"Priority: {workflow_result['priority']}")
            st.write(f"Missing information: {workflow_result['supervisor_result'].get('missing_information', [])}")
            st.write(f"Recommended next action: {workflow_result['next_action']}")
            decision = st.radio("Demo Human Review Decision", ["APPROVE", "REJECT", "REQUEST_MORE_INFORMATION"], index=0, key="human_review_decision_radio")
            if st.button("Submit Demo Human Review Decision"):
                st.session_state.human_review_decision = decision
                st.success(f"Demo decision recorded: {decision}. No external claim, appeal, or payment action was taken.")

        st.subheader("Audit trace")
        st.json(workflow_result.get("audit_trace", [])[-12:])

        st.subheader("Final case summary")
        summary_payload = {
            "synthetic_patient": workflow_result["patient"],
            "claim": workflow_result["claim"],
            "agents_executed": sorted(workflow_result.get("agent_results", {}).keys()),
            "workflow_status": workflow_result["workflow_status"],
            "risk_score": workflow_result["risk_score"],
            "priority": workflow_result["priority"],
            "billing_qa": workflow_result.get("billing_qa_result", {}),
            "human_review": workflow_result["human_review_required"],
            "next_action": workflow_result["next_action"],
            "warnings": workflow_result.get("warnings", []),
        }
        st.json(summary_payload)
        st.download_button(
            label="Download synthetic JSON case report",
            data=json.dumps(summary_payload, indent=2, default=str),
            file_name="synthetic_patient_rcm_workflow.json",
            mime="application/json",
        )

        if st.button("Reset Demo Case"):
            st.session_state.synthetic_patient = _default_patient()
            st.session_state.synthetic_claim = _default_claim(st.session_state.synthetic_patient["patient_id"])
            st.session_state.workflow_result = None
            st.session_state.human_review_decision = None
            st.rerun()
    else:
        st.info("Run the workflow to generate a synthetic patient-to-RCM case summary.")
        if st.button("Reset Demo Case"):
            st.session_state.synthetic_patient = _default_patient()
            st.session_state.synthetic_claim = _default_claim(st.session_state.synthetic_patient["patient_id"])
            st.session_state.workflow_result = None
            st.session_state.human_review_decision = None
            st.rerun()

elif page == "Demo Scenarios":
    st.title("End-to-End Demo Scenarios")
    scenarios = load_demo_scenarios()
    scenario_ids = {scenario["title"]: scenario["id"] for scenario in scenarios}
    selected_title = st.selectbox("Choose a demo scenario", list(scenario_ids.keys()))
    selected_id = scenario_ids[selected_title]
    selected_scenario = next(scenario for scenario in scenarios if scenario["id"] == selected_id)
    scenario_result = run_demo_scenario(selected_id)

    st.subheader(selected_scenario["title"])
    st.write(selected_scenario["description"])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Claim**")
        st.write(selected_scenario["claim_id"])
        st.markdown("**Supervisor task**")
        st.write(selected_scenario["task_type"])
        st.markdown("**Priority**")
        st.write(scenario_result["priority"])
    with col2:
        st.markdown("**Risk score**")
        st.write(scenario_result["risk_score"])
        st.markdown("**Next action**")
        st.write(scenario_result["next_action"])
        st.markdown("**Human review required**")
        st.write(scenario_result["human_review_required"])

    st.subheader("Agents invoked")
    st.write(scenario_result["agents_required"])

    st.subheader("Deterministic findings")
    findings_df = pd.DataFrame(scenario_result.get("deterministic_findings", []))
    if findings_df.empty:
        st.info("No deterministic findings were reported for this scenario.")
    else:
        st.dataframe(findings_df, width="stretch")

    st.subheader("Billing QA")
    if "billing_qa" in scenario_result.get("agent_results", {}):
        billing = scenario_result["agent_results"]["billing_qa"]
        st.json({
            "status": billing.get("status") or billing.get("qa_status"),
            "priority": billing.get("priority") or billing.get("qa_priority"),
            "risk_score": billing.get("risk_score"),
            "issues": billing.get("issues", []),
        })
    else:
        st.info("Billing QA result was not available for this scenario.")

    st.subheader("Audit trace")
    st.json(scenario_result.get("audit_trace", [])[-12:])

elif page == "Agent Evaluation":
    st.title("Agent Evaluation")
    evaluation = load_evaluation_summary()
    metric_rows = [
        ("Scenarios Evaluated", str(evaluation.total_scenarios)),
        ("Evaluation Pass Rate", f"{evaluation.pass_rate:.2f}%"),
        ("Safety Pass Rate", f"{evaluation.safety_pass_rate:.2f}%"),
        ("Human Review Rate", f"{evaluation.human_review_rate:.2f}%"),
        ("Average Latency", f"{evaluation.average_latency_ms:.2f} ms"),
        ("Agent Failures", str(evaluation.total_agent_failures)),
    ]
    for row_start in (0, 3):
        columns = st.columns(3)
        for column, (label, value) in zip(columns, metric_rows[row_start:row_start + 3]):
            with column:
                st.metric(label, value)

    evaluation_rows = [
        {
            "Scenario": result.scenario_name,
            "Result": "PASS" if result.passed else "FAIL",
            "Status": result.actual_status,
            "Human Review": "Required" if result.actual_human_review else "Not required",
            "Safety": "PASS" if result.safety_passed else "FAIL",
            "Risk": result.risk_score,
            "Priority": result.priority,
            "Latency (ms)": result.latency_ms,
        }
        for result in evaluation.scenario_results
    ]
    st.subheader("Scenario evaluations")
    if evaluation_rows:
        st.dataframe(pd.DataFrame(evaluation_rows), width="stretch", hide_index=True)

        selected_scenario_id = st.selectbox(
            "Evaluation details",
            [result.scenario_id for result in evaluation.scenario_results],
            format_func=lambda scenario_id: next(
                result.scenario_name for result in evaluation.scenario_results if result.scenario_id == scenario_id
            ),
        )
        selected_result = next(
            result for result in evaluation.scenario_results if result.scenario_id == selected_scenario_id
        )
        st.json({
            "scenario_id": selected_result.scenario_id,
            "task_id": selected_result.task_id,
            "claim_id": selected_result.claim_id,
            "audit_reference": selected_result.audit_reference,
            "expected_statuses": selected_result.expected_statuses,
            "actual_status": selected_result.actual_status,
            "expected_agents": selected_result.expected_agents,
            "actual_agents": selected_result.actual_agents,
            "routed_agents": selected_result.routed_agents,
            "missing_expected_agents": selected_result.missing_expected_agents,
            "unexpected_agents": selected_result.unexpected_agents,
            "completed_agents": selected_result.completed_agents,
            "failed_agents": selected_result.failed_agents,
            "pending_agents": selected_result.pending_agents,
            "expected_human_review": selected_result.expected_human_review,
            "actual_human_review": selected_result.actual_human_review,
            "safety_passed": selected_result.safety_passed,
            "external_action_blocked": selected_result.external_action_blocked,
            "failures": selected_result.failures,
            "warnings": selected_result.warnings,
        })

        st.subheader("Evaluation distributions")
        chart_columns = st.columns(2)
        with chart_columns[0]:
            st.markdown("**Pass / fail**")
            st.bar_chart(pd.DataFrame({"Scenarios": {"Pass": evaluation.passed_scenarios, "Fail": evaluation.failed_scenarios}}))
            st.markdown("**Status**")
            st.bar_chart(pd.DataFrame.from_dict(evaluation.status_distribution, orient="index", columns=["Scenarios"]))
            st.markdown("**Human review**")
            st.bar_chart(pd.DataFrame.from_dict(evaluation.human_review_distribution, orient="index", columns=["Scenarios"]))
        with chart_columns[1]:
            st.markdown("**Priority**")
            st.bar_chart(pd.DataFrame.from_dict(evaluation.priority_distribution, orient="index", columns=["Scenarios"]))
            st.markdown("**Risk**")
            st.bar_chart(pd.DataFrame.from_dict(evaluation.risk_distribution, orient="index", columns=["Scenarios"]))
            st.markdown("**Scenario latency**")
            latency_rows = [
                {"Scenario": result.scenario_name, "Latency (ms)": result.latency_ms}
                for result in evaluation.scenario_results
            ]
            st.bar_chart(pd.DataFrame(latency_rows).set_index("Scenario"))
    else:
        st.info("No demo scenarios are available for evaluation.")

else:
    st.title("Human Review Queue")
    queue = _human_review_queue(denials)
    queue_df = pd.DataFrame(queue)
    if queue_df.empty:
        st.info("No open denials require human review.")
    else:
        st.dataframe(queue_df, width="stretch")

        st.subheader("Queue by risk")
        st.bar_chart(queue_df.set_index("claim_id")["risk_score"])


if __name__ == "__main__":
    pass
