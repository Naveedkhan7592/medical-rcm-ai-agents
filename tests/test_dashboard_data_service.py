from dashboard.data_service import load_dashboard_data


def test_load_dashboard_data_uses_real_synthetic_records() -> None:
    data = load_dashboard_data()

    assert "claims" in data
    assert "denials" in data
    assert "payments" in data
    assert "patients" in data

    assert len(data["claims"]) > 0
    assert len(data["denials"]) > 0
    assert len(data["payments"]) > 0

    assert data["claims"][0]["claim_id"] == "CLM-001"
    assert data["denials"][0]["denial_id"] == "DEN-001"
    assert data["payments"][0]["payment_id"] == "PAY-001"


def test_load_dashboard_data_exposes_human_review_queue() -> None:
    data = load_dashboard_data()

    queue = data["human_review_queue"]
    assert isinstance(queue, list)
    assert all("claim_id" in item for item in queue)
    assert all("reason" in item for item in queue)
