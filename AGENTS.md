# AI Agent Entry Point

<coding_guidelines>

Welcome to the **Developing With AI 2.0** system—an automated, orchestrator-based AI
workflow system where agents act as specialized roles within workflows coordinated by
a central orchestrator service.

## What Is This Project?

This project implements an automated AI workflow system using a 5-role skeleton across
four domains: Product, UX, UI, and Technical. The system uses a FastAPI orchestrator
service to route messages to workflows and a separate webhook receiver service to handle
GitHub integration. The goal is to facilitate high-quality software development through
structured, automated collaboration.

For detailed information, see `docs/architecture/project-overview.md`.

## Documentation Modules

This repository organizes documentation into focused modules. Consult the relevant module
for detailed guidance on specific tasks.

| Module | Path | Description |
|--------|------|-------------|
| **Usage** | `docs/usage/` | Using the application |
| **Development** | `docs/development/` | Writing code, docstrings, FastAPI |
| **Testing** | `docs/testing/` | Writing and running test code |
| **Architecture** | `docs/architecture/` | Folder structure, services, endpoints |
| **Processes** | `docs/processes/` | Git releases, code reviews, protocols |

## Code Coverage

Test coverage is enforced separately for each test tier using `uv run test-coverage`.

### Test Tiers

| Tier | Test Path | Coverage Type | Target |
|------|-----------|---------------|--------|
| **unit** | `tests/unit/` | 80% line / 70% branch | All `app/` functions |
| **component** | `tests/component/` | 100% use-case | `app/services/` only |
| **integration** | `tests/integration/` | 100% use-case | `app/api/` endpoints |
| **scripts** | `scripts/tests/` | 80% line / 70% branch | `scripts/` only |

### Coverage Rules

* **Per-function thresholds**: Line 80%, branch 70% per function (unit/scripts tiers)
* **Overall thresholds**: Line 80%, branch 70% overall (unit/scripts tiers)
* **Class fields excluded**: Pydantic model type annotations are excluded from coverage
* **Service layer**: Component tests only validate functions within `app/services/`
* **Use-case coverage**: Component/integration require 100% use-case coverage
* **Private functions**: Unit tests validate all functions; component/integration/scripts skip private

### Validation Commands

```bash
# Run all test tiers (test credentials auto-configured by pytest)
uv run test-coverage

# Run specific tier
uv run test-coverage --tier unit
uv run test-coverage --tier integration

# Custom thresholds (override defaults)
uv run test-coverage --min-line 90 --min-branch 85

# Report only (no validation)
uv run test-coverage --no-validate

# Legacy pytest-cov commands still work
uv run pytest --cov
uv run pytest --cov --cov-report=html
```

**Output**: Test coverage data is written to `.coverage/coverage.db` SQLite database,
which contains per-function coverage statistics, use-case coverage, test results, and
detailed missing line/branch information. Analysis tools (`coverage-summary`,
`coverage-files`, `coverage-file`, `coverage-functions`) read from this database.

## Generating OpenAPI Schema

Generates the OpenAPI 3.1 schema JSON file from the FastAPI application code.

* **Usage**: `uv run app.api.generate`
* **Output**: Saves to `openapi/openapi.json`
* **Note**: This script must be run before `lint` or security scans to ensure the schema
  is up-to-date
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`

## Running Python Tools

Do not invoke `python` or `python3` directly outside `uv run`. Always run Python
modules and entry points via `uv run` (e.g., `uv run python -m ...`).

### Correct Usage

```bash
# Run a module
uv run python -m scripts.everycode.generate_code_config

# Run with arguments
uv run python -m scripts.prd.chunker input.md --output-dir ./chunks

# Run entry points defined in pyproject.toml
uv run code-config
uv run test-coverage
```

### Incorrect Usage

```bash
# WRONG - do not use python directly
python -m scripts.everycode.generate_code_config
python3 -m scripts.prd.chunker input.md

# WRONG - do not use virtual environment python
.venv/bin/python -m scripts.something
```

### Why uv run?

* **Dependency management**: `uv run` ensures the correct virtual environment and
  dependencies are available
* **Consistency**: All developers and CI use the same execution method
* **Entry points**: Scripts defined in `pyproject.toml` are only accessible via `uv run`

### Writing Documentation

When documenting Python commands in markdown files, toml files, or README files, always
use the `uv run python -m` pattern:

```markdown
# In documentation
Run the chunker:
\`\`\`bash
uv run python -m scripts.prd.chunker input.md --output-dir ./chunks
\`\`\`
```

## Adding Dependencies

When adding a new dependency to `pyproject.toml`, follow this workflow:

### Step 1: Fetch Latest Version from PyPI

Fetch the latest version from PyPI using either of the methods below. Both are valid:
use **curl + jq** for readability, or **Python stdlib** when external tools are unavailable.

**Environment requirements**:

* **Network access**: Requires outbound HTTPS connection to `pypi.org` (may fail behind
  corporate proxies or firewalls)
* **TLS/SSL**: Requires a working Python SSL/TLS stack (certificate verification enabled)
* **API stability**: Relies on the PyPI JSON API (`/pypi/<package>/json` endpoint)

**Troubleshooting**:

* **Proxy issues**: Set `HTTP_PROXY` and `HTTPS_PROXY` environment variables if behind a proxy
* **TLS errors**: Verify Python's SSL certificates are up-to-date
  (`uv run python -c "import ssl; print(ssl.OPENSSL_VERSION)"`)
* **Connectivity check**: Test network access with
  `uv run python -c "import urllib.request; urllib.request.urlopen('https://pypi.org')"`
* **Alternative tools**: Use `curl https://pypi.org/pypi/<package-name>/json | jq -r '.info.version'` or `wget` if urllib fails

**Option 1: curl + jq** (recommended for readability):

```bash
curl -s https://pypi.org/pypi/<package-name>/json | jq -r '.info.version'
```

**Option 2: Python one-liner** (works without external tools):

```bash
uv run python -c "import urllib.request, json; print(json.loads(urllib.request.urlopen('https://pypi.org/pypi/<package-name>/json').read())['info']['version'])"
```

Both options fetch the PyPI JSON API and extract the `info.version` field.

**Note**: If you do not have `jq` installed and prefer not to use the long Python one-liner,
save this script to a file (e.g., `scripts/get_pypi_version.py`) and run it with
`uv run python scripts/get_pypi_version.py <package-name>`:

```python
#!/usr/bin/env python3
import json
import sys
import urllib.request

package = sys.argv[1] if len(sys.argv) > 1 else input("Package name: ")
url = f"https://pypi.org/pypi/{package}/json"
data = json.loads(urllib.request.urlopen(url).read())
print(data["info"]["version"])
```

**Manual fallback**: If the command fails, verify the package name spelling and try one of:

* Visit `https://pypi.org/project/<package-name>/` directly in a browser
* Use `pip index versions <package-name>` to list available versions
* Use `uv pip show <package-name>` if the package is already installed locally

**Verify the version before proceeding**: The extracted version must match the semantic version
pattern `MAJOR.MINOR.PATCH` (e.g., `2025.11.3`, `1.5.2`). Reject values like `"latest"`, empty
strings, or malformed versions.

Then continue with Step 2.

### Step 2: Add with Upper Bound

Manually add the dependency to the appropriate section in `pyproject.toml` with version
constraints matching the project's pattern: `>=MAJOR.MINOR.PATCH,<MAJOR.NEXT_MINOR.0`
(bound to next minor version).

**Where to add the dependency** (based on the group from the table below):

| Group | pyproject.toml Location |
|-------|-------------------------|
| main | `[project]` section under `dependencies = [...]` |
| test | `[dependency-groups]` section under `test = [...]` |
| dev | `[dependency-groups]` section under `dev = [...]` |
| knowledge | `[dependency-groups]` section under `knowledge = [...]` |

Example for a package with version `2025.11.3` added to the knowledge group:

```toml
# In [dependency-groups] section
knowledge = [
    { include-group = "test" },
    ...existing dependencies...
    "regex>=2025.11.3,<2025.12.0",  # <-- Add here
]
```

Example for a package with version `1.5.2` added to main dependencies:

```toml
# In [project] section
dependencies = [
    ...existing dependencies...
    "somepackage>=1.5.2,<1.6.0",  # <-- Add here
]
```

### Step 3: Sync and Verify

```bash
uv sync --group <group-name>
```

For example, to sync the knowledge group: `uv sync --group knowledge`

### Dependency Groups

| Group | Purpose | pyproject.toml Location |
|-------|---------|------------------------|
| main | Runtime dependencies | `[project]` section, `dependencies = [...]` |
| test | pytest, test utilities | `[dependency-groups]` section, `test = [...]` |
| dev | linters, formatters, type checkers | `[dependency-groups]` section, `dev = [...]` |
| knowledge | ML/NLP for scripts/knowledge/ | `[dependency-groups]` section, `knowledge = [...]` |

Always use the 3-step workflow above to add dependencies.

**Rules**:

* **Always fetch latest from PyPI**: Use the Python urllib command to get the current version, never guess
* **Always include upper bound**: Prevent unexpected major version upgrades
* **Choose the correct group**: Match the dependency to its purpose (see table above), then
  sync with that group (e.g., `uv sync --group knowledge`)
* **Always use 3-step workflow**: PyPI fetch → manual pyproject.toml edit → `uv sync --group <group-name>`
* **Check compatibility**: Ensure the new dependency doesn't conflict with existing ones

## Every Code Agent Orchestration

This project uses **Every Code** (`@just-every/code`) for AI agent orchestration.

For writing agents, commands, or changing agent-related settings, refer to `.code/README.md`
for complete documentation on:

* Regenerating `config.toml` from source files
* Writing agent definitions in `agents.toml`
* Writing subagent commands with instruction file references
* Configuring global settings
* Model selection guide

## Plan Execution Guidelines

When executing tasks from implementation plans (files in `docs/plans/`), agents must
follow these strict rules to ensure complete and consistent implementation.

### No Deferred Stubs Without Plan Authorization

**CRITICAL**: Do NOT create placeholder stubs, TODO comments, or deferred implementations
unless the plan explicitly indicates the item is planned for a later task.

* **Before creating a stub**: Check if the functionality is specified in the current task
* **If specified in current task**: Implement it fully, even if it requires more effort
* **If specified in a later task**: Note that in a comment with the task reference
* **If implementation is blocked**: Document what is blocking and what is needed to proceed

Bad example (unauthorized stub):

```python
def resolve_entity(entity_mention: str) -> str:
    # TODO: Integrate with variant_resolver
    return entity_mention  # Placeholder
```

Good example (plan-authorized deferral):

```python
def resolve_entity(entity_mention: str) -> str:
    # Entity resolution rules are in Task 9 (fact_redesign_plan.md lines 172-189)
    # This task (Task 6) uses pass-through until Task 9 is implemented
    return entity_mention
```

### Task Decomposition for Complex Plans

For plans with many requirements, the primary agent should:

1. **Save the plan to `.tmp/`**: Split the plan into numbered task files
2. **Delegate to sub-agents**: Use the `Task` tool with `subagent_type="general-purpose"`
   to delegate individual tasks
3. **Review each completion**: After each sub-agent returns, verify the task was fully
   implemented before proceeding to the next task
4. **Track incomplete items**: If a sub-agent reports blockers, record them and either
   resolve them before continuing or escalate to the user

Example workflow:

```text
1. Read docs/plans/my_feature_plan.md
2. Write task files:
   - .tmp/my_feature/task_1.md
   - .tmp/my_feature/task_2.md
   - .tmp/my_feature/task_3.md
3. Delegate Task 1 to sub-agent
4. Review sub-agent output for Task 1
5. Delegate Task 2 to sub-agent
6. ...
```

### Reporting Incomplete Implementation

If implementation cannot be completed, you MUST report:

* What was completed
* What could NOT be completed
* WHY it could not be completed (missing dependency, unclear requirement, etc.)
* What is needed to complete it

Do NOT silently skip requirements or create stubs without explicit acknowledgment.

## No Backwards Compatibility

**CRITICAL**: This project has a strict NO BACKWARDS COMPATIBILITY policy. Always prioritize
optimal implementations over legacy support.

### Forbidden Patterns

Do NOT use any of these backwards-compatibility patterns:

* **Backwards-compatibility shims**: Adapter layers, deprecated aliases, or compatibility wrappers
* **Deprecated aliases**: `old_name = new_name  # For backwards compatibility`
* **Version checks**: `if version < 2: use_old_method() else: use_new_method()`
* **Dual support**: Accepting both old and new formats/arguments
* **Compatibility layers**: Adapter classes or wrapper functions for old interfaces
* **Re-exports**: Keeping old import paths working via re-exports
* **Unused parameters**: `def func(new_param, old_param=None):  # old_param ignored`
* **Legacy pattern support**: Maintaining old code that depends on deprecated patterns

### When Updating Code

1. **Find all usages**: Use grep/search to find every reference to the code being changed
2. **Update all usages**: Modify every call site to use the new pattern
3. **Delete old code**: Remove the old implementation entirely—do not keep it alongside new code
4. **Run tests**: Ensure all tests pass with the new implementation
5. **No fallbacks**: Do not add fallback logic "just in case"

Always choose the best solution for current requirements, not the one that preserves old patterns.
This policy ensures the codebase stays clean, maintainable, and free of technical debt
from accumulated compatibility layers.

## External Resources

When stuck on implementation details, library usage, or unfamiliar patterns, use the
Firecrawl MCP tools to search the web for documentation and examples:

* **Search**: `mcp__firecrawl__firecrawl_search` - Search for documentation, Stack Overflow
  answers, or best practices
* **Scrape**: `mcp__firecrawl__firecrawl_scrape` - Fetch and read specific documentation pages

Examples of when to use Firecrawl:

* Unfamiliar with pyfakefs test patterns? Search for "pyfakefs modules_to_reload pytest"
* Need FastAPI middleware examples? Search for "FastAPI middleware authentication 2025"
* Library API unclear? Scrape the official documentation page

## Git Commit Signing

All commits are automatically GPG-signed using the configured signing key. This is required
by the repository's branch protection rules.

**Current configuration** (already set globally):

```bash
git config --global user.signingkey 2AAAEEBD97F32BFE
git config --global commit.gpgsign true
```

**Key location**: `~/.gnupg/` (RSA 4096-bit, no passphrase)

**GitHub verification**: The public key must be added to GitHub at
[https://github.com/settings/keys](https://github.com/settings/keys) for signatures to show as "Verified".

To export the public key:

```bash
gpg --armor --export contact@nestharus.com
```

## Git Commit Authorship

When creating git commits, agents must NOT add themselves as authors or co-authors:

* **No Co-Authored-By**: Do not add `Co-Authored-By: Claude <noreply@anthropic.com>` or
  similar lines
* **No Generated-By footers**: Do not add `🤖 Generated with [Claude Code]` or similar
  attribution footers
* **Use configured identity only**: All commits must use only the git username and email
  configured in the repository (from `git config user.name` and `git config user.email`)

The human user is the author of all commits. The agent is a tool assisting the user, not
a co-author.

**Why this matters**: Each unique author in a GitHub repository costs $30/month for a
seat. Adding Claude as a co-author would waste money on a seat for an AI that doesn't
need repository access.

## Git Branch Naming for Linear Integration

When creating branches for Linear tickets, the ticket ID casing must be preserved exactly:

* **Correct**: `NES-47-rest-to-mcp-bridge` (ticket ID `NES-47` keeps uppercase)
* **Wrong**: `nes-47-rest-to-mcp-bridge` (lowercase breaks automatic linking)

Linear automatically links branches and PRs to tickets when the ticket ID appears in the
branch name with correct casing. Using lowercase will break this automatic linking and
require manual attachment.

**Branch format**: `<TICKET-ID>-<description>` where:

* `<TICKET-ID>` preserves exact casing from Linear (e.g., `NES-47`, `PROJ-123`)
* `<description>` is lowercase with hyphens, derived from ticket title
* Total length should not exceed 50 characters

</coding_guidelines>
