import json
import os
import re
from pathlib import Path
import subprocess
import sys

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_env_example_contains_placeholders_not_populated_openai_key() -> None:
    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    openai_lines = [line for line in content.splitlines() if line.startswith("OPENAI_API_KEY=")]
    postgres_password_lines = [line for line in content.splitlines() if line.startswith("POSTGRES_PASSWORD=")]
    assert openai_lines
    assert all(line.partition("=")[2].strip() == "" for line in openai_lines)
    assert postgres_password_lines
    assert all(line.partition("=")[2].strip() == "" for line in postgres_password_lines)
    assert not re.search(r"sk-[A-Za-z0-9]{12,}", content)


def test_workflow_json_has_no_obvious_credentials() -> None:
    workflow_dir = ROOT / "workflows" / "n8n"
    paths = list(workflow_dir.rglob("*.json"))
    assert paths
    secret_pattern = re.compile(r"sk-[A-Za-z0-9]{12,}|OPENAI_API_KEY\s*[:=]\s*['\"]?[^\s'\"]+", re.IGNORECASE)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        json.loads(text)
        assert not secret_pattern.search(text), path


def test_demo_fixtures_have_no_credential_patterns() -> None:
    secret_pattern = re.compile(r"sk-[A-Za-z0-9]{12,}|password\s*[:=]\s*['\"]?[^\s'\"]+|api[_-]?key\s*[:=]\s*['\"]?[^\s'\"]+", re.IGNORECASE)
    for path in (ROOT / "data").glob("*.json"):
        assert not secret_pattern.search(path.read_text(encoding="utf-8")), path


def test_streamlit_secrets_are_ignored_and_not_committed() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".streamlit/secrets.toml" in gitignore
    assert not (ROOT / ".streamlit" / "secrets.toml").exists()


def test_settings_and_app_configuration_do_not_require_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.OPENAI_API_KEY == ""


def test_fastapi_imports_in_process_without_openai_key() -> None:
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    completed = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print(app.title)"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Synthetic Demo API" in completed.stdout
