"""JSON extraction utilities for LLM output parsing."""

from __future__ import annotations

import json
from typing import Any


def _infer_extraction_method(original: str) -> str:
    stripped = original.lstrip()
    if stripped.startswith("```"):
        return "code_fence_removal"
    if "[agent-exec]" in original:
        return "preamble_stripping"
    first_obj = stripped.find("{")
    first_list = stripped.find("[")
    starts = [idx for idx in (first_obj, first_list) if idx != -1]
    if starts and min(starts) > 0:
        return "preamble_stripping"
    return "json_extraction"


def _record_json_extraction_evidence(
    original: str,
    extracted: str,
    evidence: list[dict[str, Any]] | None,
    *,
    location: str,
) -> None:
    if evidence is None or original == extracted:
        return
    extraction_method = _infer_extraction_method(original)
    evidence_type = (
        extraction_method
        if extraction_method in {"code_fence_removal", "preamble_stripping"}
        else "json_extraction"
    )
    evidence.append(
        {
            "category": "format",
            "type": evidence_type,
            "severity": "warning",
            "details": {
                "original_length": len(original),
                "cleaned_length": len(extracted),
                "extraction_method": extraction_method,
                "location": location,
            },
        }
    )


def _extract_json_payload(output: str) -> str:
    """Extract the first valid JSON object/array from an agent output string.

    This is intentionally tolerant of:
    - leading/trailing commentary
    - fenced code blocks
    - bracket characters appearing *after* the JSON payload
    """
    cleaned = output.strip()
    if not cleaned:
        return cleaned

    # Drop agent-exec noise lines (if any).
    lines = [line for line in cleaned.splitlines() if not line.startswith("[agent-exec]")]
    cleaned = "\n".join(lines).strip()

    # If the output is a fenced block, prefer the first fenced payload.
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            fence_end = cleaned.find("```", first_newline + 1)
            if fence_end != -1:
                cleaned = cleaned[first_newline + 1 : fence_end].strip()

    decoder = json.JSONDecoder()

    # Find the first plausible JSON start and attempt raw_decode from there.
    first_obj = cleaned.find("{")
    first_list = cleaned.find("[")
    starts = [idx for idx in (first_obj, first_list) if idx != -1]
    if not starts:
        return cleaned

    for start in sorted(starts):
        # Scan forward to the next '{' or '[' and try to decode.
        idx = start
        while idx < len(cleaned):
            ch = cleaned[idx]
            if ch not in "{[":
                idx += 1
                continue
            try:
                _, end = decoder.raw_decode(cleaned[idx:])
            except json.JSONDecodeError:
                idx += 1
                continue
            return cleaned[idx : idx + end]

    # Fallback: return from earliest start if we cannot decode (caller will raise).
    return cleaned[min(starts) :]
