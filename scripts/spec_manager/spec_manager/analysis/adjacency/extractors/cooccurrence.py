"""Entity co-occurrence extractor from spec content.

Extracts adjacency signals from spec markdown -- algorithms and entities
discussed in the same section form co-occurrence edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

from spec_manager.core.annotations import AnnotationParser
from spec_manager.core.sections import SectionExtractor

from ..graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType


@dataclass
class CoOccurrence:
    """A detected co-occurrence of two entities in the same context."""

    entity_a: str
    entity_b: str
    section_id: str  # which spec section they co-occur in
    source_file: str
    proximity: float  # 0.0-1.0, closer = higher (same paragraph > same section)


def extract_cooccurrence_graph(
    spec_paths: list[Path],
    window_mode: str = "section",
) -> AdjacencyGraph:
    """Build co-occurrence graph from spec markdown files.

    Entities (algorithms, data structures, components) that appear in the
    same section/window form weighted edges.

    Uses the existing SectionExtractor and AnnotationParser from core/
    to identify declared entities and their references.

    Args:
        spec_paths: Markdown spec files to analyze
        window_mode: "section" (default) or "paragraph" granularity

    Returns:
        AdjacencyGraph with SignalType.CO_OCCURRENCE edges
    """
    graph = AdjacencyGraph()
    all_cooccurrences: list[CoOccurrence] = []

    for path in spec_paths:
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        source_file = str(path)

        if window_mode == "paragraph":
            section_entities = _extract_entity_mentions_by_paragraph(content, source_file)
        else:
            section_entities = _extract_entity_mentions(content, source_file)

        cooccurrences = _build_cooccurrence_edges(section_entities, source_file)
        all_cooccurrences.extend(cooccurrences)

    # Build graph from co-occurrences
    for cooc in all_cooccurrences:
        # Add nodes
        graph.add_node(
            cooc.entity_a,
            NodeInfo(
                node_id=cooc.entity_a,
                node_type="entity",
                metadata={"source_file": cooc.source_file},
            ),
        )
        graph.add_node(
            cooc.entity_b,
            NodeInfo(
                node_id=cooc.entity_b,
                node_type="entity",
                metadata={"source_file": cooc.source_file},
            ),
        )

        # Add edge (bidirectional)
        weight = 0.3 * cooc.proximity
        signal = EdgeSignal(
            signal_type=SignalType.CO_OCCURRENCE,
            weight=weight,
            details={
                "section_id": cooc.section_id,
                "source_file": cooc.source_file,
                "proximity": cooc.proximity,
            },
        )
        graph.add_edge(cooc.entity_a, cooc.entity_b, signal)
        graph.add_edge(cooc.entity_b, cooc.entity_a, signal)

    return graph


def _extract_entity_mentions(
    content: str,
    source_file: str,
) -> dict[str, list[str]]:
    """Extract entity IDs mentioned in each section.

    Uses AnnotationParser to find declarations ([=ID]) and
    references (@[+ID], @[=ID]) within each section boundary
    identified by SectionExtractor.

    Returns:
        Dict mapping section_id -> list of entity IDs mentioned
    """
    extractor = SectionExtractor()
    parser = AnnotationParser()

    result = extractor.extract(content, validate_ids=False)

    section_entities: dict[str, list[str]] = {}

    for section_id, section in result.sections.items():
        entities: list[str] = []
        full_content = section.full_content

        # Collect declarations
        for annotation in parser.parse_declarations(full_content):
            if annotation.id_value not in entities:
                entities.append(annotation.id_value)

        # Collect references
        for annotation in parser.parse_references(full_content):
            if annotation.id_value not in entities:
                entities.append(annotation.id_value)

        if entities:
            section_entities[section_id] = entities

    # Also check orphan content for references
    if result.orphan_content.strip():
        orphan_entities: list[str] = []
        for annotation in parser.parse_declarations(result.orphan_content):
            if annotation.id_value not in orphan_entities:
                orphan_entities.append(annotation.id_value)
        for annotation in parser.parse_references(result.orphan_content):
            if annotation.id_value not in orphan_entities:
                orphan_entities.append(annotation.id_value)
        if orphan_entities:
            section_entities["_orphan"] = orphan_entities

    return section_entities


def _extract_entity_mentions_by_paragraph(
    content: str,
    source_file: str,
) -> dict[str, list[str]]:
    """Extract entity IDs mentioned in each paragraph.

    Paragraphs are separated by blank lines. This provides finer granularity
    than section-based extraction.

    Returns:
        Dict mapping paragraph_id -> list of entity IDs mentioned
    """
    parser = AnnotationParser()
    paragraphs = content.split("\n\n")

    section_entities: dict[str, list[str]] = {}

    for idx, paragraph in enumerate(paragraphs):
        if not paragraph.strip():
            continue

        entities: list[str] = []
        para_id = f"para_{idx}"

        for annotation in parser.parse_declarations(paragraph):
            if annotation.id_value not in entities:
                entities.append(annotation.id_value)
        for annotation in parser.parse_references(paragraph):
            if annotation.id_value not in entities:
                entities.append(annotation.id_value)

        if entities:
            section_entities[para_id] = entities

    return section_entities


def _build_cooccurrence_edges(
    section_entities: dict[str, list[str]],
    source_file: str,
) -> list[CoOccurrence]:
    """Build pairwise co-occurrences from section entity lists.

    For each section with entities [A, B, C]:
      Emit edges: (A,B), (A,C), (B,C)
      Proximity = 1.0 / len(entities) to down-weight sections with many entities
    """
    cooccurrences: list[CoOccurrence] = []

    for section_id, entities in section_entities.items():
        if len(entities) < 2:
            continue

        # Proximity inversely proportional to entity count in section
        proximity = 1.0 / len(entities)

        # Generate all unique pairs (no self-edges)
        for entity_a, entity_b in combinations(entities, 2):
            if entity_a == entity_b:
                continue
            cooccurrences.append(
                CoOccurrence(
                    entity_a=entity_a,
                    entity_b=entity_b,
                    section_id=section_id,
                    source_file=source_file,
                    proximity=proximity,
                )
            )

    return cooccurrences
