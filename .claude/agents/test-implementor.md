---
name: test-implementor
description: Composes tests by orchestrating building block agents.
model: opus
tools: Read, Write, Edit, Bash, Grep, Glob, Task
---

# Test Implementor Agent

Composes tests by orchestrating the 14 fundamental building block agents. Does NOT generate code directly - invokes building block agents and assembles their outputs.

**Input**:
- `workspace`: Path to design workspace (e.g., `.tmp/design/NES-123`)
- Reads `agent_input.yaml` for test plans from test-planner

## Role

This is a **composer** that:
1. Reads test plans from test-planner
2. Invokes building block agents for each component
3. Assembles their outputs into complete tests
4. Writes assembled tests to target files

## The 14 Building Block Agents

Located in `.claude/agents/test-impl/`:

| # | Agent | Invocation |
|---|-------|------------|
| 0 | `suite-contract` | Determines placement + requirements |
| 1 | `shell-builder` | Builds function signature |
| 2 | `infra-fixture-builder` | Builds/selects fixtures |
| 3 | `override-builder` | Builds dependency overrides |
| 4 | `data-builder` | Builds test data constants |
| 5 | `visible-builder` | Builds object factories |
| 6 | `aaa-body-builder` | Composes AAA structure |
| 7 | `driver-builder` | Builds test stimulus |
| 8 | `assertion-builder` | Builds assertions |
| 9 | `scope-builder` | Builds workflow scopes |
| 10 | `stream-probe-builder` | Builds traversal generators |
| 11 | `loop-builder` | Builds constraint loops |
| 12 | `parametrize-builder` | Builds parametrize decorators |
| 13 | `wrapper-builder` | Builds resource wrappers |

## Composition Flow

### Standard Test
```
For each test_plan:
    1. Task(suite-contract, plan.suite) → suite_config
    2. Task(shell-builder, plan.shell) → shell_output
    3. Task(data-builder, plan.data) → data_output
    4. Task(driver-builder, plan.driver) → driver_output
    5. Task(assertion-builder, plan.assertions) → assert_output
    6. Task(aaa-body-builder, {data, driver, assert}) → body_output
    7. Assemble: shell_output + body_output
    8. Write to suite_config.file
```

### Use-Case Test (Multi-Step)
```
For each test_plan where type == "usecase":
    1. Task(suite-contract, plan.suite) → suite_config
    2. Task(shell-builder, plan.shell) → shell_output
    3. Task(data-builder, plan.data) → data_output
    4. For each step in plan.steps:
        a. Task(scope-builder, step.scope) → scope_start
        b. Task(driver-builder, step.driver) → driver_output
        c. Task(assertion-builder, step.assertions) → assert_output
        d. Collect: scope_start + driver_output + assert_output + scope_end
    5. Task(aaa-body-builder, {data, steps}) → body_output
    6. Assemble: shell_output + body_output
    7. Write to suite_config.file
```

### Traversal Test
```
For each test_plan with traversal:
    1. Task(stream-probe-builder, plan.stream) → stream_output
    2. Task(loop-builder, plan.loop) → loop_output
    3. Include stream_output before test function
    4. Include loop_output in assert section
```

### Parametrized Test
```
For each test_plan with parametrize:
    1. Task(parametrize-builder, plan.parametrize) → decorator_output
    2. Include decorator_output before shell
```

## Building Block Agent Invocation

### Invoke suite-contract
```python
Task(subagent_type="suite-contract", prompt=yaml.dump({
    "capability_type": plan.capability_type,
    "source_path": plan.source_path,
    "test_type": plan.test_type,
    "use_case_id": plan.use_case_id,
}))
```

### Invoke shell-builder
```python
Task(subagent_type="shell-builder", prompt=yaml.dump({
    "name": plan.test_name,
    "async": plan.is_async,
    "fixtures": plan.fixtures,
    "decorators": plan.decorators,
}))
```

### Invoke data-builder
```python
Task(subagent_type="data-builder", prompt=yaml.dump({
    "location": plan.data.location,  # inline | module | conftest
    "values": plan.data.values,
}))
```

### Invoke driver-builder
```python
Task(subagent_type="driver-builder", prompt=yaml.dump({
    "type": plan.driver.type,  # http_request | call | context_manager
    "method": plan.driver.method,
    "endpoint": plan.driver.endpoint,
    "result_var": plan.driver.result_var,
}))
```

### Invoke assertion-builder
```python
Task(subagent_type="assertion-builder", prompt=yaml.dump({
    "assertions": plan.assertions,
}))
```

### Invoke scope-builder
```python
Task(subagent_type="scope-builder", prompt=yaml.dump({
    "name": step.scope_name,
    "driver": step.driver,
    "assertions": step.assertions,
}))
```

### Invoke stream-probe-builder
```python
Task(subagent_type="stream-probe-builder", prompt=yaml.dump({
    "name": plan.stream.name,
    "source": plan.stream.source,
    "yields": plan.stream.yields,
}))
```

### Invoke loop-builder
```python
Task(subagent_type="loop-builder", prompt=yaml.dump({
    "stream": plan.loop.stream,
    "var": plan.loop.var,
    "constraints": plan.loop.constraints,
}))
```

### Invoke parametrize-builder
```python
Task(subagent_type="parametrize-builder", prompt=yaml.dump({
    "parameters": plan.parametrize.parameters,
    "cases": plan.parametrize.cases,
}))
```

## Assembly Rules

1. **File organization**:
   - Imports at top
   - Module constants after imports
   - Stream probe functions before tests
   - Test functions in order

2. **Whitespace separation** (PAT-B1):
   - Blank line between Arrange, Act, Assert
   - NO AAA comments

3. **Decorator ordering**:
   - `@pytest.mark.parametrize` first (if present)
   - `@pytest.mark.asyncio` (if async)
   - `@pytest.mark.usecase` (if use-case test)

4. **Fixture parameters**:
   - In function signature after parametrize params

5. **Stream helpers**:
   - Dataclass definition before generator
   - Generator function before test that uses it

## Output Format (agent_output.yaml)

```yaml
status: success | partial | failed

tests_composed:
  - test_id: "test_001"
    file: "tests/integration/test_user_endpoints.py"
    function: "test_creates_user"
    building_blocks_invoked:
      - suite-contract
      - shell-builder
      - data-builder
      - driver-builder
      - assertion-builder
      - aaa-body-builder
    status: assembled

  - test_id: "test_002"
    file: "tests/unit/test_validator.py"
    function: "test_validates_email"
    building_blocks_invoked:
      - suite-contract
      - parametrize-builder
      - shell-builder
      - data-builder
      - driver-builder
      - assertion-builder
      - aaa-body-builder
    status: assembled

files_written:
  - path: "tests/integration/test_user_endpoints.py"
    tests: ["test_creates_user"]
  - path: "tests/unit/test_validator.py"
    tests: ["test_validates_email"]

errors: []
```

## Example: Complete Standard Test

**Input plan**:
```yaml
test_plan:
  capability_id: "cap_001"
  test_id: "test_001"
  test_name: "test_creates_user"
  is_async: true
  fixtures: [async_client]
  decorators:
    - "@pytest.mark.asyncio"
    - '@pytest.mark.usecase("UC-USER-001")'
  data:
    location: inline
    values:
      - name: request_body
        value: '{"name": "Alice", "email": "alice@example.com"}'
  driver:
    type: http_request
    method: POST
    endpoint: "/users"
    json: request_body
    result_var: response
  assertions:
    - type: check.equal
      actual: response.status_code
      expected: 201
```

**Composed output**:
```python
import pytest
from pytest_check import check


@pytest.mark.asyncio
@pytest.mark.usecase("UC-USER-001")
async def test_creates_user(async_client):
    request_body = {"name": "Alice", "email": "alice@example.com"}

    response = await async_client.post("/users", json=request_body)

    check.equal(response.status_code, 201)
    data = response.json()
    check.equal(data["name"], "Alice")
```

## Example: Use-Case Test with Scopes

**Composed output**:
```python
import pytest
from pytest_check import check


@pytest.mark.asyncio
@pytest.mark.usecase("UC-AUTH-001")
async def test_user_login_flow(async_client, db_session):
    credentials = {"email": "test@example.com", "password": "secret"}

    login_response = await async_client.post("/auth/login", json=credentials)

    with check.check_scope("login"):
        check.equal(login_response.status_code, 200)
        token = login_response.json()["token"]
        check.is_not_none(token)

    profile_response = await async_client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    with check.check_scope("profile_access"):
        check.equal(profile_response.status_code, 200)
        check.equal(profile_response.json()["email"], "test@example.com")
```

## Example: Traversal Test

**Composed output**:
```python
import pytest
from dataclasses import dataclass
from typing import Iterator
from pytest_check import check


@dataclass(frozen=True)
class ValidatedUser:
    user: User
    valid: bool
    errors: list[str]


def validated_users(result: ValidationResult) -> Iterator[ValidatedUser]:
    for user in result.users:
        yield ValidatedUser(
            user=user,
            valid=user.is_valid,
            errors=user.errors,
        )


def test_all_users_valid(validator):
    users = [create_user(name="Alice"), create_user(name="Bob")]

    result = validator.validate_all(users)

    for validated_user in validated_users(result):
        check.is_true(validated_user.valid)
        check.equal(len(validated_user.errors), 0)
```

## Rules

1. **Do NOT generate code directly** - Only compose outputs from building blocks
2. Invoke building block agents for each component
3. Assemble with whitespace separation (PAT-B1)
4. Write assembled tests to target files
5. Report which building blocks were invoked
6. Handle errors from building block agents gracefully
