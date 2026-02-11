"""Build and manage the evidence index over hollowed-out specs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.schemas.hollowed_spec import HollowedSpec

logger = logging.getLogger(__name__)


class EvidenceIndex:
    """Composite index over multiple hollowed-out specs.

    Provides unified keyword and entity search across all indexed libraries.

    Attributes:
        specs: Mapping of lib_id -> HollowedSpec
        global_keyword_index: keyword -> list of (lib_id, paragraph_id)
        global_entity_index: entity_name -> list of (lib_id, paragraph_id)
    """

    def __init__(self) -> None:
        self.specs: dict[str, HollowedSpec] = {}
        self.global_keyword_index: dict[str, list[tuple[str, str]]] = {}
        self.global_entity_index: dict[str, list[tuple[str, str]]] = {}

    def add_spec(self, spec: HollowedSpec) -> None:
        """Add a hollowed spec to the index."""
        # Remove existing entries for this lib_id if re-indexing
        if spec.lib_id in self.specs:
            self.remove_spec(spec.lib_id)

        self.specs[spec.lib_id] = spec

        # Merge keyword index
        for keyword, para_ids in spec.keyword_index.items():
            entries = self.global_keyword_index.setdefault(keyword, [])
            for para_id in para_ids:
                entries.append((spec.lib_id, para_id))

        # Merge entity index
        for entity, para_ids in spec.entity_index.items():
            entries = self.global_entity_index.setdefault(entity, [])
            for para_id in para_ids:
                entries.append((spec.lib_id, para_id))

    def remove_spec(self, lib_id: str) -> None:
        """Remove a spec from the index (for re-indexing)."""
        if lib_id not in self.specs:
            return

        # Remove from keyword index
        empty_keys: list[str] = []
        for keyword, entries in self.global_keyword_index.items():
            self.global_keyword_index[keyword] = [
                (lid, pid) for lid, pid in entries if lid != lib_id
            ]
            if not self.global_keyword_index[keyword]:
                empty_keys.append(keyword)
        for key in empty_keys:
            del self.global_keyword_index[key]

        # Remove from entity index
        empty_keys = []
        for entity, entries in self.global_entity_index.items():
            self.global_entity_index[entity] = [(lid, pid) for lid, pid in entries if lid != lib_id]
            if not self.global_entity_index[entity]:
                empty_keys.append(entity)
        for key in empty_keys:
            del self.global_entity_index[key]

        del self.specs[lib_id]

    def save(self, path: Path) -> None:
        """Persist the index to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "specs": {lib_id: spec.model_dump() for lib_id, spec in self.specs.items()},
            "global_keyword_index": {
                kw: [[lid, pid] for lid, pid in entries]
                for kw, entries in self.global_keyword_index.items()
            },
            "global_entity_index": {
                ent: [[lid, pid] for lid, pid in entries]
                for ent, entries in self.global_entity_index.items()
            },
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> EvidenceIndex:
        """Load an index from a JSON file."""
        index = cls()

        if not path.exists():
            return index

        data = json.loads(path.read_text(encoding="utf-8"))

        # Load specs
        for lib_id, spec_data in data.get("specs", {}).items():
            index.specs[lib_id] = HollowedSpec.model_validate(spec_data)

        # Load global keyword index
        for kw, entries in data.get("global_keyword_index", {}).items():
            index.global_keyword_index[kw] = [(entry[0], entry[1]) for entry in entries]

        # Load global entity index
        for ent, entries in data.get("global_entity_index", {}).items():
            index.global_entity_index[ent] = [(entry[0], entry[1]) for entry in entries]

        return index

    @property
    def total_paragraphs(self) -> int:
        """Total number of paragraphs across all indexed specs."""
        return sum(len(spec.paragraphs) for spec in self.specs.values())

    @property
    def total_keywords(self) -> int:
        """Total number of unique keywords in the global index."""
        return len(self.global_keyword_index)

    @property
    def total_entities(self) -> int:
        """Total number of unique entities in the global index."""
        return len(self.global_entity_index)


def build_evidence_index(workspace_root: Path) -> EvidenceIndex:
    """Scan workspace for hollowed specs and build a unified index.

    Args:
        workspace_root: Root of the run workspace

    Returns:
        Populated EvidenceIndex
    """
    index = EvidenceIndex()
    evidence_store_dir = workspace_root / "workspace" / "evidence_store"

    if not evidence_store_dir.exists():
        logger.info("No evidence store directory found at %s", evidence_store_dir)
        return index

    for lib_dir in sorted(evidence_store_dir.iterdir()):
        if not lib_dir.is_dir():
            continue
        hollowed_path = lib_dir / "hollowed_spec.json"
        if not hollowed_path.exists():
            continue
        try:
            spec_data = json.loads(hollowed_path.read_text(encoding="utf-8"))
            spec = HollowedSpec.model_validate(spec_data)
            index.add_spec(spec)
            logger.info("Indexed hollowed spec for %s", spec.lib_id)
        except Exception as exc:
            logger.warning("Failed to load hollowed spec from %s: %s", hollowed_path, exc)

    return index
