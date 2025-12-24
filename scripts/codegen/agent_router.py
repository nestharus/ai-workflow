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
    # Block 6: Implicit AAA Body - whitespace-separated structure
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

    Returns building blocks in the order they should typically be invoked:
    1. Suite contract (determines placement)
    2. Parametrize (if needed, decorator goes first)
    3. Shell (function signature)
    4. Data builders (arrange section)
    5. Driver (act section)
    6. Assertions (assert section)
    7. AAA body (composes the sections)
    """
    return [
        "suite-contract",      # 0 - First: determine placement
        "parametrize-builder", # 12 - If needed, decorator goes before shell
        "shell-builder",       # 1 - Function signature
        "infra-fixture-builder", # 2 - Infrastructure fixtures
        "override-builder",    # 3 - Dependency overrides
        "data-builder",        # 4 - Test data constants
        "visible-builder",     # 5 - Object factories
        "wrapper-builder",     # 13 - Resource wrappers
        "driver-builder",      # 7 - Test stimulus
        "scope-builder",       # 9 - Workflow scopes (use-case tests)
        "stream-probe-builder", # 10 - Traversal generators
        "loop-builder",        # 11 - Constraint loops
        "assertion-builder",   # 8 - Assertions
        "aaa-body-builder",    # 6 - Last: compose the body
    ]
