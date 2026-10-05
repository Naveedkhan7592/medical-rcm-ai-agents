# Portfolio Talking Points

## 30-second explanation

This is a synthetic-data RCM portfolio demo showing how deterministic Python validation, specialist agents, and a supervisor can coordinate claim, eligibility, coding, denial, payment, A/R, QA, and appeal-review work. FastAPI exposes the contracts, n8n exports demonstrate orchestration, and Streamlit displays operational and evaluation results. It performs no real payer or healthcare actions.

## 2-minute technical walkthrough

Start with the synthetic records and configured rules. FastAPI exposes agent operations and a typed Supervisor task. The Supervisor selects a route for the task type, invokes available specialist collaborators, preserves their results, aggregates risk and missing/failed work, and reports `COMPLETED`, `WAITING`, or `REVIEW`. Billing QA checks cross-agent consistency; the Appeal Agent prepares a draft/readiness result that always remains for human review. Optional LLM calls are limited to explanation and recommendation text. The dashboard reads the demo dataset and invokes the same scenario runner used by the evaluation CLI.

## Why deterministic rules + LLM

Eligibility date checks, coding-reference validation, payment arithmetic, configured policy checks, routing, risk aggregation, and state transitions are explicit Python behavior. Optional LLM reasoning can make supplied findings easier to read, but it cannot override deterministic results. This separation keeps the decision path testable and auditable within this demo.

## Why human-in-the-loop

Incomplete, conflicting, uncertain, or high-risk results should remain visible for a person to assess. Appeal preparation always requires human approval. The demo does not submit claims or appeals, contact payers, post payments, or modify patient financial records.

## Why n8n + Python

Python owns the API contracts and RCM decisions. The checked-in n8n JSON exports demonstrate request validation, API calls, result routing, and a human-review wait/decision contract. They do not reproduce the billing rules and do not require an n8n runtime for automated tests.

## How the Supervisor works

The Supervisor maps typed task types to task-specific agent routes. It invokes injected collaborators, distinguishes completed, pending, and failed agents, aggregates risk and review indicators, and retains an audit reference. A failed agent is surfaced rather than replaced with fabricated output. See [docs/rcm_supervisor_agent.md](rcm_supervisor_agent.md).

## How testing works

Pytest covers specialist behavior with synthetic records and deterministic fakes, database models using isolated SQLite, FastAPI contracts using dependency overrides, n8n contracts, project/config safety, and evaluation calculations. The standard suite does not require credentials, PostgreSQL, Docker, a payer system, or an n8n runtime.

## How evaluation works

The evaluator runs each declared demo scenario through the existing runner and compares actual status, review flag, agent execution, and external-action safety with scenario expectations. It also records local latency and aggregates pass/fail, safety, review, risk, and agent-failure metrics. Latency is informational and does not determine pass/fail.

## Current limitations

All data and rules references are synthetic and incomplete. The repository does not validate real clinical coding, contractual payer behavior, clinical correctness, or production operational performance. No real healthcare integrations, production authentication, or external actions exist. No professional medical-billing deployment experience is represented by this portfolio demo.

## What would be required for production

A production effort would require authoritative and appropriately licensed coding/payer sources, qualified RCM and clinical review, privacy/security and access controls, validated integrations, audit retention, operational support, risk assessment, and a separate legal/compliance review. This repository does not implement those controls or claim compliance.
