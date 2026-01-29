"""Context logger for capturing agent activity.

Captures everything an agent does by parsing subprocess stdout:
- Model's internal reasoning (content between tool calls)
- Tool calls with full parameters
- Tool results
- Final outputs
- Errors

This data is used by ContextSummarizer to create resume context.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from .database import Database
from .models import ContextLog


class ContextLogger:
    """Logs agent activity to the database for context capture.

    Usage:
        logger = ContextLogger(db, session_id="abc123")

        # Log raw agent output (will be parsed for tool calls, etc.)
        logger.log_agent_output("planner", raw_stdout)

        # Log local tool invocations
        logger.log_tool_invocation("lint", {"draft_path": "..."}, {"findings": [...]})

        # Get formatted summary input
        summary_text = logger.get_summary_input()
    """

    def __init__(self, db: Database, session_id: str) -> None:
        """Initialize context logger.

        Args:
            db: Database instance
            session_id: Session ID to log events for
        """
        self.db = db
        self.session_id = session_id

    def _log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Log a single event to the database."""
        with self.db.session() as session:
            log = ContextLog(
                session_id=self.session_id,
                timestamp=datetime.now(UTC),
                event_type=event_type,
                data=data,
            )
            session.add(log)

    def log_agent_output(self, agent: str, raw_output: str) -> None:
        """Log and parse raw stdout from agent subprocess.

        Parses the output to extract:
        - Reasoning blocks (text between tool calls)
        - Tool calls with parameters
        - Final output

        Args:
            agent: Agent name (e.g., "planner", "writer")
            raw_output: Raw stdout from subprocess
        """
        # Store raw output
        self._log_event(
            "agent_output",
            {
                "agent": agent,
                "raw_output": raw_output,
                "parsed": self._parse_agent_output(raw_output),
            },
        )

    def _parse_agent_output(self, output: str) -> dict[str, Any]:
        """Parse agent output to extract structured information.

        Looks for patterns like:
        - Code blocks (```json, ```markdown)
        - Tool call patterns (if using structured output)
        - Reasoning sections

        Args:
            output: Raw agent output

        Returns:
            Parsed structure with code_blocks, reasoning, etc.
        """
        result: dict[str, Any] = {
            "code_blocks": [],
            "reasoning_blocks": [],
            "tool_calls": [],
        }

        # Extract code blocks
        code_block_pattern = re.compile(r"```(\w+)?\n(.*?)\n```", re.DOTALL)
        for match in code_block_pattern.finditer(output):
            lang = (match.group(1) or "").strip().lower()
            content = match.group(2).strip()
            result["code_blocks"].append({"language": lang, "content": content})

            # Try to parse JSON blocks for tool calls
            if lang == "json":
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and ("tool" in parsed or "function" in parsed):
                        result["tool_calls"].append(parsed)
                except json.JSONDecodeError:
                    pass

        # Extract text outside code blocks as reasoning
        text_without_code = code_block_pattern.sub("", output).strip()
        paragraphs = [p.strip() for p in text_without_code.split("\n\n") if p.strip()]
        result["reasoning_blocks"] = paragraphs

        return result

    def log_tool_invocation(
        self,
        tool: str,
        params: dict[str, Any],
        result: dict[str, Any] | str | list | None,
        error: str | None = None,
    ) -> None:
        """Log local tool invocation (lint, skeleton, etc.).

        Args:
            tool: Tool name (e.g., "lint", "skeleton", "tempo")
            params: Parameters passed to tool
            result: Tool result
            error: Error message if tool failed
        """
        self._log_event(
            "tool_invocation",
            {
                "tool": tool,
                "params": params,
                "result": result,
                "error": error,
            },
        )

    def log_error(self, error: str, context: dict[str, Any] | None = None) -> None:
        """Log an error event.

        Args:
            error: Error message
            context: Additional context about the error
        """
        self._log_event(
            "error",
            {
                "error": error,
                "context": context or {},
            },
        )

    def log_phase_transition(self, from_phase: str, to_phase: str) -> None:
        """Log a phase transition.

        Args:
            from_phase: Previous phase
            to_phase: New phase
        """
        self._log_event(
            "phase_transition",
            {
                "from_phase": from_phase,
                "to_phase": to_phase,
            },
        )

    def get_session_logs(self) -> list[ContextLog]:
        """Get all logs for this session.

        Returns:
            List of ContextLog objects ordered by timestamp
        """
        with self.db.session() as session:
            logs = (
                session.query(ContextLog)
                .filter(ContextLog.session_id == self.session_id)
                .order_by(ContextLog.timestamp)
                .all()
            )
            # Detach from session
            for log in logs:
                session.expunge(log)
            return logs

    def get_summary_input(self) -> str:
        """Format logs for GLM summarization.

        Returns a formatted string suitable for the summarizer prompt.

        Returns:
            Formatted log text
        """
        logs = self.get_session_logs()
        parts: list[str] = []

        for log in logs:
            timestamp = log.timestamp.isoformat() if log.timestamp else "unknown"
            event_type = log.event_type

            if event_type == "agent_output":
                agent = log.data.get("agent", "unknown")
                parsed = log.data.get("parsed", {})
                reasoning = parsed.get("reasoning_blocks", [])
                code_blocks = parsed.get("code_blocks", [])

                parts.append(f"\n### Agent: {agent} ({timestamp})")

                if reasoning:
                    parts.append("\nReasoning:")
                    for block in reasoning[:5]:  # Limit to first 5 blocks
                        parts.append(f"  - {block[:500]}...")  # Truncate long blocks

                if code_blocks:
                    parts.append(f"\nProduced {len(code_blocks)} code block(s):")
                    for block in code_blocks[:3]:  # Limit to first 3
                        lang = block.get("language", "text")
                        content = block.get("content", "")[:300]
                        parts.append(f"  - {lang}: {content}...")

            elif event_type == "tool_invocation":
                tool = log.data.get("tool", "unknown")
                error = log.data.get("error")
                result = log.data.get("result", {})

                if error:
                    parts.append(f"\n### Tool: {tool} - FAILED ({timestamp})")
                    parts.append(f"  Error: {error}")
                else:
                    parts.append(f"\n### Tool: {tool} ({timestamp})")
                    # Summarize result
                    if isinstance(result, dict):
                        keys = list(result.keys())[:5]
                        parts.append(f"  Result keys: {keys}")

            elif event_type == "phase_transition":
                from_phase = log.data.get("from_phase", "?")
                to_phase = log.data.get("to_phase", "?")
                parts.append(f"\n### Phase: {from_phase} -> {to_phase} ({timestamp})")

            elif event_type == "error":
                error = log.data.get("error", "unknown error")
                parts.append(f"\n### ERROR ({timestamp}): {error}")

        return "\n".join(parts)
