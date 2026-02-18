# TODO(single-layer): KEEP/EXTEND — Metrics module needs shape-aware metrics
#   (Sections 14.1-14.3): shape verifier pass rate, work item convergence rate,
#   per-phase iteration count, stagnation detection. Success criteria (Section 14.2):
#   verifier pass rate, convergence, iteration count. Failure criteria (Section 14.3):
#   stagnation, unbounded growth, shape drift, pin-caught issues escaping without
#   verifier replacement, LLM heuristic reliance for success declaration (must flag
#   as failure). Success criteria (Section 14.2): spec fidelity (QA/judge pass rate
#   >= baseline, no dropped requirements), complexity reduction (fewer gates, fewer
#   dispatch branches, pin/layer code deleted). Reduced thrash metric (Section 14.2):
#   fewer phase-local remediation retries / work-item churn than baseline. These
#   complement existing metrics.
# ALGORITHM(single-layer):
#   References: response3 Sections 14.2 and 14.3.
#   Data structures:
#     - SpecFidelityMetrics: {qa_judge_pass_rate: float, baseline_qa_judge_pass_rate: float, dropped_requirement_count: int, baseline_dropped_requirement_count: int, fidelity_delta: float}.
#     - ShapeEvaluationMetrics: {shape_verifier_pass_rate: float, work_item_convergence_rate: float, avg_iterations_to_close: float, stagnation_events: int, drift_open_count: int}.
#     - ComplexityReductionMetrics: {deleted_pin_modules: int, deleted_layer_branches: int, gate_count_delta: int, dispatch_branch_delta: int}.
#     - ThrashMetrics: {work_item_churn_ratio: float, requeue_count: int, phase_local_retries: int}.
#   Interface contracts:
#     - def compute_spec_fidelity_metrics(baseline: dict[str, Any], variant: dict[str, Any]) -> SpecFidelityMetrics
#       §14.2 success criterion #1: QA/judge pass rate >= baseline, no increase in dropped requirements.
#     - def compute_shape_metrics(run_payload: dict[str, Any]) -> ShapeEvaluationMetrics
#     - def compute_complexity_metrics(baseline: dict[str, Any], variant: dict[str, Any]) -> ComplexityReductionMetrics
#     - def compute_thrash_metrics(run_payload: dict[str, Any]) -> ThrashMetrics
#   Control flow:
#     1. Keep existing detail-capture and convergence scoring.
#     2. Add shape-aware calculations from verifier/work-item/per-phase-iteration artifacts.
#     3. Flag failure when heuristic-only completion marker appears without deterministic verifier/test evidence.
#   Error handling:
#     - Missing required artifacts returns metric object with zeroed values plus warning flags.
#   Integration points:
#     - Called by evals.runner A/B comparison reporting.
#   Test requirements:
#     - Correct pass-rate and convergence formulas.
#     - Failure-flag logic for stagnation/unbounded growth/heuristic reliance.
# IMPL(single-layer): Keep this module as the authoritative source for Section 14.2/14.3
# metric formulas; runner/report should consume computed fields rather than re-derive them.
# IMPL(single-layer): Existing detail-capture + convergence helpers remain baseline inputs;
# extend this file with SpecFidelityMetrics/ShapeEvaluationMetrics/ComplexityReductionMetrics/
# ThrashMetrics so A/B comparisons share one deterministic metrics surface.

"""Metrics computation for spec refinement evaluation.

Provides precision/recall scoring with fuzzy matching for NLP variation,
convergence analysis, and phase-level metrics aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, cast

from spec_manager.compliance.promotion.config import PhaseId


def _fuzzy_ratio(a: str, b: str) -> float:
    """Compute fuzzy similarity ratio between two strings.

    Uses max of SequenceMatcher ratio and token-containment score.
    Token containment checks what fraction of the shorter string's
    significant tokens (4+ chars) appear in the longer string, using
    4-character prefix matching for morphological tolerance (e.g.
    "writes"/"write", "issued"/"issues").

    This handles the common case where expected items are short
    distilled descriptions and actual items are longer prose sentences
    containing the same information.

    Args:
        a: First string.
        b: Second string.

    Returns:
        Similarity ratio between 0.0 and 1.0.
    """
    if not a or not b:
        return 0.0
    # Normalize strings for comparison
    a_normalized = " ".join(a.lower().split())
    b_normalized = " ".join(b.lower().split())

    seq_ratio = SequenceMatcher(None, a_normalized, b_normalized).ratio()

    # Token containment: fraction of shorter's significant tokens in longer
    a_tokens = set(a_normalized.split())
    b_tokens = set(b_normalized.split())
    if len(a_tokens) <= len(b_tokens):
        shorter_tokens, longer_tokens = a_tokens, b_tokens
    else:
        shorter_tokens, longer_tokens = b_tokens, a_tokens

    # Use 4-char prefix matching on significant tokens (4+ chars)
    sig_shorter = {t for t in shorter_tokens if len(t) >= 4}
    if sig_shorter:
        longer_prefixes = {t[:4] for t in longer_tokens if len(t) >= 4}
        matches = sum(1 for t in sig_shorter if t[:4] in longer_prefixes)
        containment = matches / len(sig_shorter)
    else:
        containment = 0.0

    return max(seq_ratio, containment)


@dataclass
class DetailScore:
    """Score for detail capture with precision and recall.

    Attributes:
        matched_count: Number of expected items that matched actual items.
        expected_count: Total expected items.
        actual_count: Total actual items.
        recall: Proportion of expected items that were matched.
        precision: Proportion of actual items that matched expected items.
    """

    matched_count: int
    expected_count: int
    actual_count: int
    recall: float
    precision: float

    @property
    def f1(self) -> float:
        """Compute F1 score (harmonic mean of precision and recall)."""
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * (self.precision * self.recall) / (self.precision + self.recall)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "matched_count": self.matched_count,
            "expected_count": self.expected_count,
            "actual_count": self.actual_count,
            "recall": self.recall,
            "precision": self.precision,
            "f1": self.f1,
        }


def score_detail_capture(
    expected: list[str],
    actual: list[str],
    fuzzy_threshold: float = 0.8,
) -> DetailScore:
    """Score detail capture using fuzzy matching.

    For each expected item, find the best matching actual item. An expected
    item is considered matched if its best match exceeds the fuzzy threshold.

    Args:
        expected: List of expected detail strings.
        actual: List of actual detail strings extracted.
        fuzzy_threshold: Minimum similarity ratio for a match (default 0.8).

    Returns:
        DetailScore with precision, recall, and match counts.
    """
    if not expected and not actual:
        return DetailScore(
            matched_count=0,
            expected_count=0,
            actual_count=0,
            recall=1.0,
            precision=1.0,
        )

    matched_expected: set[int] = set()
    matched_actual: set[int] = set()

    # Find best matches for each expected item
    for exp_idx, exp in enumerate(expected):
        best_match_score = 0.0
        best_match_idx = -1

        for act_idx, act in enumerate(actual):
            if act_idx in matched_actual:
                continue
            score = _fuzzy_ratio(exp, act)
            if score > best_match_score:
                best_match_score = score
                best_match_idx = act_idx

        if best_match_score >= fuzzy_threshold and best_match_idx >= 0:
            matched_expected.add(exp_idx)
            matched_actual.add(best_match_idx)

    recall = len(matched_expected) / max(1, len(expected))
    precision = len(matched_actual) / max(1, len(actual))

    return DetailScore(
        matched_count=len(matched_expected),
        expected_count=len(expected),
        actual_count=len(actual),
        recall=recall,
        precision=precision,
    )


@dataclass
class PhaseMetrics:
    """Metrics for a single phase evaluation.

    Attributes:
        phase_name: Name of the phase.
        detail_score: Detail capture score with precision/recall.
        iterations: Number of iterations taken.
        converged: Whether the phase converged.
        duration_ms: Execution time in milliseconds.
        gaps_open: Number of open gaps at end of phase.
        gaps_closed: Number of gaps closed during phase.
        errors: List of error messages encountered.
    """

    phase_name: str
    detail_score: DetailScore
    iterations: int = 1
    converged: bool = True
    duration_ms: float = 0.0
    gaps_open: int = 0
    gaps_closed: int = 0
    errors: list[str] = field(default_factory=list)
    # IMPL(single-layer): `iterations` + `converged` feed reduced-thrash checks
    # (Section 14.2) and provide bounded per-phase evidence for failure analysis.

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "phase_name": self.phase_name,
            "detail_score": self.detail_score.to_dict(),
            "iterations": self.iterations,
            "converged": self.converged,
            "duration_ms": self.duration_ms,
            "gaps_open": self.gaps_open,
            "gaps_closed": self.gaps_closed,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseMetrics:
        """Deserialize from dictionary."""
        score_data = data.get("detail_score", {})
        detail_score = DetailScore(
            matched_count=score_data.get("matched_count", 0),
            expected_count=score_data.get("expected_count", 0),
            actual_count=score_data.get("actual_count", 0),
            recall=score_data.get("recall", 0.0),
            precision=score_data.get("precision", 0.0),
        )
        return cls(
            phase_name=data.get("phase_name", ""),
            detail_score=detail_score,
            iterations=data.get("iterations", 1),
            converged=data.get("converged", True),
            duration_ms=data.get("duration_ms", 0.0),
            gaps_open=data.get("gaps_open", 0),
            gaps_closed=data.get("gaps_closed", 0),
            errors=data.get("errors", []),
        )


@dataclass
class DetailCaptureMetrics:
    """Aggregate detail capture metrics across phases.

    Attributes:
        phase_metrics: Metrics for each phase by name.
        total_details_expected: Total details expected across all phases.
        total_details_captured: Total details successfully captured.
        total_details_spurious: Total spurious (hallucinated) details.
    """

    phase_metrics: dict[str, PhaseMetrics] = field(default_factory=dict)
    total_details_expected: int = 0
    total_details_captured: int = 0
    total_details_spurious: int = 0
    # IMPL(single-layer): Aggregate totals are baseline fidelity inputs; Section 14.2
    # success evaluation should compare these with QA/judge and dropped-requirement deltas.

    @property
    def recall(self) -> float:
        """Overall recall across all phases."""
        if self.total_details_expected == 0:
            return 1.0
        return self.total_details_captured / self.total_details_expected

    @property
    def precision(self) -> float:
        """Overall precision across all phases."""
        total_actual = self.total_details_captured + self.total_details_spurious
        if total_actual == 0:
            return 1.0
        return self.total_details_captured / total_actual

    @property
    def f1(self) -> float:
        """Overall F1 score."""
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * (self.precision * self.recall) / (self.precision + self.recall)

    def add_phase_metrics(self, metrics: PhaseMetrics) -> None:
        """Add metrics for a phase.

        Spurious items are only counted for phases that have expected items.
        Phases without ground truth (expected_count == 0) cannot meaningfully
        contribute to the spurious count.
        """
        self.phase_metrics[metrics.phase_name] = metrics
        self.total_details_expected += metrics.detail_score.expected_count
        self.total_details_captured += metrics.detail_score.matched_count
        if metrics.detail_score.expected_count > 0:
            spurious = metrics.detail_score.actual_count - metrics.detail_score.matched_count
            self.total_details_spurious += max(0, spurious)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "phase_metrics": {
                name: metrics.to_dict() for name, metrics in self.phase_metrics.items()
            },
            "total_details_expected": self.total_details_expected,
            "total_details_captured": self.total_details_captured,
            "total_details_spurious": self.total_details_spurious,
            "recall": self.recall,
            "precision": self.precision,
            "f1": self.f1,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DetailCaptureMetrics:
        """Deserialize from dictionary."""
        metrics = cls(
            total_details_expected=data.get("total_details_expected", 0),
            total_details_captured=data.get("total_details_captured", 0),
            total_details_spurious=data.get("total_details_spurious", 0),
        )
        for name, phase_data in data.get("phase_metrics", {}).items():
            metrics.phase_metrics[name] = PhaseMetrics.from_dict(phase_data)
        return metrics


@dataclass
class ConvergenceAnalysis:
    """Analysis of convergence trajectory.

    Attributes:
        converged: Whether the system converged within max iterations.
        iterations_to_converge: Number of iterations to reach convergence.
        final_ratio: Final convergence ratio achieved.
        plateau_start: Iteration where plateau (stagnation) began, if any.
        bottleneck: Description of identified bottleneck, if any.
        trajectory: List of convergence ratios per iteration.
    """

    converged: bool
    iterations_to_converge: int
    final_ratio: float
    plateau_start: int | None = None
    bottleneck: str | None = None
    trajectory: list[float] = field(default_factory=list)
    # IMPL(single-layer): `plateau_start`/`bottleneck` map directly to Section 14.3
    # stagnation failure signals and must propagate unchanged to runner failure reasons.

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "converged": self.converged,
            "iterations_to_converge": self.iterations_to_converge,
            "final_ratio": self.final_ratio,
            "plateau_start": self.plateau_start,
            "bottleneck": self.bottleneck,
            "trajectory": self.trajectory,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConvergenceAnalysis:
        """Deserialize from dictionary."""
        return cls(
            converged=data.get("converged", False),
            iterations_to_converge=data.get("iterations_to_converge", 0),
            final_ratio=data.get("final_ratio", 0.0),
            plateau_start=data.get("plateau_start"),
            bottleneck=data.get("bottleneck"),
            trajectory=data.get("trajectory", []),
        )


def analyze_convergence(
    trajectory: list[float],
    convergence_threshold: float = 0.95,
    stagnation_delta: float = 0.01,
    stagnation_window: int = 3,
) -> ConvergenceAnalysis:
    """Analyze a convergence trajectory to detect plateaus and bottlenecks.

    Args:
        trajectory: List of convergence ratios per iteration.
        convergence_threshold: Ratio at which convergence is considered achieved.
        stagnation_delta: Maximum change to be considered stagnant.
        stagnation_window: Number of iterations in plateau to detect stagnation.

    Returns:
        ConvergenceAnalysis with convergence status and bottleneck identification.
    """
    # IMPL(single-layer): Treat this as deterministic stagnation detection only; do not
    # gate success on heuristic completion markers without verifier/test evidence.
    if not trajectory:
        return ConvergenceAnalysis(
            converged=True,
            iterations_to_converge=0,
            final_ratio=1.0,
            trajectory=[],
        )

    final_ratio = trajectory[-1]
    converged = final_ratio >= convergence_threshold

    # Find iteration where convergence threshold was first met
    iterations_to_converge = len(trajectory)
    for idx, ratio in enumerate(trajectory):
        if ratio >= convergence_threshold:
            iterations_to_converge = idx + 1
            break

    # Detect plateau (stagnation)
    plateau_start: int | None = None
    plateau_count = 0

    for idx in range(1, len(trajectory)):
        delta = abs(trajectory[idx] - trajectory[idx - 1])
        if delta < stagnation_delta:
            plateau_count += 1
            if plateau_count >= stagnation_window and plateau_start is None:
                plateau_start = idx - stagnation_window
        else:
            plateau_count = 0

    # Identify bottleneck
    bottleneck: str | None = None
    if plateau_start is not None and not converged:
        bottleneck = f"iteration_{plateau_start}"

    return ConvergenceAnalysis(
        converged=converged,
        iterations_to_converge=iterations_to_converge,
        final_ratio=final_ratio,
        plateau_start=plateau_start,
        bottleneck=bottleneck,
        trajectory=trajectory,
    )


_MISSING = object()
_CLOSED_WORK_ITEM_STATUSES = {"DONE", "DECIDED", "MERGED"}
_PHASE_SEQUENCE: tuple[PhaseId, PhaseId, PhaseId] = ("libraries", "architecture", "quality")


def _read_value(container: Any, key: str, default: Any = _MISSING) -> Any:
    if isinstance(container, dict):
        return container.get(key, default)
    return getattr(container, key, default)


def _lookup_path(payload: Any, path: tuple[str, ...]) -> Any:
    current: Any = payload
    for segment in path:
        current = _read_value(current, segment, _MISSING)
        if current is _MISSING:
            return _MISSING
    return current


def _first_present(payload: Any, *paths: tuple[str, ...]) -> tuple[Any, bool]:
    for path in paths:
        value = _lookup_path(payload, path)
        if value is not _MISSING:
            return value, True
    return None, False


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _coerce_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return default
    return default


def _coerce_float(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _normalize_phase_id(value: Any) -> PhaseId | None:
    normalized = str(value).strip().lower()
    if normalized not in {"libraries", "architecture", "quality"}:
        return None
    return cast("PhaseId", normalized)


def _extract_qa_judge_pass_rate(payload: dict[str, Any]) -> tuple[float, bool]:
    raw, found = _first_present(
        payload,
        ("qa_judge_pass_rate",),
        ("metrics", "qa_judge_pass_rate"),
        ("qa_judge", "pass_rate"),
        ("metrics", "qa_judge", "pass_rate"),
        ("qa", "judge", "pass_rate"),
    )
    if found:
        if isinstance(raw, dict):
            passed = _coerce_float(_read_value(raw, "passed", 0.0))
            total = _coerce_float(_read_value(raw, "total", 0.0))
            if total > 0:
                return _clamp01(passed / total), True
        return _clamp01(_coerce_float(raw)), True

    score_rows, rows_found = _first_present(
        payload,
        ("qa_judge_results",),
        ("qa_judge", "results"),
        ("metrics", "qa_judge", "results"),
    )
    if rows_found:
        rows = _as_list(score_rows)
        if not rows:
            return 0.0, True
        passed = 0
        total = 0
        for row in rows:
            verdict = _read_value(row, "passed", _MISSING)
            if verdict is _MISSING:
                verdict = _read_value(row, "status", "")
                if isinstance(verdict, str):
                    verdict = verdict.strip().lower() in {"pass", "passed"}
            if verdict is not _MISSING:
                total += 1
                if _coerce_bool(verdict):
                    passed += 1
        if total == 0:
            return 0.0, True
        return _clamp01(passed / total), True

    return 0.0, False


def _extract_dropped_requirement_count(payload: dict[str, Any]) -> tuple[int, bool]:
    raw, found = _first_present(
        payload,
        ("dropped_requirement_count",),
        ("metrics", "dropped_requirement_count"),
        ("dropped_requirements_count",),
        ("metrics", "dropped_requirements_count"),
    )
    if found:
        return max(0, _coerce_int(raw)), True

    dropped_rows, rows_found = _first_present(
        payload,
        ("dropped_requirements",),
        ("metrics", "dropped_requirements"),
    )
    if rows_found:
        if isinstance(dropped_rows, (list, tuple, set)):
            return len(dropped_rows), True
        return max(0, _coerce_int(dropped_rows)), True

    return 0, False


@dataclass
class SpecFidelityMetrics:
    qa_judge_pass_rate: float
    baseline_qa_judge_pass_rate: float
    dropped_requirement_count: int
    baseline_dropped_requirement_count: int
    fidelity_delta: float
    warning_flags: list[str] = field(default_factory=list)
    failure_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "qa_judge_pass_rate": self.qa_judge_pass_rate,
            "baseline_qa_judge_pass_rate": self.baseline_qa_judge_pass_rate,
            "dropped_requirement_count": self.dropped_requirement_count,
            "baseline_dropped_requirement_count": self.baseline_dropped_requirement_count,
            "fidelity_delta": self.fidelity_delta,
            "warning_flags": self.warning_flags,
            "failure_flags": self.failure_flags,
            "meets_success_criteria": self.meets_success_criteria,
        }

    @property
    def meets_success_criteria(self) -> bool:
        return not self.failure_flags


def compute_spec_fidelity_metrics(
    baseline: dict[str, Any],
    variant: dict[str, Any],
) -> SpecFidelityMetrics:
    baseline_rate, baseline_rate_found = _extract_qa_judge_pass_rate(baseline)
    variant_rate, variant_rate_found = _extract_qa_judge_pass_rate(variant)
    baseline_dropped, baseline_dropped_found = _extract_dropped_requirement_count(baseline)
    variant_dropped, variant_dropped_found = _extract_dropped_requirement_count(variant)

    warning_flags: list[str] = []
    if not baseline_rate_found:
        warning_flags.append("missing_baseline_qa_judge_pass_rate")
    if not variant_rate_found:
        warning_flags.append("missing_variant_qa_judge_pass_rate")
    if not baseline_dropped_found:
        warning_flags.append("missing_baseline_dropped_requirements")
    if not variant_dropped_found:
        warning_flags.append("missing_variant_dropped_requirements")

    failure_flags: list[str] = []
    if variant_rate < baseline_rate:
        failure_flags.append("qa_judge_pass_rate_regression")
    if variant_dropped > baseline_dropped:
        failure_flags.append("dropped_requirements_increase")

    return SpecFidelityMetrics(
        qa_judge_pass_rate=variant_rate,
        baseline_qa_judge_pass_rate=baseline_rate,
        dropped_requirement_count=variant_dropped,
        baseline_dropped_requirement_count=baseline_dropped,
        fidelity_delta=variant_rate - baseline_rate,
        warning_flags=warning_flags,
        failure_flags=failure_flags,
    )


def _extract_phase_iteration_counts(payload: dict[str, Any]) -> tuple[dict[PhaseId, int], bool]:
    raw, found = _first_present(payload, ("phase_iteration_counts",), ("run_state", "phase_iteration_counts"))
    if not found or not isinstance(raw, dict):
        return {phase: 0 for phase in _PHASE_SEQUENCE}, False

    counts: dict[PhaseId, int] = {phase: 0 for phase in _PHASE_SEQUENCE}
    for key, value in raw.items():
        phase = _normalize_phase_id(key)
        if phase is None:
            continue
        counts[phase] = max(0, _coerce_int(value))
    return counts, True


def _extract_shape_verifier_counts(payload: dict[str, Any]) -> tuple[int, int, bool]:
    raw_summaries, found = _first_present(
        payload,
        ("shape_verifiers",),
        ("verifier_summaries",),
        ("routing", "verifier_summaries"),
    )
    if not found:
        return 0, 0, False

    entries: list[Any]
    if isinstance(raw_summaries, dict):
        entries = list(raw_summaries.values())
    else:
        entries = _as_list(raw_summaries)

    passed = 0
    total = 0
    for summary in entries:
        results = _read_value(summary, "results", [])
        result_rows = _as_list(results)
        authoritative_rows = [
            row
            for row in result_rows
            if str(_read_value(row, "kind", "")).strip().upper() != "PROPOSAL_REQUIRED"
        ]
        if authoritative_rows:
            for row in authoritative_rows:
                total += 1
                if _coerce_bool(_read_value(row, "passed", False)):
                    passed += 1
            continue

        all_passed = _read_value(summary, "all_passed", _MISSING)
        if all_passed is not _MISSING:
            total += 1
            if _coerce_bool(all_passed):
                passed += 1

    return passed, total, True


def _extract_work_items(payload: dict[str, Any]) -> tuple[list[Any], bool]:
    raw, found = _first_present(
        payload,
        ("work_items",),
        ("routing", "work_items"),
        ("coordination", "work_items"),
    )
    if not found:
        return [], False
    return _as_list(raw), True


def _extract_work_item_convergence(items: list[Any]) -> tuple[int, int]:
    if not items:
        return 0, 0
    closed = 0
    total = 0
    for item in items:
        status = str(_read_value(item, "status", "")).strip().upper()
        if not status:
            continue
        total += 1
        if status in _CLOSED_WORK_ITEM_STATUSES:
            closed += 1
    return closed, total


def _extract_avg_iterations_to_close(
    payload: dict[str, Any],
    items: list[Any],
    closed_count: int,
) -> tuple[float, bool]:
    raw, found = _first_present(
        payload,
        ("avg_iterations_to_close",),
        ("metrics", "avg_iterations_to_close"),
        ("work_item_iterations", "avg_to_close"),
    )
    if found:
        return max(0.0, _coerce_float(raw)), True

    if closed_count == 0:
        return 0.0, True

    durations: list[int] = []
    for item in items:
        status = str(_read_value(item, "status", "")).strip().upper()
        if status not in _CLOSED_WORK_ITEM_STATUSES:
            continue
        item_duration, duration_found = _first_present(
            item,
            ("iterations_to_close",),
            ("metadata", "iterations_to_close"),
        )
        if duration_found:
            durations.append(max(0, _coerce_int(item_duration)))
            continue

        closed_iter, has_closed = _first_present(
            item,
            ("closed_iteration",),
            ("metadata", "closed_iteration"),
            ("metadata", "resolved_iteration"),
        )
        created_iter, has_created = _first_present(
            item,
            ("created_iteration",),
            ("metadata", "created_iteration"),
            ("metadata", "opened_iteration"),
        )
        if has_closed and has_created:
            durations.append(max(0, _coerce_int(closed_iter) - _coerce_int(created_iter) + 1))

    if durations:
        return sum(durations) / len(durations), True
    return 0.0, False


def _extract_stagnation_events(payload: dict[str, Any]) -> tuple[int, bool]:
    raw, found = _first_present(
        payload,
        ("stagnation_events",),
        ("metrics", "stagnation_events"),
    )
    if found:
        return max(0, _coerce_int(raw)), True

    loop_events, loop_found = _first_present(payload, ("loop_events",), ("loops", "events"))
    if loop_found:
        count = 0
        for event in _as_list(loop_events):
            status = str(_read_value(event, "status", "")).strip().lower()
            if status in {"stagnant", "stagnation"}:
                count += 1
        return count, True

    convergence, convergence_found = _first_present(
        payload,
        ("convergence",),
        ("convergence_analysis",),
    )
    if convergence_found:
        plateau_start = _coerce_int(_read_value(convergence, "plateau_start", -1), default=-1)
        converged = _coerce_bool(_read_value(convergence, "converged", True), default=True)
        return (1 if plateau_start >= 0 and not converged else 0), True

    return 0, False


def _extract_drift_open_count(payload: dict[str, Any]) -> tuple[int, bool]:
    raw, found = _first_present(
        payload,
        ("drift_open_count",),
        ("shape_drift_open_count",),
        ("metrics", "drift_open_count"),
    )
    if found:
        return max(0, _coerce_int(raw)), True

    drift_reports, reports_found = _first_present(
        payload,
        ("drift_reports",),
        ("shape_drift", "reports"),
    )
    if reports_found:
        open_count = 0
        for report in _as_list(drift_reports):
            status = str(_read_value(report, "status", "")).strip().upper()
            if status in {"OPEN", "UNRESOLVED", "DRIFTED"}:
                open_count += 1
        return open_count, True

    return 0, False


def _extract_open_work_item_counts(payload: dict[str, Any]) -> tuple[list[int], bool]:
    raw, found = _first_present(
        payload,
        ("open_work_item_counts",),
        ("work_item_open_counts",),
        ("run_state", "open_work_item_count_history"),
    )
    if not found:
        return [], False
    values = [_coerce_int(value) for value in _as_list(raw)]
    return [max(0, value) for value in values], True


def _extract_max_work_items_cap(payload: dict[str, Any]) -> int | None:
    raw, found = _first_present(
        payload,
        ("max_work_items_per_phase",),
        ("run_config", "max_work_items_per_phase"),
        ("config", "max_work_items_per_phase"),
    )
    if not found:
        return None
    cap = _coerce_int(raw, default=-1)
    if cap < 0:
        return None
    return cap


def _has_unbounded_growth(payload: dict[str, Any]) -> bool:
    explicit, found = _first_present(
        payload,
        ("unbounded_growth",),
        ("metrics", "unbounded_growth"),
    )
    if found:
        return _coerce_bool(explicit)

    counts, counts_found = _extract_open_work_item_counts(payload)
    if counts_found and len(counts) >= 3:
        tail = counts[-3:]
        if tail[0] < tail[1] < tail[2]:
            return True

    cap = _extract_max_work_items_cap(payload)
    if cap is not None:
        final_count, final_found = _first_present(
            payload,
            ("open_work_item_count",),
            ("run_state", "open_work_item_count"),
        )
        if final_found and _coerce_int(final_count) > cap:
            return True

    return False


def _has_test_evidence(payload: dict[str, Any]) -> bool:
    all_tests_pass, found = _first_present(
        payload,
        ("all_tests_pass",),
        ("tests", "all_passed"),
        ("gate_results", "all_tests_pass"),
    )
    if found and isinstance(all_tests_pass, bool):
        return True

    test_results, results_found = _first_present(
        payload,
        ("test_results",),
        ("tests", "results"),
        ("tests", "failures"),
    )
    if results_found and len(_as_list(test_results)) > 0:
        return True

    totals, totals_found = _first_present(
        payload,
        ("tests", "total"),
        ("test_summary", "total"),
    )
    return totals_found and _coerce_int(totals) > 0


def _has_heuristic_completion_marker(payload: dict[str, Any]) -> bool:
    raw_flag, flag_found = _first_present(
        payload,
        ("heuristic_only_completion",),
        ("completion", "heuristic_only"),
    )
    if flag_found and _coerce_bool(raw_flag):
        return True

    source, source_found = _first_present(
        payload,
        ("completion_source",),
        ("completion", "source"),
        ("metadata", "completion_source"),
    )
    if source_found and str(source).strip().lower() == "heuristic":
        return True

    markers, markers_found = _first_present(
        payload,
        ("completion_markers",),
        ("completion", "markers"),
    )
    if markers_found:
        for marker in _as_list(markers):
            marker_source = str(_read_value(marker, "source", "")).strip().lower()
            if marker_source == "heuristic":
                return True
    return False


def _extract_escaped_architecture_issue_count(payload: dict[str, Any]) -> int:
    raw, found = _first_present(
        payload,
        ("escaped_architecture_issue_count",),
        ("pin_caught_issues_escaped",),
        ("metrics", "escaped_architecture_issue_count"),
    )
    if not found:
        return 0
    return max(0, _coerce_int(raw))


@dataclass
class ShapeEvaluationMetrics:
    shape_verifier_pass_rate: float
    work_item_convergence_rate: float
    avg_iterations_to_close: float
    stagnation_events: int
    drift_open_count: int
    phase_iteration_counts: dict[PhaseId, int] = field(
        default_factory=lambda: {phase: 0 for phase in _PHASE_SEQUENCE}
    )
    warning_flags: list[str] = field(default_factory=list)
    failure_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape_verifier_pass_rate": self.shape_verifier_pass_rate,
            "work_item_convergence_rate": self.work_item_convergence_rate,
            "avg_iterations_to_close": self.avg_iterations_to_close,
            "stagnation_events": self.stagnation_events,
            "drift_open_count": self.drift_open_count,
            "phase_iteration_counts": self.phase_iteration_counts,
            "warning_flags": self.warning_flags,
            "failure_flags": self.failure_flags,
        }


def compute_shape_metrics(run_payload: dict[str, Any]) -> ShapeEvaluationMetrics:
    warning_flags: list[str] = []
    failure_flags: list[str] = []

    verifier_passed, verifier_total, verifier_found = _extract_shape_verifier_counts(run_payload)
    if not verifier_found:
        warning_flags.append("missing_shape_verifier_artifacts")
    elif verifier_total == 0:
        warning_flags.append("empty_shape_verifier_results")
    shape_verifier_pass_rate = (
        _clamp01(verifier_passed / verifier_total) if verifier_total > 0 else 0.0
    )

    work_items, work_items_found = _extract_work_items(run_payload)
    if not work_items_found:
        warning_flags.append("missing_work_item_artifacts")
    closed_items, total_items = _extract_work_item_convergence(work_items)
    if work_items_found and total_items == 0:
        work_item_convergence_rate = 1.0
    else:
        work_item_convergence_rate = (
            _clamp01(closed_items / total_items) if total_items > 0 else 0.0
        )

    avg_iterations_to_close, avg_found = _extract_avg_iterations_to_close(
        run_payload,
        work_items,
        closed_items,
    )
    if not avg_found:
        warning_flags.append("missing_iterations_to_close_artifacts")

    stagnation_events, stagnation_found = _extract_stagnation_events(run_payload)
    if not stagnation_found:
        warning_flags.append("missing_stagnation_artifacts")

    drift_open_count, drift_found = _extract_drift_open_count(run_payload)
    if not drift_found:
        warning_flags.append("missing_shape_drift_artifacts")

    phase_iteration_counts, phase_found = _extract_phase_iteration_counts(run_payload)
    if not phase_found:
        warning_flags.append("missing_phase_iteration_counts")

    if stagnation_events > 0:
        failure_flags.append("stagnation_detected")
    if _has_unbounded_growth(run_payload):
        failure_flags.append("unbounded_growth_detected")
    if drift_open_count > 0:
        failure_flags.append("shape_drift_unresolved")
    if _extract_escaped_architecture_issue_count(run_payload) > 0:
        failure_flags.append("architecture_issues_escaped_without_verifier_replacement")

    has_deterministic_evidence = (verifier_total > 0) or _has_test_evidence(run_payload)
    if _has_heuristic_completion_marker(run_payload) and not has_deterministic_evidence:
        failure_flags.append("heuristic_only_completion_without_deterministic_evidence")

    return ShapeEvaluationMetrics(
        shape_verifier_pass_rate=shape_verifier_pass_rate,
        work_item_convergence_rate=work_item_convergence_rate,
        avg_iterations_to_close=avg_iterations_to_close,
        stagnation_events=stagnation_events,
        drift_open_count=drift_open_count,
        phase_iteration_counts=phase_iteration_counts,
        warning_flags=warning_flags,
        failure_flags=failure_flags,
    )


def _extract_count(payload: dict[str, Any], *paths: tuple[str, ...]) -> tuple[int, bool]:
    raw, found = _first_present(payload, *paths)
    if not found:
        return 0, False
    if isinstance(raw, (list, tuple, set, dict)):
        return len(raw), True
    return max(0, _coerce_int(raw)), True


@dataclass
class ComplexityReductionMetrics:
    deleted_pin_modules: int
    deleted_layer_branches: int
    gate_count_delta: int
    dispatch_branch_delta: int
    warning_flags: list[str] = field(default_factory=list)
    failure_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deleted_pin_modules": self.deleted_pin_modules,
            "deleted_layer_branches": self.deleted_layer_branches,
            "gate_count_delta": self.gate_count_delta,
            "dispatch_branch_delta": self.dispatch_branch_delta,
            "warning_flags": self.warning_flags,
            "failure_flags": self.failure_flags,
        }


def compute_complexity_metrics(
    baseline: dict[str, Any],
    variant: dict[str, Any],
) -> ComplexityReductionMetrics:
    warning_flags: list[str] = []
    failure_flags: list[str] = []

    baseline_pin_count, baseline_pin_found = _extract_count(
        baseline,
        ("pin_module_count",),
        ("metrics", "pin_module_count"),
        ("pin_modules",),
    )
    variant_pin_count, variant_pin_found = _extract_count(
        variant,
        ("pin_module_count",),
        ("metrics", "pin_module_count"),
        ("pin_modules",),
    )
    if not baseline_pin_found or not variant_pin_found:
        warning_flags.append("missing_pin_module_counts")

    baseline_layer_branches, baseline_layer_found = _extract_count(
        baseline,
        ("layer_branch_count",),
        ("metrics", "layer_branch_count"),
        ("layer_branches",),
    )
    variant_layer_branches, variant_layer_found = _extract_count(
        variant,
        ("layer_branch_count",),
        ("metrics", "layer_branch_count"),
        ("layer_branches",),
    )
    if not baseline_layer_found or not variant_layer_found:
        warning_flags.append("missing_layer_branch_counts")

    baseline_gate_count, baseline_gate_found = _extract_count(
        baseline,
        ("gate_count",),
        ("metrics", "gate_count"),
        ("gates",),
    )
    variant_gate_count, variant_gate_found = _extract_count(
        variant,
        ("gate_count",),
        ("metrics", "gate_count"),
        ("gates",),
    )
    if not baseline_gate_found or not variant_gate_found:
        warning_flags.append("missing_gate_counts")

    baseline_dispatch_count, baseline_dispatch_found = _extract_count(
        baseline,
        ("dispatch_branch_count",),
        ("metrics", "dispatch_branch_count"),
        ("dispatch_branches",),
    )
    variant_dispatch_count, variant_dispatch_found = _extract_count(
        variant,
        ("dispatch_branch_count",),
        ("metrics", "dispatch_branch_count"),
        ("dispatch_branches",),
    )
    if not baseline_dispatch_found or not variant_dispatch_found:
        warning_flags.append("missing_dispatch_branch_counts")

    deleted_pin_modules = max(0, baseline_pin_count - variant_pin_count)
    deleted_layer_branches = max(0, baseline_layer_branches - variant_layer_branches)
    gate_count_delta = baseline_gate_count - variant_gate_count
    dispatch_branch_delta = baseline_dispatch_count - variant_dispatch_count

    if gate_count_delta < 0:
        failure_flags.append("gate_count_increased")
    if dispatch_branch_delta < 0:
        failure_flags.append("dispatch_branch_count_increased")

    return ComplexityReductionMetrics(
        deleted_pin_modules=deleted_pin_modules,
        deleted_layer_branches=deleted_layer_branches,
        gate_count_delta=gate_count_delta,
        dispatch_branch_delta=dispatch_branch_delta,
        warning_flags=warning_flags,
        failure_flags=failure_flags,
    )


def _extract_requeue_count(payload: dict[str, Any]) -> tuple[int, bool]:
    raw, found = _first_present(
        payload,
        ("requeue_count",),
        ("metrics", "requeue_count"),
        ("work_items", "requeue_count"),
    )
    if found:
        return max(0, _coerce_int(raw)), True

    events, events_found = _first_present(payload, ("work_item_events",), ("events", "work_items"))
    if events_found:
        count = 0
        for event in _as_list(events):
            label = " ".join(
                [
                    str(_read_value(event, "action", "")),
                    str(_read_value(event, "status", "")),
                    str(_read_value(event, "reason", "")),
                ]
            ).lower()
            if "requeue" in label or "re-open" in label or "reopen" in label:
                count += 1
        return count, True

    return 0, False


def _extract_phase_local_retries(payload: dict[str, Any]) -> tuple[int, bool]:
    raw, found = _first_present(
        payload,
        ("phase_local_retries",),
        ("metrics", "phase_local_retries"),
    )
    if found:
        return max(0, _coerce_int(raw)), True

    retries_by_phase, by_phase_found = _first_present(payload, ("retries_by_phase",))
    if by_phase_found and isinstance(retries_by_phase, dict):
        return sum(max(0, _coerce_int(value)) for value in retries_by_phase.values()), True

    events, events_found = _first_present(payload, ("work_item_events",), ("events", "work_items"))
    if events_found:
        count = 0
        for event in _as_list(events):
            label = " ".join(
                [
                    str(_read_value(event, "action", "")),
                    str(_read_value(event, "status", "")),
                    str(_read_value(event, "reason", "")),
                ]
            ).lower()
            if "retry" in label:
                count += 1
        return count, True

    return 0, False


def _extract_total_work_item_scope(payload: dict[str, Any], items: list[Any]) -> tuple[int, bool]:
    raw, found = _first_present(
        payload,
        ("total_work_items",),
        ("metrics", "total_work_items"),
    )
    if found:
        return max(0, _coerce_int(raw)), True
    if items:
        return len(items), True

    events, events_found = _first_present(payload, ("work_item_events",), ("events", "work_items"))
    if events_found:
        ids: set[str] = set()
        for event in _as_list(events):
            item_id = str(_read_value(event, "work_item_id", "")).strip()
            if item_id:
                ids.add(item_id)
        return len(ids), True
    return 0, False


@dataclass
class ThrashMetrics:
    work_item_churn_ratio: float
    requeue_count: int
    phase_local_retries: int
    warning_flags: list[str] = field(default_factory=list)
    failure_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_item_churn_ratio": self.work_item_churn_ratio,
            "requeue_count": self.requeue_count,
            "phase_local_retries": self.phase_local_retries,
            "warning_flags": self.warning_flags,
            "failure_flags": self.failure_flags,
        }


def compute_thrash_metrics(run_payload: dict[str, Any]) -> ThrashMetrics:
    warning_flags: list[str] = []
    failure_flags: list[str] = []

    items, items_found = _extract_work_items(run_payload)
    requeue_count, requeue_found = _extract_requeue_count(run_payload)
    phase_local_retries, retries_found = _extract_phase_local_retries(run_payload)
    if not requeue_found:
        warning_flags.append("missing_requeue_artifacts")
    if not retries_found:
        warning_flags.append("missing_phase_local_retry_artifacts")

    raw_ratio, ratio_found = _first_present(
        run_payload,
        ("work_item_churn_ratio",),
        ("metrics", "work_item_churn_ratio"),
    )
    if ratio_found:
        churn_ratio = max(0.0, _coerce_float(raw_ratio))
    else:
        total_items, total_found = _extract_total_work_item_scope(run_payload, items)
        if not total_found:
            warning_flags.append("missing_total_work_item_scope")
            total_items = 0
        churn_ratio = (
            (requeue_count + phase_local_retries) / total_items
            if total_items > 0
            else 0.0
        )

    if churn_ratio > 1.0:
        failure_flags.append("high_work_item_churn")

    if not items_found:
        warning_flags.append("missing_work_item_artifacts")

    return ThrashMetrics(
        work_item_churn_ratio=churn_ratio,
        requeue_count=requeue_count,
        phase_local_retries=phase_local_retries,
        warning_flags=warning_flags,
        failure_flags=failure_flags,
    )
