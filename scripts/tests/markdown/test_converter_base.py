"""Tests for scripts.dev.markdown.converter_base module."""

from __future__ import annotations

from pathlib import Path

from scripts.dev.markdown.converter_base import (
    Document,
    Item,
    MarkdownConverter,
    Section,
    create_converter_script,
)


class TestItem:
    """Tests for the Item dataclass."""

    def test_item_creation(self) -> None:
        """Test creating an Item with all required fields."""
        item = Item(id="test-item-1", type="rule", text="Must do something")
        assert item.id == "test-item-1"
        assert item.type == "rule"
        assert item.text == "Must do something"


class TestSection:
    """Tests for the Section dataclass."""

    def test_section_creation(self) -> None:
        """Test creating a Section with all required fields."""
        section = Section(
            id="test-section",
            index=1,
            title="Test Section",
            category="standard",
            summary="A test section",
            items=[],
        )
        assert section.id == "test-section"
        assert section.index == 1
        assert section.title == "Test Section"
        assert section.category == "standard"
        assert section.summary == "A test section"
        assert section.items == []

    def test_section_with_items(self) -> None:
        """Test creating a Section with items."""
        items = [
            Item(id="item-1", type="rule", text="Rule 1"),
            Item(id="item-2", type="step", text="Step 1"),
        ]
        section = Section(
            id="test-section",
            index=1,
            title="Test Section",
            category="guide",
            summary="",
            items=items,
        )
        assert len(section.items) == 2


class TestDocument:
    """Tests for the Document dataclass."""

    def test_document_creation(self) -> None:
        """Test creating a Document with all required fields."""
        doc = Document(
            doc_id="test-doc",
            title="Test Document",
            description="A test document",
            domain=["testing"],
            scope="general",
            sections=[],
        )
        assert doc.doc_id == "test-doc"
        assert doc.title == "Test Document"
        assert doc.description == "A test document"
        assert doc.domain == ["testing"]
        assert doc.scope == "general"


class TestMarkdownConverterInit:
    """Tests for the MarkdownConverter.__init__ method."""

    def test_init_creates_paths(self, tmp_path: Path) -> None:
        """Test that __init__ correctly initializes source and target paths."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"

        converter = MarkdownConverter(str(source), str(target))

        assert converter.source_path == source
        assert converter.target_path == target
        assert converter.content == ""
        assert converter.lines == []


class TestMarkdownConverterSlugify:
    """Tests for the MarkdownConverter.slugify method."""

    def test_slugify_basic(self, tmp_path: Path) -> None:
        """Test slugify with basic text."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        result = converter.slugify("Hello World")
        assert result == "hello-world"

    def test_slugify_special_characters(self, tmp_path: Path) -> None:
        """Test slugify removes special characters."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        result = converter.slugify("Hello! World? #Test")
        assert result == "hello-world-test"

    def test_slugify_leading_trailing_hyphens(self, tmp_path: Path) -> None:
        """Test slugify removes leading and trailing hyphens."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        result = converter.slugify("  Hello World  ")
        assert result == "hello-world"


class TestMarkdownConverterDetectItemType:
    """Tests for the MarkdownConverter.detect_item_type method."""

    def test_detect_rule_type(self, tmp_path: Path) -> None:
        """Test detecting rule type items."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_item_type("You must always validate") == "rule"
        assert converter.detect_item_type("Should be done first") == "rule"
        assert converter.detect_item_type("This is required") == "rule"
        assert converter.detect_item_type("Never do this") == "rule"
        assert converter.detect_item_type("Don't forget to check") == "rule"

    def test_detect_step_type(self, tmp_path: Path) -> None:
        """Test detecting step type items."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_item_type("First, do this") == "step"
        assert converter.detect_item_type("Then run the command") == "step"
        assert converter.detect_item_type("Create a new file") == "step"
        assert converter.detect_item_type("Execute the script") == "step"

    def test_detect_note_type(self, tmp_path: Path) -> None:
        """Test detecting note type items."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_item_type("Note: This is important") == "note"
        assert converter.detect_item_type("Warning: Be careful") == "note"
        assert converter.detect_item_type("Tip: Use this trick") == "note"

    def test_detect_example_type(self, tmp_path: Path) -> None:
        """Test detecting example type items."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_item_type("Example: foo = bar") == "example"
        assert converter.detect_item_type("For example, use this") == "example"
        assert converter.detect_item_type("Such as Python or Java") == "example"

    def test_detect_definition_type(self, tmp_path: Path) -> None:
        """Test detecting definition type items."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_item_type("Definition: A term") == "definition"
        assert converter.detect_item_type("This means something") == "definition"

    def test_detect_text_type_default(self, tmp_path: Path) -> None:
        """Test default text type for unmatched patterns."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_item_type("Random content here") == "text"


class TestMarkdownConverterDetectCategory:
    """Tests for the MarkdownConverter.detect_category method."""

    def test_detect_guide_category(self, tmp_path: Path) -> None:
        """Test detecting guide category."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_category("Quick Start Guide") == "guide"
        assert converter.detect_category("How to Install") == "guide"
        assert converter.detect_category("Tutorial for Beginners") == "guide"

    def test_detect_workflow_category(self, tmp_path: Path) -> None:
        """Test detecting workflow category."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_category("CI/CD Workflow") == "workflow"
        assert converter.detect_category("Build Process") == "workflow"
        assert converter.detect_category("Deployment Pipeline") == "workflow"

    def test_detect_reference_category(self, tmp_path: Path) -> None:
        """Test detecting reference category."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_category("API Reference") == "reference"
        assert converter.detect_category("Schema Specification") == "reference"

    def test_detect_example_category(self, tmp_path: Path) -> None:
        """Test detecting example category."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_category("Code Examples") == "example"
        assert converter.detect_category("Sample Project") == "example"

    def test_detect_standard_category_default(self, tmp_path: Path) -> None:
        """Test default standard category for unmatched patterns."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        converter = MarkdownConverter(str(source), str(target))

        assert converter.detect_category("Introduction") == "standard"
        assert converter.detect_category("Overview") == "standard"


class TestMarkdownConverterReadSource:
    """Tests for the MarkdownConverter.read_source method."""

    def test_read_source(self, tmp_path: Path) -> None:
        """Test reading source markdown file."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        source.write_text("# Hello\n\nWorld\n", encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()

        assert converter.content == "# Hello\n\nWorld\n"
        assert converter.lines == ["# Hello", "", "World", ""]


class TestMarkdownConverterExtractTitle:
    """Tests for the MarkdownConverter.extract_title method."""

    def test_extract_title_found(self, tmp_path: Path) -> None:
        """Test extracting title when H1 exists."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        source.write_text("# My Document Title\n\nSome content\n", encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()

        assert converter.extract_title() == "My Document Title"

    def test_extract_title_not_found(self, tmp_path: Path) -> None:
        """Test extracting title when no H1 exists."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        source.write_text("## Subheading\n\nNo main title\n", encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()

        assert converter.extract_title() == ""

    def test_extract_title_ignores_h2(self, tmp_path: Path) -> None:
        """Test that H2 headings are not treated as title."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        source.write_text("## Not a Title\n# Real Title\n", encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()

        assert converter.extract_title() == "Real Title"


class TestMarkdownConverterExtractDescription:
    """Tests for the MarkdownConverter.extract_description method."""

    def test_extract_description_basic(self, tmp_path: Path) -> None:
        """Test extracting description from intro paragraph."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

This is the description.

## Section
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()

        assert converter.extract_description() == "This is the description."

    def test_extract_description_multiline(self, tmp_path: Path) -> None:
        """Test extracting multi-line description."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

Line one of description.
Line two of description.

## Section
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()

        assert (
            converter.extract_description() == "Line one of description. Line two of description."
        )

    def test_extract_description_stops_at_heading(self, tmp_path: Path) -> None:
        """Test that description stops at next heading."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

Description paragraph.
## Section

Not part of description.
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()

        assert converter.extract_description() == "Description paragraph."

    def test_extract_description_ignores_code_blocks(self, tmp_path: Path) -> None:
        """Test that code blocks are skipped."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

```python
# This is not description
```

This is the real description.

## Section
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()

        assert converter.extract_description() == "This is the real description."

    def test_extract_description_no_title(self, tmp_path: Path) -> None:
        """Test extracting description when no title exists."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """## Section

No description here.
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()

        assert converter.extract_description() == ""


class TestMarkdownConverterParseSections:
    """Tests for the MarkdownConverter.parse_sections method."""

    def test_parse_sections_basic(self, tmp_path: Path) -> None:
        """Test parsing basic sections."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

Intro.

## Section One

Content for section one.

## Section Two

Content for section two.
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()
        sections = converter.parse_sections()

        assert len(sections) == 2
        assert sections[0].title == "Section One"
        assert sections[1].title == "Section Two"

    def test_parse_sections_with_code_blocks(self, tmp_path: Path) -> None:
        """Test parsing sections containing code blocks."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

## Code Section

Here is some code:

```python
def hello():
    print("Hello")
```

More text.
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()
        sections = converter.parse_sections()

        assert len(sections) == 1
        # Check for code item
        code_items = [i for i in sections[0].items if i.type == "code"]
        assert len(code_items) == 1
        assert "def hello():" in code_items[0].text

    def test_parse_sections_h3_headings(self, tmp_path: Path) -> None:
        """Test parsing H3 level headings."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

## Main Section

### Subsection

Content here.
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()
        sections = converter.parse_sections()

        assert len(sections) == 2
        assert sections[0].title == "Main Section"
        assert sections[1].title == "Subsection"

    def test_parse_sections_with_list_items(self, tmp_path: Path) -> None:
        """Test parsing sections with bullet lists."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

## Requirements

- First requirement
- Second requirement
- Third requirement
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()
        sections = converter.parse_sections()

        assert len(sections) == 1
        assert len(sections[0].items) == 3

    def test_parse_sections_with_numbered_list(self, tmp_path: Path) -> None:
        """Test parsing sections with numbered lists."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

## Steps

1. First step
2. Second step
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()
        sections = converter.parse_sections()

        assert len(sections) == 1
        assert len(sections[0].items) == 2

    def test_parse_sections_empty_lines(self, tmp_path: Path) -> None:
        """Test parsing sections with empty lines separating content."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

## Section

First paragraph.

Second paragraph.
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()
        sections = converter.parse_sections()

        assert len(sections) == 1
        assert len(sections[0].items) == 2

    def test_parse_sections_unclosed_code_block(self, tmp_path: Path) -> None:
        """Test parsing sections with unclosed code block at EOF."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

## Section

```python
code without closing
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()
        sections = converter.parse_sections()

        assert len(sections) == 1
        code_items = [i for i in sections[0].items if i.type == "code"]
        assert len(code_items) == 1

    def test_parse_sections_no_sections(self, tmp_path: Path) -> None:
        """Test parsing when there are no sections."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"
        content = """# Title

Just a paragraph with no sections.
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        converter.read_source()
        sections = converter.parse_sections()

        assert len(sections) == 0


class TestMarkdownConverterDeriveDocId:
    """Tests for the MarkdownConverter.derive_doc_id method."""

    def test_derive_doc_id_with_docs_path(self, tmp_path: Path) -> None:
        """Test deriving doc ID from a path containing 'docs'."""
        docs_path = tmp_path / "docs" / "architecture" / "overview.md"
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text("# Overview\n", encoding="utf-8")
        target = tmp_path / "output.yaml"

        converter = MarkdownConverter(str(docs_path), str(target))

        doc_id = converter.derive_doc_id()
        assert doc_id == "original-architecture-overview"

    def test_derive_doc_id_without_docs_path(self, tmp_path: Path) -> None:
        """Test deriving doc ID from a path without 'docs'."""
        source = tmp_path / "some" / "random" / "file.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# File\n", encoding="utf-8")
        target = tmp_path / "output.yaml"

        converter = MarkdownConverter(str(source), str(target))

        doc_id = converter.derive_doc_id()
        assert doc_id == "original-file"


class TestMarkdownConverterGuessScope:
    """Tests for the MarkdownConverter.guess_scope method."""

    def test_guess_scope_project_app(self, tmp_path: Path) -> None:
        """Test detecting project scope from app/ references."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"

        converter = MarkdownConverter(str(source), str(target))

        assert converter.guess_scope("Check the app/models/ directory") == "project"

    def test_guess_scope_project_factory(self, tmp_path: Path) -> None:
        """Test detecting project scope from .factory/ references."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"

        converter = MarkdownConverter(str(source), str(target))

        assert converter.guess_scope("See .factory/ for templates") == "project"

    def test_guess_scope_project_agents(self, tmp_path: Path) -> None:
        """Test detecting project scope from AGENTS.md reference."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"

        converter = MarkdownConverter(str(source), str(target))

        assert converter.guess_scope("Refer to AGENTS.md") == "project"

    def test_guess_scope_general(self, tmp_path: Path) -> None:
        """Test detecting general scope for generic content."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"

        converter = MarkdownConverter(str(source), str(target))

        assert converter.guess_scope("General programming tips") == "general"


class TestMarkdownConverterConvert:
    """Tests for the MarkdownConverter.convert method."""

    def test_convert_full_document(self, tmp_path: Path) -> None:
        """Test full conversion of a markdown document."""
        source = tmp_path / "docs" / "guide.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        target = tmp_path / "output.yaml"
        content = """# Quick Start Guide

This is an introduction.

## Installation

First, run the installer.

## Configuration

Set up the config.
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        doc = converter.convert()

        assert doc.title == "Quick Start Guide"
        assert doc.description == "This is an introduction."
        assert len(doc.sections) == 2
        assert doc.sections[0].title == "Installation"
        assert doc.sections[1].title == "Configuration"
        assert doc.scope == "general"
        assert "original-" in doc.doc_id


class TestMarkdownConverterToYamlDict:
    """Tests for the MarkdownConverter.to_yaml_dict method."""

    def test_to_yaml_dict_basic(self, tmp_path: Path) -> None:
        """Test converting a Document to a dictionary."""
        source = tmp_path / "source.md"
        target = tmp_path / "target.yaml"

        converter = MarkdownConverter(str(source), str(target))

        item = Item(id="item-1", type="rule", text="Must do this")
        section = Section(
            id="section-1",
            index=1,
            title="Rules",
            category="standard",
            summary="",
            items=[item],
        )
        doc = Document(
            doc_id="test-doc",
            title="Test",
            description="Test doc",
            domain=["test"],
            scope="general",
            sections=[section],
        )

        result = converter.to_yaml_dict(doc)

        assert result["doc_id"] == "test-doc"
        assert result["title"] == "Test"
        assert result["description"] == "Test doc"
        assert result["domain"] == ["test"]
        assert result["scope"] == "general"
        assert len(result["sections"]) == 1
        assert result["sections"][0]["id"] == "section-1"
        assert len(result["sections"][0]["items"]) == 1


class TestMarkdownConverterWriteYaml:
    """Tests for the MarkdownConverter.write_yaml method."""

    def test_write_yaml_creates_file(self, tmp_path: Path) -> None:
        """Test that write_yaml creates the output file."""
        source = tmp_path / "source.md"
        target = tmp_path / "output" / "result.yaml"

        converter = MarkdownConverter(str(source), str(target))

        doc = Document(
            doc_id="test-doc",
            title="Test",
            description="Test doc",
            domain=[],
            scope="general",
            sections=[],
        )

        converter.write_yaml(doc)

        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "doc_id: test-doc" in content
        assert "title: Test" in content


class TestMarkdownConverterRun:
    """Tests for the MarkdownConverter.run method."""

    def test_run_full_pipeline(self, tmp_path: Path) -> None:
        """Test running the full conversion pipeline."""
        source = tmp_path / "source.md"
        target = tmp_path / "output.yaml"
        content = """# Test Document

A simple test.

## Section One

Some content here.
"""
        source.write_text(content, encoding="utf-8")

        converter = MarkdownConverter(str(source), str(target))
        doc = converter.run()

        assert doc.title == "Test Document"
        assert target.exists()


class TestCreateConverterScript:
    """Tests for the create_converter_script function."""

    def test_create_converter_script_basic(self) -> None:
        """Test creating a converter script."""
        result = create_converter_script("docs/guides/intro.md", "output/guides/intro.yaml")

        assert "#!/usr/bin/env python3" in result
        assert "intro.md" in result
        assert "docs/guides/intro.md" in result
        assert "output/guides/intro.yaml" in result
        assert "MarkdownConverter" in result
        assert "def main()" in result
