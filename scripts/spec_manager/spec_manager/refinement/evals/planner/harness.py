"""Planner eval harness.

Four evaluation modes:

* **e2e** — run ``PddLifecycle.run()`` in-situ, then score.
* **slice** — run ``PromotionLoop.run_slice()`` for one slice/layer, then score.
* **replay** — re-run one decision from persisted replay artifacts.
* **shadow** — run e2e candidate planner, then replay each decision with an oracle.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvalConfig:
    """Configuration for a planner eval run."""

    workspace_root: Path = field(default_factory=lambda: Path("."))
    gt_path: Path | None = None
    run_id: str = ""
    mode: str = "e2e"  # "e2e" | "slice" | "replay" | "shadow"
    fixture: str = ""
    fixture_root: Path | None = None
    model_config: str = ""
    shadow_model_config: str = ""
    # Slice-level config
    slice_id: str = ""
    layer: str = ""
    # Replay config
    replay_trace_id: str = ""
    override_path: Path | None = None


@dataclass
class EvalResult:
    """Result of a planner eval run."""

    run_id: str = ""
    mode: str = ""
    scorecard: Any = None  # PlannerScorecard
    verdicts: list[Any] = field(default_factory=list)  # list[Verdict]
    traces_evaluated: int = 0
    gt_cases_matched: int = 0
    gt_cases_unmatched: int = 0
    errors: list[str] = field(default_factory=list)


def _is_relative_to(path: Path, root: Path) -> bool:
    """Return True when *path* is within *root*."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _sha256_file(path: Path) -> str:
    """Return SHA-256 hex digest for a file path."""
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class PlannerEvalHarness:
    """Orchestrates planner evaluation across modes.

    Parameters
    ----------
    workspace_root:
        Root of the PDD workspace (where traces are stored).
    gt_path:
        Path to the planner ground truth YAML file.
    """

    def __init__(
        self,
        workspace_root: Path,
        gt_path: Path | None = None,
    ) -> None:
        self._workspace = workspace_root
        self._gt_path = gt_path

    def run_and_score(self, config: EvalConfig) -> EvalResult:
        """Run evaluation and return scored results."""
        if config.mode == "e2e":
            return self._run_e2e(config)
        if config.mode == "slice":
            return self._run_slice(config)
        if config.mode == "replay":
            return self._run_replay(config)
        if config.mode == "shadow":
            return self._run_shadow(config)
        return EvalResult(
            run_id=config.run_id,
            mode=config.mode,
            errors=[f"Unknown mode: {config.mode!r}"],
        )

    def score_existing_traces(self, run_id: str) -> EvalResult:
        """Score traces from an already-completed run (no pipeline execution)."""
        return self._score_traces(run_id)

    # ------------------------------------------------------------------
    # Mode implementations
    # ------------------------------------------------------------------

    def _run_e2e(self, config: EvalConfig) -> EvalResult:
        """In-situ: run full PddLifecycle.run(), then score traces."""
        try:
            run_id, workspace_root = self._execute_e2e_pipeline(config)
        except Exception as exc:
            return EvalResult(run_id=config.run_id, mode="e2e", errors=[str(exc)])

        scored = self._score_traces(
            run_id,
            workspace_root=workspace_root,
            gt_path=config.gt_path,
            mode="e2e",
        )
        scored.mode = "e2e"
        return scored

    def _run_slice(self, config: EvalConfig) -> EvalResult:
        """Slice-level: run one slice through PromotionLoop, then score."""
        if not config.layer or not config.slice_id:
            return EvalResult(
                run_id=config.run_id,
                mode="slice",
                errors=["Slice mode requires both --layer and --slice-id."],
            )

        logger.info(
            "Planner eval: slice mode for slice=%s layer=%s",
            config.slice_id,
            config.layer,
        )
        try:
            workspace_root, run_id = self._execute_slice(config)
            self._ensure_replay_snapshots(workspace_root, run_id)
        except Exception as exc:
            return EvalResult(run_id=config.run_id, mode="slice", errors=[str(exc)])

        scored = self._score_traces(
            run_id,
            workspace_root=workspace_root,
            gt_path=config.gt_path,
            mode="slice",
        )
        scored.mode = "slice"
        return scored

    def _run_shadow(self, config: EvalConfig) -> EvalResult:
        """Run in-situ candidate pipeline, then replay each decision with an oracle."""
        try:
            run_id, workspace_root = self._execute_e2e_pipeline(config)
        except Exception as exc:
            return EvalResult(run_id=config.run_id, mode="shadow", errors=[str(exc)])

        scored = self._score_traces(
            run_id,
            workspace_root=workspace_root,
            gt_path=config.gt_path,
            mode="shadow",
        )
        scored.mode = "shadow"
        shadow_errors = self._run_shadow_comparison(
            workspace_root=workspace_root,
            run_id=run_id,
            oracle_model_id=config.shadow_model_config.strip(),
        )
        scored.errors.extend(shadow_errors)
        return scored

    def _run_replay(self, config: EvalConfig) -> EvalResult:
        """Replay: re-run a single decision from replay.json, then diff."""
        from spec_manager.refinement.evals.planner.trace_loader import load_trace

        logger.info("Planner eval: replay trace_id=%s", config.replay_trace_id)

        result = EvalResult(run_id=config.run_id, mode="replay")
        if not config.replay_trace_id:
            result.errors.append("Replay mode requires --trace-id / replay_trace_id.")
            return result

        try:
            original = load_trace(config.workspace_root, config.replay_trace_id)
        except Exception as exc:
            result.errors.append(f"Failed to load trace: {exc}")
            return result

        # Load overrides if provided
        overrides: dict[str, Any] = {}
        if config.override_path and config.override_path.exists():
            try:
                overrides = self._load_overrides(config.override_path)
            except Exception as exc:
                result.errors.append(f"Failed to load overrides: {exc}")

        # Re-run the planner with original request (+ overrides), using only
        # materialized replay artifacts (never the live workspace state).
        try:
            with self._materialize_replay_workspace(config.workspace_root, original) as replay_root:
                replay_result = self._replay_decision(
                    original,
                    overrides,
                    workspace_root=replay_root,
                    model_id=config.model_config.strip(),
                )
            result.traces_evaluated = 1

            # Diff original vs replay
            diff = self._diff_decisions(original, replay_result)
            result.verdicts = [diff]
        except Exception as exc:
            result.errors.append(f"Replay failed: {exc}")

        return result

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_traces(
        self,
        run_id: str,
        *,
        workspace_root: Path | None = None,
        gt_path: Path | None = None,
        mode: str = "score",
    ) -> EvalResult:
        """Load traces + GT, score each decision, compute scorecard."""
        from spec_manager.refinement.evals.planner.trace_loader import (
            filter_traces,
            load_index,
            load_trace,
        )

        workspace = workspace_root or self._workspace
        result = EvalResult(run_id=run_id, mode=mode)

        # Load trace index
        try:
            entries = load_index(workspace)
        except Exception as exc:
            result.errors.append(f"Failed to load trace index: {exc}")
            return result

        run_entries = filter_traces(entries, run_id=run_id)
        if not run_entries:
            # If no run_id filter, score all traces
            run_entries = entries

        # Load ground truth
        gt = None
        effective_gt = gt_path or self._gt_path
        if effective_gt and effective_gt.exists():
            try:
                from spec_manager.refinement.evals.planner.ground_truth import (
                    load_ground_truth,
                )

                gt = load_ground_truth(effective_gt)
            except Exception as exc:
                result.errors.append(f"Failed to load ground truth: {exc}")

        # Load full traces
        traces = []
        for entry in run_entries:
            try:
                traces.append(load_trace(workspace, entry.trace_id))
            except Exception as exc:
                logger.warning("Failed to load trace %s: %s", entry.trace_id, exc)

        result.traces_evaluated = len(traces)

        # Score against GT
        verdicts = []
        if gt is not None:
            verdicts = self._evaluate_against_gt(traces, gt)
            matched_keys = {v.decision_key for v in verdicts if getattr(v, "decision_key", "")}
            result.gt_cases_matched = len(matched_keys)
            result.gt_cases_unmatched = max(len(gt.cases) - result.gt_cases_matched, 0)

        result.verdicts = verdicts

        # Compute scorecard
        try:
            from spec_manager.refinement.evals.planner.reporter import (
                PlannerReporter,
            )

            reporter = PlannerReporter(workspace, run_id)
            scorecard = reporter.compute(verdicts, traces)
            reporter.write(scorecard, traces=traces)
            result.scorecard = scorecard
        except Exception as exc:
            result.errors.append(f"Failed to compute scorecard: {exc}")

        return result

    def _evaluate_against_gt(self, traces: list[Any], gt: Any) -> list[Any]:
        """Score each trace against matching GT case."""
        from spec_manager.refinement.evals.planner.ground_truth import find_case
        from spec_manager.refinement.evals.planner.scorers.base import Verdict

        scorer_map = self._build_scorer_map()
        verdicts = []

        for trace in traces:
            gt_case = find_case(gt, trace.decision_key)
            if gt_case is None:
                # No GT for this decision — skip
                continue

            scorer = scorer_map.get(
                trace.decision_key.split(":")[1] if ":" in trace.decision_key else ""
            )
            if scorer is None:
                # Try capability from the trace
                cap = getattr(trace, "capability", "")
                if not cap and ":" in trace.decision_key:
                    cap = trace.decision_key.split(":")[1]
                scorer = scorer_map.get(cap)

            if scorer is None:
                verdicts.append(
                    Verdict(
                        decision_key=trace.decision_key,
                        trace_id=trace.trace_id,
                        capability=gt_case.capability,
                        passed=True,
                        detail="No scorer for capability",
                    )
                )
                continue

            verdict = scorer.score(trace, gt_case)
            if not getattr(verdict, "decision_key", ""):
                verdict.decision_key = trace.decision_key
            if not getattr(verdict, "trace_id", ""):
                verdict.trace_id = trace.trace_id
            if not getattr(verdict, "capability", ""):
                verdict.capability = gt_case.capability
            verdicts.append(verdict)

        return verdicts

    def _build_scorer_map(self) -> dict[str, Any]:
        """Build capability → scorer mapping."""
        from spec_manager.refinement.evals.planner.scorers.gap import GapScorer
        from spec_manager.refinement.evals.planner.scorers.integration_analysis import (
            IntegrationAnalysisScorer,
        )
        from spec_manager.refinement.evals.planner.scorers.plan import PlanScorer
        from spec_manager.refinement.evals.planner.scorers.resolve_signal import (
            ResolveSignalScorer,
        )
        from spec_manager.refinement.evals.planner.scorers.under_spec import (
            UnderSpecScorer,
        )

        return {
            "RESOLVE_SIGNAL": ResolveSignalScorer(),
            "GAP": GapScorer(),
            "PLAN": PlanScorer(),
            "UNDER_SPEC": UnderSpecScorer(),
            "INTEGRATION_ANALYSIS": IntegrationAnalysisScorer(),
        }

    # ------------------------------------------------------------------
    # Replay helpers
    # ------------------------------------------------------------------

    def _replay_decision(
        self,
        original: Any,
        overrides: dict[str, Any],
        *,
        workspace_root: Path,
        model_id: str = "",
    ) -> dict[str, Any]:
        """Re-run a planner decision using the original request + overrides."""
        from spec_manager.planner.api import (
            Planner,
            PlanningContext,
            PlanningRequest,
        )

        req_snapshot = self._request_snapshot_from_trace(original)
        inputs = dict(req_snapshot.get("inputs", {}) or {})
        input_overrides = overrides.get("inputs", {})
        if input_overrides:
            if not isinstance(input_overrides, dict):
                raise ValueError("Override field 'inputs' must be a mapping")
            inputs.update(input_overrides)

        metadata = req_snapshot.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        constraints_hint = req_snapshot.get("constraints_hint")
        if constraints_hint is not None and not isinstance(constraints_hint, dict):
            constraints_hint = None

        mapped_workspace_root, mapped_slice_root = self._mapped_context_roots(
            req_snapshot=req_snapshot,
            materialized_workspace_root=workspace_root,
        )

        ctx = PlanningContext(
            run_id=req_snapshot.get("run_id", ""),
            slice_id=req_snapshot.get("slice_id", ""),
            iteration=req_snapshot.get("iteration", 0),
            layer=req_snapshot.get("layer", "any"),
            mode=req_snapshot.get("mode", "auto"),
            workspace_root=mapped_workspace_root,
            slice_root=mapped_slice_root,
            metadata=metadata,
        )

        planner = Planner(
            workspace_root=workspace_root,
            mode=ctx.mode,
            model_id=model_id,
        )

        req = PlanningRequest(
            capability=req_snapshot.get("capability", "PLAN"),
            context=ctx,
            inputs=inputs,
            constraints_hint=constraints_hint,
        )

        result = planner.plan(req)
        replay_outputs = dict(result.outputs)
        output_overrides = overrides.get("outputs", {})
        if output_overrides:
            if not isinstance(output_overrides, dict):
                raise ValueError("Override field 'outputs' must be a mapping")
            replay_outputs.update(output_overrides)
        return {
            "trace_id": result.trace_id,
            "status": result.status,
            "outputs": replay_outputs,
        }

    @staticmethod
    def _request_snapshot_from_trace(trace: Any) -> dict[str, Any]:
        replay = getattr(trace, "replay", None)
        if isinstance(replay, dict):
            snapshot = replay.get("request_snapshot")
            if isinstance(snapshot, dict) and snapshot:
                return snapshot
        request = getattr(trace, "request", None)
        if isinstance(request, dict):
            return request
        return {}

    @staticmethod
    def _mapped_context_roots(
        *,
        req_snapshot: dict[str, Any],
        materialized_workspace_root: Path,
    ) -> tuple[str, str]:
        """Map original request roots to the materialized replay workspace."""
        raw_workspace = str(req_snapshot.get("workspace_root", "") or "")
        raw_slice = str(req_snapshot.get("slice_root", "") or "")
        original_workspace = Path(raw_workspace) if raw_workspace else None
        original_slice = Path(raw_slice) if raw_slice else None
        mapped_workspace = str(materialized_workspace_root)

        if original_slice is not None:
            if original_workspace is not None and _is_relative_to(
                original_slice, original_workspace
            ):
                rel = original_slice.resolve().relative_to(original_workspace.resolve())
                return mapped_workspace, str(materialized_workspace_root / rel)
            if original_slice.is_absolute():
                return mapped_workspace, str(materialized_workspace_root)
            return mapped_workspace, str(materialized_workspace_root / original_slice)

        return mapped_workspace, ""

    @staticmethod
    def _safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
        """Extract a zip archive safely into *dest_dir*."""
        with zipfile.ZipFile(zip_path, "r") as archive:
            for info in archive.infolist():
                rel = Path(info.filename)
                if rel.is_absolute():
                    raise ValueError(f"Snapshot zip contains absolute path: {rel}")
                target = (dest_dir / rel).resolve()
                if not _is_relative_to(target, dest_dir):
                    raise ValueError(f"Snapshot zip contains unsafe path: {rel}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    def _materialize_replay_files(
        self,
        *,
        workspace_root: Path,
        replay_payload: dict[str, Any],
    ) -> bool:
        """Materialize inline replay snapshot files if present."""
        snapshot_files = replay_payload.get("snapshot_files")
        if not isinstance(snapshot_files, dict) or not snapshot_files:
            return False

        for rel_raw, content in snapshot_files.items():
            rel_path = Path(str(rel_raw))
            if rel_path.is_absolute():
                raise ValueError(f"Inline snapshot file path must be relative: {rel_raw}")
            out_path = (workspace_root / rel_path).resolve()
            if not _is_relative_to(out_path, workspace_root):
                raise ValueError(f"Inline snapshot path escapes workspace: {rel_raw}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                out_path.write_text(content, encoding="utf-8")
            else:
                out_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        return True

    class _ReplayWorkspace:
        """Context manager that materializes replay artifacts in a temp workspace."""

        def __init__(self) -> None:
            self._tmp = tempfile.TemporaryDirectory(prefix="planner-replay-")
            self.root = Path(self._tmp.name) / "workspace"
            self.root.mkdir(parents=True, exist_ok=True)

        def __enter__(self) -> Path:
            return self.root

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            self._tmp.cleanup()

    def _materialize_replay_workspace(self, source_workspace: Path, trace: Any) -> _ReplayWorkspace:
        """Create a temp workspace from replay artifacts for one trace."""
        from spec_manager.refinement.evals.planner.trace_loader import trace_dir

        replay_payload = getattr(trace, "replay", None)
        if not isinstance(replay_payload, dict):
            raise TypeError("Trace replay.json is missing or malformed.")

        ctx = self._ReplayWorkspace()
        workspace = ctx.root
        # If anything below fails, close the tempdir immediately.
        try:
            materialized = False
            snapshot = replay_payload.get("snapshot")
            tdir = trace_dir(source_workspace, str(getattr(trace, "trace_id", "")))
            if isinstance(snapshot, dict):
                rel_zip = snapshot.get("zip_path")
                if isinstance(rel_zip, str) and rel_zip:
                    zip_path = (tdir / rel_zip).resolve()
                    if zip_path.is_file():
                        expected = str(snapshot.get("sha256", "") or "")
                        if expected and _sha256_file(zip_path) != expected:
                            raise ValueError(f"Snapshot hash mismatch for {zip_path}")
                        self._safe_extract_zip(zip_path, workspace)
                        materialized = True

            if not materialized and self._materialize_replay_files(
                workspace_root=workspace,
                replay_payload=replay_payload,
            ):
                materialized = True

            if not materialized:
                msg = (
                    "Replay artifacts are not self-contained "
                    "(missing snapshot zip or inline files)."
                )
                raise ValueError(msg)
            return ctx
        except Exception:
            ctx.__exit__(None, None, None)
            raise

    @staticmethod
    def _is_text_file(path: Path) -> bool:
        """Heuristic text-file check used for replay snapshot capture."""
        try:
            raw = path.read_bytes()
        except OSError:
            return False
        return b"\x00" not in raw

    def _collect_snapshot_files(
        self, workspace_root: Path, request_snapshot: dict[str, Any]
    ) -> list[Path]:
        """Collect a bounded set of files to snapshot for replay."""
        files: set[Path] = set()
        run_id = str(request_snapshot.get("run_id", "") or "")
        slice_root_raw = str(request_snapshot.get("slice_root", "") or "")

        # Primary scope: all text files under the slice root.
        if slice_root_raw:
            slice_root = Path(slice_root_raw)
            if (
                slice_root.exists()
                and slice_root.is_dir()
                and _is_relative_to(slice_root, workspace_root)
            ):
                for path in slice_root.rglob("*"):
                    if path.is_file() and self._is_text_file(path):
                        files.add(path)

        # Include key manifests and registries commonly read by planners.
        manifest_globs = (
            "*_manifest.yaml",
            "*_manifest.yml",
            "wiring.yaml",
            "wiring.yml",
            "*registry*.json",
            "*registry*.yaml",
            "*registry*.yml",
        )
        for pattern in manifest_globs:
            for path in workspace_root.rglob(pattern):
                if path.is_file() and self._is_text_file(path):
                    files.add(path)

        # Include run receipts to preserve decision-era quality context.
        if run_id:
            run_dir = workspace_root / ".pdd_runs" / run_id
            if run_dir.exists():
                for path in run_dir.rglob("*.json"):
                    if path.is_file() and self._is_text_file(path):
                        files.add(path)

        # Bound snapshot size to keep replay artifacts lightweight.
        limited: list[Path] = []
        for path in sorted(files):
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            limited.append(path)
            if len(limited) >= 1500:
                break
        return limited

    def _capture_snapshot_for_trace(self, workspace_root: Path, trace_id: str) -> None:
        """Capture replay snapshot zip and metadata for a trace when absent."""
        from spec_manager.refinement.evals.planner.trace_loader import load_trace, trace_dir

        trace = load_trace(workspace_root, trace_id)
        trace_path = trace_dir(workspace_root, trace_id)
        replay_path = trace_path / "replay.json"
        replay_payload = dict(getattr(trace, "replay", {}) or {})
        if not replay_payload:
            replay_payload = {
                "trace_id": trace_id,
                "request_snapshot": self._request_snapshot_from_trace(trace),
            }

        snapshot = replay_payload.get("snapshot")
        if isinstance(snapshot, dict):
            rel_zip = snapshot.get("zip_path")
            if isinstance(rel_zip, str) and (trace_path / rel_zip).exists():
                return

        request_snapshot = self._request_snapshot_from_trace(trace)
        files = self._collect_snapshot_files(workspace_root, request_snapshot)
        zip_rel = Path("artifacts") / "snapshot.zip"
        zip_path = trace_path / zip_rel
        zip_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                if not _is_relative_to(path, workspace_root):
                    continue
                rel = path.resolve().relative_to(workspace_root.resolve())
                archive.write(path, arcname=rel.as_posix())

        replay_payload["snapshot"] = {
            "zip_path": zip_rel.as_posix(),
            "sha256": _sha256_file(zip_path),
            "captured_files": len(files),
            "captured_at": datetime.now(tz=UTC).isoformat(),
            "source": "planner_eval_harness",
        }
        replay_payload["request_snapshot"] = request_snapshot
        replay_path.write_text(
            json.dumps(replay_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _ensure_replay_snapshots(self, workspace_root: Path, run_id: str) -> None:
        """Ensure each run trace has a persisted snapshot for self-contained replay."""
        from spec_manager.refinement.evals.planner.trace_loader import filter_traces, load_index

        entries = filter_traces(load_index(workspace_root), run_id=run_id)
        for entry in entries:
            try:
                self._capture_snapshot_for_trace(workspace_root, entry.trace_id)
            except Exception as exc:
                logger.warning(
                    "Could not capture replay snapshot for trace %s: %s", entry.trace_id, exc
                )

    def _resolved_run_id(self, config: EvalConfig) -> str:
        """Resolve run id, generating one when not provided."""
        if config.run_id.strip():
            return config.run_id.strip()
        fixture = config.fixture.strip() or "planner-fixture"
        ts = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")
        return f"planner-eval-{fixture}-{ts}"

    def _fixture_root(self, config: EvalConfig) -> Path:
        """Resolve fixture root path."""
        if config.fixture_root is not None:
            return config.fixture_root
        from spec_manager.core.project_root import resolve_from_root

        return resolve_from_root(
            "scripts", "spec_manager", "spec_manager", "refinement", "evals", "inputs", "fixtures"
        )

    def _prepare_fixture_workspace(self, config: EvalConfig) -> tuple[Any, Path, str]:
        """Initialize a workspace for fixture-backed planner evals."""
        from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator
        from spec_manager.refinement.workspace.manager import WorkspaceManager

        fixture = config.fixture.strip()
        if not fixture:
            raise ValueError("Fixture is required for in-situ modes (use --fixture).")

        fixtures_root = self._fixture_root(config)
        pdd_input = fixtures_root / f"{fixture}_pdd"
        phase0_output = fixtures_root / f"{fixture}_phase0_output"
        if not pdd_input.exists():
            raise FileNotFoundError(f"Fixture PDD input not found: {pdd_input}")
        if not phase0_output.exists():
            raise FileNotFoundError(f"Fixture Phase 0 output not found: {phase0_output}")

        run_id = self._resolved_run_id(config)
        manager = WorkspaceManager(run_id=run_id, input_folder=pdd_input)
        manager.initialize(force=True)
        PddOrchestrator(manager)._install_phase0_output(phase0_output)
        return manager, manager.workspace_path, run_id

    def _execute_e2e_pipeline(self, config: EvalConfig) -> tuple[str, Path]:
        """Execute the full lifecycle pipeline for the configured fixture."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager, workspace_root, run_id = self._prepare_fixture_workspace(config)
        logger.info("Planner eval: e2e mode run_id=%s fixture=%s", run_id, config.fixture)
        PddLifecycle(manager, mode="auto").run()
        self._ensure_replay_snapshots(workspace_root, run_id)
        return run_id, workspace_root

    def _execute_slice(self, config: EvalConfig) -> tuple[Path, str]:
        """Execute one PromotionLoop slice for fixture-backed eval."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle
        from spec_manager.orchestration.promotion_loop import PromotionLoop, RunContext

        manager, workspace_root, run_id = self._prepare_fixture_workspace(config)
        lifecycle = PddLifecycle(manager, mode="auto")
        layer = config.layer.lower()
        slice_refs = lifecycle._discover_slices(layer)
        target = next((ref for ref in slice_refs if ref.slice_id == config.slice_id), None)
        if target is None:
            known = ", ".join(sorted({ref.slice_id for ref in slice_refs}))
            raise ValueError(f"Slice '{config.slice_id}' not found for {layer}. Known: {known}")

        if not target.worktree_path:
            target.worktree_path = str(manager.structure.spec_snapshot_dir)

        run_context = RunContext(run_id=run_id, mode="auto", workspace_root=str(workspace_root))
        planner = lifecycle._build_planner()
        loop = PromotionLoop(workspace_root=workspace_root, planner=planner)
        loop.run_slice(target, run_context)
        return workspace_root, run_id

    def _run_shadow_comparison(
        self,
        *,
        workspace_root: Path,
        run_id: str,
        oracle_model_id: str,
    ) -> list[str]:
        """Replay each decision with an oracle planner and write shadow artifacts."""
        from spec_manager.refinement.evals.planner.trace_loader import (
            filter_traces,
            load_index,
            load_trace,
            trace_dir,
        )

        errors: list[str] = []
        entries = filter_traces(load_index(workspace_root), run_id=run_id)
        for entry in entries:
            try:
                original = load_trace(workspace_root, entry.trace_id)
                with self._materialize_replay_workspace(workspace_root, original) as replay_root:
                    oracle = self._replay_decision(
                        original,
                        overrides={},
                        workspace_root=replay_root,
                        model_id=oracle_model_id,
                    )
                    self._write_shadow_artifacts(
                        trace_dir=trace_dir(workspace_root, entry.trace_id),
                        original=original,
                        oracle=oracle,
                        oracle_workspace=replay_root,
                        oracle_model_id=oracle_model_id,
                    )
            except Exception as exc:
                errors.append(f"Shadow replay failed for {entry.trace_id}: {exc}")
        return errors

    def _write_shadow_artifacts(
        self,
        *,
        trace_dir: Path,
        original: Any,
        oracle: dict[str, Any],
        oracle_workspace: Path,
        oracle_model_id: str,
    ) -> None:
        """Write shadow_decision.json and optional shadow_calls.jsonl."""
        from spec_manager.refinement.evals.planner.trace_loader import load_trace

        orig_status = str(getattr(original, "status", "") or "")
        orig_outputs = self._outputs_for_trace(original)
        oracle_status = str(oracle.get("status", "") or "")
        oracle_outputs = dict(oracle.get("outputs", {}) or {})
        diff_keys = self._output_diff_keys(orig_outputs, oracle_outputs)

        payload = {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "oracle_model_id": oracle_model_id,
            "candidate": {
                "trace_id": str(getattr(original, "trace_id", "") or ""),
                "status": orig_status,
                "outputs": orig_outputs,
            },
            "oracle": {
                "trace_id": str(oracle.get("trace_id", "") or ""),
                "status": oracle_status,
                "outputs": oracle_outputs,
            },
            "comparison": {
                "status_match": orig_status == oracle_status,
                "output_diff_keys": diff_keys,
                "equivalent": orig_status == oracle_status and not diff_keys,
            },
        }
        (trace_dir / "shadow_decision.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        oracle_trace_id = str(oracle.get("trace_id", "") or "")
        if not oracle_trace_id:
            return
        try:
            oracle_trace = load_trace(oracle_workspace, oracle_trace_id)
        except Exception:
            return

        calls_path = trace_dir / "shadow_calls.jsonl"
        lines = [json.dumps(call, sort_keys=True) for call in oracle_trace.model_calls]
        calls_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    @staticmethod
    def _load_overrides(path: Path) -> dict[str, Any]:
        """Load replay overrides from JSON or YAML."""
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            try:
                import yaml
            except ImportError as exc:
                raise ValueError("YAML override parsing requires PyYAML") from exc
            parsed = yaml.safe_load(raw)

        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise TypeError("Override file must contain a mapping object")
        return parsed

    @staticmethod
    def _outputs_for_trace(trace: Any) -> dict[str, Any]:
        artifacts = getattr(trace, "artifacts", None) or {}
        outputs = artifacts.get("outputs")
        if isinstance(outputs, dict):
            return outputs
        override_outputs = artifacts.get("override_outputs")
        if isinstance(override_outputs, dict):
            return override_outputs
        return {}

    @staticmethod
    def _output_diff_keys(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
        diff: list[str] = []
        for key in sorted(set(list(left.keys()) + list(right.keys()))):
            if json.dumps(left.get(key), sort_keys=True) != json.dumps(
                right.get(key), sort_keys=True
            ):
                diff.append(key)
        return diff

    def _diff_decisions(self, original: Any, replay: dict[str, Any]) -> Any:
        """Compare original trace decision to replay result."""
        from spec_manager.refinement.evals.planner.scorers.base import Verdict

        orig_status = str(getattr(original, "status", "") or "")
        replay_status = replay.get("status", "")
        same_status = orig_status == replay_status

        orig_outputs = self._outputs_for_trace(original)
        replay_outputs = replay.get("outputs", {})

        diff_keys = self._output_diff_keys(orig_outputs, replay_outputs)

        return Verdict(
            decision_key=original.decision_key,
            trace_id=original.trace_id,
            capability="REPLAY_DIFF",
            passed=same_status and not diff_keys,
            score=1.0 if (same_status and not diff_keys) else 0.0,
            detail=f"status_match={same_status}, diff_keys={diff_keys}",
        )
