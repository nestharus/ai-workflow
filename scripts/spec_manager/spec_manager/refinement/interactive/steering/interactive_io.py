"""Interactive IO for human-in-the-loop disambiguation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse

if TYPE_CHECKING:
    from spec_manager.refinement.interactive.input_signal import InputSignal


class InteractiveIO:
    """Handles interactive disambiguation via stdin/stdout."""

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace

    def ask(self, ambiguity: Ambiguity, question: str) -> SteeringResponse:
        """Present a question to the user and get a response.

        Args:
            ambiguity: The detected ambiguity.
            question: The question to ask.

        Returns:
            SteeringResponse with the user's answer.
        """
        self._write_constraint_request(
            request_id=ambiguity.ambiguity_id,
            question=question,
            options=[],
            evidence_refs=[ambiguity.source_location] if ambiguity.source_location else [],
        )

        print(f"\n--- Ambiguity Detected ({ambiguity.ambiguity_id}) ---")
        print(f"Type: {ambiguity.ambiguity_type}")
        print(f"Location: {ambiguity.source_location}")
        print(f"Text: {ambiguity.source_text[:200]}")
        print(f"\nQuestion: {question}")
        print()

        response_text = self._prompt_response(
            prompt="Your response: ",
            request_id=ambiguity.ambiguity_id,
        )

        return SteeringResponse(
            ambiguity_id=ambiguity.ambiguity_id,
            response_text=response_text,
            source="interactive",
        )

    def ask_signal(self, signal: InputSignal, question: str) -> SteeringResponse:
        """Present a rich signal to the user with full context.

        Args:
            signal: The InputSignal with work context.
            question: The question to ask.

        Returns:
            SteeringResponse with the user's answer and signal traceability.
        """
        ctx = signal.work_context

        self._write_constraint_request(
            request_id=signal.signal_id,
            question=question,
            options=list(signal.options),
            evidence_refs=[signal.encountered_location] if signal.encountered_location else [],
        )

        print(f"\n{'=' * 60}")
        print(f"Signal: {signal.signal_id} ({signal.signal_type})")
        print(f"Severity: {signal.severity}")
        print(f"{'=' * 60}")

        print(f"\nPhase: {ctx.current_phase} (iteration {ctx.iteration})")
        if ctx.current_library:
            print(f"Library: {ctx.current_library}")
        print(f"Task: {ctx.current_task}")
        if ctx.related_libraries:
            print(f"Related: {', '.join(ctx.related_libraries)}")

        print(f"\nGoal: {signal.goal}")
        print(f"Location: {signal.encountered_location}")
        print(f"Text: {signal.encountered_text[:300]}")

        print(f"\nQuestion: {question}")

        if signal.options:
            print("\nSuggested options:")
            for i, opt in enumerate(signal.options, 1):
                print(f"  {i}. {opt}")

        print()
        response_text = self._prompt_response(
            prompt="Your response: ",
            request_id=signal.signal_id,
        )

        return SteeringResponse(
            ambiguity_id=signal.signal_id,
            response_text=response_text,
            source="interactive",
            signal=signal,
        )

    @staticmethod
    def _prompt_response(*, prompt: str, request_id: str) -> str:
        while True:
            response_text = input(prompt).strip()
            if response_text.lower() == "/defer":
                raise RuntimeError(f"Interactive response deferred for {request_id}")
            if response_text:
                return response_text
            print("Response cannot be empty. Enter a concrete answer or '/defer'.")

    def _write_constraint_request(
        self,
        *,
        request_id: str,
        question: str,
        options: list[str],
        evidence_refs: list[str],
    ) -> None:
        if self._workspace is None:
            return

        out_dir = self._workspace / "analysis" / "under_spec" / "interactive"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_id = request_id.replace("/", "_").replace("\\", "_")
        path = out_dir / f"{safe_id}_constraint_request.md"

        lines = [
            f"# Constraint Request: {request_id}",
            "",
            f"Generated: {datetime.now(UTC).isoformat()}",
            "",
            "## Question",
            question,
            "",
        ]
        if options:
            lines.append("## Options")
            lines.extend(f"- {opt}" for opt in options if opt)
            lines.append("")
        if evidence_refs:
            lines.append("## Evidence References")
            lines.extend(f"- {ref}" for ref in evidence_refs if ref)
            lines.append("")

        lines.extend(
            [
                "## Required Decision Format",
                "```yaml",
                "constraints:",
                f"  - constraint_id: {request_id}",
                f"    question: {question}",
                "    answer: <concrete testable answer>",
                "    source: user",
                "```",
            ]
        )

        path.write_text("\n".join(lines), encoding="utf-8")
