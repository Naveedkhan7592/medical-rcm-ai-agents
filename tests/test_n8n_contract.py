import json
from pathlib import Path


WORKFLOW_DIR = Path(__file__).parents[1] / "workflows" / "n8n"
WORKFLOWS = [
    "rcm_supervisor_workflow.json",
    "denial_to_appeal_workflow.json",
    "human_review_workflow.json",
]


def load_workflow(name: str) -> dict:
    with (WORKFLOW_DIR / name).open(encoding="utf-8") as workflow_file:
        return json.load(workflow_file)


def node_names(workflow: dict) -> set[str]:
    return {node["name"] for node in workflow["nodes"]}


def test_workflow_files_exist_and_are_valid_json() -> None:
    for name in WORKFLOWS:
        assert (WORKFLOW_DIR / name).is_file()
        workflow = load_workflow(name)
        assert workflow["nodes"]
        assert workflow["connections"]


def test_primary_workflow_has_webhook_and_supervisor_request() -> None:
    workflow = load_workflow("rcm_supervisor_workflow.json")
    types = {node["type"] for node in workflow["nodes"]}
    assert "n8n-nodes-base.webhook" in types
    request_nodes = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.httpRequest"]
    assert request_nodes
    assert any("/rcm/supervisor" in node["parameters"]["url"] for node in request_nodes)


def test_primary_workflow_validates_and_branches_statuses() -> None:
    workflow = load_workflow("rcm_supervisor_workflow.json")
    names = node_names(workflow)
    assert {"Validate Input", "Normalize Supervisor Response", "Route Supervisor Status", "Success", "Waiting - Missing Information", "Human Review", "Error Handler"} <= names
    switch = next(node for node in workflow["nodes"] if node["name"] == "Route Supervisor Status")
    outputs = switch["parameters"]["rules"]["values"]
    output_keys = {item["outputKey"] for item in outputs}
    assert {"COMPLETED", "WAITING", "REVIEW", "ERROR"} <= output_keys


def test_primary_workflow_validates_complete_supervisor_task_fields() -> None:
    workflow = load_workflow("rcm_supervisor_workflow.json")
    validate = next(node for node in workflow["nodes"] if node["name"] == "Validate Input")
    code = validate["parameters"]["jsCode"]
    for field in ("task_id", "claim_id", "task_type", "priority", "input_data", "requested_action"):
        assert f"'{field}'" in code


def test_denial_and_human_review_workflows_have_safety_nodes() -> None:
    denial = load_workflow("denial_to_appeal_workflow.json")
    human = load_workflow("human_review_workflow.json")
    assert "Human Review Required" in node_names(denial)
    assert "Wait for Human Decision" in node_names(human)
    assert "Record Human Decision" in node_names(human)
    assert any("external_actions_allowed:false" in str(node["parameters"]) for node in human["nodes"])


def test_workflows_contain_no_obvious_secrets() -> None:
    for name in WORKFLOWS:
        content = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
        assert "OPENAI_API_KEY=" not in content
        assert "sk-" not in content
        assert "postgresql://user:password@" not in content


def test_workflow_uses_configurable_api_base_url() -> None:
    workflow = load_workflow("rcm_supervisor_workflow.json")
    request = next(node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.httpRequest")
    assert "$env.RCM_API_BASE_URL" in request["parameters"]["url"]
    assert request["parameters"]["options"]["timeout"] == 30000
