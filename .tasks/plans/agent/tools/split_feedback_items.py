"""Split a markdown feedback file into per-item markdown files.

This helper supports the workflow of delegating each feedback item to an
individual sub-agent.

It extracts *top-level* list items (bullets at column 0: '-', '*', '+') and
writes each item (including its indented sub-bullets) to its own file.

Usage:

  uv run python .tasks/plans/agent/tools/split_feedback_items.py \
    --input .tasks/plans/agent/feedback3.md \
    --output-dir .tasks/plans/agent/.tmp/feedback3-items
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


_TOP_LEVEL_BULLET_RE = re.compile(r"^(?P<marker>[-*+])\s+(?P<text>.*)$")


@dataclass(frozen=True)
class SplitItem:
    index: int
    title: str
    content: str


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_top_level_list_items(markdown: str) -> list[SplitItem]:
    """Split markdown into per-item chunks based on top-level bullets.

    A "top-level" item is a bullet marker at column 0.
    Indented lines belong to the current top-level item.
    """

    lines = _normalize_newlines(markdown).split("\n")
    items: list[SplitItem] = []
    current_lines: list[str] = []
    current_title: str | None = None

    def flush() -> None:
        nonlocal current_lines, current_title
        if not current_lines:
            return
        content = "\n".join(current_lines).rstrip() + "\n"
        title = (current_title or "(untitled)").strip()
        items.append(SplitItem(index=len(items) + 1, title=title, content=content))
        current_lines = []
        current_title = None

    started = False
    for line in lines:
        match = _TOP_LEVEL_BULLET_RE.match(line)
        if match is not None:
            started = True
            flush()
            current_lines.append(line)
            current_title = match.group("text").strip()
            continue

        if not started:
            # Ignore any preamble before the first top-level bullet.
            continue

        if current_lines:
            current_lines.append(line)

    flush()
    return items


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split a markdown feedback file into per-item markdown files.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Input markdown path",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory to write per-item files into",
    )
    parser.add_argument(
        "--basename",
        default="feedback-item",
        help="Base filename for output (default: feedback-item)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing files in output-dir",
    )

    args = parser.parse_args()
    input_path: Path = args.input
    output_dir: Path = args.output_dir
    basename: str = str(args.basename)
    overwrite: bool = bool(args.overwrite)

    markdown = input_path.read_text(encoding="utf-8")
    items = split_top_level_list_items(markdown)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "input": str(input_path),
        "count": len(items),
        "items": [],
    }

    for item in items:
        filename = f"{basename}-{item.index:02d}.md"
        out_path = output_dir / filename
        if out_path.exists() and not overwrite:
            raise SystemExit(
                f"Refusing to overwrite existing file: {out_path} (pass --overwrite)"
            )
        _write_text(out_path, item.content)
        manifest["items"].append(
            {
                "index": item.index,
                "title": item.title,
                "file": str(out_path),
            }
        )

    _write_text(output_dir / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

