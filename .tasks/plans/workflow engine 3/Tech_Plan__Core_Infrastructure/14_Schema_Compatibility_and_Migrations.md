# Core Infrastructure — Schema Compatibility and Migrations

- **Doc**: Tech_Plan__Core_Infrastructure/14_Schema_Compatibility_and_Migrations.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.migrations`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`04_WSS_Workspace_State_Store.md`](04_WSS_Workspace_State_Store.md), [`07_Logs_Store.md`](07_Logs_Store.md)
- **Primary responsibility**: Explicit, auditable schema evolution with loud failures on unsupported versions.

## 14) Schema compatibility and migrations (trust requirement)

### 14.1 Forward/back rules

- If code reads a doc with `schema_version` **greater** than supported → fail loudly with upgrade instructions.
- If code reads an older doc → migrate in-memory and write back only via explicit `workflowctl migrate` (avoid silent upgrades).

### 14.2 Migration mechanism

Schema evolution is handled by explicit, auditable migrations. Migrations are not implicit “best effort” upgrades.

#### 14.2.1 Migration definition

A migration is a versioned unit that transforms one or more stores from version N → N+1.

Each migration MUST declare:

- `migration_id` (string; stable)
- `from_schema_version` (int)
- `to_schema_version` (int)
- `applies_to` (enum): `wss|repo_runtime|tickets|projects|logs|queues|index`
- `preconditions` (checks; fail loudly if unmet)
- `actions` (file transforms)

Migrations MUST be **idempotent**:
- re-running the same migration MUST not corrupt state
- if state is already at `to_schema_version`, the migration is a no-op

Migrations may be implemented as:
- code (preferred; deterministic transforms), or
- declarative “JSON patch” style transforms for simple cases

#### 14.2.2 `workflowctl migrate` behavior

`workflowctl migrate` MUST support two modes:

- `--dry-run` (default):
  - scan state roots
  - compute a migration plan
  - write the plan to `workspace/migrations/plan_<ts>.json`
  - perform no writes

- `--apply`:
  - execute the plan in order
  - write durable markers for each applied migration

Plan contents (minimum):

- target root(s)
- current versions found
- migrations required (ordered)
- files to be modified

#### 14.2.3 Ordering and versioning

- Migrations are applied in increasing `to_schema_version` order per store.
- Cross-store migrations MUST declare dependencies; the plan resolver must topologically sort.

#### 14.2.4 Backups and rollback

Rollback is “restore from backup”.

Before modifying any file, `--apply` MUST:

- copy the original file to:
  - `workspace/migrations/backups/<ts>/<original_path>`

If a migration fails mid-way:

- stop immediately (loud failure)
- leave backups intact
- write `workspace/migrations/failed_<ts>.json` with the error and partial progress

A future `workflowctl migrate --restore <ts>` MAY be added; until then, restore is manual using backups.

#### 14.2.5 Applied markers

On successful application, the tool MUST write:

- `workspace/migrations/applied/<migration_id>.json`

Including:

- `migration_id`
- `applies_to`
- `applied_at`
- `files_modified[]` with before/after hashes

### 14.3 Schema compatibility notes

- `llm_call` → `net_llm` is a naming change only.
- No data migration required (both map to the same capability).
- Runner MUST support both names in v1 for backwards compatibility.
- A warning MUST be emitted when the deprecated name is used.
- Removal of `llm_call` is planned for v2.
