# Plan

## Overview

Define a file-scoped input/output contract for the `test-strategy` agent that enables Python orchestration to pass specific target files and receive structured output the test-planner can consume programmatically.

## Current State (Problems)

1. **Unstructured Output**: The current `test-strategy` agent outputs free-form markdown under `STRATEGY:`, which requires the test-planner to parse prose rather than structured data.

2. **Implicit File Handling**: Python passes files as a formatted markdown list (`## Target Files\n- file1\n- file2`) but there's no explicit schema defining valid file formats or required metadata.

3. **No Test Type Specification**: The output doesn't explicitly map files to test types (use-case vs line/branch coverage). The planner must infer this from prose descriptions.

4. **Missing Test-to-Source Mapping**: No structured mapping between source files and their corresponding test files/functions, making coverage tracking difficult.

5. **Review Mode Mismatch**: The review mode outputs `APPROVED`/`FEEDBACK`/`BLOCKED` but these aren't formally defined or parsed consistently.

## Target State

### Input Contract

Python passes a JSON-serializable structure:

```yaml
# Input Schema (sent as formatted prompt, but adhering to this structure)
input:
  mode: "generate" | "review" | "revise"
  target_files:
    - path: "app/services/user_service.py"
      change_type: "NEW" | "MODIFY" | "DELETE" | "RENAME"  # optional
      functions_changed: ["create_user", "delete_user"]    # optional, for MODIFY
  context:
    analysis_description: "string"  # optional
    git_diff: "string"              # optional
    existing_tests:                 # optional
      - "tests/unit/test_user_service.py"
  # For review mode only:
  strategy_document: "string"       # original strategy being reviewed
  proposed_plan: "string"           # plan to review against strategy
  # For revise mode only:
  coverage_gaps:
    - function: "create_user"
      file: "app/services/user_service.py"
      line_coverage: 45.0
      branch_coverage: 30.0
```

### Output Contract

Agent outputs parseable structured data after the `STRATEGY:` marker:

```yaml
# Output Schema (STRATEGY mode)
output:
  summary: "Brief 2-3 sentence summary"
  tier_assignments:
    - file: "app/services/user_service.py"
      tier: "unit" | "component" | "integration" | "e2e"
      coverage_type: "line_branch" | "use_case"
      coverage_target: 80  # percentage for line_branch, count for use_case
      rationale: "Why this tier"
      functions:
        - name: "create_user"
          test_type: "line_branch"
          priority: "high" | "medium" | "low"
          notes: "Complex branching requires parametrized tests"
  testing_patterns:
    fixtures_required:
      - name: "user_factory"
        exists: true
        path: "tests/conftest.py"
      - name: "mock_email_service"
        exists: false
        creation_notes: "Mock SMTP client for email verification"
    mocking_strategies:
      - target: "app.infrastructure.email.EmailClient"
        approach: "dependency_injection"
        notes: "Inject mock via constructor"
    assertion_patterns:
      - pattern: "response_schema_validation"
        description: "Use pydantic model_validate"
  use_cases:
    new:
      - id: "UC-USER-001"
        endpoint: "/api/v1/users"
        method: "POST"
        description: "Create user succeeds"
        test_tier: "integration"
    existing_applicable:
      - id: "UC-AUTH-003"
        notes: "Existing auth flow covers token validation"
  edge_cases:
    - scenario: "Duplicate email registration"
      severity: "high"
      test_approach: "Expect 409 Conflict response"
    - scenario: "Empty username"
      severity: "medium"
      test_approach: "Expect 422 Validation error"
  test_file_mapping:
    - source: "app/services/user_service.py"
      tests:
        - path: "tests/unit/test_user_service.py"
          operation: "MODIFY"
          tier: "unit"
        - path: "tests/integration/test_user_endpoints.py"
          operation: "NEW"
          tier: "integration"
  guidance_for_planner:
    - "Use parametrized tests for validation edge cases"
    - "Mock EmailClient at service layer, not repository"
```

### Review Mode Output

```yaml
# Output Schema (review mode)
output:
  status: "APPROVED" | "FEEDBACK" | "BLOCKED"
  # If FEEDBACK:
  issues:
    - category: "missing_tier" | "wrong_coverage_type" | "missing_edge_case" | "pattern_mismatch"
      description: "Integration tests missing for user deletion"
      strategy_reference: "tier_assignments[0].functions[1]"
      severity: "high" | "medium" | "low"
  # If BLOCKED:
  reason: "Cannot review - strategy document is missing"
```

### Compatibility Requirements

1. **Backwards Compatible Prompt Format**: Python continues using `format_strategy_prompt()` but structures the prompt to match the input schema.

2. **Output Parsing**: Add `parse_strategy_output_structured()` that extracts YAML after `STRATEGY:` marker and validates against schema.

3. **Mode Detection**: Agent detects mode from prompt prefix (`Mode: review`, `Mode: revise`) or defaults to `generate`.

4. **Graceful Degradation**: If agent outputs unstructured text (due to model limitations), parser falls back to treating entire output as `summary` field.

## Additional Info

### Test Type Definitions

| Test Type | Coverage Metric | Target | Applies To |
|-----------|-----------------|--------|------------|
| `line_branch` | Per-function line and branch % | 80% | Unit, Component, Scripts |
| `use_case` | Use-case ID coverage | 100% | Integration, E2E |

### File Change Types

| Type | Description | Strategy Implication |
|------|-------------|---------------------|
| `NEW` | New file created | Full test coverage required |
| `MODIFY` | Existing file changed | Test additions/updates for changed functions |
| `DELETE` | File removed | Remove corresponding tests, check for broken refs |
| `RENAME` | File renamed | Update test imports, verify no logic changes |

### Tier Selection Criteria

- **Unit**: Pure functions, utilities, isolated logic
- **Component**: Service layer public APIs (functions in `app/services/`)
- **Integration**: API endpoints with mocked external deps
- **E2E**: Full stack scenarios requiring Docker/real services

## Tasks

### Task 1: Define JSON Schema Files

Create formal JSON schema definitions for input and output contracts:

- Create `docs/schemas/test-strategy-input.schema.json`
- Create `docs/schemas/test-strategy-output.schema.json`
- Create `docs/schemas/test-strategy-review.schema.json`
- Include examples in schema `$defs` or separate example files

### Task 2: Update test-strategy Agent Markdown

Modify `.tasks/agents/test-strategy.md`:

- Update `## Input` section with the new input schema structure
- Update `## Output Contract` to specify YAML structure after `STRATEGY:` marker
- Add `## Schema Reference` section pointing to schema files
- Update examples to show structured YAML output
- Ensure review/revise modes output structured data

### Task 3: Update Python Prompt Formatter

Modify `scripts/tasks/workflows/test_automation.py`:

- Update `format_strategy_prompt()` to generate prompts matching input schema
- Optionally include schema excerpt in prompt for agent reference
- Handle all three modes: generate, review, revise
- Pass `change_type` and `functions_changed` when available from git analysis

### Task 4: Add Structured Output Parser

Add to `scripts/tasks/workflows/test_automation.py`:

- Create `parse_strategy_output_structured()` function
- Extract YAML block after `STRATEGY:` marker
- Validate against schema (use `jsonschema` or `pydantic`)
- Implement graceful fallback for unstructured output
- Update `handle_strategy()` and `handle_strategy_update()` to use new parser

### Task 5: Update Test-Planner Input Handling

Modify `format_planning_prompt()` in `test_automation.py`:

- Accept structured strategy data instead of raw string
- Reference specific `tier_assignments` and `test_file_mapping` in prompt
- Pass `use_cases.new` list for use-case registry updates
- Include `guidance_for_planner` items as explicit instructions

### Task 6: Add Schema Validation Tests

Create `scripts/tests/tasks/workflows/test_strategy_schemas.py`:

- Test input schema validation with valid/invalid payloads
- Test output schema validation with agent-like outputs
- Test graceful fallback for unstructured output
- Test all three modes (generate, review, revise)

## Execution Instructions

For each task:

1. **Execute**: Use the general-purpose sub-agent to implement the task:
   ```
   Task(subagent_type="general-purpose", prompt="Implement Task N from .tasks/plans/test-strategy-contract.md. Read the plan file first, then implement the specific task requirements. Write tests as specified. Do not modify other tasks' code.")
   ```

2. **Review**: After ***EACH INDIVIDUAL*** sub-agent completes, review the changes against the task it implemented:
   - Verify all requirements are met using git to check what changes it made
   - Check that tests pass
   - Check that existing functionality is preserved
   - Note any deviations or issues

3. **Iterate**: If review finds issues, pass feedback to sub-agent:
   ```
   Task(subagent_type="general-purpose", prompt="Review feedback for Task N: [feedback]. Fix the issues identified. The plan is in .tasks/plans/test-strategy-contract.md.")
   ```

4. **Proceed**: Only move to next task when current task passes review

## Success Criteria

- [ ] JSON schemas exist and are valid JSON Schema Draft-07
- [ ] test-strategy agent markdown references schemas and shows YAML output format
- [ ] Python prompt formatters produce prompts matching input schema
- [ ] Structured output parser extracts and validates YAML from agent output
- [ ] Test-planner receives structured data from strategy output
- [ ] All existing test_automation tests continue to pass
- [ ] New schema validation tests pass with ≥80% coverage
- [ ] Lint passes (`uv run lint`)
