"""Deterministic impact classifier for constraint-related changes.

Fully deterministic — no LLM calls.  Classifies the impact, blast radius,
and reversibility of a proposed change based on structural signals.
"""

from __future__ import annotations

from spec_manager.planner.constraints.types import ImpactClassification


def classify_impact(
    *,
    layer: str,
    gap_kinds: list[str] | None = None,
    touched_files_count: int = 0,
    introduces_external_dep: bool = False,
    introduces_infra: bool = False,
    cross_library_contract: bool = False,
) -> ImpactClassification:
    """Classify the impact of a proposed change.

    All inputs are structural signals; no LLM reasoning is involved.

    Rules (evaluated top-down, first match sets *impact*):
        * **HIGH** — ``cross_library_contract`` or ``introduces_infra``
          or ``introduces_external_dep``.
        * **MEDIUM** — layer is ``L2``, or ``touched_files_count > 3``,
          or *gap_kinds* contain ``topology`` or ``boundary``.
        * **LOW** — everything else.

    Blast radius and reversibility are derived from the impact level and
    the specific triggers.

    Args:
        layer: Current layer (``L1``, ``L2``, ``L3``).
        gap_kinds: Classification of gaps triggering the change.
        touched_files_count: Number of files affected.
        introduces_external_dep: Whether an external dependency is added.
        introduces_infra: Whether infrastructure is introduced.
        cross_library_contract: Whether the change crosses library boundaries.

    Returns:
        A fully-populated :class:`ImpactClassification`.
    """
    if gap_kinds is None:
        gap_kinds = []

    triggers: list[str] = []

    # ------------------------------------------------------------------
    # Impact level
    # ------------------------------------------------------------------
    impact: str = "LOW"

    if cross_library_contract:
        impact = "HIGH"
        triggers.append("cross_library_contract")
    if introduces_infra:
        impact = "HIGH"
        triggers.append("introduces_infra")
    if introduces_external_dep:
        impact = "HIGH"
        triggers.append("introduces_external_dep")

    if impact != "HIGH":
        if layer.upper() == "L2":
            impact = "MEDIUM"
            triggers.append("layer_L2")
        if touched_files_count > 3:
            impact = "MEDIUM"
            triggers.append(f"touched_files={touched_files_count}")

        gap_lower = [g.lower() for g in gap_kinds]
        if "topology" in gap_lower:
            impact = "MEDIUM"
            triggers.append("gap_topology")
        if "boundary" in gap_lower:
            impact = "MEDIUM"
            triggers.append("gap_boundary")

    if not triggers:
        triggers.append("default_low")

    # ------------------------------------------------------------------
    # Blast radius
    # ------------------------------------------------------------------
    if cross_library_contract:
        blast_radius = "SYSTEM"
    elif impact == "HIGH":
        blast_radius = "CROSS_SLICE"
    elif impact == "MEDIUM":
        blast_radius = "SLICE"
    else:
        blast_radius = "LOCAL"

    # ------------------------------------------------------------------
    # Reversibility
    # ------------------------------------------------------------------
    if introduces_infra or introduces_external_dep:
        reversibility = "HARD"
    elif cross_library_contract or impact == "HIGH" or impact == "MEDIUM":
        reversibility = "MEDIUM"
    else:
        reversibility = "EASY"

    return ImpactClassification(
        impact=impact,  # type: ignore[arg-type]
        blast_radius=blast_radius,  # type: ignore[arg-type]
        reversibility=reversibility,  # type: ignore[arg-type]
        triggers=triggers,
    )
