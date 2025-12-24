"""Create-plan state machine.

Orchestrates top-down decomposition of a ticket into a layered design.
Communication happens through files in the workspace directory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scripts.planner.actions import ActionType
from scripts.planner.layer_manager import LayerManager

if TYPE_CHECKING:
    from scripts.planner.state import DesignState, Unit, UnitPlan


class CreatePlanStateMachine:
    """State machine for create-plan workflow.

    Phases:
    - init: Initialize from ticket
    - decomposition: Decompose pending units at current layer (parallel)
    - review: Layer reviewer checks current layer
    - test_planning: Plan tests for capabilities (after all decomposition done)
    - generate_docs: Generate architecture.md and implementation.md
    - complete: Done

    Test Planning:
    After decomposition completes (all leaves atomic), test-planner is called
    to decompose each capability into building block specifications. This
    produces test plans that execute-plan will use via test-implementor.

    All state transitions write to next_action.yaml for orchestrator.
    """

    def __init__(self, state: DesignState) -> None:
        """Initialize the create-plan state machine.

        Args:
            state: The design state to operate on
        """
        self.state = state
        self.layer_manager = LayerManager(state)

    def next_action(self) -> None:
        """Determine and write next action based on current phase.

        Writes to:
        - next_action.yaml: What the orchestrator should do
        - agent_input.yaml: Input for the agent (if calling one)
        """
        phase = self.state.phase

        if phase == "init":
            self._handle_init()
        elif phase == "decomposition":
            self._handle_decomposition()
        elif phase == "review":
            self._handle_review()
        elif phase == "test_planning":
            self._handle_test_planning()
        elif phase == "generate_docs":
            self._handle_generate_docs()
        elif phase == "complete":
            self._handle_complete()
        else:
            self._handle_error(f"Unknown phase: {phase}")

    def process_agent_output(self) -> None:
        """Process agent output and determine next action.

        Reads agent_output.yaml, updates state, writes next_action.yaml.
        """
        output = self.state.read_agent_output()
        agent = output.get("agent")

        if agent == "decomposer":
            self._process_decomposer_output(output)
        elif agent == "layer-reviewer":
            self._process_layer_reviewer_output(output)
        elif agent == "design-refactorer":
            self._process_refactorer_output(output)
        elif agent == "test-planner":
            self._process_test_planner_output(output)
        elif agent == "diagram-generator":
            self._process_diagram_generator_output(output)
        else:
            self._handle_error(f"Unknown agent output: {agent}")

    def _handle_init(self) -> None:
        """Initialize - move directly to decomposition."""
        self.state.phase = "decomposition"
        self.state.save()
        self.next_action()

    def _handle_decomposition(self) -> None:
        """Find pending units at current layer and request decomposition."""
        pending = self.layer_manager.get_pending_units_at_layer(self.state.current_layer)

        if not pending:
            # No pending units - move to review
            self.state.phase = "review"
            self.state.save()
            self.next_action()
            return

        # Write action for orchestrator
        self.state.write_next_action(
            ActionType.CALL_DECOMPOSER,
            target_units=pending,
        )

        # Write input for decomposer agent
        units_data = []
        for uid in pending:
            unit = self.state.units[uid]
            units_data.append(
                {
                    "id": uid,
                    "description": unit.description,
                    "context": self._get_unit_context(uid),
                }
            )

        self.state.write_agent_input({"units": units_data})

    def _handle_review(self) -> None:
        """Request layer review."""
        layer_units = self.layer_manager.get_units_at_layer(self.state.current_layer)
        child_units = self.layer_manager.get_units_at_layer(self.state.current_layer + 1)

        self.state.write_next_action(
            ActionType.CALL_LAYER_REVIEWER,
            layer=self.state.current_layer,
        )

        self.state.write_agent_input(
            {
                "layer": self.state.current_layer,
                "layer_units": [self._unit_to_dict(uid) for uid in layer_units],
                "child_units": [self._unit_to_dict(uid) for uid in child_units],
                "explored_paths": self._explored_paths_to_dict(),
            }
        )

    def _handle_test_planning(self) -> None:
        """Plan tests for all capabilities.

        Collects capabilities from all units and calls test-planner to
        decompose each capability into building block specifications.
        """
        # Collect all capabilities from units
        capabilities: list[dict[str, Any]] = []
        for unit in self.state.units.values():
            for cap in unit.expected_capabilities:
                capabilities.append({
                    **cap.to_dict(),
                    "source_unit_id": unit.id,
                    "capability_role": "expected",
                })
            for cap in unit.provided_capabilities:
                capabilities.append({
                    **cap.to_dict(),
                    "source_unit_id": unit.id,
                    "capability_role": "provided",
                })

        if not capabilities:
            # No capabilities to plan tests for
            self.state.phase = "generate_docs"
            self.state.save()
            self.next_action()
            return

        self.state.write_next_action(ActionType.CALL_TEST_PLANNER)
        self.state.write_agent_input({
            "capabilities": capabilities,
            "units": {uid: self._unit_to_dict(uid) for uid in self.state.units},
        })

    def _handle_generate_docs(self) -> None:
        """Generate documentation files."""
        self.state.write_next_action(
            ActionType.CALL_DIAGRAM_GENERATOR,
        )
        self.state.write_agent_input(
            {
                "units": {uid: self._unit_to_dict(uid) for uid in self.state.units},
                "layers": self.state.layers,
                "test_plans": {
                    cap_id: plan.to_dict()
                    for cap_id, plan in self.state.test_plans.items()
                },
            }
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

    def _process_decomposer_output(self, output: dict[str, Any]) -> None:
        """Process decomposer results for all units.

        Args:
            output: The agent output dictionary
        """
        results = output.get("results", [])

        for result in results:
            unit_id = result["unit_id"]
            unit = self.state.units[unit_id]

            if result.get("is_atomic"):
                unit.status = "atomic"
                unit.pattern = result.get("pattern")
                unit.plan = self._build_plan(result.get("specification", {}))
            else:
                # Decomposed - add children
                unit.status = "decomposed"
                children = result.get("children", [])
                for child_data in children:
                    child_id = child_data["id"]
                    self.state.units[child_id] = self._create_unit(child_data, parent=unit_id)
                    unit.children.append(child_id)
                self.layer_manager.add_units_to_layer([c["id"] for c in children])

        self.state.add_history("decompose", {"count": len(results)})
        self.state.save()
        self.next_action()

    def _process_layer_reviewer_output(self, output: dict[str, Any]) -> None:
        """Process layer reviewer results.

        Args:
            output: The agent output dictionary
        """
        # Handle path selection if tree-of-thought
        if output.get("selected_path"):
            self._commit_to_path(output["selected_path"])

        # Handle refactoring actions
        actions = output.get("refactoring_actions", [])
        priority_1 = [a for a in actions if a.get("priority") == 1]

        if priority_1:
            self.state.write_next_action(
                ActionType.CALL_DESIGN_REFACTORER,
            )
            self.state.write_agent_input({"actions": priority_1})
            return

        # Check proceed
        if not output.get("proceed", True):
            self._handle_error(output.get("proceed_notes", "Review blocked"))
            return

        # Advance to next layer or finish
        max_layer = self.layer_manager.get_max_layer()
        if self.state.current_layer < max_layer:
            self.state.current_layer += 1
            self.state.phase = "decomposition"
        else:
            # Check all leaves atomic
            if self._all_leaves_atomic():
                # All decomposition done - plan tests for capabilities
                self.state.phase = "test_planning"
            else:
                self.state.phase = "decomposition"

        self.state.save()
        self.next_action()

    def _process_refactorer_output(self, output: dict[str, Any]) -> None:
        """Process design refactorer results.

        Args:
            output: The agent output dictionary
        """
        # Apply unit changes from refactoring
        for change in output.get("changes", []):
            change_type = change.get("type")

            if change_type == "update":
                unit_id = change.get("unit_id")
                if unit_id in self.state.units:
                    unit = self.state.units[unit_id]
                    if "description" in change:
                        unit.description = change["description"]
                    if "pattern" in change:
                        unit.pattern = change["pattern"]
                    if "plan" in change:
                        unit.plan = self._build_plan(change["plan"])

            elif change_type == "add":
                child_data = change.get("unit", {})
                parent_id = change.get("parent_id")
                if child_data and parent_id:
                    child_id = child_data["id"]
                    self.state.units[child_id] = self._create_unit(child_data, parent=parent_id)
                    if parent_id in self.state.units:
                        self.state.units[parent_id].children.append(child_id)
                    self.layer_manager.add_units_to_layer([child_id])

            elif change_type == "remove":
                unit_id = change.get("unit_id")
                if unit_id in self.state.units:
                    unit = self.state.units[unit_id]
                    # Remove from parent's children list
                    if unit.parent and unit.parent in self.state.units:
                        parent = self.state.units[unit.parent]
                        if unit_id in parent.children:
                            parent.children.remove(unit_id)
                    # Remove from layer
                    self.layer_manager.remove_unit_from_layer(unit_id)
                    # Remove from units dict
                    del self.state.units[unit_id]

        self.state.add_history("refactor", {"changes": len(output.get("changes", []))})
        self.state.save()

        # Go back to review to continue
        self.state.phase = "review"
        self.state.save()
        self.next_action()

    def _process_test_planner_output(self, output: dict[str, Any]) -> None:
        """Process test planner results.

        Stores test plans with building block specifications in state.

        Args:
            output: The agent output dictionary containing test plans
        """
        from scripts.planner.state import BuildingBlockSpec, TestPlan

        test_plans = output.get("test_plans", [])
        for plan_data in test_plans:
            plan = TestPlan.from_dict(plan_data)
            self.state.test_plans[plan.capability_id] = plan

        self.state.add_history(
            "test_planning",
            {"test_plans_count": len(test_plans)},
        )

        # Move to generate docs
        self.state.phase = "generate_docs"
        self.state.save()
        self.next_action()

    def _process_diagram_generator_output(self, output: dict[str, Any]) -> None:
        """Process diagram generator results.

        Args:
            output: The agent output dictionary
        """
        # Diagram generator has written the docs, move to complete
        self.state.add_history(
            "generate_docs",
            {
                "files": output.get("files_written", []),
            },
        )
        self.state.phase = "complete"
        self.state.save()
        self.next_action()

    def _all_leaves_atomic(self) -> bool:
        """Check if all leaf units are atomic.

        Returns:
            True if all leaf units have status='atomic'
        """
        for unit in self.state.units.values():
            if not unit.children and unit.status != "atomic":
                return False
        return True

    def _get_unit_context(self, unit_id: str) -> dict[str, Any]:
        """Get context for a unit to help decomposition.

        Args:
            unit_id: The unit ID to get context for

        Returns:
            Context dictionary with parent chain and sibling info
        """
        unit = self.state.units.get(unit_id)
        if not unit:
            return {}

        context: dict[str, Any] = {
            "parent_chain": [],
            "siblings": [],
            "ticket": {
                "id": self.state.ticket_id,
                "title": self.state.title,
            },
        }

        # Get parent chain context
        parent_ids = self.layer_manager.get_parent_chain(unit_id)
        for pid in parent_ids:
            parent = self.state.units.get(pid)
            if parent:
                context["parent_chain"].append(
                    {
                        "id": pid,
                        "description": parent.description,
                        "operation": parent.operation,
                    }
                )

        # Get sibling context
        sibling_ids = self.layer_manager.get_siblings(unit_id)
        for sid in sibling_ids:
            sibling = self.state.units.get(sid)
            if sibling:
                context["siblings"].append(
                    {
                        "id": sid,
                        "description": sibling.description,
                        "status": sibling.status,
                    }
                )

        return context

    def _unit_to_dict(self, unit_id: str) -> dict[str, Any]:
        """Convert a unit to a dictionary for agent input.

        Args:
            unit_id: The unit ID to convert

        Returns:
            Dictionary representation of the unit
        """
        unit = self.state.units.get(unit_id)
        if not unit:
            return {}

        return unit.to_dict()

    def _explored_paths_to_dict(self) -> dict[str, Any]:
        """Convert explored paths to a serializable dictionary.

        Returns:
            Dictionary of explored paths with path data
        """
        result: dict[str, Any] = {}
        for unit_id, paths in self.state.explored_paths.items():
            result[unit_id] = {path_id: path.to_dict() for path_id, path in paths.items()}
        return result

    def _build_plan(self, spec: dict[str, Any]) -> UnitPlan:
        """Build a UnitPlan from specification data.

        Args:
            spec: Specification dictionary from agent output

        Returns:
            UnitPlan instance
        """
        from scripts.planner.state import UnitPlan

        return UnitPlan(
            type=spec.get("type", "create"),
            target_file=spec.get("target_file"),
            target_element=spec.get("target_element"),
            changes=spec.get("changes", []),
            reason=spec.get("reason"),
            old_pattern=spec.get("old_pattern"),
            new_pattern=spec.get("new_pattern"),
            specification=spec.get("specification"),
            cascading_changes=spec.get("cascading_changes", []),
        )

    def _create_unit(self, data: dict[str, Any], parent: str) -> Unit:
        """Create a Unit from decomposition data.

        Args:
            data: Unit data from agent output
            parent: Parent unit ID

        Returns:
            Unit instance
        """
        from scripts.planner.state import Unit

        return Unit(
            id=data["id"],
            description=data["description"],
            operation=data.get("operation", "CREATE"),
            status="pending",
            pattern=data.get("pattern"),
            pattern_category=data.get("pattern_category"),
            children=[],
            parent=parent,
            plan=None,
            path_id=data.get("path_id"),
            confidence=data.get("confidence"),
        )

    def _commit_to_path(self, path_id: str) -> None:
        """Commit to a selected exploration path.

        Marks the selected path as 'selected' and prunes alternatives.

        Args:
            path_id: The path ID to commit to
        """
        for _unit_id, paths in self.state.explored_paths.items():
            for pid, path in paths.items():
                if pid == path_id:
                    path.status = "selected"
                elif path.status == "exploring":
                    path.status = "pruned"
                    # Remove units associated with pruned paths
                    for sub_unit_id in path.sub_units:
                        if sub_unit_id in self.state.units:
                            self.layer_manager.remove_unit_from_layer(sub_unit_id)
                            del self.state.units[sub_unit_id]

        self.state.add_history("commit_path", {"path_id": path_id})
