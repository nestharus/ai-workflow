"""Finalization operations for spec decomposition."""

from __future__ import annotations

import json
from pathlib import Path

from spec_manager.decomposition.id_generator import (
    IDType,
    get_ids_by_type,
    load_id_map,
)
from spec_manager.decomposition.staging import get_staged_from_path


def _skip_header_lines(content_lines: list[str]) -> int:
    """Return the index where staged content begins (after tool-added header)."""
    i = 0
    # Tool-generated headers are one or more HTML comment lines followed by
    # one or more blank lines.
    while i < len(content_lines) and content_lines[i].startswith("<!--"):
        i += 1
    while i < len(content_lines) and content_lines[i].strip() == "":
        i += 1
    return i


def _relation_edges(sources: list[dict]) -> list[dict]:
    """Normalize various relation encodings into a list of edges."""
    edges: list[dict] = []
    for src in sources:
        rel_type = src.get("relation_type") or src.get("relationship") or "?"
        if src.get("from") and src.get("to"):
            edges.append({"from": src.get("from"), "to": src.get("to"), "type": rel_type})
            continue

        # Legacy shapes
        if src.get("source") and src.get("target"):
            edges.append({"from": src.get("source"), "to": src.get("target"), "type": rel_type})
            continue

        # Rich relation shape
        if src.get("source") and isinstance(src.get("targets"), list):
            for t in src.get("targets", []):
                edges.append({"from": src.get("source"), "to": t, "type": rel_type})
            continue

    # Deduplicate
    seen = set()
    out = []
    for e in edges:
        k = (e.get("from"), e.get("to"), e.get("type"))
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out


def finalize_output(workspace: Path) -> None:
    """Generate final output documents from extraction results.

    Creates:
    - {workspace}/output/entities.md - Combined entity reference
    - {workspace}/output/relations.md - Combined relations reference
    - {workspace}/output/source_with_ids.md - Annotated original
    - {workspace}/output/summary.json - Statistics and structure
    """
    output_dir = workspace / "output"
    output_dir.mkdir(exist_ok=True)

    id_map = load_id_map(workspace)

    # Generate entities.md
    _generate_entities_doc(workspace, output_dir, id_map)

    # Generate relations.md
    _generate_relations_doc(workspace, output_dir, id_map)

    # Generate source_with_ids.md
    _generate_annotated_source(workspace, output_dir)

    # Generate summary.json
    _generate_summary(workspace, output_dir, id_map)


def _generate_entities_doc(workspace: Path, output_dir: Path, id_map: dict) -> None:
    """Generate combined entities reference document."""
    entities_dir = workspace / "entities"
    output_file = output_dir / "entities.md"

    lines = [
        "# Entities Reference",
        "",
        "This document contains all extracted entities from the specification.",
        "",
        "---",
        "",
    ]

    entity_ids = sorted(get_ids_by_type(id_map, IDType.ENTITY))

    for entity_id in entity_ids:
        entity_file = entities_dir / f"{entity_id}.md"
        if entity_file.exists():
            content = entity_file.read_text()
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

    output_file.write_text("\n".join(lines))


def _generate_relations_doc(workspace: Path, output_dir: Path, id_map: dict) -> None:
    """Generate combined relations reference document."""
    relations_dir = workspace / "relations"
    output_file = output_dir / "relations.md"

    lines = [
        "# Relations Reference",
        "",
        "This document contains all extracted relations between entities.",
        "",
        "## Relation Graph",
        "",
    ]

    # Build relation summary
    relation_ids = sorted(get_ids_by_type(id_map, IDType.RELATION))

    if relation_ids:
        lines.append("```")
        for rel_id in relation_ids:
            sources = id_map.get(rel_id, [])
            for edge in _relation_edges(sources):
                lines.append(
                    f"{edge.get('from', '?')} --[{edge.get('type', '?')}]--> "
                    f"{edge.get('to', '?')}  ({rel_id})"
                )
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Include full relation documents
    for rel_id in relation_ids:
        rel_file = relations_dir / f"{rel_id}.md"
        if rel_file.exists():
            content = rel_file.read_text()
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

    output_file.write_text("\n".join(lines))


def _generate_annotated_source(workspace: Path, output_dir: Path) -> None:
    """Generate combined annotated source document."""
    staging_dir = workspace / "staging" / "discovery"
    output_file = output_dir / "source_with_ids.md"

    lines = [
        "# Annotated Source",
        "",
        "This document shows the original specification with embedded IDs.",
        "",
        "---",
        "",
    ]

    for staging_file in sorted(staging_dir.glob("*_staged.md")):
        content = staging_file.read_text()
        content_lines = content.split("\n")

        original = get_staged_from_path(staging_file) or staging_file.name
        lines.append(f"## {original}")
        lines.append("")

        start_idx = _skip_header_lines(content_lines)
        lines.extend(content_lines[start_idx:])
        lines.append("")
        lines.append("---")
        lines.append("")

    output_file.write_text("\n".join(lines))


def _generate_summary(workspace: Path, output_dir: Path, id_map: dict) -> None:
    """Generate summary statistics document."""
    output_file = output_dir / "summary.json"

    entity_ids = get_ids_by_type(id_map, IDType.ENTITY)
    relation_ids = get_ids_by_type(id_map, IDType.RELATION)
    context_ids = get_ids_by_type(id_map, IDType.CONTEXT)
    composition_ids = get_ids_by_type(id_map, IDType.COMPOSITION)

    # Count total evidence
    total_evidence = sum(len(sources) for sources in id_map.values())

    # Build entity names from files
    entity_names = {}
    entities_dir = workspace / "entities"
    for entity_id in entity_ids:
        entity_file = entities_dir / f"{entity_id}.md"
        if entity_file.exists():
            first_line = entity_file.read_text().split("\n")[0]
            if first_line.startswith("# "):
                entity_names[entity_id] = first_line[2:]

    # Build relation summary
    relations_summary: list[dict] = []
    for rel_id in relation_ids:
        for edge in _relation_edges(id_map.get(rel_id, [])):
            relations_summary.append(
                {
                    "id": rel_id,
                    "from": edge.get("from"),
                    "to": edge.get("to"),
                    "type": edge.get("type"),
                }
            )

    summary = {
        "statistics": {
            "total_entities": len(entity_ids),
            "total_relations": len(relation_ids),
            "total_contexts": len(context_ids),
            "total_compositions": len(composition_ids),
            "total_evidence_items": total_evidence,
        },
        "entities": entity_names,
        "relations": relations_summary,
        "id_types": {
            "E": "Entity - A distinct concept or component",
            "R": "Relation - How entities connect",
            "C": "Context - Background information about an entity",
            "X": "Composition - Entity composed of other entities",
            "F": "Fact - A tagged source line (used for deduplication)",
        },
    }

    output_file.write_text(json.dumps(summary, indent=2))
