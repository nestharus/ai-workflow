# Processes

This module covers documentation for development processes like git releases, code
reviews, etc.

## Topics

### Operational Protocols

**File:** `operational-protocols.md`

Defines nine operational protocols for agent behavior: consulting the Knowledge Graph,
adhering to roles, using TOON for communication, submitting messages to the orchestrator,
avoiding long-running operations, using git worktrees, running validation commands,
allowing documentation edits, and addressing all review feedback.

**Apply when:**

* Starting any agent task or workflow
* Understanding agent responsibilities and constraints
* Troubleshooting agent behavior or protocol violations

### Command Patterns

**File:** `command-patterns.md`

Describes command types and invocation patterns for orchestrator message submission,
agent invocation via `droid exec`, and GitHub integration. Includes example curl commands
for submitting messages to `/api/v1/orchestrator/submit` and explains the agent execution
context.

**Apply when:**

* Submitting messages to the orchestrator
* Understanding agent invocation mechanisms
* Integrating GitHub workflows with the orchestrator

### Inter-Domain Handoffs

**File:** `inter-domain-handoffs.md`

Explains automated handoffs between domains (Product R1 -> UX R1 -> Technical R1) via
orchestrator message routing. Emphasizes that agents don't need to manage handoffs
manually; the orchestrator handles routing based on workflow definitions.

**Apply when:**

* Designing cross-domain workflows
* Understanding how work moves between domains
* Debugging handoff routing issues

### Ticket and PR URL Handling

**File:** `ticket-handling.md`

Describes the workflow for user-initiated tasks via PR or ticket URLs: user submission,
GitHub Agent invocation for detail fetching, automatic routing based on content (labels,
file paths), and first-come-first-served ticket claiming by agents.

**Apply when:**

* Processing user-submitted PR or ticket URLs
* Understanding automatic routing logic
* Implementing ticket claiming mechanisms

### Documentation-First Approach

**File:** `documentation-first.md`

Establishes the principle that corrections to agent mistakes are made by updating the
Knowledge Graph (via R1 agents) rather than editing output directly. Ensures the system
learns and maintains a single source of truth in `docs/`.

**Apply when:**

* Correcting agent behavior or patterns
* Updating standards or conventions
* Maintaining documentation as the authoritative reference

### Review Artifact Handling

**File:** `review-artifacts.md`

Defines standards for storing review tool outputs in `.review/` with UTC timestamp
naming (`<YYYYMMDDTHHMMSSZ>.review.coderabbit` or `.review.sonar`), recording follow-up
questions in `review-questions-<timestamp>.txt`, and excluding artifacts from scans
and VCS.

**Apply when:**

* Running code review tools (CodeRabbit, SonarQube)
* Storing review outputs for agent retrieval
* Managing review artifact lifecycle

### Orchestrator Invocation Examples

**File:** `orchestrator-invocation.md`

Shows internal orchestrator commands for invoking agents via `droid exec` with specific
flags and context files. Emphasizes that these commands are for internal orchestrator
use only and should NOT be executed by humans or agents directly.

**Apply when:**

* Understanding agent execution environment
* Debugging orchestrator agent invocation
* Implementing orchestrator service logic

### Information Migration Workflow

**File:** `information-migration.yml`

Defines the structured workflow for migrating and restructuring documentation while
ensuring no information is dropped or altered. Uses CSV-based tracking with DuckDB
queries, hash-based resolution verification, and four CLI commands: `start-migration`,
`query-comparisons`, `mark-resolved`, and `validate-migration`.

**Apply when:**

* Restructuring or splitting YAML documentation files
* Migrating content between original and split documentation patterns
* Validating that migrations preserve all information
* Tracking and resolving intentional differences during migrations
* Querying comparison results to identify unresolved differences
