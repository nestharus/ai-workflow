# Tech Plan: Monitoring UI (Tauri)

## # Tech Plan: Monitoring UI (Tauri)

## Overview

This spec defines the Tauri desktop application for real-time workflow monitoring and visualization.

**Related Specs**:

- spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/4f9481c9-455d-4808-b7b4-a60eabb66a43 (Epic Brief)
- spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/27e8f1ea-0534-442e-8508-03e5eb38be68 (Core Flows)

---

## Architectural Decision: PostgreSQL `LISTEN/NOTIFY` + Cursor Reads

**Decision**: The desktop UI connects to a **local PostgreSQL database** (running on the same dev machine, typically via Docker). The UI receives low-latency “wake up” signals via `LISTEN/NOTIFY`, and uses **cursor-based reads** for correctness and replay.

This replaces file-based change signaling. The UI never reads database files across the WSL/Windows filesystem boundary.

### Architecture

- **Backend (Rust)**:
  - `sqlx` (PostgreSQL) for queries
  - One connection dedicated to `LISTEN workflow_events`
  - A small query pool for read operations
  - Tauri IPC for frontend communication
- **Frontend (React + TypeScript)**:
  - Real-time updates via Tauri event system
  - Local UI state for filters, cursors, and “acknowledged” notifications

### Update Mechanism (NOTIFY is a wakeup, not the data plane)

- UI maintains `{repo_id -> last_context_log_id}` cursors (and optionally `last_error_id`).
- Writers emit a `NOTIFY workflow_events, '<small payload>'` after committing batches (payload can be JSON text, but must stay small).
- On notify:
  1. Backend queries for new rows:
    - `context_logs WHERE id > last_context_log_id ORDER BY id LIMIT {page_size}`
    - `errors WHERE id > last_error_id ORDER BY id LIMIT {page_size}`
  2. Backend streams results to frontend via Tauri events.
- **Fallback polling**: backend also polls (e.g., every 1–2s) to recover from missed notifications or reconnects.

### UI write policy

- Monitoring UI is **read-mostly**.
- Any operational write is done by inserting an append-only control request:
  - Insert into `control_actions` (e.g., request trace escalation, suspend/restart, mark resolution).
- UI “Acknowledge” (hide/unhide) is **local preference only** and stored in `~/.workflow-monitor.json` (does not mutate operational DB state).

### Multi-repository and cross-platform paths

- Database uses a stable `repo_id` per repository.
- UI stores local path aliases per `repo_id` (Windows path vs WSL/Linux path) so “open file” / “open worktree” actions can be platform-correct.

### Trade-offs

- ✅ Cross-platform (Linux, macOS, Windows)
- ✅ Safe for WSL + Windows because DB access is over TCP, not filesystem sharing
- ✅ Supports many concurrent writers (many agents)
- ✅ No external brokers/queues required (NOTIFY used only as a wakeup)
- ⚠️ Requires local Postgres (container/service) running
- ⚠️ UI must handle reconnects and cursor catch-up

---

## Component Architecture

### Backend (Rust) - `ui/workflow-monitor/src-tauri/`

#### `src/main.rs`

- Tauri app entry point
- Initializes PostgreSQL connections (listen connection + query pool)
- Sets up IPC handlers
- Manages application lifecycle and reconnect logic

#### `src/db.rs`

- PostgreSQL queries via `sqlx`
- Read queries are performed with short-lived transactions (or autocommit)
- Queries:
  - `list_repositories()`: List repositories `repo_id`, display name, known path aliases)
  - `get_projects(repo_id)`: List projects in repo
  - `get_workflows(repo_id)`: Active and recent workflow runs
  - `get_step_executions(run_id)`: Step hierarchy for a run
  - `get_context_logs(repo_id, after_id)`: New events since cursor
  - `get_errors(repo_id, status)`: Open/resolved errors
  - `get_deviations(ticket_id)`: Implementation deviations

#### `src/change_monitor.rs`

- Postgres notification + polling loop
- `LISTEN workflow_events`
- On notify:
  - Fetch new `context_logs` rows using cursor reads
  - Fetch new/updated `errors` rows
  - Emit Tauri events to frontend
- Polling fallback (configurable interval) for catch-up and robustness

#### `src/ipc.rs`

- Tauri IPC handlers for frontend requests
- Commands:
  - `set_db_url(db_url)`: Update DB URL in local config
  - `list_repositories()`: Repositories from DB
  - `set_repo_path_alias(repo_id, path)`: Persist local alias in `~/.workflow-monitor.json`
  - `get_execution_trace(step_id)`: Full trace for debugging (server-side query)
  - `request_action(action_type, payload)`: Insert into `control_actions`
- Events:
  - `workflow_update`: New workflow started/completed
  - `step_update`: Step execution progress
  - `error_notification`: New error detected
  - `auto_resolution`: Error auto-resolved

---

### Frontend (React) - `ui/workflow-monitor/src/`

#### `App.tsx`

- Main app component
- Manages global state (selected repository/project, filters)
- Renders layout with sidebar and main content area

#### `components/ProjectSelector.tsx`

- Dropdown for selecting repository/project
- “Map Local Path” button (file picker) to set a per-machine alias path
- Shows repository status summary

#### `components/WorkflowList.tsx`

- Lists active and recent workflow runs
- Shows workflow type, status, duration
- Click to view execution timeline

#### `components/ExecutionTimeline.tsx`

- Gantt-style visualization of step executions
- Shows step hierarchy (nested steps)
- Click step to view logs

#### `components/LogViewer.tsx`

- Filterable log display
- Filters: event type, step, agent, time range
- Search functionality
- Syntax highlighting for code blocks

#### `components/NotificationCenter.tsx`

- Displays errors requiring user action
- Shows error ID, description, instructions
- “Acknowledge” button is local-only (hide/unhide), persisted to config

#### `components/ErrorDashboard.tsx`

- Shows auto-resolved errors (audit trail)
- Shows pending errors (awaiting user action)
- Filterable by repository, project, ticket, error type

---

## Configuration

### `~/.workflow-monitor.json`

Stores user preferences, DB URL, repository path aliases, and cursors.

```json

{

  "db": {

    "url": "postgresql://workflow:workflow@localhost:5432/workflow"

  },

  "repositories": [

    {

      "repo_id": "b3d6b23a-2a5c-4f0d-8ee7-2d4d1b1b6a5b",

      "display_name": "ai-workflow",

      "path_alias": "C:\\Users\\me\\projects\\ai-workflow"

    }

  ],

  "cursors": {

    "b3d6b23a-2a5c-4f0d-8ee7-2d4d1b1b6a5b": {

      "last_context_log_id": 12872,

      "last_error_id": 41

    }

  },

  "preferences": {

    "theme": "dark",

    "poll_interval_ms": 1500,

    "notification_sound": true

  },

  "acknowledged": {

    "errors": ["ERR-000041"]

  }

}

```

---

## Launch Mechanism

**User launches UI**: Runs standalone application executable

- **Linux/macOS**: `./workflow-monitor` (or via application launcher)
- **Windows**: `workflow-monitor.exe` (or via Start menu)
- **Development**: `cd ui/workflow-monitor && cargo tauri dev`

**On startup**:

1. Load configuration from `~/.workflow-monitor.json`
2. Connect to PostgreSQL (listen connection + query pool)
3. Fetch current state (repositories, active runs, recent history)
4. Start `LISTEN/NOTIFY` change monitoring
5. Start polling fallback timer
6. Display UI

---

## Security & IPC Hardening

**Decision**: Even for local-only apps, the WebView ↔ Rust boundary is a trust boundary. Tauri IPC commands must be scoped and capability-restricted.

**Enforced Constraints**:

1. **Scope File Access to Repo Roots Only**:
  - IPC commands that access filesystem (e.g., `open_file`, `read_worktree`) must validate paths
  - Deny access outside registered repository roots
  - Use Tauri's scope/allowlist features
2. **Capability-Based Permissions**:
  - Define explicit capabilities for each IPC command
  - Use Tauri's permission system to restrict command access
  - Example: `fs:read-repo` capability required for file reading
3. **Path Validation**:
  ```rust
   fn validate_repo_path(path: &Path, repo_roots: &[PathBuf]) -> Result<(), Error> {
       let resolved = path.canonicalize()?;
       for root in repo_roots {
           if resolved.starts_with(root) {
               return Ok(());
           }
       }
       Err(Error::PathOutsideRepoRoot)
   }
  ```
4. **Deny Everything by Default**:
  - Tauri configuration denies all filesystem/shell/protocol access by default
  - Only explicitly allowed operations are permitted
  - No arbitrary command execution from WebView

**Implementation**: Configure in `tauri.conf.json`:

```json
{
  "tauri": {
    "allowlist": {
      "all": false,
      "fs": {
        "scope": ["$REPO_ROOT/**"],
        "readFile": true,
        "writeFile": false
      },
      "shell": {
        "open": false,
        "execute": false
      }
    }
  }
}
```

---

## References

- Core infrastructure: spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/[CORE_INFRA_SPEC_ID]
- Monitoring: spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/[MONITORING_SPEC_ID]

