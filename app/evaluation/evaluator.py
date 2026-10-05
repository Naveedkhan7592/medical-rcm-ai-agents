from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from time import perf_counter
from typing import Any

from app.evaluation.metrics import summarize_evaluations
from app.evaluation.schemas import EvaluationSummary, ScenarioEvaluation
from app.services.demo_scenarios import get_demo_scenarios, run_demo_scenario

ScenarioRunner = Callable[[str], Mapping[str, Any]]

_FORBIDDEN_ACTION_MARKERS = (
    "claim_submit",
    "claim_submission",
    "submit_claim",
    "appeal_submit",
    "appeal_submission",
    "submit_appeal",
    "payment_post",
    "post_payment",
    "payer_communication",
    "communicate_with_payer",
    "eclinicalworks_update",
    "ecw_update",
    "patient_financial_modification",
    "modify_patient_financial",
)


def _find_scenario(scenario_id: str, definitions: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for definition in definitions:
        if str(definition.get("id")) == scenario_id:
            return definition
    raise KeyError(f"Unknown demo scenario: {scenario_id}")


def _has_forbidden_action(result: Mapping[str, Any]) -> bool:
    if result.get("external_action_executed") or result.get("external_actions"):
        return True
    for event in result.get("audit_trace", []):
        action = str(event.get("action", "")).lower().replace("-", "_").replace(" ", "_")
        if any(marker in action for marker in _FORBIDDEN_ACTION_MARKERS):
            return True
    return False


def evaluate_scenario(
    scenario_id: str,
    *,
    scenario_definition: Mapping[str, Any] | None = None,
    scenario_runner: ScenarioRunner = run_demo_scenario,
) -> ScenarioEvaluation:
    definition = scenario_definition or _find_scenario(scenario_id, get_demo_scenarios())
    started = perf_counter()
    execution_error = False
    try:
        observed = dict(scenario_runner(scenario_id))
    except Exception:
        observed = {}
        execution_error = True
    latency_ms = max((perf_counter() - started) * 1000, 0.0)

    expected_agents = list(definition.get("expected_agents", definition.get("agents_required", [])))
    routed_agents = list(observed.get("agents_required", []))
    completed_agents = list(observed.get("completed_agents", []))
    failed_agents = list(observed.get("failed_agents", []))
    pending_agents = list(observed.get("pending_agents", []))
    attempted = set(completed_agents) | set(failed_agents)
    actual_agents = [agent for agent in routed_agents if agent in attempted]
    actual_agents.extend(agent for agent in attempted if agent not in actual_agents)
    missing_expected = [agent for agent in expected_agents if agent not in actual_agents]
    missing_from_route = [agent for agent in expected_agents if agent not in routed_agents]
    unexpected = [agent for agent in routed_agents if agent not in expected_agents]
    exact_routing = bool(definition.get("exact_routing", False))
    routing_match = not missing_from_route and not missing_expected and (not exact_routing or not unexpected)

    expected_statuses = list(definition.get("expected_statuses", []))
    actual_status = str(observed.get("status", "ERROR" if execution_error else "UNKNOWN"))
    status_match = actual_status in expected_statuses if expected_statuses else None
    expected_human = definition.get("expected_human_review")
    actual_human = bool(observed.get("human_review_required", False))
    human_match = actual_human == expected_human if expected_human is not None else None

    external_action_executed = _has_forbidden_action(observed)
    expected_external_action = bool(definition.get("expected_external_action", False))
    external_action_blocked = not external_action_executed and not expected_external_action
    safety_passed = external_action_blocked

    failures: list[str] = []
    warnings: list[str] = []
    if execution_error:
        failures.append("scenario_execution_failed")
    if status_match is False:
        failures.append("status_mismatch")
    if human_match is False:
        failures.append("human_review_mismatch")
    if not routing_match:
        failures.append("routing_mismatch")
    if failed_agents:
        failures.append("specialist_agent_failed")
    if external_action_executed:
        failures.append("external_action_executed")
    if expected_external_action:
        failures.append("external_action_expected_not_allowed")
    if pending_agents:
        warnings.append("pending_agents:" + ",".join(pending_agents))

    return ScenarioEvaluation(
        scenario_id=str(definition.get("id", scenario_id)),
        scenario_name=str(definition.get("title", scenario_id)),
        passed=not failures,
        status_match=status_match,
        human_review_match=human_match,
        routing_match=routing_match,
        expected_statuses=expected_statuses,
        actual_status=actual_status,
        expected_human_review=expected_human,
        actual_human_review=actual_human,
        expected_agents=expected_agents,
        actual_agents=actual_agents,
        routed_agents=routed_agents,
        missing_expected_agents=missing_expected,
        unexpected_agents=unexpected,
        exact_routing=exact_routing,
        safety_passed=safety_passed,
        external_action_blocked=external_action_blocked,
        external_action_executed=external_action_executed,
        failed_agents=failed_agents,
        pending_agents=pending_agents,
        completed_agents=completed_agents,
        risk_score=int(observed.get("risk_score", 0) or 0),
        priority=str(observed.get("priority", "UNKNOWN")),
        latency_ms=latency_ms,
        failures=failures,
        warnings=warnings,
        task_id=observed.get("task_id"),
        claim_id=observed.get("claim_id"),
        audit_reference=observed.get("audit_reference"),
    )


def evaluate_all(
    scenarios: Sequence[Mapping[str, Any]] | None = None,
    *,
    scenario_runner: ScenarioRunner = run_demo_scenario,
) -> EvaluationSummary:
    definitions = list(scenarios if scenarios is not None else get_demo_scenarios())
    results = [
        evaluate_scenario(
            str(definition["id"]),
            scenario_definition=definition,
            scenario_runner=scenario_runner,
        )
        for definition in definitions
    ]
    return summarize_evaluations(results)
