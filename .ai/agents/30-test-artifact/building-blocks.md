Fundamental building blocks for this repo
0) Suite Contract

What you build: the “where and how” of tests (placement + runner guidance).

Artifacts

Test file location: tests/unit/…, tests/integration/…, tests/component/… etc

Test requirements per suite (requirements of integration tests; requirements of component tests; requirements of unit tests; ADDITIONAL requirements of use-case tests)

1) Test Case Shell

What you build: the top-level test function signature (sync or async) and its required decorators.

Syntactic signature

import pytest

@pytest.mark.asyncio
async def test_something(async_client):
...


Rules

Any async def test_* must have @pytest.mark.asyncio. PAT-C1

test-async-review

(Industry cross-check: “test method” and a linear success path are core xUnit patterns.
XUnit Patterns
)

2) Repo Infra Fixture

What you build: the injected infrastructure for tests (clients/app/settings), not data.

Artifacts

client, async_client, test_app, test_settings (repo-provided fixtures)

Optional infra fixtures in tests/fixtures/ (allowed)

Rules

Prefer test_app, client, async_client, test_settings; don’t recreate clients/apps. PAT-A3

test-repo-conventions-review

Prefer repo fixtures client / async_client; don’t create ad-hoc clients without need + cleanup. PAT-C3

test-async-review

Infra fixtures are OK; “magic data seeding” fixtures are not. R3

test-clarity-review

tests/fixtures/ is allowed for infra fixtures (and builders), not datasets. PAT-E6

test-data-policy-review

3) Dependency Override Harness

What you build: a controlled seam for swapping real dependencies with test doubles (fakes/stubs) via repo-approved overrides.

Syntactic signature (conceptual)

# override get_settings (or other deps) only when needed, per repo guidance


Rules

Overrides must follow repo guidance; override get_settings only when needed; fail if over-applied/misused. PAT-A4

test-repo-conventions-review

(External cross-check: “test double” is a standard building block when isolating dependencies.
martinfowler.com
+1
)

4) Local Test Data Constant

(Rename recommendation: your “Local Data Fixture” is correct as a block, but “fixture” in pytest usually means @pytest.fixture. This block is really local data.)

What you build: literals/constants that define inputs and expected values.

Implementation variants

Inline literal inside the test (preferred)

Module constant in the same test_*.py

Folder-local dataset in that folder’s conftest.py

Rules

Data must be adjacent: inline, module constant, or folder-local conftest.py. PAT-E1

test-data-policy-review

No importing datasets from shared modules across folders; no top-level dataset modules. PAT-E1

test-data-policy-review

No subset selection (no slicing/filtering/next()/branch-to-skip on case type). PAT-E2

test-data-policy-review

Folder dataset must be all-or-nothing: every test in folder consumes all cases (typically via parametrization). PAT-E3

test-data-policy-review

No mutation of shared data (in-place edits, append/remove). PAT-E4

test-data-policy-review

Clarity also enforces adjacency + the all-or-nothing folder dataset constraint. R1

test-clarity-review

5) Visible Builder

What you build: a factory that creates fresh objects/payloads while keeping important values explicit at the call site.

Syntactic signature

def build_user(**overrides):
defaults = {"active": True, "role": "user"}
return {**defaults, **overrides}


Rules

Builders are allowed only if meaningful values are explicit in the test; fail if critical defaults are hidden. PAT-E5

test-data-policy-review

and R2

test-clarity-review

Prefer builders that return fresh instances (helps immutability). PAT-E4

test-data-policy-review

Helpers must not contain assertion logic or return pass/fail. PAT-B5

test-structure-review

Builders may live in tests/fixtures/ (allowed). PAT-E6

test-data-policy-review

(Pytest also documents “factory as fixture” as an idiom; your builder block fits that shape.
pytest
)

6) Implicit AAA Body

What you build: the shape of the test body (Arrange / Act / Assert) via whitespace and ordering.

Syntactic signature (compliant: no AAA comments)

async def test_feature(async_client):
payload = {"x": 1}

    response = await async_client.post("/endpoint", json=payload)

    check.equal(response.status_code, 200)


Rules

AAA must be implicit; fail if # Arrange/# Act/# Assert comments exist. PAT-B1

test-structure-review

No branching (if/elif/else) in test bodies (narrow exception mentioned in rule text). PAT-B2

test-structure-review

No assertions before Act (Arrange assertions fail). PAT-B7

test-structure-review

Setup assertions are discouraged/warned. T5

test-traversal-contract-review

Use-case tests can have multi-step flows with intermediate assertions (but still no branching/raw traversal). PAT-B7 + PAT-B8

test-structure-review

Important correction to your block #3: your example showed AAA comments and an “Arrange hard assert allowed” variant. AAA comments are explicitly forbidden (B1)

test-structure-review

, and assertions in Arrange are explicitly forbidden (B7)

test-structure-review

(with only the use-case exception).

7) Driver

(Rename recommendation: “Async Driver” is a specialization of a more general “Driver”.)

What you build: the stimulus — the thing that exercises the system (HTTP call, service call, function call).

Syntactic signature

response = await async_client.post("/api/v1/resource", json=payload)


Rules

Async producers must be awaited; fail if coroutines are passed around un-awaited. PAT-C2

test-async-review

Prefer repo fixtures client / async_client; avoid ad-hoc clients without cleanup. PAT-C3

test-async-review

Avoid hang risks: use proper teardown/context managers; flag unbounded waits and long sleeps. PAT-C4

test-async-review

8) Assertion Primitive

What you build: the actual verification statements in the test body (not hidden in helpers).

Artifacts

check.* assertions (esp. inside loops)

Plain asserts only where allowed by repo rules (not in Arrange; use-case exception between steps)

Rules

Loop assertions are expected to be check.* (as part of approved loop pattern). PAT-B4

test-structure-review

Assertions must remain in test bodies; helpers must not assert/return pass-fail. PAT-B5

test-structure-review

No assertions before Act, except use-case multi-step flows. PAT-B7/PAT-B8

test-structure-review

9) Workflow Scope

What you build: an explicit checkpoint for multi-step use-case tests (step labeling + intermediate verification).

Syntactic signature

with check.scope("Step 1: Registration"):
await drive_register(...)
check.is_true(...)


Rules

Use-case tests may have multi-step Act sequences with assertions between steps. PAT-B8

test-structure-review

The exception allowing intermediate assertions is explicitly tied to use-case workflow tests. PAT-B7

test-structure-review

Still no branching and no raw traversal even in use-cases. PAT-B8

test-structure-review

10) Typed Stream Probe

What you build: a traversal helper that converts complex/nested structures into a readable stream of typed items.

Syntactic signature

from dataclasses import dataclass
from typing import Iterator

@dataclass(frozen=True)
class InvoiceItem:
id: str
total: int

def invoices(response: dict) -> Iterator[InvoiceItem]:
for raw in response.get("items", []):
yield InvoiceItem(id=raw["id"], total=raw["amount"])


Rules

Tests must not do raw nested traversal; traversal must be extracted into generators/pure functions. PAT-B3

test-structure-review

Stream name must describe the extracted thing (avoid generic items_stream). T1

test-traversal-contract-review

Stream contract must be explicit: typed yield (dataclass(frozen=True) or NamedTuple) OR dict with docstring + clear keys. T2

test-traversal-contract-review

Helpers must not contain assertions. PAT-B5

test-structure-review

11) Constraint Loop

What you build: the only approved looping form in tests: constrain each extracted item from a probe.

Syntactic signature (compliant)

for invoice in invoices(response):
invoice_id = invoice.id
total = invoice.total

    check.is_not_none(invoice_id)
    check.greater(total, 0)


Rules

Loops are allowed only in approved patterns:

for item in <stream>(...)

no branching in loop

extract labeled fields into locals, then check.*

no filtering/subsetting in loop. PAT-B4

test-structure-review

No branching in test bodies. PAT-B2

test-structure-review

Loop variable must match the contract (no generic item). T3

test-traversal-contract-review

Each loop must clearly communicate “what is constrained.” T4

test-traversal-contract-review

12) Parametrized Scenario Table

What you build: runner-managed scenario variation.

Syntactic signature

import pytest

@pytest.mark.parametrize("input_val, expected", [
(1, "low"),
(10, "high"),
])
async def test_limit(input_val, expected, async_client):
...


Rules

Prefer @pytest.mark.parametrize over manual iteration of scenarios. PAT-B6

test-structure-review

If using shared datasets, don’t slice/filter/select subsets — split datasets instead. PAT-E2

test-data-policy-review

Folder-level datasets must be consumed by every test (typically via parametrization). PAT-E3

test-data-policy-review

(Pytest’s own docs treat parametrization as a core mechanism.
pytest
)

13) Resource Lifetime Wrapper

What you build: explicit teardown boundaries to prevent leaks and hangs (context managers / fixture teardown).

Artifacts

async with … / with … boundaries

fixtures with teardown/finalizers

bounded waits (no long sleeps)

Rules

Require context managers / proper teardown for async resources; flag unbounded waits and long sleeps. PAT-C4

test-async-review

Avoid ad-hoc clients without cleanup. PAT-C3