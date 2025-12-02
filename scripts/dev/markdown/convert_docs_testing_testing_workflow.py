#!/usr/bin/env python3
"""Converter script for testing-workflow.md.

Converts docs/testing/testing-workflow.md to docs/testing/testing-workflow.yml.
"""

from pathlib import Path

from scripts.dev.markdown.converter_base import MarkdownConverter


def main() -> None:
    """Run the markdown to YAML conversion."""
    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent.parent
    source = project_root / "docs/testing/testing-workflow.md"
    target = project_root / "docs/testing/testing-workflow.yml"

    converter = MarkdownConverter(str(source), str(target))
    doc = converter.run()

    print(f"Converted: {source}")
    print(f"Output: {target}")
    print(f"Title: {doc.title}")
    print(f"Sections: {len(doc.sections)}")


if __name__ == "__main__":
    main()
