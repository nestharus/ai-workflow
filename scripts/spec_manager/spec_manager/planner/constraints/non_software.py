"""Non-software constraint checklist helpers.

Extracts reusable detection and checklist generation so planners and
strategies can share one domain-authoritative implementation.
"""

from __future__ import annotations

import json
from typing import Any

from spec_manager.planner.constraints.types import DecisionRequirement

NON_SOFTWARE_DIMENSIONS: tuple[str, ...] = (
    "legal",
    "economic",
    "organizational",
    "temporal",
    "operational",
)


def build_non_software_checklist_requirements(
    *,
    gaps: list[dict[str, Any]],
    context: dict[str, Any],
    existing_requirements: list[DecisionRequirement],
    impact: str,
) -> list[DecisionRequirement]:
    """Build missing checklist requirements for signaled non-software dimensions."""
    existing_dimensions = {
        str(requirement.dimension).strip().lower()
        for requirement in existing_requirements
        if str(requirement.dimension).strip()
    }
    signaled_dimensions = detect_non_software_dimensions(gaps=gaps, context=context)
    if not signaled_dimensions:
        return []

    requirements: list[DecisionRequirement] = []
    for dimension in NON_SOFTWARE_DIMENSIONS:
        if dimension not in signaled_dimensions or dimension in existing_dimensions:
            continue
        requirements.append(
            DecisionRequirement(
                decision_id=f"NSC-{dimension.upper()[:4]}",
                question=f"Has the {dimension} dimension been considered for this change?",
                kind="non_software_checklist",
                dimension=dimension,
                scope=str(context.get("scope", "intra:LIB") or "intra:LIB"),
                impact=str(impact or "MEDIUM"),
                options=["yes_addressed", "not_applicable", "needs_review"],
                needed_for=[str(context.get("slice_id", "unknown") or "unknown")],
            )
        )
    return requirements


def detect_non_software_dimensions(
    *,
    gaps: list[dict[str, Any]],
    context: dict[str, Any],
) -> set[str]:
    """Return dimensions explicitly signaled in gaps or planning context."""
    gap_text = " ".join(
        f"{str(gap.get('description', '')).strip()} {str(gap.get('target', '')).strip()}"
        for gap in gaps
    ).lower()
    try:
        context_text = json.dumps(context, default=str).lower() if context else ""
    except (TypeError, ValueError):
        context_text = str(context).lower()

    return {
        dimension
        for dimension in NON_SOFTWARE_DIMENSIONS
        if dimension in gap_text or dimension in context_text
    }
