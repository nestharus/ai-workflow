"""Action types for planner state machine.

The orchestrator reads next_action.yaml to determine what to do.
Python writes this file; orchestrator reads it.
"""

from __future__ import annotations

from enum import Enum


class ActionType(Enum):
    """Actions that Python returns to the orchestrator via next_action.yaml."""

    # === LLM Agent Invocations (Create/Update Plan) ===
    CALL_DECOMPOSER = "call_decomposer"
    CALL_LAYER_REVIEWER = "call_layer_reviewer"
    CALL_TREE_REVIEWER = "call_tree_reviewer"
    CALL_DESIGN_REFACTORER = "call_design_refactorer"
    CALL_COMMENT_APPLIER = "call_comment_applier"
    CALL_DIAGRAM_GENERATOR = "call_diagram_generator"
    CALL_DESIGN_FORMATTER = "call_design_formatter"
    GENERATE_DOCS = "generate_docs"

    # === LLM Agent Invocations (Refactor Plan) ===
    CALL_SKELETON_ANALYZER = "call_skeleton_analyzer"
    CALL_COMPONENT_ANALYZER = "call_component_analyzer"
    CALL_INTEGRATION_MAPPER = "call_integration_mapper"
    CALL_REFACTOR_PLANNER = "call_refactor_planner"

    # === Test Agent Invocations (Test-First Flow) ===
    # Tests have their own building blocks (practices) from .ai/agents/30-test-artifact/
    CALL_TEST_PLANNER = "call_test_planner"  # Plans tests from capabilities
    CALL_TEST_IMPLEMENTOR = "call_test_implementor"  # Composes tests from building blocks
    RUN_TESTS = "run_tests"

    # === Debug-Replan Invocations ===
    # When tests fail, debug and replan at current layer
    CREATE_DEBUG_WORKTREE = "create_debug_worktree"  # Create isolated debug environment
    CALL_DEBUG_FIXER = "call_debug_fixer"  # Fix failing tests (may violate blocks)
    CALL_SOLUTION_REFACTORER = "call_solution_refactorer"  # Refactor fix into building blocks
    REPLAN_LAYER = "replan_layer"  # Replan current layer after debug
    REPLAN_PARENT_LAYERS = "replan_parent_layers"  # Bigger refactoring after layer complete

    # === Code Generation Agent Invocations ===
    CALL_IMPL_AGENT = "call_impl_agent"
    CALL_COMPOSER = "call_composer"
    CALL_DELETER = "call_deleter"
    CALL_LINT_FIXER = "call_lint_fixer"

    # === Control Flow ===
    CONTINUE = "continue"
    ADVANCE_LAYER = "advance_layer"

    # === Termination ===
    COMPLETE = "complete"
    ERROR = "error"
    BLOCKED = "blocked"

    # === External Operations ===
    POST_TO_LINEAR = "post_to_linear"
    SETUP_WORKTREE = "setup_worktree"
    COMMIT_AND_PUSH = "commit_and_push"
    CREATE_PR = "create_pr"
