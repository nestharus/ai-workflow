#!/usr/bin/env python3
"""Run all writing tools on a Markdown draft.

Usage:
  python run_all.py path/to/draft.md --outdir out

Outputs:
  out/lint.md
  out/tempo.md
  out/readability.md
  out/skeleton.md
  out/borders.md
  out/outline.json
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--outdir", default="out")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    def run(cmd: list[str]) -> None:
        subprocess.run(cmd, check=False)

    tools_dir = os.path.dirname(os.path.abspath(__file__))

    run(
        [
            sys.executable,
            os.path.join(tools_dir, "lint_ai_tells.py"),
            args.path,
            "--output",
            os.path.join(args.outdir, "lint.md"),
        ]
    )
    run(
        [
            sys.executable,
            os.path.join(tools_dir, "tempo_report.py"),
            args.path,
            "--output",
            os.path.join(args.outdir, "tempo.md"),
        ]
    )
    run(
        [
            sys.executable,
            os.path.join(tools_dir, "readability_report.py"),
            args.path,
            "--output",
            os.path.join(args.outdir, "readability.md"),
        ]
    )
    run(
        [
            sys.executable,
            os.path.join(tools_dir, "extract_skeleton.py"),
            args.path,
            "--outdir",
            args.outdir,
        ]
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
