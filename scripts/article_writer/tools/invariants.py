"""Dynamic invariant extraction and enforcement for article writing.

This module uses LLM agents to:
1. Extract invariants from briefs (any constraint, not just hardcoded ones)
2. Verify drafts against extracted invariants
3. Apply fixes where possible

The system is fully dynamic - it can handle ANY invariant the user specifies,
not just pre-programmed patterns like "no markdown" or "3000 characters".
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Invariant:
    """A single invariant constraint extracted from brief."""

    name: str
    description: str
    check_type: str  # count, pattern, semantic, format
    operator: str  # max, min, equals, contains, excludes, matches
    value: Any  # The constraint value
    auto_fixable: bool = False
    fix_hint: str | None = None
    source: str = "brief"  # brief, platform, workflow


@dataclass
class InvariantCheck:
    """Result of checking a single invariant."""

    invariant: str
    status: str  # pass, fail, fixed
    details: str
    location: str | None = None
    original: str | None = None
    fixed: str | None = None


@dataclass
class InvariantResult:
    """Complete result from invariant review."""

    checks: list[InvariantCheck] = field(default_factory=list)
    revised_draft: str = ""
    unfixable_violations: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    @property
    def has_unfixable(self) -> bool:
        """Return True if there are unfixable violations."""
        return len(self.unfixable_violations) > 0

    @property
    def all_passed(self) -> bool:
        """Return True if all checks passed or were fixed."""
        return all(c.status in ("pass", "fixed") for c in self.checks)


class DynamicInvariantSystem:
    """LLM-based invariant extraction and verification.

    Instead of hardcoded patterns, this system:
    1. Uses an LLM to extract invariants from ANY brief
    2. Uses an LLM to verify ANY invariant against a draft
    3. Uses an LLM to fix violations where possible

    The LLM can handle constraints like:
    - "no passive voice"
    - "ANSI characters only"
    - "conversational but professional tone"
    - "max 500 words"
    - Any other constraint the user can express
    """

    def __init__(
        self,
        llm_runner: Callable[[str, Path, str], str],
        package_root: Path,
        workspace: Path,
    ) -> None:
        """Initialize the system.

        Args:
            llm_runner: Function to run LLM prompts (prompt, workspace, label) -> output
            package_root: Root of the article writer package (for agent templates)
            workspace: Current workspace directory
        """
        self.llm_runner = llm_runner
        self.package_root = package_root
        self.workspace = workspace
        self._extracted_invariants: list[Invariant] = []

    def extract_invariants(
        self,
        brief: dict[str, Any],
        platform: str | None = None,
        discovered_requirements: list[str] | None = None,
    ) -> list[Invariant]:
        """Extract invariants from brief using LLM.

        This can extract ANY constraint, not just predefined ones.
        """
        template_path = self.package_root / "agents" / "10_invariant_extractor.md"
        template = template_path.read_text(encoding="utf-8")

        # Build prompt
        sections = {
            "BRIEF": "```json\n" + json.dumps(brief, indent=2, ensure_ascii=False) + "\n```",
            "PLATFORM": platform or brief.get("venue", "unknown"),
            "DISCOVERED_REQUIREMENTS": "\n".join(discovered_requirements or []) or "(none)",
        }

        prompt = template.rstrip()
        for title, content in sections.items():
            prompt += f"\n\n## {title}\n{content}"

        # Run LLM
        output = self.llm_runner(prompt, self.workspace, "invariant_extractor")

        # Parse response
        invariants = self._parse_extractor_output(output)
        self._extracted_invariants = invariants

        # Save for debugging
        inv_path = self.workspace / "analysis" / "extracted_invariants.json"
        inv_path.parent.mkdir(parents=True, exist_ok=True)
        inv_path.write_text(
            json.dumps(
                [
                    {
                        "name": i.name,
                        "description": i.description,
                        "check_type": i.check_type,
                        "operator": i.operator,
                        "value": i.value,
                        "auto_fixable": i.auto_fixable,
                        "fix_hint": i.fix_hint,
                    }
                    for i in invariants
                ],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        return invariants

    def verify_and_fix(
        self,
        draft: str,
        invariants: list[Invariant] | None = None,
        brief: dict[str, Any] | None = None,
    ) -> InvariantResult:
        """Verify draft against invariants and fix violations.

        Uses LLM to check ANY invariant - not limited to predefined patterns.
        """
        if invariants is None:
            invariants = self._extracted_invariants

        if not invariants:
            return InvariantResult(
                checks=[],
                revised_draft=draft,
                summary={"total": 0, "passed": 0, "failed": 0, "fixed": 0},
            )

        template_path = self.package_root / "agents" / "09_invariant_reviewer.md"
        template = template_path.read_text(encoding="utf-8")

        # Build prompt
        invariants_json = [
            {
                "name": i.name,
                "description": i.description,
                "check_type": i.check_type,
                "operator": i.operator,
                "value": i.value,
                "auto_fixable": i.auto_fixable,
                "fix_hint": i.fix_hint,
            }
            for i in invariants
        ]

        sections = {
            "DRAFT": draft,
            "INVARIANTS": "```json\n" + json.dumps(invariants_json, indent=2) + "\n```",
            "BRIEF": "```json\n" + json.dumps(brief or {}, indent=2) + "\n```",
        }

        prompt = template.rstrip()
        for title, content in sections.items():
            prompt += f"\n\n## {title}\n{content}"

        # Run LLM
        output = self.llm_runner(prompt, self.workspace, "invariant_reviewer")

        # Parse response
        result = self._parse_reviewer_output(output, draft)

        # Save for debugging
        result_path = self.workspace / "analysis" / "invariant_review.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "checks": [
                        {
                            "invariant": c.invariant,
                            "status": c.status,
                            "details": c.details,
                            "location": c.location,
                        }
                        for c in result.checks
                    ],
                    "summary": result.summary,
                    "unfixable_violations": result.unfixable_violations,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        return result

    def _parse_extractor_output(self, output: str) -> list[Invariant]:
        """Parse invariant extractor LLM output."""
        # Extract JSON from output
        json_match = re.search(r"```json\s*\n(.*?)\n```", output, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON
            json_str = output.strip()
            if json_str.startswith("{"):
                pass  # Use as-is
            else:
                return []

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        invariants = []
        for inv in data.get("invariants", []):
            invariants.append(
                Invariant(
                    name=inv.get("name", "unnamed"),
                    description=inv.get("description", ""),
                    check_type=inv.get("check_type", "semantic"),
                    operator=inv.get("operator", "matches"),
                    value=inv.get("value"),
                    auto_fixable=inv.get("auto_fixable", False),
                    fix_hint=inv.get("fix_hint"),
                )
            )

        return invariants

    def _parse_reviewer_output(self, output: str, original_draft: str) -> InvariantResult:
        """Parse invariant reviewer LLM output."""
        # Extract JSON from output
        json_match = re.search(r"```json\s*\n(.*?)\n```", output, re.DOTALL)
        json_str = json_match.group(1) if json_match else output.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # If parsing fails, return original draft as-is
            return InvariantResult(
                checks=[],
                revised_draft=original_draft,
                summary={"total": 0, "passed": 0, "failed": 0, "fixed": 0},
            )

        checks = []
        for c in data.get("checks", []):
            checks.append(
                InvariantCheck(
                    invariant=c.get("invariant", ""),
                    status=c.get("status", "fail"),
                    details=c.get("details", ""),
                    location=c.get("location"),
                    original=c.get("original"),
                    fixed=c.get("fixed"),
                )
            )

        return InvariantResult(
            checks=checks,
            revised_draft=data.get("revised_draft", original_draft),
            unfixable_violations=data.get("unfixable_violations", []),
            summary=data.get("summary", {}),
        )


# =============================================================================
# Legacy compatibility functions
# =============================================================================
# These provide backwards compatibility with the old hardcoded system.
# They are DEPRECATED - use DynamicInvariantSystem instead.


@dataclass
class InvariantSet:
    """DEPRECATED: Use DynamicInvariantSystem instead.

    This is kept for backwards compatibility only.
    """

    invariants: list[Invariant] = field(default_factory=list)
    platform: str | None = None
    max_characters: int | None = None
    max_words: int | None = None

    def add(self, invariant: Invariant) -> None:
        """Add an invariant to the set."""
        self.invariants.append(invariant)

    def to_prompt_section(self) -> str:
        """Format invariants as a prompt section."""
        lines = ["## Invariants (MUST be enforced)", ""]
        if self.max_characters:
            lines.append(f"- Maximum {self.max_characters} characters")
        """Format invariants as a prompt section."""
        """Format invariants as a prompt section."""
        if self.max_words:
            lines.append(f"- Maximum {self.max_words} words")
        if self.platform:
            lines.append(f"- Platform: {self.platform}")
        for inv in self.invariants:
            lines.append(f"- {inv.description}")
        return "\n".join(lines)


@dataclass
class InvariantViolation:
    """DEPRECATED: Use InvariantCheck instead."""

    invariant: Invariant
    message: str
    location: str | None = None
    fixable: bool = False
    suggested_fix: str | None = None


def extract_invariants_from_brief(brief: dict[str, Any]) -> InvariantSet:
    """DEPRECATED: Use DynamicInvariantSystem.extract_invariants instead.

    This function provides minimal backwards compatibility by extracting
    obvious invariants from the brief structure. It does NOT use LLM
    and cannot handle arbitrary constraints.
    """
    inv_set = InvariantSet()

    venue = brief.get("venue", "").lower()
    inv_set.platform = venue

    constraints = brief.get("constraints", {})

    max_chars = constraints.get("max_characters")
    if max_chars:
        inv_set.max_characters = max_chars
        inv_set.add(
            Invariant(
                name="max_characters",
                description=f"Maximum {max_chars} characters",
                check_type="count",
                operator="max",
                value=max_chars,
                auto_fixable=False,
                source="brief",
            )
        )

    format_restrictions = constraints.get("format_restrictions", [])
    for restriction in format_restrictions:
        inv_set.add(
            Invariant(
                name=restriction.lower().replace(" ", "_"),
                description=restriction,
                check_type="semantic",  # Let LLM interpret
                operator="matches",
                value=restriction,
                auto_fixable=True,
                source="brief",
            )
        )

    return inv_set


def check_all_invariants(text: str, inv_set: InvariantSet) -> list[InvariantViolation]:
    """DEPRECATED: Use DynamicInvariantSystem.verify_and_fix instead.

    This minimal implementation only checks character count.
    All other invariants should be checked by the LLM.
    """
    violations = []

    # Only check character count locally (everything else is LLM's job)
    if inv_set.max_characters:
        char_count = len(text)
        if char_count > inv_set.max_characters:
            inv = next((i for i in inv_set.invariants if i.name == "max_characters"), None)
            if inv:
                violations.append(
                    InvariantViolation(
                        invariant=inv,
                        message=(
                            f"Text is {char_count} characters, max is {inv_set.max_characters} "
                            f"({char_count - inv_set.max_characters} over)"
                        ),
                        fixable=False,
                    )
                )

    return violations


def apply_fixes(text: str, violations: list[InvariantViolation]) -> str:
    """DEPRECATED: Use DynamicInvariantSystem.verify_and_fix instead.

    The LLM-based system handles fixes directly.
    This function is a no-op for backwards compatibility.
    """
    return text
