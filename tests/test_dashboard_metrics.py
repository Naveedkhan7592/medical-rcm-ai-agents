from decimal import Decimal

from dashboard.metrics import compute_overview_metrics


def test_compute_overview_metrics_uses_synthetic_data() -> None:
    metrics = compute_overview_metrics(
        total_claims=50,
        total_billed_amount=Decimal("8750.00"),
        total_paid_amount=Decimal("6400.00"),
        total_denials=15,
        outstanding_ar=Decimal("2100.00"),
        human_review_queue=6,
        high_risk_items=4,
    )

    assert metrics["total_claims"] == 50
    assert metrics["total_billed_amount"] == Decimal("8750.00")
    assert metrics["total_paid_amount"] == Decimal("6400.00")
    assert metrics["total_denials"] == 15
    assert metrics["outstanding_ar"] == Decimal("2100.00")
    assert metrics["human_review_queue"] == 6
    assert metrics["high_risk_items"] == 4
    assert metrics["denial_rate"] == Decimal("30.00")


def test_compute_overview_metrics_handles_missing_data() -> None:
    metrics = compute_overview_metrics(
        total_claims=0,
        total_billed_amount=None,
        total_paid_amount=None,
        total_denials=0,
        outstanding_ar=None,
        human_review_queue=0,
        high_risk_items=0,
    )

    assert metrics["total_claims"] == 0
    assert metrics["total_billed_amount"] is None
    assert metrics["total_paid_amount"] is None
    assert metrics["outstanding_ar"] is None
    assert metrics["denial_rate"] is None
    assert metrics["human_review_queue"] == 0
    assert metrics["high_risk_items"] == 0
