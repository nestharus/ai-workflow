"""Question taxonomy — classification and reframing.

Per response2.md Section 5.4: All questions are classified into exactly one
type. Five types are valid for users; four are internal-only and must be
reframed before user exposure.

Valid user-facing types:
    INTENT      — What is the real problem?
    CONSTRAINT  — What boundaries exist? (7 dimensions)
    TRADEOFF    — When priorities conflict, which wins?
    SCOPE       — What is in and what is out?
    VALIDATION  — How do we know it's correct?

Prohibited internal-only types (must be reframed):
    ARCHITECTURE     — Users aren't responsible for system design
    IMPLEMENTATION   — Libraries/frameworks are system choices
    DESIGN_PATTERN   — Code structuring is internal
    OPTIMIZATION     — Performance tactics are internal

Constraint dimensions (Section 5.4.4):
    operational, regulatory, organizational, legal_licensing,
    financial, platform, data
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class QuestionTaxonomy(str, enum.Enum):
    """All question types including both valid and prohibited."""

    # Valid user-facing types
    INTENT = "INTENT"
    CONSTRAINT = "CONSTRAINT"
    TRADEOFF = "TRADEOFF"
    SCOPE = "SCOPE"
    VALIDATION = "VALIDATION"

    # Prohibited internal-only types (must reframe before user exposure)
    ARCHITECTURE = "ARCHITECTURE"
    IMPLEMENTATION = "IMPLEMENTATION"
    DESIGN_PATTERN = "DESIGN_PATTERN"
    OPTIMIZATION = "OPTIMIZATION"

    # Unknown (needs classification)
    UNKNOWN = "UNKNOWN"


# Valid types that may reach the user
USER_VALID_TYPES: frozenset[QuestionTaxonomy] = frozenset(
    {
        QuestionTaxonomy.INTENT,
        QuestionTaxonomy.CONSTRAINT,
        QuestionTaxonomy.TRADEOFF,
        QuestionTaxonomy.SCOPE,
        QuestionTaxonomy.VALIDATION,
    }
)

# Internal-only types that must be reframed
PROHIBITED_TYPES: frozenset[QuestionTaxonomy] = frozenset(
    {
        QuestionTaxonomy.ARCHITECTURE,
        QuestionTaxonomy.IMPLEMENTATION,
        QuestionTaxonomy.DESIGN_PATTERN,
        QuestionTaxonomy.OPTIMIZATION,
    }
)


class QuestionScope(str, enum.Enum):
    """Whether a question affects the whole system or a specific feature."""

    SYSTEM_WIDE = "SYSTEM_WIDE"
    FEATURE_SPECIFIC = "FEATURE_SPECIFIC"


class ConstraintDimension(str, enum.Enum):
    """Constraint dimensions for CONSTRAINT-type questions (Section 5.4.4)."""

    OPERATIONAL = "operational"  # latency, throughput, availability, RTO/RPO
    REGULATORY = "regulatory"  # compliance, audit, data residency
    ORGANIZATIONAL = "organizational"  # team size, expertise, ownership
    LEGAL_LICENSING = "legal_licensing"  # open-source policy, vendor restrictions
    FINANCIAL = "financial"  # budget, cost targets, cost sensitivity
    PLATFORM = "platform"  # cloud/on-prem, network, identity provider
    DATA = "data"  # sensitivity, retention, volume, lineage, access


# TODO [R2-5.4.2]: Reframe mapping — for each prohibited type, define the
#   pattern for reframing into a valid type:
#   ARCHITECTURE → CONSTRAINT/TRADEOFF (required behavior/timing/visibility)
#   IMPLEMENTATION → CONSTRAINT/SCOPE (compatibility/lock-in/licensing)
#   DESIGN_PATTERN → CONSTRAINT/SCOPE (change frequency/ownership/audit)
#   OPTIMIZATION → CONSTRAINT/TRADEOFF (performance targets/acceptable delays)
REFRAME_TARGET_MAP: dict[QuestionTaxonomy, list[QuestionTaxonomy]] = {
    QuestionTaxonomy.ARCHITECTURE: [QuestionTaxonomy.CONSTRAINT, QuestionTaxonomy.TRADEOFF],
    QuestionTaxonomy.IMPLEMENTATION: [QuestionTaxonomy.CONSTRAINT, QuestionTaxonomy.SCOPE],
    QuestionTaxonomy.DESIGN_PATTERN: [QuestionTaxonomy.CONSTRAINT, QuestionTaxonomy.SCOPE],
    QuestionTaxonomy.OPTIMIZATION: [QuestionTaxonomy.CONSTRAINT, QuestionTaxonomy.TRADEOFF],
}


_VOCAB_RE = re.compile(r"[a-z0-9_]+")
_VAGUE_KEYWORDS = frozenset(
    {
        "something",
        "thing",
        "it",
        "stuff",
        "various",
        "whatevs",
        "whatever",
        "somehow",
        "some",
        "any",
        "many",
        "few",
        "sort",
        "sort of",
        "kind of",
        "seems",
        "kind",
        "basically",
        "generally",
        "overall",
        "something like",
    }
)
_CONSTRAINT_DIMENSION_HINTS: dict[ConstraintDimension, frozenset[str]] = {
    ConstraintDimension.OPERATIONAL: frozenset(
        {
            "latency",
            "throughput",
            "availability",
            "batch",
            "window",
            "rto",
            "rpo",
            "performance",
        }
    ),
    ConstraintDimension.REGULATORY: frozenset(
        {
            "compliance",
            "audit",
            "privacy",
            "residency",
            "gdpr",
            "sox",
        }
    ),
    ConstraintDimension.ORGANIZATIONAL: frozenset(
        {
            "team",
            "ownership",
            "support",
            "ops",
            "sre",
            "people",
            "process",
        }
    ),
    ConstraintDimension.LEGAL_LICENSING: frozenset(
        {
            "open source",
            "vendor",
            "contract",
            "license",
            "licensing",
            "approved",
        }
    ),
    ConstraintDimension.FINANCIAL: frozenset(
        {
            "budget",
            "cost",
            "spending",
            "price",
            "fees",
        }
    ),
    ConstraintDimension.PLATFORM: frozenset(
        {
            "on-prem",
            "cloud",
            "vendor lock-in",
            "provider",
            "identity",
        }
    ),
    ConstraintDimension.DATA: frozenset(
        {
            "sensitivity",
            "retention",
            "volume",
            "lineage",
            "access",
            "pii",
        }
    ),
}


def normalize_constraint_dimensions(values: Any) -> list[str]:
    """Normalize a raw dimension value or iterable to canonical dimension keys."""
    if values is None:
        return []

    raw_values = values
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, (ConstraintDimension,)):  # keep for type narrowers
        raw_values = [values.value]
    elif not isinstance(values, (list, tuple, set, frozenset)):
        raw_values = [values]

    normalized: set[str] = set()
    valid_dims = {dim.value for dim in ConstraintDimension}

    for raw_value in raw_values:
        if isinstance(raw_value, ConstraintDimension):
            value = raw_value.value
        else:
            value = str(raw_value).strip().lower().replace("-", "_").replace(" ", "_")

        value = re.sub(r"[^a-z0-9_]", "", value)
        if value in valid_dims:
            normalized.add(value)
            continue

        # Allow common aliases and old names.
        alias_map = {
            "legal": "legal_licensing",
            "licensing": "legal_licensing",
            "license": "legal_licensing",
            "platform_data": "platform",
            "regulatory": "regulatory",
            "operations": "operational",
            "operations_scope": "operational",
        }
        mapped = alias_map.get(value, "")
        if mapped:
            normalized.add(mapped)

    return sorted(normalized)


def _tokenize(text: str) -> list[str]:
    """Return simple lowercase alpha tokens."""
    return _VOCAB_RE.findall(text.lower())


def _normalize_taxonomy_value(value: Any) -> str:
    """Normalize taxonomy-like values into uppercase enum key format."""
    if isinstance(value, QuestionTaxonomy):
        return value.value
    return re.sub(r"[^A-Z_]", "", str(value).strip().upper().replace("-", "_"))


def infer_constraint_dimensions_with_key(
    text: str,
    *,
    canonical_key: str | None = None,
) -> list[str]:
    """Infer likely constraint dimensions from question text and optional canonical key."""
    matched: set[str] = set(infer_constraint_dimensions(text))

    if canonical_key:
        lowered_key = canonical_key.lower()
        normalized_key = lowered_key.replace("-", "_")
        key_tokens = " ".join(re.findall(r"[a-z0-9_]+", normalized_key))

        for dim, keywords in _CONSTRAINT_DIMENSION_HINTS.items():
            for keyword in keywords:
                normalized_keyword = keyword.replace("-", "_")
                if (
                    keyword in normalized_key
                    or normalized_keyword in normalized_key
                    or normalized_keyword.replace("_", " ") in key_tokens
                ):
                    matched.add(dim.value)
                    break

    if canonical_key:
        canonical_text = re.sub(r"[^a-z0-9_]", " ", canonical_key.lower())
        if re.search(r"operat|performance|latenc|throughput|rto|rpo|batch", canonical_text):
            matched.add(ConstraintDimension.OPERATIONAL.value)
        if re.search(r"regulat|privacy|audit|compliance|sox|gdpr|resid", canonical_text):
            matched.add(ConstraintDimension.REGULATORY.value)
        if re.search(r"org|team|ops|owner|sre|people", canonical_text):
            matched.add(ConstraintDimension.ORGANIZATIONAL.value)
        if re.search(r"legal|licen|vendor|contract|source_code", canonical_text):
            matched.add(ConstraintDimension.LEGAL_LICENSING.value)
        if re.search(r"budget|cost|spend|pay|money|financial|fees|price", canonical_text):
            matched.add(ConstraintDimension.FINANCIAL.value)
        if re.search(
            r"platform|cloud|on_prem|onprem|provider|host|identity|vendor", canonical_text
        ):
            matched.add(ConstraintDimension.PLATFORM.value)
        if re.search(r"data|pii|retention|lineage|access|volume|record", canonical_text):
            matched.add(ConstraintDimension.DATA.value)

    normalized = normalize_constraint_dimensions(sorted(matched))
    return normalized


def normalize_user_facing_taxonomy(raw_taxonomy: Any) -> str:
    """Return only valid user-facing taxonomy enum values."""
    normalized = _normalize_taxonomy_value(raw_taxonomy)
    if not normalized:
        return QuestionTaxonomy.UNKNOWN.value
    try:
        parsed = QuestionTaxonomy(normalized)
    except ValueError:
        return QuestionTaxonomy.UNKNOWN.value
    return parsed.value if parsed in USER_VALID_TYPES else QuestionTaxonomy.UNKNOWN.value


def normalize_taxonomy_type(raw_taxonomy: Any) -> str:
    """Normalize any taxonomy-like value into a `QuestionTaxonomy` value."""
    normalized = _normalize_taxonomy_value(raw_taxonomy)
    if not normalized:
        return QuestionTaxonomy.UNKNOWN.value
    try:
        return QuestionTaxonomy(normalized).value
    except ValueError:
        return QuestionTaxonomy.UNKNOWN.value


def infer_constraint_dimensions(text: str) -> list[str]:
    """Infer likely constraint dimensions from a question text."""
    lowered = text.lower()
    matched: set[str] = set()
    for dim, keywords in _CONSTRAINT_DIMENSION_HINTS.items():
        for keyword in keywords:
            if keyword in lowered:
                matched.add(dim.value)
                break
    return sorted(matched)


def is_vague_user_input(text: str) -> bool:
    """Heuristic for whether user input is vague enough to disambiguate first."""
    normalized = (text or "").strip()
    if not normalized:
        return True

    tokens = _tokenize(normalized)
    if len(tokens) <= 3:
        return True

    lowered = normalized.lower()
    for token in _VAGUE_KEYWORDS:
        if token in lowered:
            return True

    # Generic intent phrases that usually require one bounded disambiguation question.
    return (
        "what" in tokens
        and ("app" in tokens or "system" in tokens)
        and any(t in tokens for t in ("do", "should", "about", "about?"))
    )


def is_user_valid(taxonomy_type: QuestionTaxonomy) -> bool:
    """Check if a question type is valid for user exposure."""
    return taxonomy_type in USER_VALID_TYPES


def is_prohibited(taxonomy_type: QuestionTaxonomy) -> bool:
    """Check if a question type must be reframed before user exposure."""
    return taxonomy_type in PROHIBITED_TYPES


def _coerce_str_sequence(value: Any | None) -> list[str]:
    """Normalize optional textual hints into a cleaned list."""
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, (list, tuple, set, frozenset)):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                token = item.strip()
                if token:
                    result.append(token)
        return result
    return []


@dataclass
class ClassificationContext:
    """Projected subset of signal payload data for classification prompts."""

    question_text: str = ""
    prior_classifications: list[str] = field(default_factory=list)
    domain_hints: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> ClassificationContext:
        if not isinstance(payload, dict):
            return cls()
        question_text_raw = payload.get("question_text")
        return cls(
            question_text=(question_text_raw.strip() if isinstance(question_text_raw, str) else ""),
            prior_classifications=_coerce_str_sequence(payload.get("prior_classifications")),
            domain_hints=_coerce_str_sequence(payload.get("domain_hints")),
        )


def _format_classification_context_block(context: ClassificationContext) -> str:
    """Render just the classification-relevant hints for LLM prompts."""
    lines: list[str] = []
    if context.question_text:
        lines.append(f"- Reference question: {context.question_text}")
    if context.prior_classifications:
        lines.append(f"- Prior classifications: {', '.join(context.prior_classifications)}")
    if context.domain_hints:
        lines.append(f"- Domain hints: {', '.join(context.domain_hints)}")
    if not lines:
        return ""
    return "\nAdditional context to consider:\n" + "\n".join(lines) + "\n"


@dataclass(frozen=True)
class _AgentJsonOutcome:
    """Typed orchestration signal for JSON-producing agent calls."""

    payload: dict[str, Any] | None = None
    error: Exception | None = None


def _run_agent_json(prompt: str, *, run_agent: Any) -> _AgentJsonOutcome:
    """Invoke an agent, extract JSON payload, and report success/failure."""
    import json

    from spec_manager.core.json_extraction import _extract_json_payload

    try:
        raw = run_agent(prompt)
        payload = _extract_json_payload(raw)
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise TypeError("Agent JSON payload must decode to an object.")
        return _AgentJsonOutcome(payload=data)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        return _AgentJsonOutcome(error=exc)


def _build_classification_prompt(text: str, context: ClassificationContext) -> str:
    """Build taxonomy-classification instructions and policy text."""
    context_block = _format_classification_context_block(context)
    valid_names = [t.value for t in QuestionTaxonomy if t != QuestionTaxonomy.UNKNOWN]
    return (
        "Classify the following question into exactly one taxonomy type.\n\n"
        f"Question: {text}\n"
        f"{context_block}\n"
        "Valid taxonomy types:\n"
        "  INTENT — What is the real problem?\n"
        "  CONSTRAINT — What boundaries exist?\n"
        "  TRADEOFF — When priorities conflict, which wins?\n"
        "  SCOPE — What is in and what is out?\n"
        "  VALIDATION — How do we know it's correct?\n"
        "  ARCHITECTURE — System design questions\n"
        "  IMPLEMENTATION — Libraries/frameworks choices\n"
        "  DESIGN_PATTERN — Code structuring questions\n"
        "  OPTIMIZATION — Performance tactics questions\n\n"
        'Respond with JSON: {"taxonomy_type": "<TYPE>"}\n'
        f"TYPE must be one of: {', '.join(valid_names)}"
    )


def _classification_prompt_from_mapping(
    text: str,
    context: dict[str, Any] | None,
) -> str:
    """Build a classification prompt from raw context mapping input."""
    classification_context = ClassificationContext.from_mapping(context)
    return _build_classification_prompt(text, classification_context)


def _taxonomy_from_classification_payload(
    payload: dict[str, Any],
) -> QuestionTaxonomy | None:
    """Apply taxonomy rules to a parsed classification payload."""
    taxonomy_raw = payload.get("taxonomy_type")
    if not isinstance(taxonomy_raw, str):
        return None
    normalized = taxonomy_raw.upper().strip()
    if not normalized:
        return None
    try:
        return QuestionTaxonomy(normalized)
    except ValueError:
        return None


def _interpret_classification_outcome(
    outcome: _AgentJsonOutcome,
) -> QuestionTaxonomy | None:
    """Interpret a JSON-agent outcome into a taxonomy classification candidate."""
    if outcome.error is not None:
        return None
    return _taxonomy_from_classification_payload(outcome.payload or {})


def _validate_classification_candidate(
    taxonomy: QuestionTaxonomy | None,
) -> QuestionTaxonomy | None:
    """Validate taxonomy classification constraints."""
    if taxonomy is None or taxonomy == QuestionTaxonomy.UNKNOWN:
        return None
    return taxonomy


def classify_question(
    text: str,
    context: dict[str, Any] | None = None,
    *,
    run_agent: Any = None,
) -> QuestionTaxonomy:
    """Classify a question into its taxonomy type.

    Uses LLM to determine which QuestionTaxonomy value best fits the
    question *text*. Returns UNKNOWN when classification is unavailable
    or invalid.
    """
    if run_agent is None:
        return QuestionTaxonomy.UNKNOWN

    prompt = _classification_prompt_from_mapping(text, context)
    agent_outcome = _run_agent_json(prompt, run_agent=run_agent)
    parsed = _interpret_classification_outcome(agent_outcome)
    parsed = _validate_classification_candidate(parsed)
    if parsed is None:
        if agent_outcome.error is not None:
            logger.debug(
                "classify_question LLM parse failed (%s), returning UNKNOWN",
                agent_outcome.error,
            )
        else:
            logger.debug(
                "classify_question LLM parse failed (invalid taxonomy_type), returning UNKNOWN"
            )
        return QuestionTaxonomy.UNKNOWN
    return parsed


@dataclass
class ReframedQuestion:
    """Result of reframing a prohibited question into user-valid form."""

    original_text: str = ""
    original_type: QuestionTaxonomy = QuestionTaxonomy.UNKNOWN
    reframed_text: str = ""
    reframed_type: QuestionTaxonomy = QuestionTaxonomy.CONSTRAINT
    scenario: str = ""
    answer_spec_kind: str = "choice"
    choices: list[str] = None

    def __post_init__(self) -> None:
        if self.choices is None:
            self.choices = []


def _reframe_guidance_for_type(taxonomy_type: QuestionTaxonomy) -> str:
    """Return domain-specific reframing policy for prohibited types."""
    guidance_map = {
        QuestionTaxonomy.ARCHITECTURE: (
            "Reframe into a question about required behavior, timing, or visibility "
            "constraints — not about system design."
        ),
        QuestionTaxonomy.IMPLEMENTATION: (
            "Reframe into a question about compatibility, lock-in, or licensing "
            "constraints — not about library or framework choices."
        ),
        QuestionTaxonomy.DESIGN_PATTERN: (
            "Reframe into a question about change frequency, ownership, or audit "
            "constraints — not about code structure."
        ),
        QuestionTaxonomy.OPTIMIZATION: (
            "Reframe into a question about performance targets or acceptable delay "
            "tradeoffs — not about implementation tactics."
        ),
    }
    return guidance_map.get(taxonomy_type, "Reframe into a user-facing question.")


def _build_reframe_prompt(
    text: str,
    taxonomy_type: QuestionTaxonomy,
    target_types: list[QuestionTaxonomy],
    context: ClassificationContext,
) -> str:
    """Build user-facing reframing instructions and constraints."""
    target_names = [t.value for t in target_types]
    context_block = _format_classification_context_block(context)
    guidance = _reframe_guidance_for_type(taxonomy_type)
    return (
        "A question was classified as an internal-only type that cannot be shown "
        "to users directly. Reframe it as a user-valid question.\n\n"
        f"Original question: {text}\n"
        f"Original type: {taxonomy_type.value}\n"
        f"{context_block}\n"
        f"Guidance: {guidance}\n\n"
        f"The reframed question must be one of these types: {', '.join(target_names)}\n\n"
        "Respond with JSON:\n"
        "{\n"
        '  "reframed_text": "<new question text for the user>",\n'
        f'  "reframed_type": "<one of {", ".join(target_names)}>",\n'
        '  "scenario": "<brief scenario explaining why this matters>",\n'
        '  "choices": ["<choice A>", "<choice B>", ...]\n'
        "}"
    )


def _reframe_prompt_from_mapping(
    text: str,
    taxonomy_type: QuestionTaxonomy,
    target_types: list[QuestionTaxonomy],
    context: dict[str, Any] | None,
) -> str:
    """Build a reframe prompt from raw context mapping input."""
    classification_context = ClassificationContext.from_mapping(context)
    return _build_reframe_prompt(
        text,
        taxonomy_type,
        target_types,
        classification_context,
    )


def _reframed_question_from_payload(
    payload: dict[str, Any],
    *,
    original_text: str,
    original_type: QuestionTaxonomy,
) -> ReframedQuestion | None:
    """Interpret reframing payload into a typed question candidate."""
    reframed_text_raw = payload.get("reframed_text", "")
    reframed_text = reframed_text_raw.strip() if isinstance(reframed_text_raw, str) else ""
    if not reframed_text:
        return None

    reframed_type_raw = payload.get("reframed_type", "")
    if isinstance(reframed_type_raw, str):
        try:
            reframed_type = QuestionTaxonomy(reframed_type_raw.upper().strip())
        except ValueError:
            reframed_type = QuestionTaxonomy.UNKNOWN
    else:
        reframed_type = QuestionTaxonomy.UNKNOWN

    return ReframedQuestion(
        original_text=original_text,
        original_type=original_type,
        reframed_text=reframed_text,
        reframed_type=reframed_type,
        scenario=payload.get("scenario", ""),
        answer_spec_kind="choice",
        choices=payload.get("choices", []),
    )


def _interpret_reframe_outcome(
    outcome: _AgentJsonOutcome,
    *,
    original_text: str,
    original_type: QuestionTaxonomy,
) -> ReframedQuestion | None:
    """Interpret a JSON-agent outcome into a reframe candidate."""
    if outcome.error is not None:
        return None
    return _reframed_question_from_payload(
        outcome.payload or {},
        original_text=original_text,
        original_type=original_type,
    )


def _validate_reframed_question_candidate(
    question: ReframedQuestion | None,
    *,
    target_types: list[QuestionTaxonomy],
) -> ReframedQuestion | None:
    """Validate and normalize a reframe candidate against target type constraints."""
    if question is None:
        return None
    if question.reframed_type in target_types:
        return question
    return None


def reframe_to_user_valid(
    text: str,
    taxonomy_type: QuestionTaxonomy,
    context: dict[str, Any] | None = None,
    *,
    run_agent: Any = None,
) -> ReframedQuestion | None:
    """Reframe a prohibited question type into a user-valid question.

    Uses the REFRAME_TARGET_MAP to guide the LLM toward a valid question
    type.  Returns ``None`` when reframing fails (caller should escalate
    to the Planner).
    """
    if run_agent is None:
        return None

    target_types = REFRAME_TARGET_MAP.get(taxonomy_type)
    if not target_types:
        # Not a prohibited type or unknown — nothing to reframe.
        return None

    prompt = _reframe_prompt_from_mapping(
        text,
        taxonomy_type,
        target_types,
        context,
    )
    agent_outcome = _run_agent_json(prompt, run_agent=run_agent)
    candidate = _interpret_reframe_outcome(
        agent_outcome,
        original_text=text,
        original_type=taxonomy_type,
    )
    if candidate is None:
        if agent_outcome.error is not None:
            logger.debug("reframe_to_user_valid LLM parse failed (%s)", agent_outcome.error)
        return None
    return _validate_reframed_question_candidate(candidate, target_types=target_types)


_SYSTEM_WIDE_KEYWORDS: frozenset[str] = frozenset(
    {
        "system",
        "all",
        "every",
        "across",
        "global",
        "entire",
        "everywhere",
        "whole",
        "overall",
        "universal",
    }
)


def classify_scope(
    text: str,
    context: dict[str, Any] | None = None,
) -> QuestionScope:
    """Classify question scope as system-wide or feature-specific.

    Simple heuristic: if the question text mentions system-wide keywords,
    classify as SYSTEM_WIDE; otherwise FEATURE_SPECIFIC.  No LLM needed.
    """
    lowered = text.lower()
    for keyword in _SYSTEM_WIDE_KEYWORDS:
        # Word-boundary-aware check: keyword surrounded by non-alpha chars
        idx = lowered.find(keyword)
        while idx != -1:
            before_ok = idx == 0 or not lowered[idx - 1].isalpha()
            after_idx = idx + len(keyword)
            after_ok = after_idx >= len(lowered) or not lowered[after_idx].isalpha()
            if before_ok and after_ok:
                return QuestionScope.SYSTEM_WIDE
            idx = lowered.find(keyword, idx + 1)

    return QuestionScope.FEATURE_SPECIFIC
