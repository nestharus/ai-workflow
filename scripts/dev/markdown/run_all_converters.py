#!/usr/bin/env python3
# noqa: D100
"""Run all converter scripts to generate YAML files.

Executes all convert_*.py scripts in the scripts/markdown directory.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.dev.markdown.converter_base import MarkdownConverter


def main() -> None:
    """Run all markdown to YAML conversions."""
    project_root = Path(__file__).parent.parent.parent
    manifest_path = project_root / "docs/plans/md-to-yml-manifest.yml"

    # Read manifest
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    sources = manifest.get("sources", [])
    print(f"Converting {len(sources)} markdown files to YAML\n")

    success_count = 0
    error_count = 0

    for entry in sources:
        source_path = project_root / entry["path"]
        target_path = project_root / entry["target_stub"]

        try:
            if not source_path.exists():
                print(f"SKIP: {entry['path']} (file not found)")
                error_count += 1
                continue

            converter = MarkdownConverter(str(source_path), str(target_path))
            doc = converter.run()

            print(f"OK: {entry['path']}")
            print(f"    -> {entry['target_stub']}")
            print(f"    Title: {doc.title}")
            print(f"    Sections: {len(doc.sections)}")
            print()
            success_count += 1

        except Exception as e:
            print(f"ERROR: {entry['path']}")
            print(f"    {e!s}")
            print()
            error_count += 1

    print(f"\n{'=' * 50}")
    print(f"Total: {len(sources)}")
    print(f"Success: {success_count}")
    print(f"Errors: {error_count}")


if __name__ == "__main__":
    main()
