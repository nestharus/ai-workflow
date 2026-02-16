"""Bootstrap constraints from Phase 0 intake artifacts.

Parses ``constraints.md`` files produced during intake (Phase 0) and seeds the
constraint store so that downstream layers can query established constraints
without re-parsing the raw spec.

Constraint markers use the format ``([=CON-LIB-001])`` followed by a verbatim
text block describing the constraint.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Literal

from spec_manager.planner.constraints.types import (
    ConstraintFact,
    ConstraintIndexEntry,
)
from spec_manager.planner.tools.constraints_tool import ConstraintsTool

logger = logging.getLogger(__name__)

# Regex for ``([=CON-LIB-001])`` style markers.
_MARKER_RE = re.compile(
    r"\(\[=([A-Z0-9][\w-]*)\]\)",
    re.IGNORECASE,
)

# Allowed shallow subtype taxonomy from SEC-108.
_ALLOWED_SUBTYPES = {
    "invariant",
    "tradeoff_preference",
    "dependency_declaration",
    "domain_marker",
    "policy",
    "performance",
    "security",
    "privacy",
    "compliance",
    "ops",
}

# Ordered subtype rules. First matching rule wins.
_SUBTYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "security",
        (
            "auth",
            "security",
            "encrypt",
            "credential",
            "permission",
            "access control",
            "token",
            "oauth",
            "tls",
        ),
    ),
    (
        "privacy",
        (
            "privacy",
            "pii",
            "personal data",
            "anonym",
            "pseudonym",
            "consent",
            "data minimization",
            "subject access request",
        ),
    ),
    (
        "compliance",
        (
            "compliance",
            "regulation",
            "gdpr",
            "hipaa",
            "soc2",
            "pci",
            "regulatory audit",
            "legal",
        ),
    ),
    (
        "performance",
        (
            "latency",
            "throughput",
            "performance",
            "sla",
            "slo",
            "response time",
            "benchmark",
            "p95",
            "p99",
        ),
    ),
    (
        "ops",
        (
            "deploy",
            "infrastructure",
            "container",
            "kubernetes",
            "docker",
            "ci/cd",
            "pipeline",
            "runbook",
            "on-call",
            "incident",
            "sre",
            "operations",
        ),
    ),
    (
        "dependency_declaration",
        (
            "depends on",
            "dependency on",
            "requires ",
            "require ",
            "integrates with",
            "connects to",
            "calls ",
            "call ",
            "via ",
            "backed by",
            "provider",
            "vendor",
            "sdk",
            "third-party",
            "external service",
        ),
    ),
    (
        "tradeoff_preference",
        (
            "tradeoff",
            "prefer ",
            "preferable",
            "prioritize",
            "rather than",
            "instead of",
            "over ",
            "at the cost of",
            "at the expense of",
        ),
    ),
    (
        "domain_marker",
        (
            "domain",
            "business rule",
            "subject matter",
            "regulated market",
            "market convention",
            "ledger",
            "underwriting",
            "reconciliation",
            "settlement",
            "counterparty",
        ),
    ),
    (
        "policy",
        (
            "policy",
            "retry",
            "fallback",
            "timeout",
            "circuit breaker",
            "backoff",
            "error handling",
            "failure mode",
            "concurrency",
            "thread",
            "mutex",
            "lock",
        ),
    ),
    (
        "invariant",
        (
            "must",
            "shall",
            "always",
            "never",
            "required",
            "guarantee",
            "ensure",
            "exactly",
            "at least",
            "at most",
            "invariant",
            "contract",
            "interface",
            "endpoint",
            "schema",
        ),
    ),
)

_ENTITY_SIGNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:depends on|dependency on|require(?:s)?|use(?:s)?|integrate(?:s)? "
        r"with|connect(?:s)? to|call(?:s)?|via|backed by)\s+([^\n.;]+)",
        re.IGNORECASE,
    ),
)

_ENTITY_KNOWN_TOKENS = {
    "aws",
    "azure",
    "gcp",
    "kafka",
    "redis",
    "postgres",
    "postgresql",
    "mysql",
    "mongodb",
    "snowflake",
    "bigquery",
    "kubernetes",
    "docker",
    "stripe",
    "twilio",
    "sendgrid",
    "s3",
    "sqs",
    "sns",
    "nats",
    "rabbitmq",
}

_ENTITY_STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "all",
    "as",
    "at",
    "be",
    "by",
    "constraint",
    "constraints",
    "cross",
    "each",
    "for",
    "from",
    "if",
    "in",
    "internal",
    "is",
    "it",
    "library",
    "must",
    "no",
    "not",
    "of",
    "on",
    "or",
    "service",
    "should",
    "system",
    "that",
    "the",
    "this",
    "to",
    "use",
    "uses",
    "via",
    "when",
    "with",
    "api",
    "json",
    "http",
    "https",
    "rest",
    "grpc",
}

_SCOPE_HINTS = {"intra", "inter", "system"}

_TRACE_PREFIX = "bootstrap.meta."
_TEXT_UNAVAILABLE_ANSWER = "[text-unavailable: full constraint text missing from constraints.md]"

_DIMENSION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "legal",
        (
            "legal",
            "license",
            "licensing",
            "compliance",
            "regulation",
            "regulatory",
            "contract",
            "privacy",
        ),
    ),
    (
        "economic",
        (
            "cost",
            "budget",
            "pricing",
            "fee",
            "expense",
            "economic",
            "vendor lock-in",
        ),
    ),
    (
        "organizational",
        (
            "team",
            "staffing",
            "headcount",
            "ownership",
            "organizational",
            "hiring",
            "capacity",
        ),
    ),
    (
        "temporal",
        (
            "timeline",
            "deadline",
            "schedule",
            "deprecation",
            "sunset",
            "eol",
            "migration window",
            "rollout date",
            "time-bound",
        ),
    ),
    (
        "operational",
        (
            "operations",
            "operational",
            "runbook",
            "incident",
            "uptime",
            "deployment",
            "monitoring",
            "maintenance",
            "on-call",
            "sla",
            "slo",
        ),
    ),
)

ParsedConstraint = tuple[str, str, str]


# ------------------------------------------------------------------
# Bootstrap orchestration
# ------------------------------------------------------------------


def bootstrap_constraints_from_intake(
    workspace_root: Path,
    libraries_dir: Path,
    system_dir: Path | None = None,
) -> dict[str, int]:
    """Seed the constraint store from Phase 0 constraint artifacts.

    Per library, bootstrap prefers ``constraints_index.json`` (shallow tags from
    intake) and enriches seeded facts with index metadata. Raw ``constraints.md``
    parsing remains as fallback when the index is unavailable.

    Args:
        workspace_root: Workspace root (for :class:`ConstraintsTool`).
        libraries_dir: Directory containing per-library sub-directories,
            each potentially holding ``constraints_index.json`` and/or
            ``constraints.md``.
        system_dir: Optional directory with a system-level ``constraints.md``.

    Returns:
        Mapping of slice_id -> number of constraints bootstrapped.
    """
    adapter = ConstraintsTool(workspace_root=workspace_root)
    result: dict[str, int] = {}

    # System-level constraints
    if system_dir is not None:
        facts = _bootstrap_system_facts(system_dir)
        if facts:
            adapter.save_facts("__system__", facts)
            result["__system__"] = len(facts)
            logger.info("Bootstrapped %d system constraints", len(facts))

    # Per-library constraints
    if libraries_dir.is_dir():
        for lib_dir in sorted(libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue

            slice_id = lib_dir.name
            facts = _bootstrap_library_facts(lib_dir)
            if facts:
                adapter.save_facts(slice_id, facts)
                result[slice_id] = len(facts)
                logger.info(
                    "Bootstrapped %d constraints for library '%s'",
                    len(facts),
                    slice_id,
                )

    return result


def _bootstrap_system_facts(system_dir: Path) -> list[ConstraintFact]:
    """Build system-level facts from ``system/constraints.md``."""
    sys_md = system_dir / "constraints.md"
    parsed = _load_parsed_constraints(sys_md)
    return _parsed_to_facts(parsed, source="steering")


def _bootstrap_library_facts(lib_dir: Path) -> list[ConstraintFact]:
    """Build library facts from index-first intake artifacts."""
    index_path = lib_dir / "constraints_index.json"
    md_path = lib_dir / "constraints.md"
    slice_id = lib_dir.name

    if index_path.exists():
        index_entries = _read_constraints_index(index_path)
        if index_entries:
            parsed_lookup = _parsed_by_id(_load_parsed_constraints(md_path))
            return _index_to_facts(
                index_entries,
                parsed_lookup,
                source="existing",
                slice_id=slice_id,
            )

        logger.warning(
            "Constraint index exists but has no valid entries for '%s'; "
            "falling back to constraints.md",
            slice_id,
        )

    parsed = _load_parsed_constraints(md_path)
    return _parsed_to_facts(parsed, source="existing")


# ------------------------------------------------------------------
# Parsing
# ------------------------------------------------------------------


def _load_parsed_constraints(md_path: Path) -> list[ParsedConstraint]:
    if not md_path.exists():
        return []
    return _parse_constraints_md(md_path.read_text(encoding="utf-8"))


def _parse_constraints_md(content: str) -> list[ParsedConstraint]:
    """Parse ``([=CON-LIB-001])`` markers and their verbatim text blocks.

    Returns:
        List of ``(element_id, heading, body)`` tuples where *heading* is
        the text on the same line as the marker and *body* is the verbatim
        block following it until the next marker or end of file.
    """
    lines = content.split("\n")
    entries: list[ParsedConstraint] = []
    current_id: str | None = None
    current_heading = ""
    body_lines: list[str] = []

    for line in lines:
        marker = _MARKER_RE.search(line)
        if marker:
            # Flush previous entry.
            if current_id is not None:
                entries.append((current_id, current_heading, "\n".join(body_lines).strip()))

            current_id = marker.group(1)
            # Heading is line content minus the marker itself.
            current_heading = _MARKER_RE.sub("", line).strip()
            body_lines = []
        elif current_id is not None:
            body_lines.append(line)

    # Flush last entry.
    if current_id is not None:
        entries.append((current_id, current_heading, "\n".join(body_lines).strip()))

    return entries


def _parsed_to_facts(
    parsed: list[ParsedConstraint],
    source: Literal["user", "research", "steering", "existing"] = "existing",
) -> list[ConstraintFact]:
    """Convert parsed triples into :class:`ConstraintFact` objects."""
    facts: list[ConstraintFact] = []
    for element_id, heading, body in parsed:
        question = heading if heading else f"Constraint {element_id}"
        answer = body if body else heading
        facts.append(
            ConstraintFact(
                constraint_id=element_id,
                question=question,
                answer=answer,
                source=source,
                confidence=1.0,
                validated=True,
            )
        )
    return facts


# ------------------------------------------------------------------
# Index-based bootstrapping
# ------------------------------------------------------------------


def _read_constraints_index(path: Path) -> list[ConstraintIndexEntry]:
    """Read ``constraints_index.json`` and return normalized entries."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed reading constraint index %s: %s", path, exc)
        return []

    if not isinstance(raw, list):
        logger.warning("Constraint index %s is not a list; ignoring", path)
        return []

    entries: list[ConstraintIndexEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = ConstraintIndexEntry.from_dict(item)
        entry.element_id = str(entry.element_id).strip()
        entry.subtype = _normalize_subtype(str(entry.subtype).strip())
        entry.scope_hint = _normalize_scope_hint(str(entry.scope_hint).strip())
        entry.entities = _normalize_entities(entry.entities)
        entry.text_preview = str(entry.text_preview).strip()
        if entry.element_id:
            entries.append(entry)
    return entries


def _parsed_by_id(parsed: list[ParsedConstraint]) -> dict[str, tuple[str, str]]:
    """Map parsed constraints to ``element_id -> (heading, body)``."""
    by_id: dict[str, tuple[str, str]] = {}
    for element_id, heading, body in parsed:
        key = str(element_id).strip()
        if key:
            by_id[key] = (heading, body)
    return by_id


def _index_to_facts(
    index_entries: list[ConstraintIndexEntry],
    parsed_lookup: dict[str, tuple[str, str]],
    *,
    source: Literal["user", "research", "steering", "existing"] = "existing",
    slice_id: str,
) -> list[ConstraintFact]:
    """Build facts using index metadata plus parsed text when available."""
    facts: list[ConstraintFact] = []

    for entry in index_entries:
        heading, body = parsed_lookup.get(entry.element_id, ("", ""))
        heading = str(heading).strip()
        body = str(body).strip()
        preview = str(entry.text_preview).strip()
        question = heading if heading else f"Constraint {entry.element_id}"
        trace = _trace_from_index(entry)

        if body:
            answer = body
            confidence = 1.0
            validated = True
        elif heading:
            answer = heading
            confidence = 1.0
            validated = True
            trace.append(f"{_TRACE_PREFIX}answer_source=heading_only")
        else:
            answer = _TEXT_UNAVAILABLE_ANSWER
            confidence = 0.0
            validated = False
            trace.append(f"{_TRACE_PREFIX}text_unavailable=true")
            if preview:
                trace.append(f"{_TRACE_PREFIX}text_preview={preview}")

        dimension = _dimension_from_subtype(
            entry.subtype,
            text=f"{heading}\n{body}\n{preview}",
        )
        if dimension == "unknown":
            trace.append(f"{_TRACE_PREFIX}dimension_unknown=true")

        facts.append(
            ConstraintFact(
                constraint_id=entry.element_id,
                question=question,
                answer=answer,
                source=source,
                confidence=confidence,
                validated=validated,
                dimension=dimension,  # type: ignore[arg-type]
                scope=_scope_from_hint(entry.scope_hint, slice_id),
                trace=trace,
            )
        )

    return facts


def _scope_from_hint(scope_hint: str, slice_id: str) -> str:
    """Project scope hint into ``ConstraintFact.scope`` format."""
    if scope_hint == "system":
        return "system"
    if scope_hint == "inter":
        return f"inter:{slice_id}"
    return f"intra:{slice_id}"


def _dimension_from_subtype(
    subtype: str,
    *,
    text: str = "",
) -> Literal[
    "software",
    "legal",
    "economic",
    "organizational",
    "temporal",
    "operational",
    "unknown",
]:
    subtype_token = str(subtype).strip().lower()

    if subtype_token in {"compliance", "privacy"}:
        return "legal"
    if subtype_token == "tradeoff_preference":
        return "economic"
    if subtype_token == "domain_marker":
        return "organizational"
    if subtype_token in {"ops", "performance"}:
        return "operational"

    text_lower = str(text).lower()
    for dimension, keywords in _DIMENSION_KEYWORDS:
        if any(keyword in text_lower for keyword in keywords):
            return dimension  # type: ignore[return-value]

    if subtype_token in {"security", "dependency_declaration", "policy", "invariant"}:
        return "software"
    return "unknown"


def _trace_from_index(entry: ConstraintIndexEntry) -> list[str]:
    """Encode index metadata into fact trace without changing fact authority."""
    trace = [
        f"{_TRACE_PREFIX}source=constraints_index",
        f"{_TRACE_PREFIX}subtype={entry.subtype}",
        f"{_TRACE_PREFIX}scope_hint={entry.scope_hint}",
    ]
    for entity in entry.entities:
        trace.append(f"{_TRACE_PREFIX}entity={entity}")
    return trace


# ------------------------------------------------------------------
# Index classification
# ------------------------------------------------------------------


def _classify_constraint_subtype(element_id: str, text: str) -> ConstraintIndexEntry:
    """Classify a constraint using SEC-108 shallow subtype rules.

    Applies ordered keyword heuristics to emit only the SEC-108 subtype enum.

    Args:
        element_id: The constraint identifier.
        text: The full constraint text (heading + body).

    Returns:
        A :class:`ConstraintIndexEntry` with classified subtype and scope.
    """
    text_lower = text.lower()

    # Determine subtype by keyword match (first match wins, ordered by specificity).
    subtype = "policy"
    for candidate, keywords in _SUBTYPE_KEYWORDS:
        if any(keyword in text_lower for keyword in keywords):
            subtype = candidate
            break
    subtype = _normalize_subtype(subtype)

    # Determine scope hint from the element_id pattern.
    scope_hint = "intra"
    id_upper = element_id.upper()
    if "SYS" in id_upper or "SYSTEM" in id_upper:
        scope_hint = "system"
    elif "->" in text or "cross" in text_lower or re.search(r"\binter\b", text_lower):
        scope_hint = "inter"

    # Extract dependency/provider-like entity mentions.
    entities = _extract_dependency_entities(text)

    preview = text[:120].replace("\n", " ").strip()
    if len(text) > 120:
        preview += "..."

    return ConstraintIndexEntry(
        element_id=element_id,
        subtype=subtype,
        scope_hint=scope_hint,
        entities=entities,
        text_preview=preview,
    )


def classify_constraint_subtype(element_id: str, text: str) -> ConstraintIndexEntry:
    """Public classifier for constraint index projection."""
    return _classify_constraint_subtype(element_id, text)


# ------------------------------------------------------------------
# Normalization helpers
# ------------------------------------------------------------------


def _normalize_subtype(subtype: str) -> str:
    """Normalize any subtype string to the spec-defined SEC-108 vocabulary."""
    token = str(subtype).strip().lower()
    if token in _ALLOWED_SUBTYPES:
        return token

    legacy_remap = {
        "api_contract": "invariant",
        "data_model": "invariant",
        "concurrency": "policy",
        "error_handling": "policy",
        "deployment": "ops",
        "general": "policy",
    }
    if token in legacy_remap:
        return legacy_remap[token]

    return "policy"


def _normalize_scope_hint(scope_hint: str) -> str:
    token = str(scope_hint).strip().lower()
    if token in _SCOPE_HINTS:
        return token
    return "intra"


def _normalize_entities(raw_entities: object) -> list[str]:
    if not isinstance(raw_entities, list):
        return []

    entities: list[str] = []
    for raw in raw_entities:
        candidate = _normalize_entity_candidate(str(raw), from_signal=True)
        if candidate and candidate not in entities:
            entities.append(candidate)
    return entities[:10]


def _extract_dependency_entities(text: str) -> list[str]:
    """Extract dependency/provider-like entities from a constraint text."""
    entities: list[str] = []

    def add_candidate(value: str, *, from_signal: bool) -> None:
        candidate = _normalize_entity_candidate(value, from_signal=from_signal)
        if candidate and candidate not in entities:
            entities.append(candidate)

    for pattern in _ENTITY_SIGNAL_PATTERNS:
        for match in pattern.finditer(text):
            chunk = match.group(1).strip()
            for part in re.split(
                r",|;|\band\b|\bor\b|\bfor\b|\bto\b|\bfrom\b|\bwith\b|\busing\b", chunk
            ):
                add_candidate(part, from_signal=True)

    # Keep non-signal extraction narrow: known dependency/provider tokens only.
    for match in re.finditer(r"\b[A-Za-z][\w-]{1,32}\b", text):
        token = match.group(0)
        if token.lower() in _ENTITY_KNOWN_TOKENS:
            add_candidate(token, from_signal=False)

    return entities[:10]


def _normalize_entity_candidate(value: str, *, from_signal: bool) -> str:
    text = re.sub(r"\s+", " ", value).strip(" \t\n\r.,;:()[]{}\"'`")
    if not text:
        return ""

    tokens = [token for token in text.split(" ") if token]
    while tokens and tokens[0].lower() in {"a", "an", "the"}:
        tokens.pop(0)
    if not tokens:
        return ""

    normalized = " ".join(tokens[:4]).strip(" \t\n\r.,;:()[]{}\"'`")
    if not normalized:
        return ""

    lower = normalized.lower()
    if lower in _ENTITY_STOPWORDS:
        return ""

    words = normalized.split(" ")
    if len(words) > 1:
        if all(word.lower() in _ENTITY_STOPWORDS for word in words):
            return ""
        if not any(_looks_dependency_like_token(word) for word in words):
            return ""
        return normalized

    token = words[0]
    token_lower = token.lower()

    if token_lower in _ENTITY_KNOWN_TOKENS:
        return token

    if (
        from_signal
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", token)
        and token_lower not in _ENTITY_STOPWORDS
        and len(token) >= 3
        and _looks_dependency_like_token(token)
    ):
        return token

    if not from_signal and _looks_dependency_like_token(token):
        return token

    return ""


def _looks_dependency_like_token(token: str) -> bool:
    lower = token.lower()
    if lower in _ENTITY_KNOWN_TOKENS:
        return True
    if token[:1].isupper() and len(token) >= 3 and lower not in _ENTITY_STOPWORDS:
        return True
    if re.search(r"[a-z][A-Z]", token):
        return True
    if re.fullmatch(r"[A-Z]{2,}[A-Z0-9_-]*", token):
        return True
    return bool(any(char.isdigit() for char in token))
