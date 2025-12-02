# Migration Plans

This directory contains migration task documentation for the AI Workflow project.

## Fact-Based Migration Tasks (Phases 4-11)

These tasks use the fact-based migration workflow documented in
`docs/processes/fact-migration.yml`, which operates at element/sentence granularity
with iterative fact extraction, semantic validation, and multi-domain classification.

### Task Files

| File | Task | Description |
|------|------|-------------|
| `rest-migration-task.yml` | Task 5 | Migrate REST content |
| `fastapi-migration-task.yml` | Task 6 | Migrate FastAPI content (10 files) |
| `python-migration-task.yml` | Task 7 | Migrate Python content (9 files) |
| `db-migration-task.yml` | Task 8 | Migrate DB content (4 files) |
| `md-to-yml-migration-task.yml` | Tasks 9-10 | Migrate MD to YAML content |
| `validation-task.yml` | Task 11 | Final validation |
| `fact-export-task.yml` | Tasks 12-13 | Fact atomization and export |

### Workflow Overview

Each task follows the four-step fact-based migration workflow:

1. **Start fact migration**: Extract atomic facts from YAML elements about identified
   entities (e.g., FastAPI, APIRouter, status, URL)
2. **Classify facts**: Invoke knowledge-analyzer sub-agent to classify facts by domain,
   scope (GENERAL vs PROJECT), and pattern
3. **Move facts**: Move classified PROJECT facts to target files with movement tracking
4. **Validate migration**: Verify semantic preservation (similarity >= 0.95) and
   completeness

### Key Differences from File-Level Migration

Fact-based migration differs from file-level migration (documented in
`docs/processes/information-migration.yml`) in several ways:

| Aspect | File-Level Migration | Fact-Based Migration |
|--------|---------------------|---------------------|
| Granularity | Entire files or sections | Individual facts/sentences |
| Extraction | Manual content splitting | Iterative entity-based extraction |
| Validation | File hash comparison | Semantic similarity >= 0.95 |
| Classification | Single domain per file | Multi-domain tagging per fact |
| Tracking | File movement log | Sentence-level movement CSV |

## Related Documentation

- `docs/processes/fact-migration.yml`: Fact-based migration workflow reference
- `docs/processes/information-migration.yml`: File-level migration workflow (legacy)
- `docs/development/domain-definitions.yml`: Domain taxonomy and multi-domain tagging
- `docs/development/MODULE-DEFINITIONS.yml`: Pattern definitions and scope criteria

## Phase Documentation

Legacy phase documentation (file-level approach):

- `phase1.yml` / `phase1.md`: Phase 1 planning
- `phase2.yml` / `phase2.md`: Phase 2 planning
- `phase3.yml` / `phase3.md`: Phase 3 planning
- `phase4.yml` / `phase4.md`: Phase 4 planning
