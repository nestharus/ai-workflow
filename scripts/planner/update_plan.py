"""Update-plan state machine.

Applies review comments using bottom-up layer processing.
Comments are grouped by layer, processed from deepest to shallowest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scripts.planner.actions import ActionType
from scripts.planner.layer_manager import LayerManager

if TYPE_CHECKING:
    from scripts.planner.state import DesignState, ReviewComment, UnitPlan


class UpdatePlanStateMachine:
    """State machine for update-plan workflow.

    Algorithm:
    1. Group comments by target layer
    2. Start at deepest layer with comments
    3. Apply ALL comments at that layer (parallel by unit)
    4. Review that layer
    5. Move up one layer, repeat
    6. Replan tests for affected capabilities
    7. Generate updated docs

    Test Replanning:
    After all comments are applied and layers reviewed, test-planner is called
    to update test plans for any capabilities that were affected by the changes.
    """

    def __init__(self, state: DesignState) -> None:
        """Initialize update plan state machine.

        Args:
            state: The design state to manage
        """
        self.state = state
        self.layer_manager = LayerManager(state)
        self._comments_by_layer: dict[int, list[ReviewComment]] | None = None

    def next_action(self) -> None:
        """Determine and write next action."""
        phase = self.state.phase

        if phase == "init":
            self._handle_init()
        elif phase == "apply_comments":
            self._handle_apply_comments()
        elif phase == "review":
            self._handle_review()
        elif phase == "replan":
            self._handle_replan()
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
        """Process agent output."""
        next_action = self.state.read_next_action()
        action_type = next_action.get("action", "")
        if action_type == ActionType.GENERATE_DOCS.value:
            output = self.state.read_agent_output()
            self._process_generate_docs_output(output)
            return
        if action_type == ActionType.POST_TO_LINEAR.value:
            self._process_post_to_linear()
            return

        output = self.state.read_agent_output()
        agent = output.get("agent")

        if agent == "comment-applier":
            self._process_comment_applier_output(output)
        elif agent == "layer-reviewer":
            self._process_layer_reviewer_output(output)
        elif agent == "design-refactorer":
            self._process_refactorer_output(output)
        elif agent == "test-planner":
            self._process_test_planner_output(output)
        else:
            self._handle_error(f"Unknown agent: {agent}")

    def _handle_init(self) -> None:
        """Group comments by layer, start at deepest."""
        self._refresh_comments_by_layer()

        if not self._comments_by_layer:
            # No comments to process
            self.state.phase = "complete"
            self.state.save()
            self.next_action()
            return

        # Start at deepest layer
        self.state.current_layer = max(self._comments_by_layer.keys())
        self.state.phase = "apply_comments"
        self.state.save()
        self.next_action()

    def _handle_apply_comments(self) -> None:
        """Apply comments at current layer."""
        self._refresh_comments_by_layer()

        comments_by_layer = self._comments_by_layer
        assert comments_by_layer is not None  # Set by _refresh_comments_by_layer

        layer_comments = comments_by_layer.get(self.state.current_layer, [])

        if not layer_comments:
            # No comments at this layer, move to review
            self.state.phase = "review"
            self.state.save()
            self.next_action()
            return

        # Group by unit for parallel processing
        by_unit: dict[str, list[ReviewComment]] = {}
        for comment in layer_comments:
            uid = comment.target_unit_id
            by_unit.setdefault(uid, []).append(comment)

        self.state.write_next_action(
            ActionType.CALL_COMMENT_APPLIER,
            target_units=list(by_unit.keys()),
        )

        self.state.write_agent_input(
            {
                "comments_by_unit": {
                    uid: [self._comment_to_dict(c) for c in comments]
                    for uid, comments in by_unit.items()
                },
                "units": {uid: self._unit_to_dict(uid) for uid in by_unit},
            }
        )

    def _handle_review(self) -> None:
        """Review current layer after comments applied."""
        # Same as create_plan review but scoped to this layer
        layer_units = self.layer_manager.get_units_at_layer(self.state.current_layer)
        child_units = self.layer_manager.get_units_at_layer(self.state.current_layer + 1)
        main_branch = self.state.branches.get("main")
        layer_history: list[Any] = []
        if main_branch is not None:
            layer_history = main_branch.history.get(self.state.current_layer, [])[-3:]

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
                "layer_history": {
                    "layer": self.state.current_layer,
                    "previous_attempts": layer_history,
                    "note": "Consider previous attempts when suggesting refactoring",
                },
                "changes_applied": True,  # Flag that we just applied changes
            }
        )

    def _handle_replan(self) -> None:
        """Handle replanning phase for update-plan (future extensibility)."""
        self.layer_manager.pop_layer("main", self.state.current_layer + 1)
        layer_units = self.layer_manager.get_units_at_layer(self.state.current_layer)
        for unit_id in layer_units:
            unit = self.state.units.get(unit_id)
            if unit is not None:
                unit.status = "pending"

        self.state.phase = "apply_comments"
        self.state.save()
        self.next_action()

    def _handle_test_planning(self) -> None:
        """Replan tests for affected capabilities.

        After comments are applied and layers reviewed, test-planner updates
        test plans for capabilities that were affected by the changes.
        """
        # Collect capabilities from affected units
        affected_unit_ids = set()
        for comment in self.state.comments:
            if comment.resolution == "applied":
                affected_unit_ids.add(comment.target_unit_id)

        # Collect capabilities from affected units and their children
        capabilities: list[dict[str, Any]] = []
        for unit_id in self.state.units:
            unit = self.state.units[unit_id]
            # Include if directly affected or is child of affected
            is_affected = unit_id in affected_unit_ids
            has_affected_parent = unit.parent in affected_unit_ids if unit.parent else False

            if is_affected or has_affected_parent:
                for cap in unit.expected_capabilities:
                    capabilities.append(
                        {
                            **cap.to_dict(),
                            "source_unit_id": unit.id,
                            "capability_role": "expected",
                            "affected": True,
                        }
                    )
                for cap in unit.provided_capabilities:
                    capabilities.append(
                        {
                            **cap.to_dict(),
                            "source_unit_id": unit.id,
                            "capability_role": "provided",
                            "affected": True,
                        }
                    )

        if not capabilities:
            # No affected capabilities to replan
            self.state.latest_test_replanning_count = 0
            self.state.latest_replanned_tests = []
            self.state.phase = "generate_docs"
            self.state.save()
            self.next_action()
            return

        self.state.write_next_action(ActionType.CALL_TEST_PLANNER)
        self.state.write_agent_input(
            {
                "capabilities": capabilities,
                "units": {uid: self._unit_to_dict(uid) for uid in self.state.units},
                "existing_test_plans": {
                    cap_id: plan.to_dict() for cap_id, plan in self.state.test_plans.items()
                },
                "mode": "update",  # Signal this is an update, not fresh planning
            }
        )

    def _handle_generate_docs(self) -> None:
        """Generate documentation files."""
        agent_input = {
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

        if self.state.workflow == "update-plan":
            agent_input["update_summary"] = self._compute_update_summary()

        self.state.write_next_action(ActionType.GENERATE_DOCS)
        self.state.write_agent_input(agent_input)

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

    def _process_comment_applier_output(self, output: dict[str, Any]) -> None:
        """Process comment applier results.

        Args:
            output: Output from comment-applier agent
        """
        # Mark comments as resolved
        for comment_id in output.get("resolved_comments", []):
            for comment in self.state.comments:
                if comment.id == comment_id:
                    comment.resolution = "applied"

        # Apply any unit changes
        for uid, changes in output.get("unit_changes", {}).items():
            unit = self.state.units.get(uid)
            if unit and "plan" in changes:
                unit.plan = self._build_plan(changes["plan"])

        self._refresh_comments_by_layer()
        self.state.add_history(
            "apply_comments",
            {
                "layer": self.state.current_layer,
                "resolved_count": len(output.get("resolved_comments", [])),
            },
        )
        self.state.phase = "review"
        self.state.save()
        self.next_action()

    def _process_layer_reviewer_output(self, output: dict[str, Any]) -> None:
        """Process layer reviewer, move up to next layer.

        Args:
            output: Output from layer-reviewer agent
        """
        # Handle any refactoring
        actions = output.get("refactoring_actions", [])
        if actions:
            # Execute refactoring first
            self.state.write_next_action(ActionType.CALL_DESIGN_REFACTORER)
            self.state.write_agent_input({"actions": actions})
            return

        # Move up one layer (bottom-up)
        self._refresh_comments_by_layer()

        min_layer = min(self._comments_by_layer.keys()) if self._comments_by_layer else 0

        if self.state.current_layer > min_layer:
            self.state.current_layer -= 1
            self.state.phase = "apply_comments"
        else:
            # All layers done - replan tests for affected capabilities
            self.state.phase = "test_planning"

        self.state.add_history("layer_reviewed", {"layer": self.state.current_layer})
        self.state.save()
        self.next_action()

    def _process_refactorer_output(self, output: dict[str, Any]) -> None:
        """Process design refactorer results.

        Args:
            output: Output from design-refactorer agent
        """
        # Apply refactoring changes to units
        for change in output.get("changes", []):
            uid = change.get("unit_id")
            if uid and uid in self.state.units:
                unit = self.state.units[uid]
                if "description" in change:
                    unit.description = change["description"]
                if "plan" in change:
                    unit.plan = self._build_plan(change["plan"])

        self.state.add_history(
            "refactoring_applied",
            {
                "changes_count": len(output.get("changes", [])),
            },
        )
        self.state.save()

        # Continue with layer review processing
        self._continue_after_refactoring()

    def _process_test_planner_output(self, output: dict[str, Any]) -> None:
        """Process test planner results.

        Updates test plans for affected capabilities.

        Args:
            output: The agent output dictionary containing test plans
        """
        from scripts.planner.state import TestPlan

        test_plans = output.get("test_plans", [])
        replanned_tests: list[dict[str, Any]] = []
        for plan_data in test_plans:
            # TestPlan.from_dict() handles extracting suite fields from nested suite dict
            plan = TestPlan.from_dict(plan_data)
            # Update or add test plan
            self.state.test_plans[plan.capability_id] = plan
            replanned_tests.append(
                {
                    "id": plan.id,
                    "capability_id": plan.capability_id,
                    "type": plan.type,
                    "use_case": plan.use_case,
                }
            )

        self.state.add_history(
            "test_replanning",
            {"test_plans_updated": len(test_plans)},
        )
        self.state.latest_test_replanning_count = len(test_plans)
        self.state.latest_replanned_tests = replanned_tests

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

    def _continue_after_refactoring(self) -> None:
        """Continue the workflow after refactoring is complete."""
        self._refresh_comments_by_layer()

        min_layer = min(self._comments_by_layer.keys()) if self._comments_by_layer else 0

        if self.state.current_layer > min_layer:
            self.state.current_layer -= 1
            self.state.phase = "apply_comments"
        else:
            # All layers done - replan tests for affected capabilities
            self.state.phase = "test_planning"

        self.state.save()
        self.next_action()

    def _refresh_comments_by_layer(self) -> None:
        """Rebuild pending comments grouped by target layer."""
        self._comments_by_layer = {}
        for comment in self.state.comments:
            if comment.resolution == "pending":
                layer = comment.target_layer
                self._comments_by_layer.setdefault(layer, []).append(comment)

    def _comment_to_dict(self, comment: ReviewComment) -> dict[str, Any]:
        """Convert a ReviewComment to a dictionary for YAML output.

        Args:
            comment: The review comment to convert

        Returns:
            Dictionary representation of the comment
        """
        return {
            "id": comment.id,
            "author": comment.author,
            "target_unit_id": comment.target_unit_id,
            "target_layer": comment.target_layer,
            "type": comment.type,
            "content": comment.content,
            "resolution": comment.resolution,
        }

    def _unit_to_dict(self, unit_id: str) -> dict[str, Any]:
        """Convert a unit to a dictionary for YAML output.

        Args:
            unit_id: ID of the unit to convert

        Returns:
            Dictionary representation of the unit
        """
        unit = self.state.units.get(unit_id)
        if not unit:
            return {"id": unit_id, "error": "not_found"}

        result: dict[str, Any] = {
            "id": unit.id,
            "description": unit.description,
            "operation": unit.operation,
            "status": unit.status,
        }
        if unit.pattern:
            result["pattern"] = unit.pattern
        if unit.pattern_category:
            result["pattern_category"] = unit.pattern_category
        if unit.children:
            result["children"] = unit.children
        if unit.parent:
            result["parent"] = unit.parent
        if unit.plan:
            result["plan"] = unit.plan.to_dict()
        if unit.path_id:
            result["path_id"] = unit.path_id
        if unit.confidence is not None:
            result["confidence"] = unit.confidence

        return result

    def _explored_paths_to_dict(self) -> dict[str, Any]:
        """Convert explored paths to a serializable dictionary.

        Returns:
            Dictionary of explored paths with path data
        """
        result: dict[str, Any] = {}
        for unit_id, paths in self.state.explored_paths.items():
            result[unit_id] = {path_id: path.to_dict() for path_id, path in paths.items()}
        return result

    def _build_plan(self, data: dict[str, Any]) -> UnitPlan:
        """Build a UnitPlan from dictionary data.

        Args:
            data: Dictionary containing plan data

        Returns:
            UnitPlan instance
        """
        from scripts.planner.state import UnitPlan

        return UnitPlan.from_dict(data)

    def _compute_update_summary(self) -> dict[str, Any]:
        """Compute update summary statistics.

        Returns:
            Dictionary with update summary data
        """
        comments_total = len(self.state.comments)
        comments_applied = sum(1 for c in self.state.comments if c.resolution == "applied")
        comments_pending = sum(1 for c in self.state.comments if c.resolution == "pending")

        affected_unit_ids = set()
        affected_layers = set()
        for comment in self.state.comments:
            if comment.resolution == "applied":
                affected_unit_ids.add(comment.target_unit_id)
                affected_layers.add(comment.target_layer)

        # latest_test_replanning_count is always populated upstream:
        # - Set to 0 in _handle_test_planning when no capabilities affected
        # - Set to len(test_plans) in _process_test_planner_output after replanning
        latest_count = self.state.latest_test_replanning_count
        replanned_tests = self.state.latest_replanned_tests

        return {
            "update_source": self.state.update_source or "unknown",
            "prompt_text": self.state.update_prompt_text or "",
            "comments_total": comments_total,
            "comments_applied": comments_applied,
            "comments_pending": comments_pending,
            "layers_touched": sorted(affected_layers),
            "units_touched": sorted(affected_unit_ids),
            "test_plans_updated": latest_count,
            "replanned_tests": replanned_tests,
        }
