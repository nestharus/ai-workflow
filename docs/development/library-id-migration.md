# Library ID Format Migration

## Overview
Library IDs are migrating from `lib_###` to `LIB-####` for consistency with requirement (`REQ-####`) and gap (`GAP-{hash}`) conventions.
This change also enables library-scoped requirement IDs like `REQ-LIB-0001-0042`.

## Format Comparison
| Aspect | Legacy | New |
|--------|--------|-----|
| Pattern | `lib_###` | `LIB-####` |
| Example | `lib_001` | `LIB-0001` |
| Capacity | 999 libraries | 9,999 libraries |
| Case | lowercase | UPPERCASE |
| Separator | underscore | hyphen |

## Requirement ID Embedding
Requirements can now embed library scope:
- Global: `REQ-0001`
- Library-scoped: `REQ-LIB-0001-0042` (requirement 42 in library 1)

## Migration Process
1. New libraries automatically use `LIB-####` format.
2. Existing `lib_###` IDs must be migrated before running refinement workflows.
3. Update references in library directories, events, charters, specs, and architecture artifacts.
4. Run `uv run spec migrate-library-ids` to bulk-convert existing libraries.

## Validation
- `IdValidator` in `scripts/spec_manager/spec_manager/core/ids.py` validates `LIB-####` and `REQ-LIB-####-####`.
- Library synthesis enforces `LIB-####` for all new library artifacts.
