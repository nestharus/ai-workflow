"""Metrics computation for spec refinement evaluation.

Provides precision/recall scoring with fuzzy matching for NLP variation,
convergence analysis, and phase-level metrics aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any


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
