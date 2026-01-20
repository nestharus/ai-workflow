#!/usr/bin/env python3
"""
Check that declared annotations ([=ID]) are unique in plan.md.

Rules enforced:
- Each ID declared via ([=ID]) appears exactly once across plan.md
- Each line contains at most one ([=ID]) declaration
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path


DECLARATION = re.compile(r"\(\[=([^\]]+)\]\)")


def main() -> int:
    base_dir = Path(__file__).resolve().parents[1]
    plan_path = base_dir / "plan.md"
    lines = plan_path.read_text(encoding="utf-8").splitlines()

    by_id: dict[str, list[int]] = defaultdict(list)
    multi_decl_lines: list[tuple[int, str, int]] = []

    for line_num, line in enumerate(lines, 1):
        ids = [m.group(1) for m in DECLARATION.finditer(line)]
        if not ids:
            continue
        if len(ids) > 1:
            multi_decl_lines.append((line_num, line.strip(), len(ids)))
        for id_str in ids:
            by_id[id_str].append(line_num)

    duplicates = {id_str: locs for id_str, locs in by_id.items() if len(locs) > 1}

    if not duplicates and not multi_decl_lines:
        print("OK: no duplicate declarations and no multi-declaration lines.")
        return 0

    if duplicates:
        print(f"DUPLICATE ([=ID]) DECLARATIONS: {len(duplicates)}", file=sys.stderr)
        for id_str, locs in sorted(duplicates.items(), key=lambda x: (len(x[1]) * -1, x[0])):
            loc_list = ", ".join(f"L{ln}" for ln in locs)
            print(f"  {id_str}: {loc_list}", file=sys.stderr)

    if multi_decl_lines:
        print(f"LINES WITH MULTIPLE ([=ID]) DECLARATIONS: {len(multi_decl_lines)}", file=sys.stderr)
        for line_num, text, count in multi_decl_lines[:50]:
            print(f"  L{line_num} ({count}): {text[:200]}", file=sys.stderr)
        if len(multi_decl_lines) > 50:
            print("  ... (truncated)", file=sys.stderr)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

