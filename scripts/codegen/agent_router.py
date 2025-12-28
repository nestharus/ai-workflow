"""Pattern to agent routing for code generation.

Maps the 20 atomic patterns to their impl-* agents.
Maps the 14 test building blocks to their test-impl/* agents.
"""

from __future__ import annotations

# 20 atomic patterns -> impl-* agents
ATOMIC_AGENTS: dict[str, str] = {
    # Stream/Iterable processing (6)
    "Walker": "impl-walker",
    "Visitor": "impl-visitor",
    "Filter": "impl-filter",
    "Collector": "impl-collector",
    "Splitter": "impl-splitter",
    "Zip": "impl-zip",
    # Data access (4)
    "Extractor": "impl-extractor",
    "Mutator": "impl-mutator",
    "Getter": "impl-getter",
    "Setter": "impl-setter",
    # Data model (2)
    "Entity": "impl-entity",
    "Projection": "impl-projection",
    # Construction (3)
    "Builder": "impl-builder",
    "Mapper": "impl-mapper",
    "Reducer": "impl-reducer",
    # Control flow (4)
    "Guard": "impl-guard",
    "Router": "impl-router",
    "Classifier": "impl-classifier",
    "Orchestrator": "impl-orchestrator",
    # Validation (1)
    "Validator": "impl-validator",
}

# 14 test building blocks -> test-impl/* agents
# Located in .claude/agents/test-impl/
TEST_BUILDING_BLOCKS: dict[str, str] = {
    # Block 0: Suite Contract - test placement + suite requirements
    "suite-contract": "suite-contract",
    # Block 1: Test Case Shell - function signature + decorators
    "shell-builder": "shell-builder",
    # Block 2: Repo Infra Fixture - infrastructure fixtures
    "infra-fixture-builder": "infra-fixture-builder",
    # Block 3: Dependency Override - test doubles via overrides
    "override-builder": "override-builder",
    # Block 4: Local Test Data - PAT-E compliant data constants
    "data-builder": "data-builder",
    # Block 5: Visible Builder - factories with explicit values
    "visible-builder": "visible-builder",
    # Block 6: Implicit AAA Body - composing the sections
    "aaa-body-builder": "aaa-body-builder",
    # Block 7: Driver - test stimulus (HTTP/call)
    "driver-builder": "driver-builder",
    # Block 8: Assertion Primitive - check.*/assert statements
    "assertion-builder": "assertion-builder",
    # Block 9: Workflow Scope - multi-step use-case checkpoints
    "scope-builder": "scope-builder",
    # Block 10: Typed Stream Probe - traversal generators
    "stream-probe-builder": "stream-probe-builder",
    # Block 11: Constraint Loop - approved looping over streams
    "loop-builder": "loop-builder",
    # Block 12: Parametrized Scenario - @pytest.mark.parametrize
    "parametrize-builder": "parametrize-builder",
    # Block 13: Resource Lifetime - context managers/teardown
    "wrapper-builder": "wrapper-builder",
}


def get_agent_for_pattern(pattern: str) -> str:
    """Get the implementation agent for a pattern.

    Args:
        pattern: Pattern name (e.g., "Extractor", "Walker")

    Returns:
        Agent name (e.g., "impl-extractor", "impl-walker")
        Returns "composer" for non-atomic patterns.
    """
    return ATOMIC_AGENTS.get(pattern, "composer")


def is_atomic_pattern(pattern: str) -> bool:
    """Check if a pattern is atomic (has dedicated impl agent)."""
    return pattern in ATOMIC_AGENTS


def get_test_building_block_agent(block_name: str) -> str:
    """Get the test building block agent for a block name.

    Args:
        block_name: Building block name (e.g., "suite-contract", "shell-builder")

    Returns:
        Agent name (same as block name for test-impl agents)

    Raises:
        ValueError: If block name is not recognized
    """
    if block_name not in TEST_BUILDING_BLOCKS:
        msg = f"Unknown test building block: {block_name}"
        raise ValueError(msg)
    return TEST_BUILDING_BLOCKS[block_name]


def is_test_building_block(block_name: str) -> bool:
    """Check if a block name is a valid test building block."""
    return block_name in TEST_BUILDING_BLOCKS


def get_test_building_block_order() -> list[str]:
    """Get the canonical order of test building blocks.

    Returns the 14 building blocks in the order they should typically be invoked:

    1. suite-contract: Test placement and suite requirements
    2. parametrize-builder: @pytest.mark.parametrize decorators
    3. shell-builder: Function signature and decorators
    4. infra-fixture-builder: Infrastructure fixtures (repos, databases)
    5. override-builder: Test doubles via dependency overrides
    6. data-builder: PAT-E compliant local test data constants
    7. visible-builder: Factories with explicit values
    8. wrapper-builder: Resource lifetime (context managers, teardown)
    9. driver-builder: Test stimulus (HTTP calls, function invocations)
    10. scope-builder: Workflow scope with multi-step use-case checkpoints
    11. stream-probe-builder: Typed stream probe traversal generators
    12. loop-builder: Constraint loop for approved looping over streams
    13. assertion-builder: check.*/assert statements
    14. aaa-body-builder: Implicit AAA body composing the sections
    """
    return [
        "suite-contract",
        "parametrize-builder",
        "shell-builder",
        "infra-fixture-builder",
        "override-builder",
        "data-builder",
        "visible-builder",
        "wrapper-builder",
        "driver-builder",
        "scope-builder",
        "stream-probe-builder",
        "loop-builder",
        "assertion-builder",
        "aaa-body-builder",
    ]
