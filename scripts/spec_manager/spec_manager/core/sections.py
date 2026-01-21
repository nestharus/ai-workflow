"""
Section extraction utilities for spec management.

Sections are delimited by ([=ID]) declarations in markdown headers.
Each section includes the header line and all content until the next declaration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .annotations import AnnotationParser
from .ids import IdValidator


@dataclass
class Section:
    """A section extracted from spec content."""

    id_value: str
    header_line: str
    body: str
    start_line: int
    end_line: int
    source_file: Path | None = None

    @property
    def full_content(self) -> str:
        """Get the complete section content (header + body)."""
        return f"{self.header_line}\n{self.body}".strip()

    @property
    def is_empty(self) -> bool:
        """Check if the section body is empty or whitespace-only."""
        return not self.body.strip()


@dataclass
class ExtractionResult:
    """Result of section extraction from a file."""

    sections: dict[str, Section] = field(default_factory=dict)
    orphan_content: str = ""  # Content before the first declaration
    duplicate_ids: list[tuple[str, int, int]] = field(
        default_factory=list
    )  # (id, first_line, second_line)


class SectionExtractor:
    """Extract sections from spec content based on ([=ID]) declarations."""

    def __init__(self) -> None:
        self.parser = AnnotationParser()
        self.validator = IdValidator()

    def extract(
        self, content: str, source_file: Path | None = None, validate_ids: bool = True
    ) -> ExtractionResult:
        """
        Extract sections from content based on ([=ID]) declarations.

        Args:
            content: The markdown content to extract from
            source_file: Optional source file path for tracking
            validate_ids: If True, only extract sections with valid IDs

        Returns:
            ExtractionResult with extracted sections and metadata
        """
        result = ExtractionResult()
        lines = content.split("\n")

        # Find all declaration positions
        declarations: list[tuple[int, str]] = []  # (line_index, id_value)

        for i, line in enumerate(lines):
            id_value = self.parser.extract_id_from_header(line)
            if id_value:
                if not validate_ids or self.validator.is_valid(id_value):
                    declarations.append((i, id_value))

        if not declarations:
            # No declarations found - everything is orphan content
            result.orphan_content = content
            return result

        # Track seen IDs for duplicate detection
        seen_ids: dict[str, int] = {}

        # Extract content before first declaration as orphan
        first_decl_line = declarations[0][0]
        if first_decl_line > 0:
            result.orphan_content = "\n".join(lines[:first_decl_line])

        # Extract each section
        for idx, (line_idx, id_value) in enumerate(declarations):
            # Check for duplicates
            if id_value in seen_ids:
                result.duplicate_ids.append((id_value, seen_ids[id_value], line_idx + 1))
            else:
                seen_ids[id_value] = line_idx + 1

            # Determine section boundaries
            start_line = line_idx
            if idx + 1 < len(declarations):
                end_line = declarations[idx + 1][0] - 1
            else:
                end_line = len(lines) - 1

            # Extract header and body
            header_line = lines[start_line]
            body_lines = lines[start_line + 1 : end_line + 1]

            # Strip trailing empty lines from body
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()

            section = Section(
                id_value=id_value,
                header_line=header_line,
                body="\n".join(body_lines),
                start_line=start_line + 1,  # 1-indexed
                end_line=end_line + 1,  # 1-indexed
                source_file=source_file,
            )

            # Only store first occurrence (duplicates tracked separately)
            if id_value not in result.sections:
                result.sections[id_value] = section

        return result

    def extract_from_file(self, path: Path, validate_ids: bool = True) -> ExtractionResult:
        """
        Extract sections from a file.

        Args:
            path: Path to the markdown file
            validate_ids: If True, only extract sections with valid IDs

        Returns:
            ExtractionResult with extracted sections and metadata
        """
        content = path.read_text(encoding="utf-8")
        return self.extract(content, source_file=path, validate_ids=validate_ids)

    def extract_from_directory(
        self, directory: Path, pattern: str = "*.md", validate_ids: bool = True
    ) -> dict[str, ExtractionResult]:
        """
        Extract sections from all matching files in a directory.

        Args:
            directory: Directory to search
            pattern: Glob pattern for files (default: "*.md")
            validate_ids: If True, only extract sections with valid IDs

        Returns:
            Dict mapping filename (stem) to ExtractionResult
        """
        results: dict[str, ExtractionResult] = {}

        for path in sorted(directory.glob(pattern)):
            results[path.stem] = self.extract_from_file(path, validate_ids=validate_ids)

        return results

    def collect_all_ids(
        self, directory: Path, pattern: str = "*.md"
    ) -> dict[str, list[tuple[str, int]]]:
        """
        Collect all declared IDs and their locations from files in a directory.

        Args:
            directory: Directory to search
            pattern: Glob pattern for files

        Returns:
            Dict mapping ID to list of (filename, line_number) tuples
        """
        id_locations: dict[str, list[tuple[str, int]]] = {}

        for path in sorted(directory.glob(pattern)):
            content = path.read_text(encoding="utf-8")
            for annotation in self.parser.parse_declarations(content):
                if self.validator.is_valid(annotation.id_value):
                    if annotation.id_value not in id_locations:
                        id_locations[annotation.id_value] = []
                    id_locations[annotation.id_value].append(
                        (path.stem, annotation.line_number)
                    )

        return id_locations

    def rebuild_content(
        self, sections: dict[str, Section], sort_by_id: bool = True
    ) -> str:
        """
        Rebuild markdown content from sections.

        Args:
            sections: Dict mapping ID to Section
            sort_by_id: If True, sort sections by ID

        Returns:
            Rebuilt markdown content
        """
        section_list = list(sections.values())

        if sort_by_id:
            section_list.sort(key=lambda s: self.validator.sort_key(s.id_value))

        parts = []
        for section in section_list:
            parts.append(section.full_content)

        return "\n\n---\n\n".join(parts) + "\n"
