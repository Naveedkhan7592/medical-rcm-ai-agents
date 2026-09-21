import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, Denial, Patient, Payment
from app.services.database import SessionLocal
from app.services.init_db import init_db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_records(filename: str, key: str) -> list[dict[str, Any]]:
    with (DATA_DIR / filename).open(encoding="utf-8") as data_file:
        document = json.load(data_file)
    return document[key]


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def seed_data(db: Session, data_dir: Path = DATA_DIR) -> dict[str, int]:
    def records(filename: str, key: str) -> list[dict[str, Any]]:
        with (data_dir / filename).open(encoding="utf-8") as data_file:
            return json.load(data_file)[key]

    inserted = {"patients": 0, "claims": 0, "denials": 0, "payments": 0}

    for item in records("patients.json", "records"):
        if db.scalar(select(Patient).where(Patient.patient_id == item["patient_id"])) is None:
            db.add(
                Patient(
                    patient_id=item["patient_id"],
                    name=item["name"],
                    date_of_birth=parse_date(item["date_of_birth"]),
                    payer=item["payer"],
                    member_id=item["member_id"],
                )
            )
            inserted["patients"] += 1
    db.flush()

    for item in records("claims.json", "records"):
        if db.scalar(select(Claim).where(Claim.claim_id == item["claim_id"])) is None:
            db.add(
                Claim(
                    claim_id=item["claim_id"],
                    patient_id=item["patient_id"],
                    payer=item["payer"],
                    provider_id=item["provider_id"],
                    service_date=parse_date(item["service_date"]),
                    icd_codes=item["icd_codes"],
                    cpt_codes=item["cpt_codes"],
                    modifiers=item["modifiers"],
                    claim_amount=Decimal(str(item["claim_amount"])),
                    status=item["status"],
                )
            )
            inserted["claims"] += 1
    db.flush()

    for item in records("denials.json", "records"):
        if db.scalar(select(Denial).where(Denial.denial_id == item["denial_id"])) is None:
            db.add(
                Denial(
                    denial_id=item["denial_id"],
                    claim_id=item["claim_id"],
                    carc_code=item["carc_code"],
                    rarc_code=item["rarc_code"],
                    reason=item["reason"],
                    denied_amount=Decimal(str(item["denied_amount"])),
                    status=item["status"],
                )
            )
            inserted["denials"] += 1
    db.flush()

    for item in records("payments.json", "records"):
        if db.scalar(select(Payment).where(Payment.payment_id == item["payment_id"])) is None:
            db.add(
                Payment(
                    payment_id=item["payment_id"],
                    claim_id=item["claim_id"],
                    payer=item["payer"],
                    allowed_amount=Decimal(str(item["allowed_amount"])),
                    paid_amount=Decimal(str(item["paid_amount"])),
                    adjustment_amount=Decimal(str(item["adjustment_amount"])),
                    patient_responsibility=Decimal(str(item["patient_responsibility"])),
                    payment_date=parse_date(item["payment_date"]),
                    status=item["status"],
                )
            )
            inserted["payments"] += 1

    db.commit()
    return inserted


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        inserted = seed_data(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"Patients inserted: {inserted['patients']}")
    print(f"Claims inserted: {inserted['claims']}")
    print(f"Denials inserted: {inserted['denials']}")
    print(f"Payments inserted: {inserted['payments']}")


if __name__ == "__main__":
    main()
