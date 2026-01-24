# Tech Plan: Core Infrastructure & Data Model

## # Tech Plan: Core Infrastructure & Data Model

## Scope & Assumptions

**Local Development Only**: This system runs on a single dev machine. It is NOT a distributed system:

- Workflow state is stored in a **local PostgreSQL database** (typically via Docker). Database storage lives in a local Docker volume/directory and is **not committed** to git.
- PostgreSQL storage is a **PGDATA directory** (many files), typically persisted via a Docker volume; treat the volume/directory as the durability boundary.
- Many independent agent processes will read/write concurrently; PostgreSQL is chosen for safe multi-writer concurrency.
- WSL + Windows support: agents and UI connect to PostgreSQL **over TCP** (e.g., `localhost` / `host.docker.internal`) and use per-repo path aliases (no shared DB files across filesystems).
- No cloud components, external brokers, or distributed coordination.
- No external brokers/queues. Real-time UI updates use PostgreSQL `LISTEN/NOTIFY` wakeups + cursor reads from `context_logs`.

**No External Integrations**:

- No Traycer API integration (documentation loaded manually via paste or file paths).
- No Linear API integration (artifacts stored in PostgreSQL, exported to files for user consumption if desired).
- No external message queues or brokers.

**Git Configuration**:

- Add to `.gitignore`: `.worktrees/`, `.tmp/`, local `.env` files, and any DB dumps/exports (e.g., `.tmp/exports/`, `.tmp/evaluation-*`).
- Rationale: these are machine-local artifacts and/or contain sensitive data; the PostgreSQL data directory/volume is also local-only.

**PostgreSQL Connection Hygiene**:

- UI/monitor connections MUST set timeouts to prevent long-running transactions:
  - `statement_timeout`: 30000 (30 seconds for UI queries)
  - `idle_in_transaction_session_timeout`: 60000 (60 seconds)
- UI connections MUST use autocommit mode (no explicit transactions)
- Keep all transactions short (commit within seconds, not minutes)
- Never hold transactions open during LLM calls or subprocess work

**Log Retention Policy**:

- `context_logs` table implements retention: keep last 30 days OR last 100 runs per repo
- Deletion in batches (1000 rows at a time) to avoid spikes
- CLI command: `workflow db prune --repo {repo_id} --days 30`
- Automatic pruning runs daily via background task (optional)

---

## Architectural Decisions

### 1. Shared Workflow Infrastructure

**Decision**: Create `scripts/core/workflow/` module for shared infrastructure, avoiding duplication between article_writer and project management systems.

**Pattern**: Generalize article_writer's SQLAlchemy patterns onto a shared local PostgreSQL database:

- Single local PostgreSQL database (Docker/service) as the system of record (safe for many concurrent writers)
- Base models in `scripts/core/workflow/models.py` (reusable across domains)
- Generalized `StateMachine` class supporting multiple workflow types
- Shared database client with connection pooling + migrations (no file-based tuning)
- Change signaling via PostgreSQL `LISTEN/NOTIFY` (wakeup only) + cursor reads

**Trade-offs**:

- ✅ Eliminates code duplication
- ✅ Consistent patterns across all workflows
- ✅ Single source of truth for workflow state
- ⚠️ Requires refactoring article_writer to use shared infrastructure (future work)

**Constraint**: Must maintain backward compatibility with existing article_writer workflows during transition period.

---

### 2. Hierarchical Step Execution Tracking

**Decision**: Track step executions with self-referential parent-child relationships, capturing function context at spawn time.

**Pattern**: Each step execution stores:

- Unique step execution ID (UUID)
- Parent step execution ID (self-referential foreign key)
- Function context: `{module}.{function}` (e.g., `scripts.pr.review_loop.main`)
- Process ID for subprocess management
- Entry/exit timestamps for anomaly detection

**Hierarchy Example**:

```

claude-code-command (root, parent_id=NULL)

  └─ [[project-manager.open](http://project-manager.open)]([http://project-manager.open)_ticket](http://project-manager.open)_ticket) (parent_id=root_id)

      └─ task-executor.execute_task (parent_id=open_ticket_id)

          ├─ step-1.implement_feature (parent_id=execute_task_id)

          ├─ step-2.add_tests (parent_id=execute_task_id)

          └─ review-implementation.main (parent_id=execute_task_id)

```

**Trade-offs**:

- ✅ Queryable hierarchy for workflow repair agent
- ✅ Enables precise process tree killing (kill children, preserve root)
- ✅ Supports arbitrary nesting depth
- ⚠️ Requires discipline: every step spawn must log parent context

---

### 3. Stack-Based Step Context Management

**Decision**: Use `@step` decorator (not `@log_step`) that both logs AND manages execution context via stack.

**Pattern A - Automatic Context Management** (Decorator):

```python

@step(step_name="discover_scope_files")

def discover_scope_files(working_dir: str, start_commit: str):

    # Function body - context automatically managed

    pass

```

Decorator:

- Creates step execution record in PostgreSQL
- Pushes step ID onto context stack (parent = current stack top)
- Logs entry (function name, args)
- Executes function
- Logs exit (duration, status)
- Pops step ID from stack
- On exception: marks step as 'failed', does NOT catch/log the exception

**Pattern B - Explicit Event Logging** (Direct calls):

```python

from scripts.core.workflow.logger import get_step_logger

logger = get_step_logger()  # Gets current step from stack top

logger.log_event("scope_discovery", {"files_found": 42})

```

**Stack Behavior**:

- Nested `@step` calls: child's parent_id = current stack top
- Async functions: fork with own stack
- Exceptions: bubble up (no try/catch), agents handle via workflow repair

**Trade-offs**:

- ✅ Automatic parent-child relationships
- ✅ No manual context passing
- ✅ Supports arbitrary nesting
- ✅ Async-safe (separate stacks)
- ⚠️ Stack must be initialized at workflow entry point

---

### 4. Process Monitoring via CLI Wrapper

**Decision**: Create `monitored-run` CLI wrapper for subprocess tracking and management.

**Usage Pattern**:

```bash

# Instead of: uv run pr review-loop --ticket NES-123

monitored-run uv run pr review-loop --ticket NES-123

```

**Wrapper Responsibilities**:

1. Launch target command in its own process group/session (so the full child tree is killable)
2. Forward termination signals (SIGINT/SIGTERM) cleanly to the process group
3. Provide an explicit, user-visible wrapper for “this run is monitored/killable”
4. Optionally expose PID/process-group info for debugging (stdout), **without writing to the workflow database**
5. **Does NOT create step execution records** (that’s `@step`’s job)
6. **Does NOT create step context** (that’s `@step`’s job)
7. Provides process safety and killability only

**Integration with Autonomous Monitoring**:

- Monitoring agent queries `step_executions` for running processes
- On anomaly detection, queries process tree via PID
- Kills process tree using `psutil.Process(pid).children(recursive=True)`
- Preserves root interactive agents (project-manager, ticket-manager)

**Trade-offs**:

- ✅ Explicit and visible to users
- ✅ No modification to existing workflows required
- ✅ Cross-platform (psutil handles OS differences)
- ⚠️ Users must remember to use `monitored-run` for critical workflows

---

### 5. Interactive Multi-Pass Task Decomposition

**Decision**: Task decomposition uses iterative agent-driven splitting with approval gates and historical context.

**Workflow**:

1. **Pattern Discovery Agent**: Analyzes task, identifies step boundary patterns, generates regex
2. **Candidate Surfacing Script**: Python script uses regex to find all potential split points
3. **Approval Agent**: Reviews each candidate with full history, approves/denies split
4. **Split Execution**: Approved candidates split into separate files
5. **Verification Agent**: Checks each split file for multiple steps
6. **Recursive Splitting**: If multiple steps found, repeat process on that file with history
7. **Convergence**: Loop until all files approved OR agents explicitly give up

**History Tracking**:

- Track each file's journey: denials, split attempts, reasoning
- If file denied but no split performed, next iteration receives full history
- Agent must either:
  - Split successfully (verify split occurred)
  - Give up with explicit reasoning and mark as problem
- "Split this" agent must eventually accept "don't split this" and mark problem
- **No max iterations** - convergence through bug fixing, not arbitrary limits
- **Progress-based circuit breakers**: each pass must introduce new evidence; repeated identical outcomes must produce an explicit give-up record (no endless retries).

**Orchestration Script**: `scripts/core/task_decomposition/orchestrator.py`

- Called by task execution workflow (not directly by user or ticket-manager)
- Manages agent invocations and file operations
- Maintains state: approved files, denied files, pending files, history per file
- Tracks aborted executions (don't count toward baselines)

**Trade-offs**:

- ✅ Handles ambiguous step boundaries robustly
- ✅ Agent approval prevents false splits
- ✅ History prevents infinite loops between agents
- ✅ Explicit give-up mechanism for unsplittable tasks
- ⚠️ Multiple agent invocations increase latency
- ⚠️ History accumulation increases context size

---

### 6. Composite ID System with Source Tracking

**Decision**: Use composite IDs with source prefixes to avoid collisions across systems.

**ID Format**: `{SOURCE}-{PROJECT_ID}-{TICKET_ID}`

- Linear ticket: `LIN-1-NES-123` (source=LIN, project=1, ticket=NES-123)
- Local project: `LOC-1` (source=LOC, project=1)
- Local ticket: `LOC-1-T-5` (source=LOC, project=1, ticket=T-5)

**ID Types Table**:

```sql

CREATE TABLE id_sources (

    source_id SMALLSERIAL PRIMARY KEY,

    prefix TEXT UNIQUE NOT NULL,        -- e.g., 'LIN', 'LOC'

    name TEXT NOT NULL,                 -- e.g., 'Linear', 'Local'

    description TEXT,

    counter INTEGER DEFAULT 0,           -- For local ID generation

    validation_regex TEXT,

    created_at TIMESTAMPTZ DEFAULT now()

);

```

**Worktree Naming**: Uses IDs only (no human-readable names)

- Project worktree: `.worktrees/LIN-1/`
- Ticket worktree: `.worktrees/LIN-1-NES-123/`

**Branching Strategy**:

- Project worktree: Creates branch `project/{PROJECT-ID}` from current branch (e.g., `project/LIN-1` from `main`)
- Ticket worktree: Creates branch `ticket/{TICKET-ID}` from project branch (e.g., `ticket/LIN-1-NES-123` from `project/LIN-1`)
- Merge strategy: Always merge to where we branched from (hierarchical)
  - Ticket branch → project branch
  - Project branch → original branch (e.g., main)
- Branch cleanup: Delete branches after successful merge

**Commit Metadata Format (preferred)**: Git commit trailers (stable + machine-parseable)

- Trailer: `Ticket-ID: {TICKET-ID}` (e.g., `Ticket-ID: LIN-1-NES-123`)
- Optional trailer: `Project-ID: {PROJECT-ID}` (e.g., `Project-ID: LIN-1`)
- Optional trailer: `Workflow-Run: {RUN-ID}` / `Step-Execution: {STEP-EXECUTION-ID}` for deep traceability

**Fallback parsing**: For backwards compatibility, also accept `[TICKET-{TICKET-ID}]` prefixes, but new commits should emit trailers.

**Shared Helper**: `scripts/core/git/trailers.py` provides parse + emit functions to ensure consistent trailer handling across all tools.

**Trade-offs**:

- ✅ Prevents ID collisions across sources
- ✅ Queryable source metadata
- ✅ Supports multiple external systems (Linear, Jira, GitHub)
- ⚠️ Worktree names less human-readable (mitigated by project metadata in DB)

---

---

### 7. Trace Promotion and In-Flight Tracing Toggle

**Decision**: Build tracing into step/workflow instrumentation with **levels** (off/standard/verbose), and allow trace escalation **mid-run** for a specific step/workflow.

**Why**:

- Monitoring needs observability for long-running steps that produce no logs.
- Tracing should be available without forcing isolated “simulation” runs.

**Pattern**:

- Default: new/unstable workflows run in **verbose trace mode** (function enter/exit, timing; inputs/outputs where safe).
- As a workflow matures, reduce emitted trace events (“promote” to optimized mode).
- Monitoring agent can set a per-step/per-workflow trace level (stored in `step_executions.metadata` or a dedicated config table).
- Instrumentation periodically checks trace level and turns tracing on/off (or handles a signal toggle).

**Storage**:

- Trace events are written as structured rows to `context_logs` (event_type: `trace_event`).
- UI and repair tooling consume trace events like any other log event.

**Trade-offs**:

- ✅ Diagnoses hangs without killing immediately
- ✅ Avoids heavy isolated simulations as the default path
- ⚠️ Must keep tracing overhead bounded (levels + sampling)

---

### 8. Operational Writes via `control_actions` (UI → Monitor)

**Decision**: The monitoring UI is read-mostly. Any operational write (suspend/restart, trace escalation, etc.) is represented as an append-only request in `control_actions`, and applied by the monitoring agent (or a coordinator component).

**Why**:

- Multiple independent processes/agents will interact with workflow state.
- Direct UI writes to “live state” complicate concurrency and auditing.
- Append-only actions provide a durable audit trail and support retries/reconciliation.

**Notes**:

- “Acknowledge”/hide is UI-local preference (stored in UI config), not a mutation of operational state.

---

### 9. Schema Versioning and Migrations

**Decision**: Use migrations (Alembic or equivalent) and avoid hand-editing schema in-place.

- Every schema change is a migration with an explicit version.
- Application startup validates schema version before running workflows.

---

## Data Model

### Conventions

- **Repository scoping**: all domain objects are scoped by `repo_id` (see `repositories`).
- **Cursor reads**: `context_logs.id` is a monotonic `BIGSERIAL` used for UI/agent cursors.
- **Timestamps**: use `TIMESTAMPTZ` `now()`).
- **JSON**: use `JSONB` for flexible payloads `context_logs.data`, config blobs, etc.).
- **UUIDs**: use `gen_random_uuid()` (requires `pgcrypto`).

### Required Extensions

```sql

CREATE EXTENSION IF NOT EXISTS pgcrypto;

```

### Core Tables

#### `repositories`

Tracks repositories/workspaces on the dev machine and stores cross-platform root aliases.

```sql

CREATE TABLE repositories (

    repo_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    display_name TEXT NOT NULL,

    -- Optional per-OS root aliases for “open file/worktree” UX

    windows_root TEXT,

    wsl_root TEXT,

    -- Optional metadata for stability/debug

    git_remote_url TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

);

CREATE INDEX repositories_display_name_idx ON repositories (display_name);

```

#### `id_sources`

Tracks ID source systems and validation rules.

```sql

CREATE TABLE id_sources (

    source_id SMALLSERIAL PRIMARY KEY,

    prefix TEXT UNIQUE NOT NULL,             -- 'LIN', 'LOC', 'GH'

    name TEXT NOT NULL,                      -- 'Linear', 'Local', 'GitHub'

    description TEXT,

    counter INTEGER NOT NULL DEFAULT 0,       -- For local ID generation

    validation_regex TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()

);

```

#### `projects`

```sql

CREATE TABLE projects (

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    project_id TEXT NOT NULL,

    source_id SMALLINT NOT NULL REFERENCES id_sources(source_id),

    remote_id TEXT,                          -- external ID (if ever integrated)

    name TEXT NOT NULL,

    description TEXT,

    worktree_path TEXT NOT NULL,

    branch TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'active',   -- active|completed|archived

    config JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (repo_id, project_id)

);

CREATE INDEX projects_repo_status_idx ON projects (repo_id, status);

```

#### `tickets`

```sql

CREATE TABLE tickets (

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    ticket_id TEXT NOT NULL,

    project_id TEXT NOT NULL,

    source_id SMALLINT NOT NULL REFERENCES id_sources(source_id),

    remote_id TEXT,

    title TEXT NOT NULL,

    description TEXT,

    worktree_path TEXT NOT NULL,

    branch TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'open',     -- open|in_progress|blocked|done

    ordering JSONB,                          -- dependency ordering + rationale

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (repo_id, ticket_id),

    FOREIGN KEY (repo_id, project_id) REFERENCES projects (repo_id, project_id)

);

CREATE INDEX tickets_repo_project_status_idx ON tickets (repo_id, project_id, status);

```

#### `tasks`

```sql

CREATE TABLE tasks (

    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    ticket_id TEXT NOT NULL,

    title TEXT NOT NULL,

    description TEXT,

    decomposed_steps_path TEXT,              -- path to generated step files

    status TEXT NOT NULL DEFAULT 'open',     -- open|in_progress|done

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    FOREIGN KEY (repo_id, ticket_id) REFERENCES tickets (repo_id, ticket_id)

);

CREATE INDEX tasks_repo_ticket_status_idx ON tasks (repo_id, ticket_id, status);

```

#### `workflow_runs`

Groups a coherent “run” across restarts (important for monitoring + resume).

```sql

CREATE TABLE workflow_runs (

    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    workflow_type TEXT NOT NULL,             -- task_exec|rebase|review|repair|other

    project_id TEXT,

    ticket_id TEXT,

    task_id UUID,

    status TEXT NOT NULL DEFAULT 'running',  -- running|completed|failed|suspended

    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    ended_at TIMESTAMPTZ,

    root_step_execution_id UUID,             -- set after first step is created

    metadata JSONB,

    FOREIGN KEY (repo_id, project_id) REFERENCES projects (repo_id, project_id),

    FOREIGN KEY (repo_id, ticket_id) REFERENCES tickets (repo_id, ticket_id),

    FOREIGN KEY (task_id) REFERENCES tasks (task_id)

);

CREATE INDEX workflow_runs_repo_status_started_idx ON workflow_runs (repo_id, status, started_at DESC);

```

#### `step_executions`

```sql

CREATE TABLE step_executions (

    step_execution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    run_id UUID NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,

    parent_step_execution_id UUID REFERENCES step_executions(step_execution_id),

    restart_of_step_execution_id UUID REFERENCES step_executions(step_execution_id),

    attempt INTEGER NOT NULL DEFAULT 1,

    workflow_type TEXT NOT NULL,

    function_context TEXT NOT NULL,          -- e.g., [scripts.pr.review](http://scripts.pr.review)_loop.main

    branch TEXT,

    project_id TEXT,

    ticket_id TEXT,

    task_id UUID REFERENCES tasks(task_id),

    process_id INTEGER,                      -- OS PID (if applicable)

    status TEXT NOT NULL DEFAULT 'running',  -- running|completed|failed|suspended|aborted

    start_time TIMESTAMPTZ NOT NULL DEFAULT now(),

    end_time TIMESTAMPTZ,

    metadata JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()

);

CREATE INDEX step_exec_run_idx ON step_executions (run_id);

CREATE INDEX step_exec_parent_idx ON step_executions (parent_step_execution_id);

CREATE INDEX step_exec_repo_status_idx ON step_executions (repo_id, status);

```

#### `context_logs`

Append-only event stream (the primary monitoring substrate).

```sql

CREATE TABLE context_logs (

    id BIGSERIAL PRIMARY KEY,

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    run_id UUID NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,

    step_execution_id UUID NOT NULL REFERENCES step_executions(step_execution_id) ON DELETE CASCADE,

    ts TIMESTAMPTZ NOT NULL DEFAULT now(),

    event_type TEXT NOT NULL,                -- info|debug|trace_event|deviation|other

    schema_version INTEGER NOT NULL DEFAULT 1,

    data JSONB NOT NULL

);

CREATE INDEX context_logs_repo_id_idx ON context_logs (repo_id, id);

CREATE INDEX context_logs_step_id_idx ON context_logs (step_execution_id, id);

CREATE INDEX context_logs_run_id_idx ON context_logs (run_id, id);

CREATE INDEX context_logs_event_type_idx ON context_logs (event_type);

-- Optional: GIN index if querying inside JSON becomes common

-- CREATE INDEX context_logs_data_gin ON context_logs USING GIN (data);

```

#### `deviations`

```sql

CREATE TABLE deviations (

    deviation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,

    step_execution_id UUID REFERENCES step_executions(step_execution_id),

    description TEXT NOT NULL,

    severity TEXT NOT NULL DEFAULT 'medium', -- low|medium|high

    justification TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()

);

CREATE INDEX deviations_task_idx ON deviations (task_id);

```

#### `errors`

```sql

CREATE TABLE errors (

    id BIGSERIAL PRIMARY KEY,

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    error_code TEXT NOT NULL,                -- category / classifier

    description TEXT NOT NULL,

    instructions TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'open',     -- open|resolved|ignored

    affected_step_execution_ids UUID[],

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    resolved_at TIMESTAMPTZ

);

CREATE INDEX errors_repo_status_created_idx ON errors (repo_id, status, created_at DESC);

```

#### `suspended_processes`

```sql

CREATE TABLE suspended_processes (

    suspension_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    step_execution_id UUID NOT NULL REFERENCES step_executions(step_execution_id) ON DELETE CASCADE,

    error_id BIGINT REFERENCES errors(id),

    killed_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    resumed_at TIMESTAMPTZ,

    status TEXT NOT NULL DEFAULT 'suspended',  -- suspended|restarted|abandoned

    metadata JSONB

);

CREATE INDEX suspended_repo_status_idx ON suspended_processes (repo_id, status);

```

#### `conflict_resolutions`

```sql

CREATE TABLE conflict_resolutions (

    resolution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    commit_sha TEXT NOT NULL,

    project_id_1 TEXT NOT NULL,

    project_id_2 TEXT NOT NULL,

    resolution_type TEXT NOT NULL,           -- auto|manual|escalated

    resolution_text TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    FOREIGN KEY (repo_id, project_id_1) REFERENCES projects (repo_id, project_id),

    FOREIGN KEY (repo_id, project_id_2) REFERENCES projects (repo_id, project_id)

);

CREATE INDEX conflict_resolutions_repo_created_idx ON conflict_resolutions (repo_id, created_at DESC);

```

#### `step_timings`

Stores historical timing samples for baselines (exclude aborted attempts).

```sql

CREATE TABLE step_timings (

    id BIGSERIAL PRIMARY KEY,

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    workflow_type TEXT NOT NULL,

    function_context TEXT NOT NULL,

    duration_ms INTEGER NOT NULL,

    aborted BOOLEAN NOT NULL DEFAULT FALSE,

    completed_at TIMESTAMPTZ NOT NULL DEFAULT now()

);

CREATE INDEX step_timings_repo_wf_fn_idx ON step_timings (repo_id, workflow_type, function_context);

```

#### `investigation_conclusions`

```sql

CREATE TABLE investigation_conclusions (

    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    step_execution_id UUID NOT NULL REFERENCES step_executions(step_execution_id) ON DELETE CASCADE,

    investigation_type TEXT NOT NULL,

    conclusion TEXT NOT NULL,

    code_state_hash TEXT NOT NULL,           -- e.g., HEAD commit SHA

    legitimate BOOLEAN NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()

);

CREATE INDEX investigation_repo_created_idx ON investigation_conclusions (repo_id, created_at DESC);

```

#### `control_actions`

Append-only requests for operational changes (UI → monitoring agent).

```sql

CREATE TABLE control_actions (

    id BIGSERIAL PRIMARY KEY,

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    created_by TEXT NOT NULL,                -- ui|monitor|user|system

    action_type TEXT NOT NULL,               -- set_trace|suspend|restart|ack|other

    target JSONB,                            -- e.g., {"run_id": "<uuid>"} or {"step_execution_id": "<uuid>"}

    payload JSONB,                           -- action-specific payload

    status TEXT NOT NULL DEFAULT 'pending',  -- pending|applied|rejected|failed

    applied_at TIMESTAMPTZ,

    result JSONB

);

CREATE INDEX control_actions_repo_status_created_idx ON control_actions (repo_id, status, created_at DESC);

```

#### `trace_overrides`

Stores the effective desired trace levels (updated by monitoring agent based on control actions).

```sql

CREATE TABLE trace_overrides (

    id BIGSERIAL PRIMARY KEY,

    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,

    scope_type TEXT NOT NULL,                -- global|workflow_type|run|step

    workflow_type TEXT,

    run_id UUID,

    step_execution_id UUID,

    trace_level TEXT NOT NULL,               -- off|standard|verbose

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

);

CREATE INDEX trace_overrides_repo_scope_idx ON trace_overrides (repo_id, scope_type, updated_at DESC);

```

### Notes on Change Signaling

- Writers can `NOTIFY workflow_events, '<small payload>'` after committing new `context_logs`.
- Consumers (UI/agents) must always use **cursor reads** `id > last_id`) for correctness.

### Schema Migrations

- Use Alembic (SQLAlchemy) or a lightweight migration runner.
- A migration table (e.g., `alembic_version`) is created/managed by the migration tool.

### Integration with Existing article_writer Models

**Approach**: article_writer models remain in `scripts/article_writer/tools/workflow/models.py` during the transition period (article_writer may still use its legacy storage until migrated). Future refactoring will move shared patterns to `scripts/core/workflow/models.py`.

**Shared Patterns**:

- `Workflow` → Generalized to support multiple workflow types
- `Session` → Replaced by `step_executions` (more granular)
- `ContextLog` → Reused as-is
- `Artifact` → Extended to support project/ticket artifacts

---

## Core Workflow Module `scripts/core/workflow/`

**Purpose**: Shared infrastructure for all workflow systems.

### `database.py`

- PostgreSQL engine/pool management (SQLAlchemy + `psycopg`)
- Connection configured via `WORKFLOW_DB_URL` (or `.env` loaded by the CLI)
- Applies schema migrations at startup (Alembic or lightweight migration runner)
- Provides session/context manager helpers for short transactions
- Connection pool configuration:
  - `pool_size=5` (default)
  - `max_overflow=10`
  - `pool_pre_ping=True` (verify connections before use)
  - `pool_recycle=3600` (recycle connections after 1 hour)
- Optional helpers:
  - `register_repository()` / `resolve_repo_id()`
  - `notify_workflow_events(repo_id, payload)` (wakeup-only)
  - `prune_logs(repo_id, days=30)` (log retention)

### `models.py`

- Defines all tables from Data Model section using SQLAlchemy ORM
- Type hints for all fields
- Relationship definitions with cascade rules
- Validation logic for composite IDs

### `state_machine.py`

- Generalized state machine supporting multiple workflow types
- Phase transitions configurable per workflow type
- Suspension/restart logic with context preservation
- State persistence in PostgreSQL

### `logger.py`

*`@step` Decorator**:

- Creates step execution record in PostgreSQL
- Pushes step ID onto context stack (parent = current stack top)
- Logs entry (function name, args, branch, repository)
- Executes function
- Logs exit (duration, status)
- Pops step ID from stack
- On exception: marks step as 'failed', does NOT catch the exception
- Supports async functions (fork stack)

*`StepLogger` Class**:

- Explicit event logging: `logger.log_event(event_type, data)`
- Gets current step from stack top
- Writes to `context_logs` table

**Stack Management**:

- `contextvars`-backed stack for nested `@step` calls
- Automatic parent-child relationships
- Async-safe (separate stacks per async context via `contextvars`)

### `context_manager.py`

- GLM-based context summarization (adapted from article_writer)
- Reviews **incremental git diffs** (only from previous step, not all prior steps)
- Maintains running summary, refines for each new step
- Tracks deviations from plan (different naming, implementation changes)
- Stores summaries and deviations in PostgreSQL
- Reviews historical conclusions when code changes
- Provides context to step execution agents

**Key Pattern**: Incremental diff review prevents performance degradation as tasks grow.

---

## References

- Existing patterns: fil`scripts/article_writer/tools/workflow/models.py`, fil`scripts/article_writer/tools/workflow/database.py`
- Related specs: spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/4f9481c9-455d-4808-b7b4-a60eabb66a43 (Epic Brief), spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/27e8f1ea-0534-442e-8508-03e5eb38be68 (Core Flows)

