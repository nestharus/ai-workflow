#!/usr/bin/env python3
# noqa: D100
"""Converter script for orchestrator-invocation.md.

Converts docs/processes/orchestrator-invocation.md to docs/processes/orchestrator-invocation.yml.
"""

from pathlib import Path

from scripts.dev.markdown.converter_base import MarkdownConverter


def main() -> None:
    """Run the markdown to YAML conversion."""
    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent.parent
    source = project_root / "docs/processes/orchestrator-invocation.md"
    target = project_root / "docs/processes/orchestrator-invocation.yml"

    converter = MarkdownConverter(str(source), str(target))
    doc = converter.run()

    print(f"Converted: {source}")
    print(f"Output: {target}")
    print(f"Title: {doc.title}")
    print(f"Sections: {len(doc.sections)}")


if __name__ == "__main__":
    main()
