"""Create-plan state machine.

Orchestrates top-down decomposition of a ticket into a layered design.
Communication happens through files in the workspace directory.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from scripts.planner.actions import ActionType
from scripts.planner.layer_manager import LayerManager
from scripts.planner.state import DomainHypothesis, PatternHypothesis, UnitRelation

if TYPE_CHECKING:
    from scripts.planner.state import Branch, Capability, DesignState, Unit, UnitPlan


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
        elif phase == "replan":
            self._handle_replan()
        elif phase == "refactoring":
            self._handle_refactoring()
        elif phase == "test_planning":
            self._handle_test_planning()
        elif phase == "generate_docs":
            self._handle_generate_docs()
        elif phase == "post_to_linear":
            self._handle_post_to_linear()
        elif phase == "complete":
            self._handle_complete()
        else:
            self._handle_error(f"Unknown phase: {phase}")

    def process_agent_output(self) -> None:
        """Process agent output and determine next action.

        Determines agent type from current phase and next_action.yaml.
        Reads appropriate output files based on agent type.
        """
        # Determine agent type from next_action.yaml
        next_action = self.state.read_next_action()
        action_type = next_action.get("action", "")

        if action_type == "call_decomposer":
            self._process_decomposer_output({})
        elif action_type == "call_layer_reviewer":
            output = self.state.read_agent_output()
            self._process_layer_reviewer_output(output)
        elif action_type == "call_design_refactorer":
            output = self.state.read_agent_output()
            self._process_refactorer_output(output)
        elif action_type == "call_test_planner":
            output = self.state.read_agent_output()
            self._process_test_planner_output(output)
        elif action_type == ActionType.GENERATE_DOCS.value:
            output = self.state.read_agent_output()
            self._process_generate_docs_output(output)
        elif action_type == ActionType.POST_TO_LINEAR.value:
            self._process_post_to_linear()
        else:
            self._handle_error(f"Unknown action type for processing: {action_type}")

    def _handle_init(self) -> None:
        """Initialize - move directly to decomposition."""
        self.state.phase = "decomposition"
        self.state.save()
        self.next_action()

    def _handle_decomposition(self) -> None:
        """Find pending units at current layer and request decomposition."""
        pending = self.layer_manager.get_pending_units_at_layer(self.state.current_layer)
        for branch in self.state.branches.values():
            if branch.status == "replanning":
                branch.status = "exploring"

        if not pending:
            # No pending units at current layer - review parent layer (current - 1)
            parent_layer = self.state.current_layer - 1

            if parent_layer < 0:
                # Layer -1 doesn't exist, skip review and advance to next layer
                self.state.current_layer += 1
                self.state.save()
                self.next_action()
                return

            # Review parent layer now that current layer (its children) is populated
            self.state.phase = "review"
            self.state.review_target_layer = parent_layer
            self.state.save()
            self.next_action()
            return

        # Clear previous iteration's I/O files
        self.state.clear_unit_io()

        main_branch: Branch | None = self.state.branches.get("main")
        layer_history: list[Any] = []
        if main_branch is not None:
            layer_history = main_branch.history.get(self.state.current_layer, [])[-3:]
        history_prompt = self._format_layer_history_prompt(
            self.state.current_layer,
            layer_history,
        )

        # Write action for orchestrator - one decomposer per unit
        self.state.write_next_action(
            ActionType.CALL_DECOMPOSER,
            target_units=pending,
            prompt=history_prompt,
        )

        # Write per-unit input files for parallel decomposer execution
        for uid in pending:
            unit = self.state.units[uid]
            unit_data = {
                "unit": {
                    "id": uid,
                    "description": unit.description,
                    "context": self._get_unit_context(uid),
                },
                "layer_history": {
                    "layer": self.state.current_layer,
                    "previous_attempts": layer_history,
                    "note": "Avoid creating plans semantically similar to previous attempts",
                },
            }
            self.state.write_agent_input(unit_data, unit_id=uid)

    def _handle_review(self) -> None:
        """Request layer review."""
        active_branches = [
            branch_id
            for branch_id, branch in self.state.branches.items()
            if branch.status in ("exploring", "selected")
        ]

        if len(active_branches) > 1:
            self._review_all_branches()
            return

        branch_id = active_branches[0] if active_branches else "main"
        self._review_single_branch(branch_id)

    def _review_single_branch(self, branch_id: str = "main") -> None:
        """Request layer review for a single branch."""
        target_layer = (
            self.state.review_target_layer
            if self.state.review_target_layer is not None
            else self.state.current_layer
        )
        layer_units = self.layer_manager.get_units_at_layer(target_layer, branch_id)
        child_units = self.layer_manager.get_units_at_layer(target_layer + 1, branch_id)

        branch = self.state.branches.get(branch_id)
        layer_history = []
        if branch is not None:
            layer_history = branch.history.get(target_layer, [])[-3:]
        history_prompt = self._format_layer_history_prompt(target_layer, layer_history)

        self.state.write_next_action(
            ActionType.CALL_LAYER_REVIEWER,
            layer=target_layer,
            prompt=history_prompt,
            branch_id=branch_id,
        )

        self.state.write_agent_input(
            {
                "layer": target_layer,
                "layer_units": [self._unit_to_dict(uid) for uid in layer_units],
                "child_units": [self._unit_to_dict(uid) for uid in child_units],
                "explored_paths": self._explored_paths_to_dict(),
                "layer_history": {
                    "layer": target_layer,
                    "previous_attempts": layer_history,
                    "note": "Consider previous attempts when suggesting refactoring",
                },
            }
        )
        # Clear review_target_layer after writing action
        self.state.review_target_layer = None
        self.state.save()

    def _review_all_branches(self) -> None:
        """Request layer review for all active branches.

        Note: Branch-level tree review (comparing entire branch hierarchies via
        tree-reviewer agent) has been permanently disabled in favor of per-unit
        multi-path decomposition. The per-unit approach stores alternative
        decomposition paths in `explored_paths` and lets the layer reviewer
        select between them via `selected_path` output, providing more granular
        control than full branch comparison. See tree-reviewer.md for details.
        """
        active_branches = [
            branch_id
            for branch_id, branch in self.state.branches.items()
            if branch.status in ("exploring", "selected")
        ]
        # Select highest-confidence branch for single-branch review.
        # Multi-path exploration happens at the unit level via explored_paths.
        best_branch = max(
            active_branches,
            key=lambda bid: self.state.branches[bid].confidence,
        )
        self._review_single_branch(best_branch)
        return

    def _handle_refactoring(self) -> None:
        """Request design refactoring.

        The agent input was already written when the phase was set to refactoring.
        We just need to write the action.
        """
        self.state.write_next_action(ActionType.CALL_DESIGN_REFACTORER)

    def _handle_replan(self) -> None:
        """Handle replanning phase for branches marked for replan."""
        replanning_branches = [
            branch_id
            for branch_id, branch in self.state.branches.items()
            if branch.status == "replanning"
        ]
        self.state.add_history(
            "replan_start",
            {"branches": replanning_branches, "layer": self.state.current_layer},
        )
        if not replanning_branches:
            self.state.phase = "decomposition"
            self.state.save()
            self.next_action()
            return

        if self.state.current_layer == 0:
            self.state.add_history(
                "replan_error",
                {"reason": "no_parent_layer", "layer": self.state.current_layer},
            )
            self.state.phase = "decomposition"
            self.state.save()
            self.next_action()
            return

        parent_layer = self.state.current_layer - 1
        for branch_id in replanning_branches:
            branch = self.state.branches.get(branch_id)
            if branch is None:
                continue
            self.layer_manager.pop_layer(branch_id, self.state.current_layer)
            parent_units = self.layer_manager.get_branch_units_at_layer(
                branch_id,
                parent_layer,
            )
            if not parent_units:
                self.state.add_history(
                    "replan_warning",
                    {
                        "branch_id": branch_id,
                        "layer": parent_layer,
                        "reason": "no_parent_units",
                    },
                )
            for unit_id in parent_units:
                unit = self.state.units.get(unit_id)
                if unit is not None:
                    unit.status = "pending"

        self.state.phase = "decomposition"
        self.state.current_layer = parent_layer
        self.state.save()
        self.next_action()

    def _handle_test_planning(self) -> None:
        """Plan tests for all capabilities.

        Collects capabilities from all units and calls test-planner to
        decompose each capability into building block specifications.
        """
        # Collect all capabilities from units
        capabilities: list[dict[str, Any]] = []
        for unit in self.state.units.values():
            for cap in unit.expected_capabilities:
                capabilities.append(
                    {
                        **cap.to_dict(),
                        "source_unit_id": unit.id,
                        "capability_role": "expected",
                    }
                )
            for cap in unit.provided_capabilities:
                capabilities.append(
                    {
                        **cap.to_dict(),
                        "source_unit_id": unit.id,
                        "capability_role": "provided",
                    }
                )

        if not capabilities:
            # No capabilities to plan tests for
            self.state.phase = "generate_docs"
            self.state.save()
            self.next_action()
            return

        self.state.write_next_action(ActionType.CALL_TEST_PLANNER)
        self.state.write_agent_input(
            {
                "capabilities": capabilities,
                "units": {uid: self._unit_to_dict(uid) for uid in self.state.units},
            }
        )

    def _handle_generate_docs(self) -> None:
        """Generate documentation files."""
        self.state.write_next_action(ActionType.GENERATE_DOCS)
        self.state.write_agent_input(
            {
                "ticket": {
                    "id": self.state.ticket_id,
                    "title": self.state.title,
                    "url": self.state.url,
                    "workflow": self.state.workflow,
                },
                "units": {uid: self._unit_to_dict(uid) for uid in self.state.units},
                "layers": self.state.branches["main"].layers,
                "test_plans": {
                    cap_id: plan.to_dict() for cap_id, plan in self.state.test_plans.items()
                },
                "relations": [relation.to_dict() for relation in self.state.relations],
            }
        )

    def _handle_post_to_linear(self) -> None:
        """Signal to post docs to Linear."""
        self.state.write_next_action(ActionType.POST_TO_LINEAR)

    def _process_post_to_linear(self) -> None:
        """Process post to Linear completion."""
        self.state.add_history("post_to_linear", {"posted": True})
        self.state.phase = "complete"
        self.state.save()
        self.next_action()

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

        Reads from per-unit output files in outputs/ directory.
        Handles both single decomposition (children) and tree-of-thought (paths).

        Args:
            output: The agent output dictionary (used for agent type, ignored for results)
        """
        from scripts.planner.state import Branch, ExploredPath, summarize_plan

        # Read all per-unit output files
        unit_outputs = self.state.read_all_unit_outputs()
        branch = self.state.branches.get("main")
        if branch is None:
            branch = Branch(branch_id="main", layers={0: ["root"]})
            self.state.branches["main"] = branch

        for result in unit_outputs:
            unit_id = result.get("unit_id")
            if not unit_id or unit_id not in self.state.units:
                continue

            unit = self.state.units[unit_id]

            if result.get("is_atomic"):
                unit.status = "atomic"
                unit.pattern = result.get("pattern")
                unit.pattern_category = result.get("pattern_category")
                unit.plan = self._build_plan(result.get("specification", {}))
                if "expected_capabilities" in result:
                    unit.expected_capabilities = self._capabilities_from_data(
                        result.get("expected_capabilities")
                    )
                if "provided_capabilities" in result:
                    unit.provided_capabilities = self._capabilities_from_data(
                        result.get("provided_capabilities")
                    )
            elif result.get("paths"):
                # Tree-of-thought: multiple decomposition paths
                unit.status = "decomposed"
                paths = result.get("paths", [])

                # Store paths for layer reviewer to select
                if unit_id not in self.state.explored_paths:
                    self.state.explored_paths[unit_id] = {}

                # For now, select the highest confidence path automatically
                # Layer reviewer can override this selection
                best_path = max(paths, key=lambda p: p.get("confidence", 0))

                for path_data in paths:
                    path_id = path_data.get("path_id", "default")
                    is_selected = path_data == best_path

                    # Record path
                    self.state.explored_paths[unit_id][path_id] = ExploredPath(
                        confidence=path_data.get("confidence", 0.5),
                        rationale=path_data.get("rationale", ""),
                        status="selected" if is_selected else "exploring",
                        sub_unit_specs=path_data.get("sub_units", []),
                        sub_units=[su["id"] for su in path_data.get("sub_units", [])],
                    )

                new_unit_ids = self.state.commit_to_path(
                    unit_id,
                    best_path["path_id"],
                    self.layer_manager,
                )
                self.layer_manager.add_units_to_layer(new_unit_ids)
                selected_path_data = best_path
                if "relations" in selected_path_data:
                    for rel_data in selected_path_data.get("relations", []):
                        if isinstance(rel_data, dict):
                            self.state.relations.append(UnitRelation.from_dict(rel_data))
            elif result.get("children"):
                # Single decomposition path
                unit.status = "decomposed"
                children = result.get("children", [])
                for child_data in children:
                    child_id = child_data["id"]
                    self.state.units[child_id] = self._create_unit(child_data, parent=unit_id)
                    unit.children.append(child_id)
                self.layer_manager.add_units_to_layer([c["id"] for c in children])
                if "relations" in result:
                    for rel_data in result.get("relations", []):
                        if isinstance(rel_data, dict):
                            self.state.relations.append(UnitRelation.from_dict(rel_data))

            if "domain_hypotheses" in result:
                unit.domain_hypotheses = [
                    DomainHypothesis.from_dict(d)
                    for d in result.get("domain_hypotheses", [])
                    if isinstance(d, dict)
                ]

            if "pattern_hypotheses" in result:
                unit.pattern_hypotheses = [
                    PatternHypothesis.from_dict(p)
                    for p in result.get("pattern_hypotheses", [])
                    if isinstance(p, dict)
                ]

            summary = summarize_plan(result)
            branch.history.setdefault(self.state.current_layer, []).append(summary)
            if len(branch.history[self.state.current_layer]) > 5:
                branch.history[self.state.current_layer] = branch.history[self.state.current_layer][
                    -5:
                ]

        self.state.add_history("decompose", {"count": len(unit_outputs)})
        self.state.save()
        self.next_action()

    def _process_layer_reviewer_output(self, output: dict[str, Any]) -> None:
        """Process layer reviewer results.

        Args:
            output: The agent output dictionary
        """
        # Handle path selection if tree-of-thought
        selected_path = output.get("selected_path")
        if selected_path:
            try:
                unit_id: str | None = None
                path_id: str | None = None
                if isinstance(selected_path, dict):
                    unit_id = selected_path.get("unit_id")
                    path_id = selected_path.get("path_id")
                elif isinstance(selected_path, str):
                    for uid, paths in self.state.explored_paths.items():
                        if selected_path in paths:
                            unit_id = uid
                            path_id = selected_path
                            break
                if unit_id is None or path_id is None:
                    raise ValueError(f"Selected path missing unit_id or path_id: {selected_path}")
                new_unit_ids = self.state.commit_to_path(unit_id, path_id, self.layer_manager)
                self.layer_manager.add_units_to_layer(new_unit_ids)
            except (ValueError, KeyError) as e:
                logging.warning(
                    "Failed to process selected_path %r: %s. Skipping path commit.",
                    selected_path,
                    e,
                )
                # Continue without committing - planner proceeds gracefully

        # Handle refactoring actions
        actions = output.get("refactoring_actions", [])
        priority_1 = [a for a in actions if a.get("priority") == 1]

        if priority_1:
            # Set phase to refactoring and save state
            self.state.phase = "refactoring"
            self.state.add_history("review_refactor", {"actions_count": len(priority_1)})
            self.state.save()
            # Write agent input for design refactorer
            self.state.write_agent_input({"actions": priority_1})
            # Write next action
            self.state.write_next_action(ActionType.CALL_DESIGN_REFACTORER)
            return

        # Check proceed
        if not output.get("proceed", True):
            self._handle_error(output.get("proceed_notes", "Review blocked"))
            return

        # Advance to next layer or finish
        next_layer = self._find_next_layer(self.state.current_layer)
        if next_layer is not None:
            self.state.current_layer = next_layer
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

    def _merge_branch_to_main(self, branch_id: str) -> None:
        """Merge a single remaining branch into main."""
        if branch_id == "main":
            branch = self.state.branches.get("main")
            if branch is not None:
                branch.status = "selected"
            return
        branch = self.state.branches.pop(branch_id, None)
        if branch is None:
            return
        branch.branch_id = "main"
        branch.status = "selected"
        self.state.branches["main"] = branch

    def _process_refactorer_output(self, output: dict[str, Any]) -> None:
        """Process design refactorer results.

        Args:
            output: The agent output dictionary
        """
        from scripts.planner.state import Branch, summarize_plan

        changes = output.get("changes", [])
        # Apply unit changes from refactoring
        for change in changes:
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

        def _change_has_plan_spec(change: dict[str, Any]) -> bool:
            if change.get("plan") is not None or change.get("specification") is not None:
                return True
            unit = change.get("unit")
            if isinstance(unit, dict):
                return unit.get("plan") is not None or unit.get("specification") is not None
            return False

        should_record_history = any(
            (change.get("type") == "add" and change.get("unit")) or _change_has_plan_spec(change)
            for change in changes
        )
        if should_record_history:
            branch = self.state.branches.get("main")
            if branch is None:
                branch = Branch(branch_id="main", layers={0: ["root"]})
                self.state.branches["main"] = branch
            summary = summarize_plan({"changes": changes})
            branch.history.setdefault(self.state.current_layer, []).append(summary)
            if len(branch.history[self.state.current_layer]) > 5:
                branch.history[self.state.current_layer] = branch.history[self.state.current_layer][
                    -5:
                ]

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
        from scripts.planner.state import TestPlan

        test_plans = output.get("test_plans", [])
        for plan_data in test_plans:
            # TestPlan.from_dict() handles extracting suite fields from nested suite dict
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

    def _process_generate_docs_output(self, output: dict[str, Any]) -> None:
        """Process documentation generation results.

        Args:
            output: The agent output dictionary from design-formatter
        """
        # Validate that output is from design-formatter (not diagram-generator)
        agent = output.get("agent")
        if agent != "design-formatter":
            self._handle_error(
                f"Expected design-formatter output, got: {agent}. "
                "Ensure diagram-generator runs before design-formatter."
            )
            return

        # Validate required files were written
        files_written = output.get("files_written", [])
        required_files = ["architecture.md", "implementation.md"]
        missing = [f for f in required_files if f not in files_written]
        if missing:
            self._handle_error(f"design-formatter did not write required files: {missing}")
            return

        self.state.add_history(
            "generate_docs",
            {
                "agent": agent,
                "files": files_written,
            },
        )
        self.state.phase = "post_to_linear"
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

    def _find_next_layer(self, current: int) -> int | None:
        """Find the next layer with pending units.

        Searches across all active branches to find the smallest layer
        greater than current that has pending units.

        Args:
            current: Current layer number

        Returns:
            Next layer number with pending units, or None if no more layers
        """
        next_layer: int | None = None
        for branch_id, branch in self.state.branches.items():
            if branch.status not in ("exploring", "selected"):
                continue
            for layer in branch.layers:
                if layer <= current:
                    continue
                pending = self.layer_manager.get_pending_units_at_layer(layer, branch_id)
                if pending and (next_layer is None or layer < next_layer):
                    next_layer = layer
        return next_layer

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

    def _format_layer_history_prompt(
        self,
        layer: int,
        history: list[dict[str, Any]],
    ) -> str:
        history_json = json.dumps(history, ensure_ascii=True)
        return f"Layer {layer} history (avoid semantically similar plans): {history_json}"

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

    def _capabilities_from_data(self, data: Any) -> list[Capability]:
        from scripts.planner.state import Capability

        if not isinstance(data, list):
            return []
        return [Capability.from_dict(item) for item in data if isinstance(item, dict)]

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
            expected_capabilities=self._capabilities_from_data(data.get("expected_capabilities")),
            provided_capabilities=self._capabilities_from_data(data.get("provided_capabilities")),
        )
