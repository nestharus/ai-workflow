# Failure Handling and Progress Guarantee

## Progress Guarantee Principle (CON-0009)

Every phase must have a total fallback that produces a valid state without losing evidence.

Fallback states always:
- preserve L0 evidence
- keep L1 authority unchanged (unless explicitly replaced by a validated new build)
- emit gaps + tasks rather than blocking silently

## Failure Classes

1) Contract failure (invalid JSON / schema mismatch)
2) Coverage failure (unaccounted atoms)
3) Drift failure (projection mismatch)
4) Semantic failure (judge flags contradictions/unsupported derived claims)
5) Resource failure (context limits, timeouts)

## Per-Phase Fallbacks

Phase 1 (Sectionization)
- fallback: 1 section covering entire file + per-line micro-sections for unresolved atoms

Phase 2 (Surgical Decomposition)
- fallback: create a single PROSE unit for the section; mark as remainder; emit “needs decomposition” gap

Phase 4 (Library Discovery)
- fallback: 1 library per file_uid OR single library “LIB-0001” containing all units
- unresolved units remain unassigned with gaps

Phase 5 (Spec Build)
- fallback: charter-only library specs + element stubs pointing to evidence; no inferred requirements without evidence

Phase 7 (Projection Sync)
- fallback: regenerate projection from L1; treat edits/drift as gap evidence; never accept projection edits as authority

Implementation
- fallback: block the specific task; emit NEEDS_SPEC tasks; continue with other tasks

## Escalation

- Escalate only when:
  - severity ERROR gaps persist after a bounded number of repair attempts
  - coverage invariants fail
  - contradictions are detected in ACTIVE elements

Escalation actions:
- switch to stronger judge model
- increase evidence context window
- isolate minimal failing fixture and route to strategy evolution
- optional human decision capture (recorded as new evidence)
