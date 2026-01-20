"""State machine engine for pausable workflow orchestration.

Manages phase transitions, pause/resume logic, and coordinates agents
for the article writing workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .context_logger import ContextLogger
from .database import Database
from .models import Artifact, InputRequest, Workflow
from .session import SessionManager


class Phase(Enum):
    """Workflow phases in order.

    The workflow supports feedback loops:
    - REVIEW -> REVISE -> REVIEW (until reviews pass or max iterations)
    - INVARIANT_CHECK -> CONDENSE -> INVARIANT_CHECK (for length violations)
    """

    INIT = "init"
    PLAN = "plan"
    RESEARCH = "research"
    DRAFT = "draft"
    ANALYZE = "analyze"
    REVIEW = "review"
    REVISE = "revise"
    FINALIZE = "finalize"
    INVARIANT_EXTRACT = "invariant_extract"  # LLM extracts invariants from brief
    INVARIANT_CHECK = "invariant_check"  # LLM verifies draft against invariants
    CONDENSE = "condense"  # When over length limit, propose cuts to user
    APPLY_CUT = "apply_cut"  # Apply user's chosen cuts
    EXPORT = "export"
    COMPLETE = "complete"


class Status(Enum):
    """Workflow status values."""

    RUNNING = "running"
    PAUSED = "paused"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    ERROR = "error"


class ActionType(Enum):
    """Types of actions the state machine can return."""

    CALL_AGENT = "call_agent"
    RUN_TOOL = "run_tool"
    USER_INPUT = "user_input"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class NextAction:
    """Describes the next action to take.

    Returned by StateMachine.get_next_action() to tell the orchestrator
    what to do next.
    """

    action: ActionType
    agent: str | None = None
    tool: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    prompt: str | None = None
    options: list[str] | None = None
    error: str | None = None
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "action": self.action.value,
            "agent": self.agent,
            "tool": self.tool,
            "inputs": self.inputs,
            "prompt": self.prompt,
            "options": self.options,
            "error": self.error,
            "request_id": self.request_id,
        }


# Phase transition map: current phase -> next phase (default, linear flow)
# Feedback loops are handled dynamically in _determine_next_phase()
PHASE_TRANSITIONS: dict[Phase, Phase] = {
    Phase.INIT: Phase.PLAN,
    Phase.PLAN: Phase.RESEARCH,
    Phase.RESEARCH: Phase.DRAFT,
    Phase.DRAFT: Phase.ANALYZE,
    Phase.ANALYZE: Phase.REVIEW,
    Phase.REVIEW: Phase.REVISE,
    Phase.REVISE: Phase.ANALYZE,  # Loop back for re-review (controlled by iteration count)
    Phase.FINALIZE: Phase.INVARIANT_EXTRACT,
    Phase.INVARIANT_EXTRACT: Phase.INVARIANT_CHECK,
    Phase.INVARIANT_CHECK: Phase.EXPORT,  # May loop to CONDENSE for length violations
    Phase.CONDENSE: Phase.APPLY_CUT,  # After user selects cuts
    Phase.APPLY_CUT: Phase.INVARIANT_CHECK,  # Re-check after cuts applied
    Phase.EXPORT: Phase.COMPLETE,
}

# Agents for each phase
PHASE_AGENTS: dict[Phase, str | list[str] | None] = {
    Phase.INIT: None,
    Phase.PLAN: "planner",
    Phase.RESEARCH: "researcher",
    Phase.DRAFT: "writer",
    Phase.ANALYZE: None,  # Local tools only
    Phase.REVIEW: ["alignment_reviewer", "value_reviewer", "flow_reviewer", "ai_tells_reviewer", "robustness_reviewer"],
    # Multi-pass fixers: run serially, each builds on previous output
    # Order: alignment (reputation) -> ai_tells (hard bans) -> flow -> value -> robustness
    Phase.REVISE: ["alignment_fixer", "ai_tells_fixer", "flow_fixer", "value_fixer", "robustness_fixer"],
    Phase.FINALIZE: "finalizer",
    Phase.INVARIANT_EXTRACT: "invariant_extractor",
    Phase.INVARIANT_CHECK: "invariant_reviewer",
    Phase.CONDENSE: "condenser",  # Proposes cuts, waits for user choice
    Phase.APPLY_CUT: "cutter",  # Applies chosen cuts
    Phase.EXPORT: None,
}

# Tools for phases that use local tools
PHASE_TOOLS: dict[Phase, list[str] | None] = {
    Phase.ANALYZE: ["lint", "tempo", "readability", "skeleton"],
}

# Maximum iterations for feedback loops
MAX_REVIEW_ITERATIONS = 3  # Max times to loop REVIEW -> REVISE
MAX_INVARIANT_ITERATIONS = 2  # Max times to loop INVARIANT_CHECK -> REVISE

# Drift detection thresholds
DRIFT_THRESHOLD_MINOR = 0.2  # Below this is "none"
DRIFT_THRESHOLD_SIGNIFICANT = 0.5  # Above this is "significant"


class StateMachine:
    """State machine for workflow orchestration.

    Manages phase transitions, determines next actions, and handles
    pause/resume logic.

    Usage:
        db = Database("workflow.db")
        sm = StateMachine(db, workflow_id)

        # Get next action
        action = sm.get_next_action()

        # Process result and advance
        sm.process_result(result)
    """

    def __init__(
        self,
        db: Database,
        workflow_id: str,
        glm_flash_cmd: str = "./glm-flash",
    ) -> None:
        """Initialize state machine.

        Args:
            db: Database instance
            workflow_id: Workflow to manage
            glm_flash_cmd: Path to glm-flash script
        """
        self.db = db
        self.workflow_id = workflow_id
        self.session_manager = SessionManager(db, glm_flash_cmd)
        self._workflow: Workflow | None = None
        self._context_logger: ContextLogger | None = None

    @property
    def workflow(self) -> Workflow:
        """Get the workflow, loading from DB if needed."""
        if self._workflow is None:
            with self.db.session() as session:
                self._workflow = (
                    session.query(Workflow).filter(Workflow.id == self.workflow_id).first()
                )
                if self._workflow:
                    session.expunge(self._workflow)
                else:
                    raise ValueError(f"Workflow not found: {self.workflow_id}")
        return self._workflow

    def _reload_workflow(self) -> None:
        """Force reload workflow from database."""
        self._workflow = None
        _ = self.workflow  # Trigger reload

    @property
    def current_phase(self) -> Phase:
        """Get the current phase."""
        return Phase(self.workflow.phase)

    @property
    def current_status(self) -> Status:
        """Get the current status."""
        return Status(self.workflow.status)

    def _update_workflow(self, **kwargs: Any) -> None:
        """Update workflow fields in database."""
        with self.db.session() as session:
            workflow = session.query(Workflow).filter(Workflow.id == self.workflow_id).first()
            if workflow:
                for key, value in kwargs.items():
                    setattr(workflow, key, value)
                workflow.updated_at = datetime.now(timezone.utc)
        self._reload_workflow()

    def get_next_action(self) -> NextAction:
        """Determine the next action based on current state.

        Returns:
            NextAction describing what to do next
        """
        self._reload_workflow()

        # Check for pending input requests
        pending_request = self._get_pending_input_request()
        if pending_request:
            return NextAction(
                action=ActionType.USER_INPUT,
                prompt=pending_request.prompt,
                options=pending_request.options,
                request_id=pending_request.id,
            )

        # Check status
        if self.current_status == Status.COMPLETED:
            return NextAction(action=ActionType.COMPLETE)

        if self.current_status == Status.ERROR:
            return NextAction(
                action=ActionType.ERROR,
                error=self.workflow.config.get("error") if self.workflow.config else "Unknown error",
            )

        if self.current_status == Status.PAUSED:
            return NextAction(
                action=ActionType.USER_INPUT,
                prompt="Workflow is paused. Resume?",
                options=["resume", "cancel"],
            )

        if self.current_status == Status.WAITING_INPUT:
            # Should have a pending request, but return generic prompt if not
            return NextAction(
                action=ActionType.USER_INPUT,
                prompt="Waiting for user input",
            )

        # Determine action based on phase
        phase = self.current_phase

        # Handle COMPLETE phase
        if phase == Phase.COMPLETE:
            self._update_workflow(status=Status.COMPLETED.value)
            return NextAction(action=ActionType.COMPLETE)

        # Get agent or tool for this phase
        agent = PHASE_AGENTS.get(phase)
        tools = PHASE_TOOLS.get(phase)

        if tools:
            # Run local tools
            return NextAction(
                action=ActionType.RUN_TOOL,
                tool=tools[0],  # First tool
                inputs={"all_tools": tools},
            )

        if agent:
            if isinstance(agent, list):
                # Multiple agents (reviewers) - run first pending
                completed = self._get_completed_agents()
                remaining = [a for a in agent if a not in completed]
                if remaining:
                    return NextAction(
                        action=ActionType.CALL_AGENT,
                        agent=remaining[0],
                        inputs={"all_agents": agent, "completed_agents": completed},
                    )
                # All agents done - will fall through to advance phase
            else:
                return NextAction(
                    action=ActionType.CALL_AGENT,
                    agent=agent,
                )

        # No agent or tool - advance to next phase
        self._advance_phase()
        return self.get_next_action()  # Recursive call for next phase

    def _get_pending_input_request(self) -> InputRequest | None:
        """Get pending input request if any."""
        with self.db.session() as session:
            request = (
                session.query(InputRequest)
                .filter(
                    InputRequest.workflow_id == self.workflow_id,
                    InputRequest.response.is_(None),
                )
                .order_by(InputRequest.created_at)
                .first()
            )
            if request:
                session.expunge(request)
            return request

    def _get_completed_agents(self) -> list[str]:
        """Get list of completed agents for current phase."""
        config = self.workflow.config or {}
        phase_completed = config.get("phase_completed_agents", {})
        return phase_completed.get(self.current_phase.value, [])

    def _mark_agent_completed(self, agent_name: str) -> None:
        """Mark an agent as completed for current phase."""
        config = self.workflow.config or {}
        phase_completed = config.get("phase_completed_agents", {})
        phase_key = self.current_phase.value
        if phase_key not in phase_completed:
            phase_completed[phase_key] = []
        if agent_name not in phase_completed[phase_key]:
            phase_completed[phase_key].append(agent_name)
        config["phase_completed_agents"] = phase_completed
        self._update_workflow(config=config)

    def _clear_phase_completed(self) -> None:
        """Clear completed agents when advancing phase."""
        config = self.workflow.config or {}
        config["phase_completed_agents"] = {}
        self._update_workflow(config=config)

    def _get_iteration_count(self, loop_name: str) -> int:
        """Get current iteration count for a feedback loop."""
        config = self.workflow.config or {}
        iterations = config.get("loop_iterations", {})
        return iterations.get(loop_name, 0)

    def _increment_iteration(self, loop_name: str) -> int:
        """Increment and return iteration count for a feedback loop."""
        config = self.workflow.config or {}
        iterations = config.get("loop_iterations", {})
        iterations[loop_name] = iterations.get(loop_name, 0) + 1
        config["loop_iterations"] = iterations
        self._update_workflow(config=config)
        return iterations[loop_name]

    def _reset_iteration(self, loop_name: str) -> None:
        """Reset iteration count for a feedback loop."""
        config = self.workflow.config or {}
        iterations = config.get("loop_iterations", {})
        iterations[loop_name] = 0
        config["loop_iterations"] = iterations
        self._update_workflow(config=config)

    def _get_review_result(self) -> dict[str, Any]:
        """Get the latest review result to determine if loop is needed."""
        config = self.workflow.config or {}
        return config.get("last_review_result", {})

    def _set_review_result(self, result: dict[str, Any]) -> None:
        """Store review result for feedback loop decisions."""
        config = self.workflow.config or {}
        config["last_review_result"] = result
        self._update_workflow(config=config)

    def _get_invariant_result(self) -> dict[str, Any]:
        """Get the latest invariant check result."""
        config = self.workflow.config or {}
        return config.get("last_invariant_result", {})

    def _set_invariant_result(self, result: dict[str, Any]) -> None:
        """Store invariant result for feedback loop decisions."""
        config = self.workflow.config or {}
        config["last_invariant_result"] = result
        self._update_workflow(config=config)

    def _get_lint_fail_count(self) -> int:
        """Get the current lint fail count."""
        config = self.workflow.config or {}
        return config.get("lint_fail_count", 0)

    def _set_lint_fail_count(self, count: int) -> None:
        """Store lint fail count for quality-gated loop decisions."""
        config = self.workflow.config or {}
        config["lint_fail_count"] = count
        self._update_workflow(config=config)

    def _get_reviewer_verdicts(self) -> dict[str, str]:
        """Get all reviewer verdicts (PASS/FAIL) from latest review cycle."""
        config = self.workflow.config or {}
        return config.get("reviewer_verdicts", {})

    def _set_reviewer_verdict(self, agent_name: str, verdict: str) -> None:
        """Store a reviewer's verdict (PASS or FAIL)."""
        config = self.workflow.config or {}
        verdicts = config.get("reviewer_verdicts", {})
        verdicts[agent_name] = verdict
        config["reviewer_verdicts"] = verdicts
        self._update_workflow(config=config)

    def _clear_reviewer_verdicts(self) -> None:
        """Clear all reviewer verdicts for a new review cycle."""
        config = self.workflow.config or {}
        config["reviewer_verdicts"] = {}
        self._update_workflow(config=config)

    def _all_reviewers_pass(self) -> bool:
        """Check if all reviewers returned PASS verdict."""
        verdicts = self._get_reviewer_verdicts()
        if not verdicts:
            return False  # No verdicts means we can't confirm pass
        return all(v.upper() == "PASS" for v in verdicts.values())

    def _get_drift_result(self) -> dict[str, Any]:
        """Get the latest drift detection result."""
        config = self.workflow.config or {}
        return config.get("drift_result", {})

    def _set_drift_result(self, result: dict[str, Any]) -> None:
        """Store drift detection result in workflow config."""
        config = self.workflow.config or {}
        config["drift_result"] = result
        self._update_workflow(config=config)

    def _is_drift_detection_enabled(self) -> bool:
        """Check if drift detection is enabled in workflow config."""
        config = self.workflow.config or {}
        # Drift detection is opt-in via config
        return config.get("enable_drift_detection", False)

    def _should_run_drift_detection(self) -> bool:
        """Check if drift detection should run after REVISE phase.

        Drift detection runs after REVISE completes if:
        1. Drift detection is enabled in config
        2. We haven't already run drift detection this iteration
        3. We're transitioning from REVISE to ANALYZE/FINALIZE
        """
        if not self._is_drift_detection_enabled():
            return False

        config = self.workflow.config or {}
        current_iteration = self._get_iteration_count("review")

        # Check if we've already run drift detection for this iteration
        last_drift_iteration = config.get("last_drift_iteration", -1)
        if last_drift_iteration >= current_iteration:
            return False

        return True

    def _mark_drift_detection_run(self) -> None:
        """Mark that drift detection has run for the current iteration."""
        config = self.workflow.config or {}
        config["last_drift_iteration"] = self._get_iteration_count("review")
        self._update_workflow(config=config)

    def _parse_reviewer_verdict(self, content: str) -> str | None:
        """Parse PASS/FAIL verdict from reviewer markdown output.

        Looks for patterns like:
        - "### Verdict" followed by "**PASS**" or "**FAIL**"
        - "**PASS** -" or "**FAIL** -" on its own line

        Returns:
            "PASS", "FAIL", or None if no verdict found
        """
        import re

        # Look for ### Verdict section with PASS/FAIL
        verdict_section = re.search(
            r"###\s*Verdict.*?\*\*(PASS|FAIL)\*\*",
            content,
            re.IGNORECASE | re.DOTALL,
        )
        if verdict_section:
            return verdict_section.group(1).upper()

        # Fallback: look for standalone **PASS** or **FAIL** on a line
        verdict_line = re.search(
            r"^\s*[-*]?\s*\*\*(PASS|FAIL)\*\*",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
        if verdict_line:
            return verdict_line.group(1).upper()

        return None

    def _advance_phase(self) -> None:
        """Advance to the next phase, handling feedback loops."""
        current = self.current_phase

        # Clear phase completion tracking
        self._clear_phase_completed()

        # Determine next phase based on current state and results
        next_phase = self._determine_next_phase(current)

        if next_phase:
            self._update_workflow(phase=next_phase.value)
        else:
            # No next phase - complete
            self._update_workflow(phase=Phase.COMPLETE.value, status=Status.COMPLETED.value)

    def _determine_next_phase(self, current: Phase) -> Phase | None:
        """Determine the next phase, handling feedback loops.

        This implements the review feedback loop:
        1. REVIEW -> REVISE -> ANALYZE -> REVIEW (loop)
        2. After max_loops iterations (from config, default MAX_REVIEW_ITERATIONS), proceed to FINALIZE
        3. INVARIANT_CHECK may loop to CONDENSE for length violations
        4. CONDENSE waits for user input, then APPLY_CUT -> INVARIANT_CHECK
        """
        config = self.workflow.config or {}

        # Handle --no-research: skip RESEARCH phase when configured
        if current == Phase.PLAN and config.get("no_research", False):
            return Phase.DRAFT

        # Handle REVISE -> loop or continue based on quality signals
        if current == Phase.REVISE:
            # Quality-gated early exit: if lint passes AND all reviewers pass, skip to FINALIZE
            lint_fail_count = self._get_lint_fail_count()
            all_pass = self._all_reviewers_pass()

            if lint_fail_count == 0 and all_pass:
                # Quality gate passed - no need for more iterations
                self._reset_iteration("review")
                return Phase.FINALIZE

            # Use max_loops from config, falling back to MAX_REVIEW_ITERATIONS constant
            max_review_iterations = config.get("max_loops", MAX_REVIEW_ITERATIONS)
            review_iter = self._get_iteration_count("review")
            if review_iter >= max_review_iterations:
                # Max iterations reached, proceed to finalize regardless of quality
                self._reset_iteration("review")
                return Phase.FINALIZE
            # Loop back to analyze (which leads to review)
            self._increment_iteration("review")
            return Phase.ANALYZE

        # Handle INVARIANT_CHECK -> CONDENSE for length violations or EXPORT
        if current == Phase.INVARIANT_CHECK:
            inv_result = self._get_invariant_result()
            unfixable = inv_result.get("unfixable_violations", [])

            # Check for length-related violations (require user choice to condense)
            length_violations = [
                v for v in unfixable
                if v.get("invariant", "").lower() in ("max_characters", "max_words", "target_word_count")
                or "length" in v.get("reason", "").lower()
                or "character" in v.get("reason", "").lower()
            ]

            if length_violations:
                inv_iter = self._get_iteration_count("condense")
                if inv_iter < MAX_INVARIANT_ITERATIONS:
                    # Has length violations - go to CONDENSE for user decision
                    self._increment_iteration("condense")
                    # Store violations for condenser
                    config = self.workflow.config or {}
                    config["length_violations"] = length_violations
                    self._update_workflow(config=config)
                    return Phase.CONDENSE

            # Check for other unfixable violations (loop to REVISE)
            other_violations = [v for v in unfixable if v not in length_violations]
            if other_violations:
                inv_iter = self._get_iteration_count("invariant")
                if inv_iter < MAX_INVARIANT_ITERATIONS:
                    self._increment_iteration("invariant")
                    config = self.workflow.config or {}
                    config["invariant_feedback"] = other_violations
                    self._update_workflow(config=config)
                    return Phase.REVISE

            # No unfixable or max iterations, proceed to export
            self._reset_iteration("invariant")
            self._reset_iteration("condense")
            return Phase.EXPORT

        # Handle APPLY_CUT -> back to INVARIANT_CHECK
        if current == Phase.APPLY_CUT:
            return Phase.INVARIANT_CHECK

        # Default transition
        return PHASE_TRANSITIONS.get(current)

    def process_result(
        self,
        result: dict[str, Any],
        context_logger: ContextLogger | None = None,
    ) -> None:
        """Process the result of an action and advance state.

        Args:
            result: Result from agent or tool execution
            context_logger: Optional context logger to log the result
        """
        if context_logger:
            self._context_logger = context_logger

        phase = self.current_phase
        agent = PHASE_AGENTS.get(phase)

        # Log result if we have a logger
        if self._context_logger and "output" in result:
            self._context_logger.log_agent_output(
                result.get("agent", str(agent)),
                result.get("output", ""),
            )

        # Store artifact if result has content
        if "content" in result:
            self._store_artifact(
                artifact_type=result.get("type", phase.value),
                name=result.get("name", f"{phase.value}_output"),
                content=result["content"],
                metadata=result.get("metadata"),
            )

        # Mark agent as completed if this was an agent action
        executed_agent = result.get("agent")
        if executed_agent:
            self._mark_agent_completed(executed_agent)

        # Store invariant results for feedback loop decisions
        if phase == Phase.INVARIANT_CHECK and "invariant_result" in result:
            self._set_invariant_result(result["invariant_result"])

        # Store review results for feedback loop decisions
        if phase == Phase.REVIEW:
            # Accumulate review findings for editor feedback
            config = self.workflow.config or {}
            review_findings = config.get("review_findings", {})
            if executed_agent and "content" in result:
                review_findings[executed_agent] = result["content"]
                # Parse and store reviewer verdict from content
                verdict = self._parse_reviewer_verdict(result["content"])
                if verdict:
                    self._set_reviewer_verdict(executed_agent, verdict)
            config["review_findings"] = review_findings
            self._update_workflow(config=config)

        # Store lint fail count from ANALYZE phase for quality-gated loop
        if phase == Phase.ANALYZE and "lint" in result:
            lint_data = result["lint"]
            if isinstance(lint_data, dict):
                findings = lint_data.get("findings", [])
                fail_count = sum(1 for f in findings if f.get("severity") == "fail")
                self._set_lint_fail_count(fail_count)
            # Clear reviewer verdicts at start of new review cycle
            self._clear_reviewer_verdicts()

        # Store drift detection results and log warnings
        if "drift_result" in result:
            drift_result = result["drift_result"]
            self._set_drift_result(drift_result)
            self._mark_drift_detection_run()

            # Log warning if significant drift detected
            drift_level = drift_result.get("drift_level", "none")
            if drift_level == "significant":
                recommendation = drift_result.get("recommendation", "review")
                reason = drift_result.get("recommendation_reason", "")
                import logging
                logging.warning(
                    f"DRIFT DETECTED: Significant drift from original plan. "
                    f"Recommendation: {recommendation}. {reason}"
                )

        # Check if phase has multiple agents - use internal tracking
        all_agents = result.get("inputs", {}).get("all_agents")
        if all_agents:
            completed = self._get_completed_agents()
            remaining = [a for a in all_agents if a not in completed]
            if remaining:
                # More agents to run - don't advance yet
                return

        all_tools = result.get("inputs", {}).get("all_tools")
        if all_tools:
            completed = result.get("completed_tools", [])
            remaining = [t for t in all_tools if t not in completed]
            if remaining:
                # More tools to run - don't advance yet
                return

        # Advance to next phase
        self._advance_phase()

    def _store_artifact(
        self,
        artifact_type: str,
        name: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Store an artifact in the database."""
        with self.db.session() as session:
            active_session = self.session_manager.get_active_session(self.workflow_id)
            artifact = Artifact(
                workflow_id=self.workflow_id,
                session_id=active_session.id if active_session else None,
                artifact_type=artifact_type,
                name=name,
                content=content,
                artifact_metadata=metadata,
            )
            session.add(artifact)
            session.flush()
            session.expunge(artifact)
            return artifact

    def pause(self, reason: str | None = None) -> None:
        """Pause the workflow with context summarization.

        Args:
            reason: Optional reason for pausing
        """
        active_session = self.session_manager.get_active_session(self.workflow_id)

        if active_session and self._context_logger:
            # Summarize and save context
            self.session_manager.pause_session(
                active_session.id,
                self._context_logger,
                self.current_phase.value,
            )

        # Update workflow status
        config = self.workflow.config or {}
        if reason:
            config["pause_reason"] = reason
        self._update_workflow(status=Status.PAUSED.value, config=config)

    def resume(self) -> str:
        """Resume from paused state.

        Returns:
            Resume context to inject into next agent prompt
        """
        if self.current_status != Status.PAUSED:
            return ""

        # Get resume context from latest session
        active_session = self.session_manager.get_active_session(self.workflow_id)
        resume_context = ""

        if active_session:
            _, resume_context = self.session_manager.resume_session(active_session.id)

        # Update status
        self._update_workflow(status=Status.RUNNING.value)

        return resume_context

    def request_input(
        self,
        prompt: str,
        request_type: str = "input",
        options: list[str] | None = None,
    ) -> str:
        """Create an input request and pause workflow.

        Args:
            prompt: Question/prompt for the user
            request_type: Type of input (e.g., "approval", "clarification")
            options: Optional list of choices

        Returns:
            Request ID
        """
        with self.db.session() as session:
            active_session = self.session_manager.get_active_session(self.workflow_id)
            request = InputRequest(
                workflow_id=self.workflow_id,
                session_id=active_session.id if active_session else None,
                request_type=request_type,
                prompt=prompt,
                options=options,
            )
            session.add(request)
            session.flush()
            request_id = request.id
            session.expunge(request)

        self._update_workflow(status=Status.WAITING_INPUT.value)
        return request_id

    def provide_input(self, request_id: str, response: str) -> None:
        """Provide response to an input request.

        Args:
            request_id: ID of the input request
            response: User's response
        """
        with self.db.session() as session:
            request = (
                session.query(InputRequest).filter(InputRequest.id == request_id).first()
            )
            if request:
                request.response = response
                request.responded_at = datetime.now(timezone.utc)

        # Continue workflow
        self._update_workflow(status=Status.RUNNING.value)

    def set_error(self, error: str) -> None:
        """Set workflow to error state.

        Args:
            error: Error message
        """
        config = self.workflow.config or {}
        config["error"] = error
        self._update_workflow(status=Status.ERROR.value, config=config)

    def get_artifacts(self, artifact_type: str | None = None) -> list[Artifact]:
        """Get artifacts for this workflow.

        Args:
            artifact_type: Optional filter by type

        Returns:
            List of Artifact objects
        """
        with self.db.session() as session:
            query = session.query(Artifact).filter(Artifact.workflow_id == self.workflow_id)
            if artifact_type:
                query = query.filter(Artifact.artifact_type == artifact_type)
            artifacts = query.order_by(Artifact.created_at).all()
            for a in artifacts:
                session.expunge(a)
            return artifacts

    def get_artifact_content(self, name: str) -> str | None:
        """Get artifact content by name.

        Args:
            name: Artifact name

        Returns:
            Content string or None if not found
        """
        with self.db.session() as session:
            artifact = (
                session.query(Artifact)
                .filter(Artifact.workflow_id == self.workflow_id, Artifact.name == name)
                .order_by(Artifact.created_at.desc())
                .first()
            )
            return artifact.content if artifact else None


def create_workflow(
    db: Database,
    workflow_type: str = "article-writer",
    config: dict[str, Any] | None = None,
) -> StateMachine:
    """Create a new workflow and return its state machine.

    Args:
        db: Database instance
        workflow_type: Type of workflow
        config: Initial configuration

    Returns:
        StateMachine for the new workflow
    """
    with db.session() as session:
        workflow = Workflow(
            type=workflow_type,
            phase=Phase.INIT.value,
            status=Status.RUNNING.value,
            config=config,
        )
        session.add(workflow)
        session.flush()
        workflow_id = workflow.id
        session.expunge(workflow)

    return StateMachine(db, workflow_id)


def load_workflow(db: Database, workflow_id: str) -> StateMachine:
    """Load an existing workflow's state machine.

    Args:
        db: Database instance
        workflow_id: Workflow ID

    Returns:
        StateMachine for the workflow

    Raises:
        ValueError: If workflow not found
    """
    return StateMachine(db, workflow_id)
