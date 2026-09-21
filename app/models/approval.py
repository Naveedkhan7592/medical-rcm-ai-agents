from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("agent_tasks.task_id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    reviewer: Mapped[str | None] = mapped_column(String(120))
    comments: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    task: Mapped["AgentTask"] = relationship(back_populates="approvals")
