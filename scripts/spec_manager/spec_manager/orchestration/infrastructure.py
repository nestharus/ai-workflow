"""Unified infrastructure access for PDD phases.

Exposes refinement infrastructure (signal resolution, LLM output parsing,
ambiguity detection, evidence search) through a single interface that
PDD phase runners can consume without coupling directly to the refinement
package internals.

All heavyweight imports are deferred to method bodies to avoid circular
import issues between ``orchestration`` and ``refinement``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spec_manager.core.evidence_index import EvidenceIndex
    from spec_manager.refinement.hollowed_spec.searcher import (
        EvidenceSearcher,
        SearchResult,
    )
    from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
    from spec_manager.refinement.interactive.signal_resolver import SignalResolver
    from spec_manager.refinement.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


class PddInfrastructure:
    """Unified access to refinement infrastructure for PDD phases.

    Provides lazy-initialized helpers that the orchestrator and individual
    phase runners can call without importing refinement internals directly.

    Usage::

        infra = PddInfrastructure(manager)
        data = infra.parse_llm_json(raw_output)
        ambiguities = infra.detect_ambiguity(spec_text)
        results = infra.search_evidence("treasury validation")
    """

    def __init__(self, manager: WorkspaceManager) -> None:
        self.manager = manager
        self._signal_resolver: SignalResolver | None = None
        self._evidence_index: EvidenceIndex | None = None
        self._evidence_searcher: EvidenceSearcher | None = None

    # ------------------------------------------------------------------
    # Signal resolution
    # ------------------------------------------------------------------

    @property
    def signal_resolver(self) -> SignalResolver:
        """Lazy-init signal resolver for conflict resolution between phases.

        Defaults to ``AutoSignalResolver`` (non-interactive).  Callers that
        need a different mode should set ``_signal_resolver`` directly or
        use :meth:`set_signal_resolver`.
        """
        if self._signal_resolver is None:
            from spec_manager.refinement.interactive.signal_resolver import (
                AutoSignalResolver,
            )

            self._signal_resolver = AutoSignalResolver(
                workspace=self.manager.workspace_path,
            )
        return self._signal_resolver

    def set_signal_resolver(self, resolver: SignalResolver) -> None:
        """Replace the signal resolver (e.g. for interactive or eval mode)."""
        self._signal_resolver = resolver

    def create_signal_resolver(
        self,
        mode: str = "auto",
        *,
        steering_path: Path | None = None,
        use_research: bool = False,
        use_evidence_store: bool = False,
        timeout_seconds: int = 300,
    ) -> SignalResolver:
        """Create and set a signal resolver via the factory.

        Args:
            mode: One of ``"auto"``, ``"interactive"``, ``"file"``,
                ``"steering-only"``.
            steering_path: Path to steering script JSON.
            use_research: Enable web-research fallback.
            use_evidence_store: Enable evidence-store search.
            timeout_seconds: Timeout for file-based polling.

        Returns:
            The newly created resolver (also stored on ``self``).
        """
        from spec_manager.refinement.interactive.signal_resolver import (
            create_resolver,
        )

        resolver = create_resolver(
            mode=mode,
            workspace=self.manager.workspace_path,
            steering_path=steering_path,
            use_research=use_research,
            use_evidence_store=use_evidence_store,
            timeout_seconds=timeout_seconds,
        )
        self._signal_resolver = resolver
        return resolver

    # ------------------------------------------------------------------
    # LLM output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_llm_json(raw_output: str) -> dict[str, Any] | list[Any]:
        """Parse LLM output: strip code fences, fix single quotes, extract JSON.

        Applies the three-step pipeline documented in MEMORY.md:
        1. ``_strip_code_fences``  -- remove markdown fences
        2. ``_fix_single_quote_json``  -- normalise Python-style dicts
        3. ``_extract_json_payload`` + ``json.loads`` -- robust extraction

        Args:
            raw_output: Raw string from an LLM call.

        Returns:
            Parsed JSON (dict or list).

        Raises:
            ValueError: If no valid JSON could be extracted.
        """
        from spec_manager.core.json_extraction import _extract_json_payload
        from spec_manager.refinement.formats import (
            _fix_single_quote_json,
            _strip_code_fences,
        )

        if not raw_output or not raw_output.strip():
            raise ValueError("Empty LLM output")

        # Step 1: strip code fences
        cleaned = _strip_code_fences(raw_output)

        # Step 2: fix single-quote JSON
        cleaned = _fix_single_quote_json(cleaned)

        # Step 3: try direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Step 4: robust extraction fallback
        extracted = _extract_json_payload(cleaned)
        try:
            return json.loads(extracted)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to extract valid JSON from LLM output: {exc}") from exc

    @staticmethod
    def extract_json(
        raw_output: str,
        *,
        allow_array: bool = True,
        allow_object: bool = True,
        evidence: list[dict[str, Any]] | None = None,
        location: str = "pdd_infrastructure",
    ) -> dict[str, Any] | list[Any]:
        """Full-featured JSON extraction with type constraints and evidence.

        Delegates to ``formats.extract_json_from_llm_output`` for callers
        that need finer control than :meth:`parse_llm_json`.
        """
        from spec_manager.refinement.formats import extract_json_from_llm_output

        return extract_json_from_llm_output(
            raw_output,
            allow_array=allow_array,
            allow_object=allow_object,
            evidence=evidence,
            location=location,
        )

    # ------------------------------------------------------------------
    # Ambiguity detection
    # ------------------------------------------------------------------

    def detect_ambiguity(self, content: str) -> list[Ambiguity]:
        """Detect ambiguities in content using the interactive-mode detector.

        Args:
            content: Specification text to analyse.

        Returns:
            List of detected ``Ambiguity`` objects (may be empty on failure).
        """
        from spec_manager.refinement.interactive.ambiguity_detector import (
            AmbiguityDetector,
        )

        detector = AmbiguityDetector()
        return detector.detect(
            spec_text=content,
            workspace=self.manager.workspace_path,
        )

    # ------------------------------------------------------------------
    # Evidence store search
    # ------------------------------------------------------------------

    @property
    def evidence_index(self) -> EvidenceIndex:
        """Lazy-load or build the evidence index for the workspace."""
        if self._evidence_index is None:
            from spec_manager.core.evidence_index import EvidenceIndex, build_evidence_index

            index_path = (
                self.manager.structure.indexes_dir / "evidence_store_index.json"
            )
            if index_path.exists():
                self._evidence_index = EvidenceIndex.load(index_path)
                logger.info("Loaded evidence index from %s", index_path)
            else:
                self._evidence_index = build_evidence_index(
                    self.manager.structure.root,
                )
                if self._evidence_index.total_paragraphs > 0:
                    self._evidence_index.save(index_path)
                    logger.info(
                        "Built and saved evidence index (%d paragraphs)",
                        self._evidence_index.total_paragraphs,
                    )
        return self._evidence_index

    def search_evidence(
        self,
        query: str,
        *,
        max_results: int = 10,
        min_score: float = 0.1,
    ) -> list[SearchResult]:
        """Search the hollowed-out spec evidence store.

        Args:
            query: Free-text search query.
            max_results: Maximum results to return.
            min_score: Minimum relevance score threshold.

        Returns:
            Ranked list of ``SearchResult`` objects.
        """
        from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher

        if self._evidence_searcher is None:
            self._evidence_searcher = EvidenceSearcher(self.evidence_index)

        return self._evidence_searcher.search(
            query,
            max_results=max_results,
            min_score=min_score,
        )

    def search_evidence_for_ambiguity(
        self,
        ambiguity_text: str,
        ambiguity_question: str,
        context_section: str = "",
        max_results: int = 5,
    ) -> list[SearchResult]:
        """Search the evidence store specifically for ambiguity resolution.

        Combines ambiguity text, question, and context into a weighted query
        optimised for finding spec answers.

        Args:
            ambiguity_text: The ambiguous text.
            ambiguity_question: The question to resolve.
            context_section: Surrounding context from the translation.
            max_results: Maximum results to return.

        Returns:
            Ranked list of ``SearchResult`` objects.
        """
        from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher

        if self._evidence_searcher is None:
            self._evidence_searcher = EvidenceSearcher(self.evidence_index)

        return self._evidence_searcher.search_for_ambiguity(
            ambiguity_text=ambiguity_text,
            ambiguity_question=ambiguity_question,
            context_section=context_section,
            max_results=max_results,
        )
