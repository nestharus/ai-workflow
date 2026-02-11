"""Component tests for orchestration.source_analysis_cache module.

Tests SourceAnalysisCache file-based persistent caching for SourceAnalysis
results, including get/put round-trip, content hashing, invalidation,
clearing, stats tracking, version mismatch handling, and analyze_with_cache().
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from spec_manager.core.code_analysis import (
    RawCommentInfo,
    RawFunctionInfo,
    SourceAnalysis,
)
from spec_manager.orchestration.source_analysis_cache import (
    ANALYZER_VERSION,
    SourceAnalysisCache,
    _source_analysis_to_dict,
)

# ======================================================================
# Helpers
# ======================================================================


def _make_sample_analysis() -> SourceAnalysis:
    """Create a sample SourceAnalysis for testing."""
    return SourceAnalysis(
        functions=[
            RawFunctionInfo(
                name="process",
                qualified_name="Processor.process",
                start_line=10,
                end_line=25,
                is_async=False,
                is_stub=False,
                stub_reason=None,
                has_docstring=True,
                docstring="Process the input data.",
                decorators=("staticmethod",),
                args=("self", "data"),
                return_annotation="dict",
                body_start_line=12,
                body_line_count=14,
            ),
        ],
        comments=[
            RawCommentInfo(
                line=5,
                col_offset=0,
                text="SPEC: Must validate input before processing",
                raw="# SPEC: Must validate input before processing",
                enclosing_function=None,
            ),
        ],
    )


# ======================================================================
# SourceAnalysisCache: cache miss
# ======================================================================


class TestSourceAnalysisCacheGet:
    """Test SourceAnalysisCache.get() behavior."""

    def test_get_returns_none_on_cache_miss(self, tmp_path: Path) -> None:
        """get() returns None when the content hash has no cache entry."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")
        result = cache.get("deadbeef" * 8)
        assert result is None

    def test_get_increments_misses_stat(self, tmp_path: Path) -> None:
        """get() increments the misses counter on cache miss."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")
        cache.get("deadbeef" * 8)
        cache.get("cafebabe" * 8)

        assert cache.stats["misses"] == 2
        assert cache.stats["hits"] == 0


# ======================================================================
# SourceAnalysisCache: put + get round-trip
# ======================================================================


class TestSourceAnalysisCachePutAndGet:
    """Test SourceAnalysisCache.put() + get() round-trip."""

    def test_put_and_get_round_trip(self, tmp_path: Path) -> None:
        """put() followed by get() returns the same SourceAnalysis data."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")
        analysis = _make_sample_analysis()
        content_hash = "a" * 64

        path = cache.put(content_hash, analysis)
        assert path.exists()

        retrieved = cache.get(content_hash)
        assert retrieved is not None
        assert len(retrieved.functions) == 1
        assert retrieved.functions[0].name == "process"
        assert retrieved.functions[0].qualified_name == "Processor.process"
        assert retrieved.functions[0].start_line == 10
        assert retrieved.functions[0].end_line == 25
        assert retrieved.functions[0].is_async is False
        assert retrieved.functions[0].is_stub is False
        assert retrieved.functions[0].has_docstring is True
        assert retrieved.functions[0].docstring == "Process the input data."
        assert retrieved.functions[0].return_annotation == "dict"

        assert len(retrieved.comments) == 1
        assert retrieved.comments[0].line == 5
        assert "SPEC" in retrieved.comments[0].text

    def test_put_creates_cache_directory(self, tmp_path: Path) -> None:
        """put() creates the cache directory if it does not exist."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")
        analysis = SourceAnalysis()

        cache.put("b" * 64, analysis)

        cache_dir = tmp_path / ".pdd_runs" / "r1" / "source_analysis_cache"
        assert cache_dir.exists()

    def test_put_get_increments_stats(self, tmp_path: Path) -> None:
        """put()/get() increments hit and miss stats correctly."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")

        # Miss
        cache.get("c" * 64)
        assert cache.stats == {"hits": 0, "misses": 1}

        # Put then hit
        cache.put("c" * 64, SourceAnalysis())
        cache.get("c" * 64)
        assert cache.stats == {"hits": 1, "misses": 1}


# ======================================================================
# SourceAnalysisCache: content_hash
# ======================================================================


class TestSourceAnalysisCacheContentHash:
    """Test SourceAnalysisCache.content_hash() behavior."""

    def test_content_hash_is_deterministic(self, tmp_path: Path) -> None:
        """content_hash() returns the same hash for the same content."""
        cache = SourceAnalysisCache(workspace_root=tmp_path)
        content = "def foo(): pass\n"

        h1 = cache.content_hash(content)
        h2 = cache.content_hash(content)

        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex length

    def test_content_hash_differs_for_different_content(self, tmp_path: Path) -> None:
        """content_hash() returns different hashes for different content."""
        cache = SourceAnalysisCache(workspace_root=tmp_path)

        h1 = cache.content_hash("def foo(): pass\n")
        h2 = cache.content_hash("def bar(): pass\n")

        assert h1 != h2


# ======================================================================
# SourceAnalysisCache: invalidate
# ======================================================================


class TestSourceAnalysisCacheInvalidate:
    """Test SourceAnalysisCache.invalidate() behavior."""

    def test_invalidate_removes_entry(self, tmp_path: Path) -> None:
        """invalidate() removes a cached entry and returns True."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")
        content_hash = "d" * 64
        cache.put(content_hash, SourceAnalysis())

        removed = cache.invalidate(content_hash)
        assert removed is True

        # Should be a miss now
        assert cache.get(content_hash) is None

    def test_invalidate_returns_false_for_missing(self, tmp_path: Path) -> None:
        """invalidate() returns False when entry does not exist."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")
        removed = cache.invalidate("e" * 64)
        assert removed is False


# ======================================================================
# SourceAnalysisCache: clear
# ======================================================================


class TestSourceAnalysisCacheClear:
    """Test SourceAnalysisCache.clear() behavior."""

    def test_clear_removes_all_entries(self, tmp_path: Path) -> None:
        """clear() removes all entries and returns the count."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")

        cache.put("f" * 64, SourceAnalysis())
        cache.put("0" * 64, SourceAnalysis())
        cache.put("1" * 64, SourceAnalysis())

        count = cache.clear()
        assert count == 3

        # All should be misses now
        assert cache.get("f" * 64) is None
        assert cache.get("0" * 64) is None
        assert cache.get("1" * 64) is None

    def test_clear_returns_zero_when_empty(self, tmp_path: Path) -> None:
        """clear() returns 0 when cache directory does not exist."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")
        count = cache.clear()
        assert count == 0


# ======================================================================
# SourceAnalysisCache: stats
# ======================================================================


class TestSourceAnalysisCacheStats:
    """Test SourceAnalysisCache.stats property."""

    def test_stats_tracks_hits_and_misses(self, tmp_path: Path) -> None:
        """stats property tracks cumulative hits and misses."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")

        # 2 misses
        cache.get("a" * 64)
        cache.get("b" * 64)

        # 1 put + 2 hits
        cache.put("a" * 64, SourceAnalysis())
        cache.get("a" * 64)
        cache.get("a" * 64)

        assert cache.stats["misses"] == 2
        assert cache.stats["hits"] == 2


# ======================================================================
# SourceAnalysisCache: version mismatch
# ======================================================================


class TestSourceAnalysisCacheVersionMismatch:
    """Test SourceAnalysisCache version mismatch handling."""

    def test_version_mismatch_returns_cache_miss(self, tmp_path: Path) -> None:
        """get() returns None when cached entry has different analyzer version."""
        # Write a cache entry with version "v1"
        cache_v1 = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1", analyzer_version="v1")
        content_hash = "g" * 64
        cache_v1.put(content_hash, SourceAnalysis())

        # Read with version "v2"
        cache_v2 = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1", analyzer_version="v2")
        result = cache_v2.get(content_hash)

        assert result is None
        assert cache_v2.stats["misses"] == 1

    def test_same_version_returns_hit(self, tmp_path: Path) -> None:
        """get() returns cached entry when versions match."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1", analyzer_version="v1")
        content_hash = "h" * 64
        cache.put(content_hash, SourceAnalysis())

        result = cache.get(content_hash)
        assert result is not None
        assert cache.stats["hits"] == 1


# ======================================================================
# SourceAnalysisCache: analyze_with_cache
# ======================================================================


class TestSourceAnalysisCacheAnalyzeWithCache:
    """Test SourceAnalysisCache.analyze_with_cache() behavior."""

    def test_calls_analyze_source_on_miss(self, tmp_path: Path) -> None:
        """analyze_with_cache() calls analyze_source when cache misses."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")
        content = "def hello(): pass\n"

        # The autouse fixture in root conftest injects _local_python_analyzer
        # so analyze_source will use AST-based analysis (no LLM calls)
        result = cache.analyze_with_cache(content, "hello.py")

        assert result is not None
        assert len(result.functions) == 1
        assert result.functions[0].name == "hello"

        # Should have been cached
        ch = cache.content_hash(content)
        cached_result = cache.get(ch)
        assert cached_result is not None
        assert cached_result.functions[0].name == "hello"

    def test_returns_cached_on_hit(self, tmp_path: Path) -> None:
        """analyze_with_cache() returns cached result on cache hit."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="r1")
        content = "def world(): pass\n"

        # First call: populates cache
        cache.analyze_with_cache(content, "world.py")

        # Second call: should hit cache
        result2 = cache.analyze_with_cache(content, "world.py")

        assert result2 is not None
        assert result2.functions[0].name == "world"
        # One miss (first call) and one hit (second call)
        assert cache.stats["misses"] == 1
        assert cache.stats["hits"] == 1


# ======================================================================
# _source_analysis_to_dict
# ======================================================================


class TestSourceAnalysisToDict:
    """Test _source_analysis_to_dict() serialization."""

    def test_serializes_all_fields(self) -> None:
        """_source_analysis_to_dict() includes all function and comment fields."""
        analysis = _make_sample_analysis()
        d = _source_analysis_to_dict(analysis)

        assert len(d["functions"]) == 1
        f = d["functions"][0]
        assert f["name"] == "process"
        assert f["qualified_name"] == "Processor.process"
        assert f["start_line"] == 10
        assert f["end_line"] == 25
        assert f["is_async"] is False
        assert f["is_stub"] is False
        assert f["has_docstring"] is True
        assert f["docstring"] == "Process the input data."
        assert f["decorators"] == ["staticmethod"]
        assert f["args"] == ["self", "data"]
        assert f["return_annotation"] == "dict"

        assert len(d["comments"]) == 1
        c = d["comments"][0]
        assert c["line"] == 5
        assert c["col_offset"] == 0
        assert "SPEC" in c["text"]

    def test_empty_analysis(self) -> None:
        """_source_analysis_to_dict() handles empty SourceAnalysis."""
        d = _source_analysis_to_dict(SourceAnalysis())
        assert d["functions"] == []
        assert d["comments"] == []


# ======================================================================
# Cache directory paths
# ======================================================================


class TestSourceAnalysisCacheDirectory:
    """Test cache directory path construction."""

    def test_with_run_id(self, tmp_path: Path) -> None:
        """Cache with run_id uses .pdd_runs/<run_id>/source_analysis_cache/."""
        cache = SourceAnalysisCache(workspace_root=tmp_path, run_id="run-42")
        expected = tmp_path / ".pdd_runs" / "run-42" / "source_analysis_cache"
        assert cache.cache_dir == expected

    def test_without_run_id(self, tmp_path: Path) -> None:
        """Cache without run_id uses .pdd_cache/source_analysis/."""
        cache = SourceAnalysisCache(workspace_root=tmp_path)
        expected = tmp_path / ".pdd_cache" / "source_analysis"
        assert cache.cache_dir == expected
