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
    gap_severities: list[str] | None = None,
    touched_files_count: int = 0,
    introduces_external_dep: bool = False,
    introduces_infra: bool = False,
    cross_library_contract: bool = False,
    security_privacy_compliance: bool = False,
) -> ImpactClassification:
    """Classify the impact of a proposed change.

    All inputs are structural signals; no LLM reasoning is involved.

    Rules (evaluated top-down):
        * **HIGH** — ``cross_library_contract`` or ``introduces_infra``
          or ``introduces_external_dep`` or security/privacy/compliance signal.
        * **MEDIUM** — wider/localized scope signals such as high touched-file
          count, topology/boundary gap kinds, or critical blocking severities.
        * **LOW** — everything else.

    Blast radius and reversibility are derived from structural signals, then a
    final proportional-cost override applies: ``LOCAL`` + ``EASY`` downgrades
    to ``LOW`` unless a hard trigger is present.

    Args:
        layer: Current layer (``L1``, ``L2``, ``L3``).
        gap_kinds: Classification of gaps triggering the change.
        gap_severities: Gap severity labels (e.g. ``critical``, ``warning``).
        touched_files_count: Number of files affected.
        introduces_external_dep: Whether an external dependency is added.
        introduces_infra: Whether infrastructure is introduced.
        cross_library_contract: Whether the change crosses library boundaries.
        security_privacy_compliance: Whether the change introduces
            security/privacy/compliance implications.

    Returns:
        A fully-populated :class:`ImpactClassification`.
    """
    if gap_kinds is None:
        gap_kinds = []
    if gap_severities is None:
        gap_severities = []

    triggers: list[str] = []
    layer_upper = str(layer).upper()
    try:
        touched_files = max(int(touched_files_count), 0)
    except (TypeError, ValueError):
        touched_files = 0
    gap_lower = [str(g).strip().lower() for g in gap_kinds if str(g).strip()]
    severity_lower = [str(s).strip().lower() for s in gap_severities if str(s).strip()]
    medium_kinds = {"topology", "boundary"}
    critical_severity_tokens = {
        "critical",
        "blocking",
        "blocker",
        "high",
        "sev1",
        "sev-1",
        "p0",
        "p1",
    }

    # ------------------------------------------------------------------
    # Impact level
    # ------------------------------------------------------------------
    impact: str = "LOW"
    has_medium_kind = any(kind in medium_kinds for kind in gap_lower)
    has_critical_severity = any(severity in critical_severity_tokens for severity in severity_lower)

    if cross_library_contract:
        triggers.append("cross_library_contract")
    if introduces_infra:
        triggers.append("introduces_infra")
    if introduces_external_dep:
        triggers.append("introduces_external_dep")
    if security_privacy_compliance:
        triggers.append("security_privacy_compliance")
    if has_critical_severity:
        triggers.append("gap_severity_critical")
    if has_medium_kind:
        triggers.append("gap_kind_topology_or_boundary")
    if touched_files > 3:
        triggers.append(f"touched_files={touched_files}")
    if layer_upper == "L2" and touched_files > 1:
        triggers.append("layer_L2_multi_file")

    high_trigger = (
        cross_library_contract
        or introduces_infra
        or introduces_external_dep
        or security_privacy_compliance
    )
    medium_trigger = (
        touched_files > 3
        or has_medium_kind
        or has_critical_severity
        or (layer_upper == "L2" and touched_files > 1)
    )

    if high_trigger:
        impact = "HIGH"
    elif medium_trigger:
        impact = "MEDIUM"

    if not triggers:
        triggers.append("default_low")

    # ------------------------------------------------------------------
    # Blast radius
    # ------------------------------------------------------------------
    if cross_library_contract:
        blast_radius = "SYSTEM"
    elif introduces_infra or introduces_external_dep or security_privacy_compliance:
        blast_radius = "CROSS_SLICE"
    elif touched_files > 3 or has_medium_kind or (layer_upper == "L2" and touched_files > 1):
        blast_radius = "SLICE"
    else:
        blast_radius = "LOCAL"

    # ------------------------------------------------------------------
    # Reversibility
    # ------------------------------------------------------------------
    if introduces_infra or introduces_external_dep:
        reversibility = "HARD"
    elif (
        cross_library_contract
        or security_privacy_compliance
        or has_critical_severity
        or touched_files > 3
        or has_medium_kind
    ):
        reversibility = "MEDIUM"
    else:
        reversibility = "EASY"

    # Keep planning cost proportional for trivially scoped, easy-to-revert changes.
    if blast_radius == "LOCAL" and reversibility == "EASY" and not cross_library_contract:
        if impact != "LOW":
            triggers.append("local_easy_override")
        impact = "LOW"

    return ImpactClassification(
        impact=impact,  # type: ignore[arg-type]
        blast_radius=blast_radius,  # type: ignore[arg-type]
        reversibility=reversibility,  # type: ignore[arg-type]
        triggers=triggers,
    )
