"""Routing data structures for Phase 0 intake."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceSpan:
    """A contiguous range of lines in a source file."""

    file: str  # relative path to source file
    start: int  # 1-based start line (inclusive)
    end: int  # 1-based end line (inclusive)


@dataclass
class RouteEntry:
    """One routing decision: source span -> destination."""

    route_id: str  # unique ID, e.g. "R-000001"
    src: SourceSpan
    library: str  # library ID, e.g. "LIB-01"
    category: str  # ANALYSIS | CONSTRAINTS | DETAIL/ALGORITHM | DETAIL/STORE | DETAIL/SHAPE | IGNORED
    element_id: str  # e.g. "ALG-LIB01-001"
    notes: str = ""  # free-text from LLM explaining decision
    ref_stubs: list[str] = field(default_factory=list)  # unresolved cross-file references


@dataclass
class LibraryDef:
    """A discovered library."""

    lib_id: str  # e.g. "LIB-01"
    name: str  # human-readable name
    description: str  # one-line summary of responsibility


@dataclass
class CoverageLedgerEntry:
    """Coverage status for a line range."""

    file: str
    start: int
    end: int
    status: str  # "routed" | "ignored" | "uncovered"
    route_ids: list[str] = field(default_factory=list)  # which routes cover these lines
    ignore_reason: str = ""  # if ignored, why
