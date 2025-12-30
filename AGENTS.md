# AI Agent Entry Point

**CRITICAL: This is the only AGENTS.md file. Do not search for others. Follow ALL instructions
in this file exactly. These are mandatory rules, not suggestions.**

**If you do not know how to accomplish a task, check the "How To" list below for a relevant guide.**

**MANDATORY: The "How To" sections below link to documentation files. When you first need to
perform a task, read its linked file once. Do not read files for tasks you are not performing.
Do not re-read on repeat tasks.**

Application Documentation (app/ code) read `docs/architecture/project-overview.md`.

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

## How To Run And Understand Python Tests Correctly → [`docs/testing/python-tests.md`](docs/testing/python-tests.md)

## How To Generate OpenAPI Schema (app/) → [`docs/development/generate-openapi.md`](docs/development/generate-openapi.md)

## How To Execute Python Tools Correctly

Do not invoke `python` or `python3` directly outside `uv run`. Always run Python
modules and entry points via `uv run` (e.g., `uv run python -m ...`).

### How To Write Documentation Correctly

When documenting Python commands in markdown files, toml files, or README files, always
use the `uv run python -m` pattern:

## How To Add Python Dependencies Correctly → [`docs/development/adding-dependencies.md`](docs/development/adding-dependencies.md)

## How To Add Models Correctly → [`docs/development/adding-models.md`](docs/development/adding-models.md)

## How To Write Agents Correctly → [`docs/development/writing-agents.md`](docs/development/writing-agents.md)

## How To Execute Agents Correctly → [`docs/development/executing-agents.md`](docs/development/executing-agents.md)

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

## Git Branch Naming for Linear Integration

When creating branches for Linear tickets, the ticket ID casing must be preserved exactly:

* **Correct**: `NES-47-rest-to-mcp-bridge` (ticket ID `NES-47` keeps uppercase)
* **Wrong**: `nes-47-rest-to-mcp-bridge` (lowercase breaks automatic linking)

**Branch format**: `<TICKET-ID>-<description>` where:

* `<TICKET-ID>` preserves exact casing from Linear (e.g., `NES-47`, `PROJ-123`)
* `<description>` is lowercase with hyphens, derived from ticket title
* Total length must not exceed 50 characters
