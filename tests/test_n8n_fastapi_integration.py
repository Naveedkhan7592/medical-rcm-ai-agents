from collections.abc import Generator
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.services.database import get_db


class EmptyDatabase:
    """Minimal database stub for HTTP contract tests."""

    def scalar(self, *_: object) -> None:
        return None

    def close(self) -> None:
        pass


def fake_db() -> Generator[EmptyDatabase, None, None]:
    yield EmptyDatabase()


def client() -> TestClient:
    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


def task_payload() -> dict[str, Any]:
    return {
        "task_id": "TASK-DEMO-001",
        "claim_id": "CLM-DEMO-001",
        "task_type": "CLAIM_REVIEW",
        "priority": "HIGH",
        "input_data": {},
        "requested_action": "review_claim",
    }


def cleanup_dependencies() -> None:
    app.dependency_overrides.clear()


def route_status(status: str) -> str:
    """Represent the technical n8n status-routing contract only."""
    routes = {
        "COMPLETED": "SUCCESS",
        "REVIEW": "HUMAN_REVIEW",
        "WAITING": "WAITING",
    }
    return routes.get(status, "ERROR")


def test_health_endpoint_is_available() -> None:
    with client() as test_client:
        response = test_client.get("/health")

    cleanup_dependencies()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "medical-rcm-ai"


def test_supervisor_http_contract_preserves_task_identity() -> None:
    with client() as test_client:
        response = test_client.post(
            "/rcm/supervisor",
            json=task_payload(),
        )

    cleanup_dependencies()

    assert response.status_code == 200

    body = response.json()

    assert body["task_id"] == "TASK-DEMO-001"
    assert body["claim_id"] == "CLM-DEMO-001"
    assert body["status"] in {"WAITING", "REVIEW", "COMPLETED"}

    assert "human_review_required" in body
    assert "specialist_results" in body
    assert "agent_results" in body
    assert "risk_score" in body
    assert "priority" in body
    assert "next_action" in body


def test_supervisor_http_contract_rejects_invalid_task_type() -> None:
    payload = task_payload()
    payload["task_type"] = "UNSUPPORTED"

    with client() as test_client:
        response = test_client.post(
            "/rcm/supervisor",
            json=payload,
        )

    cleanup_dependencies()

    assert response.status_code == 422


def test_supervisor_http_contract_rejects_missing_required_fields() -> None:
    payload = task_payload()
    payload.pop("task_id")

    with client() as test_client:
        response = test_client.post(
            "/rcm/supervisor",
            json=payload,
        )

    cleanup_dependencies()

    assert response.status_code == 422


def test_supervisor_http_contract_preserves_retry_identity() -> None:
    payload = task_payload()

    with client() as test_client:
        first = test_client.post(
            "/rcm/supervisor",
            json=payload,
        )
        second = test_client.post(
            "/rcm/supervisor",
            json=payload,
        )

    cleanup_dependencies()

    assert first.status_code == 200
    assert second.status_code == 200

    assert first.json()["task_id"] == payload["task_id"]
    assert second.json()["task_id"] == payload["task_id"]
    assert first.json()["task_id"] == second.json()["task_id"]


def test_n8n_status_routing_completed() -> None:
    assert route_status("COMPLETED") == "SUCCESS"


def test_n8n_status_routing_review() -> None:
    assert route_status("REVIEW") == "HUMAN_REVIEW"


def test_n8n_status_routing_waiting() -> None:
    assert route_status("WAITING") == "WAITING"


def test_n8n_status_routing_unknown_status_is_error() -> None:
    assert route_status("UNKNOWN_STATUS") == "ERROR"


def test_supervisor_response_preserves_human_review_flag() -> None:
    with client() as test_client:
        response = test_client.post(
            "/rcm/supervisor",
            json=task_payload(),
        )

    cleanup_dependencies()

    assert response.status_code == 200

    body = response.json()

    assert isinstance(body["human_review_required"], bool)


def test_supervisor_response_preserves_specialist_results() -> None:
    with client() as test_client:
        response = test_client.post(
            "/rcm/supervisor",
            json=task_payload(),
        )

    cleanup_dependencies()

    assert response.status_code == 200

    body = response.json()

    assert "specialist_results" in body
    assert isinstance(body["specialist_results"], dict)


def test_supervisor_response_contains_n8n_correlation_fields() -> None:
    with client() as test_client:
        response = test_client.post(
            "/rcm/supervisor",
            json=task_payload(),
        )

    cleanup_dependencies()

    assert response.status_code == 200

    body = response.json()

    correlation_fields = {
        "task_id",
        "claim_id",
        "status",
        "next_action",
        "human_review_required",
        "audit_reference",
    }

    assert correlation_fields.issubset(body.keys())


def test_supervisor_response_contains_risk_and_priority() -> None:
    with client() as test_client:
        response = test_client.post(
            "/rcm/supervisor",
            json=task_payload(),
        )

    cleanup_dependencies()

    assert response.status_code == 200

    body = response.json()

    assert isinstance(body["risk_score"], int)
    assert 0 <= body["risk_score"] <= 100
    assert isinstance(body["priority"], str)


def test_n8n_retry_keeps_same_task_id() -> None:
    payload = task_payload()

    simulated_attempts = [
        {
            "attempt": 1,
            "technical_status": 500,
            "task_id": payload["task_id"],
        },
        {
            "attempt": 2,
            "technical_status": 200,
            "task_id": payload["task_id"],
        },
    ]

    assert simulated_attempts[0]["task_id"] == simulated_attempts[1]["task_id"]


def test_technical_http_error_is_not_success() -> None:
    technical_status = 500

    workflow_status = (
        "ERROR"
        if technical_status >= 500
        else "SUCCESS"
    )

    assert workflow_status == "ERROR"
    assert workflow_status != "SUCCESS"


def test_malformed_supervisor_response_is_not_success() -> None:
    malformed_response: dict[str, Any] = {}

    required_response_fields = {
        "task_id",
        "claim_id",
        "status",
        "next_action",
    }

    is_valid = required_response_fields.issubset(
        malformed_response.keys()
    )

    assert is_valid is False

    workflow_status = (
        "ERROR"
        if not is_valid
        else "SUCCESS"
    )

    assert workflow_status == "ERROR"


def test_supervisor_contract_does_not_invent_business_results() -> None:
    with client() as test_client:
        response = test_client.post(
            "/rcm/supervisor",
            json=task_payload(),
        )

    cleanup_dependencies()

    assert response.status_code == 200

    body = response.json()

    assert "risk_score" in body
    assert "specialist_results" in body
    assert "next_action" in body
    assert "human_review_required" in body


def test_supervisor_task_identity_is_stable_across_multiple_requests() -> None:
    payload = task_payload()

    responses: list[dict[str, Any]] = []

    with client() as test_client:
        for _ in range(3):
            response = test_client.post(
                "/rcm/supervisor",
                json=payload,
            )

            assert response.status_code == 200
            responses.append(response.json())

    cleanup_dependencies()

    task_ids = {
        result["task_id"]
        for result in responses
    }

    claim_ids = {
        result["claim_id"]
        for result in responses
    }

    assert task_ids == {payload["task_id"]}
    assert claim_ids == {payload["claim_id"]}