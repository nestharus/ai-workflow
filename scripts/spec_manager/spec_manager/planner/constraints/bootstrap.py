"""Bootstrap constraints from Phase 0 intake artifacts.

Parses ``constraints.md`` files produced during intake (Phase 0) and seeds the
constraint store so that downstream layers can query established constraints
without re-parsing the raw spec.

Constraint markers use the format ``([=CON-LIB-001])`` followed by a verbatim
text block describing the constraint.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter
from spec_manager.planner.constraints.types import (
    ConstraintFact,
    ConstraintIndexEntry,
)

logger = logging.getLogger(__name__)

# Regex for ``([=CON-LIB-001])`` style markers.
_MARKER_RE = re.compile(
    r"\(\[=([A-Z0-9][\w-]*)\]\)",
    re.IGNORECASE,
)

# Keyword → subtype mapping for heuristic classification.
_SUBTYPE_KEYWORDS: dict[str, list[str]] = {
    "performance": ["latency", "throughput", "performance", "sla", "response time", "benchmark"],
    "security": [
        "auth",
        "security",
        "encrypt",
        "credential",
        "permission",
        "access control",
        "token",
    ],
    "api_contract": ["api", "contract", "endpoint", "interface", "protocol", "rest", "grpc"],
    "data_model": [
        "schema",
        "table",
        "column",
        "field",
        "entity",
        "relation",
        "data model",
        "database",
    ],
    "concurrency": ["thread", "concurrent", "lock", "mutex", "async", "parallel", "race"],
    "error_handling": ["error", "exception", "retry", "fallback", "timeout", "circuit breaker"],
    "compliance": ["compliance", "regulation", "gdpr", "hipaa", "audit", "legal"],
    "deployment": [
        "deploy",
        "infrastructure",
        "container",
        "kubernetes",
        "docker",
        "ci/cd",
        "pipeline",
    ],
}


def bootstrap_constraints_from_intake(
    workspace_root: Path,
    libraries_dir: Path,
    system_dir: Path | None = None,
) -> dict[str, int]:
    """Parse constraints.md files and seed the constraint store.

    Scans *libraries_dir* for per-library ``constraints.md`` files and
    optionally a system-level directory for cross-cutting constraints.

    Args:
        workspace_root: Workspace root (for :class:`ConstraintStoreAdapter`).
        libraries_dir: Directory containing per-library sub-directories,
            each potentially holding a ``constraints.md``.
        system_dir: Optional directory with a system-level ``constraints.md``.

    Returns:
        Mapping of slice_id -> number of constraints bootstrapped.
    """
    adapter = ConstraintStoreAdapter(workspace_root)
    result: dict[str, int] = {}

    # System-level constraints
    if system_dir is not None:
        sys_md = system_dir / "constraints.md"
        if sys_md.exists():
            content = sys_md.read_text(encoding="utf-8")
            facts = _parsed_to_facts(_parse_constraints_md(content), source="steering")
            if facts:
                adapter.save_facts("__system__", facts)
                result["__system__"] = len(facts)
                logger.info("Bootstrapped %d system constraints", len(facts))

    # Per-library constraints
    if libraries_dir.is_dir():
        for lib_dir in sorted(libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            md_path = lib_dir / "constraints.md"
            if not md_path.exists():
                continue

            slice_id = lib_dir.name
            content = md_path.read_text(encoding="utf-8")
            facts = _parsed_to_facts(_parse_constraints_md(content), source="existing")
            if facts:
                adapter.save_facts(slice_id, facts)
                result[slice_id] = len(facts)
                logger.info(
                    "Bootstrapped %d constraints for library '%s'",
                    len(facts),
                    slice_id,
                )

    return result


# ------------------------------------------------------------------
# Parsing
# ------------------------------------------------------------------


def _parse_constraints_md(content: str) -> list[tuple[str, str, str]]:
    """Parse ``([=CON-LIB-001])`` markers and their verbatim text blocks.

    Returns:
        List of ``(element_id, heading, body)`` tuples where *heading* is
        the text on the same line as the marker and *body* is the verbatim
        block following it until the next marker or end of file.
    """
    lines = content.split("\n")
    entries: list[tuple[str, str, str]] = []
    current_id: str | None = None
    current_heading = ""
    body_lines: list[str] = []

    for line in lines:
        m = _MARKER_RE.search(line)
        if m:
            # Flush previous entry
            if current_id is not None:
                body = "\n".join(body_lines).strip()
                entries.append((current_id, current_heading, body))

            current_id = m.group(1)
            # Heading is the line content minus the marker itself
            current_heading = _MARKER_RE.sub("", line).strip()
            body_lines = []
        elif current_id is not None:
            body_lines.append(line)

    # Flush last entry
    if current_id is not None:
        body = "\n".join(body_lines).strip()
        entries.append((current_id, current_heading, body))

    return entries


def _parsed_to_facts(
    parsed: list[tuple[str, str, str]],
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
# Index classification
# ------------------------------------------------------------------


def _classify_constraint_subtype(element_id: str, text: str) -> ConstraintIndexEntry:
    """Classify a constraint's subtype using keyword heuristics.

    Examines the constraint text for domain-specific keywords and returns
    a :class:`ConstraintIndexEntry` with the best-matching subtype.

    Args:
        element_id: The constraint identifier.
        text: The full constraint text (heading + body).

    Returns:
        A :class:`ConstraintIndexEntry` with classified subtype and scope.
    """
    text_lower = text.lower()

    # Determine subtype by keyword match (first match wins, ordered by specificity)
    subtype = "general"
    for candidate, keywords in _SUBTYPE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            subtype = candidate
            break

    # Determine scope hint from the element_id pattern
    scope_hint = "intra"
    id_upper = element_id.upper()
    if "SYS" in id_upper or "SYSTEM" in id_upper:
        scope_hint = "system"
    elif "->" in text or "cross" in text_lower or re.search(r"\binter\b", text_lower):
        scope_hint = "inter"

    # Extract entity-like tokens (capitalized words that aren't common English)
    _common = {
        "the",
        "and",
        "for",
        "with",
        "must",
        "shall",
        "should",
        "will",
        "not",
        "all",
        "any",
        "each",
        "this",
        "that",
    }
    entities = []
    for word in text.split():
        clean = word.strip(".,;:()[]{}\"'")
        if (
            clean
            and clean[0].isupper()
            and clean.lower() not in _common
            and len(clean) > 2
            and clean not in entities
        ):
            entities.append(clean)

    preview = text[:120].replace("\n", " ").strip()
    if len(text) > 120:
        preview += "..."

    return ConstraintIndexEntry(
        element_id=element_id,
        subtype=subtype,
        scope_hint=scope_hint,
        entities=entities[:10],
        text_preview=preview,
    )
