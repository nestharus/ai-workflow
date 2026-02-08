# Phase 0: Cross-Reference Resolution

## The Problem

Real specs reference other files and sections constantly. In the
Workflow Engine 3 spec, nearly every paragraph references 2-3 other
locations. A single library spec (Step Execution) references:

- "Lifecycle §1" for status transitions
- "Core Infrastructure §6.4" for lock ordering
- "Enhanced Rebase §3.1" for hunk-lint
- "Integration §7.3" for dangerous capabilities
- "Core Flows Flow 12" for PAUSE protocol
- "Monitoring §5.4.2.B" for investigation classification

These are NOT optional enrichment. Some of them delegate the ENTIRE
definition to another file. Phase 0 must handle this.

---

## Key Insight: LLMs Follow References

LLMs are not constrained to a single file. When an LLM encounters a
reference like "see Lifecycle §1 for the complete state machine," it
can follow that reference — read the referenced file and understand
the full context.

This dramatically simplifies cross-reference resolution. Instead of
engineering a complex multi-pass reference resolution system, Phase 0
can let the LLM follow references naturally during classification.

**What this means for Phase 0:**
- Per-file processing still works as the primary loop
- When a file references another file, the LLM reads the referent
  to understand context before classifying
- Authority detection still matters (which file defines vs references)
- Coverage tracking still matters (nothing dropped)
- But the mechanical reference resolution pass becomes simpler — the
  LLM handles semantic linking as part of its normal processing

---

## Reference Types

### Type 1: Definitional Delegation

> "See `Lifecycle §1` for the complete authoritative state machine"

The current file delegates the ENTIRE definition to another file.
The content in the current file is meaningless without the referent.
The current file might just say "transitions follow §1" without
listing what the transitions are.

**Implication**: The extracted atom needs to either include the
referent content or preserve a link that can be followed later.

### Type 2: Authority Declaration

> "This document's §1 is the authoritative definition of ticket
> status transitions. All other specs MUST reference §1 rather
> than defining transitions independently."

One file declares itself as THE source for a concept. Other files
are satellites.

**Implication**: Phase 0 must track which file is authoritative for
which concept. When creating library structures, the authoritative
source defines the primary atom; references from other files become
links, not duplicates.

### Type 3: Contextual Enrichment

> "Error recovery playbooks provide user-facing guidance for all
> error codes defined in Logs Store §8.2.5"

The reference adds context but the current content is self-contained
enough to be useful alone. The error recovery playbook can be
understood without reading the Logs Store error definitions.

**Implication**: Phase 0 can extract the current content as-is and
record the reference as supplementary metadata.

### Type 4: Cross-Cutting Constraint

> "All lock acquisition MUST comply with the global lock order
> defined in §6.4"

A rule defined in one place applies to many files. Every file that
does locking references this one rule.

**Implication**: Phase 0 should extract the rule from its source
file (§6.4) as an atom. References to it from other files should
link to that atom, NOT create duplicate constraint atoms. The
rule itself might be an invariant ("all locking must follow a
single global order") or an algorithm ("the order is: ticket lock
→ task lock → run lock").

---

## Per-File Processing Model

Phase 0 processes one file at a time. It does NOT have the entire
spec in context simultaneously.

### Pass 1: Per-file extraction

For each file independently:

1. Intake the file (format-aware: MD, YAML, frontmatter)
2. Sectionize and extract entities
3. Decompose into classified fragments
4. Record ALL cross-references as metadata on each fragment:
   - Reference target (file + section)
   - Reference type (delegation, authority, enrichment, cross-cut)
   - Whether the fragment is self-contained or depends on referent

### Pass 2: Reference resolution

After all files are processed:

1. **Resolve delegations**: For each delegation reference, link the
   fragment to its referent fragment. If the referent wasn't
   extracted (e.g., reference to a file not in the input), mark as
   unresolved.

2. **Establish authority**: For each authority declaration, mark the
   authoritative fragment. All satellite references to the same
   concept link to the authority.

3. **Deduplicate overlaps**: When the same concept appears in
   multiple files (e.g., ticket status in Epic Brief, Lifecycle,
   WSS schema), keep the authoritative definition as primary and
   link others as references.

4. **Track cross-cutting constraints**: For constraints referenced
   from many files, extract once from the source and create links
   from all referencing files.

### Pass 3: Coverage check

Verify:
- All fragments from Pass 1 are accounted for
- All delegation references are resolved (or explicitly unresolved)
- No duplicate atoms exist for the same concept
- Authority chains are consistent (no two files claim authority
  over the same concept)

---

## Overlap Patterns in Real Specs

Some concepts appear in multiple files with different aspects:

| Concept | Files | What each adds |
|---------|-------|---------------|
| Ticket status | Epic Brief, Lifecycle, WSS, Core Flows | Epic: overview. Lifecycle: authoritative transitions. WSS: schema. Flows: usage in procedures. |
| PAUSE protocol | Core Flows, Monitoring, Foundation | Flows: step sequence. Monitoring: enforcement details. Foundation: invariant ("PAUSE is mandatory"). |
| Error codes | Logs Store, Error Recovery, Monitoring | Logs: definitions. Recovery: playbooks. Monitoring: investigation classification. |
| Sandbox lifecycle | Integration §9, Core Flows §8-9, Workflows | Integration: implementation. Flows: usage. Workflows: config options. |

Each occurrence adds a different ASPECT of the same concept. Phase 0
must:
- Detect these overlaps (same entity referenced from multiple files)
- Determine which file is authoritative for which aspect
- Create linked atoms, not duplicates

---

## Applicable Approaches from Spec Refinement

### Atom-Level Provenance Tracking (from `clean/02_PROVENANCE_AND_MEMBERSHIP.md`)

The provenance system provides the tracking infrastructure for
cross-reference resolution:

**TrackedUnit** — Each extracted fragment becomes a TrackedUnit with:
- `atom_ids` — Immutable atom-level granularity (each sentence/block
  gets a unique atom ID)
- `lineage_edges` — Track transformations: SPLIT, MERGE, REWRITE,
  PROMOTE, DEMOTE, PATCH_APPLY, INFER
- `membership_evidence` — Per-atom rationale for why it's in this unit
  (method: EXACT, SEQUENCE_ALIGN, LLM_ATOM_MAP, etc.)
- `status` — PENDING, MAPPED, MERGED, DROPPED, NON_AUTHORITATIVE,
  QUARANTINED

**CoverageReport** — Per-file verification:
- `total_atoms` — How many atoms the file produced
- `mapped_atoms` — How many found a home in the output
- `unaccounted_atom_ids` — Atoms that got lost (extraction failures)

This gives Phase 0 the ability to:
1. Track every normative sentence through extraction
2. Verify coverage after reference resolution (nothing lost)
3. Record WHY a fragment was classified as non-authoritative
4. Trace any output atom back to its source file and location

**LineageEdge** — When cross-reference resolution moves or links content:
- MERGE: Two overlapping atoms from different files combined
- SPLIT: One atom split into authoritative + satellite
- REWRITE: Content restructured during organization

### Entity Co-Occurrence Detection (from `clean/07_LIBRARY_DISCOVERY.md`)

The library discovery system detects overlapping entities across files:

**BuildCooccurrenceGraphFromEntityTags** — Builds a weighted graph where:
- Nodes = entities mentioned in the spec
- Edges = co-occurrence (same entity mentioned in multiple files)
- Weight = frequency of co-occurrence

When the same entity (e.g., "ticket status") appears in multiple files,
the co-occurrence graph identifies it. This drives:
- Authority detection: the file with the strongest definition is likely
  authoritative
- Overlap detection: multiple files defining the same concept

**Multi-Label Assignment (MultiLabelUnitsToLibraries)** — A single
extracted unit can belong to multiple libraries:
- `primary_lib_id` — Where the unit primarily belongs
- `secondary_lib_ids` — Other libraries that reference this content
- This handles cross-cutting concepts naturally (e.g., "lock ordering"
  is primary to Multi-Writer but secondary to Lifecycle, Decomposition,
  Step Execution)

**Non-Destructive Overlap Resolution (ResolveOverlapWithNonDestructiveMoves)** —
When overlaps are detected:
- Content is NOT deleted
- The authoritative source becomes the primary atom
- Satellite references become links (secondary membership)
- No information loss during deduplication

### How These Apply to Phase 0's Passes

| Phase 0 Pass | Spec Refinement Approach |
|-------------|------------------------|
| Pass 1: Per-file extraction | Each fragment → TrackedUnit with atom_ids. Cross-references recorded as metadata (not yet resolved). |
| Pass 2: Reference resolution | Co-occurrence graph detects entity overlaps. LineageEdge tracks MERGE/SPLIT. Authority established via coverage analysis (most detailed = authoritative). Non-destructive dedup creates links. |
| Pass 3: Organization | Multi-label assignment places units in primary + secondary libraries. CoverageReport verifies nothing lost. |
| Pass 4: Coverage check | CoverageReport.unaccounted_atom_ids = extraction failures. Every normative sentence must be mapped. |

### Reference Resolution Algorithm

Using spec refinement primitives:

```
For each file in input:
  units = ExtractToTrackedUnits(file)  # Pass 1
  for unit in units:
    unit.tags = ExtractEntityTags(unit)  # entities mentioned

cooccurrence = BuildCooccurrenceGraphFromEntityTags(all_tags)

# Find entities that appear in multiple files
for entity in cooccurrence.nodes:
  mentions = files_mentioning(entity)
  if len(mentions) > 1:
    # Determine authority
    authoritative = pick_most_detailed(mentions)
    for satellite in mentions - {authoritative}:
      # Non-destructive: link satellite to authority
      satellite_unit.status = NON_AUTHORITATIVE
      add LineageEdge(satellite → authoritative, type=MERGE)
      satellite_unit.secondary_lib_ids.add(authoritative.primary_lib_id)

# Verify coverage
for file in input:
  report = BuildCoverageReport(file)
  if report.unaccounted_atom_ids:
    emit_extraction_failure(report)
```

This is pseudocode showing the flow, not a literal implementation.

---

## Reference Detection Heuristics

How Phase 0 identifies cross-references in text:

### Explicit section references
- "§5.4" or "Section 5.4"
- "Core Infrastructure §6.4"
- "Lifecycle §1.2"
- "see §X" or "per §X" or "defined in §X"

### File path references
- "`Tech_Plan__Core_Infrastructure/07_Logs_Store.md`"
- "see `project_ticket_system/Lib__Lifecycle.md`"
- backtick-wrapped relative paths

### Concept references (harder to detect)
- "the state machine defined above"
- "the transitions in the lifecycle spec"
- "using the standard evidence protocol"

### Authority markers
- "authoritative definition of X"
- "canonical" / "normative"
- "All other specs MUST reference §X"
- "defined once in X, referenced elsewhere"
