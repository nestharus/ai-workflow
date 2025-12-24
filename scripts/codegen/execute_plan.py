"""Execute-plan state machine.

Generates code from a design using test-first, parallel layer-by-layer execution.
Tests are generated BEFORE code. Layers execute bottom-up (deepest atomics first).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scripts.codegen.agent_router import get_agent_for_pattern
from scripts.codegen.file_scheduler import FileScheduler
from scripts.planner.actions import ActionType
from scripts.planner.layer_manager import LayerManager

if TYPE_CHECKING:
    from scripts.planner.state import DesignState, UnitPlan


class ExecutePlanStateMachine:
    """State machine for execute-plan workflow.

    Test-First Phases (per layer, bottom-up):
    - init: Setup worktree
    - test_generation: Call test-implementor to compose tests from building blocks
    - test_verify_fail: Run tests (should fail - no implementation yet)
    - execution: Execute units at current layer
    - layer_test: Run tests for current layer
    - debug_loop: If tests fail, debug and replan at current layer
    - layer_complete: After all tests pass, move up or finish
    - test_verify_pass: Run all tests (should pass after all layers)
    - lint: Run lint-fixer
    - commit: Commit and push
    - pr: Create PR
    - complete: Done

    Debug Loop (when layer tests fail):
    1. Create debug worktree
    2. Call debug-fixer (may violate building blocks - ad-hoc fixes)
    3. Capture how fix was made
    4. Call solution-refactorer (refactor fix into building blocks)
    5. Replan affected capabilities at current layer (test-planner)
    6. Regenerate affected tests/code
    7. Run tests again
    8. Repeat until all tests at current layer pass
    9. After layer complete, optionally replan parent layers

    Integration Rules:
    - No mocking between workflow units (A→B→C must integrate)
    - Each layer must pass all tests before moving up
    - Debug solutions are refactored into building blocks via planning

    Test Building Blocks (14 agents in .claude/agents/test-impl/):
    - 0: suite-contract (test placement + suite requirements)
    - 1: shell-builder (function signature + decorators)
    - 2: infra-fixture-builder (infrastructure fixtures)
    - 3: override-builder (dependency overrides)
    - 4: data-builder (PAT-E compliant data)
    - 5: visible-builder (object factories)
    - 6: aaa-body-builder (implicit AAA body)
    - 7: driver-builder (test stimulus)
    - 8: assertion-builder (check.*/assert)
    - 9: scope-builder (workflow scopes)
    - 10: stream-probe-builder (traversal generators)
    - 11: loop-builder (constraint loops)
    - 12: parametrize-builder (@pytest.mark.parametrize)
    - 13: wrapper-builder (resource wrappers)

    Execution order:
    - Start at deepest layer (atomics)
    - Group units by target file
    - File groups run in parallel
    - Units within same file run sequentially
    - All tests at layer N must pass before moving to N-1
    """

    def __init__(self, state: DesignState) -> None:
        """Initialize execute-plan state machine.

        Args:
            state: The design state to execute
        """
        self.state = state
        self.layer_manager = LayerManager(state)
        self.file_scheduler = FileScheduler(state)

    def next_action(self) -> None:
        """Determine and write next action."""
        phase = self.state.phase

        if phase == "init":
            self._handle_init()
        elif phase == "test_generation":
            self._handle_test_generation()
        elif phase == "test_verify_fail":
            self._handle_test_verify(expected_to_fail=True)
        elif phase == "execution":
            self._handle_execution()
        elif phase == "layer_test":
            self._handle_layer_test()
        elif phase == "debug_create_worktree":
            self._handle_debug_create_worktree()
        elif phase == "debug_fix":
            self._handle_debug_fix()
        elif phase == "debug_refactor":
            self._handle_debug_refactor()
        elif phase == "debug_replan":
            self._handle_debug_replan()
        elif phase == "debug_regenerate":
            self._handle_debug_regenerate()
        elif phase == "layer_complete":
            self._handle_layer_complete()
        elif phase == "test_verify_pass":
            self._handle_test_verify(expected_to_fail=False)
        elif phase == "lint":
            self._handle_lint()
        elif phase == "commit":
            self._handle_commit()
        elif phase == "pr":
            self._handle_pr()
        elif phase == "complete":
            self._handle_complete()
        else:
            self._handle_error(f"Unknown phase: {phase}")

    def _handle_init(self) -> None:
        """Request worktree setup."""
        self.state.write_next_action(
            ActionType.SETUP_WORKTREE,
            ticket_id=self.state.ticket_id,
        )

    def _handle_test_generation(self) -> None:
        """Call test-implementor to compose tests from building blocks.

        The test-implementor reads test plans from state.yaml and invokes
        building block agents to compose complete test functions.
        """
        # Prepare test plans for the implementor
        test_plans: list[dict[str, Any]] = []
        for _cap_id, plan in self.state.test_plans.items():
            test_plans.append(plan.to_dict())

        self.state.write_agent_input(
            {
                "test_plans": test_plans,
                "worktree_path": self.state.worktree_path,
            }
        )

        self.state.write_next_action(ActionType.CALL_TEST_IMPLEMENTOR)

    def _handle_test_verify(self, *, expected_to_fail: bool) -> None:
        """Run tests to verify state.

        Args:
            expected_to_fail: True if tests should fail (before impl),
                              False if tests should pass (after impl)
        """
        self.state.write_next_action(
            ActionType.RUN_TESTS,
            worktree_path=self.state.worktree_path,
            expected_to_fail=expected_to_fail,
        )

    def _handle_execution(self) -> None:
        """Execute units at current layer."""
        # Get units at current layer
        layer_units = self.layer_manager.get_units_at_layer(self.state.current_layer)

        # Filter to units that need execution
        pending = [uid for uid in layer_units if self._unit_needs_execution(uid)]

        if not pending:
            # All units at this layer executed - run layer tests
            self.state.phase = "layer_test"
            self.state.save()
            self.next_action()
            return

        # Group by file for parallel execution
        file_groups = self.file_scheduler.group_by_file(pending)

        # Write action - orchestrator will handle parallel file groups
        self.state.write_next_action(
            ActionType.CALL_IMPL_AGENT,
            file_groups=file_groups,
            layer=self.state.current_layer,
        )

        # Write input for each unit
        units_input: dict[str, dict[str, Any]] = {}
        for uid in pending:
            unit = self.state.units[uid]
            agent = get_agent_for_pattern(unit.pattern) if unit.pattern else "composer"

            units_input[uid] = {
                "id": uid,
                "pattern": unit.pattern,
                "agent": agent,
                "plan": self._plan_to_dict(unit.plan) if unit.plan else None,
                "children": unit.children,
            }

        self.state.write_agent_input(
            {
                "units": units_input,
                "worktree_path": self.state.worktree_path,
            }
        )

    def _handle_layer_test(self) -> None:
        """Run tests for current layer's units.

        Tests all capabilities provided by units at this layer.
        If any fail, enter debug loop. If all pass, layer is complete.
        """
        # Get capabilities from units at current layer
        layer_units = self.layer_manager.get_units_at_layer(self.state.current_layer)
        capability_ids = []
        for uid in layer_units:
            unit = self.state.units.get(uid)
            if unit:
                for cap in unit.provided_capabilities:
                    if cap.test_id:
                        capability_ids.append(cap.id)

        self.state.write_next_action(
            ActionType.RUN_TESTS,
            worktree_path=self.state.worktree_path,
            layer=self.state.current_layer,
            capability_ids=capability_ids,
        )

    def _handle_debug_create_worktree(self) -> None:
        """Create debug worktree for isolated debugging."""
        self.state.write_next_action(
            ActionType.CREATE_DEBUG_WORKTREE,
            worktree_path=self.state.worktree_path,
            layer=self.state.current_layer,
        )

    def _handle_debug_fix(self) -> None:
        """Call debug-fixer to fix failing tests.

        The debug-fixer may make ad-hoc fixes that violate building blocks.
        It captures what was changed so we can refactor the solution.
        """
        # Get failing tests from layer_execution
        layer_exec = self.state.layer_execution.get(self.state.current_layer, {})
        failing_tests = layer_exec.get("failing_tests", [])
        debug_worktree_path = layer_exec.get("debug_worktree") or self.state.worktree_path

        self.state.write_next_action(
            ActionType.CALL_DEBUG_FIXER,
            worktree_path=debug_worktree_path,
        )
        self.state.write_agent_input(
            {
                "failing_tests": failing_tests,
                "worktree_path": debug_worktree_path,
                "layer": self.state.current_layer,
            }
        )

    def _handle_debug_refactor(self) -> None:
        """Refactor debug fix into building blocks.

        The solution-refactorer takes the ad-hoc fix and restructures it
        to follow building block patterns.
        """
        layer_exec = self.state.layer_execution.get(self.state.current_layer, {})
        debug_worktree_path = layer_exec.get("debug_worktree") or self.state.worktree_path

        self.state.write_next_action(
            ActionType.CALL_SOLUTION_REFACTORER,
            worktree_path=debug_worktree_path,
        )
        self.state.write_agent_input(
            {
                "worktree_path": debug_worktree_path,
                "layer": self.state.current_layer,
                "debug_changes": layer_exec.get("debug_changes", {}),
            }
        )

    def _handle_debug_replan(self) -> None:
        """Replan affected capabilities at current layer.

        After refactoring the fix, test-planner updates test plans
        for the affected capabilities.
        """
        # Get affected capability IDs from debug changes
        layer_exec = self.state.layer_execution.get(self.state.current_layer, {})
        affected_caps = layer_exec.get("affected_capabilities", [])
        debug_worktree_path = layer_exec.get("debug_worktree") or self.state.worktree_path

        # Collect capability data
        capabilities: list[dict[str, Any]] = []
        for cap_id in affected_caps:
            if cap_id in self.state.test_plans:
                plan = self.state.test_plans[cap_id]
                capabilities.append(
                    {
                        "id": cap_id,
                        "capability_id": plan.capability_id,
                        "affected": True,
                    }
                )

        self.state.write_next_action(
            ActionType.REPLAN_LAYER,
            worktree_path=debug_worktree_path,
        )
        self.state.write_agent_input(
            {
                "capabilities": capabilities,
                "layer": self.state.current_layer,
                "worktree_path": debug_worktree_path,
            }
        )

    def _handle_debug_regenerate(self) -> None:
        """Regenerate affected tests and code after replanning.

        After replanning, we need to regenerate tests and implementation
        for the affected capabilities.
        """
        layer_exec = self.state.layer_execution.get(self.state.current_layer, {})
        affected_caps = layer_exec.get("affected_capabilities", [])
        debug_worktree_path = layer_exec.get("debug_worktree") or self.state.worktree_path

        # Get test plans that need regeneration
        test_plans = []
        for cap_id in affected_caps:
            if cap_id in self.state.test_plans:
                test_plans.append(self.state.test_plans[cap_id].to_dict())

        self.state.write_next_action(
            ActionType.CALL_TEST_IMPLEMENTOR,
            worktree_path=debug_worktree_path,
        )
        self.state.write_agent_input(
            {
                "test_plans": test_plans,
                "worktree_path": debug_worktree_path,
                "mode": "regenerate",
            }
        )

    def _handle_layer_complete(self) -> None:
        """Handle layer completion - move up or finish.

        After all tests at current layer pass, optionally replan parent
        layers if there were significant changes, then move up.
        """
        layer_exec = self.state.layer_execution.get(self.state.current_layer, {})
        had_debug_fixes = layer_exec.get("debug_iteration", 0) > 0

        if had_debug_fixes and self.state.current_layer > 0:
            # Check if we need to replan parent layers
            # This is for bigger refactoring after layer completion
            self.state.write_next_action(ActionType.REPLAN_PARENT_LAYERS)
            self.state.write_agent_input(
                {
                    "completed_layer": self.state.current_layer,
                    "debug_changes": layer_exec.get("debug_changes", {}),
                }
            )
        else:
            # No replanning needed, move to next layer or finish
            self._advance_layer()

    def _advance_layer(self) -> None:
        """Advance to next layer or final verification."""
        if self.state.current_layer > 0:
            self.state.current_layer -= 1
            self.state.phase = "execution"
        else:
            # All layers done - final test verification
            self.state.phase = "test_verify_pass"

        self.state.save()
        self.next_action()

    def _handle_lint(self) -> None:
        """Run lint-fixer."""
        self.state.write_next_action(
            ActionType.CALL_LINT_FIXER,
            worktree_path=self.state.worktree_path,
            changed_only=True,
        )

    def _handle_commit(self) -> None:
        """Commit and push changes."""
        self.state.write_next_action(
            ActionType.COMMIT_AND_PUSH,
            worktree_path=self.state.worktree_path,
            message=f"{self.state.ticket_id}: {self.state.title}",
        )

    def _handle_pr(self) -> None:
        """Create PR."""
        self.state.write_next_action(
            ActionType.CREATE_PR,
            worktree_path=self.state.worktree_path,
            ticket_id=self.state.ticket_id,
            title=self.state.title,
        )

    def _handle_complete(self) -> None:
        """Signal completion."""
        self.state.write_next_action(ActionType.COMPLETE)

    def _handle_error(self, message: str) -> None:
        """Signal error.

        Args:
            message: Error message to include
        """
        self.state.phase = "error"
        self.state.save()
        self.state.write_next_action(ActionType.ERROR, message=message)

    def process_agent_output(self) -> None:
        """Process agent output."""
        output = self.state.read_agent_output()
        action = output.get("action")

        if action == "worktree_setup":
            self._process_worktree_setup(output)
        elif action == "tests_generated":
            self._process_tests_generated(output)
        elif action == "test_results":
            self._process_test_results(output)
        elif action == "layer_test_results":
            self._process_layer_test_results(output)
        elif action == "impl_results":
            self._process_impl_results(output)
        elif action == "debug_worktree_created":
            self._process_debug_worktree(output)
        elif action == "debug_fix_complete":
            self._process_debug_fix(output)
        elif action == "solution_refactored":
            self._process_solution_refactor(output)
        elif action == "layer_replanned":
            self._process_layer_replan(output)
        elif action == "parent_layers_replanned":
            self._process_parent_replan(output)
        elif action == "lint_complete":
            self._process_lint_complete(output)
        elif action == "commit_complete":
            self._process_commit_complete(output)
        elif action == "pr_created":
            self._process_pr_created(output)
        else:
            self._handle_error(f"Unknown action: {action}")

    def _process_worktree_setup(self, output: dict[str, Any]) -> None:
        """Process worktree setup result.

        Args:
            output: Agent output containing worktree info
        """
        self.state.worktree_path = output.get("worktree_path")
        self.state.branch_name = output.get("branch_name")
        self.state.base_branch = output.get("base_branch", "main")

        # Start at deepest layer (bottom-up) for execution phase
        max_layer = self.layer_manager.get_max_layer()
        self.state.current_layer = max_layer

        # Test-first: generate tests from plans (plans created in create-plan)
        self.state.phase = "test_generation"
        self.state.save()
        self.next_action()

    def _process_tests_generated(self, output: dict[str, Any]) -> None:
        """Process test generation results.

        Args:
            output: Agent output containing generated test info
        """
        # Update test plan statuses
        tests_composed = output.get("tests_composed", [])
        for test_info in tests_composed:
            cap_id = test_info.get("capability_id")
            if cap_id and cap_id in self.state.test_plans:
                self.state.test_plans[cap_id].status = "generated"

        # Move to test verification (should fail)
        self.state.phase = "test_verify_fail"
        self.state.save()
        self.next_action()

    def _process_test_results(self, output: dict[str, Any]) -> None:
        """Process test execution results.

        Args:
            output: Agent output containing test results
        """
        passed = output.get("passed", False)
        expected_fail = output.get("expected_to_fail", False)

        # Update test plan statuses based on results
        test_results = output.get("test_results", {})
        for cap_id, result in test_results.items():
            if cap_id in self.state.test_plans:
                if result.get("passed"):
                    self.state.test_plans[cap_id].status = "passing"
                else:
                    self.state.test_plans[cap_id].status = "failing"

        if expected_fail:
            # After test_verify_fail, move to execution
            self.state.phase = "execution"
        else:
            # After test_verify_pass, move to lint
            if not passed:
                # Tests failed when they should pass - this is an error
                self._handle_error("Tests failed after implementation")
                return
            self.state.phase = "lint"

        self.state.save()
        self.next_action()

    def _process_impl_results(self, output: dict[str, Any]) -> None:
        """Process implementation results.

        Args:
            output: Agent output containing impl results
        """
        results = output.get("results", {})

        for uid, result in results.items():
            if result.get("success"):
                # Mark as complete in execution state
                layer = self.layer_manager.compute_unit_depth(uid)
                if layer not in self.state.layer_execution:
                    self.state.layer_execution[layer] = {
                        "status": "in_progress",
                        "units_completed": [],
                        "units_failed": [],
                    }
                self.state.layer_execution[layer]["units_completed"].append(uid)
            else:
                # Record failure
                from scripts.planner.state import ExecutionFailure

                failure = ExecutionFailure(
                    unit_id=uid,
                    category="impl_error",
                    error=result.get("error", "Unknown error"),
                )
                self.state.failures.append(failure)

        self.state.save()
        self.next_action()

    def _process_layer_test_results(self, output: dict[str, Any]) -> None:
        """Process layer test results.

        If tests pass, layer is complete. If tests fail, enter debug loop.

        Args:
            output: Agent output containing test results for current layer
        """
        passed = output.get("passed", False)
        failing_tests = output.get("failing_tests", [])

        layer = self.state.current_layer
        if layer not in self.state.layer_execution:
            self.state.layer_execution[layer] = {}
        layer_exec = self.state.layer_execution[layer]

        if passed:
            # All tests passed - layer complete
            layer_exec["status"] = "complete"
            self.state.phase = "layer_complete"
        else:
            # Tests failed - enter debug loop
            layer_exec["status"] = "debugging"
            layer_exec["failing_tests"] = failing_tests
            debug_iter = layer_exec.get("debug_iteration", 0)
            layer_exec["debug_iteration"] = debug_iter + 1
            layer_exec["units_completed"] = []
            layer_exec["units_failed"] = []
            self.state.phase = "debug_create_worktree"

        self.state.save()
        self.next_action()

    def _process_debug_worktree(self, output: dict[str, Any]) -> None:
        """Process debug worktree creation.

        Args:
            output: Agent output containing debug worktree path
        """
        layer = self.state.current_layer
        if layer not in self.state.layer_execution:
            self.state.layer_execution[layer] = {}

        self.state.layer_execution[layer]["debug_worktree"] = output.get("debug_worktree_path")

        # Move to debug fix phase
        self.state.phase = "debug_fix"
        self.state.save()
        self.next_action()

    def _process_debug_fix(self, output: dict[str, Any]) -> None:
        """Process debug fix results.

        Captures the changes made by the debug-fixer so we can refactor them.

        Args:
            output: Agent output containing fix details
        """
        layer = self.state.current_layer
        if layer not in self.state.layer_execution:
            self.state.layer_execution[layer] = {}

        # Store the changes made during debugging
        self.state.layer_execution[layer]["debug_changes"] = output.get("changes", {})
        self.state.layer_execution[layer]["affected_capabilities"] = output.get(
            "affected_capabilities", []
        )

        # Move to refactor phase
        self.state.phase = "debug_refactor"
        self.state.save()
        self.next_action()

    def _process_solution_refactor(self, output: dict[str, Any]) -> None:
        """Process solution refactoring results.

        The ad-hoc fix has been restructured into building blocks.

        Args:
            output: Agent output containing refactored solution
        """
        layer = self.state.current_layer
        if layer not in self.state.layer_execution:
            self.state.layer_execution[layer] = {}

        # Store refactored changes
        self.state.layer_execution[layer]["refactored_changes"] = output.get("refactored", {})

        # Move to replan phase
        self.state.phase = "debug_replan"
        self.state.save()
        self.next_action()

    def _process_layer_replan(self, output: dict[str, Any]) -> None:
        """Process layer replan results.

        Test plans have been updated for affected capabilities.

        Args:
            output: Agent output containing updated test plans
        """
        from scripts.planner.state import TestPlan

        # Update test plans
        for plan_data in output.get("test_plans", []):
            plan = TestPlan.from_dict(plan_data)
            self.state.test_plans[plan.capability_id] = plan

        # Move to regenerate phase
        self.state.phase = "debug_regenerate"
        self.state.save()
        self.next_action()

    def _process_parent_replan(self, output: dict[str, Any]) -> None:
        """Process parent layers replan results.

        After completing a layer with debug fixes, parent layers may
        need replanning for the bigger refactoring.

        Args:
            output: Agent output containing parent layer updates
        """
        # Apply any parent layer updates
        for change in output.get("parent_changes", []):
            unit_id = change.get("unit_id")
            if unit_id and unit_id in self.state.units:
                unit = self.state.units[unit_id]
                if "plan" in change:
                    from scripts.planner.state import UnitPlan

                    unit.plan = UnitPlan.from_dict(change["plan"])

        # Move to next layer or finish
        self._advance_layer()

    def _process_lint_complete(self, output: dict[str, Any]) -> None:
        """Process lint completion.

        Args:
            output: Agent output (unused but kept for consistency)
        """
        del output  # Unused
        self.state.phase = "commit"
        self.state.save()
        self.next_action()

    def _process_commit_complete(self, output: dict[str, Any]) -> None:
        """Process commit completion.

        Args:
            output: Agent output (unused but kept for consistency)
        """
        del output  # Unused
        self.state.phase = "pr"
        self.state.save()
        self.next_action()

    def _process_pr_created(self, output: dict[str, Any]) -> None:
        """Process PR creation.

        Args:
            output: Agent output containing PR URL
        """
        self.state.pr_url = output.get("pr_url")
        self.state.phase = "complete"
        self.state.save()
        self.next_action()

    def _unit_needs_execution(self, unit_id: str) -> bool:
        """Check if a unit still needs to be executed.

        Args:
            unit_id: The unit ID to check

        Returns:
            True if unit needs execution, False if already complete
        """
        layer = self.layer_manager.compute_unit_depth(unit_id)
        if layer in self.state.layer_execution:
            layer_exec = self.state.layer_execution[layer]
            if layer_exec.get("status") == "debugging":
                return True
            completed = layer_exec.get("units_completed", [])
            if unit_id in completed:
                return False
        return True

    def _plan_to_dict(self, plan: UnitPlan | None) -> dict[str, Any] | None:
        """Convert plan to dict.

        Args:
            plan: The UnitPlan to convert

        Returns:
            Dictionary representation of the plan, or None
        """
        if plan is None:
            return None
        return plan.to_dict()
