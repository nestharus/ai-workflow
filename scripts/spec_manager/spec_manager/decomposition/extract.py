"""Extraction operations for spec decomposition."""

from __future__ import annotations

from pathlib import Path


def extract_entity_to_document(
    workspace: Path,
    entity_id: str,
    entity_name: str,
    evidence: list[dict],
) -> Path:
    """Extract entity information to an isolated document.

    Creates a document in {workspace}/entities/{entity_id}.md containing:
    - Entity ID and name
    - All evidence with source citations
    - Line number references for traceability

    Args:
        workspace: Workspace directory
        entity_id: Generated entity ID (e.g., "E-001")
        entity_name: Human-readable entity name
        evidence: List of evidence dicts with file, line, text

    Returns:
        Path to created entity document
    """
    entity_file = workspace / "entities" / f"{entity_id}.md"

    lines = [
        f"# {entity_name}",
        "",
        f"**ID**: `{entity_id}`",
        "",
        "## Evidence",
        "",
    ]

    for i, ev in enumerate(evidence, 1):
        lines.append(f"### Source {i}")
        lines.append(f"- **File**: `{ev['file']}`")
        lines.append(f"- **Line**: {ev['line']}")
        lines.append("")
        lines.append(f"> {ev['text']}")
        lines.append("")

    entity_file.write_text("\n".join(lines))
    return entity_file


def extract_relation_to_document(
    workspace: Path,
    relation_id: str,
    from_entity: str,
    to_entity: str,
    relation_type: str,
    evidence: dict,
) -> Path:
    """Extract relation information to an isolated document.

    Creates a document in {workspace}/relations/{relation_id}.md containing:
    - Relation ID and type
    - From/to entity references
    - Evidence with source citation

    Args:
        workspace: Workspace directory
        relation_id: Generated relation ID (e.g., "R-001")
        from_entity: Source entity ID
        to_entity: Target entity ID
        relation_type: Type of relation (uses, depends_on, etc.)
        evidence: Evidence dict with file, line, text

    Returns:
        Path to created relation document
    """
    relation_file = workspace / "relations" / f"{relation_id}.md"

    lines = [
        f"# Relation: {from_entity} → {to_entity}",
        "",
        f"**ID**: `{relation_id}`",
        f"**Type**: `{relation_type}`",
        "",
        "## Entities",
        "",
        f"- **From**: `{from_entity}`",
        f"- **To**: `{to_entity}`",
        "",
        "## Evidence",
        "",
        f"- **File**: `{evidence['file']}`",
        f"- **Line**: {evidence['line']}",
        "",
        f"> {evidence['text']}",
        "",
    ]

    relation_file.write_text("\n".join(lines))
    return relation_file


def extract_context_to_document(
    workspace: Path,
    context_id: str,
    entity_id: str,
    context_type: str,
    evidence: dict,
) -> Path:
    """Extract context information to an isolated document.

    Creates a document in {workspace}/context/{context_id}.md containing:
    - Context ID and type
    - Associated entity reference
    - Evidence with source citation

    Args:
        workspace: Workspace directory
        context_id: Generated context ID (e.g., "C-001")
        entity_id: Entity this context relates to
        context_type: Type of context (decision, constraint, etc.)
        evidence: Evidence dict with file, line, text

    Returns:
        Path to created context document
    """
    context_file = workspace / "context" / f"{context_id}.md"

    # Handle nested evidence structure
    ev = evidence.get("evidence", evidence)

    lines = [
        f"# Context for {entity_id}",
        "",
        f"**ID**: `{context_id}`",
        f"**Type**: `{context_type}`",
        f"**Entity**: `{entity_id}`",
        "",
        "## Evidence",
        "",
        f"- **File**: `{ev['file']}`",
        f"- **Line**: {ev['line']}",
        "",
        f"> {ev['text']}",
        "",
    ]

    context_file.write_text("\n".join(lines))
    return context_file


def append_evidence_to_entity(
    workspace: Path,
    entity_id: str,
    evidence: dict,
) -> None:
    """Append additional evidence to an existing entity document.

    Args:
        workspace: Workspace directory
        entity_id: Entity ID to append to
        evidence: Evidence dict with file, line, text
    """
    entity_file = workspace / "entities" / f"{entity_id}.md"

    if not entity_file.exists():
        raise FileNotFoundError(f"Entity file not found: {entity_file}")

    content = entity_file.read_text()

    # Count existing sources
    source_count = content.count("### Source ")
    next_source = source_count + 1

    additional = [
        "",
        f"### Source {next_source}",
        f"- **File**: `{evidence['file']}`",
        f"- **Line**: {evidence['line']}",
        "",
        f"> {evidence['text']}",
        "",
    ]

    entity_file.write_text(content + "\n".join(additional))


def create_rich_relation_document(
    workspace: Path,
    relation_id: str,
    snippet_id: str,
    source_entity: str,
    source_entity_name: str,
    targets: list[dict],
    relationship_type: str,
    relationship_context: str,
    original_text: str,
    file: str,
    line: int,
) -> Path:
    """Create a rich relation document with full context.

    Args:
        workspace: Workspace directory
        relation_id: Relation ID (e.g., "R-001")
        snippet_id: Source snippet ID (e.g., "S-001")
        source_entity: Source entity ID
        source_entity_name: Source entity name
        targets: List of target dicts with id, name, discovered_from_snippet
        relationship_type: Type of relationship
        relationship_context: Context describing HOW they relate
        original_text: Original text from spec
        file: Source file
        line: Source line number

    Returns:
        Path to created relation document
    """
    relation_file = workspace / "relations" / f"{relation_id}.md"

    lines = [
        f"# Relation {relation_id}",
        "",
        f"**ID**: `{relation_id}`",
        f"**Snippet**: `{snippet_id}`",
        "",
        "## Entities",
        "",
        f"- **Source**: `{source_entity}` ({source_entity_name})",
        "- **Targets**:",
    ]

    for target in targets:
        discovered_note = (
            " - *discovered from this snippet*" if target.get("discovered_from_snippet") else ""
        )
        lines.append(f"  - `{target['id']}` ({target['name']}){discovered_note}")

    lines.extend(
        [
            "",
            "## Relationship",
            "",
            f"- **Type**: `{relationship_type}`",
            f"- **Context**: {relationship_context}",
            "",
            "## Original Text",
            "",
            f"> {original_text}",
            "",
            "## Source Location",
            "",
            f"- **File**: `{file}`",
            f"- **Line**: {line}",
            "",
        ]
    )

    relation_file.write_text("\n".join(lines))
    return relation_file


def create_discovered_entity_document(
    workspace: Path,
    entity_id: str,
    entity_name: str,
    keywords: list[str],
    discovered_from_snippet: str,
    context_text: str,
) -> Path:
    """Create an entity document for an entity discovered from a relation snippet.

    Args:
        workspace: Workspace directory
        entity_id: Entity ID
        entity_name: Entity name
        keywords: Keywords for the entity
        discovered_from_snippet: Snippet ID where discovered
        context_text: Context from the snippet

    Returns:
        Path to created entity document
    """
    entity_file = workspace / "entities" / f"{entity_id}.md"

    lines = [
        f"# {entity_name}",
        "",
        f"**ID**: `{entity_id}`",
        f"**Discovered From**: `{discovered_from_snippet}`",
        "",
        "## Discovery Context",
        "",
        f"> {context_text}",
        "",
        "## Keywords",
        "",
    ]

    for kw in keywords:
        lines.append(f"- {kw}")

    lines.extend(
        [
            "",
            "## Evidence",
            "",
            "*Entity discovered from relation snippet - no direct definition found yet.*",
            "",
        ]
    )

    entity_file.write_text("\n".join(lines))
    return entity_file
