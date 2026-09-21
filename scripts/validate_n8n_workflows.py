"""Validate exported n8n workflow structure without requiring an n8n runtime."""

from __future__ import annotations

import json
import sys
from pathlib import Path


WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "workflows" / "n8n"
SECRET_MARKERS = ("OPENAI_API_KEY=", "sk-", "postgresql://user:password@")


def validate_workflow(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path.name}: invalid JSON: {exc}"]

    if not isinstance(workflow.get("nodes"), list) or not workflow["nodes"]:
        errors.append(f"{path.name}: nodes must be a non-empty list")
    if not isinstance(workflow.get("connections"), dict):
        errors.append(f"{path.name}: connections must be an object")
    names = {node.get("name") for node in workflow.get("nodes", [])}
    if None in names:
        errors.append(f"{path.name}: every node requires a name")
    if path.name in {"rcm_supervisor_workflow.json", "denial_to_appeal_workflow.json"}:
        if not any(node.get("type") == "n8n-nodes-base.webhook" for node in workflow.get("nodes", [])):
            errors.append(f"{path.name}: webhook node missing")
        if not any(node.get("type") == "n8n-nodes-base.httpRequest" and "/rcm/supervisor" in str(node.get("parameters", {}).get("url", "")) for node in workflow.get("nodes", [])):
            errors.append(f"{path.name}: /rcm/supervisor HTTP request missing")
    content = path.read_text(encoding="utf-8")
    for marker in SECRET_MARKERS:
        if marker in content:
            errors.append(f"{path.name}: forbidden secret marker {marker}")
    if "eclinical" in content.lower() or "payer-api" in content.lower():
        errors.append(f"{path.name}: external payer/eClinicalWorks endpoint reference found")
    return errors


def main() -> int:
    paths = sorted(WORKFLOW_DIR.glob("*.json"))
    if not paths:
        print(f"No workflow JSON files found under {WORKFLOW_DIR}", file=sys.stderr)
        return 1
    errors = [error for path in paths for error in validate_workflow(path)]
    if errors:
        print("n8n workflow validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"Validated {len(paths)} n8n workflow JSON files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
