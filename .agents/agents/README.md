# Agent Catalog

## Evidence Expansion Agents

- `glm-library-evidence-mapper`: Maps library charters to relevant file sections
- `chatgpt-evidence-gap-judge`: Spot-checks for missed relevant sections

## Spec Integration Agents

- `glm-library-spec-integrator`: Monotonically integrates file content into specs
- `chatgpt-library-spec-gap-judge`: Detects dropped details via content-diff

## Usage Pattern

- Evidence expansion: Run mapper for all (library, file) pairs, then spot-check uncertain files with the judge.
- Spec building: Integrate all evidence files, run gap judge per file, rerun integrator for gaps, and repeat until clean.
