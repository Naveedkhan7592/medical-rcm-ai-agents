# RCM Supervisor Agent

The RCM Supervisor Agent coordinates specialist RCM agents. It does not replace their deterministic business logic.

## Architecture

The Supervisor receives a typed `SupervisorTask`, selects a deterministic route, invokes injected specialist collaborators, preserves their results, aggregates missing evidence and risk, applies Billing QA and Appeal gates, and routes unresolved cases to human review.

Supported task types:

- `CLAIM_REVIEW`: Claims, Eligibility, Coding, Billing QA
- `DENIAL_REVIEW`: Denial, Billing QA, plus category-specific support
- `PAYMENT_REVIEW`: Payment, A/R, Billing QA
- `AR_REVIEW`: Payment, A/R, Billing QA
- `BILLING_QA`: Billing QA
- `APPEAL_REVIEW`: Denial, Billing QA, Appeal
- `FULL_RCM_REVIEW`: Claims, Eligibility, Coding, Denial, Payment, A/R, Billing QA

Specialist results are injected and preserved. Missing collaborators produce `WAITING`; exceptions produce `REVIEW` with a failed-agent record. No result is fabricated.

## Workflow state

- `READY`: task accepted and next work is known
- `IN_PROGRESS`: reserved for future incremental execution
- `WAITING`: required result or collaborator is unavailable
- `REVIEW`: specialist evidence requires human review
- `COMPLETED`: selected route completed without unresolved review signals

Billing QA `REVIEW`, Appeal `NOT_READY`, specialist human-review flags, failed agents, and high-risk results prevent a false completed/pass outcome. Appeal preparation always remains human approval work.

## Risk and missing information

Risk uses existing deterministic weights: `CRITICAL=40`, `HIGH=25`, `MEDIUM=15`, `LOW=5`, capped at 100. Specialist risk values are aggregated conservatively using the highest available risk, not blindly summed. Priority follows the resulting deterministic risk.

Missing results are listed with pending agents. Failed agents are listed separately. The Supervisor never invents eligibility, coding, denial, payment, A/R, policy, or appeal evidence.

## LLM boundary

LLM output is advisory and cannot override deterministic specialist-agent results, routing, Billing QA, Appeal readiness, risk, priority, missing information, or human-review requirements. The Supervisor's routing and state transitions remain deterministic.

## API

The future-orchestration-compatible endpoint is:

```text
POST /rcm/supervisor
```

It accepts a `SupervisorTask` and returns `SupervisorResult`. This is only a Python/FastAPI contract. No n8n workflow, webhook, payer connection, eClinicalWorks connection, or external communication is implemented.

## Audit events

- `rcm_supervisor_task_started`
- `rcm_supervisor_claim_loaded`
- `rcm_supervisor_task_classified`
- `rcm_supervisor_agents_selected`
- `rcm_supervisor_agent_started`
- `rcm_supervisor_agent_completed`
- `rcm_supervisor_agent_failed`
- `rcm_supervisor_results_aggregated`
- `rcm_supervisor_risk_evaluated`
- `rcm_supervisor_human_review_required`
- `rcm_supervisor_next_action_determined`
- `rcm_supervisor_task_completed`

Audit details are concise and synthetic-source tagged; they exclude secrets, member IDs, and raw patient payloads.

## Testing and limitations

Tests use deterministic fake specialist agents and require no PostgreSQL, Docker, network, OpenAI API, payer API, eClinicalWorks, or n8n. All healthcare data and policies in this portfolio implementation are synthetic/demo data. This is not a production healthcare system and makes no HIPAA compliance claim.
