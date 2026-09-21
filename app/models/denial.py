from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Denial(Base):
    __tablename__ = "denials"

    id: Mapped[int] = mapped_column(primary_key=True)
    denial_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.claim_id"), index=True)
    carc_code: Mapped[str] = mapped_column(String(16))
    rarc_code: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    denied_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    claim: Mapped["Claim"] = relationship(back_populates="denials")
