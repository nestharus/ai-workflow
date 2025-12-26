"""Refactor-plan state machine.

Orchestrates discovery-first refactoring workflow:
skeleton analysis -> component analysis -> integration mapping -> refactor planning
-> review -> docs -> post to Linear.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.planner.actions import ActionType
from scripts.planner.layer_manager import LayerManager

if TYPE_CHECKING:
    from scripts.planner.state import DesignState


class RefactorPlanStateMachine:
    """State machine for refactor-plan workflow.

    Phases:
    - init: Initialize from ticket and paths
    - skeleton_analysis: Analyze folder structure and entry points
    - component_analysis: Analyze each component's internal structure
    - integration_mapping: Map dependencies and integration points
    - refactor_planning: Plan refactoring operations
    - review: Layer reviewer validates refactoring plan
    - generate_docs: Generate current/target/refactoring docs
    - post_to_linear: Post docs to Linear (handled by orchestrator)
    - complete: Done
    """

    def __init__(self, state: DesignState) -> None:
        """Initialize the refactor plan state machine.

        Args:
            state: The design state to manage.
        """
        self.state = state
        self.layer_manager = LayerManager(state)

    def next_action(self) -> None:
        """Determine and write next action based on current phase."""
        phase = self.state.phase

        if phase == "init":
            self._handle_init()
        elif phase == "skeleton_analysis":
            self._handle_skeleton_analysis()
        elif phase == "component_analysis":
            self._handle_component_analysis()
        elif phase == "integration_mapping":
            self._handle_integration_mapping()
        elif phase == "refactor_planning":
            self._handle_refactor_planning()
        elif phase == "review":
            self._handle_review()
        elif phase == "generate_docs":
            self._handle_generate_docs()
        elif phase == "post_to_linear":
            self._handle_post_to_linear()
        elif phase == "complete":
            self._handle_complete()
        elif phase == "error":
            # Error state already set - just write the error action without overwriting
            self.state.write_next_action(ActionType.ERROR, message="Error state")
        else:
            self._handle_error(f"Unknown phase: {phase}")

    def process_agent_output(self) -> None:
        """Process agent output and advance to next phase."""
        next_action = self.state.read_next_action()
        action_type = next_action.get("action", "")

        if action_type == ActionType.CALL_SKELETON_ANALYZER.value:
            self._process_skeleton_analyzer_output()
        elif action_type == ActionType.CALL_COMPONENT_ANALYZER.value:
            self._process_component_analyzer_output()
        elif action_type == ActionType.CALL_INTEGRATION_MAPPER.value:
            self._process_integration_mapper_output()
        elif action_type == ActionType.CALL_REFACTOR_PLANNER.value:
            self._process_refactor_planner_output()
        elif action_type == ActionType.CALL_LAYER_REVIEWER.value:
            self._process_layer_reviewer_output()
        elif action_type == ActionType.GENERATE_DOCS.value:
            self._process_generate_docs_output()
        elif action_type == ActionType.POST_TO_LINEAR.value:
            self._process_post_to_linear()
        else:
            self._handle_error(f"Unknown action type: {action_type}")

    def _handle_init(self) -> None:
        """Initialize - move to skeleton analysis."""
        self.state.phase = "skeleton_analysis"
        self.state.save()
        self.next_action()

    def _handle_skeleton_analysis(self) -> None:
        """Request skeleton analysis of folder structure."""
        self.state.write_next_action(ActionType.CALL_SKELETON_ANALYZER)
        root_unit = self.state.units.get("root")
        self.state.write_agent_input(
            {
                "paths": self.state.paths,
                "ticket": {
                    "id": self.state.ticket_id,
                    "title": self.state.title,
                    "description": root_unit.description if root_unit else "",
                },
            }
        )

    def _handle_component_analysis(self) -> None:
        """Request component analysis for each discovered component."""
        layer_1_units = self.layer_manager.get_units_at_layer(1)
        components = []
        for uid in layer_1_units:
            unit = self.state.units.get(uid)
            if unit:
                components.append(
                    {
                        "id": uid,
                        "description": unit.description,
                        "discovered_from": getattr(unit, "discovered_from", ""),
                        "entry_points": self.state.entry_points,
                    }
                )

        self.state.write_next_action(ActionType.CALL_COMPONENT_ANALYZER)
        self.state.write_agent_input(
            {
                "components": components,
                "ticket": {
                    "id": self.state.ticket_id,
                    "title": self.state.title,
                },
            }
        )

    def _handle_integration_mapping(self) -> None:
        """Request integration mapping across components."""
        analyzed_components = []
        for unit in self.state.units.values():
            patterns_used = getattr(unit, "patterns_used", [])
            if patterns_used:
                analyzed_components.append(
                    {
                        "component_id": unit.id,
                        "patterns_used": patterns_used,
                        "capabilities": {
                            "provided": [cap.to_dict() for cap in unit.provided_capabilities],
                            "expected": [cap.to_dict() for cap in unit.expected_capabilities],
                        },
                    }
                )

        self.state.write_next_action(ActionType.CALL_INTEGRATION_MAPPER)
        self.state.write_agent_input(
            {
                "analyzed_components": analyzed_components,
                "ticket": {
                    "id": self.state.ticket_id,
                    "title": self.state.title,
                },
            }
        )

    def _handle_refactor_planning(self) -> None:
        """Request refactoring plan based on integration map."""
        self.state.write_next_action(ActionType.CALL_REFACTOR_PLANNER)
        self.state.write_agent_input(
            {
                "dependency_graph": self.state.dependency_graph,
                "circular_dependencies": self.state.circular_dependencies,
                "integration_points": self.state.integration_points,
                "external_consumers": self.state.external_consumers,
                "refactoring_risks": self.state.refactoring_risks,
                "analyzed_components": [
                    {
                        "component_id": unit.id,
                        "description": unit.description,
                        "patterns_used": getattr(unit, "patterns_used", []),
                    }
                    for unit in self.state.units.values()
                ],
                "ticket": {
                    "id": self.state.ticket_id,
                    "title": self.state.title,
                },
            }
        )

    def _handle_review(self) -> None:
        """Request layer review of refactoring plan.

        Invokes the layer reviewer agent to validate the refactoring plan,
        ensuring operations are safe, dependencies are handled correctly,
        and migration steps are properly ordered.
        """
        self.state.write_next_action(ActionType.CALL_LAYER_REVIEWER)
        self.state.write_agent_input(
            {
                "review_context": "refactor_plan",
                "refactoring_operations": self.state.refactoring_operations,
                "migration_plan": self.state.migration_plan,
                "pattern_migrations": self.state.pattern_migrations,
                "breaking_changes_summary": self.state.breaking_changes_summary,
                "risk_assessment": self.state.risk_assessment,
                "integration_context": {
                    "dependency_graph": self.state.dependency_graph,
                    "circular_dependencies": self.state.circular_dependencies,
                    "integration_points": self.state.integration_points,
                    "external_consumers": self.state.external_consumers,
                    "refactoring_risks": self.state.refactoring_risks,
                },
                "components": [
                    {
                        "id": unit.id,
                        "description": unit.description,
                        "status": unit.status,
                        "patterns_used": getattr(unit, "patterns_used", []),
                    }
                    for unit in self.state.units.values()
                ],
                "ticket": {
                    "id": self.state.ticket_id,
                    "title": self.state.title,
                },
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
                "paths": self.state.paths,
                "current": {
                    "units": {uid: unit.to_dict() for uid, unit in self.state.units.items()},
                    "layers": self.state.branches["main"].layers,
                    "entry_points": self.state.entry_points,
                },
                "integration": {
                    "dependency_graph": self.state.dependency_graph,
                    "circular_dependencies": self.state.circular_dependencies,
                    "integration_points": self.state.integration_points,
                    "external_consumers": self.state.external_consumers,
                    "refactoring_risks": self.state.refactoring_risks,
                },
                "refactor_plan": {
                    "refactoring_operations": self.state.refactoring_operations,
                    "migration_plan": self.state.migration_plan,
                    "pattern_migrations": self.state.pattern_migrations,
                    "breaking_changes_summary": self.state.breaking_changes_summary,
                    "risk_assessment": self.state.risk_assessment,
                },
            }
        )

    def _handle_post_to_linear(self) -> None:
        """Signal to post docs to Linear."""
        self.state.write_next_action(ActionType.POST_TO_LINEAR)

    def _handle_complete(self) -> None:
        """Signal completion."""
        self.state.write_next_action(ActionType.COMPLETE)

    def _handle_error(self, message: str) -> None:
        """Signal error."""
        self.state.phase = "error"
        self.state.save()
        self.state.write_next_action(ActionType.ERROR, message=message)

    def _process_skeleton_analyzer_output(self) -> None:
        """Process skeleton analyzer results."""
        from scripts.planner.state import Unit

        output = self.state.read_agent_output()

        if output.get("status") != "success":
            self._handle_error(output.get("error", "Skeleton analysis failed"))
            return

        components = output.get("components", [])
        for comp in components:
            unit_id = comp["id"]
            self.state.units[unit_id] = Unit(
                id=unit_id,
                description=comp["description"],
                operation=comp.get("operation", "MODIFY"),
                status="pending",
                parent="root",
            )
            for ep in comp.get("entry_points", []):
                if ep not in self.state.entry_points:
                    self.state.entry_points.append(ep)

            if "root" in self.state.units:
                root_children = self.state.units["root"].children
                if unit_id not in root_children:
                    root_children.append(unit_id)

            layer_1 = self.state.branches["main"].layers.setdefault(1, [])
            if unit_id not in layer_1:
                layer_1.append(unit_id)

        self.state.add_history("skeleton_analysis", {"components_count": len(components)})
        self.state.phase = "component_analysis"
        self.state.save()
        self.next_action()

    def _process_component_analyzer_output(self) -> None:
        """Process component analyzer results."""
        from scripts.planner.state import Capability, Unit

        output = self.state.read_agent_output()

        if output.get("status") != "success":
            self._handle_error(output.get("error", "Component analysis failed"))
            return

        analyzed = output.get("analyzed_components", [])
        for comp_data in analyzed:
            unit_id = comp_data["component_id"]
            unit = self.state.units.get(unit_id)
            if not unit:
                continue

            patterns = comp_data.get("patterns_used", [])
            if patterns:
                unit.pattern = patterns[0].get("pattern")
                unit.pattern_category = patterns[0].get("pattern_category")
                unit.patterns_used = patterns

            capabilities = comp_data.get("capabilities", {})
            if "provided" in capabilities:
                unit.provided_capabilities = [
                    Capability.from_dict(cap) for cap in capabilities["provided"]
                ]
            if "expected" in capabilities:
                unit.expected_capabilities = [
                    Capability.from_dict(cap) for cap in capabilities["expected"]
                ]

            decomp = comp_data.get("decomposition_suggestion", {})
            if decomp.get("should_decompose"):
                new_sub_ids: list[str] = []
                for sub_spec in decomp.get("suggested_sub_units", []):
                    sub_id = f"{unit_id}.{len(unit.children) + 1}"
                    sub_unit = Unit(
                        id=sub_id,
                        description=sub_spec.get("description", ""),
                        operation="MODIFY",
                        status="pending",
                        parent=unit_id,
                    )
                    self.state.units[sub_id] = sub_unit
                    if sub_id not in unit.children:
                        unit.children.append(sub_id)
                    new_sub_ids.append(sub_id)
                self.layer_manager.add_units_to_layer(new_sub_ids)
                unit.status = "decomposed"
            else:
                unit.status = "atomic"

        self.state.add_history("component_analysis", {"analyzed_count": len(analyzed)})
        self.state.phase = "integration_mapping"
        self.state.save()
        self.next_action()

    def _process_integration_mapper_output(self) -> None:
        """Process integration mapper results."""
        output = self.state.read_agent_output()

        if output.get("status") != "success":
            self._handle_error(output.get("error", "Integration mapping failed"))
            return

        self.state.dependency_graph = output.get("dependency_graph", {})
        self.state.circular_dependencies = output.get("circular_dependencies", [])
        self.state.integration_points = output.get("integration_points", [])
        self.state.external_consumers = output.get("external_consumers", [])
        self.state.refactoring_risks = output.get("refactoring_risks", [])

        self.state.add_history(
            "integration_mapping",
            {
                "integration_points_count": len(self.state.integration_points),
                "circular_deps_count": len(self.state.circular_dependencies),
            },
        )
        self.state.phase = "refactor_planning"
        self.state.save()
        self.next_action()

    def _process_refactor_planner_output(self) -> None:
        """Process refactor planner results."""
        output = self.state.read_agent_output()

        if output.get("status") != "success":
            self._handle_error(output.get("error", "Refactor planning failed"))
            return

        self.state.refactoring_operations = output.get("refactoring_operations", [])
        self.state.migration_plan = output.get("migration_plan", {})
        self.state.pattern_migrations = output.get("pattern_migrations", [])
        self.state.breaking_changes_summary = output.get("breaking_changes_summary", {})
        self.state.risk_assessment = output.get("risk_assessment", {})

        self.state.add_history(
            "refactor_planning",
            {
                "operations_count": len(self.state.refactoring_operations),
                "phases_count": self.state.migration_plan.get("total_phases", 0),
            },
        )
        self.state.phase = "review"
        self.state.save()
        self.next_action()

    def _process_layer_reviewer_output(self) -> None:
        """Process layer reviewer results."""
        output = self.state.read_agent_output()

        if output.get("status") != "success":
            self._handle_error(output.get("error", "Layer review failed"))
            return

        self.state.add_history("review", {"reviewer_feedback": output.get("proceed_notes", "")})
        self.state.phase = "generate_docs"
        self.state.save()
        self.next_action()

    def _process_generate_docs_output(self) -> None:
        """Process documentation generation results."""
        output = self.state.read_agent_output()

        agent = output.get("agent")
        if agent not in ("design-formatter", "refactor-design-formatter"):
            self._handle_error(f"Expected formatter output, got: {agent}")
            return

        files_written = output.get("files_written", [])
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

    def _process_post_to_linear(self) -> None:
        """Process post to Linear completion."""
        self.state.add_history("post_to_linear", {"posted": True})
        self.state.phase = "complete"
        self.state.save()
        self.next_action()
