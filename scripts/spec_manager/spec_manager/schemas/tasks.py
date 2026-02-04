"""Schemas and helpers for task planning artifacts.

Example:
    task = TaskSchema(
        task_id="TASK-0001",
        title="Add task schemas",
        description="Define schemas and helpers for task planning outputs.",
        priority="p1",
        component="spec_manager",
        libraries=["LIB-0001"],
        covers=TaskCoversSchema(
            elements=["REQ-LIB-0001-0001"],
            edges=["EDGE-LIB-0001-LIB-0002"],
            decisions=["DEC-LIB-0001-0001"],
            gaps=["GAP-FOUNDATION"],
        ),
        acceptance_criteria=["Tests cover task schemas."],
        suggested_files=["scripts/spec_manager/spec_manager/schemas/tasks.py"],
        risk_notes="Coordinate with consumers of task.json outputs.",
        validation_notes="Run schema validation on sample tasks.",
        citations=["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        depends_on=["TASK-0002"],
    )
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from spec_manager.refinement.formats import parse_evidence_pointer

from .edge_list import EDGE_ID_RE, ELEMENT_ID_RE, LIB_ID_RE, _validate_iso8601
from .interface_contract import DECISION_ID_RE

TASK_ID_RE = re.compile(r"^TASK-\d{4}$")
GAP_ID_RE = re.compile(r"^GAP-[A-Z0-9-]+$")


class TaskCoversSchema(BaseModel):
    """Coverage metadata for task planning outputs.

    Attributes:
        elements: Element IDs covered by the task.
        edges: Edge IDs covered by the task.
        decisions: Decision IDs covered by the task.
        gaps: Gap identifiers covered by the task.

    Example:
        TaskCoversSchema(
            elements=["REQ-LIB-0001-0001"],
            edges=["EDGE-LIB-0001-LIB-0002"],
            decisions=["DEC-LIB-0001-0001"],
            gaps=["GAP-FOUNDATION"],
        )
    """

    elements: list[str] = Field(default_factory=list)
    edges: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    @field_validator("elements")
    @classmethod
    def validate_elements(cls, value: list[str]) -> list[str]:
        """Ensure element IDs reference REQ/FLOW/INV/DEC identifiers.

        Args:
            value: List[str] of element IDs.

        Returns:
            The validated list of element IDs.

        Raises:
            ValueError: When an element ID does not match the expected pattern.

        Example:
            TaskCoversSchema(elements=["REQ-LIB-0001-0001"])
        """
        for element_id in value:
            if not ELEMENT_ID_RE.fullmatch(element_id):
                raise ValueError(
                    "element IDs must match REQ-LIB-####-####, FLOW-LIB-####-##, "
                    "INV-LIB-####-####, or DEC-LIB-####-####"
                )
        return value

    @field_validator("edges")
    @classmethod
    def validate_edges(cls, value: list[str]) -> list[str]:
        """Ensure edge IDs match EDGE-LIB-####-LIB-#### format.

        Args:
            value: List[str] of edge IDs.

        Returns:
            The validated list of edge IDs.

        Raises:
            ValueError: When an edge ID does not match the expected format.

        Example:
            TaskCoversSchema(edges=["EDGE-LIB-0001-LIB-0002"])
        """
        for edge_id in value:
            if not EDGE_ID_RE.fullmatch(edge_id):
                raise ValueError("edge IDs must match EDGE-LIB-####-LIB-####")
        return value

    @field_validator("decisions")
    @classmethod
    def validate_decisions(cls, value: list[str]) -> list[str]:
        """Ensure decision IDs match DEC-LIB-####-#### format.

        Args:
            value: List[str] of decision IDs.

        Returns:
            The validated list of decision IDs.

        Raises:
            ValueError: When a decision ID does not match the expected format.

        Example:
            TaskCoversSchema(decisions=["DEC-LIB-0001-0001"])
        """
        for decision_id in value:
            if not DECISION_ID_RE.fullmatch(decision_id):
                raise ValueError("decision IDs must match DEC-LIB-####-####")
        return value

    @field_validator("gaps")
    @classmethod
    def validate_gaps(cls, value: list[str]) -> list[str]:
        """Ensure gap identifiers match GAP-... format.

        Args:
            value: List[str] of gap IDs.

        Returns:
            The validated list of gap IDs.

        Raises:
            ValueError: When a gap ID does not match the expected format.

        Example:
            TaskCoversSchema(gaps=["GAP-FOUNDATION"])
        """
        for gap_id in value:
            if not GAP_ID_RE.fullmatch(gap_id):
                raise ValueError("gap IDs must match GAP-[A-Z0-9-]+")
        return value


class TaskSchema(BaseModel):
    """Describe an individual task and its validation metadata.

    Attributes:
        task_id: Task identifier ("TASK-####").
        title: Short task title.
        description: Detailed task description.
        priority: Task priority ("p0", "p1", "p2").
        component: Architecture component name.
        libraries: Library IDs referenced by the task.
        covers: Coverage metadata for related entities.
        acceptance_criteria: Testable acceptance criteria statements.
        suggested_files: File paths to consider editing.
        risk_notes: Risk assessment notes.
        validation_notes: Validation guidance.
        citations: Evidence pointers supporting task context.
        depends_on: Task IDs that must be completed first.

    Example:
        TaskSchema(
            task_id="TASK-0001",
            title="Add task schemas",
            description="Define schemas and helpers for task planning outputs.",
            priority="p1",
            component="spec_manager",
            libraries=["LIB-0001"],
            covers=TaskCoversSchema(elements=["REQ-LIB-0001-0001"]),
            acceptance_criteria=["Tests cover task schemas."],
            suggested_files=["scripts/spec_manager/spec_manager/schemas/tasks.py"],
            risk_notes="Coordinate with consumers of task.json outputs.",
            validation_notes="Run schema validation on sample tasks.",
            citations=["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
            depends_on=["TASK-0002"],
        )
    """

    task_id: str
    title: str
    description: str
    priority: Literal["p0", "p1", "p2"]
    component: str
    libraries: list[str]
    covers: TaskCoversSchema
    acceptance_criteria: list[str]
    suggested_files: list[str] = Field(default_factory=list)
    risk_notes: str = ""
    validation_notes: str = ""
    citations: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        """Ensure task_id matches TASK-#### format.

        Args:
            value: Task identifier string.

        Returns:
            The validated task identifier.

        Raises:
            ValueError: When the task_id format is invalid.

        Example:
            TaskSchema(
                task_id="TASK-0001",
                title="Title",
                description="Details",
                priority="p1",
                component="spec_manager",
                libraries=["LIB-0001"],
                covers=TaskCoversSchema(),
                acceptance_criteria=["Criterion"],
            )
        """
        if not TASK_ID_RE.fullmatch(value):
            raise ValueError("task_id must match TASK-####")
        return value

    @field_validator("libraries")
    @classmethod
    def validate_libraries(cls, value: list[str]) -> list[str]:
        """Ensure library IDs match LIB-#### format.

        Args:
            value: List[str] of library identifiers.

        Returns:
            The validated list of library identifiers.

        Raises:
            ValueError: When a library ID is invalid.

        Example:
            TaskSchema(
                task_id="TASK-0001",
                title="Title",
                description="Details",
                priority="p1",
                component="spec_manager",
                libraries=["LIB-0001"],
                covers=TaskCoversSchema(),
                acceptance_criteria=["Criterion"],
            )
        """
        for lib_id in value:
            if not LIB_ID_RE.fullmatch(lib_id):
                raise ValueError("library IDs must match LIB-####")
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_acceptance_criteria(cls, value: list[str]) -> list[str]:
        """Ensure at least one acceptance criterion is present.

        Args:
            value: List[str] of acceptance criteria statements.

        Returns:
            The validated list of acceptance criteria.

        Raises:
            ValueError: When no acceptance criteria are provided.

        Example:
            TaskSchema(
                task_id="TASK-0001",
                title="Title",
                description="Details",
                priority="p1",
                component="spec_manager",
                libraries=["LIB-0001"],
                covers=TaskCoversSchema(),
                acceptance_criteria=["Criterion"],
            )
        """
        if not value:
            raise ValueError("acceptance_criteria must include at least one entry")
        return value

    @field_validator("citations")
    @classmethod
    def validate_citations(cls, value: list[str]) -> list[str]:
        """Validate evidence pointer strings.

        Args:
            value: List[str] of evidence pointers.

        Returns:
            The validated list of evidence pointers.

        Raises:
            ValueError: When an evidence pointer is invalid.

        Example:
            TaskSchema(
                task_id="TASK-0001",
                title="Title",
                description="Details",
                priority="p1",
                component="spec_manager",
                libraries=["LIB-0001"],
                covers=TaskCoversSchema(),
                acceptance_criteria=["Criterion"],
                citations=["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
            )
        """
        for pointer in value:
            if parse_evidence_pointer(pointer, allow_multi_hop=True) is None:
                raise ValueError("citations must be valid evidence pointers")
        return value

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on(cls, value: list[str]) -> list[str]:
        """Ensure dependency task IDs match TASK-#### format.

        Args:
            value: List[str] of dependency task IDs.

        Returns:
            The validated list of dependency IDs.

        Raises:
            ValueError: When a dependency task ID is invalid.

        Example:
            TaskSchema(
                task_id="TASK-0001",
                title="Title",
                description="Details",
                priority="p1",
                component="spec_manager",
                libraries=["LIB-0001"],
                covers=TaskCoversSchema(),
                acceptance_criteria=["Criterion"],
                depends_on=["TASK-0002"],
            )
        """
        for task_id in value:
            if not TASK_ID_RE.fullmatch(task_id):
                raise ValueError("depends_on must contain TASK-#### identifiers")
        return value


class TaskIndexEntrySchema(BaseModel):
    """Summarize a task entry in the task index.

    Attributes:
        task_id: Task identifier ("TASK-####").
        title: Task title.
        status: Task status ("planned", "in_progress", "done", "blocked", "failed").
        priority: Task priority ("p0", "p1", "p2").
        component: Architecture component name.
        libraries: Library IDs referenced by the task.
        covers: Coverage summary for related entities.
        depends_on: Task dependencies.

    Example:
        TaskIndexEntrySchema(
            task_id="TASK-0001",
            title="Add task schemas",
            status="planned",
            priority="p1",
            component="spec_manager",
            libraries=["LIB-0001"],
            covers=TaskCoversSchema(),
            depends_on=["TASK-0002"],
        )
    """

    task_id: str
    title: str
    status: Literal["planned", "in_progress", "done", "blocked", "failed"]
    priority: Literal["p0", "p1", "p2"]
    component: str
    libraries: list[str]
    covers: TaskCoversSchema
    depends_on: list[str] = Field(default_factory=list)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        """Ensure task_id matches TASK-#### format.

        Args:
            value: Task identifier string.

        Returns:
            The validated task identifier.

        Raises:
            ValueError: When the task_id format is invalid.

        Example:
            TaskIndexEntrySchema(
                task_id="TASK-0001",
                title="Title",
                status="planned",
                priority="p1",
                component="spec_manager",
                libraries=["LIB-0001"],
                covers=TaskCoversSchema(),
            )
        """
        if not TASK_ID_RE.fullmatch(value):
            raise ValueError("task_id must match TASK-####")
        return value

    @field_validator("libraries")
    @classmethod
    def validate_libraries(cls, value: list[str]) -> list[str]:
        """Ensure library IDs match LIB-#### format.

        Args:
            value: List[str] of library identifiers.

        Returns:
            The validated list of library identifiers.

        Raises:
            ValueError: When a library ID is invalid.

        Example:
            TaskIndexEntrySchema(
                task_id="TASK-0001",
                title="Title",
                status="planned",
                priority="p1",
                component="spec_manager",
                libraries=["LIB-0001"],
                covers=TaskCoversSchema(),
            )
        """
        for lib_id in value:
            if not LIB_ID_RE.fullmatch(lib_id):
                raise ValueError("library IDs must match LIB-####")
        return value

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on(cls, value: list[str]) -> list[str]:
        """Ensure dependency task IDs match TASK-#### format.

        Args:
            value: List[str] of dependency task IDs.

        Returns:
            The validated list of dependency IDs.

        Raises:
            ValueError: When a dependency task ID is invalid.

        Example:
            TaskIndexEntrySchema(
                task_id="TASK-0001",
                title="Title",
                status="planned",
                priority="p1",
                component="spec_manager",
                libraries=["LIB-0001"],
                covers=TaskCoversSchema(),
                depends_on=["TASK-0002"],
            )
        """
        for task_id in value:
            if not TASK_ID_RE.fullmatch(task_id):
                raise ValueError("depends_on must contain TASK-#### identifiers")
        return value


class TaskIndexSchema(BaseModel):
    """Capture the inventory of tasks for a workflow run.

    Attributes:
        run_id: Workflow run identifier.
        generated_at: ISO-8601 timestamp with time component.
        tasks: Task index entries.

    Example:
        TaskIndexSchema(
            run_id="run_001",
            generated_at="2024-01-01T00:00:00",
            tasks=[],
        )
    """

    run_id: str
    generated_at: str
    tasks: list[TaskIndexEntrySchema]

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        """Validate the generated_at timestamp as ISO-8601.

        Args:
            value: ISO-8601 timestamp string.

        Returns:
            The validated timestamp string.

        Raises:
            ValueError: When the timestamp is invalid.

        Example:
            TaskIndexSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                tasks=[],
            )
        """
        return _validate_iso8601(value)

    @field_validator("tasks")
    @classmethod
    def validate_task_ids_unique(
        cls, value: list[TaskIndexEntrySchema]
    ) -> list[TaskIndexEntrySchema]:
        """Ensure task IDs are unique within the index.

        Args:
            value: List[TaskIndexEntrySchema] entries.

        Returns:
            The validated list of task entries.

        Raises:
            ValueError: When duplicate task IDs are detected.

        Example:
            TaskIndexSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                tasks=[],
            )
        """
        seen: set[str] = set()
        duplicates: list[str] = []
        for task in value:
            if task.task_id in seen:
                duplicates.append(task.task_id)
            seen.add(task.task_id)
        if duplicates:
            raise ValueError("task_id values must be unique")
        return value


class PatchGraphSchema(BaseModel):
    """Describe a dependency graph of tasks.

    Attributes:
        run_id: Workflow run identifier.
        generated_at: ISO-8601 timestamp with time component.
        nodes: Task IDs included in the graph.
        edges: Dependency edges (from_task, to_task).

    Example:
        PatchGraphSchema(
            run_id="run_001",
            generated_at="2024-01-01T00:00:00",
            nodes=["TASK-0001"],
            edges=[("TASK-0001", "TASK-0002")],
        )
    """

    run_id: str
    generated_at: str
    nodes: list[str]
    edges: list[tuple[str, str]]

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        """Validate the generated_at timestamp as ISO-8601.

        Args:
            value: ISO-8601 timestamp string.

        Returns:
            The validated timestamp string.

        Raises:
            ValueError: When the timestamp is invalid.

        Example:
            PatchGraphSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                nodes=[],
                edges=[],
            )
        """
        return _validate_iso8601(value)

    @field_validator("nodes")
    @classmethod
    def validate_nodes(cls, value: list[str]) -> list[str]:
        """Ensure node IDs match TASK-#### format.

        Args:
            value: List[str] of task IDs.

        Returns:
            The validated list of task IDs.

        Raises:
            ValueError: When a node ID is invalid.

        Example:
            PatchGraphSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                nodes=["TASK-0001"],
                edges=[],
            )
        """
        for node_id in value:
            if not TASK_ID_RE.fullmatch(node_id):
                raise ValueError("node IDs must match TASK-####")
        return value

    @field_validator("edges")
    @classmethod
    def validate_edges(cls, value: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Ensure edge tuples contain valid TASK-#### identifiers.

        Args:
            value: List[tuple[str, str]] of dependency edges.

        Returns:
            The validated list of dependency edges.

        Raises:
            ValueError: When an edge entry is invalid.

        Example:
            PatchGraphSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                nodes=["TASK-0001", "TASK-0002"],
                edges=[("TASK-0001", "TASK-0002")],
            )
        """
        for edge in value:
            if len(edge) != 2:
                raise ValueError("edges must contain (from_task, to_task) tuples")
            source, target = edge
            if not TASK_ID_RE.fullmatch(source) or not TASK_ID_RE.fullmatch(target):
                raise ValueError("edge task IDs must match TASK-####")
        return value

    @model_validator(mode="after")
    def validate_edge_membership(self) -> PatchGraphSchema:
        """Ensure both endpoints of every edge are declared in nodes.

        Returns:
            The validated PatchGraphSchema instance.

        Raises:
            ValueError: When an edge references a task not declared in nodes.

        Example:
            PatchGraphSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                nodes=["TASK-0001", "TASK-0002"],
                edges=[("TASK-0001", "TASK-0002")],
            )
        """
        declared = set(self.nodes)
        undeclared: list[str] = []
        for source, target in self.edges:
            if source not in declared:
                undeclared.append(source)
            if target not in declared:
                undeclared.append(target)
        if undeclared:
            unique = sorted(set(undeclared))
            raise ValueError(f"edges reference undeclared nodes: {', '.join(unique)}")
        return self

    @model_validator(mode="after")
    def validate_dag_acyclic(self) -> PatchGraphSchema:
        """Ensure the dependency graph is acyclic.

        Returns:
            The validated PatchGraphSchema instance.

        Raises:
            ValueError: When cycles are detected in the dependency graph.

        Example:
            PatchGraphSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                nodes=["TASK-0001", "TASK-0002"],
                edges=[("TASK-0001", "TASK-0002")],
            )
        """
        is_valid, errors = validate_patch_graph_acyclic(self)
        if not is_valid:
            raise ValueError("; ".join(errors))
        return self


class TaskStatusSchema(BaseModel):
    """Track task lifecycle status for status.json artifacts.

    Attributes:
        task_id: Task identifier ("TASK-####").
        status: Task status ("planned", "in_progress", "done", "blocked", "failed").
        created_at: ISO-8601 timestamp when the task status was created.
        updated_at: ISO-8601 timestamp when the task status was last updated.
        task_hash: Hash of task.json content.
        notes: Status notes.

    Example:
        TaskStatusSchema(
            task_id="TASK-0001",
            status="planned",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            task_hash="abc123",
            notes="Awaiting kickoff",
        )
    """

    task_id: str
    status: Literal["planned", "in_progress", "done", "blocked", "failed"]
    created_at: str
    updated_at: str
    task_hash: str = ""
    notes: str = ""

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        """Ensure task_id matches TASK-#### format.

        Args:
            value: Task identifier string.

        Returns:
            The validated task identifier.

        Raises:
            ValueError: When the task_id format is invalid.

        Example:
            TaskStatusSchema(
                task_id="TASK-0001",
                status="planned",
                created_at="2024-01-01T00:00:00",
                updated_at="2024-01-01T00:00:00",
            )
        """
        if not TASK_ID_RE.fullmatch(value):
            raise ValueError("task_id must match TASK-####")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamps(cls, value: str) -> str:
        """Validate status timestamps as ISO-8601 strings.

        Args:
            value: ISO-8601 timestamp string.

        Returns:
            The validated timestamp string.

        Raises:
            ValueError: When the timestamp is invalid.

        Example:
            TaskStatusSchema(
                task_id="TASK-0001",
                status="planned",
                created_at="2024-01-01T00:00:00",
                updated_at="2024-01-01T00:00:00",
            )
        """
        return _validate_iso8601(value)


def write_task_json(task: TaskSchema, output_path: Path) -> None:
    """Write a task JSON file to disk.

    Args:
        task: TaskSchema instance to serialize.
        output_path: Destination file path.

    Example:
        write_task_json(task, Path("tasks/TASK-0001.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = task.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_task_json(input_path: Path) -> TaskSchema:
    """Read and validate a task JSON file.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated TaskSchema instance.

    Example:
        task = read_task_json(Path("tasks/TASK-0001.json"))
    """
    content = input_path.read_text(encoding="utf-8")
    return TaskSchema.model_validate(json.loads(content))


def write_task_index_json(index: TaskIndexSchema, output_path: Path) -> None:
    """Write a task index JSON file to disk.

    Args:
        index: TaskIndexSchema instance to serialize.
        output_path: Destination file path.

    Example:
        write_task_index_json(index, Path("reports/task_index.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = index.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_task_index_json(input_path: Path) -> TaskIndexSchema:
    """Read and validate a task index JSON file.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated TaskIndexSchema instance.

    Example:
        index = read_task_index_json(Path("reports/task_index.json"))
    """
    content = input_path.read_text(encoding="utf-8")
    return TaskIndexSchema.model_validate(json.loads(content))


def write_patch_graph_json(graph: PatchGraphSchema, output_path: Path) -> None:
    """Write a patch graph JSON file to disk.

    Args:
        graph: PatchGraphSchema instance to serialize.
        output_path: Destination file path.

    Example:
        write_patch_graph_json(graph, Path("reports/patch_graph.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = graph.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_patch_graph_json(input_path: Path) -> PatchGraphSchema:
    """Read and validate a patch graph JSON file.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated PatchGraphSchema instance.

    Example:
        graph = read_patch_graph_json(Path("reports/patch_graph.json"))
    """
    content = input_path.read_text(encoding="utf-8")
    return PatchGraphSchema.model_validate(json.loads(content))


def write_task_status_json(status: TaskStatusSchema, output_path: Path) -> None:
    """Write a task status JSON file to disk.

    Args:
        status: TaskStatusSchema instance to serialize.
        output_path: Destination file path.

    Example:
        write_task_status_json(status, Path("tasks/TASK-0001/status.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = status.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_task_status_json(input_path: Path) -> TaskStatusSchema:
    """Read and validate a task status JSON file.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated TaskStatusSchema instance.

    Example:
        status = read_task_status_json(Path("tasks/TASK-0001/status.json"))
    """
    content = input_path.read_text(encoding="utf-8")
    return TaskStatusSchema.model_validate(json.loads(content))


def write_task_markdown(task: TaskSchema, output_path: Path) -> None:
    """Write a human-readable task report in markdown.

    Args:
        task: TaskSchema instance to render.
        output_path: Destination markdown file path.

    Example:
        write_task_markdown(task, Path("tasks/TASK-0001.md"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _join(items: list[str]) -> str:
        """Join list values or return a dash when empty.

        Args:
            items: List[str] of strings to join.

        Returns:
            Joined string or "-" when empty.

        Example:
            _join(["a", "b"])
        """
        return ", ".join(items) if items else "-"

    def _escape_table(value: str) -> str:
        """Escape pipe characters for markdown table cells.

        Args:
            value: Raw table cell value.

        Returns:
            Escaped table cell value.

        Example:
            _escape_table("a|b")
        """
        return value.replace("|", "\\|")

    lines: list[str] = [
        "# Task",
        "",
        "## Title",
        "",
        _escape_table(f"{task.task_id} - {task.title}"),
        "",
        "## Description",
        "",
        task.description or "-",
        "",
        "## Priority",
        "",
        task.priority,
        "",
        "## Component",
        "",
        task.component or "-",
        "",
        "## Libraries",
        "",
        _escape_table(_join(task.libraries)),
        "",
        "## Coverage",
        "",
        "| Type | IDs |",
        "| --- | --- |",
        f"| Elements | {_escape_table(_join(task.covers.elements))} |",
        f"| Edges | {_escape_table(_join(task.covers.edges))} |",
        f"| Decisions | {_escape_table(_join(task.covers.decisions))} |",
        f"| Gaps | {_escape_table(_join(task.covers.gaps))} |",
        "",
        "## Acceptance Criteria",
        "",
    ]

    if task.acceptance_criteria:
        lines.extend([f"- {criterion}" for criterion in task.acceptance_criteria])
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Suggested Files",
            "",
        ]
    )
    if task.suggested_files:
        lines.extend([f"- {path}" for path in task.suggested_files])
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Dependencies",
            "",
            "| Depends On |",
            "| --- |",
        ]
    )
    if task.depends_on:
        for dependency in task.depends_on:
            lines.append(f"| {_escape_table(dependency)} |")
    else:
        lines.append("| None |")

    lines.extend(
        [
            "",
            "## Risk Notes",
            "",
            task.risk_notes or "-",
            "",
            "## Validation Notes",
            "",
            task.validation_notes or "-",
            "",
            "## Citations",
            "",
        ]
    )

    if task.citations:
        lines.extend([f"- {citation}" for citation in task.citations])
    else:
        lines.append("- None")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_task_index_markdown(index: TaskIndexSchema, output_path: Path) -> None:
    """Write a human-readable task index report in markdown.

    Args:
        index: TaskIndexSchema instance to render.
        output_path: Destination markdown file path.

    Example:
        write_task_index_markdown(index, Path("reports/task_index.md"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _join(items: list[str]) -> str:
        """Join list values or return a dash when empty.

        Args:
            items: List[str] of strings to join.

        Returns:
            Joined string or "-" when empty.

        Example:
            _join(["a", "b"])
        """
        return ", ".join(items) if items else "-"

    def _escape_table(value: str) -> str:
        """Escape pipe characters for markdown table cells.

        Args:
            value: Raw table cell value.

        Returns:
            Escaped table cell value.

        Example:
            _escape_table("a|b")
        """
        return value.replace("|", "\\|")

    status_values = ["planned", "in_progress", "done", "blocked", "failed"]
    priority_values = ["p0", "p1", "p2"]
    status_counts = {status: 0 for status in status_values}
    priority_counts = {priority: 0 for priority in priority_values}

    for task in index.tasks:
        status_counts[task.status] += 1
        priority_counts[task.priority] += 1

    status_summary = ", ".join(f"{key}={value}" for key, value in status_counts.items())
    priority_summary = ", ".join(f"{key}={value}" for key, value in priority_counts.items())

    lines: list[str] = [
        "# Task Index",
        "",
        "## Metadata",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Run ID | {index.run_id} |",
        f"| Generated At | {index.generated_at} |",
        "",
        "## Summary",
        "",
        f"- Total Tasks: {len(index.tasks)}",
        f"- By Status: {status_summary}",
        f"- By Priority: {priority_summary}",
        "",
        "## Tasks",
        "",
        "| Task ID | Title | Component | Status | Priority | Dependencies |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for task in index.tasks:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table(task.task_id),
                    _escape_table(task.title),
                    _escape_table(task.component),
                    task.status,
                    task.priority,
                    _escape_table(_join(task.depends_on)),
                ]
            )
            + " |"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_patch_graph_acyclic(graph: PatchGraphSchema) -> tuple[bool, list[str]]:
    """Validate that a patch graph is acyclic.

    Args:
        graph: PatchGraphSchema instance to validate.

    Returns:
        Tuple[bool, list[str]] indicating success and any error messages.

    Example:
        is_valid, errors = validate_patch_graph_acyclic(graph)
    """
    nodes: set[str] = set(graph.nodes)

    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    in_degree: dict[str, int] = {node: 0 for node in nodes}

    for source, target in graph.edges:
        adjacency.setdefault(source, []).append(target)
        in_degree.setdefault(source, 0)
        in_degree[target] = in_degree.get(target, 0) + 1

    queue = [node for node, degree in in_degree.items() if degree == 0]
    ordered: list[str] = []

    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for target in adjacency.get(node, []):
            in_degree[target] -= 1
            if in_degree[target] == 0:
                queue.append(target)

    if len(ordered) == len(in_degree):
        return True, []

    cycles = _find_patch_graph_cycles(adjacency)
    if cycles:
        errors = [f"Cycle detected: {' -> '.join(cycle)}" for cycle in cycles]
    else:
        remaining = sorted(set(in_degree) - set(ordered))
        errors = [f"Cycle detected among tasks: {', '.join(remaining)}"]
    return False, errors


def _find_patch_graph_cycles(adjacency: dict[str, list[str]]) -> list[list[str]]:
    """Find dependency cycles in a patch graph adjacency list.

    Args:
        adjacency: Dict[str, list[str]] adjacency list for task IDs.

    Returns:
        List of cycles, where each cycle is a list of task IDs.

    Example:
        cycles = _find_patch_graph_cycles({"TASK-0001": ["TASK-0002"]})
    """
    visited: set[str] = set()
    rec_stack: set[str] = set()
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)

        for target in adjacency.get(node, []):
            if target not in visited:
                dfs(target, [*path, target])
            elif target in rec_stack and target in path:
                cycle_start = path.index(target)
                cycles.append([*path[cycle_start:], target])

        rec_stack.remove(node)

    for node in adjacency:
        if node not in visited:
            dfs(node, [node])

    return cycles


def validate_element_coverage(
    tasks: list[TaskSchema],
    required_elements: set[str],
) -> tuple[bool, list[str]]:
    """Validate that all required elements are covered by tasks.

    Args:
        tasks: List[TaskSchema] to inspect.
        required_elements: Set[str] of required element IDs.

    Returns:
        Tuple[bool, list[str]] indicating success and any error messages.

    Example:
        is_valid, errors = validate_element_coverage(tasks, {"REQ-LIB-0001-0001"})
    """
    covered: set[str] = set()
    for task in tasks:
        covered.update(task.covers.elements)

    missing = sorted(required_elements - covered)
    if not missing:
        return True, []

    errors = [f"Missing element coverage for '{element_id}'." for element_id in missing]
    return False, errors


def validate_edge_coverage(
    tasks: list[TaskSchema],
    required_edges: set[str],
) -> tuple[bool, list[str]]:
    """Validate that all required edges are covered by tasks.

    Args:
        tasks: List[TaskSchema] to inspect.
        required_edges: Set[str] of required edge IDs.

    Returns:
        Tuple[bool, list[str]] indicating success and any error messages.

    Example:
        is_valid, errors = validate_edge_coverage(tasks, {"EDGE-LIB-0001-LIB-0002"})
    """
    covered: set[str] = set()
    for task in tasks:
        covered.update(task.covers.edges)

    missing = sorted(required_edges - covered)
    if not missing:
        return True, []

    errors = [f"Missing edge coverage for '{edge_id}'." for edge_id in missing]
    return False, errors


def validate_decision_gap_coverage(
    tasks: list[TaskSchema],
    required_decisions: set[str],
    required_gaps: set[str],
) -> tuple[bool, list[str]]:
    """Validate that required decisions and gaps are covered by tasks.

    Args:
        tasks: List[TaskSchema] to inspect.
        required_decisions: Set[str] of required decision IDs.
        required_gaps: Set[str] of required gap IDs.

    Returns:
        Tuple[bool, list[str]] indicating success and any error messages.

    Example:
        is_valid, errors = validate_decision_gap_coverage(
            tasks,
            {"DEC-LIB-0001-0001"},
            {"GAP-FOUNDATION"},
        )
    """
    covered_decisions: set[str] = set()
    covered_gaps: set[str] = set()
    for task in tasks:
        covered_decisions.update(task.covers.decisions)
        covered_gaps.update(task.covers.gaps)

    errors: list[str] = []
    missing_decisions = sorted(required_decisions - covered_decisions)
    missing_gaps = sorted(required_gaps - covered_gaps)

    for decision_id in missing_decisions:
        errors.append(f"Missing decision coverage for '{decision_id}'.")
    for gap_id in missing_gaps:
        errors.append(f"Missing gap coverage for '{gap_id}'.")

    return not errors, errors


def validate_acceptance_criteria(tasks: list[TaskSchema]) -> tuple[bool, list[str]]:
    """Validate that tasks include verifiable acceptance criteria.

    Args:
        tasks: List[TaskSchema] to inspect.

    Returns:
        Tuple[bool, list[str]] indicating success and any error messages.

    Example:
        is_valid, errors = validate_acceptance_criteria(tasks)
    """
    keywords = ["test", "log", "output", "file", "created", "returns", "validates"]
    errors: list[str] = []

    for task in tasks:
        if not task.acceptance_criteria:
            errors.append(f"Task '{task.task_id}' is missing acceptance criteria.")
            continue
        has_signal = False
        for criterion in task.acceptance_criteria:
            lowered = criterion.lower()
            if any(keyword in lowered for keyword in keywords):
                has_signal = True
                break
        if not has_signal:
            errors.append(f"Task '{task.task_id}' has weak acceptance criteria.")

    return not errors, errors


__all__ = [
    "GAP_ID_RE",
    "TASK_ID_RE",
    "PatchGraphSchema",
    "TaskCoversSchema",
    "TaskIndexEntrySchema",
    "TaskIndexSchema",
    "TaskSchema",
    "TaskStatusSchema",
    "read_patch_graph_json",
    "read_task_index_json",
    "read_task_json",
    "read_task_status_json",
    "validate_acceptance_criteria",
    "validate_decision_gap_coverage",
    "validate_edge_coverage",
    "validate_element_coverage",
    "validate_patch_graph_acyclic",
    "write_patch_graph_json",
    "write_task_index_json",
    "write_task_index_markdown",
    "write_task_json",
    "write_task_markdown",
    "write_task_status_json",
]
