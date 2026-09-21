# n8n Orchestration

## Purpose

n8n provides workflow orchestration around the existing Python RCM system. It does not contain claim, payment, coding, denial, A/R, QA, or appeal business logic.

```text
n8n -> POST /rcm/supervisor -> Specialist Agents -> Billing QA -> Human Review
```

Deterministic RCM business logic remains in Python. LLM output remains advisory and cannot override deterministic RCM decisions.

## Input and output

The primary workflow validates `task_id`, `claim_id`, and `task_type` before calling the existing `POST /rcm/supervisor` endpoint. Supported task types are `CLAIM_REVIEW`, `DENIAL_REVIEW`, `PAYMENT_REVIEW`, `AR_REVIEW`, `BILLING_QA`, `APPEAL_REVIEW`, and `FULL_RCM_REVIEW`.

The normalized response preserves `task_id`, `claim_id`, `status`, `workflow_stage`, `next_action`, review requirement, priority, risk, completed/pending/failed agents, missing information, and warnings.

The complete request contract is:

```json
{
	"task_id": "TASK-DEMO-001",
	"claim_id": "CLM-DEMO-001",
	"task_type": "DENIAL_REVIEW",
	"priority": "HIGH",
	"input_data": {},
	"requested_action": "review_denial"
}
```

`task_type` is validated against the existing Supervisor enum. Domain decisions remain in Python.

## Workflow states

- `COMPLETED`: success response.
- `WAITING`: missing information or pending agent result.
- `REVIEW`: human review path; no external action continues automatically.
- `ERROR`: invalid input, malformed response, timeout, or API error.

## Errors and retries

The HTTP request has a bounded 30-second timeout. Invalid input and malformed responses become structured errors. HTTP and connection errors are preserved without stack traces or internal details. Any future retry must reuse the same `task_id`; this step does not implement automatic financial or external actions.

The integration tests exercise `GET /health` and `POST /rcm/supervisor` using FastAPI's test client and an overridden database dependency. Run `python scripts/validate_n8n_workflows.py` to validate exported workflow structure and secret safety.

## Human-in-the-loop

The human review workflow creates a review state and waits for an explicit human decision. It does not automatically approve anything. Appeal submission, claim modification, coding changes, financial changes, patient financial changes, and external payer communication remain outside these workflows and require future controlled implementation plus human approval.

## Denial-to-appeal

The denial workflow calls the Supervisor for `DENIAL_REVIEW`, routes unresolved or non-ready cases to human review, and only prepares appeal work for human review when the Supervisor indicates a suitable path. It never submits an appeal or contacts a payer.

## Credentials and audit correlation

The API base URL is configured through `RCM_API_BASE_URL`; the default is local development only. No API keys, database passwords, payer credentials, or eClinicalWorks credentials are exported. Python remains authoritative for audit events. Correlate n8n executions with Python using `task_id`, `claim_id`, workflow stage, and status.

## Limitations

All healthcare data is synthetic/demo data. This implementation does not claim HIPAA compliance, production deployment, real eClinicalWorks integration, real payer integration, clearinghouse integration, or production security. Future production hardening would require authentication, secret management, signed webhooks, idempotency persistence, observability, retry/dead-letter policy, access control, and validated external integrations.
