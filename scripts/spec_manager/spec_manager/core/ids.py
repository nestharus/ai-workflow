"""ID validation utilities for spec management.

Canonical ID formats:
- Patch: P# (e.g., P1, P10)
- Patch section: P#.# (e.g., P8.10)
- Patch invariant: P#I# (e.g., P6I5)
- Patch claim: P#C# (e.g., P4C3)
- Library: LIB-#### (e.g., LIB-0001)
- Requirement: REQ-#### or REQ-LIB-####-#### (e.g., REQ-0001, REQ-LIB-0001-0042)
- Algorithm: Algorithm # (1-67+)
- Invariant: I# (e.g., I1, I5) - replaces Goals
- Goal (legacy): G# (e.g., G6, G8) - prefer I#
- Claim (global): C#
- Statement: S#
- Topic: T#
- Component: Comp#
- Data structure: D#
- Lean skeleton: Lean#
- Non-functional goal: NFG#
- Gap: Gap G#.#
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class IdCategory(Enum):
    """Categories of IDs in spec files."""

    ALGORITHM = "algorithm"
    COMPONENT = "component"
    DATA_STRUCTURE = "data_structure"
    INVARIANT = "invariant"  # New: I# pattern
    GOAL = "goal"  # Legacy: G# pattern (prefer INVARIANT)
    CLAIM = "claim"
    STATEMENT = "statement"
    TOPIC = "topic"
    PATCH = "patch"
    PATCH_SECTION = "patch_section"
    PATCH_INVARIANT = "patch_invariant"
    PATCH_CLAIM = "patch_claim"
    LEAN = "lean"
    NON_FUNCTIONAL_GOAL = "non_functional_goal"
    GAP = "gap"
    LIBRARY = "library"
    REQUIREMENT = "requirement"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IdPattern:
    """A pattern for validating IDs."""

    pattern: re.Pattern[str]
    category: IdCategory
    description: str


class IdValidator:
    """Validator for spec IDs."""

    # Ordered from most specific to least specific
    PATTERNS: ClassVar[list[IdPattern]] = [
        IdPattern(
            re.compile(r"^Algorithm \d+$"),
            IdCategory.ALGORITHM,
            "Algorithm # (e.g., Algorithm 1)",
        ),
        IdPattern(
            re.compile(r"^Comp\d+$"),
            IdCategory.COMPONENT,
            "Comp# (e.g., Comp1)",
        ),
        IdPattern(
            re.compile(r"^D\d+$"),
            IdCategory.DATA_STRUCTURE,
            "D# (e.g., D10)",
        ),
        IdPattern(
            re.compile(r"^I\d+\.\d+$"),
            IdCategory.INVARIANT,
            "I#.# (e.g., I1.2) - sub-invariant",
        ),
        IdPattern(
            re.compile(r"^I\d+$"),
            IdCategory.INVARIANT,
            "I# (e.g., I1) - invariant",
        ),
        IdPattern(
            re.compile(r"^G\d+\.\d+$"),
            IdCategory.GOAL,
            "G#.# (e.g., G1.2) - sub-goal (legacy, prefer I#)",
        ),
        IdPattern(
            re.compile(r"^G\d+$"),
            IdCategory.GOAL,
            "G# (e.g., G6) - goal (legacy, prefer I#)",
        ),
        IdPattern(
            re.compile(r"^C\d+$"),
            IdCategory.CLAIM,
            "C# (e.g., C1) - global claim",
        ),
        IdPattern(
            re.compile(r"^S\d+$"),
            IdCategory.STATEMENT,
            "S# (e.g., S1)",
        ),
        IdPattern(
            re.compile(r"^T\d+$"),
            IdCategory.TOPIC,
            "T# (e.g., T1)",
        ),
        IdPattern(
            re.compile(r"^P\d+I\d+$"),
            IdCategory.PATCH_INVARIANT,
            "P#I# (e.g., P6I5) - patch invariant",
        ),
        IdPattern(
            re.compile(r"^P\d+C\d+$"),
            IdCategory.PATCH_CLAIM,
            "P#C# (e.g., P4C3) - patch claim",
        ),
        IdPattern(
            re.compile(r"^P\d+\.\d+$"),
            IdCategory.PATCH_SECTION,
            "P#.# (e.g., P8.10) - patch section",
        ),
        IdPattern(
            re.compile(r"^Lean\d+$"),
            IdCategory.LEAN,
            "Lean# (e.g., Lean9)",
        ),
        IdPattern(
            re.compile(r"^NFG\d+$"),
            IdCategory.NON_FUNCTIONAL_GOAL,
            "NFG# (e.g., NFG1)",
        ),
        IdPattern(
            re.compile(r"^Gap G\d+\.\d+$"),
            IdCategory.GAP,
            "Gap G#.# (e.g., Gap G1.2)",
        ),
        IdPattern(
            re.compile(r"^LIB-\d{4}$"),
            IdCategory.LIBRARY,
            "LIB-#### (e.g., LIB-0001) - library identifier",
        ),
        IdPattern(
            re.compile(r"^REQ-LIB-\d{4}-\d{4}$"),
            IdCategory.REQUIREMENT,
            "REQ-LIB-####-#### (e.g., REQ-LIB-0001-0042) - library-scoped requirement",
        ),
        IdPattern(
            re.compile(r"^REQ-\d{4}$"),
            IdCategory.REQUIREMENT,
            "REQ-#### (e.g., REQ-0001) - global requirement",
        ),
        IdPattern(
            re.compile(r"^P\d+$"),
            IdCategory.PATCH,
            "P# (e.g., P1, P10) - patch identifier",
        ),
    ]

    def is_valid(self, id_value: str) -> bool:
        """Check if an ID matches any known pattern."""
        return any(p.pattern.match(id_value) for p in self.PATTERNS)

    def get_category(self, id_value: str) -> IdCategory:
        """Get the category of an ID."""
        for pattern in self.PATTERNS:
            if pattern.pattern.match(id_value):
                return pattern.category
        return IdCategory.UNKNOWN

    def get_pattern_description(self, id_value: str) -> str | None:
        """Get the description of the pattern matching an ID."""
        for pattern in self.PATTERNS:
            if pattern.pattern.match(id_value):
                return pattern.description
        return None

    def extract_numbers(self, id_value: str) -> dict[str, int]:
        """Extract numeric components from an ID.

        Examples:
            "Algorithm 1" -> {"number": 1}
            "P6I5" -> {"patch": 6, "invariant": 5}
            "G1.2" -> {"goal": 1, "subgoal": 2}
        """
        result: dict[str, int] = {}

        # Algorithm #
        if match := re.match(r"^Algorithm (\d+)$", id_value):
            result["number"] = int(match.group(1))
        # LIB-####
        elif match := re.match(r"^LIB-(\d{4})$", id_value):
            result["library"] = int(match.group(1))
        # REQ-LIB-####-####
        elif match := re.match(r"^REQ-LIB-(\d{4})-(\d{4})$", id_value):
            result["library"] = int(match.group(1))
            result["requirement"] = int(match.group(2))
        # REQ-####
        elif match := re.match(r"^REQ-(\d{4})$", id_value):
            result["requirement"] = int(match.group(1))
        # P#I#
        elif match := re.match(r"^P(\d+)I(\d+)$", id_value):
            result["patch"] = int(match.group(1))
            result["invariant"] = int(match.group(2))
        # P#C#
        elif match := re.match(r"^P(\d+)C(\d+)$", id_value):
            result["patch"] = int(match.group(1))
            result["claim"] = int(match.group(2))
        # P#.#
        elif match := re.match(r"^P(\d+)\.(\d+)$", id_value):
            result["patch"] = int(match.group(1))
            result["section"] = int(match.group(2))
        # I#.# (invariant with sub-number)
        elif match := re.match(r"^I(\d+)\.(\d+)$", id_value):
            result["invariant"] = int(match.group(1))
            result["sub"] = int(match.group(2))
        # G#.# (legacy goal with sub-number)
        elif match := re.match(r"^G(\d+)\.(\d+)$", id_value):
            result["goal"] = int(match.group(1))
            result["subgoal"] = int(match.group(2))
        # Gap G#.#
        elif match := re.match(r"^Gap G(\d+)\.(\d+)$", id_value):
            result["goal"] = int(match.group(1))
            result["gap"] = int(match.group(2))
        # Simple patterns: I#, G#, C#, S#, T#, D#, Comp#, Lean#, NFG#, P#
        elif match := re.match(r"^(I|G|C|S|T|D|Comp|Lean|NFG|P)(\d+)$", id_value):
            result["number"] = int(match.group(2))

        return result

    def sort_key(self, id_value: str) -> tuple[int, str, int, int]:
        """Generate a sort key for ordering IDs.

        Returns tuple of (category_order, prefix, primary_num, secondary_num)
        """
        category = self.get_category(id_value)
        numbers = self.extract_numbers(id_value)

        # Category ordering (invariants first, then legacy goals)
        category_order = {
            IdCategory.INVARIANT: 0,  # New invariants first
            IdCategory.GOAL: 1,  # Legacy goals
            IdCategory.ALGORITHM: 2,
            IdCategory.DATA_STRUCTURE: 3,
            IdCategory.COMPONENT: 4,
            IdCategory.CLAIM: 5,
            IdCategory.STATEMENT: 6,
            IdCategory.TOPIC: 7,
            IdCategory.LEAN: 8,
            IdCategory.NON_FUNCTIONAL_GOAL: 9,
            IdCategory.PATCH: 10,
            IdCategory.PATCH_SECTION: 11,
            IdCategory.PATCH_INVARIANT: 12,
            IdCategory.PATCH_CLAIM: 13,
            IdCategory.GAP: 14,
            IdCategory.LIBRARY: 15,
            IdCategory.REQUIREMENT: 16,
            IdCategory.UNKNOWN: 99,
        }

        order = category_order.get(category, 99)
        prefix = id_value.split()[0] if " " in id_value else id_value.rstrip("0123456789")

        primary = numbers.get("number", numbers.get("patch", numbers.get("goal", 0)))
        secondary = numbers.get(
            "invariant", numbers.get("claim", numbers.get("section", numbers.get("subgoal", 0)))
        )
        if category == IdCategory.LIBRARY:
            primary = numbers.get("library", 0)
            secondary = 0
        elif category == IdCategory.REQUIREMENT:
            if "library" in numbers:
                primary = numbers.get("library", 0)
                secondary = numbers.get("requirement", 0)
            else:
                primary = numbers.get("requirement", 0)
                secondary = 0

        return (order, prefix, primary, secondary)
