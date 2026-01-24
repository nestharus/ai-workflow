# Tech Plan: Integration & File Structure

## # Tech Plan: Integration & File Structure

## Overview

This spec defines how the new infrastructure integrates with existing workflows and the complete file structure for the system.

**Invariants**:

- Local dev machines only (not distributed, not cloud)
- PostgreSQL state is local and must not be committed (persisted in a local Docker volume; not stored in the repo)
- No Traycer/Linear API integrations; docs loaded manually
- No external brokers/queues; UI uses PostgreSQL `LISTEN/NOTIFY` wakeups + cursor reads

**Related Specs**: 

- spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/4f9481c9-455d-4808-b7b4-a60eabb66a43 (Epic Brief)
- spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/27e8f1ea-0534-442e-8508-03e5eb38be68 (Core Flows)

---

## Retrofitting Logging to Existing Workflows

**Affected Workflows**:

- fil`.claude/commands/review-implementation.md`
- fil`.claude/commands/update-pr.md`
- fil`.claude/commands/rebase.md`
- fil`.claude/commands/merge.md`

**Approach**:

1. Wrap Python script invocations with `monitored-run` (for process safety)
2. Add `@step` decorators to key functions (for step tracking)
3. Add explicit `logger.log_event()` calls at decision points

**Note**: `monitored-run` and `@step` serve different purposes:

- `monitored-run`: Process management (PID tracking, killability)
- `@step`: Execution tracking (context, logging, hierarchy)

**Example Retrofit** (review-implementation):

```python

# Before

def run_reviewer(plan_file, files, review_file, working_dir):

    # Implementation

    pass

# After

from scripts.core.workflow.logger import step, get_step_logger

@step(step_name="run_reviewer")

def run_reviewer(plan_file, files, review_file, working_dir):

    logger = get_step_logger()

    logger.log_event("reviewer_started", {"files_count": len(files)})

    # Implementation

    logger.log_event("reviewer_completed", {"issues_found": issue_count})

```

---

## Agent Runner Integration

**Modification**: Extend fil`scripts/dev/agent_runner.py` base class with logging hooks.

**Changes**:

```python

from scripts.core.workflow.logger import step

class AgentRunner(ABC):

    @step  # Decorator infers step_name from function name

    def run(self, prompt: str) -> str:

        # @step decorator handles:

        # - Creating step execution record

        # - Pushing to context stack

        # - Logging entry/exit

        # - Marking as failed on exception (doesn't catch)

        result = self._execute(prompt)  # Subclass implements

        return result

    @abstractmethod

    def _execute(self, prompt: str) -> str:

        # Subclass implements provider-specific execution

        # This is NOT decorated - only public run() method is tracked

        pass

```

**Note**: `monitored-run` wraps the subprocess that invokes the agent. It provides process safety but does NOT create step execution records. The `@step` decorator on `AgentRunner.run()` creates the step execution record.

**Backward Compatibility**: Existing agent runners continue to work without modification. The `@step` decorator initializes context stack if not already initialized.

---

## Complete File Structure

```

scripts/

├── core/

│   ├── workflow/

│   │   ├── **init**.py

│   │   ├── [[database.py](http://database.py)]([http://database.py](http://database.py))          # Shared Postgres database client + session management

│   │   ├── [[models.py](http://models.py)]([http://models.py](http://models.py))            # SQLAlchemy models (Postgres)

│   │   ├── state_[[machine.py](http://machine.py)]([http://machine.py](http://machine.py))     # Generalized StateMachine

│   │   ├── [[logger.py](http://logger.py)]([http://logger.py](http://logger.py))            # StepLogger + @step decorator

│   │   ├── trace_[[controller.py](http://controller.py)]([http://controller.py](http://controller.py))   # Trace level toggle/promotion (in-flight)

│   │   └── context_[[manager.py](http://manager.py)]([http://manager.py](http://manager.py))   # GLM-based context summarization

│   ├── process_management/

│   │   ├── **init**.py

│   │   ├── monitored_[[run.py](http://run.py)]([http://run.py](http://run.py))     # CLI wrapper entry point

│   │   ├── process_[[tracker.py](http://tracker.py)]([http://tracker.py](http://tracker.py))   # Process tree management

│   │   ├── snapshot_[[export.py](http://export.py)]([http://export.py](http://export.py))    # (optional) Export workflow/run snapshot to investigation worktree

│   │   ├── investigation_[[cleanup.py](http://cleanup.py)]([http://cleanup.py](http://cleanup.py))  # (optional) Cleanup investigation worktrees

│   │   ├── call_graph_[[analyzer.py](http://analyzer.py)]([http://analyzer.py](http://analyzer.py))    # Continuous call graph analysis

│   │   └── anomaly_[[detector.py](http://detector.py)]([http://detector.py](http://detector.py))  # Baseline + anomaly detection

│   └── task_decomposition/

│       ├── **init**.py

│       ├── [[orchestrator.py](http://orchestrator.py)]([http://orchestrator.py](http://orchestrator.py))      # Main orchestration script

│       ├── pattern_discovery_[[agent.md](http://agent.md)]([http://agent.md](http://agent.md))

│       ├── candidate_[[surfacing.py](http://surfacing.py)]([http://surfacing.py](http://surfacing.py))

│       ├── approval_[[agent.md](http://agent.md)]([http://agent.md](http://agent.md))

│       └── verification_[[agent.md](http://agent.md)]([http://agent.md](http://agent.md))

├── project_manager/

│   ├── **init**.py

│   ├── [[cli.py](http://cli.py)]([http://cli.py](http://cli.py))                   # /project-manager command

│   ├── project_[[dao.py](http://dao.py)]([http://dao.py](http://dao.py))           # Database access

│   └── ticket_[[ordering.py](http://ordering.py)]([http://ordering.py](http://ordering.py))       # Dependency inference

├── ticket_manager/

│   ├── **init**.py

│   ├── [[cli.py](http://cli.py)]([http://cli.py](http://cli.py))                   # /ticket-manager command

│   ├── ticket_[[dao.py](http://dao.py)]([http://dao.py](http://dao.py))            # Database access

│   └── task_[[executor.py](http://executor.py)]([http://executor.py](http://executor.py))         # Task execution workflow

├── monitoring/

│   ├── **init**.py

│   ├── monitoring_[[agent.py](http://agent.py)]([http://agent.py](http://agent.py))      # Background monitoring process

│   └── workflow_repair_[[agent.md](http://agent.md)]([http://agent.md](http://agent.md))

├── evaluation/

│   ├── **init**.py

│   ├── create_evaluation_[[worktree.py](http://worktree.py)]([http://worktree.py](http://worktree.py))

│   └── gap_[[analyzer.py](http://analyzer.py)]([http://analyzer.py](http://analyzer.py))

├── artifact_export/

│   ├── **init**.py

│   └── export_[[project.py](http://project.py)]([http://project.py](http://project.py))

└── pr/

    ├── rebase_[[enhanced.py](http://enhanced.py)]([http://enhanced.py](http://enhanced.py))       # Enhanced rebase with conflict resolution

    └── other existing PR scripts

ui/

└── workflow-monitor/            # Tauri app

    ├── src-tauri/

    │   ├── src/

    │   │   ├── [[main.rs](http://main.rs)]([http://main.rs](http://main.rs))

    │   │   ├── [[db.rs](http://db.rs)]([http://db.rs](http://db.rs))

    │   │   ├── change_[[monitor.rs](http://monitor.rs)]([http://monitor.rs](http://monitor.rs))   # Postgres LISTEN/NOTIFY + cursor polling

    │   │   └── [[ipc.rs](http://ipc.rs)]([http://ipc.rs](http://ipc.rs))

    │   └── Cargo.toml

    └── src/

        ├── App.tsx

        └── components/

            ├── ProjectSelector.tsx

            ├── WorkflowList.tsx

            ├── ExecutionTimeline.tsx

            ├── LogViewer.tsx

            ├── NotificationCenter.tsx

            └── ErrorDashboard.tsx

.dev/

└── postgres/

    ├── docker-compose.yml        # Local Postgres container (volume-backed PGDATA directory)

    └── [README.md](http://README.md)                 # Local DB setup + connection strings (WSL/Windows)

.claude/

└── commands/

    ├── [[project-manager.md](http://project-manager.md)]([http://project-manager.md](http://project-manager.md))       # New command

    └── [[ticket-manager.md](http://ticket-manager.md)]([http://ticket-manager.md](http://ticket-manager.md))        # New command

```

---

## Worktree Lifecycle Management

### `scripts/core/git/trailers.py`

**Purpose**: Shared helper for Git commit trailer parsing and emission.

**Functions**:
- `parse_trailers(commit_sha: str) -> dict`: Parse trailers from commit message
- `emit_trailers(ticket_id: str, project_id: str) -> str`: Generate trailer text for commit message
- `extract_ticket_id(commit_sha: str) -> str`: Extract ticket ID (trailers first, fallback to `[TICKET-{id}]` prefix)

**Usage**: All tools that create commits or parse commit metadata MUST use this helper to ensure consistency.

### `scripts/core/git/worktree_gc.py`

**Purpose**: Worktree lifecycle management and cleanup.

**Command**: `uv run python -m scripts.core.git.worktree_gc [--force]`

**Behavior**:
1. Enumerate all worktrees (via `git worktree list`)
2. For each worktree:
   - Check if dirty (uncommitted changes)
   - If dirty: Archive patch to `.tmp/worktree-patches/{worktree-name}.patch`
   - If clean OR `--force`: Remove worktree + delete branch
3. Report removed worktrees and archived patches

**Safety**: Refuses to remove dirty worktrees unless `--force` is specified.

### `scripts/core/git/worktree_detection.py`

**Purpose**: Detect project and ticket worktrees for project-manager and ticket-manager.

**Functions**:
- `detect_projects() -> list[dict]`: Scan `.worktrees/` for project worktrees, return metadata
- `detect_tickets(project_id: str) -> list[dict]`: Scan for ticket worktrees under a project
- `is_worktree_open(worktree_path: str) -> bool`: Check if worktree has active processes

---

## Integration Notes

### Workflows to Retrofit

1. **fil`.claude/commands/review-implementation.md**`
  - Add `@step` to `run_reviewer()`, `discover_scope_files()`, `generate_review()`
  - Wrap invocation with `monitored-run`
2. **fil`.claude/commands/update-pr.md**`
  - Add `@step` to main execution functions
  - Reused by task execution workflow
3. **fil`.claude/commands/rebase.md**`
  - Enhanced version in `scripts/pr/rebase_enhanced.py`
  - Add `@step` to conflict resolution functions
4. **fil`.claude/commands/merge.md**`
  - Add `@step` to merge verification functions
  - Wrap invocation with `monitored-run`

### Agent Runner Modifications

- fil`scripts/dev/agent_runner.py`: Add `@step` decorator to `run()` method
- All subclasses automatically inherit logging
- No changes required to existing agent implementations

---

## References

- Core infrastructure: spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/[CORE_INFRA_SPEC_ID]
- Monitoring: spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/[MONITORING_SPEC_ID]
- Project management: spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/[PROJECT_MGMT_SPEC_ID]

