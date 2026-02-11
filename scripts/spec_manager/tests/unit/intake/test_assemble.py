"""Tests for intake assembly (deterministic, no LLM calls)."""

from __future__ import annotations

from pathlib import Path

from spec_manager.intake.assemble import assemble_output
from spec_manager.intake.types import LibraryDef, RouteEntry, SourceSpan


def _write_md(directory: Path, name: str, content: str) -> None:
    path = directory / name
    path.write_text(content, encoding="utf-8")


class TestAssembleOutput:
    def test_single_route_single_library(self, tmp_path: Path) -> None:
        """One route creates one output file in the library dir."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "line1\nline2\nline3\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        libraries = [
            LibraryDef(lib_id="LIB-01", name="MyLib", description="Test library"),
        ]
        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=3),
                library="LIB-01",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB01-001",
            ),
        ]

        libraries_dir = assemble_output(source_dir, routes, libraries, output_dir)

        assert libraries_dir.exists()
        algorithms = libraries_dir / "LIB-01" / "details" / "algorithms.md"
        assert algorithms.exists()
        content = algorithms.read_text(encoding="utf-8")
        assert "line1" in content
        assert "line2" in content
        assert "line3" in content

    def test_verbatim_copy(self, tmp_path: Path) -> None:
        """Assembled output is verbatim from source (no rewriting)."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        original = (
            "The system MUST process all orders within 24 hours.\nNo silent termination is allowed."
        )
        _write_md(source_dir, "spec.md", original)

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        libraries = [
            LibraryDef(lib_id="LIB-01", name="Orders", description="Order processing"),
        ]
        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=2),
                library="LIB-01",
                category="CONSTRAINTS",
                element_id="CON-LIB01-001",
            ),
        ]

        libraries_dir = assemble_output(source_dir, routes, libraries, output_dir)

        constraints = libraries_dir / "LIB-01" / "constraints.md"
        content = constraints.read_text(encoding="utf-8")
        # Each line from source must appear verbatim
        assert "The system MUST process all orders within 24 hours." in content
        assert "No silent termination is allowed." in content

    def test_multiple_categories(self, tmp_path: Path) -> None:
        """Routes to different categories create different output files."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(
            source_dir,
            "spec.md",
            "algorithm line\nconstraint line\nanalysis line\n",
        )

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        libraries = [
            LibraryDef(lib_id="LIB-01", name="Test", description="Test lib"),
        ]
        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=1),
                library="LIB-01",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB01-001",
            ),
            RouteEntry(
                route_id="R-000002",
                src=SourceSpan(file="spec.md", start=2, end=2),
                library="LIB-01",
                category="CONSTRAINTS",
                element_id="CON-LIB01-001",
            ),
            RouteEntry(
                route_id="R-000003",
                src=SourceSpan(file="spec.md", start=3, end=3),
                library="LIB-01",
                category="ANALYSIS",
                element_id="ANL-LIB01-001",
            ),
        ]

        libraries_dir = assemble_output(source_dir, routes, libraries, output_dir)

        assert (libraries_dir / "LIB-01" / "details" / "algorithms.md").exists()
        assert (libraries_dir / "LIB-01" / "constraints.md").exists()
        assert (libraries_dir / "LIB-01" / "analysis.md").exists()

    def test_multiple_libraries(self, tmp_path: Path) -> None:
        """Routes to different libraries create separate directories."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "lib1 content\nlib2 content\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        libraries = [
            LibraryDef(lib_id="LIB-01", name="First", description="First lib"),
            LibraryDef(lib_id="LIB-02", name="Second", description="Second lib"),
        ]
        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=1),
                library="LIB-01",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB01-001",
            ),
            RouteEntry(
                route_id="R-000002",
                src=SourceSpan(file="spec.md", start=2, end=2),
                library="LIB-02",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB02-001",
            ),
        ]

        libraries_dir = assemble_output(source_dir, routes, libraries, output_dir)

        assert (libraries_dir / "LIB-01" / "details" / "algorithms.md").exists()
        assert (libraries_dir / "LIB-02" / "details" / "algorithms.md").exists()

    def test_no_routes(self, tmp_path: Path) -> None:
        """No routes → empty libraries dir, no crash."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        libraries_dir = assemble_output(source_dir, [], [], output_dir)
        assert libraries_dir.exists()
        assert list(libraries_dir.iterdir()) == []

    def test_element_annotation_in_output(self, tmp_path: Path) -> None:
        """Each route entry's element_id is annotated in the output."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "content here\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        libraries = [
            LibraryDef(lib_id="LIB-01", name="Test", description="Test"),
        ]
        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=1),
                library="LIB-01",
                category="DETAIL/ALGORITHM",
                element_id="ALG-LIB01-001",
            ),
        ]

        libraries_dir = assemble_output(source_dir, routes, libraries, output_dir)

        algorithms = libraries_dir / "LIB-01" / "details" / "algorithms.md"
        content = algorithms.read_text(encoding="utf-8")
        assert "[=ALG-LIB01-001]" in content
        assert "spec.md:1-1" in content

    def test_source_comment_included(self, tmp_path: Path) -> None:
        """Source location comment is present in output."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        _write_md(source_dir, "spec.md", "content\n")

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        libraries = [
            LibraryDef(lib_id="LIB-01", name="Test", description="Test"),
        ]
        routes = [
            RouteEntry(
                route_id="R-000001",
                src=SourceSpan(file="spec.md", start=1, end=1),
                library="LIB-01",
                category="ANALYSIS",
                element_id="ANL-LIB01-001",
            ),
        ]

        libraries_dir = assemble_output(source_dir, routes, libraries, output_dir)

        analysis = libraries_dir / "LIB-01" / "analysis.md"
        content = analysis.read_text(encoding="utf-8")
        assert "<!-- source: spec.md:1-1 -->" in content
