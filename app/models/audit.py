from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("agent_tasks.task_id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    task: Mapped["AgentTask"] = relationship(back_populates="audit_logs")
