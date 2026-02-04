from __future__ import annotations

import json
from pathlib import Path


def _validate_markdown_table(content: str, expected_headers: list[str]) -> bool:
    header_line = "| " + " | ".join(expected_headers) + " |"
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != header_line:
            continue
        if index + 1 >= len(lines):
            return False
        separator = lines[index + 1].strip()
        if not separator.startswith("|") or "---" not in separator:
            return False
        if index + 2 >= len(lines):
            return False
        return lines[index + 2].strip().startswith("|")
    return False


def _validate_json_index(path: Path, required_keys: set[str]) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return required_keys.issubset(payload.keys())


def _count_markdown_sections(content: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in content.splitlines():
        if line.startswith("## "):
            header = line[3:].strip()
            counts[header] = counts.get(header, 0) + 1
    return counts


def _extract_table_rows(content: str, table_header: str) -> list[list[str]]:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != table_header:
            continue
        if index + 1 >= len(lines):
            return []
        if not lines[index + 1].lstrip().startswith("|"):
            return []
        rows: list[list[str]] = []
        for row in lines[index + 2 :]:
            if not row.lstrip().startswith("|"):
                break
            cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
            rows.append(cells)
        return rows
    return []
