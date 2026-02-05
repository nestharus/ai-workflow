# Dataflow and Traceability

## Core Trace Objects

- ATOM: smallest immutable evidence unit (line-level)
- SEC: section spans (contiguous atom slices)
- UNIT: tracked units produced by decomposition (many-to-many mapping to atoms)
- ELEM: derived spec elements (REQ/FLOW/INV/DEC/ALG/DS) grounded in atoms
- LIB: library containers for elements
- TASK: implementation work items grounded in atoms/elements
- GAP: explicit unresolved items grounded in atoms

## Trace Chains

ATOM → SEC
- atom_to_section is deterministic by span membership

SEC → UNIT
- decomposition maps section fragments to units

UNIT → ELEM
- extraction maps units to derived elements

ELEM → LIB
- element.lib_id is direct

ELEM → TASK
- tasks reference required element IDs and evidence atoms

TASK → PATCH → new ATOM
- implementation produces patches and new evidence that are ingested as new revisions

## Guarantees

- Trace completeness: every ATOM is reachable from at least one of:
  - remainder unit
  - derived element
  - exclusion record
- Backtrace: any ELEM/TASK/GAP can be expanded into exact evidence atoms and original file lines

## Query Patterns

- “where did this line go?”
  - atom_id → TraceAtomToOutputs (DS-PROV-0008)
- “what evidence supports this requirement?”
  - elem_id → element_to_atoms → render atoms
- “what did we drop?”
  - unaccounted_atom_ids must be empty; otherwise GAP(COVERAGE)
- “what is still unknown?”
  - GAP(UNDERSPECIFIED/AMBIGUITY/UNRESOLVED_REFERENCE) + TASK(NEEDS_SPEC)
