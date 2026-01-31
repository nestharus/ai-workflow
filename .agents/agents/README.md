# Agent Catalog

## Evidence Expansion Agents

- `glm-library-evidence-mapper`: Maps library charters to relevant file sections
- `chatgpt-evidence-gap-judge`: Spot-checks for missed relevant sections

## Library Synthesis Agents

- `glm-file-library-labeler`: Classifies file summaries into candidate library labels
- `opus-library-label-refiner`: Merges/splits labels into stable library definitions
- `glm-library-overlap-resolver`: Resolves overlaps between library charters
- `repair-library-labels`: Repairs invalid library label JSON outputs

## Spec Integration Agents

- `glm-library-spec-integrator`: Monotonically integrates file content into specs
- `chatgpt-library-spec-gap-judge`: Detects dropped details via content-diff

## Phase 1 Sectionization Agents

- `glm-section-span-lister`: LLM-only section span extraction with stable IDs
- `glm-section-map-builder`: Human-readable section navigation map
- `glm-terms-per-section`: Domain term extraction for context indexing

## Usage Pattern

- Evidence expansion: Run mapper for all (library, file) pairs, then spot-check uncertain files with the judge.
- Spec building: Integrate all evidence files, run gap judge per file, rerun integrator for gaps, and repeat until clean.
