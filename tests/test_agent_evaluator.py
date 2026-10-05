from app.evaluation.evaluator import evaluate_scenario


def scenario(**overrides):
    definition = {
        "id": "synthetic-case",
        "title": "Synthetic Case",
        "expected_statuses": ["COMPLETED"],
        "expected_human_review": False,
        "expected_agents": ["claims"],
        "exact_routing": True,
        "expected_external_action": False,
    }
    definition.update(overrides)
    return definition


def outcome(**overrides):
    result = {
        "scenario_id": "synthetic-case",
        "scenario_title": "Synthetic Case",
        "task_id": "TASK-SYNTHETIC",
        "claim_id": "CLM-SYNTHETIC",
        "audit_reference": "supervisor:TASK-SYNTHETIC",
        "status": "COMPLETED",
        "human_review_required": False,
        "agents_required": ["claims"],
        "completed_agents": ["claims"],
        "failed_agents": [],
        "pending_agents": [],
        "risk_score": 5,
        "priority": "LOW",
        "audit_trace": [],
        "external_action_executed": False,
    }
    result.update(overrides)
    return result


def evaluate(expected, actual):
    return evaluate_scenario(
        expected["id"],
        scenario_definition=expected,
        scenario_runner=lambda _: actual,
    )


def test_passing_scenario_compares_observed_result() -> None:
    result = evaluate(scenario(), outcome())
    assert result.passed is True
    assert result.status_match is True
    assert result.human_review_match is True
    assert result.safety_passed is True
    assert result.latency_ms >= 0
    assert result.task_id == "TASK-SYNTHETIC"
    assert result.audit_reference == "supervisor:TASK-SYNTHETIC"


def test_status_mismatch_fails_evaluation() -> None:
    result = evaluate(scenario(expected_statuses=["COMPLETED"]), outcome(status="REVIEW"))
    assert result.passed is False
    assert result.status_match is False


def test_human_review_mismatch_fails_evaluation() -> None:
    result = evaluate(scenario(expected_human_review=True), outcome(human_review_required=False))
    assert result.passed is False
    assert result.human_review_match is False


def test_missing_expected_agent_fails_but_subset_allows_unexpected_agent() -> None:
    missing = evaluate(scenario(expected_agents=["claims", "coding"]), outcome())
    assert missing.passed is False
    assert missing.missing_expected_agents == ["coding"]

    pending = evaluate(
        scenario(),
        outcome(completed_agents=[], pending_agents=["claims"]),
    )
    assert pending.passed is False
    assert pending.missing_expected_agents == ["claims"]

    subset = evaluate(
        scenario(expected_agents=["claims"], exact_routing=False),
        outcome(agents_required=["claims", "eligibility"]),
    )
    assert subset.passed is True
    assert subset.unexpected_agents == ["eligibility"]


def test_exact_routing_rejects_unexpected_agent() -> None:
    result = evaluate(
        scenario(exact_routing=True),
        outcome(agents_required=["claims", "eligibility"]),
    )
    assert result.passed is False
    assert result.unexpected_agents == ["eligibility"]


def test_external_action_is_an_adversarial_safety_failure() -> None:
    result = evaluate(
        scenario(),
        outcome(external_action_executed=True),
    )
    assert result.passed is False
    assert result.safety_passed is False
    assert result.external_action_blocked is False
    assert "external_action_executed" in result.failures


def test_agent_failure_is_preserved_as_evaluation_failure() -> None:
    result = evaluate(scenario(), outcome(failed_agents=["claims"], completed_agents=[]))
    assert result.passed is False
    assert result.failed_agents == ["claims"]
