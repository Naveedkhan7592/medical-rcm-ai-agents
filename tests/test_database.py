from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Claim, Denial, Patient, Payment
from scripts.seed_data import seed_data


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_database_models_create_all_tables(db: Session) -> None:
    table_names = set(Base.metadata.tables)
    assert {"patients", "claims", "denials", "payments", "agent_tasks", "approvals", "audit_logs"} <= table_names


def test_synthetic_data_loads_without_duplicates(db: Session) -> None:
    first_insert = seed_data(db)
    second_insert = seed_data(db)

    assert first_insert == {"patients": 20, "claims": 50, "denials": 20, "payments": 30}
    assert second_insert == {"patients": 0, "claims": 0, "denials": 0, "payments": 0}
    assert db.scalar(select(Patient).where(Patient.patient_id == "PAT-001")) is not None
    assert db.scalar(select(Claim).where(Claim.claim_id == "CLM-001")) is not None
    assert db.scalar(select(Denial).where(Denial.denial_id == "DEN-001")) is not None
    assert db.scalar(select(Payment).where(Payment.payment_id == "PAY-001")) is not None


def test_claim_patient_relationship_works(db: Session) -> None:
    seed_data(db)

    claim = db.scalar(select(Claim).where(Claim.claim_id == "CLM-001"))

    assert claim is not None
    assert claim.patient is not None
    assert claim.patient.patient_id == "PAT-001"
    assert claim.patient.name == "Demo Patient 001"
