# Spec Manager

General-purpose specification management library for organizing and maintaining
specification libraries using a 4-phase workflow.

## Overview

Spec Manager provides tools for managing specification folders containing:
- **Libraries**: Domain-specific markdown files with annotated sections
- **libs.md**: Central registry mapping IDs to their primary library
- **gaps.md**: Tracking unresolved gaps and proof obligations
- **Patches**: Incremental changes to specifications
- **Inputs**: Incoming plans/patches to be decomposed

## Installation

The package is standalone and can be installed in its own environment:

```bash
cd scripts/spec_manager
uv sync
```

## Workflow

The system uses a 4-phase workflow:

1. **STAGING**: Validate and legalize incoming content
   - Lint annotation formats
   - Check for duplicate declarations
   - Find missing declarations on headers
   - Identify unannotated references
   - Normalize legacy formats

2. **PLANNING**: Decompose changes into safe batches
   - Compare IDs across plan.md, libs.md, and libraries
   - Detect sequence gaps and duplicates
   - Identify conflicts (IDs in multiple libraries)
   - Create prioritized batches for merging

3. **MERGING**: Apply batches to library files
   - Extract new sections from plan.md
   - Move misplaced sections to correct library
   - Remove duplicate sections
   - Sort library sections by ID

4. **VERIFICATION**: Confirm no drift or duplication
   - Compare content between plan.md and libraries
   - Detect duplicate IDs across libraries
   - Verify all IDs are in correct primary library
   - Find empty stubs where plan has content

## Annotation Format

### Declarations
- `([=ID])` - Declares that a section belongs to this ID
- Used in header lines: `## Algorithm 1 ([=Algorithm 1])`

### References
- `(@[+ID])` - Contextual reference (mentions another ID)
- `(@[=ID])` - Labeled reference (belongs to another ID)

### ID Patterns
| Pattern | Example | Description |
|---------|---------|-------------|
| `Algorithm #` | `Algorithm 1` | Algorithm definition |
| `G#` | `G6` | Goal |
| `G#.#` | `G1.2` | Sub-goal |
| `D#` | `D10` | Data structure |
| `Comp#` | `Comp1` | Component |
| `P#` | `P1` | Patch |
| `P#.#` | `P8.10` | Patch section |
| `P#I#` | `P6I5` | Patch invariant |
| `P#C#` | `P4C3` | Patch claim |
| `Lean#` | `Lean9` | Lean skeleton |
| `NFG#` | `NFG1` | Non-functional goal |

## Usage

### CLI (Standalone Package)

Run from the `scripts/spec_manager` directory:

```bash
cd scripts/spec_manager

# Initialize workspace
uv run python -m spec_manager init <spec_folder>

# Check status
uv run python -m spec_manager status <spec_folder>

# Run individual phases
uv run python -m spec_manager stage <spec_folder> --normalize
uv run python -m spec_manager plan <spec_folder>
uv run python -m spec_manager merge <spec_folder> --apply
uv run python -m spec_manager verify <spec_folder>

# Run analysis
uv run python -m spec_manager analyze <spec_folder> --json

# Run all phases
uv run python -m spec_manager run <spec_folder> --apply

# Cleanup
uv run python -m spec_manager cleanup <spec_folder>
```

### Claude Command

```bash
# Run via Claude command
/spec-manager .tasks/plans/my-spec

# Run specific phase
/spec-manager .tasks/plans/my-spec --phase staging
```

### Agent System

The spec-manager command orchestrates multiple specialized agents:

```bash
# Execute via agent system
uv run python -m scripts.agents spec-manager-orchestrator "Manage spec folder: .tasks/plans/my-spec"
```

### Python API

```python
from pathlib import Path
from spec_manager.workspace import WorkspaceManager
from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.staging import run_staging
from spec_manager.planning import run_planning
from spec_manager.merging import run_merging
from spec_manager.verification import run_verification
from spec_manager.analysis import run_analysis

# Initialize
spec_folder = Path(".tasks/plans/my-spec")
manager = WorkspaceManager(spec_folder)
manager.initialize()

# Run staging
content = (spec_folder / "plan.md").read_text()
staging_result = run_staging(content)
print(f"Staging: {staging_result.error_count} errors")

# Load registry
registry = LibsRegistry.from_file(spec_folder / "libs.md")

# Run planning
planning_result = run_planning(content, registry, spec_folder / "libraries")
print(f"Planning: {len(planning_result.batches)} batches")

# Run merging (dry-run)
merge_result = run_merging(content, registry, spec_folder / "libraries", apply=False)
print(f"Merging: {len(merge_result.actions_planned)} actions planned")

# Run verification
verify_result = run_verification(content, registry, spec_folder / "libraries")
print(f"Verification: {'passed' if verify_result.is_valid else 'failed'}")

# Run analysis
analysis_result = run_analysis(registry, spec_folder / "libraries")
print(f"Suggestions: {len(analysis_result.suggestions)}")
```

## Spec Folder Structure

```
my-spec/
├── plan.md              # Master specification (source of truth)
├── libs.md              # ID to library assignment registry
├── gaps.md              # Unresolved gaps and proof obligations
├── pattern_spec.md      # Canonical annotation formats
├── libraries/           # Domain-specific library files
│   ├── foundation.md
│   ├── algorithms.md
│   ├── storage.md
│   └── ...
├── patches/             # Incremental changes
│   ├── p1.md
│   ├── p2.md
│   └── ...
├── inputs/              # Incoming content to process
│   └── ...
└── .workspace/          # Processing workspace (auto-generated)
    ├── state.json       # Persistent state
    ├── reports/         # Generated reports
    ├── staging/         # Staging phase files
    ├── planning/        # Planning phase files
    ├── merging/         # Merging phase files
    └── verification/    # Verification phase files
```

## libs.md Format

```markdown
- ([=Algorithm 1])
  - primary: ingestion
  - related: foundation, storage, graph

- ([=D10])
  - primary: storage
  - related: field, graph

- ([=G6])
  - primary: foundation
  - related: algorithms
```

## Analysis Features

### Divergence Detection
Identifies libraries that should be split:
- IDs share common related patterns
- Category clustering (all algorithms in one group)
- Library size exceeds threshold

### Convergence Detection
Identifies libraries that should be merged:
- High cross-reference counts
- Small libraries with shared context
- Overlapping domains

## Agent Architecture

The spec-manager uses multiple specialized agents with model routing:

| Agent | Models | Purpose |
|-------|--------|---------|
| spec-manager-orchestrator | glm-flash | Coordinates phases, handles routing |
| spec-manager-staging | smollm2-360/glm-flash | Fast validation |
| spec-manager-planning | glm-flash/glm | Batch decomposition |
| spec-manager-merging | smollm2-360/glm-flash | Section extraction |
| spec-manager-verification | smollm2-360/glm-flash | Consistency checks |
| spec-manager-analysis | glm/claude-opus | Complex pattern detection |
| spec-manager-qa | claude-opus | Troubleshooting |

## Package Structure

```
scripts/spec_manager/
├── pyproject.toml       # Package configuration
├── README.md            # This file
└── spec_manager/        # Main package
    ├── __init__.py      # Package exports
    ├── __main__.py      # Entry point
    ├── cli.py           # CLI commands
    ├── core/            # Core utilities
    │   ├── annotations.py   # Annotation parsing
    │   ├── sections.py      # Section extraction
    │   ├── ids.py           # ID validation
    │   └── libs_registry.py # libs.md parsing
    ├── workspace/       # Workspace management
    │   ├── manager.py       # WorkspaceManager
    │   └── state.py         # State persistence
    ├── staging/         # Staging phase
    │   └── operations.py    # Validation operations
    ├── planning/        # Planning phase
    │   └── operations.py    # Decomposition operations
    ├── merging/         # Merging phase
    │   └── operations.py    # Application operations
    ├── verification/    # Verification phase
    │   └── operations.py    # Confirmation operations
    └── analysis/        # Analysis operations
        └── operations.py    # Divergence/convergence
```
