# Statement Ingestion Algorithm

## Overview

This algorithm processes raw Q&A content and invariants to build a hierarchical knowledge structure with:
- Components at multiple layers (coarse → fine)
- Flows showing how components interact
- Automatic conflict detection and deprecation
- Gap detection for unhandled responsibilities

## Core Rules

1. **No Parallel Systems**: Same responsibility = conflict. Only one component can handle a responsibility.
2. **Newest Wins**: When conflict detected, newest statement supersedes old.
3. **Cascade Deprecation**: Deprecated components become empty when nothing references them.
4. **Gap Detection**: Responsibilities that lose their handler are critical issues.
5. **Label-Based Routing**: Unknown terms go to `unknowns/` until enough evidence to classify.

## Directory Structure

```
.tasks/plans/workflow engine 2/
├── algorithm.md          # This file
├── staging.md            # Raw input (Q&A, reports, invariants)
├── qa.md                 # Processed Q&A state
├── dirty files/          # Files pending processing
├── clean files/          # Processed/paired files
├── systems/              # Knowledge structure
│   ├── index.md          # Top-level component summaries (for routing)
│   ├── unknowns/         # Labels with insufficient evidence
│   │   └── {label}.md    # Evidence collected per unknown label
│   ├── {component}/      # Each known component
│   │   ├── summary.md    # Component intent/responsibilities
│   │   ├── statements/   # Atomic statements in this component
│   │   ├── flows.md      # Internal flows between sub-components
│   │   ├── unknowns/     # Component-level unknowns
│   │   └── {sub}/        # Sub-components (recursive structure)
│   └── flows/            # Cross-cutting flows (span multiple components)
│       └── core.md       # Main system flows
└── checkpoint checks/    # Diff analysis artifacts
```

---

# Phase A: Pre-Processing Pipeline

Before statement ingestion, raw content must be processed into atomic statements.

## A1. Initial Split (Python)

**Input**: staging.md
**Output**: dirty files/1.md, 2.md, 3.md, ...
**Method**: Split by `---` delimiter

```python
# Split staging.md by --- into numbered files
sections = content.split('\n---\n')
for i, section in enumerate(sections, 1):
    write(f"dirty files/{i}.md", section)
```

## A2. Secondary Split (GLM)

**Agent**: segment-splitter
**Input**: A dirty file (e.g., 1.md)
**Output**: Line numbers where content splits into sub-sections
**Purpose**: Find question boundaries within a file

For each dirty file:
1. GLM identifies split points
2. Python splits into sub-files (1-1.md, 1-2.md, etc.)

## A3. Classification (GLM)

**Agent**: segment-classifier
**Input**: A file from dirty files/
**Output**: Classification (QUESTIONS | ANSWERS | CONCLUSIONS | INVARIANTS)
**Purpose**: Determine what type of content this is

Run in parallel with A2 for efficiency.

## A4. Q&A Pairing (GLM)

**Agent**: qa-pairer
**Input**: Questions file + Answers file
**Output**: Paired Q&A with matched questions to answers
**Purpose**: Match each question to its corresponding answer

Rules:
- Questions file is always followed by Answers file
- Match by content similarity, not position
- Output paired file (e.g., 1-1x2-1.md)

## A5. Statement Extraction (GLM)

**Agent**: statement-extractor
**Input**: Paired Q&A file or Conclusions/Invariants file
**Output**: Atomic statements (one per line)
**Purpose**: Extract discrete, actionable statements

Each statement should be:
- Self-contained (understandable without context)
- Atomic (one concept per statement)
- Actionable (describes a rule, constraint, or decision)

---

# Phase B: Statement Ingestion Pipeline

Process each extracted statement through the knowledge structure.

## Agents

### 1. responsibility-extractor (GLM)
**Input**: A statement
**Output**: What responsibility this statement describes
**Purpose**: Identify WHAT a statement does, not HOW

### 2. statement-router (GLM)
**Input**: Statement + responsibility + systems/index.md
**Output**: Target component path OR "unknown:{label}"
**Purpose**: Route statement to correct location using coarse summaries

### 3. conflict-detector (Opus)
**Input**: New statement + existing statements in target component
**Output**: List of conflicts (statements with same responsibility)
**Purpose**: Pattern recognition to find statements with same responsibility

### 4. deprecation-tracker (GPT 5.2 high)
**Input**: Conflict list + component tree
**Output**: Updated deprecation markers, list of newly-empty components
**Purpose**: Follow signals to cascade deprecation, careful auditing

### 5. gap-detector (GPT 5.2 high)
**Input**: Deprecated responsibilities + active component responsibilities
**Output**: List of gaps (responsibilities with no handler)
**Purpose**: Detailed gap recognition, careful auditing of coverage

### 6. unknown-promoter (Opus)
**Input**: unknowns/{label}.md with 3+ evidence items
**Output**: Promotion decision (new component OR merge with existing)
**Purpose**: Pattern recognition for synonyms and hidden connections

### 7. flow-updater (GLM)
**Input**: Component change + existing flows
**Output**: Updated flows
**Purpose**: Keep flows consistent with component changes

### 8. layer-summarizer (GLM)
**Input**: Changed component + parent layer
**Output**: Updated index.md / summary.md
**Purpose**: Bubble up changes to maintain routing accuracy

### 9. statement-ingestion-orchestrator (Minimax)
**Purpose**: Tool running and script execution (but YOU orchestrate manually)

## Orchestration Flow

### Phase 1: Statement Extraction
**You do**: Extract next statement from clean files/ or staging.md invariants
**Status**: Record which statement you're processing

### Phase 2: Responsibility Extraction
**Agent**: responsibility-extractor
**Input**: The statement
**Output**: Responsibility description
**You do**: Record the responsibility

### Phase 3: Label Extraction
**You do**: Identify labels/terms in the statement (grep-able names)
**Check**: Do these labels exist in systems/?

### Phase 4: Label Resolution
For each label:
- **If found**: Note the component path
- **If not found**:
  - Check unknowns/{label}.md
  - If exists: Add as evidence
  - If not: Create unknowns/{label}.md with this evidence

### Phase 5: Routing
**Agent**: statement-router
**Input**: Statement + responsibility + systems/index.md
**Output**: Target path
**You do**: Navigate to target component

### Phase 6: Conflict Check
**Agent**: conflict-detector
**Input**: New statement + target component statements
**Output**: Conflicts found?
**You do**: If conflicts, proceed to Phase 7. Else skip to Phase 8.

### Phase 7: Deprecation (if conflicts)
**Agent**: deprecation-tracker
**Input**: Conflicting statements
**Output**: What to deprecate
**You do**:
- Mark old statements as deprecated
- Check for cascade (empty components)
- Proceed to gap detection

### Phase 7b: Gap Detection (after deprecation)
**Agent**: gap-detector
**Input**: Deprecated responsibilities
**Output**: Gaps found?
**You do**: If gaps, record as critical issues to resolve

### Phase 8: Insert Statement
**You do**: Add statement to target component's statements/

### Phase 9: Unknown Promotion Check
**Agent**: unknown-promoter (if any unknown has 3+ evidence)
**Input**: unknowns/{label}.md
**Output**: Promote? Merge with existing?
**You do**: Execute promotion or merge

### Phase 10: Flow Update
**Agent**: flow-updater
**Input**: What changed
**Output**: Flow updates needed?
**You do**: Apply flow updates

### Phase 11: Summary Update
**Agent**: layer-summarizer
**Input**: Changed component
**Output**: Updated summaries
**You do**: Update index.md and parent summaries

### Phase 12: Record Progress
**You do**:
- Mark statement as processed
- Record any issues/gaps found
- Ask user if unclear

---

## State Tracking

Track in state.md:
```
## Current State

Processing: [statement ID or description]
Phase: [A1-A5 or B1-B12]
Issues: [any blockers]

## Pre-Processing Progress
- [ ] A1: Initial split (X files created)
- [ ] A2: Secondary split (X sub-files)
- [ ] A3: Classification complete
- [ ] A4: Q&A pairing complete
- [ ] A5: Statement extraction complete

## Processed Statements
- [x] Statement 1: routed to systems/ticketing/
- [x] Statement 2: created unknown "ref"
- [ ] Statement 3: IN PROGRESS

## Gaps (Critical)
- [ ] Real-time updates: was PostgreSQL LISTEN/NOTIFY, now unhandled

## Unknowns Pending Promotion
- unknowns/ref.md (2 evidence items, need 1 more)
```

## Getting Started

1. Run Phase A (Pre-Processing):
   - A1: Split staging.md by ---
   - A2-A3: Secondary split + classify (parallel)
   - A4: Pair Q&A files
   - A5: Extract statements

2. Run Phase B (Statement Ingestion):
   - Process each statement through phases 1-12
   - Track progress in state.md
   - Cycle until all statements processed
