"""Known bad signature scanning for QA case outputs."""

from __future__ import annotations

import re
from typing import Any


_SIGNATURES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "derived_pointer",
        re.compile(r"\\[(?:charter|charter\\.md|(?:libraries|runs)[\\/][^\\]]+?)::[^\\]]+?\\]", re.IGNORECASE),
        "Contains a derived/placeholder pointer (charter/libraries/runs) in citation space.",
    ),
    (
        "arch_file_pointer",
        re.compile(r"\\[file_\\d+::", re.IGNORECASE),
        "Contains a [file_###::...] citation where a library-pointer citation is expected.",
    ),
    (
        "runner_file_pointer",
        re.compile(r"see `[^`]+` for details\\.?$", re.IGNORECASE | re.MULTILINE),
        "Runner produced a file-pointer message instead of the actual content.",
    ),
    (
        "evidence_mapper_heading_sections",
        re.compile(r"\"relevant_sections\"\\s*:\\s*\\[[^\\]]*(\"Components\"|\"Workflows\"|\"Algorithms\")[^\\]]*\\]", re.IGNORECASE),
        "Evidence mapper returned summary headings as section identifiers.",
    ),
]


def scan_known_bad_signatures(text: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for signature_id, pattern, message in _SIGNATURES:
        match = pattern.search(text or "")
        if not match:
            continue
        excerpt = match.group(0)
        issues.append(
            {
                "type": "known_bad_signature",
                "signature": signature_id,
                "message": message,
                "excerpt": excerpt[:200],
            }
        )
    return issues

