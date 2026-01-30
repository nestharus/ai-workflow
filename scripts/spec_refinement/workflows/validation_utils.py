"""Shared validation utilities for evidence pointer resolution."""

from __future__ import annotations

from pathlib import Path


def build_file_id_lookup(file_manifest: dict[str, str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for file_id, path_str in file_manifest.items():
        _add_lookup(lookup, file_id, file_id)
        _add_lookup(lookup, path_str, file_id)
        path = Path(path_str)
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
    alias_map: dict[str, dict[str, str]] = {}
    for file_id, section_labels in section_manifest.items():
        normalized_map: dict[str, str] = {}
        for section_label in section_labels:
            normalized = _normalize_section_label(section_label)
            if not normalized:
                continue
            if normalized in normalized_map:
                continue
            normalized_map[normalized] = section_label
        alias_map[file_id] = normalized_map
    return alias_map


def resolve_section_reference(
    section_ref: str,
    file_id: str,
    alias_map: dict[str, dict[str, str]],
) -> str | None:
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
