import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .engine import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowModel(Base):
    __tablename__ = "workflows"

    workflow_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    definition: Mapped[dict] = mapped_column(JSON)  # full WorkflowDefinition as JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    created_by: Mapped[str] = mapped_column(String(255), default="user")


class ExecutionModel(Base):
    __tablename__ = "executions"

    execution_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(36))
    temporal_run_id: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(50), default="started")
    trigger_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
