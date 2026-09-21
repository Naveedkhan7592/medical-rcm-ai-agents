# n8n RCM Orchestration

n8n is the orchestration layer around the existing Python/FastAPI RCM system.

```text
n8n -> FastAPI -> RCM Supervisor -> Specialist Agents
```

Python remains responsible for deterministic RCM business logic. The workflows only validate input, call the Supervisor, branch on its response, preserve correlation data, and route human review.

## Workflows

- `rcm_supervisor_workflow.json`: primary webhook-to-Supervisor orchestration with completed, waiting, review, and error branches.
- `denial_to_appeal_workflow.json`: denial review routing that prepares appeal work for human review only.
- `human_review_workflow.json`: explicit wait/decision gate with approve, reject, or request-more-information decisions. It never performs external actions.

## Supervisor contract

The primary workflow sends the existing `SupervisorTask` shape to `POST /rcm/supervisor`:

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

The response is the existing `SupervisorResult` contract, including `status`, `workflow_stage`, `next_action`, completed/pending/failed agents, human review, priority, risk, missing information, and warnings.

## Local setup

1. Start the FastAPI application using the existing project setup.
2. Start n8n using your local n8n installation or another development-only method available on your machine. Docker is not required by this repository.
3. Configure the n8n environment variable `RCM_API_BASE_URL`, for example `http://localhost:8000`.
4. Import the JSON workflow through n8n's workflow import UI.
5. Keep workflows inactive while reviewing them, then activate the required webhook workflow.
6. Send a synthetic payload using the example above.

The exported workflows contain no credentials or secrets. Development deployments without API authentication are not production-safe.

## Step 16 validation

From the project root, validate the exports without installing n8n:

```bash
python scripts/validate_n8n_workflows.py
pytest -q tests/test_n8n_contract.py tests/test_n8n_fastapi_integration.py
```

The FastAPI contract tests override the database dependency with an empty synthetic store. They verify that `task_id` and `claim_id` survive the HTTP request/response and that the backend returns a real Supervisor result without PostgreSQL, Docker, OpenAI, or n8n.

## Safety and correlation

`task_id` is the idempotency/correlation identifier and is preserved across retries and branches. `claim_id`, workflow stage, agent lists, status, and risk are also retained. n8n execution IDs can be correlated with the Python Supervisor task ID and the Python audit events.

Timeouts are bounded at 30 seconds. The workflow does not retry financial or external actions; none are implemented here. Human review is mandatory before any future appeal submission, claim change, financial change, or external communication.

The same `task_id` must be reused for any technical retry. The workflows do not create a new task identity and do not retry business decisions or human-review states.
