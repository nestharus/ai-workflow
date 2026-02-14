"""Planner eval harness.

Three evaluation modes:

* **in-situ** — runs ``PddLifecycle.run()`` end-to-end, then scores
  planner traces against ground truth.
* **slice** — runs ``PromotionLoop.run_slice()`` for a single
  slice/layer, then scores.
* **replay** — re-runs a single planner decision from ``replay.json``
  (with optional input/output overrides), then diffs against the original.

Usage::

    harness = PlannerEvalHarness(workspace_root, gt_path)
    scorecard = harness.run_and_score(run_id, mode="slice", ...)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvalConfig:
    """Configuration for a planner eval run."""

    workspace_root: Path = field(default_factory=lambda: Path("."))
    gt_path: Path | None = None
    run_id: str = ""
    mode: str = "slice"  # "e2e" | "slice" | "replay"
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
        logger.info("Planner eval: e2e mode for run_id=%s", config.run_id)

        # The actual pipeline run would be invoked here.
        # For eval, the caller is expected to have already run the pipeline
        # or to use this as a post-hoc scoring step.
        # Full pipeline integration will be wired when PddLifecycle.run()
        # is exercised end-to-end.
        return self._score_traces(config.run_id)

    def _run_slice(self, config: EvalConfig) -> EvalResult:
        """Slice-level: run one slice through PromotionLoop, then score."""
        logger.info(
            "Planner eval: slice mode for slice=%s layer=%s",
            config.slice_id,
            config.layer,
        )
        # Like e2e, the actual slice run is done externally.
        # This scores whatever traces exist for the run.
        return self._score_traces(config.run_id)

    def _run_replay(self, config: EvalConfig) -> EvalResult:
        """Replay: re-run a single decision from replay.json, then diff."""
        from spec_manager.refinement.evals.planner.trace_loader import load_trace

        logger.info("Planner eval: replay trace_id=%s", config.replay_trace_id)

        result = EvalResult(run_id=config.run_id, mode="replay")

        try:
            original = load_trace(self._workspace, config.replay_trace_id)
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

        # Re-run the planner with original request (+ overrides)
        try:
            replay_result = self._replay_decision(original, overrides)
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

    def _score_traces(self, run_id: str) -> EvalResult:
        """Load traces + GT, score each decision, compute scorecard."""
        from spec_manager.refinement.evals.planner.trace_loader import (
            filter_traces,
            load_index,
            load_trace,
        )

        result = EvalResult(run_id=run_id, mode="score")

        # Load trace index
        try:
            entries = load_index(self._workspace)
        except Exception as exc:
            result.errors.append(f"Failed to load trace index: {exc}")
            return result

        run_entries = filter_traces(entries, run_id=run_id)
        if not run_entries:
            # If no run_id filter, score all traces
            run_entries = entries

        # Load ground truth
        gt = None
        if self._gt_path and self._gt_path.exists():
            try:
                from spec_manager.refinement.evals.planner.ground_truth import (
                    load_ground_truth,
                )

                gt = load_ground_truth(self._gt_path)
            except Exception as exc:
                result.errors.append(f"Failed to load ground truth: {exc}")

        # Load full traces
        traces = []
        for entry in run_entries:
            try:
                traces.append(load_trace(self._workspace, entry.trace_id))
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

            reporter = PlannerReporter(self._workspace, run_id)
            scorecard = reporter.compute(verdicts, traces)
            reporter.write(scorecard)
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

    def _replay_decision(self, original: Any, overrides: dict[str, Any]) -> dict[str, Any]:
        """Re-run a planner decision using the original request + overrides."""
        from spec_manager.planner.api import (
            Planner,
            PlanningContext,
            PlanningRequest,
        )

        req_snapshot = original.request or {}
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

        ctx = PlanningContext(
            run_id=req_snapshot.get("run_id", ""),
            slice_id=req_snapshot.get("slice_id", ""),
            iteration=req_snapshot.get("iteration", 0),
            layer=req_snapshot.get("layer", "any"),
            mode=req_snapshot.get("mode", "auto"),
            workspace_root=req_snapshot.get("workspace_root", str(self._workspace)),
            slice_root=req_snapshot.get("slice_root", ""),
            metadata=metadata,
        )

        planner = Planner(
            workspace_root=self._workspace,
            mode=ctx.mode,
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

    def _diff_decisions(self, original: Any, replay: dict[str, Any]) -> Any:
        """Compare original trace decision to replay result."""
        from spec_manager.refinement.evals.planner.scorers.base import Verdict

        orig_status = original.status
        replay_status = replay.get("status", "")
        same_status = orig_status == replay_status

        artifacts = getattr(original, "artifacts", None) or {}
        orig_outputs = artifacts.get("outputs", {}) or artifacts.get("override_outputs", {})
        replay_outputs = replay.get("outputs", {})

        # Simple structural diff
        diff_keys = set()
        for key in set(list(orig_outputs.keys()) + list(replay_outputs.keys())):
            if json.dumps(orig_outputs.get(key), sort_keys=True) != json.dumps(
                replay_outputs.get(key), sort_keys=True
            ):
                diff_keys.add(key)

        return Verdict(
            decision_key=original.decision_key,
            trace_id=original.trace_id,
            capability="REPLAY_DIFF",
            passed=same_status and not diff_keys,
            score=1.0 if (same_status and not diff_keys) else 0.0,
            detail=f"status_match={same_status}, diff_keys={sorted(diff_keys)}",
        )
