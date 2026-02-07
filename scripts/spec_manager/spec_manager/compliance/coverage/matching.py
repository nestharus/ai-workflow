"""Matching strategies for entity-to-atom cross-referencing.

Implements three matching strategies in priority order:
1. Explicit linkage via EntityMention.atom_ids (confidence 1.0)
2. Naming heuristic via Jaccard similarity (confidence 0.7)
3. Keyword overlap via shared keywords (confidence 0.4)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from spec_manager.compliance.coverage.report import CoverageMatch

if TYPE_CHECKING:
    from spec_manager.branches.types import AtomDescriptor
    from spec_manager.schemas.entities import EntitiesArtifact, Entity
    from spec_manager.schemas.hollowed_spec import HollowedParagraph

# Minimum Jaccard similarity for naming heuristic matches
_JACCARD_THRESHOLD = 0.5

# Minimum number of shared keywords for keyword overlap matches
_MIN_SHARED_KEYWORDS = 3

# camelCase boundary pattern: split before an uppercase letter preceded by a lowercase
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _tokenize_name(name: str) -> set[str]:
    """Split a name into a set of lowercase word tokens.

    Handles underscore_case, dash-case, and camelCase boundaries.
    Filters out tokens shorter than 3 characters.

    Args:
        name: The name to tokenize.

    Returns:
        Set of lowercase tokens with length >= 3.
    """
    # Split on camelCase boundaries first
    parts = _CAMEL_BOUNDARY.sub("_", name)
    # Split on underscores and dashes
    tokens = re.split(r"[_\-]+", parts)
    return {t.lower() for t in tokens if len(t) >= 3}


def match_explicit(
    entities_artifact: EntitiesArtifact,
    atom_ids: set[str],
) -> list[CoverageMatch]:
    """Match entities to atoms via explicit linkage in mentions and tags.

    Uses ``EntitiesArtifact.get_atom_ids_for_entity()`` to find entity-atom
    pairs where the atom_id exists in the provided atom registry set.

    Args:
        entities_artifact: The entities artifact containing entities, mentions, and tags.
        atom_ids: Set of atom IDs present in the atom registry.

    Returns:
        List of CoverageMatch with method='explicit' and confidence=1.0.
    """
    matches: list[CoverageMatch] = []
    for entity in entities_artifact.entities:
        linked_atoms = entities_artifact.get_atom_ids_for_entity(entity.entity_id)
        for aid in linked_atoms:
            if aid in atom_ids:
                matches.append(
                    CoverageMatch(
                        entity_id=entity.entity_id,
                        atom_id=aid,
                        match_method="explicit",
                        confidence=1.0,
                        entity_name=entity.name,
                        atom_function_name=aid,
                    )
                )
    return matches


def match_by_naming(
    entities: list[Entity],
    atom_descriptors: list[AtomDescriptor],
) -> list[CoverageMatch]:
    """Match entities to atoms via naming heuristic (Jaccard similarity).

    Tokenizes entity names and atom function names, then computes Jaccard
    similarity. Pairs with similarity >= 0.5 are considered matched.

    Args:
        entities: List of Entity objects.
        atom_descriptors: List of AtomDescriptor objects.

    Returns:
        List of CoverageMatch with method='naming' and confidence=0.7.
    """
    matches: list[CoverageMatch] = []
    for entity in entities:
        entity_tokens = _tokenize_name(entity.name)
        if not entity_tokens:
            continue
        for atom in atom_descriptors:
            atom_tokens = _tokenize_name(atom.function_name)
            if not atom_tokens:
                continue
            intersection = entity_tokens & atom_tokens
            union = entity_tokens | atom_tokens
            jaccard = len(intersection) / len(union) if union else 0.0
            if jaccard >= _JACCARD_THRESHOLD:
                matches.append(
                    CoverageMatch(
                        entity_id=entity.entity_id,
                        atom_id=atom.atom_id,
                        match_method="naming",
                        confidence=0.7,
                        entity_name=entity.name,
                        atom_function_name=atom.function_name,
                    )
                )
    return matches


def match_by_keywords(
    entity_paragraphs: dict[str, list[HollowedParagraph]],
    atom_keywords: dict[str, set[str]],
    entity_names: dict[str, str] | None = None,
) -> list[CoverageMatch]:
    """Match entities to atoms via keyword overlap.

    Compares paragraph keywords for each entity against atom keyword sets.
    Pairs with >= 3 shared keywords are considered matched.

    Args:
        entity_paragraphs: Mapping of entity_name -> list of HollowedParagraph.
        atom_keywords: Mapping of atom_id -> set of keywords.
        entity_names: Optional mapping of entity_name -> entity_id for ID lookup.

    Returns:
        List of CoverageMatch with method='keyword' and confidence=0.4.
    """
    matches: list[CoverageMatch] = []
    names_map = entity_names or {}

    for entity_name, paragraphs in entity_paragraphs.items():
        # Collect all keywords from the entity's paragraphs
        entity_kws: set[str] = set()
        for para in paragraphs:
            entity_kws.update(kw.lower() for kw in para.keywords)
        if len(entity_kws) < _MIN_SHARED_KEYWORDS:
            continue

        entity_id = names_map.get(entity_name, entity_name)

        for atom_id, atom_kws in atom_keywords.items():
            shared = entity_kws & {kw.lower() for kw in atom_kws}
            if len(shared) >= _MIN_SHARED_KEYWORDS:
                matches.append(
                    CoverageMatch(
                        entity_id=entity_id,
                        atom_id=atom_id,
                        match_method="keyword",
                        confidence=0.4,
                        entity_name=entity_name,
                        atom_function_name=atom_id,
                    )
                )
    return matches


def resolve_matches(
    explicit: list[CoverageMatch],
    naming: list[CoverageMatch],
    keyword: list[CoverageMatch],
) -> list[CoverageMatch]:
    """Merge match lists with priority ordering.

    For each entity-atom pair, keeps only the highest-confidence match.
    Priority: explicit (1.0) > naming (0.7) > keyword (0.4).

    Args:
        explicit: Matches from explicit linkage.
        naming: Matches from naming heuristic.
        keyword: Matches from keyword overlap.

    Returns:
        Deduplicated list of CoverageMatch, one per entity-atom pair.
    """
    best: dict[tuple[str, str], CoverageMatch] = {}

    # Process in reverse priority order so higher-confidence overwrites
    for match_list in [keyword, naming, explicit]:
        for match in match_list:
            key = (match.entity_id, match.atom_id)
            existing = best.get(key)
            if existing is None or match.confidence > existing.confidence:
                best[key] = match

    return sorted(best.values(), key=lambda m: (-m.confidence, m.entity_id, m.atom_id))
