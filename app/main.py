from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents import ARAgent, AppealAgent, BillingQAAgent, ClaimsAgent, CodingAgent, DenialAgent, EligibilityAgent, PaymentAgent, RCMSupervisorAgent
from app.models import Claim, Denial, Patient, Payment
from app.schemas import ARAgentResult, AppealResult, BillingQAResult, ClaimsAgentResult, CodingAgentResult, DenialAgentResult, PaymentAgentResult, SupervisorResult, SupervisorTask
from app.services.database import get_db


app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "medical-rcm-ai",
    }


@app.get("/db/health")
def database_health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {"status": "ok", "database": "connected"}


@app.post("/claims/{claim_id}/validate", response_model=ClaimsAgentResult)
def validate_claim(claim_id: str, db: Session = Depends(get_db)) -> ClaimsAgentResult:
    def claim_lookup(requested_claim_id: str) -> Claim | None:
        return db.scalar(select(Claim).where(Claim.claim_id == requested_claim_id))

    claim = claim_lookup(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")

    return ClaimsAgent(
        claim_lookup=claim_lookup,
        patient_lookup=lambda patient_id: db.scalar(select(Patient).where(Patient.patient_id == patient_id)),
    ).run(claim_id)


@app.post("/claims/{claim_id}/eligibility")
def check_claim_eligibility(claim_id: str, db: Session = Depends(get_db)):
    claim = db.scalar(select(Claim).where(Claim.claim_id == claim_id))
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return EligibilityAgent().process_claim(claim)


@app.post("/claims/{claim_id}/coding", response_model=CodingAgentResult)
def check_claim_coding(claim_id: str, db: Session = Depends(get_db)) -> CodingAgentResult:
    def claim_lookup(requested_claim_id: str) -> Claim | None:
        return db.scalar(select(Claim).where(Claim.claim_id == requested_claim_id))

    if claim_lookup(claim_id) is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return CodingAgent(claim_lookup=claim_lookup).run(claim_id)


@app.post("/denials/{denial_id}/analyze", response_model=DenialAgentResult)
def analyze_denial(denial_id: str, db: Session = Depends(get_db)) -> DenialAgentResult:
    def denial_lookup(requested_denial_id: str) -> Denial | None:
        return db.scalar(select(Denial).where(Denial.denial_id == requested_denial_id))

    def claim_lookup(claim_id: str) -> Claim | None:
        return db.scalar(select(Claim).where(Claim.claim_id == claim_id))

    if denial_lookup(denial_id) is None:
        raise HTTPException(status_code=404, detail="denial not found")
    return DenialAgent(denial_lookup=denial_lookup, claim_lookup=claim_lookup).run(denial_id)


@app.post("/payments/{payment_id}/analyze", response_model=PaymentAgentResult)
def analyze_payment(payment_id: str, db: Session = Depends(get_db)) -> PaymentAgentResult:
    def payment_lookup(requested_payment_id: str) -> Payment | None:
        return db.scalar(select(Payment).where(Payment.payment_id == requested_payment_id))

    def claim_lookup(claim_id: str) -> Claim | None:
        return db.scalar(select(Claim).where(Claim.claim_id == claim_id))

    payment = payment_lookup(payment_id)
    if payment is None:
        return PaymentAgent(payment_lookup=payment_lookup, claim_lookup=claim_lookup).run(payment_id)
    return PaymentAgent(payment_lookup=payment_lookup, claim_lookup=claim_lookup).run(payment_id)


@app.post("/claims/{claim_id}/ar/analyze", response_model=ARAgentResult)
def analyze_ar(claim_id: str, db: Session = Depends(get_db)) -> ARAgentResult:
    def claim_lookup(requested_claim_id: str) -> Claim | None:
        return db.scalar(select(Claim).where(Claim.claim_id == requested_claim_id))

    def payment_lookup(requested_claim_id: str) -> list[Payment]:
        return list(db.scalars(select(Payment).where(Payment.claim_id == requested_claim_id)).all())

    def denial_lookup(requested_claim_id: str) -> list[Denial]:
        return list(db.scalars(select(Denial).where(Denial.claim_id == requested_claim_id)).all())

    claim = claim_lookup(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return ARAgent(
        claim_lookup=claim_lookup,
        payment_lookup=payment_lookup,
        payment_agent=PaymentAgent(claim_lookup=claim_lookup),
        denial_lookup=denial_lookup,
        denial_agent=DenialAgent(claim_lookup=claim_lookup),
    ).run(claim_id)


@app.post("/claims/{claim_id}/billing-qa", response_model=BillingQAResult)
def billing_qa(claim_id: str, db: Session = Depends(get_db)) -> BillingQAResult:
    def claim_lookup(requested_claim_id: str) -> Claim | None:
        return db.scalar(select(Claim).where(Claim.claim_id == requested_claim_id))

    claim = claim_lookup(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return BillingQAAgent(claim_lookup=claim_lookup).run(claim_id)


@app.post("/claims/{claim_id}/appeal", response_model=AppealResult)
def prepare_appeal(claim_id: str, db: Session = Depends(get_db)) -> AppealResult:
    def claim_lookup(requested_claim_id: str) -> Claim | None:
        return db.scalar(select(Claim).where(Claim.claim_id == requested_claim_id))

    def denial_lookup(requested_claim_id: str) -> list[Denial]:
        return list(db.scalars(select(Denial).where(Denial.claim_id == requested_claim_id)).all())

    return AppealAgent(claim_lookup=claim_lookup, denial_lookup=denial_lookup).run(claim_id)


@app.post("/rcm/supervisor", response_model=SupervisorResult)
def supervise_rcm(task: SupervisorTask, db: Session = Depends(get_db)) -> SupervisorResult:
    def claim_lookup(claim_id: str) -> Claim | None:
        return db.scalar(select(Claim).where(Claim.claim_id == claim_id))

    return RCMSupervisorAgent(claim_lookup=claim_lookup).run(task)
