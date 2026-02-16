"""Fact tagging for decomposed workspaces.

This module assigns stable Fact IDs (F-###) to source lines referenced by extracted IDs.

Design goal: avoid rewriting spec content. Fact records are derived from the original
snapshot stored under `workspace/original/`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.decomposition.id_generator import (
    IDType,
    load_id_map,
    save_id_map,
)
from spec_manager.decomposition.workspace import resolve_original_copy

logger = logging.getLogger(__name__)


def _skip_header_lines(lines: list[str]) -> int:
    """Return the index where tool-added header ends."""
    i = 0
    while i < len(lines) and lines[i].startswith("<!--"):
        i += 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return i


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _next_fact_id(existing: dict[str, Any]) -> str:
    max_n = 0
    prefix = f"{IDType.FACT.value}-"
    for fid in existing:
        if not isinstance(fid, str) or not fid.startswith(prefix):
            continue
        suffix = fid[len(prefix) :]
        if not suffix.isdigit():
            continue
        max_n = max(max_n, int(suffix))
    return f"{IDType.FACT.value}-{max_n + 1:03d}"


def _read_utf8_lines(path: Path) -> list[str] | None:
    """Read a file as UTF-8, returning lines or None on failure."""
    try:
        return path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return None


def _read_source_line_from_original_copy(
    workspace: Path, source_file: str, line_number: int
) -> str:
    """Read a 1-indexed source line from the workspace's original snapshot."""
    if line_number <= 0:
        return ""

    # Only the stored original copy is authoritative.
    original_copy = resolve_original_copy(workspace, source_file)
    if not original_copy or not original_copy.exists():
        raise FileNotFoundError(
            f"Missing workspace original copy for source '{source_file}'. "
            "Re-run workspace initialization to restore authoritative snapshots."
        )

    content_lines = _read_utf8_lines(original_copy)
    if content_lines is None:
        raise OSError(f"Failed to read workspace original copy: {original_copy}")

    start = _skip_header_lines(content_lines)
    body = content_lines[start:]
    idx = line_number - 1
    if 0 <= idx < len(body):
        return body[idx]

    return ""


def tag_facts(workspace: Path) -> dict[str, Any]:
    """Assign Fact IDs to source lines referenced in id_map.

    Writes:
    - workspace/facts.json : canonical fact store keyed by F-###
    - workspace/id_map.json : annotates each source entry with `fact_id`
    """
    workspace = Path(workspace)
    id_map = load_id_map(workspace)

    facts_path = workspace / "facts.json"
    facts: dict[str, Any] = {}
    if facts_path.exists():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
        except Exception as err:
            logger.exception("Failed to parse facts.json at %s", facts_path)
            raise ValueError(
                f"facts.json is malformed at {facts_path}; "
                "refusing to overwrite authoritative data."
            ) from err

    # Reverse index by (file|line) for stability.
    by_source: dict[str, str] = {}
    for fid, record in facts.items():
        if not isinstance(record, dict):
            continue
        file = record.get("file")
        line = record.get("line")
        if (
            isinstance(file, str)
            and isinstance(line, int)
            and line > 0
            and file.strip()
            and file != "unknown"
        ):
            by_source[f"{file}|{line}"] = fid

    sources_tagged = 0
    new_facts = 0
    missing_text = 0

    for _id, sources in list(id_map.items()):
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue

            file = source.get("file")
            line = source.get("line")
            if (
                not isinstance(file, str)
                or not isinstance(line, int)
                or line <= 0
                or not file.strip()
                or file == "unknown"
            ):
                continue

            key = f"{file}|{line}"
            fid = by_source.get(key)
            if not fid:
                fid = _next_fact_id(facts)
                by_source[key] = fid
                new_facts += 1

            text = _read_source_line_from_original_copy(workspace, file, line)
            if not text:
                missing_text += 1

            record = {
                "file": file,
                "line": line,
                "text": text,
                "hash": _sha256_text(text),
            }
            facts[fid] = record

            if source.get("fact_id") != fid:
                source["fact_id"] = fid
                sources_tagged += 1

    # Materialize fact records in id_map so facts participate in summary/counts
    # and future ID generation.
    for fid, rec in facts.items():
        if not isinstance(rec, dict):
            continue
        file = rec.get("file")
        line = rec.get("line")
        if isinstance(file, str) and isinstance(line, int):
            id_map[fid] = [
                {
                    "file": file,
                    "line": line,
                    "type": "fact",
                    "hash": rec.get("hash", ""),
                }
            ]

    save_id_map(workspace, id_map)
    facts_path.write_text(json.dumps(facts, indent=2), encoding="utf-8")

    return {
        "facts_file": str(facts_path),
        "facts": len(facts),
        "new_facts": new_facts,
        "sources_tagged": sources_tagged,
        "missing_text": missing_text,
    }
