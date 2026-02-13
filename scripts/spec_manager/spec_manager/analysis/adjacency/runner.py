"""Orchestrates the full adjacency detection pipeline.

Collects source files and spec files, runs enabled extractors,
builds the unified graph, detects disconnected components,
and produces a report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .detector import (
    AdjacencyReport,
    build_unified_graph,
    detect_disconnected_components,
)
from .graph import AdjacencyGraph, SignalType


@dataclass
class AdjacencyAnalysisConfig:
    """Configuration for adjacency analysis."""

    source_dirs: list[Path]  # Python source directories to analyze
    spec_dirs: list[Path]  # Spec markdown directories
    include_cooccurrence: bool = True
    weight_overrides: dict[str, float] | None = None
    output_format: str = "json"  # "json" or "markdown"
    output_path: Path | None = None


def _collect_python_files(dirs: list[Path]) -> list[Path]:
    """Collect all source files from the given directories."""
    from spec_manager.core.language import is_source_file, source_rglob

    files: list[Path] = []
    for directory in dirs:
        if not directory.exists():
            continue
        if directory.is_file() and is_source_file(directory.suffix):
            files.append(directory)
        elif directory.is_dir():
            files.extend(source_rglob(directory))
    return files


def _collect_spec_files(dirs: list[Path]) -> list[Path]:
    """Collect all .md files from the given directories."""
    files: list[Path] = []
    for directory in dirs:
        if not directory.exists():
            continue
        if directory.is_file() and directory.suffix == ".md":
            files.append(directory)
        elif directory.is_dir():
            files.extend(sorted(directory.rglob("*.md")))
    return files


def run_adjacency_analysis(config: AdjacencyAnalysisConfig) -> AdjacencyReport:
    """Run the full adjacency detection pipeline.

    1. Collect source files from source_dirs
    2. Collect spec files from spec_dirs
    3. Run enabled extractors
    4. Build unified graph
    5. Detect disconnected components
    6. Produce report

    Args:
        config: Analysis configuration

    Returns:
        AdjacencyReport with full analysis
    """
    spec_files = _collect_spec_files(config.spec_dirs)

    cooccurrence_graph: AdjacencyGraph | None = None

    partial_graphs: dict[str, AdjacencyGraph] = {}

    if config.include_cooccurrence and spec_files:
        from .extractors.cooccurrence import extract_cooccurrence_graph

        cooccurrence_graph = extract_cooccurrence_graph(spec_files)
        partial_graphs["cooccurrence"] = cooccurrence_graph

    # Convert weight overrides from string keys to SignalType keys
    weight_overrides: dict[SignalType, float] | None = None
    if config.weight_overrides:
        weight_overrides = {}
        signal_type_map = {st.value: st for st in SignalType}
        for key, value in config.weight_overrides.items():
            if key in signal_type_map:
                weight_overrides[signal_type_map[key]] = value

    # Build unified graph
    unified = build_unified_graph(
        cooccurrence_graph=cooccurrence_graph,
        weight_overrides=weight_overrides,
    )

    # Detect disconnected components
    report = detect_disconnected_components(unified, partial_graphs=partial_graphs)

    return report


def save_report(report: AdjacencyReport, config: AdjacencyAnalysisConfig) -> Path:
    """Save report to configured output path.

    Returns path where report was saved.
    """
    if config.output_path is None:
        output_dir = Path(".")
        if config.output_format == "markdown":
            output_path = output_dir / "adjacency_report.md"
        else:
            output_path = output_dir / "adjacency_report.json"
    else:
        output_path = config.output_path

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if config.output_format == "markdown":
        output_path.write_text(report.to_markdown(), encoding="utf-8")
    else:
        output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    return output_path
