"""Pre-load files with cached SourceAnalysis for evidence-based gate consumption.

Gates consume ``AnalyzedFile`` objects instead of reading files and calling
``analyze_source()`` independently.  All file I/O happens once here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.core.code_analysis import SourceAnalysis, analyze_source

if TYPE_CHECKING:
    from spec_manager.orchestration.source_analysis_cache import SourceAnalysisCache


@dataclass
class AnalyzedFile:
    """Pre-loaded file with cached SourceAnalysis."""

    path: str
    analysis: SourceAnalysis
    content: str


def load_analyzed_files(
    file_paths: list[Path],
    source_cache: SourceAnalysisCache | None = None,
) -> list[AnalyzedFile]:
    """Load files and their pre-computed analyses.

    When *source_cache* is provided, uses cached analyses.
    Otherwise falls back to ``analyze_source()`` directly.

    Args:
        file_paths: Python files to load.
        source_cache: Optional persistent cache for analysis results.

    Returns:
        List of ``AnalyzedFile`` instances (files that can't be read are
        silently skipped).
    """
    results: list[AnalyzedFile] = []
    for fp in file_paths:
        try:
            content = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if source_cache is not None:
            analysis = source_cache.analyze_with_cache(content, str(fp))
        else:
            analysis = analyze_source(content, str(fp))

        results.append(AnalyzedFile(path=str(fp), analysis=analysis, content=content))
    return results
