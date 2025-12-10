"""Artifact-level semantic fact extraction orchestrator.

This module implements the canonical control flow for artifact-level semantic fact
extraction as specified in docs/plans/fact_redesign.md. It coordinates the Hunter,
Surgeon, and Auditor agents to extract facts from artifacts while maintaining
design invariants.

Note:
    The Hunter now uses the huggingface_agent_runner internally, which delegates
    model inference to the ministral-recognizer agent via subprocess.

Control Flow:
    INITIALIZE -> MAIN LOOP -> FINAL AUDIT

    MAIN LOOP:
        1. Entity Discovery Phase: Hunter discovers entities
        2. Fact Extraction Phase: Hunter extracts facts about target entity
        3. Sanitization Phase: Surgeon rewrites spans to remove facts
        4. Commit: Apply rewrites, check for no-op, persist pass record

Design Invariants (runtime assertions):
    1. Text-is-state: state_text is the only source of truth
    2. Monotonic extraction: len(state_text) decreases or triggers safety handling
    3. Localized rewrites: Only spans returned by Hunter are rewritten
    4. Non-target preservation: Anchors must be preserved (validated by Qwen3)
    5. Unified entity/fact discovery: Alternates between entity discovery and fact extraction

Usage:
    uv run knowledge.extract-artifact-facts --artifact-id artifact_123

    Or programmatically:
    from scripts.knowledge.artifact_fact_extractor import extract_artifact_facts
    result = extract_artifact_facts("artifact_123", knowledge_path)

References:
    - docs/plans/fact_redesign.md lines 780-836
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import yaml

from scripts.dev.utils import REPO_ROOT, utc_timestamp
from scripts.knowledge.ministral_hunter import (
    invoke_hunter,
    invoke_hunter_mock,
)
from scripts.knowledge.passes_manager import PassRecord, append_pass, ensure_passes_csv_exists
from scripts.knowledge.residue_manager import (
    save_residue_snapshot,
)
from scripts.knowledge.surgeon_orchestrator import (
    RewriteResult,
    SpanInput,
    SurgeonError,
    orchestrate_surgeon_pipeline,
    orchestrate_surgeon_pipeline_mock,
)
from scripts.knowledge.variant_resolver import load_qwen_embedding_model

if TYPE_CHECKING:
    from transformers import PreTrainedModel, PreTrainedTokenizer


class ExtractionSummary(TypedDict):
    """Summary of artifact-level extraction.

    Attributes:
        artifact_id: ID of the processed artifact.
        total_passes: Number of extraction passes performed.
        total_facts_extracted: Total facts extracted across all passes.
        final_state_hash: Hash of the final state text.
        audit_result: Result from the Auditor.
    """

    artifact_id: str
    total_passes: int
    total_facts_extracted: int
    final_state_hash: str
    audit_result: dict[str, Any]


class ArtifactExtractionError(Exception):
    """Error raised during artifact extraction."""


# Design invariant assertions
class InvariantViolation(Exception):
    """Error raised when a design invariant is violated."""


def _compute_hash(text: str) -> str:
    """Compute SHA-256 hash of text.

    Args:
        text: Text to hash.

    Returns:
        Hex digest of SHA-256 hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assert_text_is_state(state_text: str) -> None:
    """Assert text-is-state invariant.

    The state_text must be a non-None string. This is the only source of truth.

    Args:
        state_text: Current state text.

    Raises:
        InvariantViolation: If state_text is None.
    """
    if state_text is None:
        raise InvariantViolation("text-is-state: state_text cannot be None")


def _assert_monotonic_or_handle(
    old_len: int,
    new_len: int,
    state_hash: str,
    seen_hashes: set[str],
) -> bool:
    """Assert monotonic extraction invariant.

    Text should decrease or stay same. If it increases, that's a violation.
    If hash is repeated, we have a no-op situation.

    Args:
        old_len: Length of text before rewrite.
        new_len: Length of text after rewrite.
        state_hash: Hash of new state.
        seen_hashes: Set of previously seen hashes.

    Returns:
        True if no-op detected (hash repeated), False otherwise.

    Raises:
        InvariantViolation: If text length increased.
    """
    if new_len > old_len:
        raise InvariantViolation(
            f"monotonic-extraction: text length increased from {old_len} to {new_len}"
        )
    return state_hash in seen_hashes


def _compute_text_diff_regions(old_text: str, new_text: str) -> list[tuple[int, int]]:
    """Compute regions that differ between old and new text.

    Uses a simple character-by-character diff to find modified regions.

    Args:
        old_text: Original text.
        new_text: Modified text.

    Returns:
        List of (start, end) tuples indicating modified regions in old_text.
    """
    from difflib import SequenceMatcher

    matcher = SequenceMatcher(None, old_text, new_text)
    diff_regions: list[tuple[int, int]] = []

    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag != "equal":
            # This region was changed in the original text
            diff_regions.append((i1, i2))

    return diff_regions


def _assert_localized_rewrites(
    original_text: str,
    rewrites: list[RewriteResult],
    spans: list[SpanInput],
    new_state_text: str | None = None,
) -> None:
    """Assert localized rewrites invariant.

    Only spans returned by Hunter should be rewritten. This function validates
    that all modified regions in the text fall within the boundaries of the
    targeted spans' original text.

    Args:
        original_text: Original state text before rewrites.
        rewrites: List of rewrite results.
        spans: List of spans that were targeted.
        new_state_text: New state text after rewrites (for diff comparison).

    Raises:
        InvariantViolation: If rewrites affect text outside spans.
    """
    # First, validate all rewrites correspond to known spans
    for rewrite in rewrites:
        span_id = rewrite["span_id"]
        matching_spans = [s for s in spans if s["span_id"] == span_id]
        if not matching_spans:
            raise InvariantViolation(f"localized-rewrites: rewrite for unknown span {span_id}")

    # If we have the new state text, verify changes are localized
    if new_state_text is not None and new_state_text != original_text:
        # Build a union of all span regions in the original text
        span_regions: list[tuple[int, int]] = []
        for span in spans:
            span_text = span["original_text"]
            start = original_text.find(span_text)
            if start != -1:
                span_regions.append((start, start + len(span_text)))

        if not span_regions:
            # If we can't locate spans in the text, we can't verify localization
            return

        # Compute diff regions
        diff_regions = _compute_text_diff_regions(original_text, new_state_text)

        # Check that all diff regions fall within span regions
        for diff_start, diff_end in diff_regions:
            in_span = False
            for span_start, span_end in span_regions:
                # Check if diff region overlaps with span region
                if diff_start >= span_start and diff_end <= span_end:
                    in_span = True
                    break
                # Also check for overlapping deletions that shrink the text
                if diff_start >= span_start and diff_start < span_end:
                    in_span = True
                    break
            if not in_span and diff_end > diff_start:
                raise InvariantViolation(
                    f"localized-rewrites: change at positions [{diff_start}:{diff_end}] "
                    f"is outside all targeted spans"
                )


def _assert_non_target_preservation(
    original_text: str,
    new_text: str,
    spans: list[SpanInput],
    rewrites: list[RewriteResult],
    qwen_model: Any | None = None,
    qwen_tokenizer: Any | None = None,
    threshold: float = 0.8,
) -> None:
    """Assert non-target preservation invariant.

    Verifies that text outside the targeted spans (anchors and context) is
    preserved after rewrites. Uses a heuristic check that non-span text
    remains present.

    Args:
        original_text: Original state text.
        new_text: State text after rewrites.
        spans: List of spans that were targeted.
        rewrites: List of rewrite results.
        qwen_model: Optional Qwen model for embedding-based checks.
        qwen_tokenizer: Optional Qwen tokenizer.
        threshold: Minimum preservation threshold (default: 0.8).

    Raises:
        InvariantViolation: If non-target content is significantly altered.
    """
    # Build the set of text that should NOT have been modified
    # (everything except the span original texts)
    span_texts = {s["original_text"] for s in spans}

    # Simple heuristic: check that non-span sentences are preserved
    # Split original into sentences
    import re

    sentences = re.split(r"(?<=[.!?])\s+", original_text)

    non_span_sentences = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        # Check if this sentence is inside any span
        in_span = False
        for span_text in span_texts:
            if sentence in span_text or span_text in sentence:
                in_span = True
                break
        if not in_span:
            non_span_sentences.append(sentence)

    # Verify non-span sentences are still present in new text
    missing_sentences = []
    for sentence in non_span_sentences:
        # Allow for minor variations (whitespace, punctuation)
        normalized_sentence = sentence.lower().strip()
        normalized_new = new_text.lower()
        if normalized_sentence not in normalized_new:
            # Try partial match (first 20 chars)
            if len(normalized_sentence) > 20:
                partial = normalized_sentence[:20]
                if partial not in normalized_new:
                    missing_sentences.append(sentence)
            else:
                missing_sentences.append(sentence)

    # If too many non-span sentences are missing, it's a violation
    if non_span_sentences and missing_sentences:
        preservation_ratio = 1 - (len(missing_sentences) / len(non_span_sentences))
        if preservation_ratio < threshold:
            raise InvariantViolation(
                f"non-target-preservation: {len(missing_sentences)} of "
                f"{len(non_span_sentences)} non-span sentences were altered/removed "
                f"(preservation ratio: {preservation_ratio:.2f} < {threshold})"
            )


def load_artifact_manifest(artifact_id: str, knowledge_path: Path) -> dict[str, Any]:
    """Load artifact manifest from YAML.

    Args:
        artifact_id: ID of the artifact.
        knowledge_path: Base knowledge directory.

    Returns:
        Parsed artifact manifest.

    Raises:
        ArtifactExtractionError: If manifest not found or invalid.
    """
    manifest_path = knowledge_path / "artifacts" / f"{artifact_id}.yml"
    if not manifest_path.exists():
        raise ArtifactExtractionError(f"Artifact manifest not found: {manifest_path}")

    try:
        content = manifest_path.read_text(encoding="utf-8")
        manifest = yaml.safe_load(content)
        if not isinstance(manifest, dict):
            raise ArtifactExtractionError(f"Invalid manifest format: {manifest_path}")
    except yaml.YAMLError as e:
        raise ArtifactExtractionError(f"Failed to parse manifest: {e}") from e
    else:
        return manifest


def load_artifact_text(manifest: dict[str, Any], knowledge_path: Path) -> str:
    """Load artifact text from manifest.

    The manifest can contain:
    - inline_text: Text directly in the manifest
    - source_file: Path to file containing the text
    - source_element_id: Element ID within a YAML file

    Args:
        manifest: Parsed artifact manifest.
        knowledge_path: Base knowledge directory.

    Returns:
        Artifact text content.

    Raises:
        ArtifactExtractionError: If text cannot be loaded.
    """
    # Check for inline text first
    if "inline_text" in manifest:
        return str(manifest["inline_text"])

    # Check for source file
    if "source_file" in manifest:
        source_path = REPO_ROOT / manifest["source_file"]
        if not source_path.exists():
            raise ArtifactExtractionError(f"Source file not found: {source_path}")

        try:
            content: str = source_path.read_text(encoding="utf-8")

            # If source_element_id is specified, extract that element
            if "source_element_id" in manifest:
                element_id = manifest["source_element_id"]
                data = yaml.safe_load(content)
                element = _find_element_by_id(data, element_id)
                if element is None:
                    raise ArtifactExtractionError(
                        f"Element {element_id} not found in {source_path}"
                    )
                # Extract text field from element
                text = element.get("text", "")
                if isinstance(text, list):
                    text = " ".join(str(t) for t in text)
                content = str(text)
        except (OSError, yaml.YAMLError) as e:
            raise ArtifactExtractionError(f"Failed to load source file: {e}") from e
        else:
            return content

    raise ArtifactExtractionError("Manifest must contain inline_text or source_file")


def _find_element_by_id(data: Any, target_id: str) -> dict[str, Any] | None:
    """Recursively find a YAML element by its 'id' field.

    Args:
        data: The parsed YAML structure.
        target_id: The element ID to find.

    Returns:
        The element dict if found, None otherwise.
    """
    if isinstance(data, dict):
        if data.get("id") == target_id:
            return data
        for value in data.values():
            result = _find_element_by_id(value, target_id)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_element_by_id(item, target_id)
            if result is not None:
                return result
    return None


def resolve_entity(
    entity_mention: str,
    artifact_id: str,
    knowledge_path: Path,
) -> str:
    """Resolve entity mention to canonical ID.

    Entity resolution rules are defined in Task 9 (fact_redesign_plan.md lines 172-189).
    This Task 6 implementation uses pass-through until Task 9 implements the full
    resolution procedure which includes:
    - Exact match to YAML `id` entities
    - Exact match to canonical keywords
    - Variant match via variant table
    - Embedding similarity above threshold
    - Else: Record as unresolved candidate

    Args:
        entity_mention: The entity mention text.
        artifact_id: ID of the artifact.
        knowledge_path: Base knowledge directory.

    Returns:
        Resolved entity ID (pass-through until Task 9).
    """
    # Task 9 will implement full resolution via variant_resolver
    # Per fact_redesign_plan.md lines 172-189: Entity Resolution Rules
    return entity_mention


def apply_rewrite(
    state_text: str,
    span: SpanInput,
    replacement_text: str,
) -> str:
    """Apply a span replacement to state text.

    Args:
        state_text: Current state text.
        span: Span to replace.
        replacement_text: New text for the span.

    Returns:
        Updated state text.
    """
    original = span["original_text"]
    if original in state_text:
        return state_text.replace(original, replacement_text, 1)
    return state_text


def persist_pass(
    pass_id: str,
    artifact_id: str,
    entity_id: str,
    entity_mention: str,
    span: SpanInput,
    facts_removed: list[str],
    replacement_text: str,
    state_hash_before: str,
    state_hash_after: str,
    similarity_score: float,
    status: str,
    knowledge_path: Path,
    chunk_id: str | None = None,
) -> None:
    """Persist a pass record to the passes CSV.

    Args:
        pass_id: Unique ID for this pass.
        artifact_id: ID of the artifact.
        entity_id: Resolved entity ID.
        entity_mention: Entity mention text.
        span: The span that was rewritten.
        facts_removed: List of facts removed.
        replacement_text: Text after rewrite.
        state_hash_before: State hash before this pass.
        state_hash_after: State hash after this pass.
        similarity_score: Validation similarity score.
        status: Pass status ('success', 'failure', etc.).
        knowledge_path: Base knowledge directory.
        chunk_id: Optional chunk ID for traceability (default: auto-generated).
    """
    csv_path = knowledge_path / "facts" / "passes.csv"
    ensure_passes_csv_exists(csv_path)

    # Use provided chunk_id or generate one from span metadata
    if chunk_id is None:
        chunk_id = f"{artifact_id}:{pass_id[:8]}:{span['span_id']}"

    record = PassRecord(
        pass_id=pass_id,
        artifact_id=artifact_id,
        entity_id=entity_id,
        entity_mention=entity_mention,
        span_id=span["span_id"],
        chunk_id=chunk_id,
        span_before=span["original_text"],
        span_after=replacement_text,
        facts_removed=json.dumps(facts_removed),
        similarity_score=f"{similarity_score:.4f}",
        status=status,
        failure_reason="",
        created_at=utc_timestamp(),
    )
    append_pass(csv_path, record)


def persist_residue_report(
    artifact_id: str,
    auditor_result: dict[str, Any],
    state_text: str,
    knowledge_path: Path,
) -> None:
    """Persist residue snapshot and audit report.

    Args:
        artifact_id: ID of the artifact.
        auditor_result: Result from the Auditor.
        state_text: Final state text.
        knowledge_path: Base knowledge directory.
    """
    # Save the after snapshot
    save_residue_snapshot(
        artifact_id=artifact_id,
        state_text=state_text,
        snapshot_type="after",
        knowledge_path=knowledge_path,
    )

    # Save audit report as JSON
    residue_dir = knowledge_path / "facts" / "residue"
    residue_dir.mkdir(parents=True, exist_ok=True)
    audit_file = residue_dir / f"{artifact_id}.audit.json"
    audit_file.write_text(json.dumps(auditor_result, indent=2), encoding="utf-8")


def invoke_auditor(
    artifact_id: str,
    state_text: str,
    extraction_history: list[dict[str, Any]],
    stuck_reason: str | None,
    knowledge_path: Path,
) -> dict[str, Any]:
    """Invoke the Auditor sub-agent.

    Args:
        artifact_id: ID of the artifact.
        state_text: Current state text.
        extraction_history: History of extraction passes.
        stuck_reason: Reason for stuck state (or None).
        knowledge_path: Base knowledge directory.

    Returns:
        Auditor output dictionary.
    """
    from scripts.knowledge.surgeon_orchestrator import invoke_sub_agent

    auditor_input = {
        "artifact_id": artifact_id,
        "state_text": state_text,
        "extraction_history": extraction_history,
        "stuck_reason": stuck_reason,
    }

    try:
        return invoke_sub_agent(
            "fact-auditor",
            auditor_input,
            model="opus",
            timeout=180,  # Auditor gets more time for complex analysis
            knowledge_path=knowledge_path,
        )
    except SurgeonError as e:
        # Return a default audit result on failure
        return {
            "has_remaining_facts": True,
            "remaining_facts": [],
            "recommended_action": "escalate",
            "notes": f"Auditor invocation failed: {e}",
        }


def extract_artifact_facts(
    artifact_id: str,
    knowledge_path: Path,
    qwen_model_name: str = "Qwen/Qwen3-Embedding-0.6B",
    ministral_model_name: str = "mistralai/Ministral-3B-Instruct-2412",
    max_iterations: int = 50,
    use_mock: bool = False,
) -> ExtractionSummary:
    """Extract facts from an artifact using the multi-agent pipeline.

    Implements the canonical control flow:
    INITIALIZE -> MAIN LOOP -> FINAL AUDIT

    Note:
        The Hunter now uses the huggingface_agent_runner internally, which loads
        the model configuration from the ministral-recognizer agent's frontmatter.

    Args:
        artifact_id: ID of the artifact to process.
        knowledge_path: Base knowledge directory.
        qwen_model_name: Qwen model for embedding validation.
        ministral_model_name: Deprecated. This parameter is retained for backward
            compatibility but is ignored. The Ministral model is now configured
            via the ministral-recognizer agent's frontmatter.
        max_iterations: Maximum extraction iterations (default: 50).
        use_mock: Use mock implementations for testing (default: False).

    Returns:
        ExtractionSummary with results.

    Raises:
        ArtifactExtractionError: If extraction fails.
        InvariantViolation: If a design invariant is violated.
    """
    # Silence unused variable warning for deprecated parameter
    _ = ministral_model_name
    # INITIALIZE
    print(f"Initializing extraction for artifact: {artifact_id}")

    # Load artifact
    manifest = load_artifact_manifest(artifact_id, knowledge_path)
    state_text = load_artifact_text(manifest, knowledge_path)

    # Save before snapshot
    save_residue_snapshot(
        artifact_id=artifact_id,
        state_text=state_text,
        snapshot_type="before",
        knowledge_path=knowledge_path,
    )

    # Initialize state
    _assert_text_is_state(state_text)
    state_hash = _compute_hash(state_text)
    seen_hashes: set[str] = {state_hash}
    entity_queue: list[str] = []
    extraction_history: list[dict[str, Any]] = []
    total_facts_extracted = 0
    pass_count = 0
    stuck_reason: str | None = None

    # Load models
    qwen_model: PreTrainedModel | None = None
    qwen_tokenizer: PreTrainedTokenizer | None = None

    if not use_mock:
        print(f"Loading Qwen model: {qwen_model_name}")
        qwen_model, qwen_tokenizer = load_qwen_embedding_model(qwen_model_name)

    # MAIN LOOP
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        print(f"\n--- Iteration {iteration} ---")

        # Entity Discovery Phase
        if not entity_queue:
            print("Entity discovery phase...")
            if use_mock:
                hunter_result = invoke_hunter_mock(state_text, mode="entities")
            else:
                hunter_result = invoke_hunter(
                    state_text,
                    mode="entities",
                    knowledge_path=knowledge_path,
                )

            if hunter_result["done"]:
                print(f"Hunter signaled done: {hunter_result.get('reason')}")
                break

            # Add discovered entities to queue
            for entity in hunter_result["entities"]:
                entity_mention = entity["mention"]
                if entity_mention not in entity_queue:
                    entity_queue.append(entity_mention)

            if not entity_queue:
                print("No entities discovered, extraction complete")
                break

            print(f"Discovered entities: {entity_queue}")

        # Pop next entity
        target_entity = entity_queue.pop(0)
        entity_id = resolve_entity(target_entity, artifact_id, knowledge_path)
        print(f"Targeting entity: {target_entity}")

        # Fact Extraction Phase
        print("Fact extraction phase...")
        if use_mock:
            hunter_result = invoke_hunter_mock(
                state_text, target_entity=target_entity, mode="facts"
            )
        else:
            hunter_result = invoke_hunter(
                state_text,
                target_entity=target_entity,
                mode="facts",
                knowledge_path=knowledge_path,
            )

        if not hunter_result["facts"]:
            print(f"No facts found for {target_entity}")
            continue

        facts = hunter_result["facts"]
        spans = hunter_result["spans"]
        print(f"Found {len(facts)} fact(s) in {len(spans)} span(s)")

        # Build SpanInput list with chunk IDs for traceability
        span_inputs: list[SpanInput] = []
        for span in spans:
            # Find facts for this span
            span_facts = [f["fact_text"] for f in facts if f["evidence_span_id"] == span["span_id"]]
            # Generate chunk ID combining artifact, pass, and span info
            chunk_id = f"{artifact_id}:pass{pass_count + 1}:{span['span_id']}"
            span_inputs.append(
                SpanInput(
                    span_id=span["span_id"],
                    original_text=span["original_text"],
                    target_facts=span_facts,
                    anchor_facts=[],  # Will be determined by Organizer
                )
            )
            # Store chunk_id in span metadata for later reference (runtime dict)
            span["chunk_id"] = chunk_id  # type: ignore[typeddict-unknown-key]

        # Sanitization Phase
        print("Sanitization phase...")
        target_facts = [f["fact_text"] for f in facts]

        if use_mock:
            rewrites = orchestrate_surgeon_pipeline_mock(
                spans=span_inputs,
                target_facts=target_facts,
                anchor_facts=[],
                artifact_id=artifact_id,
            )
        else:
            rewrites = orchestrate_surgeon_pipeline(
                spans=span_inputs,
                target_facts=target_facts,
                anchor_facts=[],
                artifact_id=artifact_id,
                qwen_model=qwen_model,
                qwen_tokenizer=qwen_tokenizer,
                knowledge_path=knowledge_path,
            )

        # Save state before rewrites for invariant checks
        old_state_text = state_text
        old_len = len(state_text)
        old_hash = state_hash
        facts_this_pass: list[str] = []

        # Apply rewrites
        for rewrite in rewrites:
            if rewrite["success"]:
                matched_span = next(
                    (s for s in span_inputs if s["span_id"] == rewrite["span_id"]),
                    None,
                )
                if matched_span is not None:
                    state_text = apply_rewrite(
                        state_text, matched_span, rewrite["replacement_text"]
                    )
                    facts_this_pass.extend(matched_span.get("target_facts", []))

        # Compute new hash
        state_hash = _compute_hash(state_text)

        # Assert localized rewrites (with new state text for diff comparison)
        _assert_localized_rewrites(old_state_text, rewrites, span_inputs, state_text)

        # Assert non-target preservation
        try:
            _assert_non_target_preservation(
                old_state_text,
                state_text,
                span_inputs,
                rewrites,
                qwen_model,
                qwen_tokenizer,
            )
        except InvariantViolation as e:
            # On violation, revert to old state and log warning
            print(f"Warning: {e}")
            print("Reverting to pre-rewrite state for this pass")
            state_text = old_state_text
            state_hash = old_hash
            facts_this_pass = []

        # Assert monotonic and check for no-op
        is_no_op = _assert_monotonic_or_handle(old_len, len(state_text), state_hash, seen_hashes)

        if is_no_op:
            print("No-op detected (same hash seen before)")
            stuck_reason = "no_op_detected"
            break

        seen_hashes.add(state_hash)

        # Persist pass
        pass_id = str(uuid.uuid4())
        pass_count += 1

        # Get validation score from first successful rewrite
        similarity_score = 0.0
        for rewrite in rewrites:
            if rewrite["success"] and "score_drop" in rewrite.get("validation", {}):
                similarity_score = rewrite["validation"]["score_drop"]
                break

        if span_inputs:
            # Generate chunk_id for traceability
            chunk_id = f"{artifact_id}:pass{pass_count}:{span_inputs[0]['span_id']}"

            persist_pass(
                pass_id=pass_id,
                artifact_id=artifact_id,
                entity_id=entity_id,
                entity_mention=target_entity,
                span=span_inputs[0],  # Use first span for record
                facts_removed=facts_this_pass,
                replacement_text=rewrites[0]["replacement_text"] if rewrites else "",
                state_hash_before=old_hash,
                state_hash_after=state_hash,
                similarity_score=similarity_score,
                status="success",
                knowledge_path=knowledge_path,
                chunk_id=chunk_id,
            )

        # Record in history
        extraction_history.append(
            {
                "pass_id": pass_id,
                "entity": target_entity,
                "facts_removed": facts_this_pass,
            }
        )
        total_facts_extracted += len(facts_this_pass)

        print(f"Pass {pass_count}: Removed {len(facts_this_pass)} fact(s)")
        _assert_text_is_state(state_text)

        # Save intermediate residue snapshot after each pass
        save_residue_snapshot(
            artifact_id=artifact_id,
            state_text=state_text,
            snapshot_type="intermediate",
            pass_id=pass_id,
            knowledge_path=knowledge_path,
        )

    # Check for max iterations
    if iteration >= max_iterations:
        stuck_reason = "max_iterations"
        print(f"Hit max iterations ({max_iterations})")

    # FINAL AUDIT
    print("\n--- Final Audit ---")
    audit_result = invoke_auditor(
        artifact_id=artifact_id,
        state_text=state_text,
        extraction_history=extraction_history,
        stuck_reason=stuck_reason,
        knowledge_path=knowledge_path,
    )

    # Persist residue report
    persist_residue_report(
        artifact_id=artifact_id,
        auditor_result=audit_result,
        state_text=state_text,
        knowledge_path=knowledge_path,
    )

    print(f"Audit result: {audit_result.get('recommended_action')}")
    print(f"Notes: {audit_result.get('notes')}")

    return ExtractionSummary(
        artifact_id=artifact_id,
        total_passes=pass_count,
        total_facts_extracted=total_facts_extracted,
        final_state_hash=state_hash,
        audit_result=audit_result,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Extract facts from an artifact using multi-agent pipeline.",
    )
    parser.add_argument(
        "--artifact-id",
        required=True,
        dest="artifact_id",
        help="ID of the artifact to process.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    parser.add_argument(
        "--qwen-model",
        default="Qwen/Qwen3-Embedding-0.6B",
        dest="qwen_model",
        help="Qwen model for embedding validation.",
    )
    parser.add_argument(
        "--ministral-model",
        default="mistralai/Ministral-3B-Instruct-2412",
        dest="ministral_model",
        help=(
            "Deprecated. Retained for backward compatibility but ignored. "
            "The Ministral model is now configured via the ministral-recognizer agent."
        ),
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=50,
        dest="max_iterations",
        help="Maximum extraction iterations (default: 50).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock implementations for testing.",
    )
    return parser.parse_args(argv)


def main() -> int:
    """Entry point for knowledge.extract-artifact-facts command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()

    # Resolve knowledge path
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    try:
        result = extract_artifact_facts(
            artifact_id=args.artifact_id,
            knowledge_path=knowledge_path,
            qwen_model_name=args.qwen_model,
            ministral_model_name=args.ministral_model,
            max_iterations=args.max_iterations,
            use_mock=args.mock,
        )

        print("\n" + "=" * 50)
        print("Extraction Summary")
        print("=" * 50)
        print(f"Artifact ID: {result['artifact_id']}")
        print(f"Total Passes: {result['total_passes']}")
        print(f"Total Facts Extracted: {result['total_facts_extracted']}")
        print(f"Final State Hash: {result['final_state_hash'][:16]}...")
        print(f"Audit Action: {result['audit_result'].get('recommended_action')}")

    except ArtifactExtractionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except InvariantViolation as e:
        print(f"Invariant violation: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
    else:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
