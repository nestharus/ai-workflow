"""PRD input classifier: Determine if input is structured PRD or unstructured prose.

This module provides classification logic to route update-prd workflow correctly.
Uses deterministic heuristic classification.

Usage:
    python -m scripts.prd.classifier input.md

Output:
    Prints classification result: "PRD", "PROSE", or "AMBIGUOUS"
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class InputType(Enum):
    """Classification result for input type."""

    PRD = "prd"
    PROSE = "prose"
    AMBIGUOUS = "ambiguous"


@dataclass
class ClassificationResult:
    """Result of input classification.

    Attributes:
        input_type: Detected type (PRD, PROSE, or AMBIGUOUS).
        confidence: Confidence score (0.0-1.0) or None if using heuristics.
        method: Classification method used ("heuristic").
        reasoning: Explanation of classification decision.
    """

    input_type: InputType
    confidence: float | None
    method: str
    reasoning: str = ""

    def to_dict(self) -> dict[str, str | float | None]:
        """Convert to dictionary for JSON serialization."""
        return {
            "input_type": self.input_type.value,
            "confidence": self.confidence,
            "method": self.method,
            "reasoning": self.reasoning,
        }


# PRD section header patterns (precompiled, case-insensitive)
_PRD_SECTION_HEADERS = [
    re.compile(r"^##\s+resources?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+goal\s+list\s*$", re.IGNORECASE),
    re.compile(r"^##\s+goals?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+invariants?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+constraints?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+requirements?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+features?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+dependencies?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+assumptions?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+acceptance\s+criteria\s*$", re.IGNORECASE),
    re.compile(r"^##\s+user\s+stories?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+use\s+cases?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+functional\s+requirements?\s*$", re.IGNORECASE),
    re.compile(r"^##\s+non-functional\s+requirements?\s*$", re.IGNORECASE),
]

# Indexed ID patterns (precompiled, case-insensitive; e.g., RES-1, GOAL-123, INV-42)
_INDEXED_ID_PATTERNS = [
    re.compile(r"\bRES-\d+\b", re.IGNORECASE),
    re.compile(r"\bGOAL-\d+\b", re.IGNORECASE),
    re.compile(r"\bINV-\d+\b", re.IGNORECASE),
    re.compile(r"\bREQ-\d+\b", re.IGNORECASE),
    re.compile(r"\bFEAT-\d+\b", re.IGNORECASE),
    re.compile(r"\bCON-\d+\b", re.IGNORECASE),
    re.compile(r"\bDEP-\d+\b", re.IGNORECASE),
    re.compile(r"\bUSR-\d+\b", re.IGNORECASE),
    re.compile(r"\bUS-\d+\b", re.IGNORECASE),
    re.compile(r"\bUC-\d+\b", re.IGNORECASE),
    re.compile(r"\bFR-\d+\b", re.IGNORECASE),
    re.compile(r"\bNFR-\d+\b", re.IGNORECASE),
]

# Prose indicator patterns (precompiled, case-insensitive)
# Note: Patterns starting with '^' are applied per-line, others to full content
_PROSE_INDICATORS = [
    re.compile(r"\bi\s+think\b", re.IGNORECASE),
    re.compile(r"\bwe\s+should\b", re.IGNORECASE),
    re.compile(r"\bwe\s+need\b", re.IGNORECASE),
    re.compile(r"\bplease\s+add\b", re.IGNORECASE),
    re.compile(r"\bcan\s+you\b", re.IGNORECASE),
    re.compile(r"\bwould\s+be\s+nice\b", re.IGNORECASE),
    re.compile(r"\bi\s+want\b", re.IGNORECASE),
    re.compile(r"\bi\s+would\s+like\b", re.IGNORECASE),
    re.compile(r"\blet's\b", re.IGNORECASE),
    re.compile(r"\bmaybe\s+we\b", re.IGNORECASE),
    re.compile(r"\bhow\s+about\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+if\b", re.IGNORECASE),
    re.compile(r"\bcould\s+we\b", re.IGNORECASE),
    re.compile(r"\bshould\s+we\b", re.IGNORECASE),
    re.compile(r"^\s*add\s+", re.IGNORECASE),
    re.compile(r"^\s*change\s+", re.IGNORECASE),
    re.compile(r"^\s*update\s+", re.IGNORECASE),
    re.compile(r"^\s*remove\s+", re.IGNORECASE),
    re.compile(r"^\s*delete\s+", re.IGNORECASE),
    re.compile(r"^\s*modify\s+", re.IGNORECASE),
    re.compile(r"^\s*fix\s+", re.IGNORECASE),
    re.compile(r"^\s*implement\s+", re.IGNORECASE),
]


def _count_section_headers(content: str) -> int:
    """Count PRD section headers in content.

    Args:
        content: Text content to analyze.

    Returns:
        Number of PRD section headers found.
    """
    count = 0
    for line in content.split("\n"):
        stripped = line.strip()
        for pattern in _PRD_SECTION_HEADERS:
            if pattern.match(stripped):
                count += 1
                break  # Don't double-count a line
    return count


def _count_indexed_ids(content: str) -> int:
    """Count indexed IDs in content.

    Args:
        content: Text content to analyze.

    Returns:
        Number of indexed IDs found (unique occurrences).
    """
    all_ids: set[str] = set()
    for pattern in _INDEXED_ID_PATTERNS:
        matches = pattern.findall(content)
        all_ids.update(match.upper() for match in matches)
    return len(all_ids)


def _count_prose_indicators(content: str) -> int:
    r"""Count prose indicators in content.

    Pattern matching behavior differs based on anchoring:

    - Anchored patterns (starting with '^'): Evaluated against each line
      individually. Counts at most once per line even if the pattern could
      match multiple times on the same line. This is designed for command-like
      indicators (e.g., "add X", "remove Y") that typically appear at line start.

    - Non-anchored patterns: Applied via pattern.findall on the entire content,
      counting every occurrence. The same phrase appearing multiple times
      (whether on one line or across lines) is counted separately each time.

    Rationale: Line-anchored patterns like ``^\\s*add\\s+`` detect imperative
    commands at line beginnings, while conversational patterns like "we should"
    may appear anywhere and benefit from full occurrence counting.

    Args:
        content: Text content to analyze.

    Returns:
        Number of prose indicator matches found.
    """
    count = 0
    lines = content.split("\n")

    for pattern in _PROSE_INDICATORS:
        # Check if pattern starts with ^ (line-start anchor)
        if pattern.pattern.startswith("^"):
            # Apply to each line using pattern.match (explicit start-of-line matching)
            for line in lines:
                if pattern.match(line):
                    count += 1
        else:
            # Apply to whole content
            matches = pattern.findall(content)
            count += len(matches)

    return count


def classify_by_heuristics(content: str) -> ClassificationResult:
    """Classify input using deterministic heuristics.

    Decision logic:
        - 3+ section headers AND 5+ indexed IDs -> PRD
        - 3+ prose indicators AND <2 section headers -> PROSE
        - <2 section headers AND <3 indexed IDs -> PROSE
        - Otherwise -> AMBIGUOUS

    Args:
        content: Text content to classify.

    Returns:
        ClassificationResult with input_type, confidence, method, and reasoning.
    """
    section_count = _count_section_headers(content)
    id_count = _count_indexed_ids(content)
    prose_count = _count_prose_indicators(content)

    reasoning_parts = [
        f"section_headers={section_count}",
        f"indexed_ids={id_count}",
        f"prose_indicators={prose_count}",
    ]

    # Decision logic
    if section_count >= 3 and id_count >= 5:
        input_type = InputType.PRD
        reasoning_parts.append("decision: PRD (3+ headers AND 5+ IDs)")
    elif prose_count >= 3 and section_count < 2:
        input_type = InputType.PROSE
        reasoning_parts.append("decision: PROSE (3+ prose indicators AND <2 headers)")
    elif section_count < 2 and id_count < 3:
        input_type = InputType.PROSE
        reasoning_parts.append("decision: PROSE (<2 headers AND <3 IDs)")
    else:
        input_type = InputType.AMBIGUOUS
        reasoning_parts.append("decision: AMBIGUOUS (mixed signals)")

    return ClassificationResult(
        input_type=input_type,
        confidence=None,  # Heuristics don't provide confidence scores
        method="heuristic",
        reasoning="; ".join(reasoning_parts),
    )


def classify_input(content: str) -> ClassificationResult:
    """Classify input content as PRD, PROSE, or AMBIGUOUS.

    Currently uses heuristic classification. LLM integration can be added later.

    Args:
        content: Text content to classify.

    Returns:
        ClassificationResult with classification details.
    """
    return classify_by_heuristics(content)


def main() -> int:
    """CLI entry point.

    Reads input file from command line and prints classification result.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.prd.classifier <input_file>", file=sys.stderr)
        return 1

    input_path = Path(sys.argv[1])

    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        return 1

    try:
        content = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        print(f"Error: Failed to read file as UTF-8: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: Failed to read file: {e}", file=sys.stderr)
        return 1

    result = classify_input(content)

    # Print just the type value in uppercase
    print(result.input_type.value.upper())

    return 0


if __name__ == "__main__":
    sys.exit(main())
