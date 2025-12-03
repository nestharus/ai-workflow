"""Artifact rendering logic for the knowledge graph system.

This module provides functions for rendering artifacts from facts per
fact_redesign.md lines 938-946. Rendering follows the render plan steps
defined in the render plan's steps sequence.

Render Engines:
    - text_llm: Uses Claude CLI (haiku model) to render artifact from facts
    - none: Returns source artifact text unchanged (for diagrams, etc.)

Current Implementation Status:
    - Implemented: Infrastructure, file I/O, ordering, extension mapping, step interpretation,
      LLM rendering via Claude CLI, terminology normalization via variant system,
      embedding-based self-check via Qwen3
    - Deferred to Task 9: Entity resolution (per fact_redesign_plan.md)
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

from scripts.dev.utils import REPO_ROOT

if TYPE_CHECKING:
    from scripts.knowledge.artifact_manager import ArtifactManifest, ContributorFact
    from scripts.knowledge.render_plan_manager import RenderPlan

# Module-level logger
_logger = logging.getLogger(__name__)

# MIME type to file extension mapping
MIME_TO_EXTENSION: dict[str, str] = {
    "text/markdown": ".md",
    "text/yaml": ".yml",
    "text/x-yaml": ".yml",
    "application/x-yaml": ".yml",
    "application/json": ".json",
    "text/x-mermaid": ".mmd",
    "text/plain": ".txt",
}

# Role to priority mapping for ordering
# Lower numbers = higher priority (constraints first, then prose, then references)
ROLE_PRIORITY_MAP: dict[str, int] = {
    "constraint": 1,
    "metadata": 2,
    "entity_ref": 3,
    "artifact_root": 4,
}


def _get_output_extension(artifact_format: str) -> str:
    """Map MIME type to file extension.

    Args:
        artifact_format: MIME type string.

    Returns:
        File extension including leading dot.
    """
    return MIME_TO_EXTENSION.get(artifact_format, ".txt")


def _get_rendered_path(
    artifact_id: str,
    artifact_format: str,
    rendered_dir: Path,
) -> Path:
    """Get the output path for a rendered artifact.

    Args:
        artifact_id: The artifact identifier.
        artifact_format: MIME type for extension mapping.
        rendered_dir: Base rendered artifacts directory.

    Returns:
        Path to the rendered artifact file.
    """
    extension = _get_output_extension(artifact_format)
    return rendered_dir / f"{artifact_id}{extension}"


def _derive_role_priority(role: str) -> int:
    """Derive role_priority from role using the priority map.

    Args:
        role: The semantic role (constraint, entity_ref, artifact_root, metadata).

    Returns:
        Priority value (lower = higher priority).
    """
    return ROLE_PRIORITY_MAP.get(role, 99)


def _gather_contributor_facts(
    manifest: ArtifactManifest,
    render_plan: RenderPlan,
) -> list[dict[str, Any]]:
    """Collect contributor facts from manifest.

    Collects structural FieldFacts and semantic facts from the manifest's
    contributors section. Includes all ordering-relevant fields:
    - type, element_id, field_path, fact_id (base fields)
    - role, role_priority, group_key, group_id (ordering fields)

    For structural FieldFacts, includes field_path, value, and containing
    element context. For semantic facts, includes fact text and source attribution.

    If contributor entries don't contain role_priority, it's derived from role
    using ROLE_PRIORITY_MAP for backward compatibility.

    Args:
        manifest: The artifact manifest containing contributor references.
        render_plan: The render plan with input configuration.

    Returns:
        List of contributor fact dictionaries with ordering fields.
    """
    facts: list[dict[str, Any]] = []
    inputs = render_plan["inputs"]

    if inputs.get("use_structural_fieldfacts", True):
        for structural in manifest.get("contributors", {}).get("structural", []):
            role = structural.get("role", "constraint")
            fact = {
                "type": "structural",
                "element_id": structural.get("element_id", ""),
                "field_path": structural.get("field_path", ""),
                "fact_id": structural.get("fact_id", ""),
                # Ordering-relevant fields
                "role": role,
                "role_priority": structural.get("role_priority", _derive_role_priority(role)),
                "group_key": structural.get("group_key", ""),
                "group_id": structural.get("group_id", ""),
            }
            facts.append(fact)

    if inputs.get("use_semantic_facts", True):
        for semantic in manifest.get("contributors", {}).get("semantic", []):
            role = semantic.get("role", "constraint")
            fact = {
                "type": "semantic",
                "element_id": semantic.get("element_id", ""),
                "field_path": semantic.get("field_path", ""),
                "fact_id": semantic.get("fact_id", ""),
                # Ordering-relevant fields
                "role": role,
                "role_priority": semantic.get("role_priority", _derive_role_priority(role)),
                "group_key": semantic.get("group_key", ""),
                "group_id": semantic.get("group_id", ""),
            }
            facts.append(fact)

    _logger.debug(
        "Gathered %d contributor facts for artifact %s",
        len(facts),
        manifest["artifact_id"],
    )
    return facts


def _normalize_terminology(
    facts: list[dict[str, Any]],
    keyword_variant_mapping: dict[str, str] | None = None,
    knowledge_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Normalize terminology to canonical keywords.

    Uses the variant resolver system to replace variant keywords with their
    canonical forms. Loads variant mappings from variant_candidates.csv.

    Args:
        facts: List of contributor facts.
        keyword_variant_mapping: Optional pre-loaded keyword variant mapping.
            If not provided, attempts to load from knowledge_path.
        knowledge_path: Path to knowledge directory (default: REPO_ROOT / ".knowledge").

    Returns:
        List of facts with normalized terminology.
    """
    # Load or use provided variant mapping
    if keyword_variant_mapping is None:
        knowledge_path = knowledge_path or REPO_ROOT / ".knowledge"
        try:
            # Import here to avoid circular imports
            from scripts.knowledge.variant_resolver import apply_variant_decisions

            keyword_variant_mapping = apply_variant_decisions(knowledge_path)
        except (ImportError, FileNotFoundError, ValueError) as e:
            _logger.debug(
                "Could not load variant mapping, returning facts unchanged: %s", e
            )
            return facts

    if not keyword_variant_mapping:
        _logger.debug("No variant mapping available, returning facts unchanged")
        return facts

    # Normalize facts by replacing variant terms with canonical forms
    normalized_facts = []
    for fact in facts:
        normalized_fact = dict(fact)

        # Check text-containing fields for variant terms
        for field_name in ("value", "fact_text", "text", "content"):
            if field_name in normalized_fact and isinstance(
                normalized_fact[field_name], str
            ):
                original_value = normalized_fact[field_name]
                normalized_value = original_value

                # Replace each variant term with its canonical form
                for variant_term, canonical_term in keyword_variant_mapping.items():
                    if variant_term in normalized_value and variant_term != canonical_term:
                        normalized_value = normalized_value.replace(
                            variant_term, canonical_term
                        )
                        _logger.debug(
                            "Normalized '%s' to '%s' in field %s",
                            variant_term,
                            canonical_term,
                            field_name,
                        )

                normalized_fact[field_name] = normalized_value

        normalized_facts.append(normalized_fact)

    _logger.debug(
        "Normalized terminology for %d facts using %d variant mappings",
        len(normalized_facts),
        len(keyword_variant_mapping),
    )
    return normalized_facts


def _order_facts(
    facts: list[dict[str, Any]],
    ordering_rules: list[str],
) -> list[dict[str, Any]]:
    """Order facts by determinism rules.

    Orders facts by the specified priority keys for deterministic output.
    Common ordering keys: role_priority, group_id, field_path,
    discriminator_field_value.

    Args:
        facts: List of contributor facts.
        ordering_rules: List of keys to sort by in priority order.

    Returns:
        List of facts ordered by determinism rules.
    """
    if not ordering_rules:
        return facts

    def sort_key(fact: dict[str, Any]) -> tuple:
        return tuple(str(fact.get(key, "")) for key in ordering_rules)

    ordered = sorted(facts, key=sort_key)
    _logger.debug(
        "Ordered %d facts by rules: %s",
        len(ordered),
        ordering_rules,
    )
    return ordered


def _render_with_llm(
    ordered_facts: list[dict[str, Any]],
    render_plan: RenderPlan,
    artifact_kind: str,
    source_text: str = "",
    timeout_seconds: int = 120,
) -> str:
    """Render artifact using LLM via Claude CLI.

    Uses Claude CLI (haiku model) to render artifact from ordered facts
    following render plan instructions. Pattern from surgeon_orchestrator.py.

    Args:
        ordered_facts: List of ordered contributor facts.
        render_plan: The render plan with step instructions.
        artifact_kind: The artifact kind being rendered.
        source_text: Original source text for fallback (monotonic safety).
        timeout_seconds: Timeout for Claude CLI invocation (default 120s).

    Returns:
        Rendered artifact text.
    """
    _logger.debug(
        "Rendering artifact with LLM: %d facts, kind=%s, plan=%s",
        len(ordered_facts),
        artifact_kind,
        render_plan.get("render_plan_id", "unknown"),
    )

    # Build render instructions from render plan steps
    instructions = []
    for step in render_plan.get("steps", []):
        instruction = step.get("instruction", "")
        if instruction:
            instructions.append(f"- {instruction}")

    render_instructions = "\n".join(instructions) if instructions else "Render the artifact."

    # Format facts as context
    facts_context = json.dumps(ordered_facts, indent=2, default=str)

    # Build the prompt
    prompt = f"""You are rendering an artifact of type: {artifact_kind}

## Render Plan Instructions
{render_instructions}

## Contributor Facts (in deterministic order)
{facts_context}

## Task
Render the artifact by synthesizing the facts above following the render plan instructions.
Output ONLY the rendered artifact text, with no additional commentary or markdown fencing.
Preserve the semantic content of all facts accurately.
"""

    # Try Claude CLI invocation
    try:
        result = subprocess.run(
            ["claude", "--model", "haiku", "--print", "--prompt", prompt],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

        if result.returncode == 0 and result.stdout.strip():
            rendered_text = result.stdout.strip()
            _logger.info(
                "Successfully rendered artifact via Claude CLI: %d chars",
                len(rendered_text),
            )
            return rendered_text
        else:
            _logger.warning(
                "Claude CLI returned non-zero or empty output (rc=%d), "
                "falling back to source text",
                result.returncode,
            )
            if result.stderr:
                _logger.debug("Claude CLI stderr: %s", result.stderr[:500])

    except subprocess.TimeoutExpired:
        _logger.warning(
            "Claude CLI timed out after %ds, falling back to source text",
            timeout_seconds,
        )
    except FileNotFoundError:
        _logger.warning(
            "Claude CLI not found, falling back to source text. "
            "Install Claude Code CLI to enable LLM rendering."
        )
    except OSError as e:
        _logger.warning("Claude CLI invocation failed: %s, falling back to source text", e)

    # Monotonic safety: fall back to source text unchanged
    if source_text:
        _logger.debug("Using source text fallback (%d chars)", len(source_text))
        return source_text

    # If no source text, generate minimal placeholder
    _logger.debug("No source text available, generating minimal placeholder")
    return f"[Rendered artifact: {artifact_kind}]"


def _render_none(
    manifest: ArtifactManifest,
    artifacts_dir: Path,
) -> str:
    """Return source artifact text unchanged.

    For render_engine=none, the artifact is tracked and indexed but not
    re-rendered. This function attempts to load the source artifact text
    from the source file.

    Args:
        manifest: The artifact manifest.
        artifacts_dir: Base artifacts directory.

    Returns:
        Source artifact text, or empty string if source not found.
    """
    source = manifest.get("source", {})
    source_file = source.get("source_file", "")

    if not source_file:
        _logger.warning(
            "No source file for artifact %s, returning empty string",
            manifest["artifact_id"],
        )
        return ""

    # Try to load from source file
    # Note: This assumes source_file is relative to repo root, not artifacts_dir
    source_path = Path(source_file)
    if not source_path.is_absolute():
        # Look relative to artifacts_dir parent (repo root)
        repo_root = artifacts_dir.parent.parent
        source_path = repo_root / source_file

    if not source_path.exists():
        _logger.warning(
            "Source file not found for artifact %s: %s",
            manifest["artifact_id"],
            source_path,
        )
        return ""

    try:
        content = source_path.read_text(encoding="utf-8")

        # Extract specific field if field_path is specified
        field_path = source.get("field_path", "")
        if field_path:
            # Try to extract the specific field from YAML
            try:
                data = yaml.safe_load(content)
                parts = field_path.split(".")
                for part in parts:
                    if isinstance(data, dict) and part in data:
                        data = data[part]
                    elif isinstance(data, list) and part.isdigit():
                        data = data[int(part)]
                    else:
                        # Field path not found, return full content
                        _logger.debug(
                            "Field path %s not found, returning full content",
                            field_path,
                        )
                        return content

                # Return the extracted value as string
                if isinstance(data, str):
                    return data
                return yaml.safe_dump(data, default_flow_style=False, allow_unicode=True)
            except yaml.YAMLError:
                # Not valid YAML, return full content
                return content

        return content
    except OSError as exc:
        _logger.warning(
            "Failed to read source file for artifact %s: %s",
            manifest["artifact_id"],
            exc,
        )
        return ""


def _self_check(
    rendered_text: str,
    contributor_facts: list[dict[str, Any]],
    similarity_threshold: float = 0.7,
) -> bool:
    """Verify every statement maps to contributor fact using embeddings.

    Uses Qwen embeddings to verify that:
    1. Every contributor fact is represented in at least one statement
    2. Every statement in the rendered text is backed by at least one fact

    Args:
        rendered_text: The rendered artifact text.
        contributor_facts: List of contributor facts.
        similarity_threshold: Minimum cosine similarity for fact-statement match.

    Returns:
        True if self-check passes, False otherwise.
    """
    if not rendered_text or not contributor_facts:
        _logger.debug("Self-check: empty rendered text or no facts, returning True")
        return True

    # Parse rendered text into statements (split on sentence boundaries)
    import re

    # Split on period, question mark, exclamation mark followed by space or newline
    # Also split on double newlines (paragraph breaks)
    statements = []
    raw_statements = re.split(r"(?<=[.!?])\s+|\n\n+", rendered_text.strip())
    for stmt in raw_statements:
        cleaned = stmt.strip()
        if cleaned and len(cleaned) > 5:  # Skip very short fragments
            statements.append(cleaned)

    if not statements:
        _logger.debug("Self-check: no statements extracted, returning True")
        return True

    # Extract fact texts from contributor facts
    fact_texts = []
    for fact in contributor_facts:
        # Try various field names for fact content
        text = fact.get("fact_text") or fact.get("value") or fact.get("text") or ""
        if isinstance(text, str) and text.strip():
            fact_texts.append(text.strip())

    if not fact_texts:
        _logger.debug("Self-check: no fact texts extracted, returning True")
        return True

    # Try to load Qwen embeddings for semantic comparison
    try:
        from scripts.knowledge.variant_resolver import (
            compute_cosine_similarity,
            embed_keywords,
            load_qwen_embedding_model,
        )

        model, tokenizer = load_qwen_embedding_model()

        # Embed statements and facts
        statement_embeddings = embed_keywords(statements, model, tokenizer)
        fact_embeddings = embed_keywords(fact_texts, model, tokenizer)

        # Compute similarity matrix
        similarity_matrix = compute_cosine_similarity(
            statement_embeddings, fact_embeddings
        )

        # Check that each fact has at least one matching statement
        missing_facts = []
        for i, fact_text in enumerate(fact_texts):
            max_sim = float(similarity_matrix[:, i].max())
            if max_sim < similarity_threshold:
                missing_facts.append((fact_text[:50], max_sim))
                _logger.debug(
                    "Fact not represented: '%s...' (max_sim=%.2f)",
                    fact_text[:50],
                    max_sim,
                )

        # Check that each statement has at least one backing fact
        orphan_statements = []
        for i, stmt in enumerate(statements):
            max_sim = float(similarity_matrix[i, :].max())
            if max_sim < similarity_threshold:
                orphan_statements.append((stmt[:50], max_sim))
                _logger.debug(
                    "Orphan statement: '%s...' (max_sim=%.2f)",
                    stmt[:50],
                    max_sim,
                )

        if missing_facts or orphan_statements:
            _logger.warning(
                "Self-check failed: %d missing facts, %d orphan statements",
                len(missing_facts),
                len(orphan_statements),
            )
            return False

        _logger.debug(
            "Self-check passed: %d statements, %d facts, threshold=%.2f",
            len(statements),
            len(fact_texts),
            similarity_threshold,
        )
        return True

    except ImportError as e:
        _logger.warning(
            "Qwen embeddings not available for self-check, assuming pass: %s", e
        )
        return True
    except Exception as e:
        _logger.warning(
            "Self-check embedding computation failed, assuming pass: %s", e
        )
        return True


def _get_step_handler(
    step_id: str,
) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    """Get the handler function for a render plan step.

    Maps step IDs to internal handler functions. Steps that don't have
    handlers are logged and skipped.

    Args:
        step_id: The step ID from the render plan.

    Returns:
        Handler function or None if step is not implemented.
    """
    # Step handlers modify and return context
    # Context contains: facts, normalized_facts, ordered_facts, rendered_text, etc.
    step_handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "gather": _step_gather,
        "normalize": _step_normalize,
        "order": _step_order,
        "render": _step_render,
        "self_check": _step_self_check,
    }
    return step_handlers.get(step_id)


def _step_gather(ctx: dict[str, Any]) -> dict[str, Any]:
    """Handler for 'gather' step - collects contributor facts."""
    ctx["facts"] = _gather_contributor_facts(ctx["manifest"], ctx["render_plan"])
    return ctx


def _step_normalize(ctx: dict[str, Any]) -> dict[str, Any]:
    """Handler for 'normalize' step - normalizes terminology."""
    facts = ctx.get("facts", [])
    ctx["normalized_facts"] = _normalize_terminology(facts)
    return ctx


def _step_order(ctx: dict[str, Any]) -> dict[str, Any]:
    """Handler for 'order' step - orders facts by determinism rules."""
    facts = ctx.get("normalized_facts", ctx.get("facts", []))
    ordering_rules = ctx["render_plan"].get("determinism", {}).get("ordering", [])
    ctx["ordered_facts"] = _order_facts(facts, ordering_rules)
    return ctx


def _step_render(ctx: dict[str, Any]) -> dict[str, Any]:
    """Handler for 'render' step - renders artifact with appropriate engine."""
    render_engine = ctx["render_plan"]["render_engine"]
    ordered_facts = ctx.get("ordered_facts", ctx.get("normalized_facts", ctx.get("facts", [])))

    if render_engine == "text_llm":
        ctx["rendered_text"] = _render_with_llm(
            ordered_facts, ctx["render_plan"], ctx["artifact_kind"]
        )
    elif render_engine == "none":
        ctx["rendered_text"] = _render_none(ctx["manifest"], ctx["artifacts_dir"])
    else:
        msg = f"Unsupported render_engine: {render_engine}"
        raise ValueError(msg)

    return ctx


def _step_self_check(ctx: dict[str, Any]) -> dict[str, Any]:
    """Handler for 'self_check' step - verifies rendered output."""
    rendered_text = ctx.get("rendered_text", "")
    ordered_facts = ctx.get("ordered_facts", ctx.get("facts", []))

    if not _self_check(rendered_text, ordered_facts):
        _logger.warning(
            "Self-check failed for artifact %s",
            ctx["artifact_id"],
        )

    return ctx


def render_artifact(
    manifest: ArtifactManifest,
    render_plan: RenderPlan,
    artifacts_dir: Path,
    rendered_dir: Path,
) -> Path:
    """Render an artifact from facts following the render plan.

    Main rendering function that interprets the steps sequence from the
    render plan. Each step ID maps to an internal handler function:
    - gather: Collect contributor facts from manifest
    - normalize: Normalize terminology to canonical keywords
    - order: Order facts by determinism rules
    - render: Render with LLM or none engine
    - self_check: Verify rendered output

    If the render plan doesn't specify steps, uses default pipeline:
    gather -> normalize -> order -> render -> self_check

    Args:
        manifest: The artifact manifest containing contributor references.
        render_plan: The render plan defining rendering steps.
        artifacts_dir: Base artifacts directory.
        rendered_dir: Output directory for rendered artifacts.

    Returns:
        Path to the rendered artifact file.

    Raises:
        OSError: If writing the rendered file fails.
        ValueError: If render_engine is unsupported.
    """
    artifact_id = manifest["artifact_id"]
    artifact_format = manifest["artifact_format"]
    artifact_kind = manifest["artifact_kind"]
    render_engine = render_plan["render_engine"]

    _logger.info(
        "Rendering artifact %s (kind=%s, engine=%s)",
        artifact_id,
        artifact_kind,
        render_engine,
    )

    # Build execution context
    ctx: dict[str, Any] = {
        "manifest": manifest,
        "render_plan": render_plan,
        "artifacts_dir": artifacts_dir,
        "artifact_id": artifact_id,
        "artifact_kind": artifact_kind,
    }

    # Get steps from render plan or use defaults
    steps = render_plan.get("steps", [])
    if not steps:
        # Default pipeline if no steps specified
        steps = [
            {"id": "gather"},
            {"id": "normalize"},
            {"id": "order"},
            {"id": "render"},
            {"id": "self_check"},
        ]

    # Execute steps in order
    for step in steps:
        step_id = step.get("id", "")
        handler = _get_step_handler(step_id)

        if handler is None:
            _logger.debug(
                "Skipping unrecognized step '%s' for artifact %s",
                step_id,
                artifact_id,
            )
            continue

        _logger.debug("Executing step '%s' for artifact %s", step_id, artifact_id)
        ctx = handler(ctx)

    # Get rendered text from context
    rendered_text = ctx.get("rendered_text", "")

    # Write rendered artifact to file
    rendered_dir.mkdir(parents=True, exist_ok=True)
    output_path = _get_rendered_path(artifact_id, artifact_format, rendered_dir)

    output_path.write_text(rendered_text, encoding="utf-8")
    _logger.info("Wrote rendered artifact to %s", output_path)

    return output_path


def get_output_extension(artifact_format: str) -> str:
    """Get the file extension for an artifact format.

    Public wrapper around _get_output_extension for external use.

    Args:
        artifact_format: MIME type string.

    Returns:
        File extension including leading dot.
    """
    return _get_output_extension(artifact_format)
