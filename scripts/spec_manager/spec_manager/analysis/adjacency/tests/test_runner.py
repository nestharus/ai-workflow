"""Tests for the adjacency analysis runner."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from spec_manager.analysis.adjacency.runner import (
    AdjacencyAnalysisConfig,
    run_adjacency_analysis,
    save_report,
)


def _write_file(directory: Path, filename: str, content: str) -> Path:
    """Write a file and return its path."""
    path = directory / filename
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    """Create a fixture directory with known source and spec files."""
    src_dir = tmp_path / "src"
    spec_dir = tmp_path / "specs"
    src_dir.mkdir()
    spec_dir.mkdir()

    # Source files with known call relationships
    _write_file(
        src_dir,
        "processor.py",
        """\
        def validate(data):
            return len(data) > 0

        def process(data):
            if validate(data):
                return transform(data)
            return None

        def transform(data):
            return data.upper()

        def read_orders():
            pass

        def write_orders(orders):
            pass
        """,
    )

    _write_file(
        src_dir,
        "events.py",
        """\
        class EventService:
            def publish_event(self):
                self.emit("order.created")

            def handle_event(self):
                self.subscribe("order.created", self.on_order)

            def on_order(self, event):
                pass
        """,
    )

    # Spec files with entity declarations
    _write_file(
        spec_dir,
        "algorithms.md",
        """\
        ## Sort Algorithm ([=Algorithm 1])

        Sorting implementation. See also (@[+Algorithm 2]).

        ## Search Algorithm ([=Algorithm 2])

        Binary search implementation.
        """,
    )

    return tmp_path


class TestRunAdjacencyAnalysis:
    def test_end_to_end(self, fixture_dir: Path) -> None:
        config = AdjacencyAnalysisConfig(
            source_dirs=[fixture_dir / "src"],
            spec_dirs=[fixture_dir / "specs"],
        )

        report = run_adjacency_analysis(config)

        assert report.total_nodes > 0
        assert report.total_edges >= 0
        assert report.num_components >= 1

    def test_disabled_extractors(self, fixture_dir: Path) -> None:
        config = AdjacencyAnalysisConfig(
            source_dirs=[fixture_dir / "src"],
            spec_dirs=[fixture_dir / "specs"],
            include_call_graph=False,
            include_event_graph=False,
            include_store_graph=False,
            include_cooccurrence=True,
        )

        report = run_adjacency_analysis(config)

        # Only co-occurrence should produce results
        assert report.total_nodes >= 0
        # Call edges should not be present
        assert report.signal_type_counts.get("call", 0) == 0

    def test_all_extractors_disabled(self, fixture_dir: Path) -> None:
        config = AdjacencyAnalysisConfig(
            source_dirs=[fixture_dir / "src"],
            spec_dirs=[fixture_dir / "specs"],
            include_call_graph=False,
            include_event_graph=False,
            include_store_graph=False,
            include_cooccurrence=False,
        )

        report = run_adjacency_analysis(config)
        assert report.total_nodes == 0
        assert report.total_edges == 0

    def test_empty_directories(self, tmp_path: Path) -> None:
        empty_src = tmp_path / "empty_src"
        empty_spec = tmp_path / "empty_spec"
        empty_src.mkdir()
        empty_spec.mkdir()

        config = AdjacencyAnalysisConfig(
            source_dirs=[empty_src],
            spec_dirs=[empty_spec],
        )

        report = run_adjacency_analysis(config)
        assert report.total_nodes == 0

    def test_nonexistent_directories(self, tmp_path: Path) -> None:
        config = AdjacencyAnalysisConfig(
            source_dirs=[tmp_path / "nonexistent_src"],
            spec_dirs=[tmp_path / "nonexistent_spec"],
        )

        report = run_adjacency_analysis(config)
        assert report.total_nodes == 0

    def test_weight_overrides(self, fixture_dir: Path) -> None:
        config = AdjacencyAnalysisConfig(
            source_dirs=[fixture_dir / "src"],
            spec_dirs=[fixture_dir / "specs"],
            weight_overrides={"call": 2.0, "co_occurrence": 0.1},
        )

        report = run_adjacency_analysis(config)
        # Report should complete without error
        assert report.total_nodes >= 0


class TestSaveReport:
    def test_json_output(self, fixture_dir: Path, tmp_path: Path) -> None:
        config = AdjacencyAnalysisConfig(
            source_dirs=[fixture_dir / "src"],
            spec_dirs=[fixture_dir / "specs"],
            output_format="json",
            output_path=tmp_path / "output" / "report.json",
        )

        report = run_adjacency_analysis(config)
        output_path = save_report(report, config)

        assert output_path.exists()
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert "total_nodes" in data
        assert "components" in data

    def test_markdown_output(self, fixture_dir: Path, tmp_path: Path) -> None:
        config = AdjacencyAnalysisConfig(
            source_dirs=[fixture_dir / "src"],
            spec_dirs=[fixture_dir / "specs"],
            output_format="markdown",
            output_path=tmp_path / "output" / "report.md",
        )

        report = run_adjacency_analysis(config)
        output_path = save_report(report, config)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "# Adjacency Analysis Report" in content

    def test_default_output_path(self, fixture_dir: Path, tmp_path: Path) -> None:
        config = AdjacencyAnalysisConfig(
            source_dirs=[fixture_dir / "src"],
            spec_dirs=[fixture_dir / "specs"],
            output_format="json",
            output_path=None,
        )

        report = run_adjacency_analysis(config)
        # save_report should default to current directory
        output_path = save_report(report, config)
        assert output_path.name == "adjacency_report.json"
