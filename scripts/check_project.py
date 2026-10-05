from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRECTORIES = (".github/workflows", "app", "dashboard", "data", "docs", "scripts", "tests", "workflows/n8n")
REQUIRED_FILES = (
    ".env.example",
    ".gitignore",
    "app/main.py",
    "app/config.py",
    "dashboard/streamlit_app.py",
    "requirements.txt",
    ".github/workflows/ci.yml",
    "scripts/evaluate_demo_scenarios.py",
    "scripts/validate_n8n_workflows.py",
)
CORE_IMPORTS = ("app.main", "app.evaluation.evaluator", "dashboard.data_service", "dashboard.metrics")
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
)


def check_project(root: Path = ROOT) -> list[tuple[str, bool, str]]:
    root = root.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    structure_missing = [
        *(directory for directory in REQUIRED_DIRECTORIES if not (root / directory).is_dir()),
        *(filename for filename in REQUIRED_FILES if not (root / filename).is_file()),
    ]
    structure_ok = not structure_missing

    imports_ok = True
    import_details: list[str] = []
    for module in CORE_IMPORTS:
        try:
            importlib.import_module(module)
        except Exception as exc:
            imports_ok = False
            import_details.append(f"{module}: {type(exc).__name__}")

    try:
        from app.services.demo_scenarios import get_demo_scenarios

        scenarios_ok = bool(get_demo_scenarios())
    except Exception:
        scenarios_ok = False

    workflow_paths = list((root / "workflows" / "n8n").glob("*.json"))
    workflows_ok = bool(workflow_paths)
    for workflow_path in workflow_paths:
        try:
            json.loads(workflow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            workflows_ok = False
            break

    dashboard_source = root / "dashboard" / "streamlit_app.py"
    try:
        compile(dashboard_source.read_text(encoding="utf-8"), str(dashboard_source), "exec")
        dashboard_ok = True
    except (OSError, SyntaxError):
        dashboard_ok = False

    env_content = (root / ".env.example").read_text(encoding="utf-8") if (root / ".env.example").is_file() else ""
    gitignore_content = (root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").is_file() else ""
    config_paths = [root / ".env.example", *workflow_paths]
    config_safe = bool(env_content) and ".streamlit/secrets.toml" in gitignore_content
    for path in config_paths:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            config_safe = False
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            config_safe = False
    if re.search(r"^(?:OPENAI_API_KEY|POSTGRES_PASSWORD)[ \t]*=[ \t]*[^ \t\r\n]+", env_content, re.MULTILINE):
        config_safe = False

    return [
        ("Project structure", structure_ok, ", ".join(structure_missing) if structure_missing else "required paths present"),
        ("Core imports", imports_ok, "; ".join(import_details) if import_details else "core modules import"),
        ("Demo scenarios", scenarios_ok, "scenario catalog available" if scenarios_ok else "scenario catalog unavailable"),
        ("n8n workflows", workflows_ok, f"{len(workflow_paths)} valid JSON file(s)" if workflows_ok else "missing or invalid workflow JSON"),
        ("Dashboard entrypoint", dashboard_ok, "entrypoint exists and compiles" if dashboard_ok else "entrypoint missing or invalid"),
        ("Configuration safety", config_safe, "placeholder config and secrets exclusion checked" if config_safe else "configuration safety check failed"),
    ]


def main(_: Sequence[str] | None = None) -> int:
    results = check_project()
    for label, passed, detail in results:
        print(f"{label:<24} {'PASS' if passed else 'FAIL'}  {detail}")
    return 0 if all(passed for _, passed, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
