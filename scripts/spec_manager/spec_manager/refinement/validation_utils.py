"""Shared validation utilities for evidence pointer resolution."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from spec_manager.core.file_id_lookup import (
    build_file_id_lookup as build_file_id_lookup,
)

from .formats import EVIDENCE_POINTER_NEW_RE, EVIDENCE_POINTER_RE

SECTION_ID_RE = re.compile(r"^SEC-[A-Za-z0-9]+-\d{4}$")
_SECTION_FILE_ID_RE = re.compile(r"^SEC-(F\d{4})-\d{4}$")

logger = logging.getLogger(__name__)


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


def strip_invalid_section_pointers(
    content: str,
    file_manifest: dict[str, dict[str, str]],
    section_reader: Callable[[str], dict[str, Any] | None],
) -> str:
    """Remove evidence pointers whose section_ref doesn't exist in the resolved file.

    Args:
        content: Text containing evidence pointers.
        file_manifest: File manifest mapping file_id -> {relpath, sha256}.
        section_reader: Callable(file_id) -> dict or None that reads section data.
    """
    invalid_pointers: set[str] = set()
    file_id_lookup = build_file_id_lookup(file_manifest)

    for match in EVIDENCE_POINTER_RE.finditer(content):
        file_ref = match.group(1).strip()
        section_ref = match.group(2).strip()
        resolved_file_id = file_id_lookup.get(file_ref)
        if resolved_file_id is None:
            continue
        sections_data = section_reader(resolved_file_id)
        if sections_data is None:
            continue
        sections_list = sections_data.get("sections") if isinstance(sections_data, dict) else None
        valid_section_ids: set[str] = set()
        if isinstance(sections_list, list):
            for entry in sections_list:
                if isinstance(entry, dict):
                    sid = entry.get("section_id")
                    if isinstance(sid, str) and sid:
                        valid_section_ids.add(sid)
        if valid_section_ids and section_ref not in valid_section_ids:
            invalid_pointers.add(match.group(0))
            logger.debug("Stripping invalid section pointer: %s", match.group(0))

    cleaned = content
    for pointer in invalid_pointers:
        cleaned = cleaned.replace(pointer, "")

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" \n", "\n", cleaned)
    return cleaned


def fix_cross_file_section_pointers(
    content: str,
    file_manifest: dict[str, dict[str, str]],
) -> str:
    """Rewrite evidence pointers whose file_ref mismatches the section's embedded file_id.

    LLMs sometimes emit pointers like ``[spec_snapshot/wrong.md::SEC-F0002-0001]``
    where the relpath resolves to a different file_id than the one embedded in the
    section reference.  This function detects such mismatches and rewrites the
    file_ref to the correct relpath from the manifest.
    """
    file_id_lookup = build_file_id_lookup(file_manifest)
    # Build reverse lookup: file_id -> relpath
    relpath_by_file_id: dict[str, str] = {}
    for fid, entry in file_manifest.items():
        if isinstance(entry, dict) and "relpath" in entry:
            relpath_by_file_id[fid] = entry["relpath"]

    replacements: list[tuple[str, str]] = []

    for match in EVIDENCE_POINTER_NEW_RE.finditer(content):
        file_ref = match.group(1).strip()
        section_ref = match.group(2).strip()
        resolved_file_id = file_id_lookup.get(f"spec_snapshot/{file_ref}") or file_id_lookup.get(
            file_ref
        )
        section_file_match = _SECTION_FILE_ID_RE.match(section_ref)
        if not section_file_match:
            continue
        section_file_id = section_file_match.group(1)
        if resolved_file_id == section_file_id:
            continue
        # Mismatch: section belongs to a different file than the pointer references
        correct_relpath = relpath_by_file_id.get(section_file_id)
        if not correct_relpath:
            continue
        old_pointer = match.group(0)
        new_pointer = f"[spec_snapshot/{correct_relpath}::{section_ref}]"
        if old_pointer != new_pointer:
            replacements.append((old_pointer, new_pointer))
            logger.debug(
                "Fixed cross-file pointer: %s -> %s",
                old_pointer,
                new_pointer,
            )

    result = content
    for old, new in replacements:
        result = result.replace(old, new)
    return result
