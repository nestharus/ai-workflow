"""Tests for intake coverage check (deterministic, no LLM calls).

Tests that trigger uncovered lines mock the LLM classification to avoid
requiring API access.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from spec_manager.intake.coverage import check_coverage
from spec_manager.intake.types import RouteEntry, SourceSpan


def _write_md(directory: Path, name: str, content: str) -> None:
    path = directory / name
    path.write_text(content, encoding="utf-8")


def _mock_classify_all_uncovered(entries, file_lines, output_dir):
    """Mock that returns all entries as uncovered (no LLM call)."""
    from spec_manager.intake.types import CoverageLedgerEntry

    return [
        CoverageLedgerEntry(
            file=e.file, start=e.start, end=e.end, status="uncovered",
        )
        for e in entries
    ]


def _mock_classify_all_ignored(entries, file_lines, output_dir):
    """Mock that returns all entries as ignored (no LLM call)."""
    from spec_manager.intake.types import CoverageLedgerEntry

    return [
        CoverageLedgerEntry(
            file=e.file, start=e.start, end=e.end,
            status="ignored", ignore_reason="test noise",
        )
        for e in entries
    ]


class TestCheckCoverage:
    def test_full_coverage(self, tmp_path: Path) -> None:
        """All lines covered → all ledger entries are 'routed'."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "line1\nline2\nline3\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=3),
                library="LIB-01",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB01-001",
            ),
        ]

        ledger = check_coverage(source_dir, routes, output_dir)
        assert all(e.status == "routed" for e in ledger)
        assert (output_dir / "coverage_ledger.jsonl").exists()

    @patch("spec_manager.intake.coverage._classify_uncovered", _mock_classify_all_uncovered)
    def test_partial_coverage(self, tmp_path: Path) -> None:
        """Only some lines covered → ledger has both routed and uncovered."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "line1\nline2\nline3\nline4\nline5\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=2),
                library="LIB-01",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB01-001",
            ),
        ]

        ledger = check_coverage(source_dir, routes, output_dir)

        statuses = {e.status for e in ledger}
        assert "routed" in statuses
        assert "uncovered" in statuses

    @patch("spec_manager.intake.coverage._classify_uncovered", _mock_classify_all_uncovered)
    def test_no_routes(self, tmp_path: Path) -> None:
        """No routes at all → everything is uncovered."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "line1\nline2\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        ledger = check_coverage(source_dir, [], output_dir)

        assert all(e.status == "uncovered" for e in ledger)

    def test_no_source_files(self, tmp_path: Path) -> None:
        """No source files → empty ledger."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        ledger = check_coverage(source_dir, [], output_dir)
        assert ledger == []

    def test_empty_file_skipped(self, tmp_path: Path) -> None:
        """Empty source file → no ledger entries for it."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "empty.md", "")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        ledger = check_coverage(source_dir, [], output_dir)
        assert ledger == []

    def test_multiple_routes_same_lines(self, tmp_path: Path) -> None:
        """Overlapping routes → route_ids accumulate."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "line1\nline2\nline3\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=2),
                library="LIB-01",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB01-001",
            ),
            RouteEntry(
                route_id="R-000002",
                src=SourceSpan(file="spec.md", start=2, end=3),
                library="LIB-02",
                category="ANALYSIS",
                element_id="ANL-LIB02-001",
            ),
        ]

        ledger = check_coverage(source_dir, routes, output_dir)
        # All lines should be routed
        assert all(e.status == "routed" for e in ledger)

    def test_writes_jsonl(self, tmp_path: Path) -> None:
        """Coverage ledger written as JSONL."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "line1\nline2\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=2),
                library="LIB-01",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB01-001",
            ),
        ]

        check_coverage(source_dir, routes, output_dir)

        import json

        ledger_file = output_dir / "coverage_ledger.jsonl"
        assert ledger_file.exists()
        lines = ledger_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        for line in lines:
            record = json.loads(line)
            assert "file" in record
            assert "start" in record
            assert "status" in record

    @patch("spec_manager.intake.coverage._classify_uncovered", _mock_classify_all_ignored)
    def test_ignored_lines_counted_as_covered(self, tmp_path: Path) -> None:
        """Lines classified as ignored count toward coverage percentage."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "line1\nline2\nline3\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        # Only route line 1, lines 2-3 uncovered → LLM marks as ignored
        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=1),
                library="LIB-01",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB01-001",
            ),
        ]

        ledger = check_coverage(source_dir, routes, output_dir)

        statuses = {e.status for e in ledger}
        assert "routed" in statuses
        assert "ignored" in statuses
        assert "uncovered" not in statuses
