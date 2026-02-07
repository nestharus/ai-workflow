"""Evidence pointer parsing utilities.

Evidence pointers reference specific sections within spec snapshot files.
Two formats exist:

- New format: ``[spec_snapshot/<relpath>::<section_id>]``
- Legacy format: ``[<file_ref>::<section_ref>]``
"""

from __future__ import annotations

import re

EVIDENCE_POINTER_RE = re.compile(r"\[([^\[\]]+?)::([^\[\]]+?)\]")
EVIDENCE_POINTER_NEW_RE = re.compile(r"\[spec_snapshot/([^:]+)::([^\]]+)\]")


def parse_evidence_pointer(pointer: str, *, allow_multi_hop: bool = False) -> dict[str, str] | None:
    """Parse evidence pointer into file/section refs and format type.

    When *allow_multi_hop* is ``True``, three-part pointers such as
    ``[file_ref::intermediate::section_ref]`` are accepted and the result
    includes an ``"intermediate"`` key.  When ``False`` (the default),
    multi-hop pointers cause the function to return ``None``.
    """
    cleaned = pointer.strip()
    if not cleaned:
        return None
    if "::" in cleaned and not cleaned.startswith("["):
        cleaned = f"[{cleaned}]"
    match = EVIDENCE_POINTER_NEW_RE.fullmatch(cleaned)
    if match:
        file_ref = match.group(1).strip()
        section_ref = match.group(2).strip()
        if "::" in section_ref:
            if not allow_multi_hop:
                return None
            intermediate, _, final_section = section_ref.partition("::")
            return {
                "file_ref": file_ref,
                "intermediate": intermediate.strip(),
                "section_ref": final_section.strip(),
                "format": "new",
            }
        return {
            "file_ref": file_ref,
            "section_ref": section_ref,
            "format": "new",
        }
    match = EVIDENCE_POINTER_RE.fullmatch(cleaned)
    if match:
        file_ref = match.group(1).strip()
        section_ref = match.group(2).strip()
        if "::" in section_ref:
            if not allow_multi_hop:
                return None
            intermediate, _, final_section = section_ref.partition("::")
            return {
                "file_ref": file_ref,
                "intermediate": intermediate.strip(),
                "section_ref": final_section.strip(),
                "format": "legacy",
            }
        return {
            "file_ref": file_ref,
            "section_ref": section_ref,
            "format": "legacy",
        }
    return None


def extract_pointer_components(pointer: str) -> tuple[str, str, str] | None:
    """Extract file reference, section reference, and format from an evidence pointer."""
    parsed = parse_evidence_pointer(pointer)
    if not parsed:
        return None
    return parsed["file_ref"], parsed["section_ref"], parsed["format"]
