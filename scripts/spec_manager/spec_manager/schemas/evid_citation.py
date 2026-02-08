"""EVID citation parsing and formatting utilities (CON-0021).

This module provides functions to parse, validate, and format EVID citations
in the canonical bracketed format: [EVID-F####-R####-L#-L#]

EVID citations are the canonical way to reference evidence ranges in
human-readable documents per CON-0021 and AUTH-0002.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .evidence_ranges import EVID_CITATION_PATTERN, EVIDENCE_ID_PATTERN

# Pattern to extract EVID from bracketed citation
_EVID_EXTRACT_PATTERN = re.compile(r"\[(EVID-F\d{4}-R\d{4}-L\d+-L\d+)\]")


@dataclass(frozen=True)
class EvidCitation:
    """Parsed EVID citation with components.

    Attributes:
        evid: Full EVID string (e.g., EVID-F0001-R0001-L1-L25)
        file_uid: File UID (e.g., F0001)
        rev_id: Revision ID (e.g., R0001)
        start_line: Start line number
        end_line: End line number
    """

    evid: str
    file_uid: str
    rev_id: str
    start_line: int
    end_line: int

    @property
    def bracketed(self) -> str:
        """Return the bracketed citation format."""
        return f"[{self.evid}]"


def parse_evid_citation(text: str) -> EvidCitation | None:
    """Parse a bracketed EVID citation string.

    Args:
        text: Text that may contain an EVID citation (e.g., '[EVID-F0001-R0001-L1-L25]')

    Returns:
        EvidCitation if valid citation found, None otherwise
    """
    text = text.strip()
    if not text:
        return None

    # Try to extract EVID from bracketed format
    extract_match = _EVID_EXTRACT_PATTERN.search(text)
    if extract_match:
        evid = extract_match.group(1)
    elif text.startswith("EVID-"):
        # Allow bare EVID format as well
        evid = text
    else:
        return None

    # Validate against the canonical pattern
    match = EVIDENCE_ID_PATTERN.fullmatch(evid)
    if not match:
        return None

    return EvidCitation(
        evid=evid,
        file_uid=match.group("file_uid"),
        rev_id=match.group("rev_id"),
        start_line=int(match.group("start")),
        end_line=int(match.group("end")),
    )


def format_evid_citation(evid: str) -> str:
    """Format an EVID string as a bracketed citation.

    Args:
        evid: EVID string (e.g., 'EVID-F0001-R0001-L1-L25')

    Returns:
        Bracketed citation (e.g., '[EVID-F0001-R0001-L1-L25]')

    Raises:
        ValueError: If evid is not a valid EVID format
    """
    evid = evid.strip()
    if not validate_evid_format(evid):
        raise ValueError(f"Invalid EVID format: {evid}")
    return f"[{evid}]"


def validate_evid_format(evid: str) -> bool:
    """Validate that a string is a valid EVID format.

    Args:
        evid: String to validate (without brackets)

    Returns:
        True if valid EVID format, False otherwise
    """
    if not evid:
        return False
    return EVIDENCE_ID_PATTERN.fullmatch(evid.strip()) is not None


def extract_evid_citations(text: str) -> list[EvidCitation]:
    """Extract all EVID citations from text.

    Args:
        text: Text that may contain multiple EVID citations

    Returns:
        List of parsed EvidCitation objects
    """
    citations: list[EvidCitation] = []
    for match in EVID_CITATION_PATTERN.finditer(text):
        citation = parse_evid_citation(match.group(0))
        if citation:
            citations.append(citation)
    return citations


def build_evid(
    file_uid: str,
    rev_id: str,
    start_line: int,
    end_line: int,
) -> str:
    """Build an EVID string from components.

    Args:
        file_uid: File UID (e.g., F0001)
        rev_id: Revision ID (e.g., R0001)
        start_line: Start line number (1-based)
        end_line: End line number (1-based, inclusive)

    Returns:
        EVID string (e.g., 'EVID-F0001-R0001-L1-L25')

    Raises:
        ValueError: If components are invalid
    """
    if not re.fullmatch(r"F\d{4}", file_uid):
        raise ValueError(f"Invalid file_uid format: {file_uid}")
    if not re.fullmatch(r"R\d{4}", rev_id):
        raise ValueError(f"Invalid rev_id format: {rev_id}")
    if start_line < 1:
        raise ValueError(f"start_line must be >= 1, got {start_line}")
    if end_line < start_line:
        raise ValueError(f"end_line ({end_line}) must be >= start_line ({start_line})")

    return f"EVID-{file_uid}-{rev_id}-L{start_line}-L{end_line}"
