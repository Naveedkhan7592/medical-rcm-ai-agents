from __future__ import annotations

from decimal import Decimal
from typing import Any


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def compute_overview_metrics(
    *,
    total_claims: int | None,
    total_billed_amount: Decimal | int | str | None,
    total_paid_amount: Decimal | int | str | None,
    total_denials: int | None,
    outstanding_ar: Decimal | int | str | None,
    human_review_queue: int | None,
    high_risk_items: int | None,
) -> dict[str, Any]:
    billed = _as_decimal(total_billed_amount)
    paid = _as_decimal(total_paid_amount)
    ar = _as_decimal(outstanding_ar)

    denial_rate: Decimal | None = None
    if total_claims and total_claims > 0 and total_denials is not None:
        denial_rate = (Decimal(total_denials) / Decimal(total_claims) * Decimal("100")).quantize(Decimal("0.01"))

    return {
        "total_claims": total_claims or 0,
        "total_billed_amount": billed,
        "total_paid_amount": paid,
        "total_denials": total_denials or 0,
        "outstanding_ar": ar,
        "denial_rate": denial_rate,
        "human_review_queue": human_review_queue or 0,
        "high_risk_items": high_risk_items or 0,
    }
