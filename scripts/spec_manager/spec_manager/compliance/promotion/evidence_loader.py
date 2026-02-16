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


@dataclass(frozen=True)
class EvidenceLoadFailure:
    """One unreadable file encountered during evidence loading."""

    path: str
    reason: str


class AnalyzedFileLoadResult(list[AnalyzedFile]):
    """Loaded analyzed files plus explicit read/decode failures."""

    def __init__(
        self,
        files: list[AnalyzedFile] | None = None,
        *,
        load_failures: list[EvidenceLoadFailure] | None = None,
    ) -> None:
        super().__init__(files or [])
        self.load_failures = load_failures or []


def load_analyzed_files(
    file_paths: list[Path],
    source_cache: SourceAnalysisCache | None = None,
) -> AnalyzedFileLoadResult:
    """Load files and their pre-computed analyses.

    When *source_cache* is provided, uses cached analyses.
    Otherwise falls back to ``analyze_source()`` directly.

    Args:
        file_paths: Python files to load.
        source_cache: Optional persistent cache for analysis results.

    Returns:
        ``AnalyzedFileLoadResult`` containing successfully loaded files and
        explicit unreadable-file failures.
    """
    results: list[AnalyzedFile] = []
    load_failures: list[EvidenceLoadFailure] = []
    for fp in file_paths:
        try:
            content = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            load_failures.append(
                EvidenceLoadFailure(
                    path=str(fp),
                    reason=f"read_error:{type(exc).__name__}",
                )
            )
            continue

        if source_cache is not None:
            analysis = source_cache.analyze_with_cache(content, str(fp))
        else:
            analysis = analyze_source(content, str(fp))

        results.append(AnalyzedFile(path=str(fp), analysis=analysis, content=content))
    return AnalyzedFileLoadResult(files=results, load_failures=load_failures)
