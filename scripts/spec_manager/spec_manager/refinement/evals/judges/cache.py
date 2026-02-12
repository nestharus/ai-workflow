"""Deterministic cache for LLM judge results."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JudgeCacheKey:
    """Composite key that uniquely identifies a cached judge result."""

    judge_type: str
    model_id: str
    prompt_version: str
    input_hash: str


class JudgeCache:
    """File-backed cache for judge outputs, keyed by JudgeCacheKey."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    def get(self, key: JudgeCacheKey) -> dict | None:
        """Return cached dict if it exists, otherwise None."""
        path = self._key_path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt cache entry %s: %s", path, exc)
            return None

    def put(self, key: JudgeCacheKey, data: dict) -> Path:
        """Atomically write *data* to the cache and return the written path."""
        path = self._key_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        _fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=path.stem)
        tmp_path = Path(tmp)
        try:
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        else:
            return path

    def copy_to_run(self, key: JudgeCacheKey, run_dir: Path) -> None:
        """Copy cached result to run-scoped directory for provenance.

        Writes to ``run_dir/judges/{judge_type}/{input_hash}.json``.
        Silently skips if the cached entry does not exist.
        """
        src = self._key_path(key)
        if not src.exists():
            return
        dest = run_dir / "judges" / key.judge_type / f"{key.input_hash}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))

    def _key_path(self, key: JudgeCacheKey) -> Path:
        """Deterministic path: ``{cache_dir}/{judge_type}/{input_hash}.json``."""
        return self.cache_dir / key.judge_type / f"{key.input_hash}.json"

    @classmethod
    def compute_hash(cls, *parts: str) -> str:
        """SHA-256 hex digest of the concatenated *parts*."""
        h = hashlib.sha256()
        for part in parts:
            h.update(part.encode("utf-8"))
        return h.hexdigest()
