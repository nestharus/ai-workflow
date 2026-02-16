"""Known bad signature scanning for QA case outputs."""

from __future__ import annotations

import re
from typing import Any

_SIGNATURES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "derived_pointer",
        re.compile(
            r"\[(?:charter(?:\.md)?|(?:libraries|runs)[\\/][^\]]+?)::[^\]]+?\]",
            re.IGNORECASE,
        ),
        "Contains a derived/placeholder pointer (charter/libraries/runs) in citation space.",
    ),
    (
        "arch_file_pointer",
        re.compile(r"\[(?:F\d{4}|spec_snapshot/[^:]+)::", re.IGNORECASE),
        "Contains a file-based citation where a library-pointer citation is expected.",
    ),
    (
        "legacy_pointer_format",
        re.compile(r"\[F\d{4}::[A-Z_]+\]", re.IGNORECASE),
        "Contains legacy [file_id::LABEL] pointer format; should use "
        "[spec_snapshot/<relpath>::SEC-...] format.",
    ),
    (
        "runner_file_pointer",
        re.compile(r"see `[^`]+` for details\.?$", re.IGNORECASE | re.MULTILINE),
        "Runner produced a file-pointer message instead of the actual content.",
    ),
    (
        "evidence_mapper_heading_sections",
        re.compile(
            r'"relevant_sections"\s*:\s*\[[^\]]*("Components"|"Workflows"|"Algorithms"|"(?!SEC-)[^"]+")[^\]]*\]',
            re.IGNORECASE,
        ),
        "Evidence mapper returned summary headings or non-section IDs as identifiers.",
    ),
    # CON-0021: Legacy pointers in evidence fields (should be EVID-only)
    (
        "legacy_pointer_in_evidence",
        re.compile(
            r'"(?:evidence|evidence_id|evidence_ids|citations)"[^:]*:\s*'
            r'(?:\[[^\]]*)?"\[?(?:F\d{4}|LIB-\d{4}|spec_snapshot/)[^"]*"',
            re.IGNORECASE,
        ),
        "Evidence field contains legacy pointer format; should use EVID-F####-R####-L#-L# format.",
    ),
    # CON-0021: spec_snapshot in evidence context
    (
        "spec_snapshot_in_evidence",
        re.compile(
            r'"(?:evidence|evidence_id|evidence_ids|citations)"[^:]*:\s*'
            r'(?:\[[^\]]*)?"\[?spec_snapshot/[^"]*"',
            re.IGNORECASE,
        ),
        "Evidence field contains spec_snapshot pointer; should use EVID-F####-R####-L#-L# format.",
    ),
]


def scan_known_bad_signatures(text: str) -> list[dict[str, Any]]:
    """Scan text for known bad signature patterns."""
    issues: list[dict[str, Any]] = []
    for signature_id, pattern, message in _SIGNATURES:
        for occurrence, match in enumerate(pattern.finditer(text or ""), start=1):
            excerpt = match.group(0)
            issues.append(
                {
                    "type": "known_bad_signature",
                    "signature": signature_id,
                    "message": message,
                    "occurrence": occurrence,
                    "excerpt": excerpt[:200],
                }
            )
    return issues
