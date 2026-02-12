"""Tests for JudgeCache."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

from spec_manager.refinement.evals.judges.cache import JudgeCache, JudgeCacheKey


def _sample_key(suffix: str = "abc") -> JudgeCacheKey:
    return JudgeCacheKey(
        judge_type="completeness",
        model_id="opus",
        prompt_version="v1",
        input_hash=suffix,
    )


class TestJudgeCacheGetPut:
    """Basic get/put round-trip."""

    def test_get_empty_returns_none(self, tmp_path: Path) -> None:
        cache = JudgeCache(tmp_path)
        assert cache.get(_sample_key()) is None

    def test_put_then_get(self, tmp_path: Path) -> None:
        cache = JudgeCache(tmp_path)
        key = _sample_key()
        data = {"score": 0.95, "details": ["ok"]}
        cache.put(key, data)
        assert cache.get(key) == data

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        cache = JudgeCache(tmp_path)
        key = _sample_key()
        cache.put(key, {"v": 1})
        cache.put(key, {"v": 2})
        assert cache.get(key) == {"v": 2}


class TestJudgeCacheKeyPath:
    """Deterministic path generation."""

    def test_same_key_same_path(self, tmp_path: Path) -> None:
        cache = JudgeCache(tmp_path)
        key = _sample_key()
        assert cache._key_path(key) == cache._key_path(key)

    def test_path_structure(self, tmp_path: Path) -> None:
        cache = JudgeCache(tmp_path)
        key = _sample_key("deadbeef")
        path = cache._key_path(key)
        assert path == tmp_path / "completeness" / "deadbeef.json"


class TestJudgeCacheHash:
    """compute_hash stability."""

    def test_stable_across_calls(self) -> None:
        h1 = JudgeCache.compute_hash("a", "b")
        h2 = JudgeCache.compute_hash("a", "b")
        assert h1 == h2

    def test_different_inputs_different_hash(self) -> None:
        assert JudgeCache.compute_hash("a") != JudgeCache.compute_hash("b")

    def test_order_matters(self) -> None:
        assert JudgeCache.compute_hash("a", "b") != JudgeCache.compute_hash("b", "a")


class TestJudgeCacheConcurrency:
    """Concurrent writes must not corrupt data."""

    def test_concurrent_writes(self, tmp_path: Path) -> None:
        cache = JudgeCache(tmp_path)
        key = _sample_key("concurrent")

        def _write(value: int) -> int:
            cache.put(key, {"v": value})
            return value

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_write, i) for i in range(2)]
            concurrent.futures.wait(futures)
            for f in futures:
                f.result()  # propagate exceptions

        result = cache.get(key)
        assert result is not None
        assert "v" in result
        assert result["v"] in {0, 1}


class TestJudgeCacheCopyToRun:
    """Tests for copy_to_run provenance feature (Section 5.4)."""

    def test_copy_existing_entry(self, tmp_path: Path) -> None:
        """Existing cache entry is copied to run directory."""
        cache_dir = tmp_path / "cache"
        run_dir = tmp_path / "run"
        cache = JudgeCache(cache_dir)
        key = _sample_key("copy01")
        data = {"score": 0.9, "detail": "good"}
        cache.put(key, data)

        cache.copy_to_run(key, run_dir)

        dest = run_dir / "judges" / key.judge_type / f"{key.input_hash}.json"
        assert dest.exists()
        copied = json.loads(dest.read_text(encoding="utf-8"))
        assert copied == data

    def test_copy_missing_entry_silently_skips(self, tmp_path: Path) -> None:
        """Missing cache entry does not raise, no file created."""
        cache_dir = tmp_path / "cache"
        run_dir = tmp_path / "run"
        cache = JudgeCache(cache_dir)
        key = _sample_key("nonexistent")

        # Should not raise
        cache.copy_to_run(key, run_dir)

        dest = run_dir / "judges" / key.judge_type / f"{key.input_hash}.json"
        assert not dest.exists()

    def test_copy_creates_nested_directories(self, tmp_path: Path) -> None:
        """copy_to_run creates judge type subdirectory if it does not exist."""
        cache_dir = tmp_path / "cache"
        run_dir = tmp_path / "deep" / "nested" / "run"
        cache = JudgeCache(cache_dir)
        key = _sample_key("nested")
        cache.put(key, {"v": 1})

        cache.copy_to_run(key, run_dir)

        dest = run_dir / "judges" / key.judge_type / f"{key.input_hash}.json"
        assert dest.exists()

    def test_copy_preserves_content_integrity(self, tmp_path: Path) -> None:
        """Copied file has identical content to cached file."""
        cache_dir = tmp_path / "cache"
        run_dir = tmp_path / "run"
        cache = JudgeCache(cache_dir)
        key = _sample_key("integrity")
        data = {"nested": {"list": [1, 2, 3]}, "string": "hello"}
        cache.put(key, data)

        cache.copy_to_run(key, run_dir)

        src_path = cache._key_path(key)
        dest_path = run_dir / "judges" / key.judge_type / f"{key.input_hash}.json"
        assert src_path.read_text() == dest_path.read_text()

    def test_copy_different_judge_types(self, tmp_path: Path) -> None:
        """Copies for different judge types go to separate subdirs."""
        cache_dir = tmp_path / "cache"
        run_dir = tmp_path / "run"
        cache = JudgeCache(cache_dir)

        key_arch = JudgeCacheKey(
            judge_type="arch_quality",
            model_id="opus",
            prompt_version="v1",
            input_hash="aaa",
        )
        key_code = JudgeCacheKey(
            judge_type="code_quality",
            model_id="opus",
            prompt_version="v1",
            input_hash="bbb",
        )
        cache.put(key_arch, {"type": "arch"})
        cache.put(key_code, {"type": "code"})

        cache.copy_to_run(key_arch, run_dir)
        cache.copy_to_run(key_code, run_dir)

        assert (run_dir / "judges" / "arch_quality" / "aaa.json").exists()
        assert (run_dir / "judges" / "code_quality" / "bbb.json").exists()
