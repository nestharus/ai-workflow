#!/usr/bin/env python3
# noqa: D100
"""Base module for converting Markdown files to YAML documentation format.

This module provides the core parsing and conversion logic used by individual
converter scripts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import yaml


@dataclass
class Item:
    """Represents a single item within a section."""

    id: str
    type: str  # rule, step, note, example, code, table, diagram
    text: str


@dataclass
class Section:
    """Represents a section within the document."""

    id: str
    index: int
    title: str
    category: str  # standard, guide, workflow, reference, example
    summary: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Document:
    """Represents the entire parsed document."""

    doc_id: str
    title: str
    description: str
    domain: list[str]
    scope: str  # general or project
    sections: list[Section] = field(default_factory=list)


class MarkdownConverter:
    """Converts Markdown files to structured YAML format."""

    ITEM_TYPE_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "rule": [
            "must",
            "should",
            "shall",
            "required",
            "always",
            "never",
            "do not",
            "don't",
        ],
        "step": [
            "first",
            "then",
            "next",
            "finally",
            "step",
            "create",
            "run",
            "execute",
        ],
        "note": ["note:", "important:", "warning:", "caution:", "tip:"],
        "example": ["example:", "e.g.", "for example", "such as", "like:"],
        "definition": ["definition:", "means", "refers to", "is defined as"],
    }

    CATEGORY_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "guide": ["guide", "how to", "tutorial", "getting started"],
        "workflow": ["workflow", "flow", "process", "sequence", "pipeline"],
        "reference": ["reference", "api", "specification", "schema"],
        "example": ["example", "sample", "demo"],
        "standard": [],  # default
    }

    def __init__(self, source_path: str, target_path: str) -> None:
        """Initialize the converter with source and target paths.

        Args:
            source_path: Path to the markdown file to convert.
            target_path: Path where the YAML output will be written.
        """
        self.source_path = Path(source_path)
        self.target_path = Path(target_path)
        self.content: str = ""
        self.lines: list[str] = []

    def slugify(self, text: str) -> str:
        """Convert text to a URL-safe slug.

        Args:
            text: The text to convert.

        Returns:
            A lowercase, hyphenated slug.
        """
        # Remove special characters and convert to lowercase
        slug = re.sub(r"[^\w\s-]", "", text.lower())
        # Replace whitespace with hyphens
        slug = re.sub(r"[-\s]+", "-", slug)
        # Remove leading/trailing hyphens
        return slug.strip("-")

    def detect_item_type(self, text: str) -> str:
        """Detect the type of an item based on its content.

        Args:
            text: The item text to analyze.

        Returns:
            The detected type: rule, step, note, example, definition, or text.
        """
        text_lower = text.lower()
        for item_type, patterns in self.ITEM_TYPE_PATTERNS.items():
            for pattern in patterns:
                if pattern in text_lower:
                    return item_type
        return "text"

    def detect_category(self, title: str) -> str:
        """Detect the category of a section based on its title.

        Args:
            title: The section title to analyze.

        Returns:
            The detected category: guide, workflow, reference, example, or standard.
        """
        title_lower = title.lower()
        for category, patterns in self.CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if pattern in title_lower:
                    return category
        return "standard"

    def read_source(self) -> None:
        """Read the source markdown file."""
        self.content = self.source_path.read_text(encoding="utf-8")
        self.lines = self.content.split("\n")

    def extract_title(self) -> str:
        """Extract the document title from the first H1 heading.

        Returns:
            The document title, or empty string if not found.
        """
        for line in self.lines:
            if line.startswith("# ") and not line.startswith("## "):
                return line[2:].strip()
        return ""

    def extract_description(self) -> str:
        """Extract the document description from intro text after title.

        Returns:
            The description text, or empty string if not found.
        """
        in_intro = False
        description_lines: list[str] = []

        for line in self.lines:
            # Skip until we find the title
            if line.startswith("# ") and not line.startswith("## "):
                in_intro = True
                continue

            # Stop at the next heading
            if in_intro and line.startswith("#"):
                break

            # Collect non-empty lines that aren't code blocks
            if in_intro and line.strip() and not line.startswith("```"):
                description_lines.append(line.strip())

            # Stop after first paragraph
            if in_intro and not line.strip() and description_lines:
                break

        return " ".join(description_lines)

    def parse_sections(self) -> list[Section]:
        """Parse all sections from the markdown content.

        Returns:
            A list of Section objects.
        """
        sections: list[Section] = []
        current_section: Section | None = None
        current_items: list[str] = []
        in_code_block = False
        code_block_lines: list[str] = []
        section_index = 0

        for line in self.lines:
            # Track code blocks
            if line.startswith("```"):
                if in_code_block:
                    # End of code block
                    in_code_block = False
                    if current_section:
                        code_content = "\n".join(code_block_lines)
                        item_id = f"{current_section.id}-code-{len(current_section.items) + 1}"
                        current_section.items.append(
                            Item(id=item_id, type="code", text=code_content)
                        )
                    code_block_lines = []
                else:
                    # Start of code block
                    in_code_block = True
                continue

            if in_code_block:
                code_block_lines.append(line)
                continue

            # Check for section headings (H2 or H3)
            if line.startswith("## ") or line.startswith("### "):
                # Save current section if exists
                if current_section:
                    self._flush_items(current_section, current_items)
                    sections.append(current_section)
                    current_items = []

                # Create new section
                section_index += 1
                heading_level = 2 if line.startswith("## ") else 3
                title = line[heading_level + 1 :].strip()
                section_id = self.slugify(title)
                category = self.detect_category(title)

                current_section = Section(
                    id=section_id,
                    index=section_index,
                    title=title,
                    category=category,
                    summary="",
                    items=[],
                )
                continue

            # Collect content within a section
            if current_section:
                stripped = line.strip()
                if stripped:
                    current_items.append(stripped)
                elif current_items:
                    # Empty line - flush current items
                    self._flush_items(current_section, current_items)
                    current_items = []

        # Save last section
        if current_section:
            self._flush_items(current_section, current_items)
            sections.append(current_section)

        return sections

    def _flush_items(self, section: Section, items: list[str]) -> None:
        """Process and add collected items to a section.

        Args:
            section: The section to add items to.
            items: The list of raw text items to process.
        """
        if not items:
            return

        # Check if this is a list (bullets or numbered)
        is_list = all(
            item.startswith(("- ", "* ", "+ "))
            or re.match(r"^\d+\.", item)
            or re.match(r"^\*\*", item)
            for item in items
        )

        if is_list:
            for item_text in items:
                # Remove list markers
                clean_text = re.sub(r"^[-*+]\s+", "", item_text)
                clean_text = re.sub(r"^\d+\.\s+", "", clean_text)
                item_type = self.detect_item_type(clean_text)
                item_id = f"{section.id}-{self.slugify(clean_text[:30])}"
                section.items.append(Item(id=item_id, type=item_type, text=clean_text))
        else:
            # Treat as paragraph text
            combined_text = " ".join(items)
            item_type = self.detect_item_type(combined_text)
            item_id = f"{section.id}-{len(section.items) + 1}"
            section.items.append(Item(id=item_id, type=item_type, text=combined_text))

    def derive_doc_id(self) -> str:
        """Derive the document ID from the source path.

        Returns:
            A document ID in the format original-<category>-<filename>.
        """
        # Get path parts after docs/
        parts = self.source_path.parts
        try:
            docs_idx = parts.index("docs")
            relevant_parts = parts[docs_idx + 1 :]
        except ValueError:
            relevant_parts = [self.source_path.stem]

        # Convert to slug format
        name_parts = [self.slugify(p.replace(".md", "")) for p in relevant_parts]
        return "original-" + "-".join(name_parts)

    def guess_scope(self, content: str) -> str:
        """Guess the scope (general or project) based on content.

        Args:
            content: The document content to analyze.

        Returns:
            'project' if references to app/* paths found, otherwise 'general'.
        """
        # Check for project-specific references
        if re.search(r"app/|\.factory/|webhook_receiver/", content):
            return "project"
        if re.search(r"AGENTS\.md|docs/architecture/", content):
            return "project"
        return "general"

    def convert(self) -> Document:
        """Perform the full conversion of markdown to Document.

        Returns:
            A Document object representing the parsed content.
        """
        self.read_source()

        title = self.extract_title()
        description = self.extract_description()
        sections = self.parse_sections()
        doc_id = self.derive_doc_id()
        scope = self.guess_scope(self.content)

        return Document(
            doc_id=doc_id,
            title=title,
            description=description,
            domain=[],  # To be filled later
            scope=scope,
            sections=sections,
        )

    def to_yaml_dict(self, doc: Document) -> dict:
        """Convert a Document to a dictionary suitable for YAML output.

        Args:
            doc: The Document to convert.

        Returns:
            A dictionary representation of the document.
        """
        return {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "description": doc.description,
            "domain": doc.domain,
            "scope": doc.scope,
            "sections": [
                {
                    "id": section.id,
                    "index": section.index,
                    "title": section.title,
                    "category": section.category,
                    "summary": section.summary,
                    "items": [
                        {"id": item.id, "type": item.type, "text": item.text}
                        for item in section.items
                    ],
                }
                for section in doc.sections
            ],
        }

    def write_yaml(self, doc: Document) -> None:
        """Write the document to a YAML file.

        Args:
            doc: The Document to write.
        """
        # Ensure target directory exists
        self.target_path.parent.mkdir(parents=True, exist_ok=True)

        yaml_dict = self.to_yaml_dict(doc)

        with self.target_path.open("w", encoding="utf-8") as f:
            yaml.dump(
                yaml_dict,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=100,
            )

    def run(self) -> Document:
        """Execute the full conversion pipeline.

        Returns:
            The converted Document object.
        """
        doc = self.convert()
        self.write_yaml(doc)
        return doc


def create_converter_script(source_path: str, target_path: str) -> str:
    """Generate the content for a converter script.

    Args:
        source_path: Path to the source markdown file.
        target_path: Path where the YAML output will be written.

    Returns:
        The Python script content as a string.
    """
    script_template = '''#!/usr/bin/env python3
# noqa: D100
"""Converter script for {source_basename}.

Converts {source_path} to {target_path}.
"""

from pathlib import Path

from scripts.dev.markdown.converter_base import MarkdownConverter


def main() -> None:
    """Run the markdown to YAML conversion."""
    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent.parent
    source = project_root / "{source_path}"
    target = project_root / "{target_path}"

    converter = MarkdownConverter(str(source), str(target))
    doc = converter.run()

    print(f"Converted: {{source}}")
    print(f"Output: {{target}}")
    print(f"Title: {{doc.title}}")
    print(f"Sections: {{len(doc.sections)}}")


if __name__ == "__main__":
    main()
'''
    source_basename = Path(source_path).name
    return script_template.format(
        source_basename=source_basename,
        source_path=source_path,
        target_path=target_path,
    )
