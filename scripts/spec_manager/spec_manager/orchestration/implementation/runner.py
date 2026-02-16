"""ImplementationRunner: per-slice IMPLEMENT execution for PromotionLoop.

Runs function-by-function implementation with file-based artifact IO and strict
implementor schema parsing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from difflib import unified_diff
from pathlib import Path
from typing import Any

from spec_manager.orchestration.coordination.signals import (
    CoordinationSignal,
    FunctionRef,
    LocalContext,
    SearchHints,
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
    pin_proposals_path: str = ""
    edge_proposals_path: str = ""
    under_spec_events_path: str = ""
    tests_added_path: str = ""
    notes_path: str = ""
    pin_proposals: list[dict[str, Any]] = field(default_factory=list)
    edge_proposals: list[dict[str, Any]] = field(default_factory=list)
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    tests_added: list[str] = field(default_factory=list)
    functions_implemented: int = 0
    functions_skipped: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


class ImplementationRunner:
    """Per-slice implementation runner."""

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
        slice_id: str,
        iteration: int,
        iteration_dir: Path,
        plan_path: Path | None,
        gaps_path: Path | None,
        constraints_paths: list[Path] | None = None,
        max_functions: int = 50,
    ) -> ImplementationRunResult:
        """Run implementation on one slice and materialize all artifacts."""
        from spec_manager.core.edit_in_place import TranslationState, analyze_project

        result = ImplementationRunResult()
        iteration_dir.mkdir(parents=True, exist_ok=True)
        worktree_branch, latest_commit = self._resolve_git_context(slice_root)
        patch_path_hint = (iteration_dir / "patch.diff").as_posix()
        notes_path_hint = (iteration_dir / "notes.md").as_posix()

        before_snapshot = self._snapshot_text_files(slice_root)
        plan_intentions = self._load_plan_intentions(plan_path)
        gap_report = self._load_gap_report(gaps_path)
        constraints_context = self._load_constraints_context(constraints_paths or [])

        project_state = analyze_project(str(slice_root))
        candidates = self._collect_unresolved_candidates(
            project_state=project_state,
            slice_root=slice_root,
            unresolved_states={TranslationState.UNRESOLVED, TranslationState.STUB},
        )
        prioritized = self._prioritize_candidates(
            candidates=candidates,
            plan_intentions=plan_intentions,
            gap_report=gap_report,
        )

        all_pin_proposals: list[PinProposal] = []
        all_edge_proposals: list[EdgeProposal] = []
        all_under_spec: list[UnderSpecEvent] = []
        all_tests: list[TestArtifact] = []
        all_edits: list[dict[str, Any]] = []
        all_notes: list[str] = []
        all_signals: list[CoordinationSignal] = []

        for idx, candidate in enumerate(prioritized):
            if result.functions_implemented >= max_functions:
                result.functions_skipped += len(prioritized) - idx
                break

            refreshed_state = analyze_project(str(slice_root))
            live_file_state, live_func = self._lookup_live_function(
                project_state=refreshed_state,
                file_key=candidate["file_key"],
                qualified_name=candidate["qualified_name"],
                unresolved_states={TranslationState.UNRESOLVED, TranslationState.STUB},
            )
            if live_file_state is None or live_func is None:
                result.functions_skipped += 1
                continue

            try:
                file_content = candidate["file_path"].read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                result.errors.append(
                    {
                        "file": candidate["file_rel"],
                        "error": f"Failed to read file for implementation: {exc}",
                    }
                )
                continue

            output = self._call_implementor(
                func=live_func,
                file_content=file_content,
                file_state=live_file_state,
                constraints_context=constraints_context,
                file_rel=candidate["file_rel"],
            )
            if output is None:
                result.errors.append(
                    {
                        "function": candidate["qualified_name"],
                        "error": "Agent returned invalid or unparseable output",
                    }
                )
                continue

            if output.under_spec_events:
                all_under_spec.extend(output.under_spec_events)
                remaining_candidates = len(prioritized) - idx
                result.functions_skipped += remaining_candidates

                function_ref = FunctionRef(
                    file=candidate["file_rel"],
                    symbol=candidate["qualified_name"],
                    signature_line=self._signature_line_text(
                        file_content=file_content,
                        line_number=int(getattr(live_func, "line_start", 0) or 0),
                    ),
                )
                base_spec_refs = self._build_spec_refs(
                    func=live_func,
                    file_rel=candidate["file_rel"],
                    symbol=candidate["qualified_name"],
                    fallback_text=(
                        output.under_spec_events[0].question if output.under_spec_events else ""
                    ),
                )

                for event in output.under_spec_events:
                    classification = _classify_under_spec(event)
                    need_summary = str(event.question).strip()
                    if not need_summary:
                        need_summary = (
                            f"Need clarification to continue implementing "
                            f"{candidate['qualified_name']}"
                        )
                    signal = CoordinationSignal(
                        run_id=self._run_id,
                        layer="l1",
                        slice_id=slice_id,
                        iteration=iteration,
                        classification=classification,
                        need=SignalNeed(
                            summary=need_summary,
                            artifact_type=_need_artifact_type(event),
                            artifact_key=str(
                                event.needed_for or candidate["qualified_name"]
                            ).strip(),
                            expected_shape=_need_expected_shape(event),
                            confidence=_need_confidence(event),
                        ),
                        spec_refs=list(base_spec_refs),
                        local_context=LocalContext(
                            blocked_function=function_ref,
                            attempted_approach=(
                                f"Blocked while implementing {candidate['qualified_name']}: "
                                f"{need_summary}"
                            ),
                        ),
                        progress=SignalProgress(
                            functions_implemented=result.functions_implemented,
                            functions_skipped=result.functions_skipped,
                            worktree_branch=worktree_branch,
                            latest_commit=latest_commit,
                            artifacts={
                                "patch_path": patch_path_hint,
                                "notes_path": notes_path_hint,
                            },
                        ),
                        search_hints=SearchHints(
                            keywords=_signal_keywords(event),
                            possible_owner_slices=[],
                        ),
                        payload={
                            "origin_event_kind": event.kind,
                            "origin_options": event.options,
                            "origin_needed_for": event.needed_for or "",
                            "origin_evidence_paths": event.evidence_paths,
                        },
                    )
                    all_signals.append(signal)
                break

            applied_for_function: list[dict[str, Any]] = []
            apply_failed = False
            for edit in output.edits:
                applied, apply_error = self._apply_unified_diff(
                    slice_root=slice_root,
                    unified_diff=edit.unified_diff,
                )
                if not applied:
                    result.errors.append(
                        {
                            "file": edit.path,
                            "error": f"Failed to apply implementation diff: {apply_error}",
                        }
                    )
                    apply_failed = True
                    break
                applied_for_function.append(
                    {
                        "function": candidate["qualified_name"],
                        "file": edit.path,
                        "method": "unified_diff",
                        "diff": edit.unified_diff,
                    }
                )

            if apply_failed:
                result.functions_skipped += 1
                continue

            post_state = analyze_project(str(slice_root))
            if self._is_function_still_unresolved(
                project_state=post_state,
                file_key=candidate["file_key"],
                qualified_name=candidate["qualified_name"],
                unresolved_states={TranslationState.UNRESOLVED, TranslationState.STUB},
            ):
                result.errors.append(
                    {
                        "function": candidate["qualified_name"],
                        "error": "Function remains unresolved after edit application",
                    }
                )

            all_edits.extend(applied_for_function)
            all_pin_proposals.extend(output.pin_proposals)
            all_edge_proposals.extend(output.edge_proposals)
            all_tests.extend(output.tests)
            if output.notes_md:
                all_notes.append(output.notes_md)
            result.functions_implemented += 1

        result.applied_edits = all_edits
        result.pin_proposals = [p.to_dict() for p in all_pin_proposals]
        result.edge_proposals = [e.to_dict() for e in all_edge_proposals]
        result.under_spec_events = [e.to_dict() for e in all_under_spec]
        result.tests_added = self._materialize_test_artifacts(
            slice_root=slice_root,
            tests=all_tests,
            errors=result.errors,
        )
        result.signals = [s.to_dict() for s in all_signals]

        after_snapshot = self._snapshot_text_files(slice_root)
        patch_text = self._build_patch(
            before_snapshot=before_snapshot, after_snapshot=after_snapshot
        )

        self._write_artifacts(
            iteration_dir,
            result,
            all_pin_proposals,
            all_edge_proposals,
            all_under_spec,
            all_tests,
            all_notes,
            signals=all_signals,
            patch_text=patch_text,
        )
        return result

    def _call_implementor(
        self,
        *,
        func: Any,
        file_content: str,
        file_state: Any,
        constraints_context: str,
        file_rel: str,
    ) -> ImplementorOutput | None:
        """Call the pdd-function-implementor agent for one function."""
        from spec_manager.refinement.formats import (
            _extract_json_payload,
            _strip_code_fences,
        )

        prompt = self._build_prompt(
            func=func,
            file_content=file_content,
            file_state=file_state,
            constraints_context=constraints_context,
            file_rel=file_rel,
        )

        cleaned = ""
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
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning(
                "Implementor returned invalid schema for %s: %s (raw: %.200s)",
                getattr(func, "qualified_name", "<unknown>"),
                exc,
                cleaned,
            )
            return None
        except Exception as exc:
            logger.error(
                "Implementor failed for %s: %s",
                getattr(func, "qualified_name", "<unknown>"),
                exc,
                exc_info=True,
            )
            return None

    def _build_prompt(
        self,
        *,
        func: Any,
        file_content: str,
        file_state: Any,
        constraints_context: str,
        file_rel: str,
    ) -> str:
        """Build strict-schema prompt for the implementation agent."""
        lines = file_content.splitlines()
        func_text = "\n".join(lines[func.line_start - 1 : func.line_end])
        spec_requirements = [c.text for c in getattr(func, "spec_comments", [])]

        first_func_line = min((f.line_start for f in file_state.functions), default=len(lines))
        file_header = "\n".join(lines[: first_func_line - 1])

        class_methods: list[str] = []
        for other_func in file_state.functions:
            if other_func.qualified_name != func.qualified_name:
                sig_line = lines[other_func.line_start - 1].rstrip()
                class_methods.append(sig_line)

        signature = lines[func.line_start - 1].strip() if func.line_start - 1 < len(lines) else ""
        schema = (
            "{\n"
            '  "function_target": {"file": "path/relative/to/slice_root.ext", '
            '"fqn": "package.module:SymbolName", "signature": "string", '
            '"span_hint": {"start_line": 1, "end_line": 2}},\n'
            '  "edits": [{"path": "path/relative/to/slice_root.ext", '
            '"unified_diff": "diff --git ..."}],\n'
            '  "pin_proposals": [{"pin_id": "PIN-...", "role": "ATOM", '
            '"fqn": "package.module:SymbolName", "file": "path/relative/to/slice_root.ext"'
            ", "
            '"span": {"start_line": 1, "end_line": 2, "anchor_before": "...", '
            '"anchor_after": "..."}, "atom_id_hint": "ATOM-...", "evidence_paths": []}],\n'
            '  "edge_proposals": [{"src": "PIN-... or fqn", "dst": "PIN-... or store/event id", '
            '"signal_type": "CALL", "weight": 0.7, "evidence_paths": []}],\n'
            '  "tests": [{"path": "tests/test_symbol.ext", "purpose": "...", "scope": "UNIT", "'
            'runner_hint": null, "unified_diff": "diff --git ..."}],\n'
            '  "under_spec_events": [{"kind": "MISSING_CONSTRAINT", "question": "...", '
            '"options": ["..."], "needed_for": "package.module:SymbolName", '
            '"evidence_paths": []}],\n'
            '  "notes_md": "short markdown notes"\n'
            "}"
        )

        parts = [
            "## FILE CONTEXT\n",
            f"```\n{file_header}\n```\n",
        ]

        if class_methods:
            parts.append("## OTHER METHODS IN CLASS\n")
            parts.append("```\n")
            for method_line in class_methods:
                parts.append(f"{method_line}\n")
            parts.append("```\n")

        parts.append("## FUNCTION TO IMPLEMENT\n")
        parts.append(f"```\n{func_text}\n```\n")

        parts.append("## FUNCTION TARGET\n")
        parts.append(
            json.dumps(
                {
                    "file": file_rel,
                    "fqn": getattr(func, "qualified_name", ""),
                    "signature": signature,
                    "span_hint": {
                        "start_line": getattr(func, "line_start", 0),
                        "end_line": getattr(func, "line_end", 0),
                    },
                },
                indent=2,
            )
            + "\n"
        )

        parts.append("## REQUIREMENTS (from spec comments)\n")
        if spec_requirements:
            for i, req in enumerate(spec_requirements, 1):
                parts.append(f"{i}. {req}\n")
        else:
            parts.append("1. Preserve current behavior and remove unresolved/stub state.\n")

        parts.append("## CONSTRAINTS\n")
        if constraints_context:
            parts.append(constraints_context)
            parts.append("\n")
        else:
            parts.append("(none provided)\n")

        parts.append(
            "\n## TASK\n"
            "Implement only this function target.\n"
            "If ambiguity blocks implementation, emit under_spec_events "
            "and avoid the ambiguous edit.\n"
            "Return ONLY valid JSON matching this exact schema and include all top-level keys, "
            "using empty arrays when there are no entries.\n\n"
            "## REQUIRED OUTPUT SCHEMA\n"
        )
        parts.append(schema)
        parts.append("\n")
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
        *,
        signals: list[CoordinationSignal] | None = None,
        patch_text: str = "",
    ) -> None:
        """Write implementation artifacts and set result path refs."""
        patch_path = iteration_dir / "patch.diff"
        patch_path.write_text(patch_text, encoding="utf-8")
        result.patch_path = patch_path.name

        pins_path = iteration_dir / "pin_proposals.json"
        pins_path.write_text(
            json.dumps([p.to_dict() for p in pin_proposals], indent=2),
            encoding="utf-8",
        )
        result.pin_proposals_path = pins_path.name

        edges_path = iteration_dir / "edge_proposals.json"
        edges_path.write_text(
            json.dumps([e.to_dict() for e in edge_proposals], indent=2),
            encoding="utf-8",
        )
        result.edge_proposals_path = edges_path.name

        under_spec_path = iteration_dir / "under_spec_events.json"
        under_spec_path.write_text(
            json.dumps([e.to_dict() for e in under_spec_events], indent=2),
            encoding="utf-8",
        )
        result.under_spec_events_path = under_spec_path.name

        tests_path = iteration_dir / "tests_added.json"
        tests_path.write_text(
            json.dumps([t.to_dict() for t in tests], indent=2),
            encoding="utf-8",
        )
        result.tests_added_path = tests_path.name

        if signals:
            signals_path = iteration_dir / "signals.json"
            signals_path.write_text(
                json.dumps([s.to_dict() for s in signals], indent=2),
                encoding="utf-8",
            )

        notes_path = iteration_dir / "notes.md"
        notes_path.write_text("\n\n---\n\n".join(notes), encoding="utf-8")
        result.notes_path = notes_path.name

    @staticmethod
    def _snapshot_text_files(slice_root: Path) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for file_path in sorted(slice_root.rglob("*")):
            if not file_path.is_file():
                continue
            if any(part.startswith(".") for part in file_path.parts):
                continue
            rel = file_path.relative_to(slice_root).as_posix()
            try:
                snapshot[rel] = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        return snapshot

    @staticmethod
    def _signature_line_text(*, file_content: str, line_number: int) -> str:
        lines = file_content.splitlines()
        if line_number <= 0 or line_number > len(lines):
            return ""
        return lines[line_number - 1].strip()

    @staticmethod
    def _build_spec_refs(
        *,
        func: Any,
        file_rel: str,
        symbol: str,
        fallback_text: str,
    ) -> list[SpecRef]:
        refs: list[SpecRef] = []
        for comment in getattr(func, "spec_comments", []):
            spec_text = str(getattr(comment, "text", "")).strip()
            if not spec_text:
                continue
            raw_line = getattr(comment, "line", 0)
            try:
                source_line_hint = int(raw_line or 0)
            except (TypeError, ValueError):
                source_line_hint = 0
            refs.append(
                SpecRef(
                    spec_text=spec_text,
                    source_file=file_rel,
                    source_symbol=symbol,
                    source_line_hint=source_line_hint,
                )
            )

        if refs:
            return refs

        try:
            fallback_line = int(getattr(func, "line_start", 0) or 0)
        except (TypeError, ValueError):
            fallback_line = 0
        return [
            SpecRef(
                spec_text=str(fallback_text).strip(),
                source_file=file_rel,
                source_symbol=symbol,
                source_line_hint=fallback_line,
            )
        ]

    @staticmethod
    def _resolve_git_context(slice_root: Path) -> tuple[str, str]:
        branch = ""
        latest_commit = ""
        try:
            branch_proc = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=slice_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if branch_proc.returncode == 0:
                branch = branch_proc.stdout.strip()
        except OSError:
            branch = ""

        try:
            commit_proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=slice_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if commit_proc.returncode == 0:
                latest_commit = commit_proc.stdout.strip()
        except OSError:
            latest_commit = ""

        return branch, latest_commit

    @staticmethod
    def _build_patch(*, before_snapshot: dict[str, str], after_snapshot: dict[str, str]) -> str:
        candidate_paths = sorted(set(before_snapshot.keys()) | set(after_snapshot.keys()))
        patch_chunks: list[str] = []
        for rel_path in candidate_paths:
            before_text = before_snapshot.get(rel_path)
            after_text = after_snapshot.get(rel_path)
            if before_text == after_text:
                continue
            before_lines = (before_text or "").splitlines(keepends=True)
            after_lines = (after_text or "").splitlines(keepends=True)
            diff_lines = list(
                unified_diff(
                    before_lines,
                    after_lines,
                    fromfile=f"a/{rel_path}",
                    tofile=f"b/{rel_path}",
                )
            )
            if diff_lines:
                patch_chunks.extend(diff_lines)
        return "".join(patch_chunks)

    @staticmethod
    def _load_json(path: Path | None) -> Any:
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @classmethod
    def _load_plan_intentions(cls, plan_path: Path | None) -> list[dict[str, Any]]:
        payload = cls._load_json(plan_path)
        if isinstance(payload, dict):
            intentions = payload.get("intentions", [])
            if isinstance(intentions, list):
                return [row for row in intentions if isinstance(row, dict)]
            return []
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []

    @classmethod
    def _load_gap_report(cls, gaps_path: Path | None) -> list[dict[str, Any]]:
        payload = cls._load_json(gaps_path)
        if isinstance(payload, dict):
            rows = payload.get("open_gaps", payload.get("gaps", []))
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
            return []
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []

    @staticmethod
    def _load_constraints_context(paths: list[Path]) -> str:
        chunks: list[str] = []
        seen: set[Path] = set()
        for raw_path in paths:
            path = raw_path.expanduser().resolve() if raw_path else raw_path
            if not path or path in seen or not path.exists() or not path.is_file():
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            text = text.strip()
            if not text:
                continue
            # Keep context bounded to reduce prompt bloat.
            if len(text) > 5000:
                text = text[:5000] + "\n... (truncated)"
            chunks.append(f"### {path.name}\n{text}")
        return "\n\n".join(chunks)

    @classmethod
    def _collect_unresolved_candidates(
        cls,
        *,
        project_state: Any,
        slice_root: Path,
        unresolved_states: set[Any],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for file_path, file_state in sorted(project_state.files.items()):
            source_path = Path(file_path)
            if not source_path.is_absolute():
                source_path = (slice_root / source_path).resolve()
            file_rel = cls._normalize_path(cls._rel_to_slice(source_path, slice_root))
            unresolved = [
                fn for fn in file_state.functions if fn.translation_state in unresolved_states
            ]
            for func in sorted(unresolved, key=lambda item: item.line_start, reverse=True):
                spec_texts = [c.text for c in getattr(func, "spec_comments", [])]
                if not spec_texts and func.translation_state in unresolved_states:
                    continue
                candidates.append(
                    {
                        "file_key": str(file_path),
                        "file_path": source_path,
                        "file_rel": file_rel,
                        "qualified_name": str(getattr(func, "qualified_name", "")).strip(),
                        "function": func,
                    }
                )
        return candidates

    @classmethod
    def _prioritize_candidates(
        cls,
        *,
        candidates: list[dict[str, Any]],
        plan_intentions: list[dict[str, Any]],
        gap_report: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []

        plan_hints = cls._build_target_hints(plan_intentions)
        gap_hints = cls._build_target_hints(gap_report)

        plan_first: list[dict[str, Any]] = []
        gap_second: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []

        for candidate in candidates:
            if cls._candidate_matches_hints(candidate, plan_hints):
                plan_first.append(candidate)
            elif cls._candidate_matches_hints(candidate, gap_hints):
                gap_second.append(candidate)
            else:
                remaining.append(candidate)

        return plan_first + gap_second + remaining

    @classmethod
    def _build_target_hints(cls, rows: list[dict[str, Any]]) -> dict[str, set[str]]:
        files: set[str] = set()
        symbols: set[str] = set()

        for row in rows:
            if not isinstance(row, dict):
                continue

            for key in ("file", "target_file", "path", "module_path"):
                val = row.get(key)
                if isinstance(val, str) and val.strip():
                    files.add(cls._normalize_path(val))

            target_files = row.get("target_files")
            if isinstance(target_files, list):
                for val in target_files:
                    text = str(val).strip()
                    if text:
                        files.add(cls._normalize_path(text))

            for key in (
                "function_name",
                "target",
                "target_symbol",
                "symbol",
                "symbol_fqn",
                "fqn",
                "needed_for",
                "artifact_key",
            ):
                val = row.get(key)
                if isinstance(val, str) and val.strip():
                    symbols.add(val.strip().lower())

            target_symbols = row.get("target_symbols")
            if isinstance(target_symbols, list):
                for val in target_symbols:
                    text = str(val).strip().lower()
                    if text:
                        symbols.add(text)

            location = row.get("location")
            if isinstance(location, dict):
                loc_file = str(location.get("file", "")).strip()
                if loc_file:
                    files.add(cls._normalize_path(loc_file))
                loc_symbol = str(location.get("symbol", "")).strip().lower()
                if loc_symbol:
                    symbols.add(loc_symbol)

        return {"files": files, "symbols": symbols}

    @classmethod
    def _candidate_matches_hints(
        cls,
        candidate: dict[str, Any],
        hints: dict[str, set[str]],
    ) -> bool:
        hint_files = hints.get("files", set())
        hint_symbols = hints.get("symbols", set())

        file_rel = cls._normalize_path(str(candidate.get("file_rel", "")))
        if file_rel and any(cls._path_matches(file_rel, hint_file) for hint_file in hint_files):
            return True

        qualified_name = str(candidate.get("qualified_name", "")).strip().lower()
        symbols = {qualified_name} if qualified_name else set()
        if qualified_name:
            for sep in ("::", ":", "."):
                if sep in qualified_name:
                    symbols.add(qualified_name.rsplit(sep, 1)[-1])

        return any(sym in hint_symbols for sym in symbols if sym)

    @staticmethod
    def _lookup_live_function(
        *,
        project_state: Any,
        file_key: str,
        qualified_name: str,
        unresolved_states: set[Any],
    ) -> tuple[Any | None, Any | None]:
        file_state = project_state.files.get(file_key)
        if file_state is None:
            return None, None
        for func in file_state.functions:
            if str(getattr(func, "qualified_name", "")).strip() != qualified_name:
                continue
            if func.translation_state not in unresolved_states:
                return None, None
            return file_state, func
        return None, None

    @staticmethod
    def _is_function_still_unresolved(
        *,
        project_state: Any,
        file_key: str,
        qualified_name: str,
        unresolved_states: set[Any],
    ) -> bool:
        file_state = project_state.files.get(file_key)
        if file_state is None:
            return False
        for func in file_state.functions:
            if str(getattr(func, "qualified_name", "")).strip() != qualified_name:
                continue
            return func.translation_state in unresolved_states
        return False

    @staticmethod
    def _normalize_path(path: str) -> str:
        return path.strip().replace("\\", "/").lstrip("./").lower()

    @staticmethod
    def _path_matches(candidate: str, hint: str) -> bool:
        if not candidate or not hint:
            return False
        return candidate == hint or candidate.endswith(f"/{hint}") or hint.endswith(f"/{candidate}")

    @staticmethod
    def _rel_to_slice(path: Path, slice_root: Path) -> str:
        try:
            return path.resolve().relative_to(slice_root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

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
                prefix="impl_patch_",
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
        logger.warning(
            "Unknown under-spec event kind %r — defaulting to AMBIGUOUS_SPEC. "
            "Consider adding it to the classification mapping.",
            event.kind,
        )
        return "AMBIGUOUS_SPEC"
    return classification


def _need_artifact_type(event: UnderSpecEvent) -> str:
    kind = str(event.kind).strip().upper()
    if kind in {"EXTERNAL_DEP_UNKNOWN", "NEEDS_API_DECISION"}:
        return "git_symbol"
    if kind in {"MISSING_CONSTRAINT", "NEEDS_PRODUCT_DECISION"}:
        return "spec_comment"
    if kind == "CONFLICTING_CONSTRAINTS":
        return "spec_constraint_set"
    return "unknown"


def _need_expected_shape(event: UnderSpecEvent) -> dict[str, Any]:
    kind = str(event.kind).strip().upper()
    needed_for = str(event.needed_for or "").strip()
    if kind in {"EXTERNAL_DEP_UNKNOWN", "NEEDS_API_DECISION"}:
        return {"kind": "callable", "signature_hint": needed_for}
    if kind == "CONFLICTING_CONSTRAINTS":
        return {"kind": "constraint_resolution", "decision_type": event.decision_type}
    if kind in {"MISSING_CONSTRAINT", "NEEDS_PRODUCT_DECISION"}:
        return {"kind": "text_requirement", "decision_type": event.decision_type}
    return {"kind": "unknown"}


def _need_confidence(event: UnderSpecEvent) -> float:
    kind = str(event.kind).strip().upper()
    if kind == "EXTERNAL_DEP_UNKNOWN":
        return 0.9
    if kind in {"NEEDS_API_DECISION", "CONFLICTING_CONSTRAINTS"}:
        return 0.8
    if kind in {"MISSING_CONSTRAINT", "NEEDS_PRODUCT_DECISION"}:
        return 0.7
    return 0.6


def _signal_keywords(event: UnderSpecEvent) -> list[str]:
    raw = f"{event.needed_for or ''} {event.question}".strip()
    if not raw:
        return []
    separators = [":", ".", "/", "\\", "_", ",", "(", ")", "[", "]", "{", "}"]
    normalized = raw
    for separator in separators:
        normalized = normalized.replace(separator, " ")
    seen: set[str] = set()
    keywords: list[str] = []
    for token in normalized.split():
        cleaned = "".join(ch for ch in token if ch.isalnum())
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        keywords.append(cleaned)
    return keywords
