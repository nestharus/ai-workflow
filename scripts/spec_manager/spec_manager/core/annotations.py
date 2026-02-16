"""Annotation parsing utilities for spec management.

Canonical annotation syntax:
- Declaration: ([=ID]) - declares that a section belongs to this ID
- Reference (related): (@[+ID]) - contextual reference (mentions)
- Reference (labeled): (@[=ID]) - labeled reference (belongs to)
- Invariant ref: (@[!I#]) - references an invariant this element enforces
- Pin to artifact: (@pin path:symbol) - pins spec element to artifact location
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class AnnotationType(Enum):
    """Types of annotations in spec files."""

    DECLARATION = "declaration"  # ([=ID])
    REFERENCE_RELATED = "reference_related"  # (@[+ID])
    REFERENCE_LABELED = "reference_labeled"  # (@[=ID])
    INVARIANT_REF = "invariant_ref"  # (@[!I#])
    PIN = "pin"  # (@pin path:symbol)


@dataclass(frozen=True)
class Annotation:
    """An annotation found in spec content."""

    id_value: str
    annotation_type: AnnotationType
    line_number: int
    column: int
    raw_text: str


@dataclass(frozen=True)
class PinAnnotation:
    """A pin annotation linking spec to artifact."""

    file_path: str  # Path to the artifact file
    symbol: str  # Symbol within the file (function, class, etc.)
    line_number: int
    column: int
    raw_text: str

    @property
    def full_location(self) -> str:
        """Get the full location string."""
        return f"{self.file_path}:{self.symbol}"


class AnnotationParser:
    """Parser for spec annotations."""

    # Canonical patterns
    DECLARATION_PATTERN = re.compile(r"\(\[=([^\]]+)\]\)")
    REFERENCE_RELATED_PATTERN = re.compile(r"\(@\[\+([^\]]+)\]\)")
    REFERENCE_LABELED_PATTERN = re.compile(r"\(@\[=([^\]]+)\]\)")
    INVARIANT_REF_PATTERN = re.compile(r"\(@\[!([^\]]+)\]\)")  # (@[!I1])
    PIN_PATTERN = re.compile(r"\(@pin\s+([^:]+):([^\)]+)\)")  # (@pin path:symbol)

    # Legacy patterns to detect and normalize
    LEGACY_PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        (re.compile(r"\[\(=([^\]]+)\)\]"), "[(=ID)]"),  # Legacy format
        (re.compile(r"\(=\[([^\]]+)\]\)"), "(=[ID])"),  # Legacy format
        (re.compile(r"\(\+\[([^\]]+)\]\)"), "(+[ID])"),  # Legacy format
    ]

    def parse_declarations(self, content: str) -> Iterator[Annotation]:
        """Extract all declaration annotations from content."""
        for line_num, line in enumerate(content.splitlines(), start=1):
            for match in self.DECLARATION_PATTERN.finditer(line):
                yield Annotation(
                    id_value=match.group(1).strip(),
                    annotation_type=AnnotationType.DECLARATION,
                    line_number=line_num,
                    column=match.start(),
                    raw_text=match.group(0),
                )

    def parse_references(self, content: str) -> Iterator[Annotation]:
        """Extract all reference annotations from content."""
        for line_num, line in enumerate(content.splitlines(), start=1):
            # Related references
            for match in self.REFERENCE_RELATED_PATTERN.finditer(line):
                yield Annotation(
                    id_value=match.group(1).strip(),
                    annotation_type=AnnotationType.REFERENCE_RELATED,
                    line_number=line_num,
                    column=match.start(),
                    raw_text=match.group(0),
                )
            # Labeled references
            for match in self.REFERENCE_LABELED_PATTERN.finditer(line):
                yield Annotation(
                    id_value=match.group(1).strip(),
                    annotation_type=AnnotationType.REFERENCE_LABELED,
                    line_number=line_num,
                    column=match.start(),
                    raw_text=match.group(0),
                )

    def parse_invariant_refs(self, content: str) -> Iterator[Annotation]:
        """Extract all invariant reference annotations (@[!I#]) from content."""
        for line_num, line in enumerate(content.splitlines(), start=1):
            for match in self.INVARIANT_REF_PATTERN.finditer(line):
                yield Annotation(
                    id_value=match.group(1).strip(),
                    annotation_type=AnnotationType.INVARIANT_REF,
                    line_number=line_num,
                    column=match.start(),
                    raw_text=match.group(0),
                )

    def parse_pins(self, content: str) -> Iterator[PinAnnotation]:
        """Extract all pin annotations (@pin path:symbol) from content.

        Pins link spec elements to artifact locations, enabling drift detection.
        """
        for line_num, line in enumerate(content.splitlines(), start=1):
            for match in self.PIN_PATTERN.finditer(line):
                yield PinAnnotation(
                    file_path=match.group(1).strip(),
                    symbol=match.group(2).strip(),
                    line_number=line_num,
                    column=match.start(),
                    raw_text=match.group(0),
                )

    def parse_all(self, content: str) -> Iterator[Annotation]:
        """Extract all annotations from content (excluding pins)."""
        yield from self.parse_declarations(content)
        yield from self.parse_references(content)
        yield from self.parse_invariant_refs(content)

    def find_legacy_patterns(self, content: str) -> list[tuple[int, str, str]]:
        """Find legacy annotation patterns that need normalization.

        Returns: List of (line_number, matched_text, legacy_format_name)
        """
        findings = []
        for line_num, line in enumerate(content.splitlines(), start=1):
            for pattern, format_name in self.LEGACY_PATTERNS:
                for match in pattern.finditer(line):
                    findings.append((line_num, match.group(0), format_name))
        return findings

    def normalize_legacy(self, content: str) -> str:
        """Normalize legacy annotation patterns to canonical format.

        Transforms:
        - [(=ID)] -> ([=ID])
        - (=[ID]) -> ([=ID])
        - (+[ID]) -> (@[+ID])
        """
        result = content

        # [(=ID)] -> ([=ID])
        result = re.sub(r"\[\(=([^\]]+)\)\]", r"([=\1])", result)

        # (=[ID]) -> ([=ID])
        result = re.sub(r"\(=\[([^\]]+)\]\)", r"([=\1])", result)

        # (+[ID]) -> (@[+ID])
        result = re.sub(r"\(\+\[([^\]]+)\]\)", r"(@[+\1])", result)

        return result

    def extract_id_from_header(self, header_line: str) -> str | None:
        """Extract the declared ID from a header line.

        Args:
            header_line: A markdown header line (e.g., "## Algorithm 1 ([=Algorithm 1])")

        Returns:
            The ID value if found, None otherwise.
        """
        match = self.DECLARATION_PATTERN.search(header_line)
        if match:
            return match.group(1).strip()
        return None
