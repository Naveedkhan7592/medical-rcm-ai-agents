from app.evaluation.metrics import summarize_evaluations
from app.evaluation.schemas import ScenarioEvaluation


def evaluation(**overrides):
    values = {
        "scenario_id": "case-1",
        "scenario_name": "Case 1",
        "passed": True,
        "status_match": True,
        "human_review_match": True,
        "routing_match": True,
        "expected_statuses": ["COMPLETED"],
        "actual_status": "COMPLETED",
        "expected_human_review": False,
        "actual_human_review": False,
        "expected_agents": ["claims"],
        "actual_agents": ["claims"],
        "missing_expected_agents": [],
        "unexpected_agents": [],
        "exact_routing": True,
        "safety_passed": True,
        "external_action_blocked": True,
        "external_action_executed": False,
        "failed_agents": [],
        "pending_agents": [],
        "completed_agents": ["claims"],
        "risk_score": 5,
        "priority": "LOW",
        "latency_ms": 10.0,
        "failures": [],
        "warnings": [],
    }
    values.update(overrides)
    return ScenarioEvaluation(**values)


def test_zero_scenarios_are_safe() -> None:
    summary = summarize_evaluations([])
    assert summary.total_scenarios == 0
    assert summary.pass_rate == 0
    assert summary.human_review_rate == 0
    assert summary.safety_pass_rate == 0
    assert summary.average_latency_ms == 0


def test_rates_latency_and_agent_failures_aggregate() -> None:
    summary = summarize_evaluations([
        evaluation(scenario_id="one", latency_ms=10),
        evaluation(
            scenario_id="two",
            scenario_name="Case 2",
            passed=False,
            status_match=False,
            actual_status="REVIEW",
            actual_human_review=True,
            human_review_match=False,
            safety_passed=False,
            external_action_blocked=False,
            external_action_executed=True,
            failed_agents=["denial", "payment"],
            priority="CRITICAL",
            risk_score=45,
            latency_ms=30,
        ),
    ])
    assert summary.total_scenarios == 2
    assert summary.passed_scenarios == 1
    assert summary.failed_scenarios == 1
    assert summary.pass_rate == 50
    assert summary.human_review_rate == 50
    assert summary.safety_pass_rate == 50
    assert summary.average_latency_ms == 20
    assert summary.total_agent_failures == 2
    assert summary.scenarios_with_agent_failures == 1
    assert summary.high_critical_risk_count == 1
    assert summary.status_distribution == {"COMPLETED": 1, "REVIEW": 1}
    assert summary.priority_distribution == {"LOW": 1, "CRITICAL": 1}
    assert summary.human_review_distribution == {"Not required": 1, "Required": 1}
    assert summary.risk_distribution == {"LOW": 1, "CRITICAL": 1}
