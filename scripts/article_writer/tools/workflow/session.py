"""Session manager for agent session lifecycle.

Manages the creation, pausing, resuming, and completion of agent sessions
within workflows.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .context_logger import ContextLogger
from .context_summarizer import ContextSummarizer, PartialState
from .database import Database
from .models import Checkpoint, Session


class SessionManager:
    """Manages agent sessions within workflows.

    Usage:
        manager = SessionManager(db)

        # Create a new session
        session = manager.create_session(workflow_id, "planner")

        # Get the active session
        session = manager.get_active_session(workflow_id)

        # Pause with context summarization
        manager.pause_session(session.id, context_logger)

        # Resume
        resume_context = manager.get_resume_context(session.id)
    """

    def __init__(self, db: Database, glm_cmd: str = "./glm") -> None:
        """Initialize session manager.

        Args:
            db: Database instance
            glm_cmd: Path to glm script for summarization
        """
        self.db = db
        self.summarizer = ContextSummarizer(glm_cmd)

    def create_session(self, workflow_id: str, agent_type: str) -> Session:
        """Create a new agent session.

        Args:
            workflow_id: Parent workflow ID
            agent_type: Type of agent (e.g., "planner", "writer", "reviewer")

        Returns:
            Created Session object
        """
        with self.db.session() as db_session:
            session = Session(
                workflow_id=workflow_id,
                agent_type=agent_type,
                status="active",
            )
            db_session.add(session)
            db_session.flush()  # Get the ID

            # Detach so we can return it
            db_session.expunge(session)
            return session

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session object or None if not found
        """
        with self.db.session() as db_session:
            session = db_session.query(Session).filter(Session.id == session_id).first()
            if session:
                db_session.expunge(session)
            return session

    def get_active_session(self, workflow_id: str) -> Session | None:
        """Get the currently active session for a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            Active Session or None if no active session
        """
        with self.db.session() as db_session:
            session = (
                db_session.query(Session)
                .filter(Session.workflow_id == workflow_id, Session.status == "active")
                .order_by(Session.created_at.desc())
                .first()
            )
            if session:
                db_session.expunge(session)
            return session

    def get_workflow_sessions(self, workflow_id: str) -> list[Session]:
        """Get all sessions for a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            List of Session objects ordered by creation time
        """
        with self.db.session() as db_session:
            sessions = (
                db_session.query(Session)
                .filter(Session.workflow_id == workflow_id)
                .order_by(Session.created_at)
                .all()
            )
            for s in sessions:
                db_session.expunge(s)
            return sessions

    def pause_session(
        self,
        session_id: str,
        context_logger: ContextLogger,
        workflow_phase: str,
    ) -> PartialState:
        """Pause a session with context summarization.

        Calls GLM to summarize the session context and stores it
        for later resume.

        Args:
            session_id: Session ID to pause
            context_logger: ContextLogger with session logs
            workflow_phase: Current workflow phase

        Returns:
            PartialState extracted from the summary
        """
        # Get session logs
        summary_input = context_logger.get_summary_input()

        # Summarize with GLM
        summary_text = self.summarizer.summarize_session(summary_input)
        partial_state = self.summarizer.extract_partial_state(summary_text)

        # Update session status and resume context
        with self.db.session() as db_session:
            session = db_session.query(Session).filter(Session.id == session_id).first()
            if session:
                session.status = "paused"
                session.resume_context = summary_text
                session.updated_at = datetime.now(UTC)

            # Also create a checkpoint
            checkpoint = Checkpoint(
                workflow_id=session.workflow_id if session else "",
                phase=workflow_phase,
                partial_state=partial_state.to_dict(),
            )
            db_session.add(checkpoint)

        return partial_state

    def resume_session(self, session_id: str) -> tuple[Session, str]:
        """Resume a paused session.

        Args:
            session_id: Session ID to resume

        Returns:
            Tuple of (Session, resume_context_text)

        Raises:
            ValueError: If session not found or not paused
        """
        with self.db.session() as db_session:
            session = db_session.query(Session).filter(Session.id == session_id).first()

            if not session:
                raise ValueError(f"Session not found: {session_id}")

            if session.status != "paused":
                raise ValueError(f"Session is not paused: {session.status}")

            # Get the latest checkpoint for context
            checkpoint = (
                db_session.query(Checkpoint)
                .filter(Checkpoint.workflow_id == session.workflow_id)
                .order_by(Checkpoint.created_at.desc())
                .first()
            )

            # Build resume context
            resume_context = ""
            if session.resume_context:
                partial_state = PartialState.from_dict(
                    checkpoint.partial_state if checkpoint else {}
                )
                resume_context = self.summarizer.format_resume_context(partial_state)

            # Update session status
            session.status = "active"
            session.updated_at = datetime.now(UTC)

            db_session.expunge(session)
            return session, resume_context

    def complete_session(self, session_id: str) -> None:
        """Mark a session as completed.

        Args:
            session_id: Session ID to complete
        """
        with self.db.session() as db_session:
            session = db_session.query(Session).filter(Session.id == session_id).first()
            if session:
                session.status = "completed"
                session.updated_at = datetime.now(UTC)

    def get_resume_context(self, session_id: str) -> str:
        """Get formatted resume context for a session.

        Args:
            session_id: Session ID

        Returns:
            Formatted resume context text, or empty string if none
        """
        session = self.get_session(session_id)
        if not session or not session.resume_context:
            return ""

        # Parse and format the resume context
        partial_state = self.summarizer.extract_partial_state(session.resume_context)
        return self.summarizer.format_resume_context(partial_state)

    def get_latest_checkpoint(self, workflow_id: str) -> Checkpoint | None:
        """Get the latest checkpoint for a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            Latest Checkpoint or None
        """
        with self.db.session() as db_session:
            checkpoint = (
                db_session.query(Checkpoint)
                .filter(Checkpoint.workflow_id == workflow_id)
                .order_by(Checkpoint.created_at.desc())
                .first()
            )
            if checkpoint:
                db_session.expunge(checkpoint)
            return checkpoint
