"""Tests for intake routing data structures."""

from __future__ import annotations

from spec_manager.intake.types import (
    CoverageLedgerEntry,
    LibraryDef,
    RouteEntry,
    SourceSpan,
)


class TestSourceSpan:
    def test_construction(self) -> None:
        span = SourceSpan(file="spec.md", start=1, end=10)
        assert span.file == "spec.md"
        assert span.start == 1
        assert span.end == 10

    def test_single_line(self) -> None:
        span = SourceSpan(file="a.md", start=5, end=5)
        assert span.start == span.end


class TestRouteEntry:
    def test_construction(self) -> None:
        entry = RouteEntry(
            route_id="R-000001",
            src=SourceSpan(file="spec.md", start=1, end=5),
            library="LIB-01",
            category="DETAIL/ALGORITHM",
            element_id="ALG-LIB01-001",
        )
        assert entry.route_id == "R-000001"
        assert entry.src.file == "spec.md"
        assert entry.library == "LIB-01"
        assert entry.category == "DETAIL/ALGORITHM"
        assert entry.element_id == "ALG-LIB01-001"
        assert entry.notes == ""
        assert entry.ref_stubs == []

    def test_optional_fields(self) -> None:
        entry = RouteEntry(
            route_id="R-000002",
            src=SourceSpan(file="spec.md", start=6, end=10),
            library="LIB-02",
            category="CONSTRAINTS",
            element_id="CON-LIB02-001",
            notes="Survives reimplementation test",
            ref_stubs=["REF-001", "REF-002"],
        )
        assert entry.notes == "Survives reimplementation test"
        assert entry.ref_stubs == ["REF-001", "REF-002"]


class TestLibraryDef:
    def test_construction(self) -> None:
        lib = LibraryDef(
            lib_id="LIB-01",
            name="Transaction Processing",
            description="Handles all transaction lifecycle operations",
        )
        assert lib.lib_id == "LIB-01"
        assert lib.name == "Transaction Processing"
        assert lib.description == "Handles all transaction lifecycle operations"


class TestCoverageLedgerEntry:
    def test_routed_entry(self) -> None:
        entry = CoverageLedgerEntry(
            file="spec.md",
            start=1,
            end=10,
            status="routed",
            route_ids=["R-000001", "R-000002"],
        )
        assert entry.status == "routed"
        assert len(entry.route_ids) == 2
        assert entry.ignore_reason == ""

    def test_ignored_entry(self) -> None:
        entry = CoverageLedgerEntry(
            file="spec.md",
            start=11,
            end=15,
            status="ignored",
            ignore_reason="Blank lines",
        )
        assert entry.status == "ignored"
        assert entry.ignore_reason == "Blank lines"
        assert entry.route_ids == []

    def test_defaults(self) -> None:
        entry = CoverageLedgerEntry(
            file="a.md", start=1, end=1, status="uncovered"
        )
        assert entry.route_ids == []
        assert entry.ignore_reason == ""
