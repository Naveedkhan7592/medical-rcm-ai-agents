# Agent Evaluation

## Purpose

The evaluation layer measures deterministic behavior of the repository's synthetic RCM demo scenarios. It is an observer and comparator, not another decision-making agent. It invokes the existing `run_demo_scenario` service and compares its supervisor result with declarative expectations in the scenario catalog. Evaluation never changes the observed result.

This evaluation framework measures deterministic demo behavior and does not establish clinical correctness, payer compliance, HIPAA compliance, or production readiness.

## Architecture

- `app/services/demo_scenarios.py` remains the source of scenario definitions and demo execution.
- `app/evaluation/evaluator.py` compares observed supervisor outputs with scenario expectations.
- `app/evaluation/metrics.py` aggregates pass, safety, human-review, latency, risk, and agent-failure metrics.
- `app/evaluation/schemas.py` defines typed scenario and summary results.
- `scripts/evaluate_demo_scenarios.py` prints a human-readable or JSON report and returns a CI-friendly exit status.
- The Streamlit Agent Evaluation page renders the same evaluator output; it does not accept edits to results.

The conceptual trace is:

```text
Scenario
  -> task_id
  -> Supervisor
  -> Specialist Agents
  -> audit_reference
  -> Evaluation Result
```

The evaluator preserves `scenario_id`, `task_id`, `claim_id`, and `audit_reference` where available. It complements rather than replaces the existing supervisor audit events and audit model.

## Scenario expectations

Each synthetic scenario declares evaluation metadata alongside its existing task setup:

- `expected_statuses`: accepted supervisor statuses; supports multiple safe outcomes.
- `expected_human_review`: whether the result must require human review.
- `expected_agents`: specialist agents expected to be invoked.
- `exact_routing`: when true, any additional routed agent fails routing evaluation; otherwise unexpected routed agents are recorded but are not automatically failures.
- `expected_external_action`: must remain false for this synthetic portfolio.

Agent evaluation distinguishes selected `routed_agents` from `actual_agents` that completed or failed. Missing expected invocations, specialist failures, expectation mismatches, and safety violations are reported, not hidden. Pending agents are retained in results and warnings.

## Routing and status

The evaluator compares the scenario's expected specialists against the supervisor's selected route and actual completed/failed agent lists. It records missing and unexpected agents. Subset routing is supported; exact routing is opt-in per scenario.

Status is compared only when `expected_statuses` is defined. One or more accepted values are supported so a scenario may explicitly accept safe states such as `REVIEW` or `WAITING`. A legitimate `REVIEW` outcome passes when it matches the declared expectation; evaluation does not impose `COMPLETED` as the only passing status.

## Human review

`expected_human_review` is compared with the supervisor's actual `human_review_required` value. A scenario expecting review fails if the supervisor permits autonomous completion. Human-review rate is an aggregate of actual outcomes.

## Safety

All current scenarios set `expected_external_action` to false. The evaluator fails if a result indicates `external_action_executed`, includes external actions, or contains a recognized forbidden action in the captured audit trace (claim submission, appeal submission, payment posting, payer communication, eClinicalWorks update, or patient financial modification). The evaluation layer performs none of these actions; this is a local synthetic safety check, not an external-system interceptor.

## Latency and aggregate metrics

Scenario execution time is measured locally with `time.perf_counter()` and reported as `latency_ms`. It is observational only and is not subject to a target threshold. Aggregates include pass/fail totals and rate, human-review rate, safety pass rate, average latency, total and scenario-level agent failures, pending-agent rate, high/critical priority count, status distribution, priority distribution, and risk distribution. Rates and averages are zero for an empty scenario list.

## CLI usage

Run from the repository root:

```bash
python scripts/evaluate_demo_scenarios.py
python scripts/evaluate_demo_scenarios.py --json
```

The command returns exit status `0` when every required evaluation passes and `1` when one or more scenarios fail.

## Dashboard usage

Start the dashboard from the repository root:

```bash
python -m streamlit run dashboard/streamlit_app.py
```

Select **Agent Evaluation** to view summary KPIs, scenario results, routing and safety details, audit correlation identifiers, and pass/fail, status, priority, human-review, risk, and latency charts.

## Data handling and limitations

The scenarios use synthetic data and synthetic identifiers only. Evaluation output contains scenario/task/claim identifiers, status, priority, risk, agent names, evaluation codes, audit reference, and measured latency. It does not include full agent payloads, patient records, secrets, API keys, or credentials. The framework does not perform payer or eClinicalWorks integrations, claim or appeal submissions, payment posting, patient financial modifications, or any real healthcare action. It does not establish clinical correctness, payer compliance, HIPAA compliance, or production readiness.
