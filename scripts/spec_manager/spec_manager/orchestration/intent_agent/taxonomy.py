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
from dataclasses import dataclass
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
USER_VALID_TYPES: frozenset[QuestionTaxonomy] = frozenset({
    QuestionTaxonomy.INTENT,
    QuestionTaxonomy.CONSTRAINT,
    QuestionTaxonomy.TRADEOFF,
    QuestionTaxonomy.SCOPE,
    QuestionTaxonomy.VALIDATION,
})

# Internal-only types that must be reframed
PROHIBITED_TYPES: frozenset[QuestionTaxonomy] = frozenset({
    QuestionTaxonomy.ARCHITECTURE,
    QuestionTaxonomy.IMPLEMENTATION,
    QuestionTaxonomy.DESIGN_PATTERN,
    QuestionTaxonomy.OPTIMIZATION,
})


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
_VAGUE_KEYWORDS = frozenset({
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
})
_CONSTRAINT_DIMENSION_HINTS: dict[ConstraintDimension, frozenset[str]] = {
    ConstraintDimension.OPERATIONAL: frozenset({
        "latency",
        "throughput",
        "availability",
        "batch",
        "window",
        "rto",
        "rpo",
        "performance",
    }),
    ConstraintDimension.REGULATORY: frozenset({
        "compliance",
        "audit",
        "privacy",
        "residency",
        "gdpr",
        "sox",
    }),
    ConstraintDimension.ORGANIZATIONAL: frozenset({
        "team",
        "ownership",
        "support",
        "ops",
        "sre",
        "people",
        "process",
    }),
    ConstraintDimension.LEGAL_LICENSING: frozenset({
        "open source",
        "vendor",
        "contract",
        "license",
        "licensing",
        "approved",
    }),
    ConstraintDimension.FINANCIAL: frozenset({
        "budget",
        "cost",
        "spending",
        "price",
        "fees",
    }),
    ConstraintDimension.PLATFORM: frozenset({
        "on-prem",
        "cloud",
        "vendor lock-in",
        "provider",
        "identity",
    }),
    ConstraintDimension.DATA: frozenset({
        "sensitivity",
        "retention",
        "volume",
        "lineage",
        "access",
        "pii",
    }),
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

    if not canonical_key:
        return normalize_constraint_dimensions(sorted(matched))

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
    if re.search(r"platform|cloud|on_prem|onprem|provider|host|identity|vendor", canonical_text):
        matched.add(ConstraintDimension.PLATFORM.value)
    if re.search(r"data|pii|retention|lineage|access|volume|record", canonical_text):
        matched.add(ConstraintDimension.DATA.value)

    return normalize_constraint_dimensions(sorted(matched))


def normalize_user_facing_taxonomy(raw_taxonomy: Any) -> str:
    """Return only valid user-facing taxonomy enum values."""
    normalized = _normalize_taxonomy_value(raw_taxonomy)
    if not normalized:
        return QuestionTaxonomy.CONSTRAINT.value
    try:
        parsed = QuestionTaxonomy(normalized)
    except ValueError:
        return QuestionTaxonomy.CONSTRAINT.value
    return parsed.value if parsed in USER_VALID_TYPES else QuestionTaxonomy.CONSTRAINT.value


def normalize_taxonomy_type(raw_taxonomy: Any) -> str:
    """Normalize any taxonomy-like value into a `QuestionTaxonomy` value."""
    normalized = _normalize_taxonomy_value(raw_taxonomy)
    if not normalized:
        return QuestionTaxonomy.CONSTRAINT.value
    try:
        return QuestionTaxonomy(normalized).value
    except ValueError:
        return QuestionTaxonomy.CONSTRAINT.value


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
    if lower := lowered:
        for token in _VAGUE_KEYWORDS:
            if token in lowered:
                return True

        # Generic intent phrases that usually require one bounded disambiguation question.
        if (
            "what" in tokens
            and ("app" in tokens or "system" in tokens)
            and any(t in tokens for t in ("do", "should", "about", "about?")
        ):
            return True

    return False


def is_user_valid(taxonomy_type: QuestionTaxonomy) -> bool:
    """Check if a question type is valid for user exposure."""
    return taxonomy_type in USER_VALID_TYPES


def is_prohibited(taxonomy_type: QuestionTaxonomy) -> bool:
    """Check if a question type must be reframed before user exposure."""
    return taxonomy_type in PROHIBITED_TYPES


def classify_question(
    text: str,
    context: dict[str, Any] | None = None,
    *,
    run_agent: Any = None,
) -> QuestionTaxonomy:
    """Classify a question into its taxonomy type.

    Uses LLM to determine which QuestionTaxonomy value best fits the
    question *text*.  Falls back to CONSTRAINT when the LLM is
    unavailable or returns something unparseable.
    """
    if run_agent is None:
        return QuestionTaxonomy.CONSTRAINT

    from spec_manager.core.json_extraction import _extract_json_payload

    context_block = ""
    if context:
        context_block = f"\nAdditional context:\n{context}\n"

    valid_names = [t.value for t in QuestionTaxonomy if t != QuestionTaxonomy.UNKNOWN]

    prompt = (
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

    import json

    try:
        raw = run_agent(prompt)
        payload = _extract_json_payload(raw)
        data = json.loads(payload)
        type_str = data.get("taxonomy_type", "").upper().strip()
        return QuestionTaxonomy(type_str)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        logger.debug("classify_question LLM parse failed (%s), defaulting to CONSTRAINT", exc)
        return QuestionTaxonomy.CONSTRAINT


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

    from spec_manager.core.json_extraction import _extract_json_payload

    target_names = [t.value for t in target_types]
    context_block = ""
    if context:
        context_block = f"\nAdditional context:\n{context}\n"

    # Per-type reframe guidance
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
    guidance = guidance_map.get(taxonomy_type, "Reframe into a user-facing question.")

    prompt = (
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

    import json

    try:
        raw = run_agent(prompt)
        payload = _extract_json_payload(raw)
        data = json.loads(payload)

        reframed_type_str = data.get("reframed_type", "").upper().strip()
        try:
            reframed_type = QuestionTaxonomy(reframed_type_str)
        except ValueError:
            reframed_type = target_types[0]

        # Ensure the reframed type is actually one of the valid targets
        if reframed_type not in target_types:
            reframed_type = target_types[0]

        reframed_text = data.get("reframed_text", "").strip()
        if not reframed_text:
            return None

        return ReframedQuestion(
            original_text=text,
            original_type=taxonomy_type,
            reframed_text=reframed_text,
            reframed_type=reframed_type,
            scenario=data.get("scenario", ""),
            answer_spec_kind="choice",
            choices=data.get("choices", []),
        )
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        logger.debug("reframe_to_user_valid LLM parse failed (%s)", exc)
        return None


_SYSTEM_WIDE_KEYWORDS: frozenset[str] = frozenset({
    "system", "all", "every", "across", "global", "entire",
    "everywhere", "whole", "overall", "universal",
})


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
