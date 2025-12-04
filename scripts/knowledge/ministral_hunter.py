"""Ministral Hunter module for entity discovery and fact extraction.

This module provides functionality for entity discovery and fact extraction using
the HuggingFace agent runner with the ministral-recognizer agent. It implements
the Hunter role in the multi-agent extraction pipeline as specified in
docs/plans/fact_redesign.md.

The Hunter is optimized for recall over precision, returning minimal spans containing
facts about target entities with explicit termination signals when extraction is complete.

Note:
    This module now delegates model inference to the huggingface_agent_runner via
    subprocess invocation. Direct model loading is no longer required.

Usage:
    # Entity discovery mode
    entities = invoke_hunter(state_text, mode='entities', knowledge_path=knowledge_path)

    # Fact extraction mode
    facts = invoke_hunter(
        state_text, target_entity='create_app', mode='facts', knowledge_path=knowledge_path
    )

Modes:
    - entities: Discover all entities mentioned in the text
    - facts: Extract all explicit facts about a target entity with minimal spans

Output Contract (JSON):
    {
        "mode": "entities" | "facts",
        "entities": [{"mention": str, "type_hint": str, "evidence_span_id": str}],
        "target_entity": {"mention": str, "resolved_id": str},
        "facts": [{"fact_text": str, "evidence_span_id": str, "confidence": float}],
        "spans": [{"span_id": str, "original_text": str}],
        "done": bool,
        "reason": str | null
    }

References:
    - docs/plans/fact_redesign.md lines 572-581, 671-689
"""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from pathlib import Path
from typing import Any, Literal, TypedDict

from scripts.dev.utils import REPO_ROOT

# Configure logging
logger = logging.getLogger(__name__)


class HunterError(Exception):
    """Error raised when the Hunter inference fails."""


class EntityResult(TypedDict):
    """Entity discovered by the Hunter.

    Attributes:
        mention: The entity mention as it appears in text.
        type_hint: Heuristic type hint (e.g., 'FUNCTION', 'CLASS', 'PATH').
        evidence_span_id: ID of the span containing this entity.
    """

    mention: str
    type_hint: str
    evidence_span_id: str


class TargetEntity(TypedDict):
    """Target entity for fact extraction.

    Attributes:
        mention: The entity mention being targeted.
        resolved_id: Resolved entity ID (or mention if not resolved).
    """

    mention: str
    resolved_id: str


class FactResult(TypedDict):
    """Fact extracted by the Hunter.

    Attributes:
        fact_text: The atomic fact about the target entity.
        evidence_span_id: ID of the span containing this fact.
        confidence: Confidence score (0.0-1.0).
    """

    fact_text: str
    evidence_span_id: str
    confidence: float


class SpanResult(TypedDict):
    """Span returned by the Hunter.

    Attributes:
        span_id: Unique identifier for this span.
        original_text: The original text of the span.
    """

    span_id: str
    original_text: str


class HunterOutput(TypedDict):
    """Full output from the Hunter.

    Attributes:
        mode: The mode the Hunter was invoked in ('entities' or 'facts').
        entities: List of discovered entities (entity mode only).
        target_entity: The target entity (fact mode only).
        facts: List of extracted facts (fact mode only).
        spans: List of spans containing evidence.
        done: Whether extraction is complete for this target.
        reason: Explanation for done=true or null if not done.
    """

    mode: Literal["entities", "facts"]
    entities: list[EntityResult]
    target_entity: TargetEntity | None
    facts: list[FactResult]
    spans: list[SpanResult]
    done: bool
    reason: str | None


# Prompt templates
ENTITY_DISCOVERY_PROMPT = """You are an entity discovery agent. Find all entities mentioned in the following text.

An entity is any named thing that could have facts associated with it:
- Functions, classes, methods (e.g., create_app, FastAPI)
- Files and paths (e.g., app/core/factory.py)
- Technical concepts (e.g., API versioning, dependency injection)
- Named patterns or conventions

For each entity found, provide:
- mention: The exact text as it appears
- type_hint: What kind of entity (FUNCTION, CLASS, PATH, CONCEPT, etc.)
- evidence_span_id: A unique ID for the span containing this entity

If no entities are found, set done=true.

Text to analyze:
{state_text}

Respond with valid JSON only:
{{
    "mode": "entities",
    "entities": [
        {{"mention": "...", "type_hint": "...", "evidence_span_id": "..."}}
    ],
    "target_entity": null,
    "facts": [],
    "spans": [
        {{"span_id": "...", "original_text": "..."}}
    ],
    "done": false,
    "reason": null
}}"""

FACT_EXTRACTION_PROMPT = """You are a fact extraction agent. Extract all explicit facts about the entity '{target_entity}' from the following text.

Rules for fact extraction:
1. Extract ONLY facts that are explicitly stated about '{target_entity}'
2. Each fact should be atomic (one piece of information)
3. Include minimal spans - only the text needed to support the fact
4. Be comprehensive - extract ALL facts about this entity
5. If no facts remain about '{target_entity}', set done=true

For each fact, provide:
- fact_text: The atomic fact as a complete sentence
- evidence_span_id: ID of the span containing this fact
- confidence: How confident you are (0.0-1.0)

Text to analyze:
{state_text}

Respond with valid JSON only:
{{
    "mode": "facts",
    "entities": [],
    "target_entity": {{"mention": "{target_entity}", "resolved_id": "{target_entity}"}},
    "facts": [
        {{"fact_text": "...", "evidence_span_id": "...", "confidence": 0.95}}
    ],
    "spans": [
        {{"span_id": "...", "original_text": "..."}}
    ],
    "done": false,
    "reason": null
}}"""


def _ensure_log_dir(knowledge_path: Path) -> Path:
    """Ensure the hunter logs directory exists.

    Args:
        knowledge_path: Base knowledge directory.

    Returns:
        Path to the hunter logs directory.
    """
    log_dir = knowledge_path / "facts" / "hunter_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _log_interaction(
    log_dir: Path,
    prompt: str,
    response: str,
    mode: str,
    target_entity: str | None = None,
) -> None:
    """Log a Hunter interaction for debugging.

    Args:
        log_dir: Directory to write logs to.
        prompt: The prompt sent to the model.
        response: The model's response.
        mode: The mode ('entities' or 'facts').
        target_entity: Target entity (for fact mode).
    """
    log_id = str(uuid.uuid4())[:8]
    log_file = log_dir / f"{log_id}_{mode}.json"
    log_data = {
        "log_id": log_id,
        "mode": mode,
        "target_entity": target_entity,
        "prompt": prompt,
        "response": response,
    }
    try:
        log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to write hunter log: %s", e)


def _invoke_huggingface_agent(
    agent_name: str,
    input_json: dict[str, Any],
    timeout: int,
    knowledge_path: Path,
) -> dict[str, Any]:
    """Invoke a HuggingFace agent via subprocess.

    Args:
        agent_name: Name of the agent (e.g., 'ministral-recognizer').
        input_json: JSON input to send to the agent.
        timeout: Timeout in seconds.
        knowledge_path: Base knowledge directory for logging.

    Returns:
        Parsed JSON output from the agent.

    Raises:
        HunterError: If invocation fails, times out, or returns invalid JSON.
    """
    log_dir = _ensure_log_dir(knowledge_path)
    prompt_str = json.dumps(input_json)

    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "agent.huggingface",
                "--agent",
                agent_name,
                "--prompt",
                prompt_str,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired as e:
        raise HunterError(f"Agent {agent_name} timed out after {timeout}s: {e}") from e
    except FileNotFoundError as e:
        raise HunterError(f"uv CLI not found: {e}") from e
    except subprocess.SubprocessError as e:
        raise HunterError(f"Agent invocation failed: {e}") from e

    if result.returncode != 0:
        raise HunterError(
            f"Agent {agent_name} returned non-zero exit code {result.returncode}: {result.stderr}"
        )

    # Parse JSON output from stdout
    stdout = result.stdout.strip()
    if not stdout:
        raise HunterError(f"Agent {agent_name} returned empty output")

    # Log the interaction with target_entity metadata
    target_entity = input_json.get("target_entity")
    _log_interaction(log_dir, prompt_str, stdout, input_json.get("mode", "unknown"), target_entity)

    return _parse_json_response(stdout)


def _parse_json_response(response: str) -> dict[str, Any]:
    """Parse JSON from model response, handling potential formatting issues.

    Args:
        response: Raw model response text.

    Returns:
        Parsed JSON dictionary.

    Raises:
        HunterError: If no valid JSON found.
    """
    # Try to find JSON in the response
    json_start = response.find("{")
    json_end = response.rfind("}") + 1

    if json_start == -1 or json_end == 0:
        raise HunterError(f"No JSON found in response: {response[:200]}")

    json_str = response[json_start:json_end]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HunterError(f"Invalid JSON in response: {e}") from e


def _validate_hunter_output(data: dict[str, Any], mode: str) -> None:
    """Validate that the Hunter output contains required fields.

    Args:
        data: Parsed JSON data.
        mode: Expected mode ('entities' or 'facts').

    Raises:
        HunterError: If required fields are missing.
    """
    required_fields = ["mode", "entities", "facts", "spans", "done"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise HunterError(f"Missing required fields: {missing}")

    if data.get("mode") != mode:
        raise HunterError(f"Mode mismatch: expected '{mode}', got '{data.get('mode')}'")

    if mode == "facts" and "target_entity" not in data:
        raise HunterError("Missing 'target_entity' field for fact mode")


def invoke_hunter(
    state_text: str,
    target_entity: str | None = None,
    mode: Literal["entities", "facts"] = "entities",
    model: Any | None = None,  # noqa: ANN401 - Deprecated, ignored
    tokenizer: Any | None = None,  # noqa: ANN401 - Deprecated, ignored
    model_name: str = "mistralai/Ministral-3B-Instruct-2412",  # Deprecated, ignored
    knowledge_path: Path | None = None,
    timeout: int = 120,
) -> HunterOutput:
    """Invoke the Hunter for entity discovery or fact extraction.

    This function delegates to the ministral-recognizer agent via the
    huggingface_agent_runner subprocess. It either discovers entities in the text
    or extracts facts about a specific entity.

    Note:
        The `model`, `tokenizer`, and `model_name` parameters are deprecated and
        ignored. Model loading is now handled by the agent runner, which reads
        the model configuration from the agent's frontmatter.

    Args:
        state_text: The current state text to analyze.
        target_entity: Target entity for fact extraction (required for 'facts' mode).
        mode: 'entities' for entity discovery, 'facts' for fact extraction.
        model: Deprecated. Ignored.
        tokenizer: Deprecated. Ignored.
        model_name: Deprecated. Ignored.
        knowledge_path: Base knowledge directory for logging (default: .knowledge).
        timeout: Timeout in seconds for inference (default: 120).

    Returns:
        HunterOutput with entities, facts, spans, and done flag.

    Raises:
        HunterError: If inference fails, JSON parsing fails, or required fields missing.
        ValueError: If mode is 'facts' but target_entity is not provided.
    """
    # Silence unused variable warnings for deprecated params
    _ = model, tokenizer, model_name

    if mode == "facts" and not target_entity:
        raise ValueError("target_entity is required for 'facts' mode")

    # Resolve knowledge path
    if knowledge_path is None:
        knowledge_path = REPO_ROOT / ".knowledge"
    elif not knowledge_path.is_absolute():
        knowledge_path = REPO_ROOT / knowledge_path

    # Build input JSON matching ministral-recognizer agent contract
    input_json: dict[str, Any] = {
        "mode": mode,
        "state_text": state_text,
    }
    if mode == "facts":
        input_json["target_entity"] = target_entity

    # Invoke the huggingface agent
    data = _invoke_huggingface_agent(
        agent_name="ministral-recognizer",
        input_json=input_json,
        timeout=timeout,
        knowledge_path=knowledge_path,
    )

    # Validate response
    _validate_hunter_output(data, mode)

    # Build output
    entities: list[EntityResult] = []
    for e in data.get("entities", []):
        entities.append(
            EntityResult(
                mention=str(e.get("mention", "")),
                type_hint=str(e.get("type_hint", "")),
                evidence_span_id=str(e.get("evidence_span_id", "")),
            )
        )

    target: TargetEntity | None = None
    if data.get("target_entity"):
        t = data["target_entity"]
        target = TargetEntity(
            mention=str(t.get("mention", "")),
            resolved_id=str(t.get("resolved_id", "")),
        )

    facts: list[FactResult] = []
    for f in data.get("facts", []):
        facts.append(
            FactResult(
                fact_text=str(f.get("fact_text", "")),
                evidence_span_id=str(f.get("evidence_span_id", "")),
                confidence=float(f.get("confidence", 0.0)),
            )
        )

    spans: list[SpanResult] = []
    for s in data.get("spans", []):
        spans.append(
            SpanResult(
                span_id=str(s.get("span_id", "")),
                original_text=str(s.get("original_text", "")),
            )
        )

    return HunterOutput(
        mode=mode,
        entities=entities,
        target_entity=target,
        facts=facts,
        spans=spans,
        done=bool(data.get("done", False)),
        reason=data.get("reason"),
    )


def invoke_hunter_mock(
    state_text: str,
    target_entity: str | None = None,
    mode: Literal["entities", "facts"] = "entities",
) -> HunterOutput:
    """Mock Hunter for testing without loading the actual model.

    This function provides a deterministic mock response for testing purposes.
    It simulates entity discovery and fact extraction based on simple heuristics.

    Args:
        state_text: The current state text to analyze.
        target_entity: Target entity for fact extraction.
        mode: 'entities' for entity discovery, 'facts' for fact extraction.

    Returns:
        Mock HunterOutput.
    """
    if mode == "entities":
        # Simple heuristic: look for CamelCase or snake_case words
        import re

        potential_entities = re.findall(r"\b([A-Z][a-zA-Z]+|[a-z]+_[a-z_]+)\b", state_text)
        entities = []
        spans = []

        for i, entity in enumerate(list(set(potential_entities))[:5]):  # Limit to 5
            span_id = f"span_{i}"
            entities.append(
                EntityResult(
                    mention=entity,
                    type_hint="IDENTIFIER",
                    evidence_span_id=span_id,
                )
            )
            # Find the sentence containing this entity
            for sentence in state_text.split("."):
                if entity in sentence:
                    spans.append(
                        SpanResult(
                            span_id=span_id,
                            original_text=sentence.strip() + ".",
                        )
                    )
                    break

        return HunterOutput(
            mode="entities",
            entities=entities,
            target_entity=None,
            facts=[],
            spans=spans,
            done=len(entities) == 0,
            reason="No entities found" if len(entities) == 0 else None,
        )

    # Fact extraction mode
    if not target_entity:
        return HunterOutput(
            mode="facts",
            entities=[],
            target_entity=None,
            facts=[],
            spans=[],
            done=True,
            reason="No target entity provided",
        )

    # Check if entity is in text
    if target_entity.lower() not in state_text.lower():
        return HunterOutput(
            mode="facts",
            entities=[],
            target_entity=TargetEntity(mention=target_entity, resolved_id=target_entity),
            facts=[],
            spans=[],
            done=True,
            reason=f"Entity '{target_entity}' not found in text",
        )

    # Extract sentences containing the entity
    facts = []
    spans = []
    for i, sentence in enumerate(state_text.split(".")):
        if target_entity.lower() in sentence.lower():
            span_id = f"span_{i}"
            spans.append(
                SpanResult(
                    span_id=span_id,
                    original_text=sentence.strip() + ".",
                )
            )
            facts.append(
                FactResult(
                    fact_text=f"{target_entity} is mentioned in: {sentence.strip()}.",
                    evidence_span_id=span_id,
                    confidence=0.8,
                )
            )

    return HunterOutput(
        mode="facts",
        entities=[],
        target_entity=TargetEntity(mention=target_entity, resolved_id=target_entity),
        facts=facts,
        spans=spans,
        done=len(facts) == 0,
        reason="All facts extracted" if len(facts) == 0 else None,
    )
