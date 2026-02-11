"""Base types and helpers for planner eval scorers.

Provides the ``Verdict`` dataclass returned by every scorer and the
``CapabilityScorer`` protocol that all concrete scorers implement.
Also contains shared matching utilities used across scorers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Verdict:
    """Result of evaluating one decision against ground truth.

    Attributes:
        decision_key: Identifier for the decision being scored.
        trace_id: ID of the trace that produced the decision.
        capability: Name of the capability being evaluated.
        passed: Whether the decision passed all hard gates.
        score: Normalized score between 0.0 and 1.0.
        detail: Human-readable explanation of the verdict.
        hard_gate_failures: List of hard gate names that failed.
        soft_signal_warnings: List of soft signal names that triggered warnings.
    """

    decision_key: str = ""
    trace_id: str = ""
    capability: str = ""
    passed: bool = True
    score: float = 1.0
    detail: str = ""
    hard_gate_failures: list[str] = field(default_factory=list)
    soft_signal_warnings: list[str] = field(default_factory=list)


class CapabilityScorer(Protocol):
    """Protocol for per-capability scorers."""

    def score(self, trace: Any, gt_case: Any) -> Verdict: ...


# ------------------------------------------------------------------
# Shared matching helpers
# ------------------------------------------------------------------


def _matches_atom(intention: dict[str, Any], match_spec: dict[str, Any]) -> bool:
    """Check whether an intention dict matches a match specification.

    The match spec may contain any combination of the following keys.
    All present keys must match (AND semantics).

    - ``function_name_any_of``: intention["function_name"] must be in the list.
    - ``file_any_of``: intention["file"] must be in the list.
    - ``component_id_any_of``: intention["component_id"] must be in the list.
    - ``function_name_regex``: regex must match intention["function_name"].
    - ``description_contains``: substring must appear in intention["description"].

    Args:
        intention: Dict representing a single planner intention/output.
        match_spec: Dict of match criteria.

    Returns:
        True if every criterion in match_spec is satisfied.
    """
    if not match_spec:
        return False

    checks: list[bool] = []

    if "function_name_any_of" in match_spec:
        fn_name = intention.get("function_name", "")
        checks.append(fn_name in match_spec["function_name_any_of"])

    if "file_any_of" in match_spec:
        file_val = intention.get("file", "")
        checks.append(file_val in match_spec["file_any_of"])

    if "component_id_any_of" in match_spec:
        comp_id = intention.get("component_id", "")
        checks.append(comp_id in match_spec["component_id_any_of"])

    if "function_name_regex" in match_spec:
        fn_name = intention.get("function_name", "")
        pattern = match_spec["function_name_regex"]
        checks.append(bool(re.search(pattern, fn_name)))

    if "description_contains" in match_spec:
        description = intention.get("description", "")
        substring = match_spec["description_contains"]
        checks.append(substring.lower() in description.lower())

    # If no recognised keys were present, nothing can match.
    if not checks:
        return False

    return all(checks)
