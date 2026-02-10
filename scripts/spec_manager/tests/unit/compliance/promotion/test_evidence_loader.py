"""Tests for evidence_loader module."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.compliance.promotion.evidence_loader import (
    AnalyzedFile,
    load_analyzed_files,
)


class TestAnalyzedFile:
    def test_dataclass_fields(self) -> None:
        from spec_manager.core.code_analysis import SourceAnalysis

        analysis = SourceAnalysis(functions=[], comments=[])
        af = AnalyzedFile(path="/tmp/x.py", analysis=analysis, content="x = 1")
        assert af.path == "/tmp/x.py"
        assert af.content == "x = 1"
        assert af.analysis.functions == []


class TestLoadAnalyzedFiles:
    def test_loads_files_without_cache(self, tmp_path: Path) -> None:
        f = tmp_path / "sample.py"
        f.write_text(
            textwrap.dedent("""\
                def hello():
                    return 1
            """),
            encoding="utf-8",
        )

        results = load_analyzed_files([f])
        assert len(results) == 1
        assert results[0].path == str(f)
        assert "def hello" in results[0].content
        assert len(results[0].analysis.functions) >= 1

    def test_skips_unreadable_files(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.py"
        results = load_analyzed_files([missing])
        assert len(results) == 0

    def test_loads_multiple_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f1.write_text("def a(): return 1\n", encoding="utf-8")
        f2 = tmp_path / "b.py"
        f2.write_text("def b(): return 2\n", encoding="utf-8")

        results = load_analyzed_files([f1, f2])
        assert len(results) == 2
        paths = {r.path for r in results}
        assert str(f1) in paths
        assert str(f2) in paths

    def test_loads_with_cache(self, tmp_path: Path) -> None:
        from spec_manager.orchestration.source_analysis_cache import SourceAnalysisCache

        f = tmp_path / "cached.py"
        f.write_text("def cached(): return 42\n", encoding="utf-8")

        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="test-run")
        results = load_analyzed_files([f], source_cache=cache)

        assert len(results) == 1
        assert cache.stats["misses"] == 1

        # Second call should hit cache
        results2 = load_analyzed_files([f], source_cache=cache)
        assert len(results2) == 1
        assert cache.stats["hits"] == 1

    def test_empty_file_list(self) -> None:
        results = load_analyzed_files([])
        assert results == []
