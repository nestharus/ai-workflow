#!/usr/bin/env python3
"""
Normalize and validate annotation syntax in gen3 rag markdown files.

Target annotation forms:
- Declaration: ([=ID])
- Reference (related): (@[+ID])
- Reference (label-attached): (@[=ID])

Legacy/illegal forms this script can fix:
- [(=ID)]          -> ([=ID])
- (=[ID])          -> (@[=ID])
- (+[ID])          -> (@[+ID])

This script also scans for any parenthetical groups that contain square brackets
and reports those that look like legacy/illegal annotations.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# New canonical patterns
DECLARATION = re.compile(r"\(\[=([^\]]+)\]\)")
REF_RELATED = re.compile(r"\(@\[\+([^\]]+)\]\)")
REF_LABEL = re.compile(r"\(@\[=([^\]]+)\]\)")

# Legacy patterns
LEGACY_DECL = re.compile(r"\[\(=([^\]]+)\)\]")
LEGACY_REF_RELATED = re.compile(r"\(\+\[([^\]]+)\]\)")
LEGACY_REF_LABEL = re.compile(r"\(=\[([^\]]+)\]\)")

# Generic "something in parentheses with at least one []"
PAREN_WITH_BRACKET = re.compile(r"\([^)]*\[[^)]*\)")

# Allowed non-annotation markdown patterns like ([text][ref]) or ([text](url))
MARKDOWN_REF_LINK = re.compile(r"^\(\[[^\]]+\]\[[^\]]+\]\)$")
MARKDOWN_INLINE_LINK = re.compile(r"^\(\[[^\]]+\]\([^)]+\)\)$")


@dataclass(frozen=True)
class Finding:
    path: Path
    line_num: int
    snippet: str
    kind: str


def default_targets(base_dir: Path) -> list[Path]:
    targets = [base_dir / "plan.md"]
    targets.extend(sorted((base_dir / "libraries").glob("*.md")))
    return [p for p in targets if p.exists()]


def normalize_text(text: str) -> tuple[str, int]:
    replaced = 0

    def _sub_count(pattern: re.Pattern[str], repl: str, s: str) -> tuple[str, int]:
        new_s, n = pattern.subn(repl, s)
        return new_s, n

    text, n = _sub_count(LEGACY_DECL, r"([=\1])", text)
    replaced += n
    text, n = _sub_count(LEGACY_REF_RELATED, r"(@[+\1])", text)
    replaced += n
    text, n = _sub_count(LEGACY_REF_LABEL, r"(@[=\1])", text)
    replaced += n

    return text, replaced


def find_illegal_parenthetical_groups(path: Path, lines: list[str]) -> tuple[list[Finding], list[Finding]]:
    illegal: list[Finding] = []
    unknown: list[Finding] = []

    for line_num, line in enumerate(lines, 1):
        for match in PAREN_WITH_BRACKET.finditer(line):
            group = match.group(0)

            if (
                DECLARATION.fullmatch(group)
                or REF_RELATED.fullmatch(group)
                or REF_LABEL.fullmatch(group)
                or MARKDOWN_REF_LINK.fullmatch(group)
                or MARKDOWN_INLINE_LINK.fullmatch(group)
            ):
                continue

            if LEGACY_REF_LABEL.fullmatch(group) or LEGACY_REF_RELATED.fullmatch(group):
                illegal.append(Finding(path=path, line_num=line_num, snippet=group, kind="legacy-annotation"))
                continue

            unknown.append(Finding(path=path, line_num=line_num, snippet=group, kind="unknown"))

    return illegal, unknown


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize and validate annotation syntax.")
    parser.add_argument("--fix", action="store_true", help="Rewrite files in-place to normalize annotations.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if unknown parenthetical-bracket patterns exist (non-annotation markdown links are allowed).",
    )
    parser.add_argument("paths", nargs="*", help="Files to process (defaults to plan.md + libraries/*.md).")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[1]
    targets = [Path(p) for p in args.paths] if args.paths else default_targets(base_dir)
    targets = [p if p.is_absolute() else (Path.cwd() / p) for p in targets]

    total_replaced = 0
    all_illegal: list[Finding] = []
    all_unknown: list[Finding] = []

    for path in targets:
        if not path.exists():
            print(f"Missing file: {path}", file=sys.stderr)
            return 2
        if path.is_dir():
            print(f"Skipping directory: {path}", file=sys.stderr)
            continue

        original = path.read_text(encoding="utf-8")
        updated = original
        replaced = 0
        if args.fix:
            updated, replaced = normalize_text(updated)
            if replaced:
                path.write_text(updated, encoding="utf-8")

        lines = (updated if args.fix else original).splitlines()
        illegal, unknown = find_illegal_parenthetical_groups(path, lines)
        all_illegal.extend(illegal)
        all_unknown.extend(unknown)
        total_replaced += replaced

    if args.fix:
        print(f"Rewrites applied: {total_replaced}")

    print(f"Illegal legacy annotations: {len(all_illegal)}")
    for f in all_illegal[:200]:
        print(f"{f.path}:{f.line_num}: {f.snippet}")
    if len(all_illegal) > 200:
        print("... (truncated)")

    print(f"Unknown parenthetical bracket groups: {len(all_unknown)}")
    for f in all_unknown[:50]:
        print(f"{f.path}:{f.line_num}: {f.snippet}")
    if len(all_unknown) > 50:
        print("... (truncated)")

    if all_illegal:
        return 1
    if args.strict and all_unknown:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

