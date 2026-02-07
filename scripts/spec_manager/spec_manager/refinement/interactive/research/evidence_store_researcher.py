"""Evidence store researcher - searches hollowed-out specs for ambiguity answers."""

from __future__ import annotations

import logging
from pathlib import Path

from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher, SearchResult
from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse

logger = logging.getLogger(__name__)

# Minimum score threshold for evidence store results to be considered "found"
EVIDENCE_FOUND_THRESHOLD = 0.4


class EvidenceStoreResearcher:
    """Searches the hollowed-out spec evidence store for ambiguity resolution.

    Integrates with the existing research flow as a pre-filter before web search.
    When the evidence store has a high-confidence answer, web search is skipped.
    When no answer is found, the ambiguity is flagged as a potential spec gap.
    """

    def __init__(self, index: EvidenceIndex) -> None:
        self._index = index
        self._searcher = EvidenceSearcher(index)

    def research(
        self,
        ambiguity: Ambiguity,
        workspace: Path,
    ) -> SteeringResponse | None:
        """Search the evidence store for an answer to the ambiguity.

        Args:
            ambiguity: The ambiguity to research.
            workspace: Working directory.

        Returns:
            SteeringResponse if a sufficient answer was found, None otherwise.
        """
        results = self._searcher.search_for_ambiguity(
            ambiguity_text=ambiguity.source_text,
            ambiguity_question=ambiguity.suggested_question,
            context_section=ambiguity.source_location,
            max_results=5,
        )

        if not results:
            logger.info(
                "No evidence store results for ambiguity %s",
                ambiguity.ambiguity_id,
            )
            return None

        # Check if top result meets the threshold
        top_score = results[0].score
        if top_score < EVIDENCE_FOUND_THRESHOLD:
            logger.info(
                "Evidence store results below threshold (%.2f < %.2f) for %s",
                top_score,
                EVIDENCE_FOUND_THRESHOLD,
                ambiguity.ambiguity_id,
            )
            return None

        logger.info(
            "Evidence store found answer for %s (score=%.2f)",
            ambiguity.ambiguity_id,
            top_score,
        )
        return self._format_response(ambiguity, results)

    def _format_response(
        self,
        ambiguity: Ambiguity,
        results: list[SearchResult],
    ) -> SteeringResponse:
        """Format search results into a SteeringResponse."""
        parts: list[str] = []
        for result in results:
            if result.score >= EVIDENCE_FOUND_THRESHOLD:
                parts.append(
                    f"[{result.lib_id}/{result.section_path}] "
                    f"(score={result.score:.2f}): {result.paragraph.text}"
                )

        response_text = "\n\n".join(parts) if parts else results[0].paragraph.text

        return SteeringResponse(
            ambiguity_id=ambiguity.ambiguity_id,
            response_text=response_text,
            source="evidence_store",
        )

    def flag_as_spec_gap(
        self,
        ambiguity: Ambiguity,
        workspace: Path,
    ) -> None:
        """Flag an unresolved ambiguity as a genuine spec gap.

        Creates a Gap entry in the workspace's gap queue for the
        spec building phase to address.
        """
        from spec_manager.refinement.core.gap import Gap, GapEvidence, GapType
        from spec_manager.refinement.core.gap_queue import GapQueue
        from spec_manager.core.gaps import Severity

        gap_evidence = GapEvidence(
            invariant_family="ambiguity",
            description=(
                f"Unresolved ambiguity: {ambiguity.suggested_question}"
            ),
            details={
                "ambiguity_id": ambiguity.ambiguity_id,
                "source_text": ambiguity.source_text,
                "source_location": ambiguity.source_location,
                "ambiguity_type": ambiguity.ambiguity_type,
                "confidence": ambiguity.confidence,
                "gap_type": "ambiguity",
            },
            confidence=ambiguity.confidence,
            location=ambiguity.source_location,
            detector="evidence_store_researcher",
        )

        gap = Gap(
            id=f"GAP-ES-{ambiguity.ambiguity_id}",
            gap_type=GapType.ambiguity,
            severity=Severity.WARNING,
            source=[ambiguity.source_location],
            derived_artifact_target=ambiguity.source_location,
            description=(
                f"Evidence gap: {ambiguity.suggested_question}"
            ),
            evidence=[gap_evidence],
        )

        # Write gap to the workspace gap queue file
        gap_queue_path = workspace / "evidence_store_gaps.json"
        if gap_queue_path.exists():
            import json

            existing_data = json.loads(
                gap_queue_path.read_text(encoding="utf-8")
            )
            queue = GapQueue.from_dict(existing_data)
        else:
            queue = GapQueue()

        # Add the new gap
        existing_ids = {g.id for g in queue.gaps}
        if gap.id not in existing_ids:
            queue.gaps.append(gap)

        import json

        gap_queue_path.parent.mkdir(parents=True, exist_ok=True)
        gap_queue_path.write_text(
            json.dumps(queue.to_dict(), indent=2), encoding="utf-8"
        )
        logger.info(
            "Flagged ambiguity %s as spec gap in %s",
            ambiguity.ambiguity_id,
            gap_queue_path,
        )
