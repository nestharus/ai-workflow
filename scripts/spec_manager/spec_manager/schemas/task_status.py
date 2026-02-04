"""Schemas and helpers for implementation-phase task status artifacts.

Example:
    status = TaskImplementationStatusSchema(
        task_id="TASK-0001",
        status="in_progress",
        started_at="2024-01-01T00:00:00",
        repo_root="/repo",
    )
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .edge_list import TASK_ID_RE, _validate_iso8601


class TestResultSchema(BaseModel):
    """Capture test execution details."""

    ran: bool
    command: str
    exit_code: int
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None


class AuditResultSchema(BaseModel):
    """Capture audit verdict and issue count."""

    verdict: Literal["pass", "fail"]
    issues: int


class TaskImplementationStatusSchema(BaseModel):
    """Track implementation status for a task during execution phases."""

    task_id: str
    status: Literal["planned", "in_progress", "done", "blocked", "failed"]
    started_at: str | None = None
    finished_at: str | None = None
    repo_root: str
    patch_sha256: str = ""
    applied_files: list[str] = Field(default_factory=list)
    tests: TestResultSchema | None = None
    audit: AuditResultSchema | None = None

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
            TaskImplementationStatusSchema(
                task_id="TASK-0001",
                status="planned",
                repo_root="/repo",
            )
        """
        if not TASK_ID_RE.fullmatch(value):
            raise ValueError("task_id must match TASK-####")
        return value

    @field_validator("started_at", "finished_at")
    @classmethod
    def validate_timestamps(cls, value: str | None) -> str | None:
        """Validate ISO-8601 timestamps when provided.

        Args:
            value: ISO-8601 timestamp string or None.

        Returns:
            The validated timestamp string or None.

        Raises:
            ValueError: When the timestamp is invalid.

        Example:
            TaskImplementationStatusSchema(
                task_id="TASK-0001",
                status="planned",
                repo_root="/repo",
            )
        """
        if value is None:
            return value
        return _validate_iso8601(value)

    @model_validator(mode="after")
    def validate_status_requirements(self) -> TaskImplementationStatusSchema:
        """Enforce required fields based on status transitions.

        Returns:
            The validated TaskImplementationStatusSchema instance.

        Raises:
            ValueError: When required fields are missing for the status.

        Example:
            TaskImplementationStatusSchema(
                task_id="TASK-0001",
                status="done",
                started_at="2024-01-01T00:00:00",
                finished_at="2024-01-01T01:00:00",
                repo_root="/repo",
                patch_sha256="abc123",
            )
        """
        if self.status == "in_progress" and self.started_at is None:
            raise ValueError("started_at is required when status is in_progress")
        if self.status in {"done", "failed"} and (
            self.started_at is None or self.finished_at is None
        ):
            raise ValueError("started_at and finished_at are required when status is done/failed")
        if self.status == "done" and not self.patch_sha256:
            raise ValueError("patch_sha256 is required when status is done")
        return self


def validate_status_transition(old_status: str, new_status: str) -> tuple[bool, str]:
    """Validate status transitions against the task state machine.

    Args:
        old_status: Current status string.
        new_status: Desired status string.

    Returns:
        Tuple of (is_valid, error_message). When valid, error_message is empty.

    Example:
        validate_status_transition("planned", "in_progress")
    """
    allowed_statuses = {"planned", "in_progress", "done", "blocked", "failed"}
    if old_status not in allowed_statuses:
        return False, f"Unknown old status: {old_status}"
    if new_status not in allowed_statuses:
        return False, f"Unknown new status: {new_status}"

    transitions = {
        "planned": {"in_progress"},
        "in_progress": {"done", "failed", "blocked"},
        "blocked": {"in_progress"},
    }
    if new_status in transitions.get(old_status, set()):
        return True, ""
    return False, f"Invalid transition from {old_status} to {new_status}."


def write_task_implementation_status_json(
    status: TaskImplementationStatusSchema,
    output_path: Path,
) -> None:
    """Write a task implementation status JSON file to disk.

    Args:
        status: TaskImplementationStatusSchema instance to serialize.
        output_path: Destination file path.

    Example:
        write_task_implementation_status_json(status, Path("reports/task_status.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = status.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_task_implementation_status_json(input_path: Path) -> TaskImplementationStatusSchema:
    """Read and validate a task implementation status JSON file.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated TaskImplementationStatusSchema instance.

    Example:
        status = read_task_implementation_status_json(Path("reports/task_status.json"))
    """
    content = input_path.read_text(encoding="utf-8")
    return TaskImplementationStatusSchema.model_validate(json.loads(content))


__all__ = [
    "AuditResultSchema",
    "TaskImplementationStatusSchema",
    "TestResultSchema",
    "read_task_implementation_status_json",
    "validate_status_transition",
    "write_task_implementation_status_json",
]
