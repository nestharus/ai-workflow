"""Entity coverage analyzer orchestrating matching strategies.

Cross-references hollowed spec entities against registered atom functions
to produce a coverage report identifying gaps in both directions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from spec_manager.compliance.coverage.matching import (
    match_by_keywords,
    match_by_naming,
    match_explicit,
    resolve_matches,
)
from spec_manager.compliance.coverage.report import (
    EntityCoverageReport,
    UnmatchedAtom,
    UnmatchedEntity,
)

if TYPE_CHECKING:
    from spec_manager.branches.atoms import AtomRegistry
    from spec_manager.core.evidence_index import EvidenceIndex
    from spec_manager.schemas.entities import EntitiesArtifact
    from spec_manager.schemas.hollowed_spec import HollowedParagraph


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class CoverageAnalyzer(Protocol):
    """Plugin interface for entity coverage analysis strategies.

    Any implementation must expose an ``analyze`` method that produces
    an ``EntityCoverageReport``.
    """

    def analyze(self) -> EntityCoverageReport: ...


class EntityCoverageAnalyzer:
    """Analyzer that cross-references spec entities against atom functions.

    Runs three matching strategies (explicit, naming, keyword) in priority
    order and produces an ``EntityCoverageReport``.

    Args:
        evidence_index: The evidence index with entity/paragraph data.
        atom_registry: The atom registry with atom descriptors.
        entities_artifact: Optional entities artifact for explicit linkage.
    """

    def __init__(
        self,
        evidence_index: EvidenceIndex,
        atom_registry: AtomRegistry,
        entities_artifact: EntitiesArtifact | None = None,
    ) -> None:
        """Initialize the analyzer with evidence index and atom registry.

        Args:
            evidence_index: The evidence index with entity/paragraph data.
            atom_registry: The atom registry with atom descriptors.
            entities_artifact: Optional entities artifact for explicit linkage.
        """
        self._evidence_index = evidence_index
        self._atom_registry = atom_registry
        self._entities_artifact = entities_artifact

    def analyze(self) -> EntityCoverageReport:
        """Run all matching strategies and produce a coverage report.

        Returns:
            EntityCoverageReport with matched pairs, unmatched entities,
            unmatched atoms, and coverage ratios.
        """
        all_atoms = self._atom_registry.list_all()
        atom_ids_set = {a.atom_id for a in all_atoms}

        # --- Strategy 1: Explicit linkage ---
        explicit_matches = []
        if self._entities_artifact is not None:
            explicit_matches = match_explicit(self._entities_artifact, atom_ids_set)

        # --- Strategy 2: Naming heuristic ---
        entities_list = []
        if self._entities_artifact is not None:
            entities_list = list(self._entities_artifact.entities)
        naming_matches = match_by_naming(entities_list, all_atoms)

        # --- Strategy 3: Keyword overlap ---
        entity_paragraphs = self._collect_entity_paragraphs()
        # Build atom keywords from function names (tokenized)
        atom_keywords: dict[str, set[str]] = {}
        for atom in all_atoms:
            # Use function name tokens as keywords
            from spec_manager.compliance.coverage.matching import _tokenize_name

            tokens = _tokenize_name(atom.function_name)
            if tokens:
                atom_keywords[atom.atom_id] = tokens

        # Build entity name -> entity_id mapping
        entity_names: dict[str, str] = {}
        if self._entities_artifact is not None:
            for entity in self._entities_artifact.entities:
                entity_names[entity.name] = entity.entity_id

        keyword_matches = match_by_keywords(entity_paragraphs, atom_keywords, entity_names)

        # Resolve all matches
        matched = resolve_matches(explicit_matches, naming_matches, keyword_matches)

        # Determine matched IDs
        matched_entity_ids = {m.entity_id for m in matched}
        matched_atom_ids = {m.atom_id for m in matched}

        # Identify unmatched
        unmatched_entities, unmatched_atoms = self._identify_unmatched(
            matched_entity_ids, matched_atom_ids
        )

        # Compute totals and coverage ratios
        total_entities = len(self._get_all_entity_ids())
        total_atoms = len(all_atoms)

        entity_coverage = len(matched_entity_ids) / total_entities if total_entities > 0 else 1.0
        atom_coverage = len(matched_atom_ids) / total_atoms if total_atoms > 0 else 1.0

        return EntityCoverageReport(
            matched=matched,
            unmatched_entities=unmatched_entities,
            unmatched_atoms=unmatched_atoms,
            entity_coverage=entity_coverage,
            atom_coverage=atom_coverage,
            total_entities=total_entities,
            total_atoms=total_atoms,
        )

    def _collect_entity_paragraphs(self) -> dict[str, list[HollowedParagraph]]:
        """Group paragraphs by entity name using the evidence index.

        Returns:
            Mapping of entity_name -> list of HollowedParagraph.
        """
        result: dict[str, list[HollowedParagraph]] = {}
        for entity_name, entries in self._evidence_index.global_entity_index.items():
            paragraphs: list[HollowedParagraph] = []
            for lib_id, para_id in entries:
                spec = self._evidence_index.specs.get(lib_id)
                if spec is None:
                    continue
                para = spec.paragraphs.get(para_id)
                if para is not None:
                    paragraphs.append(para)
            if paragraphs:
                result[entity_name] = paragraphs
        return result

    def _get_all_entity_ids(self) -> set[str]:
        """Collect all entity IDs from both the evidence index and entities artifact.

        Returns:
            Set of all known entity identifiers.
        """
        entity_ids: set[str] = set()

        # From entities artifact
        if self._entities_artifact is not None:
            for entity in self._entities_artifact.entities:
                entity_ids.add(entity.entity_id)

        # From evidence index (entity names used as IDs when no artifact)
        # Only add entity index names if we have no artifact (to avoid mixing types)
        if self._entities_artifact is None:
            for entity_name in self._evidence_index.global_entity_index:
                entity_ids.add(entity_name)

        return entity_ids

    def _identify_unmatched(
        self,
        matched_entity_ids: set[str],
        matched_atom_ids: set[str],
    ) -> tuple[list[UnmatchedEntity], list[UnmatchedAtom]]:
        """Identify entities and atoms that were not matched.

        Args:
            matched_entity_ids: Entity IDs that have at least one match.
            matched_atom_ids: Atom IDs that have at least one match.

        Returns:
            Tuple of (unmatched_entities, unmatched_atoms).
        """
        # Unmatched entities
        unmatched_entities: list[UnmatchedEntity] = []

        if self._entities_artifact is not None:
            for entity in self._entities_artifact.entities:
                if entity.entity_id not in matched_entity_ids:
                    # Look up paragraph and lib info from evidence index
                    para_ids: list[str] = []
                    lib_ids: list[str] = []
                    entries = self._evidence_index.global_entity_index.get(entity.name, [])
                    for lib_id, para_id in entries:
                        para_ids.append(para_id)
                        if lib_id not in lib_ids:
                            lib_ids.append(lib_id)
                    unmatched_entities.append(
                        UnmatchedEntity(
                            entity_id=entity.entity_id,
                            name=entity.name,
                            kind=entity.kind.value,
                            paragraph_ids=para_ids,
                            lib_ids=lib_ids,
                        )
                    )
        else:
            # Fall back to evidence index entity names
            for entity_name in self._evidence_index.global_entity_index:
                if entity_name not in matched_entity_ids:
                    entries = self._evidence_index.global_entity_index[entity_name]
                    para_ids = [pid for _, pid in entries]
                    lib_ids = list(dict.fromkeys(lid for lid, _ in entries))
                    unmatched_entities.append(
                        UnmatchedEntity(
                            entity_id=entity_name,
                            name=entity_name,
                            kind="unknown",
                            paragraph_ids=para_ids,
                            lib_ids=lib_ids,
                        )
                    )

        # Unmatched atoms
        unmatched_atoms: list[UnmatchedAtom] = []
        for atom in self._atom_registry.list_all():
            if atom.atom_id not in matched_atom_ids:
                unmatched_atoms.append(
                    UnmatchedAtom(
                        atom_id=atom.atom_id,
                        function_name=atom.function_name,
                        kind=atom.kind.value,
                        vertical_slice=atom.vertical_slice,
                    )
                )

        return unmatched_entities, unmatched_atoms
