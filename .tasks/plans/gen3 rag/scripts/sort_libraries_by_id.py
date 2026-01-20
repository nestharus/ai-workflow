#!/usr/bin/env python3
"""
Sort library sections alphabetically by ID while preserving header+body content.
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
]

ANNOTATION_PATTERN = re.compile(r"\(\[=([^\]]+)\]\)")


def is_legal_id(text: str) -> bool:
    for pattern in ID_PATTERNS_LEGAL:
        if re.match(f"^{pattern}$", text):
            return True
    return False


def extract_sections(lines: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    prefix: list[str] = []
    sections: list[tuple[str, list[str]]] = []

    i = 0
    first_section = True
    while i < len(lines):
        match = ANNOTATION_PATTERN.search(lines[i])
        if match and is_legal_id(match.group(1)):
            if first_section:
                prefix = lines[:i]
                first_section = False
            section_id = match.group(1)
            start = i
            i += 1
            while i < len(lines):
                next_match = ANNOTATION_PATTERN.search(lines[i])
                if next_match and is_legal_id(next_match.group(1)):
                    break
                i += 1
            sections.append((section_id, lines[start:i]))
        else:
            i += 1

    return prefix, sections


def sort_library_file(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    has_trailing_newline = content.endswith("\n")

    prefix, sections = extract_sections(lines)
    if not sections:
        return False

    sorted_sections = sorted(sections, key=lambda item: item[0].casefold())
    if [section_id for section_id, _ in sections] == [section_id for section_id, _ in sorted_sections]:
        return False

    new_lines: list[str] = []
    new_lines.extend(prefix)
    for _, section_lines in sorted_sections:
        new_lines.extend(section_lines)

    new_content = "\n".join(new_lines)
    if has_trailing_newline and not new_content.endswith("\n"):
        new_content += "\n"
    path.write_text(new_content, encoding="utf-8")
    return True


def main() -> None:
    base = Path(__file__).resolve().parents[1]
    libs_dir = base / "libraries"

    updated = 0
    for lib_file in sorted(libs_dir.glob("*.md")):
        if sort_library_file(lib_file):
            updated += 1
            print(f"sorted: {lib_file.name}")
        else:
            print(f"unchanged: {lib_file.name}")

    print(f"\nUpdated {updated} library file(s).")


if __name__ == "__main__":
    main()
