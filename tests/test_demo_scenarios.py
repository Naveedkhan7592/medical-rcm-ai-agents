from app.services.demo_scenarios import get_demo_scenarios, run_demo_scenario


def test_demo_scenarios_catalog_has_required_fields() -> None:
    scenarios = get_demo_scenarios()
    assert scenarios
    scenario = scenarios[0]
    assert {"id", "title", "claim_id", "task_type", "description"}.issubset(scenario)
    assert scenario["claim_id"].startswith("CLM-")
    assert scenario["task_type"] in {"CLAIM_REVIEW", "DENIAL_REVIEW", "PAYMENT_REVIEW", "FULL_RCM_REVIEW"}


def test_run_demo_scenario_returns_supervisor_result() -> None:
    scenario = run_demo_scenario("eligibility-denial")
    assert scenario["claim_id"] == "CLM-004"
    assert scenario["task_id"].startswith("TASK-")
    assert isinstance(scenario["agents_required"], list)
    assert scenario["agents_required"]
    assert "risk_score" in scenario
    assert "priority" in scenario
    assert "audit_trace" in scenario
