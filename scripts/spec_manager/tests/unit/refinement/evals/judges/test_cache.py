"""Tests for JudgeCache."""

from __future__ import annotations

import concurrent.futures
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
