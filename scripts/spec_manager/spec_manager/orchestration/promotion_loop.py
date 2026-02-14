"""Per-slice iterative PromotionLoop.

Replaces the sequential P0-P10 pipeline with a per-slice loop that
invokes phases as tools until all gaps are closed and all atoms are
promoted through compliance gates.

State machine (per slice)::

    START_ITER
      ↓
    COLLECT_BASELINE   (diff/hash + manifest)
      ↓
    GAP_EXPLORATION    (P3 + GapQueue view)
      ↓
    PLAN               (P8)
      ↓
    IMPLEMENT          (P9) ← emits patch + pin/edge proposals + evidence
      ↓
    UNDER_SPEC_CHECK   (block-or-decide)
      ↓
    PROMOTE            (evidence integrity/completeness gates)
      ├─ if gates fail → DEMOTE → RESTART_ITER
      ↓
    INTEGRATE (CI)     (merge to parent + tick pipeline)
      ├─ if tests fail → DOWNWARD_FLOW → DEMOTE → RESTART_ITER
      ↓
    VERIFY             (P6 + P7 + architectural gates)
      ├─ if verify fails → DEMOTE → RESTART_ITER
      ↓
    ALIGN              (POWER alignment — drift/reward hacking)
      ├─ if high-severity findings → DEMOTE → RESTART_ITER
      ↓
    DONE?              (termination checks)
      ├─ if done → SLICE_COMPLETE
      └─ else → NEXT_ITER

Usage::

    loop = PromotionLoop(worktree_manager=wm, workspace_root=Path("."))
    result = loop.run_slice(slice_ref, run_context)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from spec_manager.orchestration.demotion import DemotionManager, DemotionTicket
from spec_manager.orchestration.evidence import EvidenceBundle
from spec_manager.orchestration.models import Layer

logger = logging.getLogger(__name__)


_SCAN_FALLBACK_KEY = "enable_gap_scanner_fallback"


def _hash_bytes(content: bytes) -> str:
    """Return stable SHA256 hex digest for content."""
    return hashlib.sha256(content).hexdigest()


def _hash_text(content: str) -> str:
    """Return stable SHA256 hex digest for text."""
    return _hash_bytes(content.encode("utf-8"))


def _safe_rel(path: Path, root: Path) -> str:
    """Return path relative to root, or best-effort fallback."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _location_span(
    *,
    start_line: Any = None,
    end_line: Any = None,
    start_col: Any = None,
    end_col: Any = None,
) -> dict[str, int]:
    """Normalize location payload into an explicit span dict."""
    span: dict[str, int] = {}
    if isinstance(start_line, int) and start_line > 0:
        span["start_line"] = start_line
    if isinstance(end_line, int) and end_line > 0:
        span["end_line"] = end_line
    elif "start_line" in span:
        span["end_line"] = span["start_line"]
    if isinstance(start_col, int) and start_col >= 0:
        span["start_col"] = start_col
    if isinstance(end_col, int) and end_col >= 0:
        span["end_col"] = end_col
    return span


def _normalize_gap_record(gap: dict[str, Any]) -> dict[str, Any]:
    """Ensure every gap has explicit location/span metadata."""
    location = gap.get("location", {}) or {}
    span = gap.get("span", {}) or {}
    normalized_span = _location_span(
        start_line=span.get("start_line") or location.get("start_line"),
        end_line=span.get("end_line") or location.get("end_line"),
        start_col=span.get("start_col") or location.get("start_col"),
        end_col=span.get("end_col") or location.get("end_col"),
    )
    file_path = gap.get("file", "") or location.get("file", "")
    merged = dict(gap)
    merged["file"] = file_path
    merged["span"] = normalized_span
    merged["location"] = {"file": file_path, **normalized_span}
    return merged


# ------------------------------------------------------------------
# Step protocol and result types
# ------------------------------------------------------------------


@dataclass
class StepResult:
    """Result of running a single loop step."""

    status: Literal["OK", "RETRY", "BLOCKED", "FAIL", "WAITING"] = "OK"
    bundle_path: str = ""
    emitted_tickets: list[DemotionTicket] = field(default_factory=list)
    notes_path: str | None = None
    error: str = ""


class LoopStep(Protocol):
    """Protocol for a single step in the promotion loop."""

    name: str

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Execute this step."""
        ...


@dataclass
class SliceRef:
    """Reference to a slice of work."""

    slice_id: str
    layer: Layer = "l1"
    library_id: str = ""
    worktree_path: str = ""


@dataclass
class RunContext:
    """Run-scoped context shared across all slices."""

    run_id: str = ""
    mode: Literal["interactive", "auto"] = "auto"
    workspace_root: str = ""
    max_iterations: int = 20
    max_iterations_by_layer: dict[str, int] = field(
        default_factory=lambda: {"l1": 20, "l2": 30, "l3": 15}
    )
    max_wait_cycles: int = 10
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class SliceContext:
    """Per-slice context for loop steps."""

    slice_id: str = ""
    slice_root: str = ""  # grandchild worktree path
    dirty_parent_root: str = ""
    clean_sibling_root: str = ""
    layer: Layer = "l1"
    run_id: str = ""
    mode: Literal["interactive", "auto"] = "auto"
    workspace_root: str = ""
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class SliceResult:
    """Final result of running the promotion loop on one slice."""

    slice_id: str = ""
    status: Literal["COMPLETE", "BLOCKED", "FAILED", "MAX_ITERATIONS", "STAGNATED", "WAITING"] = (
        "COMPLETE"
    )
    iterations: int = 0
    remaining_gaps: int = 0
    demotion_tickets: list[DemotionTicket] = field(default_factory=list)
    blocked_questions: list[str] = field(default_factory=list)
    pending_signals: list[dict] = field(default_factory=list)
    wake_count: int = 0
    error: str = ""


# ------------------------------------------------------------------
# Loop step implementations (delegate to existing modules)
# ------------------------------------------------------------------


class CollectBaselineStep:
    """Collect manifest + diff baseline for the slice."""

    name = "COLLECT_BASELINE"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Collect file hashes and diff from previous iteration."""
        from spec_manager.orchestration.evidence import DiffRef, ManifestRef

        slice_root = Path(ctx.slice_root)
        if not slice_root.exists():
            return StepResult(status="FAIL", error=f"Slice root does not exist: {ctx.slice_root}")

        # Collect manifest: list all source files with content hashes.
        files: list[dict[str, Any]] = []
        for p in sorted(slice_root.rglob("*")):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                try:
                    raw = p.read_bytes()
                except OSError as exc:
                    logger.debug("Baseline skip unreadable file %s: %s", p, exc)
                    continue
                rel_path = _safe_rel(p, slice_root)
                files.append(
                    {
                        "path": rel_path,
                        "sha256": _hash_bytes(raw),
                        "size_bytes": len(raw),
                    }
                )

        manifest_hash_input = "\n".join(
            f"{f['path']}:{f.get('sha256', '')}" for f in sorted(files, key=lambda x: x["path"])
        )
        manifest_hash = _hash_text(manifest_hash_input) if files else ""

        bundle.manifest = ManifestRef(files=files)
        bundle.diff = DiffRef(
            base_commit=bundle.diff.base_commit,
            head_commit=manifest_hash,
            changed_files=[f["path"] for f in files],
            content_hash=manifest_hash,
        )

        # Save bundle
        bundle.save(Path(ctx.workspace_root))
        return StepResult(status="OK")


class GapExplorationStep:
    """Find remaining gaps — layer-aware.

    - L1: P3 compliance (spec comments + stub functions)
    - L2: Architecture continuity gaps (unconsumed pins, missing components,
      missing event handlers, logic in arch files, manifest drift)
    - L3: Quality closure gaps (run reviewers → findings are gaps)
    """

    name = "GAP_EXPLORATION"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Dispatch to layer-specific gap exploration."""
        if ctx.layer == "l1":
            return self._explore_l1(ctx, bundle)
        if ctx.layer == "l2":
            return self._explore_l2(ctx, bundle)
        if ctx.layer == "l3":
            return self._explore_l3(ctx, bundle)
        return StepResult(status="OK")

    @staticmethod
    def _reuse_previous_gaps_if_fresh(
        ctx: SliceContext, bundle: EvidenceBundle
    ) -> list[dict[str, Any]] | None:
        """Reuse previous iteration gaps if file hash is unchanged."""
        if bundle.iteration <= 1:
            return None
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        prev_bundle_path = (
            workspace
            / ".pdd_runs"
            / bundle.run_id
            / "slices"
            / bundle.slice_id
            / f"iter_{bundle.iteration - 1:03d}"
            / "bundle.json"
        )
        if not prev_bundle_path.exists():
            return None

        try:
            prev = EvidenceBundle.load(prev_bundle_path)
        except Exception as exc:
            logger.debug(
                "Could not load previous bundle for gap reuse %s: %s", prev_bundle_path, exc
            )
            return None

        if prev.diff.content_hash and prev.diff.content_hash == bundle.diff.content_hash:
            return [dict(g) for g in (prev.gaps.open_gaps or [])]
        return None

    @staticmethod
    def _normalize_gap(gap: dict[str, Any]) -> dict[str, Any]:
        """Normalize prior gap evidence to span/location schema."""
        return _normalize_gap_record(gap)

    def _explore_l1(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L1: prefer promotion evidence; scanner is fallback only."""
        from spec_manager.orchestration.evidence import GapReportRef

        reused = self._reuse_previous_gaps_if_fresh(ctx, bundle)
        if reused is not None:
            bundle.gaps = GapReportRef(open_gaps=[self._normalize_gap(g) for g in reused])
            return StepResult(status="OK")

        allow_scan_fallback = bool(ctx.config.get(_SCAN_FALLBACK_KEY, False))
        if not allow_scan_fallback:
            bundle.gaps = GapReportRef(open_gaps=[])
            return StepResult(status="OK")

        slice_root = Path(ctx.slice_root)
        from spec_manager.core.language import source_rglob

        py_files = source_rglob(slice_root)
        if not py_files:
            bundle.gaps = GapReportRef(open_gaps=[])
            return StepResult(status="OK")

        try:
            from spec_manager.compliance.detection.orchestrator import (
                ScanConfig,
                scan_executable_gaps,
            )

            report = scan_executable_gaps(
                filepaths=py_files,
                project_root=slice_root,
                config=ScanConfig(enable_comments=True, enable_stubs=True),
            )

            gaps: list[dict[str, Any]] = []
            for ev in report.all_evidence:
                span = _location_span(
                    start_line=getattr(ev, "line_start", None) or getattr(ev, "start_line", None),
                    end_line=getattr(ev, "line_end", None) or getattr(ev, "end_line", None),
                    start_col=getattr(ev, "col_start", None) or getattr(ev, "start_col", None),
                    end_col=getattr(ev, "col_end", None) or getattr(ev, "end_col", None),
                )
                location_file = getattr(ev, "location", "") or ""
                gaps.append(
                    {
                        "file": location_file,
                        "description": getattr(ev, "description", ""),
                        "kind": getattr(ev, "invariant_family", "gap"),
                        "span": span,
                        "location": {"file": location_file, **span},
                    }
                )

            bundle.gaps = GapReportRef(open_gaps=gaps)
        except Exception as exc:
            logger.warning("L1 fallback gap exploration failed: %s", exc, exc_info=True)
            bundle.gaps = GapReportRef(open_gaps=[])
            return StepResult(status="RETRY", error=f"L1 fallback gap exploration failed: {exc}")

        return StepResult(status="OK")

    def _explore_l2(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L2: architecture continuity gaps via LLM analysis.

        Gaps are: unconsumed pins, missing components/files for manifest
        targets, missing event handlers, logic-like code in architectural
        files, manifest drift.
        """
        import json

        from spec_manager.core.language import source_rglob
        from spec_manager.orchestration.evidence import GapReportRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None

        if not slice_root or not slice_root.exists():
            bundle.gaps = GapReportRef(open_gaps=[])
            return StepResult(status="OK")

        reused = self._reuse_previous_gaps_if_fresh(ctx, bundle)
        if reused is not None:
            bundle.gaps = GapReportRef(open_gaps=[self._normalize_gap(g) for g in reused])
            return StepResult(status="OK")

        # Gather code summaries from slice for LLM analysis
        code_summaries: list[str] = []
        for py_file in source_rglob(slice_root):
            if py_file.is_file() and not any(p.startswith(".") for p in py_file.parts):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    lines = content.split("\n")[:80]
                    code_summaries.append(
                        f"### {py_file.relative_to(slice_root)}\n```\n" + "\n".join(lines) + "\n```"
                    )
                except (OSError, UnicodeDecodeError):
                    continue

        if not code_summaries:
            bundle.gaps = GapReportRef(open_gaps=[])
            return StepResult(status="OK")

        # Also include any open demotion tickets targeting L2
        open_tickets: list[str] = []
        demotions_dir = workspace / "analysis" / "demotion"
        if demotions_dir.exists():
            for ticket_file in demotions_dir.glob("*.json"):
                try:
                    data = json.loads(ticket_file.read_text(encoding="utf-8"))
                    if data.get("target_layer") == "L2":
                        open_tickets.append(data.get("diagnosis", ""))
                except Exception as exc:
                    logger.debug("Failed to read ticket file %s: %s", ticket_file, exc)
                    continue

        # L2 ReviewPack: 5 specialized architecture reviewers
        l2_reviewers = [
            ("pdd-l2-arch-boundary-reviewer", "ARCH_BOUNDARY"),
            ("pdd-l2-topology-reviewer", "TOPOLOGY"),
            ("pdd-l2-pin-edge-reviewer", "PIN_COVERAGE"),
            ("pdd-l2-arch-drift-reviewer", "ARCH_DRIFT"),
            ("pdd-l2-governance-reviewer", "GOVERNANCE"),
        ]

        # Pattern library for review context
        from spec_manager.orchestration.pattern_library import PatternLibrary

        pattern_lib = PatternLibrary()

        all_gaps: list[dict[str, Any]] = []
        code_section = "\n\n".join(code_summaries[:15])
        ticket_section = ""
        if open_tickets:
            ticket_section = "\n\n## OPEN DEMOTION TICKETS\n" + "\n".join(
                f"- {t}" for t in open_tickets[:10]
            )

        for reviewer_name, dimension in l2_reviewers:
            pattern_section = pattern_lib.get_review_prompt_section(dimension)
            reviewer_prompt = (
                f"## TASK\n"
                f"Review this architecture slice for {dimension} issues.\n\n"
                f"{pattern_section}\n\n"
                f"## CODE\n\n{code_section}"
                f"{ticket_section}\n"
            )

            try:
                from spec_manager.core.agent_utils import run_agent
                from spec_manager.core.json_extraction import _extract_json_payload
                from spec_manager.refinement.formats import _strip_code_fences

                output = run_agent(
                    agent_name=reviewer_name,
                    prompt=reviewer_prompt,
                    workspace=workspace,
                )
                cleaned = _strip_code_fences(output)
                data = json.loads(_extract_json_payload(cleaned))

                for finding in data.get("findings", []):
                    location = finding.get("location", {}) or {}
                    span = _location_span(
                        start_line=location.get("start_line"),
                        end_line=location.get("end_line"),
                        start_col=location.get("start_col"),
                        end_col=location.get("end_col"),
                    )
                    file_path = location.get("file", "")
                    all_gaps.append(
                        {
                            "kind": f"l2_{dimension.lower()}_finding",
                            "reviewer": reviewer_name,
                            "dimension": dimension,
                            "component_id": location.get("symbol", ""),
                            "file": file_path,
                            "description": finding.get("evidence", ""),
                            "severity": finding.get("severity", "MINOR"),
                            "required_change_type": finding.get(
                                "required_change_type", "wiring_only"
                            ),
                            "suggested_fix": finding.get("suggested_fix", ""),
                            "span": span,
                            "location": {"file": file_path, **span},
                        }
                    )
            except Exception as exc:
                logger.debug("L2 reviewer %s failed: %s", reviewer_name, exc)

        bundle.gaps = GapReportRef(open_gaps=all_gaps)

        return StepResult(status="OK")

    def _explore_l3(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L3: quality closure gaps — run reviewers, findings are gaps.

        Each reviewer finding that hasn't been resolved is an open gap.
        """
        import json

        from spec_manager.core.language import source_rglob
        from spec_manager.orchestration.evidence import GapReportRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None

        if not slice_root or not slice_root.exists():
            bundle.gaps = GapReportRef(open_gaps=[])
            return StepResult(status="OK")

        reused = self._reuse_previous_gaps_if_fresh(ctx, bundle)
        if reused is not None:
            bundle.gaps = GapReportRef(open_gaps=[self._normalize_gap(g) for g in reused])
            return StepResult(status="OK")

        # Gather code from slice — L3 slices are per-file (cq-{stem}),
        # so only review the matching file, not all files in the worktree
        code_files: dict[str, str] = {}
        target_stem = ctx.slice_id.removeprefix("cq-") if ctx.slice_id.startswith("cq-") else ""
        for py_file in source_rglob(slice_root):
            if py_file.is_file() and not any(p.startswith(".") for p in py_file.parts):
                if target_stem and py_file.stem != target_stem:
                    continue
                try:
                    code_files[str(py_file.relative_to(slice_root))] = py_file.read_text(
                        encoding="utf-8"
                    )
                except (OSError, UnicodeDecodeError):
                    continue

        if not code_files:
            bundle.gaps = GapReportRef(open_gaps=[])
            return StepResult(status="OK")

        reviewers = [
            "chatgpt-clarity-reviewer",
            "chatgpt-completeness-reviewer",
            "chatgpt-consistency-reviewer",
            "chatgpt-correctness-reviewer",
            "pdd-l3-drift-reviewer",
        ]

        # Pattern library for review context
        from spec_manager.orchestration.pattern_library import PatternLibrary

        pattern_lib = PatternLibrary()

        # Map reviewer names to pattern dimensions
        _REVIEWER_DIMENSIONS: dict[str, str] = {
            "chatgpt-clarity-reviewer": "CLARITY",
            "chatgpt-completeness-reviewer": "CORRECTNESS",
            "chatgpt-consistency-reviewer": "CONSISTENCY",
            "chatgpt-correctness-reviewer": "CORRECTNESS",
            "pdd-l3-drift-reviewer": "DRIFT",
        }

        all_gaps: list[dict[str, Any]] = []

        for file_path, code_content in code_files.items():
            for reviewer in reviewers:
                dimension = _REVIEWER_DIMENSIONS.get(reviewer, "")
                pattern_section = (
                    pattern_lib.get_review_prompt_section(dimension) if dimension else ""
                )
                reviewer_prompt = (
                    "## TASK\n"
                    "Review the following code for quality issues.\n"
                    "For each finding include: severity (BLOCKER/MAJOR/MINOR),\n"
                    "category (style/maintainability/logic/architecture/drift),\n"
                    "required_change_type (refactor_only/wiring_only/behavior_change),\n"
                    "and description.\n"
                    'Return JSON: {"findings": [...]}\n\n'
                    f"{pattern_section}\n\n"
                    f"File: {file_path}\n\n"
                    f"```\n{code_content[:4000]}\n```\n"
                )

                try:
                    from spec_manager.core.agent_utils import run_agent
                    from spec_manager.core.json_extraction import _extract_json_payload
                    from spec_manager.refinement.formats import _strip_code_fences

                    output = run_agent(
                        agent_name=reviewer,
                        prompt=reviewer_prompt,
                        workspace=workspace,
                    )
                    cleaned = _strip_code_fences(output)
                    data = json.loads(_extract_json_payload(cleaned))

                    for finding in data.get("findings", []):
                        location = finding.get("location", {}) or {}
                        span = _location_span(
                            start_line=location.get("start_line"),
                            end_line=location.get("end_line"),
                            start_col=location.get("start_col"),
                            end_col=location.get("end_col"),
                        )
                        all_gaps.append(
                            {
                                "kind": "quality_finding",
                                "file": file_path,
                                "reviewer": reviewer,
                                "description": finding.get("description", ""),
                                "severity": finding.get("severity", "MINOR"),
                                "category": finding.get("category", "style"),
                                "required_change_type": finding.get(
                                    "required_change_type", "refactor_only"
                                ),
                                "span": span,
                                "location": {"file": file_path, **span},
                            }
                        )
                except Exception as exc:
                    logger.debug("L3 reviewer %s failed for %s: %s", reviewer, file_path, exc)

        bundle.gaps = GapReportRef(open_gaps=all_gaps)
        return StepResult(status="OK")


class PlanStep:
    """Generate implementation plan from gaps — layer-aware.

    - L1: Convert spec gaps into function implementation intentions (P8)
    - L2: Convert architecture gaps into a wiring plan (which component
      to adjust, how to connect pins, handlers/routes to add)
    - L3: Convert quality findings into a refactor plan (group by
      function/span, sequence smallest safe refactors first, define
      "no behavior change" acceptance criteria)

    After generating intentions, checks decision requirements against
    the constraints store.  Uncovered decisions become under-spec events
    that block the slice before implementation begins.

    When a *planner* is provided, routes plan generation through the
    planner module instead of the static _plan_l2/_plan_l3
    methods.  The planner provides richer context-aware planning
    including integration analysis and constraint checking.
    """

    name = "PLAN"

    def __init__(self, planner: Any = None) -> None:
        self._planner = planner

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Generate layer-appropriate implementation plan from gaps."""
        from spec_manager.orchestration.evidence import PlanRef

        if not bundle.gaps.open_gaps:
            bundle.plan = PlanRef(intentions=[])
            return StepResult(status="OK")

        # L1: no-op — agents implement directly from spec comments/gaps,
        # no planner-generated intentions needed.
        if ctx.layer == "l1":
            bundle.plan = PlanRef(intentions=[])
            return StepResult(status="OK")

        # Route through planner if available (L2/L3 only)
        if self._planner is not None:
            intentions = self._plan_via_planner(ctx, bundle)
        elif ctx.layer == "l2":
            intentions = self._plan_l2(bundle.gaps.open_gaps)
        elif ctx.layer == "l3":
            intentions = self._plan_l3(bundle.gaps.open_gaps)
        else:
            intentions = []

        bundle.plan = PlanRef(intentions=intentions)

        # Run planning gate: check decision requirements against constraints
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else None
        if workspace:
            try:
                from spec_manager.orchestration.under_spec.planning_gate import (
                    run_planning_gate,
                )
                from spec_manager.planner.constraints.store import (
                    ConstraintsStore,
                )

                store = ConstraintsStore(workspace)
                gate_result = run_planning_gate(
                    constraints_store=store,
                    slice_id=ctx.slice_id,
                    intentions=intentions,
                )

                if not gate_result.all_covered:
                    existing = bundle.implementation.under_spec_events or []
                    bundle.implementation.under_spec_events = (
                        existing + gate_result.under_spec_events
                    )
            except Exception as exc:
                logger.debug("Planning gate skipped: %s", exc)

        return StepResult(status="OK")

    def _plan_via_planner(self, ctx: SliceContext, bundle: EvidenceBundle) -> list[dict[str, Any]]:
        """Route plan generation through the planner module."""
        from spec_manager.planner.api import PlanningContext

        planning_ctx = PlanningContext(
            run_id=ctx.run_id,
            slice_id=ctx.slice_id,
            layer=ctx.layer,
            mode=ctx.mode,
            workspace_root=ctx.workspace_root,
            slice_root=ctx.slice_root,
            bundle_ref=bundle,
        )
        return self._planner.plan_from_gaps(planning_ctx, bundle.gaps.open_gaps)

    @staticmethod
    def _plan_l2(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """L2: each gap becomes a wiring/assembly intention."""
        intentions = []
        for gap in gaps:
            component_id = gap.get("component_id", "")
            intentions.append(
                {
                    "gap_id": gap.get("file", component_id or "unknown"),
                    "component_id": component_id,
                    "target_file": gap.get("file", ""),
                    "approach": f"Wire: {gap.get('description', '')}",
                    "acceptance_criteria": "Component assembled, pins connected, no inlined logic",
                    "layer_constraint": "wiring_only",
                }
            )
        return intentions

    @staticmethod
    def _plan_l3(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """L3: group findings by file, sequence smallest refactors first."""
        # Group by file
        by_file: dict[str, list[dict[str, Any]]] = {}
        for gap in gaps:
            f = gap.get("file", "unknown")
            by_file.setdefault(f, []).append(gap)

        intentions = []
        for file_path, file_gaps in sorted(by_file.items()):
            # Sort: MINOR first (smallest, safest refactors)
            severity_order = {"MINOR": 0, "MAJOR": 1, "BLOCKER": 2}
            file_gaps.sort(key=lambda g: severity_order.get(g.get("severity", "MINOR"), 0))

            descriptions = [g.get("description", "") for g in file_gaps[:5]]
            intentions.append(
                {
                    "gap_id": file_path,
                    "target_file": file_path,
                    "approach": f"Refactor {len(file_gaps)} findings: {'; '.join(descriptions)}",
                    "acceptance_criteria": "No behavior change, all reviewers pass",
                    "layer_constraint": "refactor_only",
                    "finding_count": len(file_gaps),
                }
            )
        return intentions


class ImplementStep:
    """Execute the plan — layer-aware.

    - L1: Fill function bodies from spec comments via ImplementationRunner (P9)
    - L2: "Architectural assembler" — create/adjust component entrypoints,
      connect pins, add missing handlers/routes, refactor wiring.
      Must NOT invent business logic; emits under-spec or demotion if required.
    - L3: "Clean-code refactorer" — apply targeted refactors for planned
      finding set.  Must NOT change behavior; emits demotion if logic touched.
    """

    name = "IMPLEMENT"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Dispatch to layer-specific implementation and emit evidence atomically."""
        from spec_manager.orchestration.evidence import ImplementationRef

        # L1 runs even without intentions (uses gaps directly).
        # L2/L3 need explicit intentions from the planner.
        if ctx.layer != "l1" and not bundle.plan.intentions:
            bundle.implementation = ImplementationRef()
            return StepResult(status="OK")

        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            bundle.implementation = ImplementationRef()
            return StepResult(status="OK")

        result: StepResult
        if ctx.layer == "l1":
            result = self._implement_l1(ctx, bundle, slice_root)
        elif ctx.layer == "l2":
            result = self._implement_l2(ctx, bundle, slice_root)
        elif ctx.layer == "l3":
            result = self._implement_l3(ctx, bundle, slice_root)
        else:
            result = StepResult(status="OK")

        if result.status != "OK":
            return result

        try:
            self._emit_transactional_evidence(ctx, bundle, slice_root)
        except Exception as exc:
            logger.warning("Failed to emit transactional evidence: %s", exc, exc_info=True)
            return StepResult(
                status="RETRY",
                notes_path=result.notes_path,
                error=f"Implementation evidence emission failed: {exc}",
            )

        return result

    @staticmethod
    def _collect_slice_hashes(slice_root: Path) -> list[dict[str, Any]]:
        """Collect hash evidence for all non-hidden files in the slice."""
        files: list[dict[str, Any]] = []
        for file_path in sorted(slice_root.rglob("*")):
            if not file_path.is_file():
                continue
            if any(part.startswith(".") for part in file_path.parts):
                continue
            try:
                raw = file_path.read_bytes()
            except OSError as exc:
                logger.debug("Skipping unreadable file for hash evidence %s: %s", file_path, exc)
                continue
            rel = _safe_rel(file_path, slice_root)
            files.append(
                {
                    "path": rel,
                    "sha256": _hash_bytes(raw),
                    "size_bytes": len(raw),
                }
            )
        return files

    @staticmethod
    def _canonical_edge_signal(signal_type: Any) -> str:
        """Map implementation-specific edge types to evidence graph contract."""
        if not isinstance(signal_type, str):
            return "REFERENCE"
        signal = signal_type.upper()
        if signal in {"CALL"}:
            return "CALL"
        if signal in {"STORE_TOUCH"}:
            return "STORE_TOUCH"
        if signal in {"EVENT_EMIT", "EVENT_HANDLE", "EVENT"}:
            return "EVENT"
        return "REFERENCE"

    @staticmethod
    def _normalize_gap(gap: dict[str, Any]) -> dict[str, Any]:
        """Ensure every gap has explicit location span metadata."""
        location = gap.get("location", {}) or {}
        span = gap.get("span", {}) or {}
        normalized_span = _location_span(
            start_line=span.get("start_line") or location.get("start_line"),
            end_line=span.get("end_line") or location.get("end_line"),
            start_col=span.get("start_col") or location.get("start_col"),
            end_col=span.get("end_col") or location.get("end_col"),
        )
        file_path = gap.get("file", "") or location.get("file", "")
        merged = dict(gap)
        merged["file"] = file_path
        merged["span"] = normalized_span
        merged["location"] = {"file": file_path, **normalized_span}
        return merged

    @staticmethod
    def _gaps_from_under_spec_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Project under-spec events into gap inventory records."""
        gaps: list[dict[str, Any]] = []
        for event in events:
            span = _location_span(
                start_line=(event.get("span") or {}).get("start_line"),
                end_line=(event.get("span") or {}).get("end_line"),
                start_col=(event.get("span") or {}).get("start_col"),
                end_col=(event.get("span") or {}).get("end_col"),
            )
            file_path = event.get("file", "") or event.get("context", "")
            gaps.append(
                {
                    "kind": "ambiguity_gap",
                    "file": file_path,
                    "description": event.get("question", "Under-specification event"),
                    "severity": "BLOCKER",
                    "required_change_type": "spec_change",
                    "span": span,
                    "location": {"file": file_path, **span},
                }
            )
        return gaps

    def _emit_transactional_evidence(
        self,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        slice_root: Path,
    ) -> None:
        """Emit code+evidence artifacts as one promotion transaction."""
        from spec_manager.orchestration.evidence import GraphDeltaRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        iteration_dir = bundle.iter_dir(workspace)
        iteration_dir.mkdir(parents=True, exist_ok=True)

        file_hashes = self._collect_slice_hashes(slice_root)
        manifest_hash_input = "\n".join(
            f"{f['path']}:{f.get('sha256', '')}"
            for f in sorted(file_hashes, key=lambda x: x["path"])
        )
        manifest_hash = _hash_text(manifest_hash_input) if file_hashes else ""

        # Update manifest/diff to prove evidence aligns with exact file text.
        bundle.manifest.files = file_hashes
        bundle.diff.changed_files = [f["path"] for f in file_hashes]
        bundle.diff.content_hash = manifest_hash
        bundle.diff.head_commit = manifest_hash

        file_hash_path = iteration_dir / "file_hashes.json"
        file_hash_path.write_text(json.dumps(file_hashes, indent=2), encoding="utf-8")
        bundle.manifest.path = file_hash_path.name

        pin_deltas = bundle.implementation.pin_proposals or []
        edge_deltas = bundle.implementation.edge_proposals or []

        graph_deltas: list[GraphDeltaRef] = []
        if pin_deltas:
            pin_delta_path = iteration_dir / "pins.delta.json"
            pin_delta_path.write_text(json.dumps(pin_deltas, indent=2), encoding="utf-8")
            graph_deltas.append(
                GraphDeltaRef(
                    path=pin_delta_path.name,
                    delta_type="pin_proposal",
                    produced_by=self.name,
                )
            )
        if edge_deltas:
            canonical_edges = []
            for edge in edge_deltas:
                canonical_edges.append(
                    {
                        "src": edge.get("src", ""),
                        "dst": edge.get("dst", ""),
                        "signal_type": self._canonical_edge_signal(edge.get("signal_type")),
                        "weight": edge.get("weight", 0.7),
                    }
                )
            edge_delta_path = iteration_dir / "graph.delta.json"
            edge_delta_path.write_text(json.dumps(canonical_edges, indent=2), encoding="utf-8")
            graph_deltas.append(
                GraphDeltaRef(
                    path=edge_delta_path.name,
                    delta_type="edge_proposal",
                    produced_by=self.name,
                )
            )
        bundle.graph_deltas = graph_deltas

        pins_payload = {
            "schema_version": "1",
            "slice_id": ctx.slice_id,
            "layer": ctx.layer,
            "file_hash": manifest_hash,
            "pins": pin_deltas,
        }
        pins_payload_json = json.dumps(pins_payload, indent=2)
        pins_path = iteration_dir / "pins.snapshot.json"
        pins_path.write_text(pins_payload_json, encoding="utf-8")
        bundle.pins_snapshot.path = pins_path.name
        bundle.pins_snapshot.schema_version = pins_payload["schema_version"]
        bundle.pins_snapshot.snapshot_hash = _hash_text(pins_payload_json)

        graph_payload = {
            "schema_version": "1",
            "slice_id": ctx.slice_id,
            "layer": ctx.layer,
            "file_hash": manifest_hash,
            "edges": [
                {
                    "src": edge.get("src", ""),
                    "dst": edge.get("dst", ""),
                    "signal_type": self._canonical_edge_signal(edge.get("signal_type")),
                    "weight": edge.get("weight", 0.7),
                }
                for edge in edge_deltas
            ],
        }
        graph_payload_json = json.dumps(graph_payload, indent=2)
        graph_path = iteration_dir / "graph.snapshot.json"
        graph_path.write_text(graph_payload_json, encoding="utf-8")
        bundle.graph_snapshot.path = graph_path.name
        bundle.graph_snapshot.schema_version = graph_payload["schema_version"]
        bundle.graph_snapshot.snapshot_hash = _hash_text(graph_payload_json)

        explicit_gaps = [
            self._normalize_gap(g)
            for g in (bundle.implementation.gap_inventory or [])
            if isinstance(g, dict)
        ]
        event_gaps = self._gaps_from_under_spec_events(
            bundle.implementation.under_spec_events or []
        )
        if explicit_gaps or event_gaps:
            gap_inventory = explicit_gaps + event_gaps
        else:
            gap_inventory = [self._normalize_gap(g) for g in bundle.gaps.open_gaps]
        gap_path = iteration_dir / "gap_inventory.json"
        gap_path.write_text(json.dumps(gap_inventory, indent=2), encoding="utf-8")
        bundle.gaps.path = gap_path.name
        bundle.gaps.open_gaps = gap_inventory

        receipt = {
            "transaction": "code_plus_evidence",
            "slice_id": ctx.slice_id,
            "layer": ctx.layer,
            "file_hash": manifest_hash,
            "pins_snapshot": bundle.pins_snapshot.path,
            "graph_snapshot": bundle.graph_snapshot.path,
            "gap_inventory": bundle.gaps.path,
            "graph_delta_count": len(bundle.graph_deltas),
        }
        receipt_path = iteration_dir / "promotion.receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        bundle.promotion.path = receipt_path.name

    def _implement_l1(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L1: fill function bodies via ImplementationRunner (P9)."""
        from spec_manager.orchestration.evidence import ImplementationRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        try:
            from spec_manager.orchestration.implementation.runner import (
                ImplementationRunner,
            )

            runner = ImplementationRunner(
                workspace_root=workspace,
                run_id=ctx.run_id,
            )

            iteration_dir = bundle.iter_dir(workspace)
            run_result = runner.run_for_slice(
                slice_root=slice_root,
                iteration_dir=iteration_dir,
                plan_intentions=bundle.plan.intentions,
                gap_report=bundle.gaps.open_gaps,
            )

            gap_inventory = self._gaps_from_under_spec_events(run_result.under_spec_events)
            if run_result.functions_skipped > 0:
                gap_inventory.append(
                    {
                        "kind": "stub_gap",
                        "file": "",
                        "description": (
                            f"{run_result.functions_skipped} function(s) were skipped during "
                            "implementation and need follow-up."
                        ),
                        "severity": "MAJOR",
                        "required_change_type": "behavior_change",
                        "span": {},
                        "location": {"file": ""},
                    }
                )
            for err in run_result.errors:
                file_path = err.get("file", "")
                gap_inventory.append(
                    {
                        "kind": "ambiguity_gap",
                        "file": file_path,
                        "description": err.get("error", "Implementation error"),
                        "severity": "BLOCKER",
                        "required_change_type": "spec_change",
                        "span": {},
                        "location": {"file": file_path},
                    }
                )

            bundle.implementation = ImplementationRef(
                patch_path=run_result.patch_path,
                applied_edits=run_result.applied_edits,
                gap_inventory=gap_inventory,
                pin_proposals=run_result.pin_proposals,
                edge_proposals=run_result.edge_proposals,
                under_spec_events=run_result.under_spec_events,
                tests_added=run_result.tests_added,
            )

            if run_result.notes_path:
                return StepResult(status="OK", notes_path=run_result.notes_path)

        except Exception as exc:
            logger.warning("L1 implementation failed: %s", exc, exc_info=True)
            bundle.implementation = ImplementationRef()
            return StepResult(status="RETRY", error=f"L1 implementation failed: {exc}")

        return StepResult(status="OK")

    def _implement_l2(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L2: architectural assembler — wiring, dispatch, lifecycle, IO boundaries."""
        import json

        from spec_manager.core.language import source_rglob
        from spec_manager.orchestration.evidence import ImplementationRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        # Gather current code for context
        code_summaries: list[str] = []
        for py_file in source_rglob(slice_root):
            if py_file.is_file() and not any(p.startswith(".") for p in py_file.parts):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    lines = content.split("\n")[:60]
                    code_summaries.append(
                        f"### {py_file.relative_to(slice_root)}\n```\n" + "\n".join(lines) + "\n```"
                    )
                except (OSError, UnicodeDecodeError):
                    continue

        intentions_text = json.dumps(bundle.plan.intentions, indent=2)

        prompt = (
            "## TASK\n"
            "You are an Architectural Assembler. Apply minimal patches to wire components:\n"
            "- Create/adjust component entrypoints\n"
            "- Connect pins in correct order\n"
            "- Add missing handlers/routes\n"
            "- Refactor wiring to satisfy boundaries\n\n"
            "CONSTRAINT: Do NOT invent business logic. If the gap requires new logic,\n"
            "return it as an under_spec_event instead of implementing it.\n\n"
            "Return JSON with keys:\n"
            '- "edits": [{"file": ..., "description": ...}]\n'
            '- "pin_proposals": [{"pin_id": ..., "fqn": ..., "file": ..., "span": {...}}]\n'
            '- "edge_proposals": [{"src": ..., "dst": ..., '
            '"signal_type": "CALL"|"STORE_TOUCH"|"EVENT"|"REFERENCE"}]\n'
            '- "gap_inventory": [{"kind": "stub_gap"|"comment_gap"|"ambiguity_gap", "file": ..., '
            '"description": ..., "span": {"start_line": N, "end_line": N}}]\n'
            '- "under_spec_events": [{"question": ..., "context": ...}]\n\n'
            f"## PLAN\n{intentions_text}\n\n"
            "## CURRENT CODE\n\n" + "\n\n".join(code_summaries[:10])
        )

        try:
            from spec_manager.core.agent_utils import run_agent
            from spec_manager.core.json_extraction import _extract_json_payload
            from spec_manager.refinement.formats import _strip_code_fences

            output = run_agent(
                agent_name="opus-architecture-proposer",
                prompt=prompt,
                workspace=workspace,
            )
            cleaned = _strip_code_fences(output)
            data = json.loads(_extract_json_payload(cleaned))

            gap_inventory = [self._normalize_gap(g) for g in data.get("gap_inventory", [])]
            gap_inventory.extend(
                self._gaps_from_under_spec_events(data.get("under_spec_events", []))
            )
            bundle.implementation = ImplementationRef(
                applied_edits=data.get("edits", []),
                gap_inventory=gap_inventory,
                pin_proposals=data.get("pin_proposals", []),
                edge_proposals=data.get("edge_proposals", []),
                under_spec_events=data.get("under_spec_events", []),
            )

        except Exception as exc:
            logger.warning("L2 implementation failed: %s", exc)
            bundle.implementation = ImplementationRef()
            return StepResult(
                status="RETRY",
                error=f"L2 implementation parse error: {exc}",
            )

        return StepResult(status="OK")

    def _implement_l3(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L3: clean-code refactorer — targeted refactors, no behavior change."""
        import json

        from spec_manager.core.language import source_rglob
        from spec_manager.orchestration.evidence import ImplementationRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        intentions_text = json.dumps(bundle.plan.intentions, indent=2)
        gaps_text = json.dumps(bundle.gaps.open_gaps[:20], indent=2)

        # Gather code for the files being refactored — scope to slice file for L3
        code_summaries: list[str] = []
        target_files = {i.get("target_file", "") for i in bundle.plan.intentions}
        target_stem = ctx.slice_id.removeprefix("cq-") if ctx.slice_id.startswith("cq-") else ""
        for py_file in source_rglob(slice_root):
            if target_stem and py_file.stem != target_stem:
                continue
            rel = (
                str(py_file.relative_to(slice_root))
                if slice_root in py_file.parents or py_file.parent == slice_root
                else ""
            )
            if (rel in target_files or not target_files) and py_file.is_file():
                try:
                    content = py_file.read_text(encoding="utf-8")
                    code_summaries.append(
                        f"### {py_file.relative_to(slice_root)}\n```\n{content[:3000]}\n```"
                    )
                except (OSError, UnicodeDecodeError):
                    continue

        prompt = (
            "## TASK\n"
            "You are a Clean-Code Refactorer. Apply targeted refactors to "
            "resolve quality findings.\n\n"
            "CONSTRAINT: Do NOT change behavior. All refactors must be behavior-preserving.\n"
            "If a finding requires a logic change, return it as a demotion_needed item.\n\n"
            "Return JSON with keys:\n"
            '- "edits": [{"file": ..., "description": ...}]\n'
            '- "pin_proposals": [{"pin_id": ..., "fqn": ..., "file": ..., "span": {...}}]\n'
            '- "edge_proposals": [{"src": ..., "dst": ..., '
            '"signal_type": "CALL"|"STORE_TOUCH"|"EVENT"|"REFERENCE"}]\n'
            '- "gap_inventory": [{"kind": "stub_gap"|"comment_gap"|"ambiguity_gap", "file": ..., '
            '"description": ..., "span": {"start_line": N, "end_line": N}}]\n'
            '- "demotion_needed": [{"file": ..., "reason": ..., "target_layer": "L1"|"L2"}]\n\n'
            f"## REFACTOR PLAN\n{intentions_text}\n\n"
            f"## FINDINGS TO ADDRESS\n{gaps_text}\n\n"
            "## CURRENT CODE\n\n" + "\n\n".join(code_summaries[:10])
        )

        try:
            from spec_manager.core.agent_utils import run_agent
            from spec_manager.core.json_extraction import _extract_json_payload
            from spec_manager.refinement.formats import _strip_code_fences

            output = run_agent(
                agent_name="chatgpt-correctness-reviewer",
                prompt=prompt,
                workspace=workspace,
            )
            cleaned = _strip_code_fences(output)
            data = json.loads(_extract_json_payload(cleaned))

            # Convert demotion_needed to under_spec_events for downstream processing
            under_spec = []
            for d in data.get("demotion_needed", []):
                under_spec.append(
                    {
                        "kind": "NEEDS_PRODUCT_DECISION",
                        "file": d.get("file", ""),
                        "question": f"Logic change required: {d.get('reason', '')}",
                        "context": d.get("file", ""),
                        "demotion_target": d.get("target_layer", "L1"),
                    }
                )

            gap_inventory = [self._normalize_gap(g) for g in data.get("gap_inventory", [])]
            gap_inventory.extend(self._gaps_from_under_spec_events(under_spec))
            bundle.implementation = ImplementationRef(
                applied_edits=data.get("edits", []),
                gap_inventory=gap_inventory,
                pin_proposals=data.get("pin_proposals", []),
                edge_proposals=data.get("edge_proposals", []),
                under_spec_events=under_spec,
            )

        except Exception as exc:
            logger.warning("L3 implementation failed: %s", exc)
            bundle.implementation = ImplementationRef()
            return StepResult(
                status="RETRY",
                error=f"L3 implementation parse error: {exc}",
            )

        return StepResult(status="OK")


class CoordinateStep:
    """Coordinate agent dependencies via reactive planner triage.

    For L1: treats under_spec_events as coordination signals,
    calls planner triage, registers monitors, returns WAITING.

    For L2/L3: delegates to existing UnderSpecManager behavior.
    """

    name = "COORDINATE"

    def __init__(self, planner: Any = None) -> None:
        self._planner = planner

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Dispatch to L1 coordination or L2/L3 under-spec resolution."""
        if ctx.layer == "l1":
            return self._coordinate_l1(ctx, bundle)
        # L2/L3: existing under-spec behavior
        return self._resolve_under_spec(ctx, bundle)

    def _coordinate_l1(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L1: convert under_spec_events to CoordinationSignals and triage.

        If no signals/under_spec_events: return OK.
        Otherwise: write signals to iteration dir and return WAITING.
        """
        from spec_manager.orchestration.coordination.signals import CoordinationSignal

        raw_events = bundle.implementation.under_spec_events
        if not raw_events:
            return StepResult(status="OK")

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        # Convert under_spec_events to CoordinationSignals
        signals: list[CoordinationSignal] = []
        for event in raw_events:
            # Map under-spec event kinds to signal classifications
            kind = event.get("kind", "AMBIGUOUS_SPEC")
            classification_map = {
                "MISSING_CONSTRAINT": "MISSING_INTERFACE",
                "AMBIGUITY": "AMBIGUOUS_SPEC",
                "CONFLICTING": "CONFLICTING_REQUIREMENTS",
                "INTERFACE_MISMATCH": "INTERFACE_MISMATCH",
            }
            classification = classification_map.get(kind, "AMBIGUOUS_SPEC")

            from spec_manager.orchestration.coordination.signals import (
                SignalNeed,
                SpecRef,
            )

            signal = CoordinationSignal(
                run_id=ctx.run_id,
                layer=ctx.layer,
                slice_id=ctx.slice_id,
                classification=classification,
                need=SignalNeed(
                    summary=event.get("question", ""),
                    artifact_type=event.get("kind", ""),
                ),
                spec_refs=[SpecRef(spec_text=event.get("context", ""))]
                if event.get("context")
                else [],
            )
            signals.append(signal)

        # If planner available: triage each signal
        if self._planner is not None:
            for signal in signals:
                try:
                    self._planner.triage_signal(signal)
                except Exception as exc:
                    logger.debug("Planner triage failed for signal %s: %s", signal.signal_id, exc)

        # Write signals to iteration dir
        iteration_dir = bundle.iter_dir(workspace)
        for signal in signals:
            signal.write_to(iteration_dir)

        return StepResult(status="WAITING")

    def _resolve_under_spec(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L2/L3: resolve under-spec events via UnderSpecManager.

        Delegates to UnderSpecManager for constraint resolution.
        """
        raw_events = bundle.implementation.under_spec_events

        if not raw_events:
            return StepResult(status="OK")

        from spec_manager.orchestration.under_spec.manager import (
            UnderSpecEvent,
            UnderSpecManager,
        )

        events = [UnderSpecEvent.from_dict(e) for e in raw_events]
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        manager = UnderSpecManager(
            workspace_root=workspace,
            mode=ctx.mode,
            planner=self._planner,
        )
        outcome = manager.resolve(slice_id=ctx.slice_id, events=events, layer=ctx.layer)

        # Record decisions in the bundle
        bundle.under_spec.decisions = [
            {"event_id": e.event_id, "question": e.question} for e in outcome.resolved
        ]
        bundle.under_spec.blockers = [e.to_dict() for e in outcome.blocked]

        # Record new constraint refs
        if outcome.constraints:
            constraint_path = str(workspace / "analysis" / "constraints" / f"{ctx.slice_id}.json")
            if constraint_path not in bundle.facts.constraints_refs:
                bundle.facts.constraints_refs.append(constraint_path)

        if outcome.is_blocked:
            bundle.status = "BLOCKED"
            return StepResult(
                status="BLOCKED",
                error=f"Under-specification: {len(outcome.blocked)} unresolvable events",
            )

        return StepResult(status="OK")


class AnalyzeStep:
    """Analyze slice after implementation — layer-aware.

    - L1: P1 + P2 (structure + decomposition) via SourceAnalysisCache
    - L2: Build/update architecture graph cache (components, entrypoints,
      pins, edges, events, middleware ordering, dependencies)
    - L3: Compute diff summary + structural metrics (size, duplication
      hotspots, refactor impact candidates)
    """

    name = "ANALYZE"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Dispatch to layer-specific analysis."""
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            return StepResult(status="OK")

        if ctx.layer == "l1":
            return self._analyze_l1(ctx, bundle, slice_root)
        if ctx.layer == "l2":
            return self._analyze_l2(ctx, bundle, slice_root)
        if ctx.layer == "l3":
            return self._analyze_l3(ctx, bundle, slice_root)

        return StepResult(status="OK")

    def _analyze_l1(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L1: source analysis via cache (P1 + P2)."""
        from spec_manager.core.language import source_rglob

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        try:
            from spec_manager.orchestration.source_analysis_cache import (
                SourceAnalysisCache,
            )

            cache = SourceAnalysisCache(
                workspace_root=workspace,
                run_id=ctx.run_id,
            )

            entries: list[dict[str, str]] = []
            for py_file in source_rglob(slice_root):
                if not py_file.is_file():
                    continue
                if any(part.startswith(".") for part in py_file.parts):
                    continue
                try:
                    content = py_file.read_text(encoding="utf-8")
                    analysis = cache.analyze_with_cache(
                        content, str(py_file.relative_to(slice_root))
                    )
                    entries.append(
                        {
                            "path": str(py_file.relative_to(slice_root)),
                            "functions": str(len(analysis.functions)),
                            "comments": str(len(analysis.comments)),
                        }
                    )
                except (OSError, UnicodeDecodeError) as exc:
                    logger.debug("Skipping %s: %s", py_file, exc)

            bundle.source_index.entries = entries
            bundle.source_index.path = "source_analysis.index.json"

            logger.info(
                "Analyzed %d files (cache stats: %s)",
                len(entries),
                cache.stats,
            )

        except Exception as exc:
            logger.warning("L1 analysis failed: %s", exc, exc_info=True)
            return StepResult(status="RETRY", error=f"L1 analysis failed: {exc}")

        return StepResult(status="OK")

    def _analyze_l2(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L2: build architecture graph summary (components, pins, edges)."""
        import json

        from spec_manager.core.language import source_rglob

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        # Gather file summaries for LLM analysis
        code_summaries: list[str] = []
        for py_file in source_rglob(slice_root):
            if py_file.is_file() and not any(p.startswith(".") for p in py_file.parts):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    code_summaries.append(
                        f"### {py_file.relative_to(slice_root)}\n```\n" + content[:1500] + "\n```"
                    )
                except (OSError, UnicodeDecodeError):
                    continue

        if not code_summaries:
            return StepResult(status="OK")

        prompt = (
            "## TASK\n"
            "Analyze the architecture of this code and produce a component graph summary.\n"
            "Identify: components, entrypoints, pins/atoms used, edges (calls/events/deps),\n"
            "middleware ordering, and dependency direction.\n\n"
            'Return JSON: {"components": [...], "edges": [...], '
            '"stats": {"total_components": N, "total_edges": N}}\n\n'
            "## CODE\n\n" + "\n\n".join(code_summaries[:15])
        )

        try:
            from spec_manager.core.agent_utils import run_agent
            from spec_manager.core.json_extraction import _extract_json_payload
            from spec_manager.refinement.formats import _strip_code_fences

            output = run_agent(
                agent_name="opus-architecture-proposer",
                prompt=prompt,
                workspace=workspace,
            )
            cleaned = _strip_code_fences(output)
            data = json.loads(_extract_json_payload(cleaned))

            # Store in source_index for downstream consumption
            entries = []
            for comp in data.get("components", []):
                entries.append(
                    {
                        "path": comp.get("file", ""),
                        "component_id": comp.get("id", ""),
                        "type": comp.get("type", ""),
                    }
                )
            bundle.source_index.entries = entries
            bundle.source_index.path = "architecture_graph.index.json"

            stats = data.get("stats", {})
            logger.info(
                "L2 analysis: %d components, %d edges",
                stats.get("total_components", 0),
                stats.get("total_edges", 0),
            )

        except Exception as exc:
            logger.warning("L2 analysis failed: %s", exc, exc_info=True)
            return StepResult(status="RETRY", error=f"L2 analysis failed: {exc}")

        return StepResult(status="OK")

    def _analyze_l3(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L3: diff summary + structural metrics."""
        from spec_manager.core.language import FUNCTION_KEYWORDS, source_rglob

        entries: list[dict[str, str]] = []
        total_lines = 0
        total_functions = 0
        target_stem = ctx.slice_id.removeprefix("cq-") if ctx.slice_id.startswith("cq-") else ""

        for py_file in source_rglob(slice_root):
            if not py_file.is_file():
                continue
            if any(part.startswith(".") for part in py_file.parts):
                continue
            if target_stem and py_file.stem != target_stem:
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                lines = content.split("\n")
                # Simple function count (heuristic — actual analysis done by reviewers)
                func_count = sum(
                    1
                    for line in lines
                    if any(line.strip().startswith(kw) for kw in FUNCTION_KEYWORDS)
                )
                total_lines += len(lines)
                total_functions += func_count
                entries.append(
                    {
                        "path": str(py_file.relative_to(slice_root)),
                        "lines": str(len(lines)),
                        "functions": str(func_count),
                    }
                )
            except (OSError, UnicodeDecodeError):
                continue

        bundle.source_index.entries = entries
        bundle.source_index.path = "quality_metrics.index.json"

        logger.info(
            "L3 analysis: %d files, %d lines, %d functions",
            len(entries),
            total_lines,
            total_functions,
        )

        return StepResult(status="OK")


class PromoteStep:
    """Run evidence-first compliance gates.

    Promotion gates validate consistency and completeness of emitted evidence:
    file hashes, gap spans, pin/graph snapshots, and graph delta signal types.
    They do not re-evaluate source code directly on the normal path.
    """

    name = "PROMOTE"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Dispatch to layer-specific promotion gates."""
        has_evidence = bool(
            bundle.manifest.files
            or bundle.implementation.applied_edits
            or bundle.implementation.pin_proposals
            or bundle.implementation.edge_proposals
            or bundle.gaps.open_gaps
        )
        if not has_evidence:
            return StepResult(status="OK")

        if ctx.layer == "l1":
            return self._promote_l1(ctx, bundle)
        if ctx.layer == "l2":
            return self._promote_l2(ctx, bundle)
        if ctx.layer == "l3":
            return self._promote_l3(ctx, bundle)

        return StepResult(status="OK")

    @staticmethod
    def _expected_manifest_hash(bundle: EvidenceBundle) -> str:
        """Compute stable manifest hash from manifest entries."""
        if not bundle.manifest.files:
            return ""
        material = "\n".join(
            f"{item.get('path', '')}:{item.get('sha256', '')}"
            for item in sorted(bundle.manifest.files, key=lambda x: x.get("path", ""))
        )
        return _hash_text(material) if material else ""

    def _validate_hash_consistency(self, bundle: EvidenceBundle) -> list[str]:
        """Validate that evidence references match manifest hash state."""
        failures: list[str] = []
        if not bundle.manifest.files:
            failures.append("Manifest missing files/hash entries")
            return failures

        expected = self._expected_manifest_hash(bundle)
        if not expected:
            failures.append("Manifest hash could not be computed")
            return failures

        recorded = bundle.diff.content_hash
        if recorded and recorded != expected:
            failures.append("Diff content hash does not match manifest hash")

        if not bundle.pins_snapshot.path:
            failures.append("Pin snapshot artifact missing")
        if not bundle.pins_snapshot.snapshot_hash:
            failures.append("Pin snapshot hash missing")

        if not bundle.graph_snapshot.path:
            failures.append("Graph snapshot artifact missing")
        if not bundle.graph_snapshot.snapshot_hash:
            failures.append("Graph snapshot hash missing")

        return failures

    @staticmethod
    def _validate_gap_spans(bundle: EvidenceBundle) -> list[str]:
        """Ensure each open gap carries explicit location/span metadata."""
        failures: list[str] = []
        for idx, gap in enumerate(bundle.gaps.open_gaps):
            if not isinstance(gap, dict):
                failures.append(f"Gap {idx} is not a dict record")
                continue
            span = gap.get("span", {}) or {}
            location = gap.get("location", {}) or {}
            if not isinstance(span, dict) or not isinstance(location, dict):
                failures.append(f"Gap {idx} has malformed span/location")
                continue
            if "file" not in location:
                failures.append(f"Gap {idx} missing location.file")
        return failures

    def _validate_graph_evidence(self, bundle: EvidenceBundle) -> list[str]:
        """Validate graph delta/snapshot consistency and signal taxonomy."""
        failures: list[str] = []
        allowed = {"CALL", "STORE_TOUCH", "EVENT", "REFERENCE"}

        if bundle.implementation.edge_proposals and not bundle.graph_deltas:
            failures.append("Edge proposals exist but graph delta artifacts are missing")

        for edge in bundle.implementation.edge_proposals or []:
            signal = self._canonical_edge_signal(edge.get("signal_type"))
            if signal not in allowed:
                failures.append(f"Unsupported edge signal type: {edge.get('signal_type')}")

        for delta in bundle.graph_deltas or []:
            if not delta.path:
                failures.append("Graph delta missing artifact path")
            if delta.delta_type not in {"pin_proposal", "edge_proposal", "merge"}:
                failures.append(f"Unknown graph delta type: {delta.delta_type}")

        return failures

    @staticmethod
    def _to_gate(
        gate_id: str, passed: bool, summary: str, required_change_type: str
    ) -> dict[str, Any]:
        """Build a gate entry for EvidenceBundle gates report."""
        return {
            "gate_id": gate_id,
            "passed": passed,
            "summary": summary,
            "required_change_type": required_change_type,
        }

    def _promote_l1(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L1: verify evidence transaction integrity."""
        failures = self._validate_hash_consistency(bundle)
        failures.extend(self._validate_gap_spans(bundle))
        failures.extend(self._validate_graph_evidence(bundle))

        bundle.gates.gates = [
            self._to_gate(
                "EVIDENCE_HASH_ALIGNMENT",
                not any("hash" in f.lower() or "manifest" in f.lower() for f in failures),
                "; ".join(f for f in failures if "hash" in f.lower() or "manifest" in f.lower())
                or "Manifest and snapshot hashes are aligned",
                "refactor_only",
            ),
            self._to_gate(
                "GAP_SPAN_COMPLETENESS",
                not any("gap" in f.lower() for f in failures),
                "; ".join(f for f in failures if "gap" in f.lower())
                or "Gap inventory includes location metadata",
                "behavior_change",
            ),
            self._to_gate(
                "GRAPH_EVIDENCE_COMPLETENESS",
                not any("graph" in f.lower() or "edge" in f.lower() for f in failures),
                "; ".join(f for f in failures if "graph" in f.lower() or "edge" in f.lower())
                or "Graph evidence artifacts are complete",
                "wiring_only",
            ),
        ]

        if failures:
            return StepResult(
                status="RETRY",
                emitted_tickets=[
                    DemotionTicket(
                        run_id=ctx.run_id,
                        slice_id=ctx.slice_id,
                        source="GATE_FAILURE",
                        gate="EVIDENCE_INTEGRITY",
                        target_layer="L1",
                        severity="BLOCKER",
                        diagnosis="; ".join(failures),
                    )
                ],
                error="L1 evidence integrity gate failed",
            )
        return StepResult(status="OK")

    def _promote_l2(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L2: architecture gates over pin/graph evidence."""
        failures = self._validate_hash_consistency(bundle)
        failures.extend(self._validate_graph_evidence(bundle))

        bundle.gates.gates = [
            self._to_gate(
                "PIN_CONSUMPTION_EVIDENCE",
                bool(bundle.pins_snapshot.path),
                "Pin snapshot present" if bundle.pins_snapshot.path else "Pin snapshot missing",
                "wiring_only",
            ),
            self._to_gate(
                "EDGE_REALIZATION_EVIDENCE",
                bool(bundle.graph_snapshot.path),
                "Graph snapshot present"
                if bundle.graph_snapshot.path
                else "Graph snapshot missing",
                "wiring_only",
            ),
            self._to_gate(
                "ARCH_EVENT_COVERAGE_EVIDENCE",
                bool(bundle.graph_snapshot.path),
                "Graph snapshot available for event coverage checks"
                if bundle.graph_snapshot.path
                else "Missing graph snapshot for event coverage checks",
                "wiring_only",
            ),
            self._to_gate(
                "EVIDENCE_HASH_ALIGNMENT",
                not any("hash" in f.lower() or "manifest" in f.lower() for f in failures),
                "; ".join(f for f in failures if "hash" in f.lower() or "manifest" in f.lower())
                or "Manifest and evidence hashes align",
                "behavior_change",
            ),
        ]

        failed_gates = [g for g in bundle.gates.gates if not g["passed"]]
        if failed_gates:
            tickets = []
            for gate in failed_gates:
                target = "L1" if gate["required_change_type"] == "behavior_change" else "L2"
                tickets.append(
                    DemotionTicket(
                        run_id=ctx.run_id,
                        slice_id=ctx.slice_id,
                        source="GATE_FAILURE",
                        gate=gate["gate_id"],
                        origin_layer="L2",
                        target_layer=target,
                        severity="BLOCKER",
                        diagnosis=gate["summary"],
                    )
                )
            return StepResult(
                status="RETRY",
                emitted_tickets=tickets,
                error=f"L2 evidence gates failed: {[g['gate_id'] for g in failed_gates]}",
            )
        return StepResult(status="OK")

    def _promote_l3(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L3: quality closure checks over emitted evidence."""

        # Check if there are still open quality gaps
        open_gaps = bundle.gaps.open_gaps
        quality_gaps = [g for g in open_gaps if g.get("kind") == "quality_finding"]

        if quality_gaps:
            # Still have unresolved findings — not ready to promote
            tickets = []
            for g in quality_gaps:
                cat = g.get("category", "style")
                if cat in ("logic", "correctness"):
                    tickets.append(
                        DemotionTicket(
                            run_id=ctx.run_id,
                            slice_id=ctx.slice_id,
                            source="REVIEW",
                            origin_layer="L3",
                            target_layer="L1",
                            severity=g.get("severity", "MAJOR"),
                            diagnosis=g.get("description", "Quality finding requires logic change"),
                            failing_files=[g["file"]] if g.get("file") else [],
                        )
                    )
                elif cat == "architecture":
                    tickets.append(
                        DemotionTicket(
                            run_id=ctx.run_id,
                            slice_id=ctx.slice_id,
                            source="REVIEW",
                            origin_layer="L3",
                            target_layer="L2",
                            severity=g.get("severity", "MAJOR"),
                            diagnosis=g.get("description", "Quality finding requires arch change"),
                            failing_files=[g["file"]] if g.get("file") else [],
                        )
                    )

            if tickets:
                error_msg = (
                    f"L3: {len(quality_gaps)} quality findings unresolved "
                    f"({len(tickets)} demotions)"
                )
                return StepResult(
                    status="RETRY",
                    emitted_tickets=tickets,
                    error=error_msg,
                )

            # Non-demotion findings: retry to fix in L3
            return StepResult(
                status="RETRY",
                error=f"L3: {len(quality_gaps)} quality findings still open",
            )

        failures = self._validate_hash_consistency(bundle)
        failures.extend(self._validate_gap_spans(bundle))

        behavior_change_gaps = [
            g
            for g in bundle.implementation.gap_inventory
            if g.get("required_change_type") == "behavior_change"
        ]
        wiring_edges = [
            e
            for e in bundle.implementation.edge_proposals
            if self._canonical_edge_signal(e.get("signal_type")) != "REFERENCE"
        ]

        bundle.gates.gates = [
            self._to_gate(
                "NO_LOGIC_CHANGE_EVIDENCE",
                not behavior_change_gaps,
                "No behavior-change gaps in implementation evidence"
                if not behavior_change_gaps
                else f"{len(behavior_change_gaps)} behavior-change gap(s) reported",
                "behavior_change",
            ),
            self._to_gate(
                "NO_ARCH_BOUNDARY_VIOLATIONS_EVIDENCE",
                not wiring_edges,
                "No architecture wiring edges emitted in L3"
                if not wiring_edges
                else f"{len(wiring_edges)} architecture edge(s) emitted in L3",
                "wiring_only",
            ),
            self._to_gate(
                "EVIDENCE_HASH_ALIGNMENT",
                not failures,
                "; ".join(failures) if failures else "Evidence hashes align with current text",
                "refactor_only",
            ),
        ]

        failed = [gate for gate in bundle.gates.gates if not gate["passed"]]
        if failed:
            tickets = []
            for gate in failed:
                target = "L1" if gate["required_change_type"] == "behavior_change" else "L2"
                if gate["required_change_type"] == "refactor_only":
                    target = "L3"
                tickets.append(
                    DemotionTicket(
                        run_id=ctx.run_id,
                        slice_id=ctx.slice_id,
                        source="GATE_FAILURE",
                        origin_layer="L3",
                        target_layer=target,
                        gate=gate["gate_id"],
                        severity="BLOCKER" if target in {"L1", "L3"} else "MAJOR",
                        diagnosis=gate["summary"],
                    )
                )
            return StepResult(
                status="RETRY",
                emitted_tickets=tickets,
                error=f"L3 evidence gates failed: {[g['gate_id'] for g in failed]}",
            )

        return StepResult(status="OK")


class IntegrateStep:
    """Merge slice into dirty, tick CI pipeline.

    On CI failure, invokes an Investigator agent (budget=2 attempts)
    before falling through to demotion.  If the Investigator produces
    a fix, the fix is applied and CI is retried.
    """

    name = "INTEGRATE"

    def __init__(self, worktree_manager: Any = None, *, investigator_budget: int = 2) -> None:
        self._wm = worktree_manager
        self._investigator_budget = investigator_budget

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Merge grandchild → dirty, tick pipeline."""
        if not self._wm:
            return StepResult(status="OK")

        # 1. Merge slice → layer dirty
        merge_result = self._wm.merge_slice_to_dirty(ctx.layer, ctx.slice_id)
        if not merge_result.success:
            ticket = DemotionTicket(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                source="TEST_FAILURE",
                target_layer="L1",
                severity="BLOCKER",
                diagnosis=f"Merge conflict: {merge_result.error}",
            )
            return StepResult(
                status="RETRY",
                emitted_tickets=[ticket],
                error=merge_result.error,
            )

        # 2. Tick CI pipeline
        tick_result = self._wm.tick_pipeline(active_layer=ctx.layer)

        if not tick_result.demotion_tickets:
            return StepResult(status="OK")

        # 3. CI failed — try Investigator before demotion
        investigator_result = self._try_investigator(ctx, tick_result)
        if investigator_result and investigator_result.get("fixed"):
            # Re-tick pipeline after fix
            tick_result = self._wm.tick_pipeline(active_layer=ctx.layer)
            if not tick_result.demotion_tickets:
                return StepResult(status="OK")

        # 4. Investigator failed or didn't fix — emit demotion tickets
        tickets = []
        for dt_ref in tick_result.demotion_tickets:
            logger.warning("Pipeline demotion: %s", dt_ref)
            tickets.append(
                DemotionTicket(
                    run_id=ctx.run_id,
                    slice_id=ctx.slice_id,
                    source="TEST_FAILURE",
                    target_layer="L1",
                    severity="BLOCKER",
                    diagnosis=f"CI failure after integration: {dt_ref}",
                )
            )

        if tickets:
            return StepResult(
                status="RETRY",
                emitted_tickets=tickets,
                error=f"CI pipeline failed with {len(tickets)} demotion(s)",
            )

        return StepResult(status="OK")

    def _try_investigator(self, ctx: SliceContext, tick_result: Any) -> dict[str, Any] | None:
        """Invoke Investigator agent to fix CI failures.

        Args:
            ctx: Slice context.
            tick_result: The failing pipeline tick result.

        Returns:
            Dict with ``fixed`` bool, or None if investigator unavailable.
        """
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else None
        if not workspace:
            return None

        for attempt in range(1, self._investigator_budget + 1):
            logger.info(
                "Investigator attempt %d/%d for slice '%s'",
                attempt,
                self._investigator_budget,
                ctx.slice_id,
            )
            try:
                import json

                from spec_manager.core.agent_utils import run_agent
                from spec_manager.core.json_extraction import _extract_json_payload
                from spec_manager.refinement.formats import _strip_code_fences

                prompt = (
                    "## TASK\n"
                    "CI tests failed after integrating a slice. Investigate and fix.\n"
                    "You must respect layer constraints:\n"
                    f"- Current layer: {ctx.layer}\n"
                    "- L1: may change function bodies\n"
                    "- L2: wiring only, no new logic\n"
                    "- L3: refactor only, no behavior change\n\n"
                    'Return JSON: {"fixed": true/false, "patch": "...", '
                    '"root_cause": "...", "evidence": "..."}\n\n'
                    f"Failing tickets: {tick_result.demotion_tickets[:5]}\n"
                    f"Slice: {ctx.slice_id}\n"
                )

                output = run_agent(
                    agent_name="pdd-investigator",
                    prompt=prompt,
                    workspace=workspace,
                )
                cleaned = _strip_code_fences(output)
                data = json.loads(_extract_json_payload(cleaned))

                if data.get("fixed"):
                    logger.info(
                        "Investigator fixed CI failure (attempt %d): %s",
                        attempt,
                        data.get("root_cause", "unknown"),
                    )
                    return {"fixed": True, "attempt": attempt, "data": data}

            except Exception as exc:
                logger.debug("Investigator attempt %d failed: %s", attempt, exc)

        logger.info(
            "Investigator exhausted budget (%d attempts) for slice '%s'",
            self._investigator_budget,
            ctx.slice_id,
        )
        return {"fixed": False}


class VerifyStep:
    """Run layer-aware post-integration verification.

    Per layer:
    - L1: cross-library connectivity (P6) + lineage (P7)
    - L2: pin consumption + topology + no inlined logic + manifest drift
    - L3: reviewer closure + no-logic-change + drift

    All layers:
    - Governance/oversight check (fail closed on FAIL)
    - Finding → DemotionTicket triage
    """

    name = "VERIFY"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Run governance checks + layer-specific verification."""
        import json
        import time

        from spec_manager.orchestration.evidence import Finding

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        findings: list[dict[str, Any]] = []
        notes: dict[str, Any] = {
            "layer": ctx.layer,
            "slice_id": ctx.slice_id,
            "timestamp": time.time(),
            "findings": [],
        }

        def emit_finding(**kw: Any) -> None:
            f = Finding(
                dimension=kw.get("dimension", "VERIFY"),
                category=kw.get("category", "drift"),
                severity=kw.get("severity", "MINOR"),
                required_change_type=kw.get("required_change_type", "refactor_only"),
                location=kw.get("location", {}),
                evidence=kw.get("evidence", ""),
                suggested_fix=kw.get("suggested_fix", ""),
                confidence=kw.get("confidence", 0.7),
                tags=kw.get("tags", []),
            )
            findings.append(f.to_dict())

        def triage_to_ticket(f: dict[str, Any]) -> DemotionTicket | None:
            required = f.get("required_change_type", "refactor_only")
            cat = f.get("category", "style")
            sev = f.get("severity", "MINOR")

            if cat == "governance":
                target = ctx.layer.upper()
            elif required == "behavior_change":
                target = "L1"
            elif cat == "architecture" or required == "wiring_only":
                target = "L2"
            else:
                return None

            loc = f.get("location") or {}
            failing_files = [loc["file"]] if loc.get("file") else []

            return DemotionTicket(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                source="VERIFY",
                origin_layer=ctx.layer.upper(),
                target_layer=target,
                severity=sev if sev in ("BLOCKER", "MAJOR", "MINOR") else "MINOR",
                diagnosis=f.get("evidence", "")[:500] or f.get("dimension", "Verification finding"),
                failing_files=failing_files,
            )

        def run_agent_json(agent_name: str, prompt: str) -> dict[str, Any]:
            try:
                from spec_manager.core.agent_utils import run_agent
                from spec_manager.core.json_extraction import (
                    _extract_json_payload,
                )
                from spec_manager.refinement.formats import _strip_code_fences

                out = run_agent(
                    agent_name=agent_name,
                    prompt=prompt,
                    workspace=workspace,
                )
                cleaned = _strip_code_fences(out)
                return json.loads(_extract_json_payload(cleaned))
            except Exception:
                # C03: Surface errors — LLM agent failure needs diagnosis
                logger.warning(
                    "Agent %s failed for verify step — returning empty",
                    agent_name,
                    exc_info=True,
                )
                return {}

        # 0) Governance / oversight
        oversight_prompt = (
            "## TASK\n"
            "Act as Pipeline Oversight Enforcer for this slice.\n"
            "Check: missing receipts, undocumented deviations, decision injection patterns.\n"
            "Return JSON: "
            '{"status": "PASS"|"WARN"|"FAIL", "findings": [{"severity": ..., "evidence": ..., '
            '"location": {}, "required_change_type": ...}]}\n\n'
            f"Slice: {ctx.slice_id}\nLayer: {ctx.layer}\n"
        )
        oversight = run_agent_json("pipeline-oversight-enforcer", oversight_prompt)
        if oversight:
            status = oversight.get("status", "PASS")
            for of in oversight.get("findings", []) or []:
                emit_finding(
                    dimension="GOVERNANCE",
                    category="governance",
                    severity=of.get("severity", "MAJOR"),
                    required_change_type=of.get("required_change_type", "refactor_only"),
                    location=of.get("location", {}),
                    evidence=of.get("evidence", "Oversight finding"),
                    confidence=0.8,
                )
            if status == "FAIL":
                tickets = [t for t in (triage_to_ticket(f) for f in findings) if t]
                notes["findings"] = findings
                iteration_dir = bundle.iter_dir(workspace)
                iteration_dir.mkdir(parents=True, exist_ok=True)
                notes_path = iteration_dir / "verify.notes.json"
                notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
                return StepResult(
                    status="RETRY",
                    emitted_tickets=tickets,
                    notes_path=str(notes_path),
                    error="VERIFY: governance FAIL",
                )

        # 1) Layer-specific verification
        if ctx.layer == "l1":
            prompt = (
                "## TASK\n"
                "Verify L1 post-integration correctness:\n"
                "1) Cross-library connectivity (P6): promoted interfaces connect; no orphan "
                "dependencies.\n"
                "2) Lineage (P7): architecture-facing surfaces trace back to spec/atoms; flag "
                "orphans.\n"
                'Return JSON: {"findings": [...]} with required_change_type in {'
                "refactor_only, wiring_only, behavior_change}.\n\n"
                "Provide file locations when possible.\n"
            )
            data = run_agent_json("pdd-l1-verifier", prompt)
            for f in data.get("findings", []) or []:
                emit_finding(**f)

        elif ctx.layer == "l2":
            prompt = (
                "## TASK\n"
                "Verify L2 architecture post-integration:\n"
                "- Pin consumption coverage (no unaccounted promoted pins)\n"
                "- Topology connectivity (no orphan components)\n"
                "- No inlined business logic in architecture\n"
                "- Conformance to component manifest / intended topology\n"
                'Return JSON: {"findings": [...]}.\n'
            )
            data = run_agent_json("pdd-l2-verifier", prompt)
            for f in data.get("findings", []) or []:
                emit_finding(**f)

        elif ctx.layer == "l3":
            prompt = (
                "## TASK\n"
                "Verify L3 clean-code post-integration:\n"
                "- All quality findings resolved (closure)\n"
                "- Changes are behavior-preserving (no logic change)\n"
                "- No architectural boundary violations introduced\n"
                "- No unplanned functionality (drift)\n"
                'Return JSON: {"findings": [...]}.\n'
            )
            data = run_agent_json("pdd-l3-verifier", prompt)
            for f in data.get("findings", []) or []:
                emit_finding(**f)

        # 2) Convert to demotion tickets
        tickets = [t for t in (triage_to_ticket(f) for f in findings) if t]

        # Persist verify notes
        notes["findings"] = findings
        iteration_dir = bundle.iter_dir(workspace)
        iteration_dir.mkdir(parents=True, exist_ok=True)
        notes_path = iteration_dir / "verify.notes.json"
        notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")

        # Decide pass/fail
        has_blocker = any(f.get("severity") == "BLOCKER" for f in findings)
        has_major = any(f.get("severity") == "MAJOR" for f in findings)

        if has_blocker or (tickets and has_major):
            return StepResult(
                status="RETRY",
                emitted_tickets=tickets,
                notes_path=str(notes_path),
                error=f"VERIFY: {len(findings)} findings ({len(tickets)} demotions)",
            )

        return StepResult(status="OK", notes_path=str(notes_path))


class AlignStep:
    """POWER alignment check: detect drift and reward hacking.

    Compares the current implementation against the original spec
    (charter/constraints) to ensure the system hasn't drifted from
    its intended purpose or started optimizing for proxy metrics.

    Runs after VERIFY, before termination check.  High-severity
    findings emit DemotionTickets.
    """

    name = "ALIGN"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Run POWER alignment on the slice."""
        from spec_manager.core.language import source_rglob

        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            return StepResult(status="OK")

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        # Gather charter/constraints and current code for alignment comparison
        charter_files: list[str] = []
        code_summaries: list[str] = []

        # Look for charter in library structure
        libraries_dir = workspace / "libraries"
        if libraries_dir.exists():
            for lib_dir in sorted(libraries_dir.iterdir()):
                if not lib_dir.is_dir():
                    continue
                charter_path = lib_dir / "charter.md"
                if charter_path.exists():
                    charter_files.append(
                        f"## {lib_dir.name}\n\n" + charter_path.read_text(encoding="utf-8")
                    )
                constraints_path = lib_dir / "constraints.md"
                if constraints_path.exists():
                    charter_files.append(
                        f"## {lib_dir.name} constraints\n\n"
                        + constraints_path.read_text(encoding="utf-8")
                    )

        # Gather current code from slice
        for py_file in source_rglob(slice_root):
            if not py_file.is_file():
                continue
            if any(part.startswith(".") for part in py_file.parts):
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                # Include first 100 lines as summary
                lines = content.split("\n")[:100]
                code_summaries.append(
                    f"### {py_file.relative_to(slice_root)}\n```python\n"
                    + "\n".join(lines)
                    + "\n```"
                )
            except (OSError, UnicodeDecodeError):
                continue

        if not charter_files or not code_summaries:
            # No charter to check against — skip
            return StepResult(status="OK")

        try:
            import json

            from spec_manager.core.agent_utils import run_agent
            from spec_manager.refinement.formats import (
                _extract_json_payload,
                _strip_code_fences,
            )

            prompt = (
                "## TASK\n\n"
                "Check the implementation against the original charter/constraints.\n"
                "Detect requirement drift and reward hacking.\n"
                "Return JSON with keys: drift_findings, reward_hacking_findings.\n"
                "Each finding should have: severity (HIGH/MEDIUM/LOW), description, file.\n\n"
                "## CHARTER/CONSTRAINTS\n\n"
                + "\n\n---\n\n".join(charter_files)
                + "\n\n## CURRENT CODE\n\n"
                + "\n\n".join(code_summaries[:20])  # limit context
            )

            output = run_agent(
                agent_name="opus-alignment-checker",
                prompt=prompt,
                workspace=workspace,
            )
            cleaned = _strip_code_fences(output)
            data = json.loads(_extract_json_payload(cleaned))

            drift = data.get("drift_findings", [])
            reward = data.get("reward_hacking_findings", [])

            # Emit DemotionTickets for high-severity findings
            tickets: list[DemotionTicket] = []
            for finding in drift + reward:
                severity = finding.get("severity", "LOW")
                if severity == "HIGH":
                    tickets.append(
                        DemotionTicket(
                            run_id=ctx.run_id,
                            slice_id=ctx.slice_id,
                            source="REVIEW",
                            target_layer="L1",
                            origin_layer=ctx.layer.upper(),
                            severity="BLOCKER",
                            diagnosis=finding.get("description", "POWER alignment drift"),
                            failing_files=[finding.get("file", "")],
                        )
                    )

            if tickets:
                return StepResult(
                    status="RETRY",
                    emitted_tickets=tickets,
                    error=f"POWER alignment: {len(tickets)} high-severity findings",
                )

        except Exception as exc:
            logger.warning("POWER alignment check failed: %s", exc, exc_info=True)
            return StepResult(status="RETRY", error=f"POWER alignment check failed: {exc}")


# ------------------------------------------------------------------
# Default step sequence
# ------------------------------------------------------------------

DEFAULT_STEPS: list[type] = [
    CollectBaselineStep,
    GapExplorationStep,
    PlanStep,
    ImplementStep,
    CoordinateStep,
    PromoteStep,
    IntegrateStep,
    VerifyStep,
    AlignStep,
]


# ------------------------------------------------------------------
# PromotionLoop
# ------------------------------------------------------------------


class PromotionLoop:
    """Per-slice iterative promotion loop.

    Replaces the sequential P0-P10 pipeline with a convergence loop
    that runs until all gaps are closed and all atoms promoted.

    Args:
        worktree_manager: Multi-layer worktree manager.
        workspace_root: Root of the repository.
        demotion_manager: Handles applying demotion tickets.
        steps: Custom step sequence (defaults to all steps).
    """

    def __init__(
        self,
        worktree_manager: Any = None,
        workspace_root: Path = Path("."),
        demotion_manager: DemotionManager | None = None,
        steps: list[Any] | None = None,
        planner: Any = None,
    ) -> None:
        self._wm = worktree_manager
        self._workspace_root = workspace_root
        self._dm = demotion_manager or DemotionManager(workspace_root)
        self._planner = planner

        # Build step instances
        if steps is not None:
            self._steps = steps
        else:
            self._steps = []
            for step_cls in DEFAULT_STEPS:
                if step_cls is IntegrateStep:
                    self._steps.append(step_cls(worktree_manager=self._wm))
                elif step_cls in (PlanStep, CoordinateStep):
                    self._steps.append(step_cls(planner=self._planner))
                else:
                    self._steps.append(step_cls())

    def run_slice(
        self,
        slice_ref: SliceRef,
        run_context: RunContext,
    ) -> SliceResult:
        """Run the promotion loop on a single slice until convergence.

        Args:
            slice_ref: The slice to process.
            run_context: Run-scoped configuration.

        Returns:
            SliceResult with final status.
        """
        ctx = SliceContext(
            slice_id=slice_ref.slice_id,
            slice_root=slice_ref.worktree_path,
            layer=slice_ref.layer,
            run_id=run_context.run_id,
            mode=run_context.mode,
            workspace_root=run_context.workspace_root,
            config=run_context.config,
        )

        # Set dirty/clean parent paths if worktree manager available
        if self._wm:
            dirty = self._wm._layer_worktrees.get(ctx.layer, {}).get("dirty")
            clean = self._wm._layer_worktrees.get(ctx.layer, {}).get("clean")
            if dirty:
                ctx.dirty_parent_root = str(dirty)
            if clean:
                ctx.clean_sibling_root = str(clean)

        # Layer-specific iteration limit
        max_iters = run_context.max_iterations_by_layer.get(
            slice_ref.layer, run_context.max_iterations
        )

        all_tickets: list[DemotionTicket] = []
        iteration = 0
        waiting_iterations = 0

        # Stagnation detection: track gap counts over iterations.
        # Uses a sliding window — if min gap count over the last N iterations
        # hasn't improved compared to the N iterations before that, it's stagnated.
        # WAITING iterations are excluded from stagnation detection.
        gap_history: list[int] = []
        stagnation_window = 3

        # Per-ticket retry budget: track (failing_files_key, gate) → count
        retry_tracker: dict[tuple[str, str], int] = {}
        retry_budget = 3

        bundle: EvidenceBundle | None = None

        while iteration < max_iters:
            iteration += 1
            logger.info("=== Slice '%s' iteration %d/%d ===", ctx.slice_id, iteration, max_iters)

            bundle = EvidenceBundle(
                run_id=run_context.run_id,
                slice_id=slice_ref.slice_id,
                iteration=iteration,
                mode=run_context.mode,
                workspace_root=run_context.workspace_root,
                slice_root=slice_ref.worktree_path,
            )

            retry = False
            waiting = False

            for step in self._steps:
                logger.debug("Running step: %s", step.name)
                result = step.run(ctx, bundle)

                if result.emitted_tickets:
                    all_tickets.extend(result.emitted_tickets)
                    # Apply demotion tickets + track retries per unique failure pattern
                    seen_keys: set[tuple[str, str]] = set()
                    for ticket in result.emitted_tickets:
                        self._dm.apply(ticket, Path(ctx.slice_root))
                        files_key = (
                            ",".join(sorted(ticket.failing_files)) if ticket.failing_files else ""
                        )
                        gate_key = ticket.gate or ticket.source or ""
                        tracker_key = (files_key, gate_key)
                        seen_keys.add(tracker_key)

                    # Increment once per unique pattern per iteration (not per ticket)
                    for tracker_key in seen_keys:
                        retry_tracker[tracker_key] = retry_tracker.get(tracker_key, 0) + 1
                        if retry_tracker[tracker_key] > retry_budget:
                            logger.warning(
                                "Slice '%s': per-ticket retry budget exceeded "
                                "for (%s, %s) — escalating",
                                ctx.slice_id,
                                tracker_key[0],
                                tracker_key[1],
                            )
                            return SliceResult(
                                slice_id=ctx.slice_id,
                                status="STAGNATED",
                                iterations=iteration,
                                remaining_gaps=len(bundle.gaps.open_gaps),
                                demotion_tickets=all_tickets,
                                error=f"Per-ticket retry budget exceeded for gate={tracker_key[1]}",
                            )

                if result.status == "WAITING":
                    # Slice needs coordination — save bundle and return WAITING
                    waiting = True
                    break

                if result.status == "BLOCKED":
                    # Slice is blocked — return with blocked status
                    questions = []
                    for event in bundle.implementation.under_spec_events:
                        if q := event.get("question"):
                            questions.append(q)
                    return SliceResult(
                        slice_id=ctx.slice_id,
                        status="BLOCKED",
                        iterations=iteration,
                        demotion_tickets=all_tickets,
                        blocked_questions=questions,
                    )

                if result.status == "RETRY":
                    # A gate/test/merge failed — restart iteration
                    retry = True
                    break

                if result.status == "FAIL":
                    return SliceResult(
                        slice_id=ctx.slice_id,
                        status="FAILED",
                        iterations=iteration,
                        demotion_tickets=all_tickets,
                        error=result.error,
                    )

            # Handle WAITING: save bundle and return to scheduler
            if waiting:
                waiting_iterations += 1
                bundle.save(Path(run_context.workspace_root))
                # Collect pending signal info from bundle
                pending = [
                    {"question": e.get("question", ""), "kind": e.get("kind", "")}
                    for e in (bundle.implementation.under_spec_events or [])
                ]
                return SliceResult(
                    slice_id=ctx.slice_id,
                    status="WAITING",
                    iterations=iteration,
                    remaining_gaps=len(bundle.gaps.open_gaps),
                    demotion_tickets=all_tickets,
                    pending_signals=pending,
                    wake_count=waiting_iterations,
                )

            # Stagnation detection runs on EVERY non-WAITING iteration (including retries).
            # Uses sliding window: compare min(recent window) vs min(previous window).
            # If the recent window minimum hasn't improved, the slice is stagnated.
            remaining = len(bundle.gaps.open_gaps)
            gap_history.append(remaining)

            if len(gap_history) >= 2 * stagnation_window:
                prev_window = gap_history[-(2 * stagnation_window) : -stagnation_window]
                recent_window = gap_history[-stagnation_window:]
                if min(recent_window) >= min(prev_window):
                    logger.warning(
                        "Slice '%s': stagnation detected — min gaps not improving "
                        "(recent=%d, previous=%d, window=%d)",
                        ctx.slice_id,
                        min(recent_window),
                        min(prev_window),
                        stagnation_window,
                    )
                    bundle.save(Path(run_context.workspace_root))
                    return SliceResult(
                        slice_id=ctx.slice_id,
                        status="STAGNATED",
                        iterations=iteration,
                        remaining_gaps=remaining,
                        demotion_tickets=all_tickets,
                        error=(
                            f"Stagnation: min gaps not improving for {stagnation_window} iterations"
                        ),
                    )

            if retry:
                # Save bundle at end of iteration even on retry for inspectability
                bundle.save(Path(run_context.workspace_root))
                continue

            # Check termination
            if remaining == 0:
                bundle.status = "COMPLETE"
                bundle.save(Path(run_context.workspace_root))
                return SliceResult(
                    slice_id=ctx.slice_id,
                    status="COMPLETE",
                    iterations=iteration,
                    remaining_gaps=0,
                    demotion_tickets=all_tickets,
                )

            # Still gaps — loop
            logger.info(
                "Slice '%s': %d gaps remaining, continuing",
                ctx.slice_id,
                remaining,
            )

        # Max iterations reached
        return SliceResult(
            slice_id=ctx.slice_id,
            status="MAX_ITERATIONS",
            iterations=iteration,
            remaining_gaps=len(bundle.gaps.open_gaps) if bundle else 0,
            demotion_tickets=all_tickets,
        )

    def run_slices(
        self,
        slice_refs: list[SliceRef],
        run_context: RunContext,
    ) -> list[SliceResult]:
        """Run the promotion loop on multiple slices sequentially.

        For parallel execution, use ReactivePromotionScheduler instead.

        Args:
            slice_refs: Slices to process.
            run_context: Run-scoped configuration.

        Returns:
            List of SliceResults.
        """
        results = []
        for ref in slice_refs:
            result = self.run_slice(ref, run_context)
            results.append(result)

            if result.status == "FAILED":
                logger.error("Slice '%s' failed: %s", ref.slice_id, result.error)
                # Continue with other slices rather than aborting

        return results
