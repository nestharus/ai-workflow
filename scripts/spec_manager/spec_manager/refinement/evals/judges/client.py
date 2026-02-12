"""JudgeClient — thin wrapper that calls an LLM agent and validates the response."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from spec_manager.core.agent_utils import run_agent
from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.refinement.formats import _strip_code_fences

if TYPE_CHECKING:
    from spec_manager.refinement.evals.judges.cache import JudgeCache, JudgeCacheKey

logger = logging.getLogger(__name__)


class JudgeClient:
    """Execute an LLM judge agent and return a validated Pydantic model."""

    def __init__(
        self,
        agent_name: str,
        workspace: Path,
        schema_cls: type[BaseModel],
        max_retries: int = 2,
        model_id: str = "",
        producer_model_id: str = "",
        allow_self_judge: bool = False,
    ) -> None:
        self.agent_name = agent_name
        self.workspace = workspace
        self.schema_cls = schema_cls
        self.max_retries = max_retries
        self._model_id = model_id
        self._producer_model_id = producer_model_id
        self._allow_self_judge = allow_self_judge

    def judge(
        self,
        prompt: str,
        cache: JudgeCache | None = None,
        cache_key: JudgeCacheKey | None = None,
        run_dir: Path | None = None,
    ) -> BaseModel:
        """Call the judge agent, validate the output, and return the model.

        If *cache* and *cache_key* are provided the cache is checked first and
        successful results are written back.

        If *run_dir* is provided, the cached result is also copied to
        ``run_dir/judges/{judge_type}/{hash}.json`` for provenance.
        """
        # Enforce judge != producer (Research Prompt 3, Section 5.2)
        if (
            self._producer_model_id
            and self._model_id
            and self._producer_model_id == self._model_id
            and not self._allow_self_judge
        ):
            raise ValueError(
                f"Judge model '{self._model_id}' is the same as producer model. "
                f"Use allow_self_judge=True to override."
            )

        if cache is not None and cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit for %s", cache_key)
                if run_dir is not None:
                    cache.copy_to_run(cache_key, run_dir)
                return self.schema_cls.model_validate(cached)

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                output = run_agent(
                    agent_name=self.agent_name,
                    prompt=prompt,
                    workspace=self.workspace,
                    model_id=self._model_id,
                )
                cleaned = _strip_code_fences(output)
                extracted = _extract_json_payload(cleaned)
                result = self.schema_cls.model_validate(json.loads(extracted))

                if cache is not None and cache_key is not None:
                    cache.put(cache_key, result.model_dump())
                    if run_dir is not None:
                        cache.copy_to_run(cache_key, run_dir)

                return result
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Judge attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                if attempt + 1 < self.max_retries:
                    time.sleep(2**attempt)

        raise RuntimeError(
            f"Judge {self.agent_name} failed after {self.max_retries} attempts"
        ) from last_error
