"""Surgeon orchestrator for the multi-agent rewrite pipeline.

This module orchestrates the Surgeon sub-agent pipeline (Organizer -> Planner ->
Rewriter -> Reviewer) with Qwen3 embedding validation for artifact-level semantic
fact extraction.

The Surgeon pipeline ensures safe, localized rewrites that remove target facts
while preserving anchor facts (non-target information).

Usage:
    from scripts.knowledge.surgeon_orchestrator import orchestrate_surgeon_pipeline

    rewrites = orchestrate_surgeon_pipeline(
        spans=spans,
        target_facts=["Fact A about X"],
        anchor_facts=["Fact B about Y"],
        artifact_id="artifact_123",
        qwen_model=model,
        qwen_tokenizer=tokenizer,
    )

Pipeline Stages:
    1. Organizer: Groups spans by overlaps/related facts
    2. Planner: Plans rewrite strategy for each group
    3. Rewriter: Executes rewrites preserving anchors
    4. Qwen3 Validator: Validates semantic removal via embeddings
    5. Reviewer: Reviews low-confidence rewrites

References:
    - docs/plans/fact_redesign.md lines 691-762
    - scripts/knowledge/variant_resolver.py for Qwen embedding utilities
"""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge.variant_resolver import (
    compute_cosine_similarity,
    embed_keywords,
)

if TYPE_CHECKING:
    from transformers import PreTrainedModel, PreTrainedTokenizer

# Configure logging
logger = logging.getLogger(__name__)


class SurgeonError(Exception):
    """Error raised when the Surgeon pipeline fails."""


class SpanInput(TypedDict):
    """Input span for the Surgeon pipeline.

    Attributes:
        span_id: Unique identifier for this span.
        original_text: The original text of the span.
        target_facts: Facts to be removed from this span.
        anchor_facts: Facts to be preserved in this span.
    """

    span_id: str
    original_text: str
    target_facts: list[str]
    anchor_facts: list[str]


class RewriteResult(TypedDict):
    """Result of a rewrite operation.

    Attributes:
        span_id: ID of the span that was rewritten.
        replacement_text: The new text replacing the span.
        validation: Validation results from Qwen3.
        review: Review results if validation failed.
        success: Whether the rewrite was successful.
    """

    span_id: str
    replacement_text: str
    validation: dict[str, Any]
    review: dict[str, Any] | None
    success: bool


class GroupResult(TypedDict):
    """Result from the Organizer grouping spans.

    Attributes:
        group_id: Unique identifier for this group.
        span_ids: List of span IDs in this group.
        anchors_to_keep: Anchor facts to preserve.
        targets_to_remove: Target facts to remove.
    """

    group_id: str
    span_ids: list[str]
    anchors_to_keep: list[str]
    targets_to_remove: list[str]


class PlanResult(TypedDict):
    """Result from the Planner planning a rewrite.

    Attributes:
        group_id: ID of the group being planned.
        plan: The rewrite plan details.
    """

    group_id: str
    plan: dict[str, Any]


def _ensure_log_dir(knowledge_path: Path) -> Path:
    """Ensure the surgeon logs directory exists.

    Args:
        knowledge_path: Base knowledge directory.

    Returns:
        Path to the surgeon logs directory.
    """
    log_dir = knowledge_path / "facts" / "surgeon_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _log_interaction(
    log_dir: Path,
    stage: str,
    prompt_json: dict[str, Any],
    response: str,
    parsed: dict[str, Any] | None,
) -> None:
    """Log a Surgeon interaction for debugging.

    Args:
        log_dir: Directory to write logs to.
        stage: Pipeline stage name.
        prompt_json: The JSON prompt sent to the agent.
        response: Raw response from the agent.
        parsed: Parsed JSON response (or None if parsing failed).
    """
    log_id = str(uuid.uuid4())[:8]
    log_file = log_dir / f"{log_id}_{stage}.json"
    log_data = {
        "log_id": log_id,
        "stage": stage,
        "prompt": prompt_json,
        "raw_response": response,
        "parsed_response": parsed,
    }
    try:
        log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to write surgeon log: %s", e)


def invoke_sub_agent(
    agent_name: str,
    prompt_json: dict[str, Any],
    model: str = "haiku",
    timeout: int = 120,
    knowledge_path: Path | None = None,
) -> dict[str, Any]:
    """Invoke a Claude sub-agent via subprocess.

    Args:
        agent_name: Name of the sub-agent (e.g., 'fact-surgeon-organizer').
        prompt_json: JSON input to send to the agent.
        model: Model to use (default: 'haiku').
        timeout: Timeout in seconds (default: 120).
        knowledge_path: Base knowledge directory for logging.

    Returns:
        Parsed JSON output from the agent.

    Raises:
        SurgeonError: If invocation fails, times out, or returns invalid JSON.
    """
    if knowledge_path is None:
        knowledge_path = REPO_ROOT / ".knowledge"
    elif not knowledge_path.is_absolute():
        knowledge_path = REPO_ROOT / knowledge_path

    log_dir = _ensure_log_dir(knowledge_path)

    # Build the prompt string from JSON
    prompt_str = json.dumps(prompt_json, indent=2)

    try:
        result = subprocess.run(
            [  # noqa: S607 - trusted executable from project tooling
                "claude",
                "--agent",
                agent_name,
                "--model",
                model,
                "--print",
                "--prompt",
                prompt_str,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired as e:
        raise SurgeonError(f"Sub-agent {agent_name} timed out after {timeout}s: {e}") from e
    except FileNotFoundError as e:
        raise SurgeonError(f"Claude CLI not found: {e}") from e
    except subprocess.SubprocessError as e:
        raise SurgeonError(f"Sub-agent invocation failed: {e}") from e

    if result.returncode != 0:
        raise SurgeonError(
            f"Sub-agent {agent_name} returned non-zero exit code "
            f"{result.returncode}: {result.stderr}"
        )

    # Parse JSON output from stdout
    stdout = result.stdout.strip()
    if not stdout:
        raise SurgeonError(f"Sub-agent {agent_name} returned empty output")

    # Try to find JSON in the output
    json_start = stdout.find("{")
    json_end = stdout.rfind("}") + 1
    if json_start == -1 or json_end == 0:
        _log_interaction(log_dir, agent_name, prompt_json, stdout, None)
        raise SurgeonError(f"No JSON found in {agent_name} output: {stdout[:200]}")

    json_str = stdout[json_start:json_end]

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        _log_interaction(log_dir, agent_name, prompt_json, stdout, None)
        raise SurgeonError(f"Invalid JSON in {agent_name} output: {e}") from e

    _log_interaction(log_dir, agent_name, prompt_json, stdout, parsed)
    return parsed


class ValidationResult(TypedDict):
    """Result from Qwen3 validation.

    Attributes:
        score_drop: Target removal score (sim(fact,orig) - sim(fact,new)).
        target_passed: Whether target was sufficiently removed.
        anchor_similarity: Similarity between orig and new spans for anchor preservation.
        anchor_passed: Whether anchors were sufficiently preserved.
        over_removal_detected: Whether significant over-removal was detected.
        needs_review: Whether this rewrite should be sent to Reviewer.
    """

    score_drop: float
    target_passed: bool
    anchor_similarity: float
    anchor_passed: bool
    over_removal_detected: bool
    needs_review: bool


def validate_removal_qwen3(
    fact_text: str,
    orig_span: str,
    new_span: str,
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
    threshold: float = 0.2,
    anchor_texts: list[str] | None = None,
    anchor_threshold: float = 0.7,
) -> tuple[float, bool]:
    """Validate fact removal using Qwen3 embeddings.

    Computes the similarity drop between the fact and the original/new spans.
    A sufficient drop indicates the fact was successfully removed.

    Args:
        fact_text: The fact that should have been removed.
        orig_span: Original span text before rewrite.
        new_span: New span text after rewrite.
        model: Loaded Qwen embedding model.
        tokenizer: Loaded Qwen tokenizer.
        threshold: Minimum score drop required (default: 0.2).
        anchor_texts: Optional list of anchor texts to check for preservation.
        anchor_threshold: Minimum similarity to retain for anchors (default: 0.7).

    Returns:
        Tuple of (score_drop, passed) where:
        - score_drop: cosine_sim(fact, orig) - cosine_sim(fact, new)
        - passed: whether score_drop >= threshold
    """
    # Handle empty new span (deletion case)
    if not new_span or not new_span.strip():
        # If span was deleted, fact is definitely removed
        return 1.0, True

    # Embed all three texts
    texts = [fact_text, orig_span, new_span]
    embeddings = embed_keywords(texts, model, tokenizer, batch_size=3)

    # Compute cosine similarities
    similarity_matrix = compute_cosine_similarity(embeddings)

    # similarity_matrix[0, 1] = sim(fact, orig)
    # similarity_matrix[0, 2] = sim(fact, new)
    sim_orig = float(similarity_matrix[0, 1])
    sim_new = float(similarity_matrix[0, 2])

    score_drop = sim_orig - sim_new
    passed = score_drop >= threshold

    return score_drop, passed


def validate_removal_with_anchors(
    fact_text: str,
    orig_span: str,
    new_span: str,
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
    anchor_texts: list[str] | None = None,
    target_threshold: float = 0.2,
    anchor_threshold: float = 0.7,
) -> ValidationResult:
    """Validate fact removal with anchor preservation check.

    Computes both target removal score and anchor preservation similarity.
    Detects over-removal cases where anchors are not adequately preserved.

    Args:
        fact_text: The fact that should have been removed.
        orig_span: Original span text before rewrite.
        new_span: New span text after rewrite.
        model: Loaded Qwen embedding model.
        tokenizer: Loaded Qwen tokenizer.
        anchor_texts: Optional list of anchor texts to check for preservation.
        target_threshold: Minimum score drop for target removal (default: 0.2).
        anchor_threshold: Minimum similarity for anchor preservation (default: 0.7).

    Returns:
        ValidationResult with detailed validation metrics.
    """
    # Handle empty new span (deletion case)
    if not new_span or not new_span.strip():
        return ValidationResult(
            score_drop=1.0,
            target_passed=True,
            anchor_similarity=0.0,
            anchor_passed=False,  # Full deletion doesn't preserve anchors
            over_removal_detected=True,
            needs_review=True,
        )

    # Embed fact, orig, and new
    texts = [fact_text, orig_span, new_span]
    embeddings = embed_keywords(texts, model, tokenizer, batch_size=3)

    # Compute cosine similarities
    similarity_matrix = compute_cosine_similarity(embeddings)

    # Target removal: sim(fact, orig) - sim(fact, new)
    sim_fact_orig = float(similarity_matrix[0, 1])
    sim_fact_new = float(similarity_matrix[0, 2])
    score_drop = sim_fact_orig - sim_fact_new
    target_passed = score_drop >= target_threshold

    # Anchor preservation: sim(orig, new) should remain high
    sim_orig_new = float(similarity_matrix[1, 2])
    anchor_passed = sim_orig_new >= anchor_threshold

    # Over-removal detection: high score_drop but low anchor preservation
    over_removal_detected = target_passed and not anchor_passed

    # Also check explicit anchor texts if provided
    if anchor_texts and anchor_passed:
        anchor_embeddings = embed_keywords(
            [*anchor_texts, new_span], model, tokenizer, batch_size=len(anchor_texts) + 1
        )
        anchor_sim_matrix = compute_cosine_similarity(anchor_embeddings)

        # Check each anchor's similarity to new span
        for i in range(len(anchor_texts)):
            anchor_to_new_sim = float(anchor_sim_matrix[i, len(anchor_texts)])
            if anchor_to_new_sim < anchor_threshold:
                anchor_passed = False
                over_removal_detected = True
                break

    # Determine if review is needed
    # Review needed if: target not passed, OR over-removal detected
    needs_review = not target_passed or over_removal_detected

    return ValidationResult(
        score_drop=score_drop,
        target_passed=target_passed,
        anchor_similarity=sim_orig_new,
        anchor_passed=anchor_passed,
        over_removal_detected=over_removal_detected,
        needs_review=needs_review,
    )


def _get_spans_by_ids(
    spans: list[SpanInput],
    span_ids: list[str],
) -> list[dict[str, str]]:
    """Get span objects by their IDs.

    Args:
        spans: List of all spans.
        span_ids: IDs of spans to retrieve.

    Returns:
        List of span dicts with span_id and original_text.
    """
    span_map = {s["span_id"]: s for s in spans}
    return [
        {"span_id": sid, "original_text": span_map[sid]["original_text"]}
        for sid in span_ids
        if sid in span_map
    ]


def orchestrate_surgeon_pipeline(
    spans: list[SpanInput],
    target_facts: list[str],
    anchor_facts: list[str],
    artifact_id: str,
    qwen_model: PreTrainedModel,
    qwen_tokenizer: PreTrainedTokenizer,
    knowledge_path: Path | None = None,
    validation_threshold: float = 0.2,
) -> list[RewriteResult]:
    """Orchestrate the full Surgeon pipeline for rewriting spans.

    Pipeline stages:
    1. Organizer: Group spans by overlaps/related facts
    2. For each group:
       a. Planner: Plan rewrite strategy
       b. Rewriter: Execute rewrite
       c. Qwen3 Validator: Validate semantic removal
       d. Reviewer: Review if validation failed
    3. If any stage fails, retain original span (monotonic safety)

    Args:
        spans: List of spans to potentially rewrite.
        target_facts: Facts to remove from spans.
        anchor_facts: Facts to preserve in spans.
        artifact_id: ID of the artifact being processed.
        qwen_model: Loaded Qwen model for validation.
        qwen_tokenizer: Loaded Qwen tokenizer.
        knowledge_path: Base knowledge directory.
        validation_threshold: Minimum score_drop for validation (default: 0.2).

    Returns:
        List of RewriteResult for each span.
    """
    if knowledge_path is None:
        knowledge_path = REPO_ROOT / ".knowledge"
    elif not knowledge_path.is_absolute():
        knowledge_path = REPO_ROOT / knowledge_path

    results: list[RewriteResult] = []
    span_map = {s["span_id"]: s for s in spans}

    # Stage 1: Organizer - Group spans
    try:
        organizer_input = {
            "spans": [
                {
                    "span_id": s["span_id"],
                    "original_text": s["original_text"],
                    "target_facts": s.get("target_facts", target_facts),
                    "anchor_facts": s.get("anchor_facts", anchor_facts),
                }
                for s in spans
            ],
            "artifact_id": artifact_id,
        }
        organizer_output = invoke_sub_agent(
            "fact-surgeon-organizer",
            organizer_input,
            knowledge_path=knowledge_path,
        )
        groups: list[GroupResult] = organizer_output.get("groups", [])
    except SurgeonError as e:
        logger.warning("Organizer failed, retaining all original spans: %s", e)
        # Return all spans unchanged
        return [
            RewriteResult(
                span_id=s["span_id"],
                replacement_text=s["original_text"],
                validation={"error": str(e)},
                review=None,
                success=False,
            )
            for s in spans
        ]

    if not groups:
        # No groups formed - no rewrites needed
        return [
            RewriteResult(
                span_id=s["span_id"],
                replacement_text=s["original_text"],
                validation={"reason": "no_groups_formed"},
                review=None,
                success=True,
            )
            for s in spans
        ]

    # Process each group
    processed_span_ids: set[str] = set()

    for group in groups:
        group_id = group.get("group_id", str(uuid.uuid4())[:8])
        span_ids = group.get("span_ids", [])
        anchors = group.get("anchors_to_keep", anchor_facts)
        targets = group.get("targets_to_remove", target_facts)

        group_spans = _get_spans_by_ids(spans, span_ids)

        if not group_spans:
            continue

        # Stage 2: Planner - Plan rewrite
        try:
            planner_input = {
                "group_id": group_id,
                "spans": group_spans,
                "anchors_to_keep": anchors,
                "targets_to_remove": targets,
            }
            planner_output = invoke_sub_agent(
                "fact-surgeon-planner",
                planner_input,
                knowledge_path=knowledge_path,
            )
            plan = planner_output.get("plan", {})
        except SurgeonError as e:
            logger.warning("Planner failed for group %s: %s", group_id, e)
            # Retain original spans for this group
            for sid in span_ids:
                if sid in span_map:
                    results.append(
                        RewriteResult(
                            span_id=sid,
                            replacement_text=span_map[sid]["original_text"],
                            validation={"error": f"Planner failed: {e}"},
                            review=None,
                            success=False,
                        )
                    )
                    processed_span_ids.add(sid)
            continue

        # Stage 3: Rewriter - Execute rewrite
        try:
            rewriter_input = {
                "group_id": group_id,
                "plan": plan,
                "spans": group_spans,
            }
            rewriter_output = invoke_sub_agent(
                "fact-surgeon-rewriter",
                rewriter_input,
                knowledge_path=knowledge_path,
            )
            rewrites = rewriter_output.get("rewrites", [])
            self_check = rewriter_output.get("self_check", {})
        except SurgeonError as e:
            logger.warning("Rewriter failed for group %s: %s", group_id, e)
            # Retain original spans for this group
            for sid in span_ids:
                if sid in span_map:
                    results.append(
                        RewriteResult(
                            span_id=sid,
                            replacement_text=span_map[sid]["original_text"],
                            validation={"error": f"Rewriter failed: {e}"},
                            review=None,
                            success=False,
                        )
                    )
                    processed_span_ids.add(sid)
            continue

        # Stage 4: Qwen3 Validator - Validate each rewrite with anchor preservation
        for rewrite in rewrites:
            sid = rewrite.get("span_id", "")
            replacement = rewrite.get("replacement_text", "")

            if sid not in span_map:
                continue

            original = span_map[sid]["original_text"]
            span_targets = span_map[sid].get("target_facts", targets)
            span_anchors = span_map[sid].get("anchor_facts", anchors)

            # Validate removal for each target fact with anchor preservation check
            all_passed = True
            needs_review = False
            min_score_drop = float("inf")
            max_anchor_similarity = 0.0
            any_over_removal = False

            for target_fact in span_targets:
                validation = validate_removal_with_anchors(
                    target_fact,
                    original,
                    replacement,
                    qwen_model,
                    qwen_tokenizer,
                    anchor_texts=span_anchors,
                    target_threshold=validation_threshold,
                    anchor_threshold=0.7,
                )
                min_score_drop = min(min_score_drop, validation["score_drop"])
                max_anchor_similarity = max(max_anchor_similarity, validation["anchor_similarity"])

                if not validation["target_passed"]:
                    all_passed = False
                if validation["over_removal_detected"]:
                    any_over_removal = True
                if validation["needs_review"]:
                    needs_review = True

            validation_result = {
                "score_drop": min_score_drop if min_score_drop != float("inf") else 0.0,
                "passed": all_passed,
                "anchor_similarity": max_anchor_similarity,
                "anchor_passed": not any_over_removal,
                "over_removal_detected": any_over_removal,
                "threshold": validation_threshold,
                "self_check": self_check,
            }

            # Stage 5: Reviewer - Review if validation failed OR over-removal detected
            review_result = None
            final_success = all_passed and not any_over_removal

            if needs_review:
                try:
                    reviewer_input = {
                        "group_id": group_id,
                        "original_spans": [{"span_id": sid, "text": original}],
                        "rewrites": [{"span_id": sid, "replacement_text": replacement}],
                        "plan": plan,
                        "validation": validation_result,
                        "over_removal_detected": any_over_removal,
                    }
                    review_output = invoke_sub_agent(
                        "fact-surgeon-reviewer",
                        reviewer_input,
                        knowledge_path=knowledge_path,
                    )
                    review_result = review_output
                    decision = review_output.get("decision", "reject")

                    if decision == "approve":
                        final_success = True
                    elif decision in ("reject", "iterate"):
                        # Retain original span on reject or iterate
                        replacement = original
                        final_success = False
                except SurgeonError as e:
                    logger.warning("Reviewer failed for span %s: %s", sid, e)
                    # Retain original on reviewer failure
                    replacement = original
                    final_success = False

            results.append(
                RewriteResult(
                    span_id=sid,
                    replacement_text=replacement,
                    validation=validation_result,
                    review=review_result,
                    success=final_success,
                )
            )
            processed_span_ids.add(sid)

    # Add any unprocessed spans (not in any group)
    for span in spans:
        if span["span_id"] not in processed_span_ids:
            results.append(
                RewriteResult(
                    span_id=span["span_id"],
                    replacement_text=span["original_text"],
                    validation={"reason": "not_in_any_group"},
                    review=None,
                    success=True,
                )
            )

    return results


def orchestrate_surgeon_pipeline_mock(
    spans: list[SpanInput],
    target_facts: list[str],
    anchor_facts: list[str],
    artifact_id: str,
) -> list[RewriteResult]:
    """Mock Surgeon pipeline for testing without sub-agents.

    Performs simple string-based fact removal for testing purposes.

    Args:
        spans: List of spans to potentially rewrite.
        target_facts: Facts to remove from spans.
        anchor_facts: Facts to preserve in spans.
        artifact_id: ID of the artifact being processed.

    Returns:
        List of mock RewriteResult for each span.
    """
    results: list[RewriteResult] = []

    for span in spans:
        original = span["original_text"]
        replacement = original

        # Simple heuristic: remove sentences containing target keywords
        span_targets = span.get("target_facts", target_facts)
        for target in span_targets:
            # Extract key terms from target fact
            keywords = [w for w in target.split() if len(w) > 3]
            for keyword in keywords:
                if keyword.lower() in replacement.lower():
                    # Try to remove the sentence containing the keyword
                    sentences = replacement.split(".")
                    new_sentences = [s for s in sentences if keyword.lower() not in s.lower()]
                    replacement = ".".join(new_sentences)
                    if replacement and not replacement.endswith("."):
                        replacement += "."

        # Clean up
        replacement = replacement.strip()
        if replacement == ".":
            replacement = ""

        results.append(
            RewriteResult(
                span_id=span["span_id"],
                replacement_text=replacement,
                validation={"mock": True, "score_drop": 0.5, "passed": True},
                review=None,
                success=True,
            )
        )

    return results


# --- Individual Stage Functions (for testing and direct invocation) ---


class OrganizerOutput(TypedDict):
    """Output from the Organizer stage.

    Attributes:
        groups: List of span groups with their associated facts.
    """

    groups: list[GroupResult]


class PlannerOutput(TypedDict):
    """Output from the Planner stage.

    Attributes:
        plans: List of rewrite plans for each group.
    """

    plans: list[dict[str, Any]]


class RewriterOutput(TypedDict):
    """Output from the Rewriter stage.

    Attributes:
        rewritten_text: The rewritten span text.
        self_check: Self-check results from the rewriter.
        confidence: Confidence score for the rewrite.
    """

    rewritten_text: str
    self_check: dict[str, bool]
    confidence: float


class ReviewerOutput(TypedDict):
    """Output from the Reviewer stage.

    Attributes:
        decision: Decision on the rewrite (approve, reject, iterate).
        reason: Reason for the decision.
        suggested_fix: Optional suggested fix for rejected/iterate cases.
    """

    decision: str
    reason: str
    suggested_fix: str | None


class SurgeonResult(TypedDict):
    """Result from a single span surgery operation.

    Attributes:
        span_id: ID of the span that was processed.
        original_text: Original span text.
        rewritten_text: Rewritten span text.
        facts_removed: List of facts that were removed.
        score_drop: Validation score drop.
        status: Status of the surgery (success, failure).
        failure_reason: Reason for failure if applicable.
    """

    span_id: str
    original_text: str
    rewritten_text: str
    facts_removed: list[str]
    score_drop: float
    status: str
    failure_reason: str


def compute_score_drop(
    fact_text: str,
    original_text: str,
    rewritten_text: str,
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
) -> float:
    """Compute the score drop for a fact removal.

    The score drop measures how much less similar the rewritten text is
    to the fact compared to the original text.

    Args:
        fact_text: The fact that should have been removed.
        original_text: Original text before rewrite.
        rewritten_text: Text after rewrite.
        model: Loaded embedding model.
        tokenizer: Loaded tokenizer.

    Returns:
        Score drop value (sim(fact, original) - sim(fact, rewritten)).
    """
    # Handle empty rewritten text
    if not rewritten_text or not rewritten_text.strip():
        return 1.0

    # Embed all three texts
    texts = [fact_text, original_text, rewritten_text]
    embeddings = embed_keywords(texts, model, tokenizer, batch_size=3)

    # Compute cosine similarities
    similarity_matrix = compute_cosine_similarity(embeddings)

    # score_drop = sim(fact, original) - sim(fact, rewritten)
    sim_orig = float(similarity_matrix[0, 1])
    sim_new = float(similarity_matrix[0, 2])

    return sim_orig - sim_new


def organize_spans(
    spans: list[dict[str, Any]],
    knowledge_path: Path | None = None,
) -> OrganizerOutput:
    """Organize spans into groups for rewriting.

    Invokes the fact-surgeon-organizer sub-agent to group spans by
    overlapping facts and related entities.

    Args:
        spans: List of spans with their target/anchor facts.
        knowledge_path: Base knowledge directory for logging.

    Returns:
        OrganizerOutput with grouped spans.
    """
    organizer_input = {"spans": spans}
    result = invoke_sub_agent(
        "fact-surgeon-organizer",
        organizer_input,
        knowledge_path=knowledge_path,
    )
    return OrganizerOutput(groups=result.get("groups", []))


def plan_rewrites(
    groups: list[GroupResult],
    knowledge_path: Path | None = None,
) -> PlannerOutput:
    """Plan rewrites for each group of spans.

    Invokes the fact-surgeon-planner sub-agent to create rewrite plans.

    Args:
        groups: List of span groups from the organizer.
        knowledge_path: Base knowledge directory for logging.

    Returns:
        PlannerOutput with rewrite plans.
    """
    planner_input = {"groups": groups}
    result = invoke_sub_agent(
        "fact-surgeon-planner",
        planner_input,
        knowledge_path=knowledge_path,
    )
    return PlannerOutput(plans=result.get("plans", []))


def rewrite_span(
    plan: dict[str, Any],
    span_text: str,
    anchors: list[str],
    targets: list[str],
    knowledge_path: Path | None = None,
) -> RewriterOutput:
    """Rewrite a span according to the plan.

    Invokes the fact-surgeon-rewriter sub-agent to execute the rewrite.

    Args:
        plan: Rewrite plan for this span.
        span_text: Original span text.
        anchors: Anchor facts to preserve.
        targets: Target facts to remove.
        knowledge_path: Base knowledge directory for logging.

    Returns:
        RewriterOutput with the rewritten text and self-check.
    """
    rewriter_input = {
        "plan": plan,
        "span_text": span_text,
        "anchors_to_keep": anchors,
        "targets_to_remove": targets,
    }
    result = invoke_sub_agent(
        "fact-surgeon-rewriter",
        rewriter_input,
        knowledge_path=knowledge_path,
    )
    return RewriterOutput(
        rewritten_text=result.get("rewritten_text", span_text),
        self_check=result.get("self_check", {}),
        confidence=result.get("confidence", 0.0),
    )


def review_rewrite(
    original_text: str,
    rewritten_text: str,
    removed_facts: list[str],
    score_drop: float,
    knowledge_path: Path | None = None,
) -> ReviewerOutput:
    """Review a rewrite and decide on its acceptance.

    Invokes the fact-surgeon-reviewer sub-agent to review the rewrite.

    Args:
        original_text: Original span text.
        rewritten_text: Rewritten span text.
        removed_facts: Facts that were supposed to be removed.
        score_drop: Validation score drop.
        knowledge_path: Base knowledge directory for logging.

    Returns:
        ReviewerOutput with the review decision.
    """
    reviewer_input = {
        "original_text": original_text,
        "rewritten_text": rewritten_text,
        "removed_facts": removed_facts,
        "score_drop": score_drop,
    }
    result = invoke_sub_agent(
        "fact-surgeon-reviewer",
        reviewer_input,
        knowledge_path=knowledge_path,
    )
    return ReviewerOutput(
        decision=result.get("decision", "reject"),
        reason=result.get("reason", ""),
        suggested_fix=result.get("suggested_fix"),
    )
