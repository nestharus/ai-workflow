#!/usr/bin/env python3
"""
List candidate headers (#/##/###) that do not include a declared annotation ([=ID]).

This is a heuristic report (not necessarily an error), but is useful for finding
orphaned headers that likely should declare an ID.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


DECLARATION = re.compile(r"\(\[=([^\]]+)\]\)")
HEADER = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Find headers missing ([=ID]) declarations.")
    parser.add_argument("--fail", action="store_true", help="Exit non-zero if any are found.")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[1]
    plan_path = base_dir / "plan.md"
    lines = plan_path.read_text(encoding="utf-8").splitlines()

    missing: list[tuple[int, int, str]] = []
    for line_num, line in enumerate(lines, 1):
        m = HEADER.match(line)
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2)
        if DECLARATION.search(text):
            continue
        missing.append((line_num, level, text.strip()))

    print(f"Headers (#/##/###) missing ([=ID]): {len(missing)}")
    for line_num, level, text in missing[:200]:
        print(f"L{line_num} {'#'*level} {text}")
    if len(missing) > 200:
        print("... (truncated)")

    return 1 if (args.fail and missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())

