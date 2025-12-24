"""State management for planner and codegen state machines.

All communication happens through files in the workspace directory:
    .tmp/design/<ticket>/
    ├── state.yaml          # Main state (Python reads/writes)
    ├── next_action.yaml    # Python writes, orchestrator reads
    ├── agent_input.yaml    # Python writes, agent reads
    └── agent_output.yaml   # Agent writes, Python reads
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml

if TYPE_CHECKING:
    from typing import Any

    from scripts.planner.actions import ActionType


@dataclass
class Capability:
    """A capability that a unit expects from children or provides to parent.

    Capabilities are contracts. Each capability gets one test.
    """

    id: str
    description: str
    type: Literal["output", "behavior", "integration", "data", "guarantee"]
    # For expected: which child should provide this
    provider_unit_id: str | None = None
    # For cross-component: which units are involved
    involved_units: list[str] = field(default_factory=list)
    # Test that verifies this capability
    test_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "type": self.type,
        }
        if self.provider_unit_id:
            result["provider_unit_id"] = self.provider_unit_id
        if self.involved_units:
            result["involved_units"] = self.involved_units
        if self.test_id:
            result["test_id"] = self.test_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Capability:
        """Create from dictionary loaded from YAML."""
        return cls(
            id=data["id"],
            description=data["description"],
            type=data["type"],
            provider_unit_id=data.get("provider_unit_id"),
            involved_units=data.get("involved_units", []),
            test_id=data.get("test_id"),
        )


@dataclass
class BuildingBlockSpec:
    """Specification for a test building block.

    Each building block agent produces one component of the final test.
    The 14 building blocks are defined in .claude/agents/test-impl/.
    """

    block: str  # Agent name: suite-contract, shell-builder, etc.
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {
            "block": self.block,
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BuildingBlockSpec:
        """Create from dictionary loaded from YAML."""
        return cls(
            block=data["block"],
            params=data.get("params", {}),
        )


@dataclass
class TestPlan:
    """Plan for a test that verifies a capability.

    One test per capability. Component tests mapped by use-cases.
    Decomposes the test into building block specifications that
    test-implementor will invoke and assemble.
    """

    id: str
    capability_id: str
    use_case: str
    type: Literal["unit", "component", "integration", "script"]
    # Suite information from suite-contract
    suite_file: str | None = None
    suite_type: Literal["unit", "component", "integration", "script"] | None = None
    # Building blocks to invoke (in order)
    building_blocks: list[BuildingBlockSpec] = field(default_factory=list)
    # Test function metadata
    test_name: str | None = None
    is_async: bool = False
    fixtures: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    # Execution status
    status: Literal["planned", "generated", "passing", "failing"] = "planned"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {
            "id": self.id,
            "capability_id": self.capability_id,
            "use_case": self.use_case,
            "type": self.type,
            "status": self.status,
        }
        if self.suite_file:
            result["suite_file"] = self.suite_file
        if self.suite_type:
            result["suite_type"] = self.suite_type
        if self.building_blocks:
            result["building_blocks"] = [bb.to_dict() for bb in self.building_blocks]
        if self.test_name:
            result["test_name"] = self.test_name
        if self.is_async:
            result["is_async"] = self.is_async
        if self.fixtures:
            result["fixtures"] = self.fixtures
        if self.decorators:
            result["decorators"] = self.decorators
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestPlan:
        """Create from dictionary loaded from YAML."""
        building_blocks = [
            BuildingBlockSpec.from_dict(bb) for bb in data.get("building_blocks", [])
        ]
        return cls(
            id=data["id"],
            capability_id=data["capability_id"],
            use_case=data["use_case"],
            type=data["type"],
            suite_file=data.get("suite_file"),
            suite_type=data.get("suite_type"),
            building_blocks=building_blocks,
            test_name=data.get("test_name"),
            is_async=data.get("is_async", False),
            fixtures=data.get("fixtures", []),
            decorators=data.get("decorators", []),
            status=data.get("status", "planned"),
        )


@dataclass
class UnitPlan:
    """Plan for implementing a unit."""

    type: Literal["patch", "regenerate", "create", "delete"]
    target_file: str | None = None
    target_element: str | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    old_pattern: str | None = None
    new_pattern: str | None = None
    specification: dict[str, Any] | None = None
    cascading_changes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {"type": self.type}
        if self.target_file:
            result["target_file"] = self.target_file
        if self.target_element:
            result["target_element"] = self.target_element
        if self.changes:
            result["changes"] = self.changes
        if self.reason:
            result["reason"] = self.reason
        if self.old_pattern:
            result["old_pattern"] = self.old_pattern
        if self.new_pattern:
            result["new_pattern"] = self.new_pattern
        if self.specification:
            result["specification"] = self.specification
        if self.cascading_changes:
            result["cascading_changes"] = self.cascading_changes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnitPlan:
        """Create from dictionary loaded from YAML."""
        return cls(
            type=data["type"],
            target_file=data.get("target_file"),
            target_element=data.get("target_element"),
            changes=data.get("changes", []),
            reason=data.get("reason"),
            old_pattern=data.get("old_pattern"),
            new_pattern=data.get("new_pattern"),
            specification=data.get("specification"),
            cascading_changes=data.get("cascading_changes", []),
        )


@dataclass
class Unit:
    """A decomposition unit in the design tree."""

    id: str
    description: str
    operation: Literal["CREATE", "MODIFY", "DELETE"]
    status: Literal["pending", "atomic", "decomposed"] = "pending"
    pattern: str | None = None
    pattern_category: str | None = None
    children: list[str] = field(default_factory=list)
    parent: str | None = None
    plan: UnitPlan | None = None
    path_id: str | None = None
    confidence: float | None = None
    # Capabilities this unit EXPECTS from its children (contracts)
    expected_capabilities: list[Capability] = field(default_factory=list)
    # Capabilities this unit PROVIDES to its parent
    provided_capabilities: list[Capability] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "operation": self.operation,
            "status": self.status,
        }
        if self.pattern:
            result["pattern"] = self.pattern
        if self.pattern_category:
            result["pattern_category"] = self.pattern_category
        if self.children:
            result["children"] = self.children
        if self.parent:
            result["parent"] = self.parent
        if self.plan:
            result["plan"] = self.plan.to_dict()
        if self.path_id:
            result["path_id"] = self.path_id
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.expected_capabilities:
            result["expected_capabilities"] = [c.to_dict() for c in self.expected_capabilities]
        if self.provided_capabilities:
            result["provided_capabilities"] = [c.to_dict() for c in self.provided_capabilities]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Unit:
        """Create from dictionary loaded from YAML."""
        plan = None
        if data.get("plan"):
            plan = UnitPlan.from_dict(data["plan"])

        expected_caps = [Capability.from_dict(c) for c in data.get("expected_capabilities", [])]
        provided_caps = [Capability.from_dict(c) for c in data.get("provided_capabilities", [])]

        return cls(
            id=data["id"],
            description=data["description"],
            operation=data["operation"],
            status=data.get("status", "pending"),
            pattern=data.get("pattern"),
            pattern_category=data.get("pattern_category"),
            children=data.get("children", []),
            parent=data.get("parent"),
            plan=plan,
            path_id=data.get("path_id"),
            confidence=data.get("confidence"),
            expected_capabilities=expected_caps,
            provided_capabilities=provided_caps,
        )


@dataclass
class ExploredPath:
    """A tree-of-thought exploration path."""

    confidence: float
    rationale: str
    status: Literal["exploring", "selected", "pruned"]
    sub_units: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {
            "confidence": self.confidence,
            "rationale": self.rationale,
            "status": self.status,
            "sub_units": self.sub_units,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExploredPath:
        """Create from dictionary loaded from YAML."""
        return cls(
            confidence=data["confidence"],
            rationale=data["rationale"],
            status=data["status"],
            sub_units=data.get("sub_units", []),
        )


def summarize_plan(plan_data: dict[str, Any]) -> dict[str, Any]:
    """Create canonical summary of a plan for history tracking.

    Extracts key structural information (unit IDs, titles, descriptions)
    to enable semantic duplicate detection without exact text matching.

    Args:
        plan_data: Plan data from decomposer/refactorer output

    Returns:
        Canonical summary dict with units list
    """

    def summarize_specification(specification: Any) -> str:
        summary_text = ""
        if isinstance(specification, dict):
            purpose = specification.get("purpose", "")
            if isinstance(purpose, str):
                summary_text = purpose
            if not summary_text:
                location = specification.get("location", "")
                if isinstance(location, str):
                    summary_text = location
                if not summary_text and specification:
                    summary_text = str(specification)
        elif isinstance(specification, str):
            summary_text = specification
        return summary_text

    def summarize_units(units: list[dict[str, Any]]) -> list[dict[str, str]]:
        summaries: list[dict[str, str]] = []
        for unit in units:
            if not isinstance(unit, dict):
                continue
            unit_id = unit.get("id")
            if not isinstance(unit_id, str):
                unit_id = ""
            title = unit.get("title")
            if not isinstance(title, str) or not title:
                description = unit.get("description")
                title = description if isinstance(description, str) else ""
            description = unit.get("description", "")
            if not isinstance(description, str):
                description = ""
            summaries.append(
                {
                    "id": unit_id,
                    "title": title,
                    "description": description[:100],
                }
            )
        return summaries

    units: list[dict[str, Any]] = []

    paths = plan_data.get("paths", [])
    if isinstance(paths, list) and paths:
        for path in paths:
            if not isinstance(path, dict):
                continue
            sub_units = path.get("sub_units", [])
            if isinstance(sub_units, list):
                units.extend([unit for unit in sub_units if isinstance(unit, dict)])

    if not units:
        children = plan_data.get("children", [])
        if isinstance(children, list) and children:
            units.extend([unit for unit in children if isinstance(unit, dict)])

    if not units:
        changes = plan_data.get("changes", [])
        if isinstance(changes, list) and changes:
            for change in changes:
                if not isinstance(change, dict):
                    continue
                change_type = change.get("type")
                if change_type == "add":
                    unit = change.get("unit")
                    if isinstance(unit, dict):
                        units.append(unit)
                elif change_type == "update":
                    update_unit: dict[str, Any] = {"id": change.get("unit_id")}
                    if "title" in change:
                        update_unit["title"] = change.get("title")
                    if "description" in change:
                        update_unit["description"] = change.get("description")
                    if not update_unit.get("description"):
                        summary_text = summarize_specification(change.get("plan"))
                        if not summary_text:
                            summary_text = summarize_specification(change.get("specification"))
                        if summary_text:
                            update_unit["description"] = summary_text
                    units.append(update_unit)

    if not units and (plan_data.get("is_atomic") or plan_data.get("specification")):
        summary_text = summarize_specification(plan_data.get("specification", ""))
        unit_id = plan_data.get("unit_id")
        units.append(
            {
                "id": unit_id if isinstance(unit_id, str) else "",
                "description": summary_text,
            }
        )

    return {"units": summarize_units(units)}


@dataclass
class Branch:
    """A Tree-of-Thought branch with its own layer history.

    Each branch maintains independent layers, plan history, and can spawn
    sub-branches for nested exploration paths.
    """

    branch_id: str
    layers: dict[int, list[str]] = field(default_factory=dict)
    history: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    sub_branches: dict[str, Branch] = field(default_factory=dict)
    status: Literal["exploring", "selected", "pruned", "replanning"] = "exploring"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {
            "branch_id": self.branch_id,
            "status": self.status,
            "confidence": self.confidence,
        }
        if self.layers:
            result["layers"] = self.layers
        if self.history:
            result["history"] = self.history
        if self.sub_branches:
            result["sub_branches"] = {
                sub_id: sub_branch.to_dict() for sub_id, sub_branch in self.sub_branches.items()
            }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Branch:
        """Create from dictionary loaded from YAML."""
        # Recursively parse sub-branches
        sub_branches: dict[str, Branch] = {}
        for sub_id, sub_data in data.get("sub_branches", {}).items():
            sub_branches[sub_id] = cls.from_dict(sub_data)

        return cls(
            branch_id=data["branch_id"],
            layers=data.get("layers", {}),
            history=data.get("history", {}),
            sub_branches=sub_branches,
            status=data.get("status", "exploring"),
            confidence=data.get("confidence", 1.0),
        )


@dataclass
class ReviewComment:
    """A review comment for update-plan."""

    id: str
    author: str
    target_unit_id: str
    target_layer: int
    type: Literal["suggestion", "concern", "question", "approval"]
    content: str
    resolution: Literal["pending", "applied", "deferred", "rejected"] = "pending"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {
            "id": self.id,
            "author": self.author,
            "target_unit_id": self.target_unit_id,
            "target_layer": self.target_layer,
            "type": self.type,
            "content": self.content,
            "resolution": self.resolution,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewComment:
        """Create from dictionary loaded from YAML."""
        return cls(
            id=data["id"],
            author=data["author"],
            target_unit_id=data["target_unit_id"],
            target_layer=data["target_layer"],
            type=data["type"],
            content=data["content"],
            resolution=data.get("resolution", "pending"),
        )


@dataclass
class ExecutionFailure:
    """A failure during code generation."""

    unit_id: str
    category: str
    error: str
    blocks: list[str] = field(default_factory=list)
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {
            "unit_id": self.unit_id,
            "category": self.category,
            "error": self.error,
            "blocks": self.blocks,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionFailure:
        """Create from dictionary loaded from YAML."""
        return cls(
            unit_id=data["unit_id"],
            category=data["category"],
            error=data["error"],
            blocks=data.get("blocks", []),
            retry_count=data.get("retry_count", 0),
        )


@dataclass
class DesignState:
    """Complete state for a design workflow.

    All state is persisted to state.yaml in the workspace directory.
    Communication with orchestrator happens through additional YAML files.
    """

    # Workspace path
    workspace: Path

    # Metadata
    ticket_id: str
    title: str
    url: str = ""
    workflow: Literal["create-plan", "update-plan", "execute-plan", "refactor-plan"] = "create-plan"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # State Machine
    phase: str = "init"
    current_layer: int = 0
    review_target_layer: int | None = None
    iteration: int = 1

    # Unit Tree (with Tree-of-Thought branching)
    branches: dict[str, Branch] = field(
        default_factory=lambda: {"main": Branch(branch_id="main", layers={0: ["root"]})}
    )
    units: dict[str, Unit] = field(default_factory=dict)

    # Tree-of-Thought
    explored_paths: dict[str, dict[str, ExploredPath]] = field(default_factory=dict)
    branch_reports: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Capabilities and Tests
    # Test plans mapped by capability_id
    test_plans: dict[str, TestPlan] = field(default_factory=dict)

    # Review Comments
    comments: list[ReviewComment] = field(default_factory=list)

    # Execution State (for execute-plan)
    worktree_path: str | None = None
    branch_name: str | None = None
    base_branch: str = "main"
    file_groups: dict[str, list[str]] = field(default_factory=dict)
    layer_execution: dict[int, dict[str, Any]] = field(default_factory=dict)
    failures: list[ExecutionFailure] = field(default_factory=list)

    # PR info
    pr_url: str | None = None

    # History
    history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, workspace: Path) -> DesignState:
        """Load state from workspace/state.yaml.

        Args:
            workspace: Path to workspace directory

        Returns:
            Loaded DesignState

        Raises:
            FileNotFoundError: If state.yaml doesn't exist
        """
        state_path = workspace / "state.yaml"
        if not state_path.exists():
            msg = f"No state file at {state_path}"
            raise FileNotFoundError(msg)

        with state_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls._from_dict(workspace, data)

    def save(self) -> None:
        """Save state to workspace/state.yaml."""
        self.updated_at = datetime.now().isoformat()
        self.workspace.mkdir(parents=True, exist_ok=True)

        state_path = self.workspace / "state.yaml"
        with state_path.open("w", encoding="utf-8") as f:
            yaml.dump(
                self._to_dict(),
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

    def write_next_action(
        self,
        action_type: ActionType,
        **kwargs: str | int | float | bool | list[Any] | dict[str, Any] | None,
    ) -> None:
        """Write next action for orchestrator.

        Args:
            action_type: The action type to write
            **kwargs: Additional fields to include
        """
        data = {"action": action_type.value, **kwargs}
        action_path = self.workspace / "next_action.yaml"
        with action_path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def read_next_action(self) -> dict[str, Any]:
        """Read next action (for status/debug).

        Returns:
            Contents of next_action.yaml
        """
        action_path = self.workspace / "next_action.yaml"
        if not action_path.exists():
            return {}
        with action_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def write_agent_input(self, data: dict[str, Any], unit_id: str | None = None) -> None:
        """Write input for agent.

        Args:
            data: Data to write
            unit_id: Optional unit ID for per-unit input files
        """
        if unit_id:
            # Per-unit input file in inputs/ subdirectory
            inputs_dir = self.workspace / "inputs"
            inputs_dir.mkdir(exist_ok=True)
            input_path = inputs_dir / f"{unit_id}.yaml"
        else:
            # Legacy single input file
            input_path = self.workspace / "agent_input.yaml"
        with input_path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def write_agent_input_json(self, data: dict[str, Any]) -> None:
        """Write JSON input for agent."""
        input_path = self.workspace / "agent_input.json"
        with input_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def read_agent_output(self, unit_id: str | None = None) -> dict[str, Any]:
        """Read output from agent.

        Args:
            unit_id: Optional unit ID for per-unit output files

        Returns:
            Contents of the output file
        """
        if unit_id:
            # Per-unit output file in outputs/ subdirectory
            output_path = self.workspace / "outputs" / f"{unit_id}.yaml"
        else:
            # Legacy single output file
            output_path = self.workspace / "agent_output.yaml"
        if not output_path.exists():
            return {}
        with output_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def read_agent_output_json(self) -> dict[str, Any]:
        """Read JSON output from agent."""
        output_path = self.workspace / "agent_output.json"
        if not output_path.exists():
            return {}
        with output_path.open(encoding="utf-8") as f:
            return json.load(f) or {}

    def read_all_unit_outputs(self) -> list[dict[str, Any]]:
        """Read all per-unit output files from outputs/ directory.

        Returns:
            List of output dictionaries, one per unit
        """
        outputs_dir = self.workspace / "outputs"
        if not outputs_dir.exists():
            return []
        results = []
        for output_file in outputs_dir.glob("*.yaml"):
            with output_file.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                if data:
                    results.append(data)
        return results

    def clear_unit_io(self) -> None:
        """Clear inputs/ and outputs/ directories for next iteration."""
        for subdir in ["inputs", "outputs"]:
            dir_path = self.workspace / subdir
            if dir_path.exists():
                for f in dir_path.glob("*.yaml"):
                    f.unlink()

    def add_history(self, action: str, details: dict[str, Any] | None = None) -> None:
        """Add an entry to the history log.

        Args:
            action: Action name
            details: Optional details dict
        """
        self.history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": action,
                "details": details or {},
            }
        )

    def _to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        # Convert units
        units_dict = {uid: unit.to_dict() for uid, unit in self.units.items()}

        # Convert explored paths
        paths_dict: dict[str, dict[str, Any]] = {}
        for unit_id, paths in self.explored_paths.items():
            paths_dict[unit_id] = {path_id: path.to_dict() for path_id, path in paths.items()}

        # Convert comments
        comments_list = [c.to_dict() for c in self.comments]

        # Convert failures
        failures_list = [f.to_dict() for f in self.failures]

        # Convert test plans
        test_plans_dict = {cap_id: tp.to_dict() for cap_id, tp in self.test_plans.items()}

        # Convert branches
        branches_dict = {branch_id: branch.to_dict() for branch_id, branch in self.branches.items()}

        return {
            "ticket_id": self.ticket_id,
            "title": self.title,
            "url": self.url,
            "workflow": self.workflow,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "phase": self.phase,
            "current_layer": self.current_layer,
            "review_target_layer": self.review_target_layer,
            "iteration": self.iteration,
            "branches": branches_dict,
            "units": units_dict,
            "explored_paths": paths_dict,
            "test_plans": test_plans_dict,
            "comments": comments_list,
            "worktree_path": self.worktree_path,
            "branch_name": self.branch_name,
            "base_branch": self.base_branch,
            "file_groups": self.file_groups,
            "layer_execution": self.layer_execution,
            "failures": failures_list,
            "pr_url": self.pr_url,
            "history": self.history,
        }

    @classmethod
    def _from_dict(cls, workspace: Path, data: dict[str, Any]) -> DesignState:
        """Create from dictionary loaded from YAML.

        Args:
            workspace: Workspace path
            data: Dictionary from YAML

        Returns:
            DesignState instance
        """
        # Parse units
        units: dict[str, Unit] = {}
        for uid, unit_data in data.get("units", {}).items():
            units[uid] = Unit.from_dict(unit_data)

        # Parse explored paths
        explored_paths: dict[str, dict[str, ExploredPath]] = {}
        for unit_id, paths in data.get("explored_paths", {}).items():
            explored_paths[unit_id] = {
                path_id: ExploredPath.from_dict(path_data) for path_id, path_data in paths.items()
            }

        # Parse comments
        comments = [ReviewComment.from_dict(c) for c in data.get("comments", [])]

        # Parse failures
        failures = [ExecutionFailure.from_dict(f) for f in data.get("failures", [])]

        # Parse test plans
        test_plans: dict[str, TestPlan] = {}
        for cap_id, tp_data in data.get("test_plans", {}).items():
            test_plans[cap_id] = TestPlan.from_dict(tp_data)

        # Parse branches
        branches: dict[str, Branch] = {}
        # New format: deserialize branches
        for branch_id, branch_data in data["branches"].items():
            branches[branch_id] = Branch.from_dict(branch_data)

        if "main" not in branches:
            branches["main"] = Branch(branch_id="main", layers={0: ["root"]})

        return cls(
            workspace=workspace,
            ticket_id=data["ticket_id"],
            title=data["title"],
            url=data.get("url", ""),
            workflow=data.get("workflow", "create-plan"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            phase=data.get("phase", "init"),
            current_layer=data.get("current_layer", 0),
            review_target_layer=data.get("review_target_layer"),
            iteration=data.get("iteration", 1),
            branches=branches,
            units=units,
            explored_paths=explored_paths,
            test_plans=test_plans,
            comments=comments,
            worktree_path=data.get("worktree_path"),
            branch_name=data.get("branch_name"),
            base_branch=data.get("base_branch", "main"),
            file_groups=data.get("file_groups", {}),
            layer_execution=data.get("layer_execution", {}),
            failures=failures,
            pr_url=data.get("pr_url"),
            history=data.get("history", []),
        )
