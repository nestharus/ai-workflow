"""ImplementationRunner: per-slice adapter over the LLM implementation agent.

Wraps the legacy ``_run_implementation()`` logic from ``pdd_orchestrator``
into a per-slice, per-function runner that produces the full artifact set
expected by the PromotionLoop's EvidenceBundle.

Output artifacts per slice iteration:
- ``patch.diff`` — unified diff of all applied edits
- ``pin_proposals.json`` — LLM-proposed pins
- ``edge_proposals.json`` — LLM-proposed edges
- ``under_spec_events.json`` — ambiguity blockers
- ``tests_added.json`` — test artifacts with diffs
- ``notes.md`` — implementation notes
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.orchestration.coordination.signals import (
    CoordinationSignal,
    SignalNeed,
    SignalProgress,
    SpecRef,
)
from spec_manager.orchestration.implementation.types import (
    EdgeProposal,
    ImplementorOutput,
    PinProposal,
    TestArtifact,
    UnderSpecEvent,
)

logger = logging.getLogger(__name__)


@dataclass
class ImplementationRunResult:
    """Result of running implementation on a slice."""

    patch_path: str = ""
    applied_edits: list[dict[str, Any]] = field(default_factory=list)
    pin_proposals: list[dict[str, Any]] = field(default_factory=list)
    edge_proposals: list[dict[str, Any]] = field(default_factory=list)
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    tests_added: list[str] = field(default_factory=list)
    notes_path: str = ""
    functions_implemented: int = 0
    functions_skipped: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


class ImplementationRunner:
    """Per-slice implementation runner.

    Adapts the legacy ``pdd_orchestrator._run_implementation()`` pattern
    into the per-slice, per-function loop that the PromotionLoop expects.

    The runner:
    1. Analyzes the slice for unresolved functions (gaps).
    2. Groups targets by file.
    3. Calls the ``pdd-function-implementor`` agent per function.
    4. Applies edits (function body or unified diff).
    5. Applies implementor-emitted test artifacts into the slice worktree.
    6. Collects pin/edge proposals, under-spec events, and test artifacts.
    7. Writes all artifacts to the iteration directory.

    Args:
        workspace_root: Repository root.
        run_id: Current run identifier.
    """

    def __init__(
        self,
        workspace_root: Path,
        run_id: str = "",
    ) -> None:
        self._workspace = workspace_root
        self._run_id = run_id

    def run_for_slice(
        self,
        *,
        slice_root: Path,
        iteration_dir: Path,
        plan_intentions: list[dict[str, Any]],
        gap_report: list[dict[str, Any]],
        constraints_paths: list[Path] | None = None,
        max_functions: int = 50,
    ) -> ImplementationRunResult:
        """Run implementation on a slice.

        Args:
            slice_root: Root of the slice worktree.
            iteration_dir: Directory to write output artifacts.
            plan_intentions: Plan intentions from PlanStep.
            gap_report: Open gaps from GapExplorationStep.
            constraints_paths: Paths to constraint files.
            max_functions: Maximum functions to implement per call.

        Returns:
            ImplementationRunResult with all artifacts.
        """
        from spec_manager.core.edit_in_place import (
            TranslationState,
            analyze_project,
        )

        result = ImplementationRunResult()
        iteration_dir.mkdir(parents=True, exist_ok=True)

        # Analyze the slice for unresolved functions
        project_state = analyze_project(str(slice_root))

        # Collect all unresolved functions across files
        all_pin_proposals: list[PinProposal] = []
        all_edge_proposals: list[EdgeProposal] = []
        all_under_spec: list[UnderSpecEvent] = []
        all_tests: list[TestArtifact] = []
        all_edits: list[dict[str, Any]] = []
        all_notes: list[str] = []
        count = 0

        for file_path, file_state in sorted(project_state.files.items()):
            unresolved = [
                f
                for f in file_state.functions
                if f.translation_state in (TranslationState.UNRESOLVED, TranslationState.STUB)
            ]
            if not unresolved:
                continue

            source_path = Path(file_path)
            try:
                file_content = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                result.errors.append({"file": file_path, "error": str(exc)})
                continue

            # Process bottom-up to preserve line numbers
            for func in sorted(unresolved, key=lambda f: f.line_start, reverse=True):
                if count >= max_functions:
                    result.functions_skipped += 1
                    continue

                spec_texts = [c.text for c in func.spec_comments]
                if not spec_texts and func.translation_state == TranslationState.STUB:
                    result.functions_skipped += 1
                    continue

                # Check for blocking under-spec events
                if all_under_spec:
                    # Stop scheduling if we already have blockers
                    result.functions_skipped += 1
                    continue

                output = self._call_implementor(func, file_content, file_state, slice_root)

                if output is None:
                    result.errors.append(
                        {
                            "function": func.qualified_name,
                            "error": "Agent returned no output",
                        }
                    )
                    continue

                # Collect under-spec events (blockers)
                if output.under_spec_events:
                    all_under_spec.extend(output.under_spec_events)
                    # Don't apply edits for functions with under-spec
                    continue

                # Apply edits (unified diffs only)
                for edit in output.edits:
                    all_edits.append(
                        {
                            "function": func.qualified_name,
                            "file": edit.path,
                            "method": "unified_diff",
                            "diff": edit.unified_diff,
                        }
                    )
                count += 1
                result.functions_implemented += 1

                # Collect proposals and tests
                all_pin_proposals.extend(output.pin_proposals)
                all_edge_proposals.extend(output.edge_proposals)
                all_tests.extend(output.tests)
                if output.notes_md:
                    all_notes.append(output.notes_md)

        # Convert under-spec events to coordination signals
        all_signals: list[CoordinationSignal] = []
        for event in all_under_spec:
            classification = _classify_under_spec(event)
            signal = CoordinationSignal(
                run_id=self._run_id,
                layer="l1",
                slice_id="",  # filled by caller
                iteration=0,  # filled by caller
                classification=classification,
                need=SignalNeed(
                    summary=event.question,
                    artifact_key=event.needed_for or "",
                ),
                spec_refs=[SpecRef(spec_text=event.question)],
                progress=SignalProgress(
                    functions_implemented=count,
                    functions_skipped=result.functions_skipped,
                ),
                # C01: Preserve provenance — carry original event for traceability
                payload={
                    "origin_event_kind": event.kind,
                    "origin_options": event.options,
                    "origin_needed_for": event.needed_for or "",
                    "origin_evidence_paths": event.evidence_paths,
                },
            )
            all_signals.append(signal)

        # Write artifacts to iteration directory
        result.applied_edits = all_edits
        result.pin_proposals = [p.to_dict() for p in all_pin_proposals]
        result.edge_proposals = [e.to_dict() for e in all_edge_proposals]
        result.under_spec_events = [e.to_dict() for e in all_under_spec]
        result.tests_added = self._materialize_test_artifacts(
            slice_root=slice_root,
            tests=all_tests,
            errors=result.errors,
        )

        if all_signals:
            result.signals = [s.to_dict() for s in all_signals]

        # Persist artifacts as files
        self._write_artifacts(
            iteration_dir,
            result,
            all_pin_proposals,
            all_edge_proposals,
            all_under_spec,
            all_tests,
            all_notes,
            all_signals,
        )

        return result

    def _call_implementor(
        self,
        func: Any,
        file_content: str,
        file_state: Any,
        slice_root: Path,
    ) -> ImplementorOutput | None:
        """Call the pdd-function-implementor agent for one function."""
        from spec_manager.refinement.formats import (
            _extract_json_payload,
            _strip_code_fences,
        )

        prompt = self._build_prompt(func, file_content, file_state)

        try:
            from spec_manager.core.agent_utils import run_agent

            output = run_agent(
                agent_name="pdd-function-implementor",
                prompt=prompt,
                workspace=self._workspace,
            )
            cleaned = _strip_code_fences(output)
            payload = _extract_json_payload(cleaned)
            data = json.loads(payload)
            return ImplementorOutput.from_dict(data)
        except json.JSONDecodeError:
            # C03: Surface errors — record malformed output for diagnosis
            logger.exception(
                "Implementor returned unparseable JSON for %s (raw: %.200s)",
                func.qualified_name,
                cleaned if "cleaned" in dir() else "<unavailable>",
            )
            return None
        except Exception as exc:
            logger.error(
                "Implementor failed for %s: %s",
                func.qualified_name,
                exc,
                exc_info=True,
            )
            return None

    def _build_prompt(
        self,
        func: Any,
        file_content: str,
        file_state: Any,
    ) -> str:
        """Build the prompt for the pdd-function-implementor agent."""
        lines = file_content.splitlines()
        func_text = "\n".join(lines[func.line_start - 1 : func.line_end])
        spec_requirements = [c.text for c in func.spec_comments]

        first_func_line = min((f.line_start for f in file_state.functions), default=len(lines))
        file_header = "\n".join(lines[: first_func_line - 1])

        class_methods: list[str] = []
        for other_func in file_state.functions:
            if other_func.qualified_name != func.qualified_name:
                sig_line = lines[other_func.line_start - 1].rstrip()
                class_methods.append(sig_line)

        parts = [
            "## FILE CONTEXT\n",
            f"```\n{file_header}\n```\n",
        ]

        if class_methods:
            parts.append("## OTHER METHODS IN CLASS\n")
            parts.append("```\n")
            for m in class_methods:
                parts.append(f"{m}\n")
            parts.append("```\n")

        parts.append("## FUNCTION TO IMPLEMENT\n")
        parts.append(f"```\n{func_text}\n```\n")

        parts.append("## REQUIREMENTS (from spec comments)\n")
        for i, req in enumerate(spec_requirements, 1):
            parts.append(f"{i}. {req}\n")

        parts.append(
            "\n## TASK\n"
            "Implement the function body that fulfills ALL requirements above.\n"
            "Return JSON with: edits, pin_proposals, edge_proposals, tests, "
            "under_spec_events, notes_md.\n"
            "If you encounter ambiguity, emit an under_spec_event instead of guessing.\n"
        )

        return "\n".join(parts)

    @staticmethod
    def _write_artifacts(
        iteration_dir: Path,
        result: ImplementationRunResult,
        pin_proposals: list[PinProposal],
        edge_proposals: list[EdgeProposal],
        under_spec_events: list[UnderSpecEvent],
        tests: list[TestArtifact],
        notes: list[str],
        signals: list[CoordinationSignal] | None = None,
    ) -> None:
        """Write all implementation artifacts to the iteration directory."""
        if pin_proposals:
            path = iteration_dir / "pin_proposals.json"
            path.write_text(
                json.dumps([p.to_dict() for p in pin_proposals], indent=2),
                encoding="utf-8",
            )
            result.patch_path = str(iteration_dir / "patch.diff")

        if edge_proposals:
            path = iteration_dir / "edge_proposals.json"
            path.write_text(
                json.dumps([e.to_dict() for e in edge_proposals], indent=2),
                encoding="utf-8",
            )

        if under_spec_events:
            path = iteration_dir / "under_spec_events.json"
            path.write_text(
                json.dumps([e.to_dict() for e in under_spec_events], indent=2),
                encoding="utf-8",
            )

        if signals:
            path = iteration_dir / "signals.json"
            path.write_text(
                json.dumps([s.to_dict() for s in signals], indent=2),
                encoding="utf-8",
            )

        if tests:
            path = iteration_dir / "tests_added.json"
            path.write_text(
                json.dumps([t.to_dict() for t in tests], indent=2),
                encoding="utf-8",
            )

        if notes:
            path = iteration_dir / "notes.md"
            path.write_text("\n\n---\n\n".join(notes), encoding="utf-8")
            result.notes_path = str(path)

    def _materialize_test_artifacts(
        self,
        *,
        slice_root: Path,
        tests: list[TestArtifact],
        errors: list[dict[str, str]],
    ) -> list[str]:
        """Apply implementor-emitted test artifacts to the slice worktree."""
        materialized: list[str] = []
        seen: set[str] = set()
        slice_root_resolved = slice_root.resolve()

        for test in tests:
            raw_path = str(test.path).strip().replace("\\", "/").lstrip("./")
            if not raw_path:
                errors.append({"file": "", "error": "Test artifact missing path"})
                continue

            target = (slice_root / raw_path).resolve()
            try:
                target.relative_to(slice_root_resolved)
            except ValueError:
                errors.append(
                    {
                        "file": raw_path,
                        "error": "Test artifact path escapes slice worktree",
                    }
                )
                continue

            if str(test.unified_diff or "").strip():
                applied, apply_error = self._apply_unified_diff(
                    slice_root=slice_root,
                    unified_diff=test.unified_diff,
                )
                if not applied:
                    errors.append(
                        {
                            "file": raw_path,
                            "error": f"Failed to apply test artifact diff: {apply_error}",
                        }
                    )
                    continue

            if not target.exists():
                errors.append(
                    {
                        "file": raw_path,
                        "error": "Test artifact was not materialized in the worktree",
                    }
                )
                continue

            if raw_path not in seen:
                seen.add(raw_path)
                materialized.append(raw_path)

        return materialized

    @staticmethod
    def _apply_unified_diff(
        *,
        slice_root: Path,
        unified_diff: str,
    ) -> tuple[bool, str]:
        """Apply a unified diff in the slice worktree using ``git apply``."""
        if not unified_diff.strip():
            return False, "empty unified diff"

        patch_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=slice_root,
                prefix="impl_test_",
                suffix=".diff",
            ) as handle:
                handle.write(unified_diff)
                patch_path = Path(handle.name)

            check = subprocess.run(
                ["git", "apply", "--check", str(patch_path)],
                cwd=slice_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if check.returncode != 0:
                return False, check.stderr.strip() or "git apply --check failed"

            apply = subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=slice_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if apply.returncode != 0:
                return False, apply.stderr.strip() or "git apply failed"

            return True, ""
        except OSError as exc:
            return False, str(exc)
        finally:
            if patch_path is not None:
                with contextlib.suppress(OSError):
                    patch_path.unlink()


def _classify_under_spec(event: UnderSpecEvent) -> str:
    """Map UnderSpecEvent.kind to CoordinationSignal.classification."""
    mapping = {
        "MISSING_CONSTRAINT": "AMBIGUOUS_SPEC",
        "CONFLICTING_CONSTRAINTS": "CONFLICTING_REQUIREMENTS",
        "EXTERNAL_DEP_UNKNOWN": "MISSING_INTERFACE",
        "NEEDS_PRODUCT_DECISION": "AMBIGUOUS_SPEC",
        "NEEDS_API_DECISION": "MISSING_INTERFACE",
    }
    classification = mapping.get(event.kind)
    if classification is None:
        # C00: Surface ambiguity — don't silently map unknown kinds
        logger.warning(
            "Unknown under-spec event kind %r — defaulting to AMBIGUOUS_SPEC. "
            "Consider adding it to the classification mapping.",
            event.kind,
        )
        return "AMBIGUOUS_SPEC"
    return classification
