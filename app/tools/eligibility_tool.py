from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from app.schemas import EligibilityCheckResult, EligibilityState


DEFAULT_ELIGIBILITY_PATH = Path(__file__).resolve().parents[2] / "data" / "eligibility.json"


class EligibilityTool:
    """Read-only eligibility lookup over synthetic demo records."""

    def __init__(self, data_path: str | Path = DEFAULT_ELIGIBILITY_PATH) -> None:
        self.data_path = Path(data_path)
        self._records = self._load_records()

    def _load_records(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        with self.data_path.open(encoding="utf-8") as data_file:
            document = json.load(data_file)
        records = {}
        for record in document.get("records", []):
            key = (record["patient_id"], record["payer"], record["member_id"])
            records[key] = record
        return records

    def check_eligibility(
        self,
        patient_id: str,
        payer: str | None,
        member_id: str | None,
    ) -> EligibilityCheckResult:
        if not payer or not member_id:
            return EligibilityCheckResult(
                patient_id=patient_id,
                payer=payer,
                member_id=member_id,
                eligibility_state=EligibilityState.UNKNOWN,
                source="synthetic_demo",
            )

        record = self._records.get((patient_id, payer, member_id))
        if record is None:
            return EligibilityCheckResult(
                patient_id=patient_id,
                payer=payer,
                member_id=member_id,
                eligibility_state=EligibilityState.UNKNOWN,
                source="synthetic_demo",
            )

        eligible = bool(record["eligible"])
        return EligibilityCheckResult(
            patient_id=record["patient_id"],
            payer=record["payer"],
            member_id=record["member_id"],
            eligible=eligible,
            eligibility_state=(EligibilityState.ELIGIBLE if eligible else EligibilityState.INELIGIBLE),
            coverage_start=self._parse_date(record.get("coverage_start")),
            coverage_end=self._parse_date(record.get("coverage_end")),
            source=record.get("source", "synthetic_demo"),
        )

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        return date.fromisoformat(value) if value else None


def check_eligibility(
    patient_id: str,
    payer: str | None,
    member_id: str | None,
) -> EligibilityCheckResult:
    """Convenience interface for a synthetic eligibility lookup."""
    return EligibilityTool().check_eligibility(patient_id, payer, member_id)
