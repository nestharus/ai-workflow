"""Persistent SourceAnalysisCache for cross-iteration reuse.

The in-memory cache in ``core.code_analysis`` only survives a single
process invocation.  This module provides a file-based cache that
persists across iterations and runs, keyed by ``(content_hash, analyzer_version)``.

The cache lives in ``.pdd_runs/<run_id>/source_analysis_cache/`` and each
entry is a JSON file named ``<content_hash>.json`` containing the
serialized ``SourceAnalysis``.

Usage::

    cache = SourceAnalysisCache(workspace_root=Path("."), run_id="abc")

    # Check before calling analyze_source
    cached = cache.get(content_hash)
    if cached is None:
        result = analyze_source(content, filepath)
        cache.put(content_hash, result)
    else:
        result = cached
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import (
    SourceAnalysis,
    _dict_to_source_analysis,
)

logger = logging.getLogger(__name__)

ANALYZER_VERSION = "1"


class SourceAnalysisCache:
    """File-based persistent cache for SourceAnalysis results.

    Keys are content hashes (SHA-256 of source text).
    Values are SourceAnalysis objects serialized as JSON.
    """

    def __init__(
        self,
        workspace_root: Path,
        run_id: str = "",
        analyzer_version: str = ANALYZER_VERSION,
    ) -> None:
        if run_id:
            self._cache_dir = workspace_root / ".pdd_runs" / run_id / "source_analysis_cache"
        else:
            self._cache_dir = workspace_root / ".pdd_cache" / "source_analysis"
        self._version = analyzer_version
        self._hits = 0
        self._misses = 0

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses}

    def content_hash(self, content: str) -> str:
        """Compute the content hash for cache lookup."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get(self, content_hash: str) -> SourceAnalysis | None:
        """Look up a cached analysis by content hash.

        Returns None on cache miss.
        """
        path = self._cache_dir / f"{content_hash}.json"
        if not path.exists():
            self._misses += 1
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("_version") != self._version:
                self._misses += 1
                return None

            self._hits += 1
            return _dict_to_source_analysis(data)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.debug("Cache read failed for %s: %s", content_hash, exc)
            self._misses += 1
            return None

    def put(self, content_hash: str, analysis: SourceAnalysis) -> Path:
        """Store an analysis result in the persistent cache.

        Returns:
            Path to the cache file.
        """
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / f"{content_hash}.json"

        data = _source_analysis_to_dict(analysis)
        data["_version"] = self._version
        data["_content_hash"] = content_hash

        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def analyze_with_cache(
        self,
        content: str,
        filepath: str = "",
    ) -> SourceAnalysis:
        """Analyze source with persistent caching.

        Checks persistent cache first, then falls back to
        ``analyze_source()`` (which has its own in-memory cache).

        Args:
            content: Source code.
            filepath: Optional filepath for context.

        Returns:
            SourceAnalysis result (from cache or fresh).
        """
        from spec_manager.core.code_analysis import analyze_source

        ch = self.content_hash(content)
        cached = self.get(ch)
        if cached is not None:
            return cached

        result = analyze_source(content, filepath)
        self.put(ch, result)
        return result

    def preload_from_manifest(
        self,
        manifest_files: list[dict[str, Any]],
        slice_root: Path,
    ) -> int:
        """Preload cache entries from a manifest's file list.

        Reads each file, computes hash, and checks if it's cached.
        Returns the number of cache misses (files that need fresh analysis).

        This lets the ANALYZE step know how much work is needed.
        """
        misses = 0
        for entry in manifest_files:
            file_path = slice_root / entry.get("path", "")
            if not file_path.exists() or not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                ch = self.content_hash(content)
                if self.get(ch) is None:
                    misses += 1
            except (OSError, UnicodeDecodeError):
                misses += 1
        return misses

    def invalidate(self, content_hash: str) -> bool:
        """Remove a specific cache entry.

        Returns True if the entry existed and was removed.
        """
        path = self._cache_dir / f"{content_hash}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def clear(self) -> int:
        """Remove all cache entries.

        Returns the number of entries removed.
        """
        if not self._cache_dir.exists():
            return 0
        count = 0
        for path in self._cache_dir.glob("*.json"):
            path.unlink()
            count += 1
        return count


def _source_analysis_to_dict(analysis: SourceAnalysis) -> dict[str, Any]:
    """Serialize SourceAnalysis to a JSON-compatible dict."""
    functions = []
    for f in analysis.functions:
        functions.append(
            {
                "name": f.name,
                "qualified_name": f.qualified_name,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "is_async": f.is_async,
                "is_stub": f.is_stub,
                "stub_reason": f.stub_reason,
                "has_docstring": f.has_docstring,
                "docstring": f.docstring,
                "decorators": list(f.decorators),
                "args": list(f.args),
                "return_annotation": f.return_annotation,
                "body_start_line": f.body_start_line,
                "body_line_count": f.body_line_count,
            }
        )

    comments = []
    for c in analysis.comments:
        comments.append(
            {
                "line": c.line,
                "col_offset": c.col_offset,
                "text": c.text,
                "raw": c.raw,
                "enclosing_function": c.enclosing_function,
            }
        )

    return {"functions": functions, "comments": comments}
