"""Entity index management for keyword-based entity matching."""

from __future__ import annotations

import json
from pathlib import Path


def load_entity_index(workspace: Path) -> dict:
    """Load entity index from workspace.

    Format:
    {
        "E-001": {
            "name": "Authentication Service",
            "keywords": ["auth", "authentication", "login"],
            "aliases": [],
            "sources": ["spec.md:42"]
        }
    }
    """
    index_file = workspace / "entity_index.json"
    if index_file.exists():
        return json.loads(index_file.read_text())
    return {}


def save_entity_index(workspace: Path, index: dict) -> None:
    """Save entity index to workspace."""
    index_file = workspace / "entity_index.json"
    index_file.write_text(json.dumps(index, indent=2))


def add_entity_to_index(
    workspace: Path,
    entity_id: str,
    name: str,
    keywords: list[str],
    source: str,
) -> None:
    """Add a new entity to the index.

    Args:
        workspace: Workspace directory
        entity_id: Entity ID (e.g., "E-001")
        name: Entity name
        keywords: List of keywords for matching
        source: Source reference (e.g., "spec.md:42")
    """
    index = load_entity_index(workspace)

    # Normalize keywords
    normalized_keywords = [kw.lower().strip() for kw in keywords]
    # Add the name itself as a keyword
    normalized_keywords.append(name.lower())
    # Remove duplicates while preserving order
    seen = set()
    unique_keywords = []
    for kw in normalized_keywords:
        if kw not in seen:
            seen.add(kw)
            unique_keywords.append(kw)

    index[entity_id] = {
        "name": name,
        "keywords": unique_keywords,
        "aliases": [],
        "sources": [source],
    }

    save_entity_index(workspace, index)


def add_source_to_entity(workspace: Path, entity_id: str, source: str) -> None:
    """Add a source reference to an existing entity."""
    index = load_entity_index(workspace)

    if entity_id in index:
        if source not in index[entity_id]["sources"]:
            index[entity_id]["sources"].append(source)
        save_entity_index(workspace, index)


def add_keywords_to_entity(workspace: Path, entity_id: str, keywords: list[str]) -> None:
    """Add keywords to an existing entity."""
    index = load_entity_index(workspace)

    if entity_id in index:
        existing = set(index[entity_id]["keywords"])
        for kw in keywords:
            normalized = kw.lower().strip()
            if normalized not in existing:
                index[entity_id]["keywords"].append(normalized)
                existing.add(normalized)
        save_entity_index(workspace, index)


def check_rediscovery(
    workspace: Path,
    entity_name: str,
    keywords: list[str],
) -> dict:
    """Check if an entity matches any existing entity by keywords.

    Returns:
        {"match": None} if no match
        {"match": "E-005", "confidence": 0.85, "matched_keywords": [...]} if match found
    """
    index = load_entity_index(workspace)

    if not index:
        return {"match": None}

    # Normalize input keywords
    search_keywords = {kw.lower().strip() for kw in keywords}
    search_keywords.add(entity_name.lower())

    best_match = None
    best_confidence = 0.0
    best_matched = []

    for entity_id, entity_data in index.items():
        existing_keywords = set(entity_data["keywords"])

        # Direct keyword overlap
        matched = search_keywords & existing_keywords

        # Partial matching (e.g., "auth" matches "authentication")
        partial_matched = set()
        for search_kw in search_keywords:
            for existing_kw in existing_keywords:
                if (
                    search_kw in existing_kw or existing_kw in search_kw
                ) and search_kw != existing_kw:
                    partial_matched.add(f"{search_kw}~{existing_kw}")

        # Calculate confidence
        total_search = len(search_keywords)
        total_existing = len(existing_keywords)
        exact_matches = len(matched)
        partial_matches = len(partial_matched)

        # Confidence formula: weighted combination of exact and partial
        if total_search > 0:
            confidence = (exact_matches + 0.5 * partial_matches) / max(total_search, total_existing)
            confidence = min(confidence, 1.0)  # Cap at 1.0

            if confidence > best_confidence and confidence >= 0.3:  # Threshold
                best_match = entity_id
                best_confidence = confidence
                best_matched = list(matched) + [p.split("~")[0] for p in partial_matched]

    if best_match:
        return {
            "match": best_match,
            "confidence": round(best_confidence, 2),
            "matched_keywords": best_matched,
        }

    return {"match": None}


def get_all_keywords(workspace: Path) -> dict[str, str]:
    """Get a mapping of all keywords to their entity IDs.

    Returns:
        {"auth": "E-001", "login": "E-001", "user": "E-002", ...}
    """
    index = load_entity_index(workspace)
    keyword_map = {}

    for entity_id, entity_data in index.items():
        for kw in entity_data["keywords"]:
            keyword_map[kw] = entity_id

    return keyword_map
