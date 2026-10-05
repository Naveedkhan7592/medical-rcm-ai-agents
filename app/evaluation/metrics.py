from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from app.evaluation.schemas import EvaluationSummary, ScenarioEvaluation


def summarize_evaluations(results: Iterable[ScenarioEvaluation]) -> EvaluationSummary:
    evaluations = list(results)
    total = len(evaluations)
    passed = sum(result.passed for result in evaluations)
    human_review = sum(result.actual_human_review for result in evaluations)
    safe = sum(result.safety_passed for result in evaluations)
    pending = sum(bool(result.pending_agents) for result in evaluations)
    latency_total = sum(result.latency_ms for result in evaluations)

    risk_buckets = Counter(
        "CRITICAL" if result.risk_score >= 40 else
        "HIGH" if result.risk_score >= 25 else
        "MEDIUM" if result.risk_score >= 15 else "LOW"
        for result in evaluations
    )
    priorities = Counter(result.priority for result in evaluations)
    statuses = Counter(result.actual_status for result in evaluations)
    reviews = Counter("Required" if result.actual_human_review else "Not required" for result in evaluations)

    return EvaluationSummary(
        total_scenarios=total,
        passed_scenarios=passed,
        failed_scenarios=total - passed,
        pass_rate=round(passed * 100 / total, 2) if total else 0.0,
        human_review_rate=round(human_review * 100 / total, 2) if total else 0.0,
        safety_pass_rate=round(safe * 100 / total, 2) if total else 0.0,
        average_latency_ms=round(latency_total / total, 2) if total else 0.0,
        total_agent_failures=sum(len(result.failed_agents) for result in evaluations),
        scenarios_with_agent_failures=sum(bool(result.failed_agents) for result in evaluations),
        pending_agent_rate=round(pending * 100 / total, 2) if total else 0.0,
        high_critical_risk_count=sum(result.priority in {"HIGH", "CRITICAL"} for result in evaluations),
        status_distribution=dict(sorted(statuses.items())),
        priority_distribution=dict(sorted(priorities.items())),
        human_review_distribution=dict(sorted(reviews.items())),
        risk_distribution={key: risk_buckets[key] for key in ("LOW", "MEDIUM", "HIGH", "CRITICAL") if risk_buckets[key]},
        scenario_results=evaluations,
    )
