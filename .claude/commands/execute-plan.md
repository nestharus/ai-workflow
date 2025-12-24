---
description: Execute implementation design with test-first parallel layer-by-layer code generation
argument-hint: "<ticket-id>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Execute Implementation Plan

Execute the design for ticket `$ARGUMENTS` using test-first, parallel layer-by-layer code generation.

**Prerequisites**: Run `/create-plan $ARGUMENTS` first.

**Test-First Flow**: Tests are generated BEFORE code. Each capability gets one test. Tests should fail initially, then pass after code generation.

## Step 1: Initialize

```bash
uv run codegen init .tmp/design/$ARGUMENTS
```

Returns JSON: `{ "ok": true, "workspace": "...", "ticket_id": "...", "total_units": N }`

## Step 2: Execute State Machine Loop

```bash
while true; do
    action=$(uv run codegen next .tmp/design/$ARGUMENTS)
    action_type=$(echo "$action" | jq -r '.action')

    case "$action_type" in
        "complete") break ;;
        "error") echo "Error: $(echo "$action" | jq -r '.message')"; exit 1 ;;

        "setup_worktree")
            ticket_id=$(echo "$action" | jq -r '.ticket_id')
            uv run pr setup-worktree "$ticket_id" > .tmp/design/$ARGUMENTS/agent_output.yaml
            ;;

        "call_test_implementor")
            # Compose tests from test plans (plans created in /create-plan):
            # Uses 14 building block agents in .claude/agents/test-impl/
            Task(subagent_type="test-implementor", prompt="workspace: .tmp/design/$ARGUMENTS")
            ;;

        "run_tests")
            # Run tests - verify fail (before impl) or pass (after impl)
            worktree=$(echo "$action" | jq -r '.worktree_path')
            layer=$(echo "$action" | jq -r '.layer // "all"')
            cd "$worktree" && uv run pytest --tb=short > .tmp/design/$ARGUMENTS/test_output.txt 2>&1 || true
            ;;

        "call_impl_agent")
            # Execute units at current layer (grouped by file for parallelism)
            Task(subagent_type="impl-executor", prompt="workspace: .tmp/design/$ARGUMENTS")
            ;;

        # === Debug Loop (when layer tests fail) ===
        "create_debug_worktree")
            # Create isolated worktree for debugging
            worktree=$(echo "$action" | jq -r '.worktree_path')
            layer=$(echo "$action" | jq -r '.layer')
            uv run pr create-debug-worktree "$worktree" "$layer" > .tmp/design/$ARGUMENTS/agent_output.yaml
            ;;

        "call_debug_fixer")
            # Fix failing tests (may make ad-hoc fixes that violate building blocks)
            # Captures what was changed so we can refactor the solution
            Task(subagent_type="debug-fixer", prompt="workspace: .tmp/design/$ARGUMENTS")
            ;;

        "call_solution_refactorer")
            # Refactor debug fix into building block patterns
            # Takes ad-hoc fix and restructures to follow patterns
            Task(subagent_type="solution-refactorer", prompt="workspace: .tmp/design/$ARGUMENTS")
            ;;

        "replan_layer")
            # Replan affected capabilities at current layer
            # Updates test plans after debug fix is refactored
            Task(subagent_type="test-planner", prompt="workspace: .tmp/design/$ARGUMENTS mode=replan")
            ;;

        "replan_parent_layers")
            # Bigger refactoring after layer complete
            # Updates parent layers if debug fixes had cascading effects
            Task(subagent_type="parent-replanner", prompt="workspace: .tmp/design/$ARGUMENTS")
            ;;
        # === End Debug Loop ===

        "call_lint_fixer")
            worktree=$(echo "$action" | jq -r '.worktree_path')
            Task(subagent_type="lint-fixer", prompt="--worktree $worktree --changed-only")
            ;;

        "commit_and_push")
            worktree=$(echo "$action" | jq -r '.worktree_path')
            message=$(echo "$action" | jq -r '.message')
            uv run pr commit-push --worktree "$worktree" --set-upstream --message "$message"
            ;;

        "create_pr")
            worktree=$(echo "$action" | jq -r '.worktree_path')
            # Create PR, capture URL
            cd "$worktree" && gh pr create --base main --title "$ARGUMENTS: <TITLE>" --body "..."
            ;;
    esac

    uv run codegen process .tmp/design/$ARGUMENTS
done
```

## Step 3: Output

```bash
uv run codegen status .tmp/design/$ARGUMENTS
```

Get commit references:
```bash
cd <worktree_path>
git rev-parse HEAD                    # current_branch_commit
git rev-parse origin/main             # pr_target_branch_commit
```

Print:
```
================================================================================
IMPLEMENTATION COMPLETE - CODE REVIEW REQUESTED
================================================================================
Ticket: $ARGUMENTS - <TITLE>
Linear: <LINEAR_TICKET_URL>
PR: <PR_URL>
Worktree: <worktree_path>

References:
  current_branch_commit: <SHA>
  pr_target_branch_commit: <SHA>

Execution Summary:
  Layers executed: <N>
  Total units: <count>
  Successful: <count>
  Failed: <count>

Test-First Summary:
  Capabilities: <count>
  Test plans: <count>
  Tests generated: <count>
  Tests passing: <count>/<count>

Plan Distribution:
  CREATE: <count> (new code written)
  PATCH: <count> (existing code modified)
  REGENERATE: <count> (code rewritten)
  DELETE: <count> (code removed)

Layer Breakdown:
  Layer N: <count> atomics (impl-extractor: X, impl-validator: Y, ...)
  Layer N-1: <count> compositions
  ...
  Layer 0: 1 root

================================================================================
LINEAR COMMENTS REFERENCE
================================================================================

The implementation was generated from these Linear comments:

1. "Architecture Design"
   - PURPOSE: Human-readable overview with Mermaid diagrams
   - USE FOR: Understanding high-level structure of changes
   - FETCH: uv run linear get-comment $ARGUMENTS --title "Architecture Design"

2. "Implementation Design"
   - PURPOSE: Machine-readable unit tree with detailed plans
   - USE FOR: Verifying code matches each unit's plan
   - FETCH: uv run linear get-comment $ARGUMENTS --title "Implementation Design"
   - CONTAINS:
     * Unit hierarchy (root → components → atomics)
     * Pattern assignments (Walker, Extractor, Mapper, etc.)
     * Plan details (target file, changes, specifications)

================================================================================
CODE REVIEW INSTRUCTIONS
================================================================================

View the PR diff:
  cd <worktree_path> && git diff origin/main...HEAD

Fetch the design that was implemented:
  uv run linear get-comment $ARGUMENTS --title "Implementation Design"

VERIFY EACH UNIT:
1. Locate the unit in "Implementation Design"
2. Find the corresponding code change in the PR
3. Verify:
   - Pattern is correctly applied (Walker yields, Filter predicates, etc.)
   - Plan changes were implemented (for PATCH)
   - Specification was followed (for CREATE/REGENERATE)
   - Code was removed cleanly (for DELETE)

PATTERN SEMANTICS TO CHECK:
  Walker     - yields elements, doesn't collect
  Visitor    - accepts callback, applies to each
  Filter     - returns predicate result, streams
  Collector  - accumulates into collection
  Extractor  - gets single value from source
  Mutator    - sets single value on target
  Builder    - constructs from parts
  Mapper     - transforms format
  Guard      - early return on condition
  Router     - dispatches based on input
  Validator  - returns validation result

COMPOSITION CHECK:
  - Parent units correctly wire up children
  - Imports/exports match between units
  - No orphaned code from refactoring

CAPABILITY VERIFICATION:
  - Each capability has exactly one test
  - Tests verify the expected behavior (not implementation details)
  - Component tests are mapped to use-cases
  - All tests pass after code generation

TEST-FIRST CHECK:
  - Tests were generated BEFORE implementation code
  - Tests composed from 14 building blocks by test-implementor
  - Building blocks used correctly:
    * suite-contract determined correct test file + suite type
    * shell-builder has correct decorators (@pytest.mark.asyncio for async)
    * data-builder follows PAT-E (inline/module/conftest adjacency)
    * aaa-body-builder uses whitespace separation (NO AAA comments - PAT-B1)
    * scope-builder used for multi-step use-case tests
    * stream-probe-builder + loop-builder for traversal tests
  - No production code added without corresponding test
  - One test per capability (component tests mapped by use-cases)

YOU ARE REVIEWING CODE IMPLEMENTATION AGAINST THE DESIGN.
Compare: "Implementation Design" (what should exist) ↔ PR diff (what was built)
Verify: All capabilities have passing tests

Cleanup after merge: git worktree remove <worktree_path>
================================================================================
```

## Notes

- **Test-First**: Tests generated before code; tests should fail, then pass
- **Decomposer/Composer Pattern**:
  - `test-planner` (decomposer) - Breaks capabilities into building block specifications
  - `test-implementor` (composer) - Invokes building block agents and assembles outputs
- **14 Test Building Blocks** (in `.claude/agents/test-impl/`):

  | # | Agent | Purpose |
  |---|-------|---------|
  | 0 | `suite-contract` | Test placement + suite requirements |
  | 1 | `shell-builder` | Function signature + decorators |
  | 2 | `infra-fixture-builder` | Infrastructure fixtures (client, async_client) |
  | 3 | `override-builder` | Dependency overrides (test doubles) |
  | 4 | `data-builder` | PAT-E compliant data constants |
  | 5 | `visible-builder` | Object factories with explicit values |
  | 6 | `aaa-body-builder` | Implicit AAA body (whitespace-separated, NO comments) |
  | 7 | `driver-builder` | Test stimulus (HTTP/call) |
  | 8 | `assertion-builder` | check.*/assert statements |
  | 9 | `scope-builder` | Workflow scopes for use-case tests |
  | 10 | `stream-probe-builder` | Typed traversal generators |
  | 11 | `loop-builder` | Approved constraint loops |
  | 12 | `parametrize-builder` | @pytest.mark.parametrize decorators |
  | 13 | `wrapper-builder` | Resource lifetime wrappers |

- **Building Block Selection by Test Type**:
  - Standard: 0→1→4→7→8→6
  - Use-case (multi-step): 0→1→4→(9→7→8)+→6
  - Traversal: 0→1→4→7→10→11→8→6
  - Parametrized: 0→12→1→4→7→8→6
- **PAT Rules Enforced**:
  - PAT-B1: No AAA comments (whitespace separation only)
  - PAT-B7: No assertions before Act (except use-case multi-step)
  - PAT-E1: Data adjacent (inline, module, or folder conftest)
- Layers execute bottom-up (deepest atomics first)
- Same-file units run sequentially (avoid conflicts)
- Different-file units run in parallel (throughput)
- State machine handles all scheduling logic
- One test per capability (component tests mapped by use-cases)
