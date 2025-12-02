#!/usr/bin/env python3
"""Generate individual converter scripts from the manifest.

Reads docs/plans/md-to-yml-manifest.yml and creates a converter script
for each entry.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.dev.markdown.converter_base import create_converter_script


def derive_script_name(source_path: str) -> str:
    """Derive the script name from the source path.

    Args:
        source_path: The source markdown file path.

    Returns:
        The script filename.
    """
    # Convert path like docs/architecture/event-flow.md
    # to convert_docs_architecture_event_flow.py
    path = Path(source_path)
    parts = path.parts
    name_parts = [p.replace(".md", "").replace("-", "_") for p in parts]
    return "convert_" + "_".join(name_parts) + ".py"


def main() -> None:
    """Generate converter scripts from manifest."""
    project_root = Path(__file__).parent.parent.parent
    manifest_path = project_root / "docs/plans/md-to-yml-manifest.yml"
    scripts_dir = project_root / "scripts/markdown"

    # Read manifest
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    sources = manifest.get("sources", [])
    print(f"Found {len(sources)} entries in manifest")

    for entry in sources:
        source_path = entry["path"]
        target_path = entry["target_stub"]
        script_name = derive_script_name(source_path)
        script_path = scripts_dir / script_name

        # Generate script content
        script_content = create_converter_script(source_path, target_path)

        # Write script
        script_path.write_text(script_content, encoding="utf-8")
        script_path.chmod(0o755)

        print(f"Created: {script_path.name}")

    print(f"\nGenerated {len(sources)} converter scripts in {scripts_dir}")


if __name__ == "__main__":
    main()
