from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    payer: Mapped[str] = mapped_column(String(120))
    provider_id: Mapped[str] = mapped_column(String(64))
    service_date: Mapped[date] = mapped_column(Date)
    icd_codes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    cpt_codes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    modifiers: Mapped[list[Any]] = mapped_column(JSON, default=list)
    claim_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(32), default="SUBMITTED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    patient: Mapped["Patient"] = relationship(back_populates="claims")
    denials: Mapped[list["Denial"]] = relationship(back_populates="claim")
    payments: Mapped[list["Payment"]] = relationship(back_populates="claim")
