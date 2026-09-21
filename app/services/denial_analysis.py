from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.schemas import DenialCategory


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class DenialAnalysisService:
    """Load synthetic denial-code and payer-policy facts for deterministic analysis."""

    def __init__(self, data_dir: str | Path = DEFAULT_DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.code_reference = self._load_json("denial_codes.json")
        self.payer_policies = self._load_payer_policies()

    def classify_codes(self, carc_code: str | None, rarc_code: str | None) -> DenialCategory | None:
        categories = []
        for code_type, code in (("carc", carc_code), ("rarc", rarc_code)):
            mapping = self.code_reference.get(code_type, {}).get(str(code)) if code else None
            if mapping:
                categories.append(DenialCategory(mapping["category"]))
        if categories and all(category == categories[0] for category in categories):
            return categories[0]
        return categories[0] if len(set(categories)) == 1 else None

    def policy_for(self, payer: str | None) -> dict[str, Any] | None:
        return self.payer_policies.get(payer) if payer else None

    def code_description(self, code_type: str, code: str | None) -> str | None:
        if not code:
            return None
        mapping = self.code_reference.get(code_type, {}).get(str(code))
        return mapping.get("description") if mapping else None

    def _load_json(self, filename: str) -> dict[str, Any]:
        with (self.data_dir / filename).open(encoding="utf-8") as data_file:
            return json.load(data_file)

    def _load_payer_policies(self) -> dict[str, dict[str, Any]]:
        document = self._load_json("payer_policies.json")
        return {policy["payer"]: policy for policy in document.get("policies", [])}


def value(item: Mapping[str, Any] | Any | None, name: str, default: Any = None) -> Any:
    if item is None:
        return default
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)
