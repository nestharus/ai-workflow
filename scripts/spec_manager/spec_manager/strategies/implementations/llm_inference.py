"""LLM-based inference strategies for prose fragment processing.

CRITICAL: LLM outputs are EVIDENCE, not truth.
- Each inference has confidence score and provenance spans
- Prose fragments are reduced over passes as inferences are confirmed
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

from spec_manager.core.provenance import (
    GranularityLevel,
    SourceLocation,
    TrackedUnit,
    UnitStatus,
    UnitType,
)

logger = logging.getLogger(__name__)


@dataclass
class InferenceResult:
    """Result of an LLM inference operation."""

    inferred_content: str  # What was inferred
    confidence: float  # 0.0-1.0 confidence score
    source_spans: list[SourceLocation]  # Where the inference came from
    inference_type: str  # "requirement", "claim", "patch_target", etc.
    rationale: str  # LLM's explanation


@dataclass
class ProseFragmentEvidence:
    """Evidence from LLM inference over prose fragments."""

    fragment: str  # The prose fragment analyzed
    location: SourceLocation
    inferences: list[InferenceResult]  # What the LLM inferred
    remaining_prose: str | None  # Content not captured by inferences


class ProseFragmentInferenceDetector:
    """Infer requirements/claims from scattered prose fragments using LLM.

    CRITICAL: Outputs are EVIDENCE with confidence, not authoritative truth.
    """

    def __init__(self, llm_client: Any = None) -> None:
        self._llm = llm_client

    def detect(self, units: list[TrackedUnit]) -> list[ProseFragmentEvidence]:
        """Analyze prose units to infer hidden requirements/claims."""
        evidence_list = []

        for unit in units:
            if unit.unit_type != UnitType.PROSE:
                continue

            # Skip short prose (unlikely to contain hidden requirements)
            if len(unit.content) < 50:
                continue

            evidence = self._analyze_fragment(unit)
            if evidence.inferences:
                evidence_list.append(evidence)

        return evidence_list

    def _analyze_fragment(self, unit: TrackedUnit) -> ProseFragmentEvidence:
        """Analyze a single prose fragment for hidden requirements."""
        inferences: list[InferenceResult] = []

        inferences = self._heuristic_inference(unit) if not self._llm else self._llm_inference(unit)

        return ProseFragmentEvidence(
            fragment=unit.content,
            location=unit.source,
            inferences=inferences,
            remaining_prose=self._compute_remaining(unit.content, inferences),
        )

    def _heuristic_inference(
        self, unit: TrackedUnit, fallback_reason: str | None = None
    ) -> list[InferenceResult]:
        """Fallback heuristic-based inference without LLM."""
        inferences: list[InferenceResult] = []
        content = unit.content

        # Pattern: "must", "should", "always", "never"
        requirement_patterns = [
            (r"\b(must|shall)\s+(\w+)", 0.8),
            (r"\b(should)\s+(\w+)", 0.6),
            (r"\b(always|never)\s+(\w+)", 0.7),
            (r"\brequire[ds]?\b", 0.7),
        ]

        for pattern, base_confidence in requirement_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                # Extract surrounding context
                start = max(0, match.start() - 50)
                end = min(len(content), match.end() + 50)
                context = content[start:end].strip()

                inferences.append(
                    InferenceResult(
                        inferred_content=context,
                        confidence=base_confidence,
                        source_spans=[unit.source],
                        inference_type="requirement",
                        rationale=self._build_heuristic_rationale(match.group(), fallback_reason),
                    )
                )

        return inferences

    def _llm_inference(self, unit: TrackedUnit) -> list[InferenceResult]:
        """Use LLM to infer requirements from prose."""
        prompt = "Analyze this prose fragment and extract any "
        prompt += "hidden requirements, claims, or invariants.\n\n"
        prompt += f"Fragment:\n{unit.content}\n\n"
        prompt += (
            "For each inference:\n"
            "1. State the requirement/claim clearly\n"
            "2. Provide a confidence score (0.0-1.0)\n"
            "3. Explain your reasoning\n\n"
            "Output as JSON array:\n"
            '[{"content": "...", "confidence": 0.X, '
            '"type": "requirement|claim|invariant", "rationale": "..."}]'
        )

        try:
            response = self._llm.complete(prompt)
            import json

            results = json.loads(response)

            return [
                InferenceResult(
                    inferred_content=r["content"],
                    confidence=r["confidence"],
                    source_spans=[unit.source],
                    inference_type=r["type"],
                    rationale=r["rationale"],
                )
                for r in results
            ]
        except Exception as exc:
            logger.warning(
                "LLM inference failed for %s; falling back to heuristics",
                unit.id,
                exc_info=True,
            )
            fallback_reason = f"LLM inference failed: {type(exc).__name__}: {exc}"
            return self._heuristic_inference(unit, fallback_reason=fallback_reason)

    def _compute_remaining(self, content: str, inferences: list[InferenceResult]) -> str | None:
        """Compute what prose remains after inferences are extracted."""
        remaining = content
        for inf in inferences:
            # Remove inferred content from remaining
            remaining = remaining.replace(inf.inferred_content, "")

        remaining = remaining.strip()
        return remaining if remaining else None


class ProseFragmentReductionStrategy:
    """Strategy to reduce prose fragments by promoting inferences to structured elements.

    Iteratively transforms inferred requirements into Claims/Invariants,
    shrinking the prose remainder over passes.
    """

    def __init__(self, confidence_threshold: float = 0.7) -> None:
        self.confidence_threshold = confidence_threshold
        self.detector = ProseFragmentInferenceDetector()

    def execute(self, units: list[TrackedUnit]) -> tuple[list[TrackedUnit], list[TrackedUnit]]:
        """Execute prose reduction.

        Returns:
            (promoted_units, updated_prose_units)
        """
        evidence_list = self.detector.detect(units)

        promoted: list[TrackedUnit] = []
        updated_prose: list[TrackedUnit] = []

        for evidence in evidence_list:
            # Promote high-confidence inferences
            for inf in evidence.inferences:
                if inf.confidence >= self.confidence_threshold:
                    promoted.append(self._create_structured_unit(inf, evidence))

            # Update prose unit with remaining content
            if evidence.remaining_prose:
                updated_prose.append(self._create_remainder_unit(evidence))

        return promoted, updated_prose

    def _create_structured_unit(
        self, inference: InferenceResult, evidence: ProseFragmentEvidence
    ) -> TrackedUnit:
        """Create a structured unit from an inference."""
        # Determine unit type from inference type
        type_map = {
            "requirement": UnitType.INVARIANT,
            "claim": UnitType.CLAIM,
            "invariant": UnitType.INVARIANT,
        }
        unit_type = type_map.get(inference.inference_type, UnitType.CLAIM)

        location_key = (
            f"{evidence.location.file}:{evidence.location.line_start}:{evidence.location.line_end}"
        )
        id_hash = hashlib.sha256(
            f"{location_key}\0{inference.inferred_content}".encode()
        ).hexdigest()
        content_hash = hashlib.sha256(inference.inferred_content.encode()).hexdigest()
        return TrackedUnit(
            id=f"_inferred_{id_hash[:12]}",
            content=inference.inferred_content,
            unit_type=unit_type,
            source=evidence.location,
            introduced_by="llm_inference",
            annotations=[f"(@[confidence:{inference.confidence:.2f}])"],
            granularity=GranularityLevel.SENTENCE,
            content_hash=content_hash,
        )

    def _create_remainder_unit(self, evidence: ProseFragmentEvidence) -> TrackedUnit:
        """Create a prose unit for remaining content."""
        content = evidence.remaining_prose or ""
        location_key = (
            f"{evidence.location.file}:{evidence.location.line_start}:{evidence.location.line_end}"
        )
        id_hash = hashlib.sha256(f"{location_key}\0{content}".encode()).hexdigest()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        return TrackedUnit(
            id=f"_remainder_{id_hash[:12]}",
            content=content,
            unit_type=UnitType.PROSE,
            source=evidence.location,
            introduced_by="llm_inference",
            status=UnitStatus.PENDING,
            granularity=GranularityLevel.SENTENCE,
            content_hash=content_hash,
        )

    @staticmethod
    def _build_heuristic_rationale(keyword: str, fallback_reason: str | None) -> str:
        """Build rationale text for heuristic inferences."""
        base = f"Contains requirement keyword: '{keyword}'"
        if fallback_reason:
            return f"{base}; fallback_reason={fallback_reason}"
        return base


class VagueReferenceResolver:
    """Resolve vague entity references using LLM + context retrieval.

    When a patch says "update the algorithm" without specifying which one,
    this resolver uses context to infer the target.
    """

    def __init__(self, reference_store: Any = None, llm_client: Any = None) -> None:
        self._store = reference_store
        self._llm = llm_client

    def resolve(self, reference_text: str, context: dict[str, Any]) -> list[InferenceResult]:
        """Resolve a vague reference to candidate targets.

        Args:
            reference_text: The vague reference (e.g., "the algorithm")
            context: Available context (patch chain, intermediates, etc.)

        Returns:
            List of candidate resolutions with confidence scores
        """
        candidates: list[InferenceResult] = []

        if self._store:
            # Get candidate targets from reference store
            store_candidates = self._store.retrieve(reference_text, context, top_k=10)
            for cand_id, score in store_candidates:
                candidates.append(
                    InferenceResult(
                        inferred_content=cand_id,
                        confidence=score,
                        source_spans=[],
                        inference_type="patch_target",
                        rationale=f"Retrieved from reference store (score: {score:.2f})",
                    )
                )

        if self._llm and context:
            # Use LLM to rank/refine candidates
            candidates = self._llm_rerank(reference_text, candidates, context)

        return sorted(candidates, key=lambda x: -x.confidence)

    def _llm_rerank(
        self, reference_text: str, candidates: list[InferenceResult], context: dict[str, Any]
    ) -> list[InferenceResult]:
        """Use LLM to rerank candidates based on context."""
        if not candidates:
            return candidates

        prompt = f"""Given the vague reference "{reference_text}" and this context:

Patch chain: {context.get("patch_chain", "unknown")}
Nearby elements: {context.get("nearby_elements", [])}

Rank these candidates by likelihood of being the target:
{[c.inferred_content for c in candidates]}

Output as JSON: [{{"id": "...", "confidence": 0.X, "reason": "..."}}]"""

        try:
            response = self._llm.complete(prompt)
            import json

            rankings = json.loads(response)

            # Update confidence scores
            for ranking in rankings:
                for cand in candidates:
                    if cand.inferred_content == ranking["id"]:
                        cand.confidence = ranking["confidence"]
                        cand.rationale = ranking["reason"]
                        break

        except Exception:
            logger.debug("LLM score adjustment failed", exc_info=True)
            # Keep original scores on error

        return candidates
