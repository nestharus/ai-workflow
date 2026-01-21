"""SQLAlchemy models for workflow state machine.

Tables:
- workflows: Root workflow tracking (id, type, phase, status, config)
- sessions: Agent session tracking within workflows
- context_logs: Event logs for context capture and summarization
- input_requests: User input requests for pause/resume
- artifacts: Outputs from agents (drafts, plans, reviews, etc.)
- checkpoints: Partial completion state for resume
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


def _new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Workflow(Base):
    """Root workflow tracking.

    Each workflow represents a complete article writing session that can be
    paused and resumed. Multiple workflows can run concurrently.
    """

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="article-writer")
    phase: Mapped[str] = mapped_column(String(50), nullable=False, default="init")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    # Relationships
    sessions: Mapped[list[Session]] = relationship(
        "Session", back_populates="workflow", cascade="all, delete-orphan"
    )
    input_requests: Mapped[list[InputRequest]] = relationship(
        "InputRequest", back_populates="workflow", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact", back_populates="workflow", cascade="all, delete-orphan"
    )
    checkpoints: Mapped[list[Checkpoint]] = relationship(
        "Checkpoint", back_populates="workflow", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Workflow(id={self.id!r}, phase={self.phase!r}, status={self.status!r})>"


class Session(Base):
    """Agent session within a workflow.

    Each session tracks a single agent's execution (planner, writer, reviewer, etc.)
    with context logging and resume capability.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    resume_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="sessions")
    context_logs: Mapped[list[ContextLog]] = relationship(
        "ContextLog", back_populates="session", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact", back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Session(id={self.id!r}, agent_type={self.agent_type!r}, status={self.status!r})>"


class ContextLog(Base):
    """Event log for context capture.

    Captures everything an agent does for later summarization:
    - agent_output: Raw stdout from agent subprocess
    - tool_call: Local tool invocation (lint, skeleton, etc.)
    - tool_result: Result from local tool
    - error: Error events
    """

    __tablename__ = "context_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="context_logs")

    def __repr__(self) -> str:
        return f"<ContextLog(id={self.id}, event_type={self.event_type!r})>"


class InputRequest(Base):
    """User input request for pause/resume.

    When a workflow needs user input, an InputRequest is created and the
    workflow pauses. The orchestrator (Claude Code) presents this to the user,
    collects the response, and resumes the workflow.
    """

    __tablename__ = "input_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    request_type: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="input_requests")

    def __repr__(self) -> str:
        return f"<InputRequest(id={self.id!r}, type={self.request_type!r}, responded={self.response is not None})>"


class Artifact(Base):
    """Output from an agent.

    Stores all outputs: plans, drafts, reviews, analysis results, etc.
    """

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="artifacts")
    session: Mapped[Session | None] = relationship("Session", back_populates="artifacts")

    def __repr__(self) -> str:
        return f"<Artifact(id={self.id!r}, type={self.artifact_type!r}, name={self.name!r})>"


class Checkpoint(Base):
    """Partial completion state for resume.

    Stores work items, gaps, questions, and next steps identified during
    phase completion for later resume with full context.
    """

    __tablename__ = "checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    phase: Mapped[str] = mapped_column(String(50), nullable=False)
    partial_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="checkpoints")

    def __repr__(self) -> str:
        return f"<Checkpoint(id={self.id!r}, phase={self.phase!r})>"
