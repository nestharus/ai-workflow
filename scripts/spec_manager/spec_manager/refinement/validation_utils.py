"""Shared validation utilities for evidence pointer resolution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .formats import EVIDENCE_POINTER_RE

SECTION_ID_RE = re.compile(r"^SEC-[A-Za-z0-9]+-\d{4}$")


def build_file_id_lookup(
    file_manifest: dict[str, dict[str, str]], spec_snapshot_dir: Path | None = None
) -> dict[str, str]:
    """Build a lookup mapping various file identifiers to canonical file_id.

    Maps: file_id, relpath, resolved absolute path, filename, and stem.
    """
    lookup: dict[str, str] = {}
    spec_snapshot_dir = spec_snapshot_dir or Path.cwd()
    for file_id, file_data in file_manifest.items():
        _add_lookup(lookup, file_id, file_id)
        relpath = file_data["relpath"]
        _add_lookup(lookup, relpath, file_id)
        _add_lookup(lookup, f"spec_snapshot/{relpath}", file_id)
        path = Path(relpath)
        if not path.is_absolute():
            path = spec_snapshot_dir / path
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = ""
        if resolved:
            _add_lookup(lookup, resolved, file_id)
        if path.name:
            _add_lookup(lookup, path.name, file_id)
        if path.stem:
            _add_lookup(lookup, path.stem, file_id)
    return lookup


def build_section_alias_map(
    section_manifest: dict[str, list[str]],
) -> dict[str, dict[str, str]]:
    """Build a normalized section label alias map for each file.

    Normalizes legacy labels while keeping section IDs canonical.
    """
    alias_map: dict[str, dict[str, str]] = {}
    for file_id, section_labels in section_manifest.items():
        normalized_map: dict[str, str] = {}
        for section_label in section_labels:
            if not section_label:
                continue
            if SECTION_ID_RE.match(section_label):
                normalized_map[section_label] = section_label
                continue
            normalized = _normalize_section_label(section_label)
            if not normalized:
                continue
            if normalized in normalized_map:
                continue
            normalized_map[normalized] = section_label
        alias_map[file_id] = normalized_map
    return alias_map


def build_section_id_lookup(file_id: str, sections_data: dict[str, Any]) -> dict[str, str]:
    """Build lookup mapping section IDs and labels to canonical section IDs."""
    lookup: dict[str, str] = {}
    sections = sections_data.get("sections") if isinstance(sections_data, dict) else None
    if not isinstance(sections, list):
        return lookup
    for entry in sections:
        if not isinstance(entry, dict):
            continue
        section_id = entry.get("section_id")
        label = entry.get("label")
        if isinstance(section_id, str) and section_id:
            lookup.setdefault(section_id, section_id)
        if isinstance(label, str) and label:
            target = section_id if isinstance(section_id, str) and section_id else label
            lookup.setdefault(label, target)
            normalized = _normalize_section_label(label)
            if normalized:
                lookup.setdefault(normalized, target)
    return lookup


def resolve_section_reference(
    section_ref: str,
    file_id: str,
    alias_map: dict[str, dict[str, str]],
    sections_data: dict[str, Any] | None = None,
) -> str | None:
    """Resolve a section reference to a canonical section ID when possible."""
    if not section_ref:
        return None
    section_ref = section_ref.strip()
    if sections_data:
        lookup = build_section_id_lookup(file_id, sections_data)
        if section_ref in lookup:
            return lookup[section_ref]
        normalized = _normalize_section_label(section_ref)
        if normalized and normalized in lookup:
            return lookup[normalized]
    if re.fullmatch(rf"SEC-{re.escape(file_id)}-\d{{4}}", section_ref):
        if section_ref in alias_map.get(file_id, {}):
            return section_ref
        return None
    normalized = _normalize_section_label(section_ref)
    if not normalized:
        return None
    return alias_map.get(file_id, {}).get(normalized)


def _normalize_section_label(label: str) -> str:
    return label.strip().lower().replace(" ", "_").replace("-", "_")


def _add_lookup(lookup: dict[str, str], key: str, value: str) -> None:
    if not key:
        return
    if key in lookup:
        return
    lookup[key] = value


def strip_invalid_file_pointers(
    content: str,
    file_manifest: dict[str, dict[str, str]],
    *,
    allow_multi_hop: bool = False,
) -> str:
    """Remove evidence pointers with invalid file references from content.

    When allow_multi_hop is True, keep multi-hop pointers (e.g. library
    citations like [LIB-0001::spec.md::REQS]) even if the file_ref is not
    in the file manifest. Also collapses redundant whitespace from removed
    pointers.
    """
    invalid_pointers: set[str] = set()
    file_id_lookup = build_file_id_lookup(file_manifest)
    for match in EVIDENCE_POINTER_RE.finditer(content):
        file_ref = match.group(1).strip()
        section_ref = match.group(2).strip()
        resolved_file_id = file_id_lookup.get(file_ref)
        if resolved_file_id is None:
            if allow_multi_hop and "::" in section_ref:
                continue
            invalid_pointers.add(match.group(0))

    cleaned = content
    for pointer in invalid_pointers:
        cleaned = cleaned.replace(pointer, "")

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" \n", "\n", cleaned)
    return cleaned
