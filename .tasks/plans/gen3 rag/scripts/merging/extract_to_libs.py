#!/usr/bin/env python3
"""
Extract missing content from plan.md to library files based on libs.md assignments.
"""

from __future__ import annotations

import re
from pathlib import Path


ID_PATTERNS_LEGAL = [
    r"Algorithm \d+",
    r"Comp\d+",
    r"D\d+",
    r"G\d+",
    r"C\d+",
    r"S\d+",
    r"T\d+",
    r"P\d+I\d+",
    r"P\d+C\d+",
    r"P\d+\.\d+",
    r"Lean\d+",
    r"NFG\d+",
    r"P\d+",
]

DECLARATION_PATTERN = re.compile(r"\(\[=([^\]]+)\]\)")


def is_legal_id(text: str) -> bool:
    return any(re.fullmatch(pattern, text) for pattern in ID_PATTERNS_LEGAL)


def parse_libs_md(path: Path) -> dict[str, str]:
    """Parse libs.md to get ID -> primary library mapping."""
    assignments: dict[str, str] = {}
    current_id = None
    current_primary = None

    for line in path.read_text(encoding="utf-8").splitlines():
        id_match = re.match(r"^-\s+\(\[=([^\]]+)\]\)", line)
        if id_match:
            if current_id and current_primary:
                assignments[current_id] = current_primary
            current_id = id_match.group(1).strip()
            current_primary = None
            continue

        primary_match = re.match(r"^\s+- primary:\s*(\w+)", line)
        if primary_match:
            current_primary = primary_match.group(1).strip()

    if current_id and current_primary:
        assignments[current_id] = current_primary

    return assignments


def extract_sections_by_annotation(lines: list[str]) -> dict[str, str]:
    """Extract sections based on ([=ID]) declarations."""
    sections: dict[str, str] = {}
    idx = 0
    while idx < len(lines):
        match = DECLARATION_PATTERN.search(lines[idx])
        if match and is_legal_id(match.group(1)):
            id_name = match.group(1)
            header_line = lines[idx]
            idx += 1
            body_lines: list[str] = []
            while idx < len(lines):
                next_match = DECLARATION_PATTERN.search(lines[idx])
                if next_match and is_legal_id(next_match.group(1)):
                    break
                body_lines.append(lines[idx])
                idx += 1
            section_text = "\n".join([header_line, *body_lines]).strip()
            sections[id_name] = section_text
            continue
        idx += 1
    return sections


def extract_declared_ids(lines: list[str]) -> set[str]:
    """Extract declared IDs in a library file."""
    ids: set[str] = set()
    for line in lines:
        match = DECLARATION_PATTERN.search(line)
        if match and is_legal_id(match.group(1)):
            ids.add(match.group(1))
    return ids


def main() -> None:
    base = Path(__file__).resolve().parents[2]
    plan_path = base / "plan.md"
    libs_dir = base / "libraries"
    libs_md = base / "libs.md"

    plan_lines = plan_path.read_text(encoding="utf-8").split("\n")
    plan_sections = extract_sections_by_annotation(plan_lines)

    assignments = parse_libs_md(libs_md)
    if not assignments:
        print("No assignments found in libs.md.")
        return

    library_ids: dict[str, set[str]] = {}
    for lib_file in sorted(libs_dir.glob("*.md")):
        library_ids[lib_file.stem] = extract_declared_ids(
            lib_file.read_text(encoding="utf-8").split("\n")
        )

    to_add: dict[str, list[str]] = {}
    missing_in_plan: list[str] = []

    for id_name, lib_name in sorted(assignments.items()):
        section = plan_sections.get(id_name)
        if not section:
            missing_in_plan.append(id_name)
            continue
        if id_name in library_ids.get(lib_name, set()):
            continue
        to_add.setdefault(lib_name, []).append(section)

    print("Extracting missing content to libraries...")
    print("=" * 60)

    total_added = 0
    for lib_name, sections in sorted(to_add.items()):
        lib_file = libs_dir / f"{lib_name}.md"
        existing = lib_file.read_text(encoding="utf-8") if lib_file.exists() else ""

        addition = "\n\n---\n\n".join(s.strip("\n") for s in sections if s.strip())
        if not addition:
            continue

        if existing.strip():
            new_content = existing.rstrip() + "\n\n---\n\n" + addition + "\n"
        else:
            new_content = addition + "\n"

        lib_file.write_text(new_content, encoding="utf-8")
        print(f"{lib_name}: Added {len(sections)} section(s)")
        total_added += len(sections)

    if missing_in_plan:
        print("\nIDs in libs.md missing from plan.md:")
        for id_name in sorted(missing_in_plan)[:50]:
            print(f"  - {id_name}")
        if len(missing_in_plan) > 50:
            print(f"  ... and {len(missing_in_plan) - 50} more")

    print("\n" + "=" * 60)
    print(f"Total sections added: {total_added}")


if __name__ == "__main__":
    main()
