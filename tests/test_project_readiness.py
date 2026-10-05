from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from scripts.check_project import check_project

ROOT = Path(__file__).resolve().parents[1]


def test_project_checker_passes_repository_root() -> None:
    results = check_project(ROOT)
    assert results
    assert all(passed for _, passed, _ in results)


def test_dashboard_entrypoint_and_required_workflows_exist() -> None:
    assert (ROOT / "dashboard" / "streamlit_app.py").is_file()
    assert not (ROOT / "dashboard" / "app.py").exists()
    assert list((ROOT / "workflows" / "n8n").glob("*.json"))


def test_dashboard_and_evaluation_modules_import_without_web_server() -> None:
    import dashboard.data_service
    import dashboard.metrics
    from app.evaluation.evaluator import evaluate_all

    assert callable(evaluate_all)
    assert dashboard.data_service.load_dashboard_data()["claims"]
    assert callable(dashboard.metrics.compute_overview_metrics)


def test_health_readiness_and_api_metadata() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "medical-rcm-ai"}
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "service": "medical-rcm-ai",
        "mode": "synthetic-demo",
    }
    assert "Synthetic Demo API" in app.title
    assert "synthetic" in app.description.lower()
    assert "no autonomous payer actions" in app.description.lower()


def test_validation_and_not_found_error_contract() -> None:
    from tests.test_n8n_fastapi_integration import cleanup_dependencies, client as api_client

    with api_client() as client:
        invalid = client.post("/rcm/supervisor", json={"claim_id": "CLM-X"})
        missing_claim = client.post("/claims/CLM-MISSING/validate")
    cleanup_dependencies()

    assert invalid.status_code == 422
    assert invalid.json()["detail"]
    assert missing_claim.status_code == 404
    assert missing_claim.json()["detail"] == "claim not found"


def test_supervisor_review_is_a_successful_business_response(monkeypatch) -> None:
    import app.main as main_module
    from app.schemas import SupervisorResult
    from tests.test_n8n_fastapi_integration import cleanup_dependencies, client, task_payload

    class ReviewSupervisor:
        def __init__(self, **_: object) -> None:
            pass

        def run(self, task):
            return SupervisorResult(
                task_id=task.task_id,
                claim_id=task.claim_id,
                status="REVIEW",
                current_stage="HUMAN_REVIEW",
                workflow_stage="HUMAN_REVIEW",
                next_action="HUMAN_REVIEW",
                agents_required=["denial", "billing_qa"],
                completed_agents=["denial", "billing_qa"],
                pending_agents=[],
                failed_agents=[],
                human_review_required=True,
                priority="HIGH",
                risk_score=25,
            )

    monkeypatch.setattr(main_module, "RCMSupervisorAgent", ReviewSupervisor)

    payload = task_payload()
    payload["task_type"] = "DENIAL_REVIEW"
    with client() as test_client:
        response = test_client.post("/rcm/supervisor", json=payload)
    cleanup_dependencies()

    assert response.status_code == 200
    assert response.json()["status"] == "REVIEW"
    assert response.json()["human_review_required"] is True
