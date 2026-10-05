from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evaluation.evaluator import evaluate_all
from app.services.demo_scenarios import get_demo_scenarios


def _load_records(path: Path, key: str) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get(key, [])


def load_dashboard_data(base_dir: str | Path | None = None) -> dict[str, Any]:
    data_dir = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parents[1] / "data"

    claims = _load_records(data_dir / "claims.json", "records")
    denials = _load_records(data_dir / "denials.json", "records")
    payments = _load_records(data_dir / "payments.json", "records")
    patients = _load_records(data_dir / "patients.json", "records")

    human_review_queue = [
        {
            "claim_id": item["claim_id"],
            "denial_id": item["denial_id"],
            "reason": item["reason"],
            "status": item.get("status", "OPEN"),
            "risk_score": min(int(float(item.get("denied_amount", 0)) // 10), 100),
        }
        for item in sorted(denials, key=lambda row: row.get("denial_id", ""))
        if str(item.get("status", "OPEN")).upper() in {"OPEN", "PENDING", "REVIEW"}
    ]

    return {
        "claims": claims,
        "denials": denials,
        "payments": payments,
        "patients": patients,
        "human_review_queue": human_review_queue,
    }


def load_demo_scenarios() -> list[dict[str, Any]]:
    return get_demo_scenarios()


def load_evaluation_summary():
    return evaluate_all()
