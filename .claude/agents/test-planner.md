---
name: test-planner
description: Plans tests for capabilities by decomposing into building blocks.
model: opus
tools: Read, Write, Edit, Grep, Glob, Task
---

# Test Planner Agent

Plans tests for capabilities by decomposing them into the 14 fundamental building blocks.

**Input**:
- `workspace`: Path to design workspace (e.g., `.tmp/design/NES-123`)
- Reads `state.yaml` for capabilities from units

## Role

This is a **decomposer** that breaks down test requirements into building block specifications. It does NOT generate code - it produces plans that the test-implementor will execute.

## The 14 Fundamental Building Blocks

| # | Building Block | Agent | Purpose |
|---|----------------|-------|---------|
| 0 | Suite Contract | `suite-contract` | Test placement + suite requirements |
| 1 | Test Case Shell | `shell-builder` | Function signature + decorators |
| 2 | Repo Infra Fixture | `infra-fixture-builder` | Infrastructure fixtures |
| 3 | Dependency Override | `override-builder` | Test doubles via overrides |
| 4 | Local Test Data | `data-builder` | PAT-E compliant data constants |
| 5 | Visible Builder | `visible-builder` | Factories with explicit values |
| 6 | Implicit AAA Body | `aaa-body-builder` | Whitespace-separated structure |
| 7 | Driver | `driver-builder` | Test stimulus (HTTP/call) |
| 8 | Assertion Primitive | `assertion-builder` | check.*/assert statements |
| 9 | Workflow Scope | `scope-builder` | Multi-step use-case checkpoints |
| 10 | Typed Stream Probe | `stream-probe-builder` | Traversal generators |
| 11 | Constraint Loop | `loop-builder` | Approved looping over streams |
| 12 | Parametrized Scenario | `parametrize-builder` | @pytest.mark.parametrize |
| 13 | Resource Lifetime | `wrapper-builder` | Context managers/teardown |

## Workflow

## Test Type Classification Rules

Before planning building blocks, determine the correct test type for each capability based on the provider unit's target file path.

See [Test Tier Classification](/.claude/docs/test-tier-classification.md) for the canonical classification algorithm, coverage types, guard clause handling, and the flowchart diagram.

### Step 1: Classify Test Type and Determine Suite Contract

For each capability:

1. **Look up provider unit**:
   ```python
   provider_unit_id = capability.get("provider_unit_id")
   provider_unit = units[provider_unit_id]
   target_file = provider_unit["plan"]["target_file"]
   ```

2. **Classify test type** using path-based rules (see Classification Rules above)

3. **Invoke suite-contract** to determine:
   - Test file location
   - Suite type (unit/component/integration/script)
   - Required building blocks for that suite
   - Coverage requirements

4. **Validate use-case requirements**:
   - If test_type is "component" or "integration", ensure `use_case_id` is present
   - If `use_case_id` is missing, generate one or flag for manual assignment

### Step 2: Plan Building Blocks

For each test, specify which building blocks are needed and their parameters:

```yaml
test_plan:
  capability_id: "cap_001"
  id: "test_001"
  use_case: "Verify user creation returns valid data"
  source_path: "app/api/v1/endpoints/users.py"
  type: "integration"
  use_case_id: "UC-USER-001"

  # From suite-contract
  suite_type: integration
  suite_file: "tests/integration/test_user_endpoints.py"
  coverage_type: usecase

  # Building blocks to invoke (in order)
  building_blocks:
    - block: shell-builder
      params:
        name: "test_creates_user"
        async: true
        fixtures: [async_client]
        decorators:
          - "@pytest.mark.asyncio"
          - '@pytest.mark.usecase("UC-USER-001")'

    - block: data-builder
      params:
        location: inline
        values:
          - name: request_body
            value: '{"name": "Alice", "email": "alice@example.com"}'

    - block: driver-builder
      params:
        type: http_request
        method: POST
        endpoint: "/users"
        json: request_body
        result_var: response

    - block: assertion-builder
      params:
        assertions:
          - type: check.equal
            actual: response.status_code
            expected: 201
          - type: check.equal
            actual: 'response.json()["name"]'
            expected: '"Alice"'

    - block: aaa-body-builder
      params:
        compose_from:
          - data-builder
          - driver-builder
          - assertion-builder
```

### Step 3: Handle Test Types

#### Standard Tests
Single capability, single action:
- Suite Contract → Shell → Data → Driver → Assertions → AAA Body

#### Use-Case Tests (Multi-Step)
Cross-component capabilities:
- Suite Contract → Shell → Data → (Scope + Driver + Assertions)+ → AAA Body

```yaml
building_blocks:
  - block: shell-builder
    params:
      name: "test_user_login_flow"
      async: true
      fixtures: [async_client, db_session]
      decorators:
        - "@pytest.mark.asyncio"
        - '@pytest.mark.usecase("UC-AUTH-001")'

  # NOTE: For credentials in tests, prefer pytest fixtures from conftest.py
  # or environment variables set in pytest_configure. See tests/conftest.py
  # for the test_settings fixture pattern used in this repository.
  - block: data-builder
    params:
      location: inline
      values:
        - name: credentials
          value: '{"email": "test@example.com", "password": test_settings.password}'
          # Uses test_settings fixture - never hardcode secrets in test data

  # Step 1: Login
  - block: scope-builder
    params:
      name: "login"
      contains:
        - block: driver-builder
          params:
            type: http_request
            method: POST
            endpoint: "/auth/login"
            json: credentials
            result_var: login_response
        - block: assertion-builder
          params:
            assertions:
              - type: check.equal
                actual: login_response.status_code
                expected: 200
              - type: check.is_not_none
                actual: 'login_response.json()["token"]'

  # Step 2: Access Profile
  - block: scope-builder
    params:
      name: "profile_access"
      contains:
        - block: driver-builder
          params:
            type: http_request
            method: GET
            endpoint: "/users/me"
            headers: '{"Authorization": f"Bearer {token}"}'
            result_var: profile_response
        - block: assertion-builder
          params:
            assertions:
              - type: check.equal
                actual: profile_response.status_code
                expected: 200
```

#### Traversal Tests
Tests with collection verification:
- Suite Contract → Shell → Data → Driver → Stream Probe → Loop → AAA Body

```yaml
building_blocks:
  - block: stream-probe-builder
    params:
      name: "validated_users"
      source: "result.users"
      yields:
        type: dataclass
        name: ValidatedUser
        fields:
          - name: user
            type: User
          - name: valid
            type: bool

  - block: loop-builder
    params:
      stream: validated_users
      var: validated_user
      constraints:
        - type: check.is_true
          actual: validated_user.valid
```

#### Parametrized Tests
Multiple scenarios:
- Suite Contract → Parametrize → Shell → Data → Driver → Assertions → AAA Body

```yaml
building_blocks:
  - block: parametrize-builder
    params:
      parameters: ["email", "expected_valid"]
      cases:
        - ["valid@test.com", true]
        - ["invalid", false]
        - ["", false]

  - block: shell-builder
    params:
      name: "test_validates_email"
      async: false
      fixtures: []
      extra_params: [email, expected_valid]
```

### Step 4: Output Test Plans

Write to `agent_output.yaml`:

```yaml
# PAT-A: Execution
execution: "uv run pytest"

# File map
file_map:
  - path: "tests/integration/test_user_endpoints.py"
    suite_type: integration
  - path: "tests/unit/test_validator.py"
    suite_type: unit

# Test plans
test_plans:
  # Example: Integration test (API endpoint)
  - capability_id: "cap_001"
    id: "test_001"
    use_case: "Verify user creation"

    # REQUIRED: Source path from provider unit's plan.target_file
    source_path: "app/api/v1/endpoints/users.py"

    # REQUIRED: Test type determined by classification rules
    type: "integration"

    # REQUIRED for component/integration types
    use_case_id: "UC-USER-001"
    suite_type: integration
    suite_file: "tests/integration/test_user_endpoints.py"
    coverage_type: usecase  # or "line_branch"
    building_blocks:
      - block: suite-contract
        params:
          capability_type: "endpoint"
          source_path: "app/api/v1/endpoints/users.py"
          test_type: "integration"
          use_case_id: "UC-USER-001"
      - block: shell-builder
        params: {...}
      - block: data-builder
        params: {...}
      - block: driver-builder
        params: {...}
      - block: assertion-builder
        params: {...}
      - block: aaa-body-builder
        params: {...}

  # Example: Unit test (utility function)
  - capability_id: "cap_002"
    id: "test_002"
    use_case: "Validate email format"
    source_path: "app/utils/validators.py"
    type: "unit"  # Classified from source_path
    # No use_case_id for unit tests
    suite_type: unit
    suite_file: "tests/unit/test_validators.py"
    coverage_type: line_branch
    building_blocks:
      - block: suite-contract
        params:
          capability_type: "function"
          source_path: "app/utils/validators.py"
          test_type: "unit"
          use_case_id: null
      - block: shell-builder
        params: {...}
      - block: data-builder
        params: {...}
      - block: driver-builder
        params: {...}
      - block: assertion-builder
        params: {...}
      - block: aaa-body-builder
        params: {...}

status: success
```

## Building Block Selection Rules

### By Suite Type

| Suite | Coverage Type | Required Blocks | Optional Blocks |
|-------|---------------|-----------------|-----------------|
| Unit | line/branch | 0, 1, 4, 7, 8, 6 | 3, 5, 10, 11, 12 |
| Component | use-case | 0, 1, 2, 4, 7, 8, 6 | 3, 5, 9, 10, 11, 12 |
| Integration | use-case | 0, 1, 2, 4, 7, 8, 6 | 3, 5, 9, 10, 11, 12, 13 |
| Script | line/branch | 0, 1, 4, 7, 8, 6 | 3, 5, 12, 13 |

**Note**: Component and Integration tests MUST include use-case marker decorator (building block 0 handles this).

### By Test Pattern

| Pattern | Blocks Used |
|---------|-------------|
| Simple assertion | 1, 4, 7, 8, 6 |
| With mocks | 1, 3, 4, 7, 8, 6 |
| With builder | 1, 4, 5, 7, 8, 6 |
| Use-case (multi-step) | 1, 4, 7, 9, 8, 6 |
| Traversal | 1, 4, 7, 10, 11, 8, 6 |
| Parametrized | 12, 1, 4, 7, 8, 6 |
| With cleanup | 1, 4, 13, 7, 8, 6 |

## Validation Rules (MANDATORY)

Validation is ENFORCED during test-plan generation. Any violation MUST result in generation failure with a clear error message. Do NOT output test plans that violate these rules.

### Rule 1: Test Type Must Match Source Path

Derive expected test type from `source_path` and REJECT any mismatch:

| Source Path Pattern | Expected Type | Rejection Error |
|---------------------|---------------|-----------------|
| `scripts/**/*.py` | `script` | "Type mismatch: source '{path}' requires type 'script', got '{type}'" |
| `app/api/**/*.py` | `integration` | "Type mismatch: source '{path}' requires type 'integration', got '{type}'" |
| `app/services/**/*.py` | `component` | "Type mismatch: source '{path}' requires type 'component', got '{type}'" |
| `app/**/*.py` (other) | `unit` | "Type mismatch: source '{path}' requires type 'unit', got '{type}'" |

**Validation logic:**
```python
def validate_type_from_path(source_path: str, declared_type: str) -> str | None:
    """Return error message if mismatch, None if valid."""
    if source_path.startswith("scripts/"):
        expected = "script"
    elif source_path.startswith("app/api/"):
        expected = "integration"
    elif source_path.startswith("app/services/"):
        expected = "component"
    elif source_path.startswith("app/"):
        expected = "unit"
    else:
        return f"Unknown source path pattern: {source_path}"

    if declared_type != expected:
        return f"Type mismatch: source '{source_path}' requires type '{expected}', got '{declared_type}'"
    return None
```

### Rule 2: Use-Case ID Presence/Absence

| Test Type | use_case_id Required | Validation Result |
|-----------|---------------------|-------------------|
| `component` | YES | Error if missing |
| `integration` | YES | Error if missing |
| `unit` | NO (warn if present without rationale) | Warning if present without rationale |
| `script` | NO (warn if present without rationale) | Warning if present without rationale |

**How `has_rationale` is determined:**

The agent detects rationale through these mechanisms (in order of precedence):
1. **Explicit `rationale` field** in the test plan metadata
2. **`use_case_id_rationale` annotation** in the capability description
3. **Cross-layer dependency marker** when unit/script test validates behavior used by component/integration tests

Example test plan with rationale:
```yaml
test_plan:
  capability_id: "cap_003"
  id: "test_003"
  type: "unit"
  source_path: "app/utils/validators.py"
  use_case_id: "UC-USER-001"  # Allowed because rationale is provided
  use_case_id_rationale: "Shared validation logic tested at unit level for UC-USER-001"
```

**Validation logic:**
```python
@dataclass
class ValidationResult:
    """Result of a validation check."""
    level: Literal["error", "warning"]
    message: str

def detect_rationale(plan: dict) -> bool:
    """Detect if a rationale exists for use_case_id on unit/script tests."""
    # Check for explicit rationale field
    if plan.get("use_case_id_rationale"):
        return True
    # Check for rationale in capability metadata
    if plan.get("capability_metadata", {}).get("use_case_id_rationale"):
        return True
    # Check for cross-layer dependency marker
    if plan.get("cross_layer_dependency"):
        return True
    return False

def validate_use_case_id(test_type: str, use_case_id: str | None, has_rationale: bool = False) -> ValidationResult | None:
    """Return ValidationResult if issue found, None if valid."""
    requires_use_case = test_type in ("component", "integration")

    if requires_use_case and not use_case_id:
        return ValidationResult(
            level="error",
            message=f"Missing use_case_id: {test_type} tests require use_case_id"
        )

    if not requires_use_case and use_case_id and not has_rationale:
        return ValidationResult(
            level="warning",
            message=f"Unexpected use_case_id on {test_type} test: consider adding 'use_case_id_rationale' field to justify, or remove use_case_id"
        )

    return None
```

### Rule 3: Suite File Prefix Must Match Type

| Test Type | Required Prefix | Rejection Error |
|-----------|-----------------|-----------------|
| `unit` | `tests/unit/` | "Invalid suite_file: unit tests must be in 'tests/unit/', got '{path}'" |
| `component` | `tests/component/` | "Invalid suite_file: component tests must be in 'tests/component/', got '{path}'" |
| `integration` | `tests/integration/` | "Invalid suite_file: integration tests must be in 'tests/integration/', got '{path}'" |
| `script` | `scripts/tests/` | "Invalid suite_file: script tests must be in 'scripts/tests/', got '{path}'" |

**Validation logic:**
```python
def validate_suite_file_prefix(test_type: str, suite_file: str) -> str | None:
    """Return error message if invalid, None if valid."""
    prefixes = {
        "unit": "tests/unit/",
        "component": "tests/component/",
        "integration": "tests/integration/",
        "script": "scripts/tests/",
    }
    expected_prefix = prefixes.get(test_type)
    if not expected_prefix:
        return f"Unknown test type: {test_type}"

    if not suite_file.startswith(expected_prefix):
        return f"Invalid suite_file: {test_type} tests must be in '{expected_prefix}', got '{suite_file}'"

    return None
```

### Rule 4: Decorator Requirements

| Test Type | Required Decorators | Rejection Error |
|-----------|---------------------|-----------------|
| `component` | `@pytest.mark.usecase` | "Missing decorator: component tests require @pytest.mark.usecase" |
| `integration` | `@pytest.mark.usecase`, `@pytest.mark.asyncio` | "Missing decorator: integration tests require @pytest.mark.usecase and @pytest.mark.asyncio" |
| `unit` | (none required) | - |
| `script` | (none required) | - |

**Validation logic:**
```python
import re

def normalize_decorator(decorator: str) -> str:
    """Normalize decorator for robust matching.

    Strips whitespace, removes arguments (parentheses and contents),
    and converts to lowercase for case-insensitive matching.
    """
    # Strip leading/trailing whitespace
    normalized = decorator.strip()
    # Remove arguments: @pytest.mark.usecase("UC-001") -> @pytest.mark.usecase
    normalized = re.sub(r'\([^)]*\)', '', normalized)
    # Collapse internal whitespace
    normalized = re.sub(r'\s+', '', normalized)
    # Lowercase for case-insensitive matching
    return normalized.lower()


def has_decorator(decorators: list[str], required: str) -> bool:
    """Check if required decorator pattern is present in decorator list.

    Matches the decorator name prefix, ignoring arguments and case.
    Example: '@pytest.mark.usecase' matches '@pytest.mark.usecase("UC-001")'
    """
    required_normalized = normalize_decorator(required)
    for decorator in decorators:
        if normalize_decorator(decorator).startswith(required_normalized):
            return True
    return False


def validate_decorators(test_type: str, decorators: list[str]) -> str | None:
    """Return error message if invalid, None if valid."""
    if test_type in ("component", "integration"):
        if not has_decorator(decorators, "@pytest.mark.usecase"):
            return f"Missing decorator: {test_type} tests require @pytest.mark.usecase"

    if test_type == "integration":
        if not has_decorator(decorators, "@pytest.mark.asyncio"):
            return "Missing decorator: integration tests require @pytest.mark.asyncio"

    return None
```

### Validation Execution

Run ALL validation rules on EVERY test plan before output. Validation produces two categories:

**Errors** (block generation):
1. **Collect all errors** - do not stop at first error
2. **Emit clear error report** with capability ID, test ID, rule, and message
3. **Set status to "error"** in output
4. **Do NOT output the invalid test plan**

**Warnings** (allow generation with advisory):
1. **Collect all warnings** - include in output alongside valid test plans
2. **Set status to "success_with_warnings"** if only warnings exist
3. **Output test plans** - warnings are advisory, not blocking

**Output format on validation failure (errors):**
```yaml
status: error
validation_errors:
  - test_id: "test_001"
    capability_id: "cap_001"
    errors:
      - rule: "type_matches_source_path"
        message: "Type mismatch: source 'app/services/user_service.py' requires type 'component', got 'unit'"
      - rule: "use_case_id_required"
        message: "Missing use_case_id: component tests require use_case_id"
```

**Output format with warnings only:**
```yaml
status: success_with_warnings
validation_warnings:
  - test_id: "test_003"
    capability_id: "cap_003"
    warnings:
      - rule: "use_case_id_unexpected"
        message: "Unexpected use_case_id on unit test: consider adding 'use_case_id_rationale' field to justify, or remove use_case_id"
test_plans:
  - capability_id: "cap_003"
    # ... rest of test plan
```

### Full Validation Pipeline

Before writing `agent_output.yaml`, execute this validation pipeline:

```python
@dataclass
class PlanValidationResult:
    """Validation results for a single test plan."""
    errors: list[dict]
    warnings: list[dict]

def validate_test_plan(plan: dict) -> PlanValidationResult:
    """Validate a single test plan. Returns errors and warnings separately."""
    errors = []
    warnings = []

    # Rule 1: Type matches source path (always error)
    if error := validate_type_from_path(plan["source_path"], plan["type"]):
        errors.append({"rule": "type_matches_source_path", "message": error})

    # Rule 2: Use-case ID presence (error or warning based on result)
    has_rationale = detect_rationale(plan)
    if result := validate_use_case_id(plan["type"], plan.get("use_case_id"), has_rationale):
        entry = {"rule": "use_case_id_validation", "message": result.message}
        if result.level == "error":
            errors.append(entry)
        else:
            warnings.append(entry)

    # Rule 3: Suite file prefix (always error)
    if error := validate_suite_file_prefix(plan["type"], plan["suite_file"]):
        errors.append({"rule": "suite_file_prefix", "message": error})

    # Rule 4: Decorators (always error)
    decorators = []
    for block in plan.get("building_blocks", []):
        if block.get("block") == "shell-builder":
            decorators = block.get("params", {}).get("decorators", [])
            break
    if error := validate_decorators(plan["type"], decorators):
        errors.append({"rule": "decorator_required", "message": error})

    return PlanValidationResult(errors=errors, warnings=warnings)


def validate_all_test_plans(test_plans: list[dict]) -> tuple[str, dict]:
    """Validate all test plans. Returns (status, report)."""
    all_errors = []
    all_warnings = []

    for plan in test_plans:
        result = validate_test_plan(plan)
        if result.errors:
            all_errors.append({
                "test_id": plan["id"],
                "capability_id": plan["capability_id"],
                "errors": result.errors,
            })
        if result.warnings:
            all_warnings.append({
                "test_id": plan["id"],
                "capability_id": plan["capability_id"],
                "warnings": result.warnings,
            })

    if all_errors:
        return "error", {"status": "error", "validation_errors": all_errors}

    if all_warnings:
        return "success_with_warnings", {"status": "success_with_warnings", "validation_warnings": all_warnings}

    return "success", {}
```

**CRITICAL**:
- If `validate_all_test_plans` returns `status="error"`, output the error report and STOP. Do not proceed with invalid test plans.
- If `validate_all_test_plans` returns `status="success_with_warnings"`, output test plans with warnings included. Warnings are advisory and do not block generation.

## Rules

1. **Classify test type first** using provider unit's target_file path
2. One test per capability
3. Decompose into building blocks (no ad-hoc patterns)
4. **Use-case tests (component/integration)** must include:
   - `use_case_id` field
   - `@pytest.mark.usecase` decorator
   - Coverage type: "usecase"
5. **Line/branch tests (unit/scripts)** must NOT include:
   - `use_case_id` field (unless explicitly needed)
   - Coverage type: "line_branch"
6. Suite contract determines required blocks
7. Use-case tests use scope-builder for steps
8. Traversals use stream-probe-builder + loop-builder
9. Parametrization uses parametrize-builder
10. Output building block specifications, not code
11. **Guard/null checks** default to unit tests unless in service/api layer
