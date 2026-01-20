#!/usr/bin/env python3
"""
Find empty stub sections in libraries/ based on ([=ID]) annotation boundaries.

Definition:
- A section starts on a line containing ([=ID]) where ID matches a legal pattern.
- The section body continues until the next ([=ID]) line (or EOF).
- A section is an "empty stub" if its body contains no non-whitespace characters.

This script optionally cross-references plan.md to highlight stubs that now have
content in plan.md (i.e., libraries are out of sync).
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
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
    return any(re.fullmatch(pattern, text) for pattern in ID_PATTERNS_LEGAL)


@dataclass(frozen=True)
class Section:
    id_name: str
    header_line: str
    start_line: int
    end_line: int
    body: str

    @property
    def body_stripped(self) -> str:
        return self.body.strip()

    @property
    def header_level(self) -> int | None:
        stripped = self.header_line.lstrip()
        if not stripped.startswith("#"):
            return None
        match = re.match(r"^(#+)", stripped)
        return len(match.group(1)) if match else None


def extract_sections_by_annotation(lines: list[str]) -> list[Section]:
    sections: list[Section] = []

    idx = 0
    while idx < len(lines):
        match = ANNOTATION_PATTERN.search(lines[idx])
        if match and is_legal_id(match.group(1)):
            id_name = match.group(1)
            header_line = lines[idx]
            start_idx = idx
            idx += 1

            body_lines: list[str] = []
            while idx < len(lines):
                next_match = ANNOTATION_PATTERN.search(lines[idx])
                if next_match and is_legal_id(next_match.group(1)):
                    break
                body_lines.append(lines[idx])
                idx += 1

            sections.append(
                Section(
                    id_name=id_name,
                    header_line=header_line,
                    start_line=start_idx + 1,
                    end_line=idx + 1,
                    body="\n".join(body_lines),
                )
            )
            continue

        idx += 1

    return sections


def main() -> int:
    parser = argparse.ArgumentParser(description="Find empty stubs in libraries/")
    parser.add_argument(
        "--base",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Base directory (defaults to this script's directory)",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="Path to plan.md (defaults to <base>/plan.md)",
    )
    parser.add_argument(
        "--libs-dir",
        type=Path,
        default=None,
        help="Path to libraries/ (defaults to <base>/libraries)",
    )
    args = parser.parse_args()

    base: Path = args.base
    plan_path: Path = args.plan if args.plan is not None else (base / "plan.md")
    libs_dir: Path = args.libs_dir if args.libs_dir is not None else (base / "libraries")

    if not plan_path.exists():
        raise SystemExit(f"plan.md not found: {plan_path}")
    if not libs_dir.exists():
        raise SystemExit(f"libraries/ not found: {libs_dir}")

    plan_lines = plan_path.read_text(encoding="utf-8").split("\n")
    plan_sections = {s.id_name: s for s in extract_sections_by_annotation(plan_lines)}

    empty: list[tuple[str, Path, Section]] = []
    total_sections = 0

    for lib_file in sorted(libs_dir.glob("*.md")):
        lib_lines = lib_file.read_text(encoding="utf-8").split("\n")
        sections = extract_sections_by_annotation(lib_lines)
        total_sections += len(sections)

        for section in sections:
            if section.body_stripped:
                continue
            empty.append((section.id_name, lib_file, section))

    print(f"Library sections: {total_sections}")
    print(f"Empty stubs: {len(empty)}")

    if not empty:
        return 0

    print("\n--- Empty stubs (libraries/) ---")
    for id_name, lib_file, lib_section in sorted(empty, key=lambda x: (x[1].name, x[2].start_line)):
        plan_section = plan_sections.get(id_name)

        if plan_section is None:
            status = "missing_in_plan"
            plan_info = ""
        elif plan_section.body_stripped:
            status = "plan_has_body"
            plan_info = f" | plan.md:{plan_section.start_line}"
        else:
            status = "plan_empty"
            plan_info = f" | plan.md:{plan_section.start_line}"

        print(f"- {lib_file.name}:{lib_section.start_line}: {id_name} ({status}){plan_info}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
