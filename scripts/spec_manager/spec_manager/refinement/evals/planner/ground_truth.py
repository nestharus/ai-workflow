"""Load and validate constraint-based planner ground truth from YAML files.

Ground truth is constraint-based (not exact match). Each case has a decision_key
that joins ``{layer}:{capability}:{slice_id}:{iteration}:{input_hash[:8]}`` to
capability-specific constraints (must_include / must_not_include atoms, invariants,
process expectations, and a rubric with hard gates + soft signals).

Supported capabilities: RESOLVE_SIGNAL, GAP, PLAN, UNDER_SPEC,
INTEGRATION_ANALYSIS.

Public API:
    load_ground_truth  -- deserialize a YAML (or JSON) file
    save_ground_truth  -- serialize back to YAML (or JSON)
    find_case          -- lookup a single case by decision_key
    find_cases_by_capability -- filter cases by capability string

Dataclasses:
    GroundTruthMeta, AtomMatch, InvariantRule, ProcessExpectation,
    RubricGate, RubricSignal, Rubric, GroundTruthCase, PlannerGroundTruth
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

try:
    import yaml

    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GroundTruthMeta:
    """Top-level metadata for a ground-truth file.

    Attributes:
        spec_id: Identifier of the spec under evaluation (e.g.
            ``chaotic_treasury_expanded``).
        gt_version: Schema version for this ground-truth format.
        created_at: ISO-8601 date string when the file was authored.
        notes: Free-form description or changelog.
    """

    spec_id: str = ""
    gt_version: int = 1
    created_at: str = ""
    notes: str = ""


@dataclass
class AtomMatch:
    """A single must-include or must-not-include atom.

    ``match`` holds capability-specific matching criteria such as
    ``function_name_any_of``, ``file_any_of``, ``function_name_regex``, etc.
    The exact keys depend on the capability and layer.

    Attributes:
        id: A human-readable identifier for this atom (e.g. ``fn:create_ledger_entry``).
        match: Dictionary of match criteria understood by scorers.
    """

    id: str = ""
    match: dict[str, Any] = field(default_factory=dict)


@dataclass
class InvariantRule:
    """A structural invariant that must hold for a decision output.

    Attributes:
        type: Kind of invariant -- ``schema``, ``scope``, or ``dedupe``.
        rule: Named rule identifier (e.g. ``l1_plan_intentions_v1``).
        key_fields: For dedupe invariants, the fields used as dedup key.
        max_duplicates: For dedupe invariants, maximum allowed duplicates.
    """

    type: str = ""
    rule: str = ""
    key_fields: list[str] = field(default_factory=list)
    max_duplicates: int = 0


@dataclass
class ProcessExpectation:
    """An expectation about the *process* rather than the output.

    Attributes:
        type: Kind of process expectation (e.g. ``evidence_first``).
        min_rate: Minimum acceptable rate (0.0 -- 1.0).
        applicable_when: Optional condition under which this expectation applies.
    """

    type: str = ""
    min_rate: float = 0.0
    applicable_when: str = ""


@dataclass
class RubricGate:
    """A hard gate in the scoring rubric.

    Attributes:
        metric: Name of the metric (e.g. ``must_include_recall``).
        threshold: Value at or above which the gate passes.
    """

    metric: str = ""
    threshold: float = 0.0


@dataclass
class RubricSignal:
    """A soft signal in the scoring rubric.

    Attributes:
        metric: Name of the metric (e.g. ``actionability``).
        threshold_warn: Below this value a warning is emitted.
        threshold_fail: Below this value the signal fails.
    """

    metric: str = ""
    threshold_warn: float = 0.0
    threshold_fail: float = 0.0


@dataclass
class Rubric:
    """Scoring rubric composed of hard gates and soft signals.

    Attributes:
        hard_gates: Gates that must pass for the case to be considered correct.
        soft_signals: Signals that produce warnings but do not block.
    """

    hard_gates: list[RubricGate] = field(default_factory=list)
    soft_signals: list[RubricSignal] = field(default_factory=list)


@dataclass
class GroundTruthCase:
    """A single ground-truth case tying a decision key to its constraints.

    Attributes:
        decision_key: Join key of the form
            ``{layer}:{capability}:{slice_id}:{iteration}:{input_hash[:8]}``.
        capability: One of RESOLVE_SIGNAL, GAP, PLAN, UNDER_SPEC,
            INTEGRATION_ANALYSIS.
        layer: ``l1``, ``l2``, or ``l3``.
        slice_id: Slice identifier (e.g. ``LIB-01``).
        iteration: Zero-based iteration number.
        input_fingerprint: Dictionary of hashes for the inputs that produced
            this case (e.g. ``{"gaps_hash": "sha256:..."}``).
        expected: Capability-specific constraint dictionary.  The schema of
            this dict varies by capability -- see module docstring.
        process_expectations: Optional list of process-level expectations.
        rubric: Scoring rubric for this case.
    """

    decision_key: str = ""
    capability: str = ""
    layer: str = ""
    slice_id: str = ""
    iteration: int = 0
    input_fingerprint: dict[str, str] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    process_expectations: list[ProcessExpectation] = field(default_factory=list)
    rubric: Rubric = field(default_factory=Rubric)


@dataclass
class PlannerGroundTruth:
    """Complete ground truth for planner evaluation.

    Attributes:
        meta: File-level metadata.
        cases: Ordered list of ground-truth cases.
    """

    meta: GroundTruthMeta = field(default_factory=GroundTruthMeta)
    cases: list[GroundTruthCase] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_atom_match(raw: dict[str, Any]) -> AtomMatch:
    """Deserialize a single atom-match dictionary."""
    return AtomMatch(
        id=raw.get("id", ""),
        match=raw.get("match", {}),
    )


def _parse_invariant(raw: dict[str, Any]) -> InvariantRule:
    """Deserialize a single invariant-rule dictionary."""
    return InvariantRule(
        type=raw.get("type", ""),
        rule=raw.get("rule", ""),
        key_fields=raw.get("key_fields", []),
        max_duplicates=raw.get("max_duplicates", 0),
    )


def _parse_process_expectation(raw: dict[str, Any]) -> ProcessExpectation:
    """Deserialize a single process-expectation dictionary."""
    return ProcessExpectation(
        type=raw.get("type", ""),
        min_rate=float(raw.get("min_rate", 0.0)),
        applicable_when=raw.get("applicable_when", ""),
    )


def _parse_rubric_gate(raw: dict[str, Any]) -> RubricGate:
    return RubricGate(
        metric=raw.get("metric", ""),
        threshold=float(raw.get("threshold", 0.0)),
    )


def _parse_rubric_signal(raw: dict[str, Any]) -> RubricSignal:
    return RubricSignal(
        metric=raw.get("metric", ""),
        threshold_warn=float(raw.get("threshold_warn", 0.0)),
        threshold_fail=float(raw.get("threshold_fail", 0.0)),
    )


def _parse_rubric(raw: dict[str, Any] | None) -> Rubric:
    if not raw:
        return Rubric()
    return Rubric(
        hard_gates=[_parse_rubric_gate(g) for g in raw.get("hard_gates", [])],
        soft_signals=[_parse_rubric_signal(s) for s in raw.get("soft_signals", [])],
    )


def _parse_case(raw: dict[str, Any]) -> GroundTruthCase:
    """Deserialize a single ground-truth case dictionary."""
    return GroundTruthCase(
        decision_key=raw.get("decision_key", ""),
        capability=raw.get("capability", ""),
        layer=raw.get("layer", ""),
        slice_id=raw.get("slice_id", ""),
        iteration=int(raw.get("iteration", 0)),
        input_fingerprint=raw.get("input_fingerprint", {}),
        expected=raw.get("expected", {}),
        process_expectations=[
            _parse_process_expectation(pe) for pe in raw.get("process_expectations", [])
        ],
        rubric=_parse_rubric(raw.get("rubric")),
    )


def _parse_meta(raw: dict[str, Any] | None) -> GroundTruthMeta:
    if not raw:
        return GroundTruthMeta()
    return GroundTruthMeta(
        spec_id=raw.get("spec_id", ""),
        gt_version=int(raw.get("gt_version", 1)),
        created_at=raw.get("created_at", ""),
        notes=raw.get("notes", ""),
    )


def _load_raw(path: Path) -> dict[str, Any]:
    """Load raw dictionary from a YAML or JSON file.

    Uses PyYAML when available; falls back to ``json`` for ``.json`` files
    or when PyYAML is not installed.
    """
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix == ".json" or not _HAS_YAML:
        if not _HAS_YAML and suffix not in (".json",):
            _logger.warning("PyYAML not installed; attempting JSON parse for %s", path)
        return json.loads(text)  # type: ignore[no-any-return]

    # YAML path (.yaml / .yml / anything else when pyyaml is available)
    return yaml.safe_load(text) or {}  # type: ignore[no-any-return]


def _serialize(gt: PlannerGroundTruth) -> dict[str, Any]:
    """Convert a ``PlannerGroundTruth`` to a plain dictionary.

    Uses ``dataclasses.asdict`` for a full recursive conversion, then strips
    default/empty values from process_expectations and rubric to keep YAML
    readable.
    """
    return asdict(gt)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_ground_truth(path: Path) -> PlannerGroundTruth:
    """Load planner ground truth from a YAML (or JSON) file.

    Parameters:
        path: Filesystem path to the ground-truth file.

    Returns:
        Fully-parsed ``PlannerGroundTruth`` instance.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file cannot be parsed.
    """
    if not path.exists():
        raise FileNotFoundError(f"Ground truth file not found: {path}")

    try:
        raw = _load_raw(path)
    except Exception as exc:
        raise ValueError(f"Failed to parse ground truth file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise TypeError(f"Ground truth file must contain a mapping, got {type(raw).__name__}")

    meta = _parse_meta(raw.get("meta"))
    cases = [_parse_case(c) for c in raw.get("cases", [])]
    return PlannerGroundTruth(meta=meta, cases=cases)


def save_ground_truth(gt: PlannerGroundTruth, path: Path) -> None:
    """Serialize planner ground truth to a YAML (or JSON) file.

    The output format is chosen by file extension: ``.json`` produces JSON;
    everything else produces YAML (requires PyYAML).

    Parameters:
        gt: The ground truth instance to persist.
        path: Destination file path.  Parent directories are created
            automatically.

    Raises:
        RuntimeError: If YAML output is requested but PyYAML is not installed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _serialize(gt)
    suffix = path.suffix.lower()

    if suffix == ".json":
        path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
        return

    if not _HAS_YAML:
        raise RuntimeError(
            "PyYAML is required to save YAML files. Install it with: pip install pyyaml"
        )

    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def find_case(gt: PlannerGroundTruth, decision_key: str) -> GroundTruthCase | None:
    """Look up a single ground-truth case by its decision key.

    Parameters:
        gt: The ground truth to search.
        decision_key: Exact decision key string.

    Returns:
        The matching ``GroundTruthCase``, or ``None`` if not found.
    """
    for case in gt.cases:
        if case.decision_key == decision_key:
            return case
    return None


def find_cases_by_capability(gt: PlannerGroundTruth, capability: str) -> list[GroundTruthCase]:
    """Filter ground-truth cases by capability name.

    Parameters:
        gt: The ground truth to search.
        capability: Capability string (e.g. ``PLAN``, ``GAP``).

    Returns:
        List of matching cases (may be empty).
    """
    return [c for c in gt.cases if c.capability == capability]
