from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.evaluator import evaluate_all


def _human_report(summary) -> str:
    lines = [
        "RCM AGENT EVALUATION",
        "",
        f"Scenarios: {summary.total_scenarios}",
        f"Passed: {summary.passed_scenarios}",
        f"Failed: {summary.failed_scenarios}",
        f"Pass Rate: {summary.pass_rate:.2f}%",
        f"Safety Pass Rate: {summary.safety_pass_rate:.2f}%",
        f"Human Review Rate: {summary.human_review_rate:.2f}%",
        f"Average Latency: {summary.average_latency_ms:.2f} ms",
        f"Agent Failures: {summary.total_agent_failures}",
        "",
        "Scenario Results",
        "----------------",
    ]
    for result in summary.scenario_results:
        label = "PASS" if result.passed else "FAIL"
        lines.append(f"{result.scenario_name:<32} {label}  {result.actual_status}")
        for failure in result.failures:
            lines.append(f"  - {failure}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the synthetic RCM demo scenarios.")
    parser.add_argument("--json", action="store_true", help="Print the evaluation summary as JSON.")
    arguments = parser.parse_args(argv)
    summary = evaluate_all()
    if arguments.json:
        print(json.dumps(summary.model_dump(mode="json"), indent=2))
    else:
        print(_human_report(summary))
    return 0 if summary.failed_scenarios == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
