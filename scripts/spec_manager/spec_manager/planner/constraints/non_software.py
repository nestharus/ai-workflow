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

_NON_SOFTWARE_DIMENSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "legal": (
        "legal",
        "license",
        "licensing",
        "compliance",
        "regulation",
        "regulatory",
        "contract",
        "gdpr",
        "hipaa",
        "soc2",
        "pci",
        "privacy",
    ),
    "economic": (
        "economic",
        "cost",
        "budget",
        "pricing",
        "fee",
        "spend",
        "expense",
        "roi",
        "tco",
        "vendor lock-in",
    ),
    "organizational": (
        "organizational",
        "team",
        "staff",
        "staffing",
        "headcount",
        "owner",
        "ownership",
        "hiring",
        "onboarding",
        "capacity",
        "support",
    ),
    "temporal": (
        "temporal",
        "timeline",
        "deadline",
        "deprecation",
        "sunset",
        "migration window",
        "schedule",
        "rollout date",
        "eol",
    ),
    "operational": (
        "operational",
        "operations",
        "runbook",
        "on-call",
        "incident",
        "uptime",
        "sla",
        "slo",
        "deployment",
        "monitoring",
        "maintenance",
    ),
}


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
    if not signaled_dimensions and str(impact).strip().upper() == "HIGH":
        signaled_dimensions = set(NON_SOFTWARE_DIMENSIONS)
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

    combined_text = f"{gap_text} {context_text}".strip()
    return {
        dimension
        for dimension in NON_SOFTWARE_DIMENSIONS
        if _is_dimension_signaled(combined_text, dimension)
    }


def _is_dimension_signaled(text: str, dimension: str) -> bool:
    if not text:
        return False
    keywords = _NON_SOFTWARE_DIMENSION_KEYWORDS.get(dimension, ())
    return any(keyword in text for keyword in keywords)
