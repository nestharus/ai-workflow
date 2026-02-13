"""Section-type semantics for PDD spec sections.

Defines who each section is for, what it should contain, and provides
light heuristic helpers for content validation.
"""

from __future__ import annotations

# --- Heuristic keyword lists ---
# Keywords that suggest implementation-level detail (algorithms, code).
# Function definition keywords are sourced from core.language.FUNCTION_KEYWORDS.
from spec_manager.core.language import FUNCTION_KEYWORDS as _FUNC_KW

# --- Audience ---
# Who should read each section.
SECTION_AUDIENCE: dict[str, str] = {
    "Overview": "everyone",
    "Constraints": "planners",
    "Analysis": "planners",
    "Details": "implementors",
}

# --- Purpose ---
# What kind of content belongs in each section.
SECTION_PURPOSE: dict[str, str] = {
    "Overview": "composition_glue",
    "Constraints": "planning_priorities",
    "Analysis": "decision_history",
    "Details": "implementation_specifics",
}

# Convenience sets for role-based filtering.
PLANNER_SECTIONS: frozenset[str] = frozenset({"Analysis", "Constraints", "Overview"})
IMPLEMENTOR_SECTIONS: frozenset[str] = frozenset({"Details", "Overview"})

_IMPLEMENTATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "algorithm",
        "iterate",
        "loop",
        "step 1",
        "step 2",
        "step 3",
        "pseudocode",
        "function(",
        *_FUNC_KW,
        "return ",
        "parse(",
        "for each",
        "while ",
        "if (",
    }
)

# Keywords that suggest architectural rationale (belongs in Analysis).
_RATIONALE_KEYWORDS: frozenset[str] = frozenset(
    {
        "because",
        "rationale",
        "tradeoff",
        "trade-off",
        "we chose",
        "decision:",
        "alternative",
        "rejected because",
        "considered",
        "pros and cons",
    }
)

# Keywords that suggest requirements / directives (belongs in Details).
_REQUIREMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "must",
        "shall",
        "required",
        "mandatory",
        "the system will",
        "the service shall",
        "when a ",
        "if the ",
    }
)

# Keywords that suggest planning constraints.
_CONSTRAINT_KEYWORDS: frozenset[str] = frozenset(
    {
        "priority",
        "ordering",
        "before",
        "after",
        "dependency",
        "blocked by",
        "prerequisite",
        "deadline",
    }
)


def _has_keywords(text: str, keywords: frozenset[str]) -> list[str]:
    """Return matched keywords found in *text* (case-insensitive)."""
    lower = text.lower()
    return [kw for kw in keywords if kw in lower]


def validate_section_content(section: str, content: str) -> list[str]:
    """Return warnings when *content* appears misplaced for *section*.

    Uses lightweight keyword scanning (no LLM calls).  Returns an empty
    list when nothing looks wrong.
    """
    warnings: list[str] = []

    if section == "Overview":
        hits = _has_keywords(content, _IMPLEMENTATION_KEYWORDS)
        if len(hits) >= 2:
            sample = ", ".join(hits[:3])
            warnings.append(
                f"Overview contains implementation-level detail "
                f"(matched: {sample}). Consider moving to Details."
            )

    elif section == "Constraints":
        hits = _has_keywords(content, _REQUIREMENT_KEYWORDS)
        if len(hits) >= 2:
            sample = ", ".join(hits[:3])
            warnings.append(
                f"Constraints contains requirement language "
                f"(matched: {sample}). Consider moving to Details."
            )

    elif section == "Analysis":
        # Analysis should be decision records, not directives.
        directive_hits = _has_keywords(content, _REQUIREMENT_KEYWORDS)
        rationale_hits = _has_keywords(content, _RATIONALE_KEYWORDS)
        if len(directive_hits) >= 2 and len(rationale_hits) == 0:
            sample = ", ".join(directive_hits[:3])
            warnings.append(
                f"Analysis contains directives rather than decision records "
                f"(matched: {sample}). Consider moving directives to Details."
            )

    elif section == "Details":
        hits = _has_keywords(content, _RATIONALE_KEYWORDS)
        if len(hits) >= 2:
            sample = ", ".join(hits[:3])
            warnings.append(
                f"Details contains architectural rationale "
                f"(matched: {sample}). Consider moving to Analysis."
            )

    return warnings
