# Phase 6 Implementation Plan: Entity-Tag Graph Library Discovery

## Overview

**Phase 6 Goal:** Align library discovery and spec building with the design's data shapes: entities -> co-occurrence graph -> libraries -> derived elements (REQ/FLOW/INV/DEC/ALG/DS) -> spec_index with atom-to-element bidirectional maps.

**Key Design References:**
- `07_LIBRARY_DISCOVERY.md`: DS-DISC-0001..0005, ALG-DISC-0001..0005
- `08_LIBRARY_SPEC_BUILDING.md`: DS-SPEC-0001..0005, ALG-SPEC-0001..0006
- `13_STRUCTURE_AND_DECOMPOSITION.md`: DS-STRUCT-0003..0005 (Entity, EntityMention, EntityTag)
- `00_ID_REGISTRY.md`: ALG-CORE-0006 (AllocateLibraryId), ALG-CORE-0007 (ResolveLocalIdsToStableIds)

**Constraints to Honor:** CON-0005 (evidence citations), CON-0019 (local_id rewriting), CON-0008 (stable IDs)

---

## Work Item 1: Introduce Explicit Entities Artifact

**Gap:** Current discovery uses TF-IDF word clustering without explicit Entity (DS-STRUCT-0003) or EntityTag (DS-STRUCT-0005) artifacts.

**Implementation Steps:**

1.1 **Create Entity schema** in `scripts/spec_manager/spec_manager/schemas/entities.py`:
```python
- Entity: entity_id (ENT-####), name, kind (enum), canonical_symbol
- EntityMention: entity_id, section_id, atom_ids, confidence
- EntityTag: entity_id, evidence_id|null, atom_ids, confidence
- EntitiesArtifact: entities[], mentions[], tags[], extraction_method
```

1.2 **Add entity extraction agent step** in `scripts/spec_manager/spec_manager/discovery/entity_extraction.py`:
- Input: SectionizationOutput (from Phase 3 evidence ranges)
- Output: EntitiesArtifact
- Uses LLM agent with schema validation (ALG-STRUCT-0003 pattern)
- Fallback: Convert existing "terms per section" from decomposition to entities

1.3 **Extend entity_index.py** to use new Entity schema:
- Migrate keyword-based entity storage to ENT-#### format
- Add atom_ids linking for each entity occurrence

**Tests:** `tests/spec_manager/schemas/test_entities.py`
- Validate Entity ID format (ENT-####)
- Test EntityMention atom_ids population
- Test extraction agent mock output validation

---

## Work Item 2: Library Discovery via Entity Co-occurrence Graph

**Gap:** Current `CandidateIdentifier` uses word clustering and reference patterns; design requires entity co-occurrence graph (ALG-DISC-0001).

**Implementation Steps:**

2.1 **Create co-occurrence graph builder** in `scripts/spec_manager/spec_manager/discovery/cooccurrence.py`:
```python
class CooccurrenceGraph:
    """Entity co-occurrence graph (ALG-DISC-0001)."""

    def build_from_entity_tags(
        self,
        entity_tags: list[EntityTag],
        window_policy: WindowPolicy
    ) -> WeightedGraph:
        # mentions: atom_id -> [entity_id...]
        # For each atom, add edges between co-occurring entities
        # Weight by same_atom_weight from policy
```

2.2 **Add library candidate proposal** in `scripts/spec_manager/spec_manager/discovery/library_proposal.py`:
- Implements ALG-DISC-0002 (ProposeLibraryCandidates)
- LLM proposes candidates from entity graph clusters
- Output: list[LibraryCandidate] with seed_atoms and proposed_name

2.3 **Add stability key to CandidateLibrary** and implement ALG-CORE-0006:
- Add `stability_key: str` field to CandidateLibrary
- Create `LibraryIdAllocator` in `scripts/spec_manager/spec_manager/core/library_registry.py`:
```python
def allocate_library_id(stability_key: str, existing: dict) -> tuple[str, bool]:
    # Returns (lib_id, is_new) per ALG-CORE-0006
```

2.4 **Refactor discover_with_all_signals()** to use co-occurrence graph:
- Replace TF-IDF clustering with entity graph clustering
- Keep reference graph and unit type as secondary signals
- Update LibraryRefiner to work with new candidate format

**Tests:** `tests/spec_manager/discovery/test_cooccurrence.py`
- Test graph building from entity tags
- Test library candidate proposal with mock LLM
- Test stability key idempotence (same key -> same lib_id)

---

## Work Item 3: Derived Elements Must Cite atom_ids/evidence_ids

**Gap:** Current SpecElement in `spec_indexes.py` has `citations: list[str]` but not `evidence_atom_ids` per DS-SPEC-0001.

**Implementation Steps:**

3.1 **Create DerivedElement schema** in `scripts/spec_manager/spec_manager/schemas/derived_elements.py`:
```python
class DerivedElement(BaseModel):
    """DS-SPEC-0001 compliant derived element."""
    elem_id: str  # {KIND}-LIB-{lib_seq:04d}-{seq:04d}
    kind: Literal["REQ", "FLOW", "INV", "DEC", "ALG", "DS", "NOTE", "GAP"]
    lib_id: str
    title: str
    body: str
    evidence_atom_ids: list[str]  # REQUIRED, must be non-empty
    confidence: float
    status: Literal["DRAFT", "ACTIVE", "NON_AUTHORITATIVE", "QUARANTINED", "DEPRECATED"]
    derived_from_elem_ids: list[str]
    relations: list[RelationEdge]
```

3.2 **Add validation for evidence grounding** (CON-0005):
```python
@model_validator(mode="after")
def validate_evidence_grounding(self) -> "DerivedElement":
    if not self.evidence_atom_ids:
        raise ValueError("DerivedElement must cite at least one evidence atom")
    return self
```

3.3 **Update spec-building agents** to output evidence_atom_ids:
- Extend agent contracts in `schemas/spec_patches.py` to require evidence
- Add evidence expansion from EVID ranges to atom lists

3.4 **Add RelationEdge schema** (DS-SPEC-0004):
```python
class RelationEdge(BaseModel):
    from_id: str
    to_id: str
    relation_type: Literal["DEPENDS_ON", "REFINES", "CONTRADICTS", "OVERLAPS", "IMPLEMENTS"]
    evidence_atom_ids: list[str]
    confidence: float
```

**Tests:** `tests/spec_manager/schemas/test_derived_elements.py`
- Test elem_id format validation
- Test rejection of elements without evidence_atom_ids
- Test relation edge validation

---

## Work Item 4: Implement local_id -> stable_id Rewriting

**Gap:** No implementation of CON-0019 (local_id resolution); design requires ALG-CORE-0007.

**Implementation Steps:**

4.1 **Define TagIndexDelta schema** in `scripts/spec_manager/spec_manager/schemas/tag_delta.py`:
```python
class TagItem(BaseModel):
    local_id: str  # Agent-assigned temporary ID
    existing_elem_id: str | None  # Set if referencing existing element
    kind: str
    lib_id: str
    evidence_atom_ids: list[str]
    title: str
    body: str

class TagRelation(BaseModel):
    from_local_id: str
    to_local_id: str
    relation_type: str
    evidence_atom_ids: list[str]

class TagIndexDelta(BaseModel):
    items: list[TagItem]
    relations: list[TagRelation]
```

4.2 **Implement LocalIdResolver** in `scripts/spec_manager/spec_manager/core/local_id_resolver.py`:
```python
class LocalIdResolver:
    """ALG-CORE-0007 implementation."""

    def resolve(
        self,
        tag_delta: TagIndexDelta,
        allocator_state: DeterministicIdAllocatorState
    ) -> ResolvedDelta:
        # Build local_id -> stable_id mapping
        # Allocate new IDs for new items via fingerprint
        # Rewrite relation endpoints
```

4.3 **Create DeterministicIdAllocatorState** (DS-CORE-0009):
```python
@dataclass
class DeterministicIdAllocatorState:
    counters: dict[str, int]  # prefix|namespace -> counter
    reserved: set[str]
    stable_maps: dict[str, str]  # fingerprint -> allocated_id
```

4.4 **Integrate resolver into spec-building pipeline**:
- Agents emit local_ids
- Post-processing calls LocalIdResolver
- Resolved elements stored with stable IDs

**Tests:** `tests/spec_manager/core/test_local_id_resolver.py`
- Test new item allocation
- Test existing item reference preservation
- Test relation endpoint rewriting
- Test idempotence (same fingerprint -> same ID)

---

## Work Item 5: Build Design-Compliant spec_index

**Gap:** Current SpecIndex in `spec_indexes.py` lacks `atom_to_elements` and `element_to_atoms` bidirectional maps required by DS-SPEC-0003.

**Implementation Steps:**

5.1 **Create SpecIndexV2 schema** in `scripts/spec_manager/spec_manager/schemas/spec_index_v2.py`:
```python
class SpecIndexV2(BaseModel):
    """DS-SPEC-0003 compliant spec index."""
    libraries: list[Library]  # DS-DISC-0001
    elements: dict[str, DerivedElement]  # elem_id -> element
    atom_to_elements: dict[str, list[str]]  # atom_id -> [elem_id]
    element_to_atoms: dict[str, list[str]]  # elem_id -> [atom_id]
    relations: list[RelationEdge]
    created_at: str
```

5.2 **Implement spec index builder** (ALG-SPEC-0003) in `scripts/spec_manager/spec_manager/discovery/spec_index_builder.py`:
```python
def build_spec_index(
    libraries: list[Library],
    elements: list[DerivedElement]
) -> SpecIndexV2:
    # Build bidirectional atom <-> element maps
    atom_to_elements = defaultdict(list)
    element_to_atoms = {}

    for elem in elements:
        element_to_atoms[elem.elem_id] = elem.evidence_atom_ids
        for atom_id in elem.evidence_atom_ids:
            atom_to_elements[atom_id].append(elem.elem_id)

    return SpecIndexV2(...)
```

5.3 **Add legacy format support**:
- Keep writing `spec_index.json` (old format) during transition
- Write `spec_index_v2.json` with new format
- Add migration utility to convert old -> new

5.4 **Integrate with workflow orchestrator**:
- Update finalize phase to emit SpecIndexV2
- Update reports to use new index format

**Tests:** `tests/spec_manager/schemas/test_spec_index_v2.py`
- Test bidirectional map consistency
- Test serialization roundtrip
- Test backward compatibility with legacy format

---

## Implementation Sequence

```
Phase 6 Dependencies:
  [1] Entities --> [2] Co-occurrence Graph --> [4] local_id resolver
                                           \
                                            --> [5] SpecIndex V2
                                           /
  [3] DerivedElement evidence_atom_ids ---/
```

**Recommended Order:**
1. Work Item 1 (Entities) - independent, foundation for WI-2
2. Work Item 3 (DerivedElement with evidence) - independent, foundation for WI-5
3. Work Item 2 (Co-occurrence graph) - depends on WI-1
4. Work Item 4 (local_id resolver) - depends on WI-3
5. Work Item 5 (SpecIndex V2) - depends on WI-3, WI-4

---

## Files to Create

| File | Purpose |
|------|---------|
| `schemas/entities.py` | Entity, EntityMention, EntityTag schemas |
| `schemas/derived_elements.py` | DerivedElement, RelationEdge schemas |
| `schemas/tag_delta.py` | TagIndexDelta for local_id handling |
| `schemas/spec_index_v2.py` | SpecIndexV2 with atom maps |
| `discovery/entity_extraction.py` | Entity extraction agent |
| `discovery/cooccurrence.py` | Co-occurrence graph builder |
| `discovery/library_proposal.py` | LLM-based library proposer |
| `discovery/spec_index_builder.py` | SpecIndex builder (ALG-SPEC-0003) |
| `core/library_registry.py` | Library ID allocator (ALG-CORE-0006) |
| `core/local_id_resolver.py` | Local -> stable ID resolver (ALG-CORE-0007) |

---

## Files to Modify

| File | Modifications |
|------|---------------|
| `discovery/candidate.py` | Add stability_key field, integrate entity graph |
| `discovery/refinement.py` | Use new library candidates with atom evidence |
| `discovery/__init__.py` | Export new modules |
| `schemas/spec_indexes.py` | Keep for backward compatibility |
| `core/__init__.py` | Export new registries |
| `schemas/evidence_graph.py` | Add ENTITY node handling |

---

## Constraints Addressed

| Constraint | Implementation |
|------------|----------------|
| CON-0005 | DerivedElement requires non-empty evidence_atom_ids |
| CON-0008 | Library IDs stable via stability_key allocator |
| CON-0019 | LocalIdResolver rewrites agent local_ids to stable IDs |
