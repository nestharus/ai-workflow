from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from spec_manager.schemas.task_status import (
    TaskImplementationStatusSchema,
    read_task_implementation_status_json,
    validate_status_transition,
    write_task_implementation_status_json,
)


def _create_planned_status() -> dict[str, object]:
    return {
        "task_id": "TASK-0001",
        "status": "planned",
        "repo_root": "/repo",
    }


def _create_in_progress_status() -> dict[str, object]:
    return {
        "task_id": "TASK-0001",
        "status": "in_progress",
        "started_at": "2024-01-01T00:00:00",
        "repo_root": "/repo",
    }


def _create_done_status() -> dict[str, object]:
    return {
        "task_id": "TASK-0001",
        "status": "done",
        "started_at": "2024-01-01T00:00:00",
        "finished_at": "2024-01-01T01:00:00",
        "repo_root": "/repo",
        "patch_sha256": "abc123",
        "applied_files": ["scripts/spec_manager/spec_manager/schemas/task_status.py"],
    }


def test_task_status_valid_planned() -> None:
    status = TaskImplementationStatusSchema.model_validate(_create_planned_status())
    assert status.status == "planned"


def test_task_status_valid_in_progress() -> None:
    status = TaskImplementationStatusSchema.model_validate(_create_in_progress_status())
    assert status.started_at == "2024-01-01T00:00:00"


def test_task_status_valid_done() -> None:
    status = TaskImplementationStatusSchema.model_validate(_create_done_status())
    assert status.patch_sha256 == "abc123"


def test_task_status_invalid_task_id() -> None:
    payload = _create_planned_status()
    payload["task_id"] = "TASK-1"
    with pytest.raises(ValidationError):
        TaskImplementationStatusSchema.model_validate(payload)


def test_task_status_invalid_status() -> None:
    payload = _create_planned_status()
    payload["status"] = "unknown"
    with pytest.raises(ValidationError):
        TaskImplementationStatusSchema.model_validate(payload)


def test_task_status_in_progress_missing_started_at() -> None:
    payload = _create_planned_status()
    payload["status"] = "in_progress"
    with pytest.raises(ValidationError):
        TaskImplementationStatusSchema.model_validate(payload)


def test_task_status_done_missing_timestamps() -> None:
    payload = _create_done_status()
    payload.pop("started_at")
    payload.pop("finished_at")
    with pytest.raises(ValidationError):
        TaskImplementationStatusSchema.model_validate(payload)


def test_task_status_done_missing_patch_sha256() -> None:
    payload = _create_done_status()
    payload["patch_sha256"] = ""
    with pytest.raises(ValidationError):
        TaskImplementationStatusSchema.model_validate(payload)


def test_validate_status_transition_valid_planned_to_in_progress() -> None:
    is_valid, error = validate_status_transition("planned", "in_progress")
    assert is_valid is True
    assert error == ""


def test_validate_status_transition_valid_in_progress_to_done() -> None:
    is_valid, error = validate_status_transition("in_progress", "done")
    assert is_valid is True
    assert error == ""


def test_validate_status_transition_valid_blocked_to_in_progress() -> None:
    is_valid, error = validate_status_transition("blocked", "in_progress")
    assert is_valid is True
    assert error == ""


def test_validate_status_transition_invalid_planned_to_done() -> None:
    is_valid, error = validate_status_transition("planned", "done")
    assert is_valid is False
    assert "Invalid transition" in error


def test_validate_status_transition_invalid_done_to_in_progress() -> None:
    is_valid, error = validate_status_transition("done", "in_progress")
    assert is_valid is False
    assert "Invalid transition" in error


def test_task_status_json_round_trip(fs) -> None:
    status = TaskImplementationStatusSchema.model_validate(_create_done_status())
    output_path = Path("/work/task_status.json")
    write_task_implementation_status_json(status, output_path)

    loaded = read_task_implementation_status_json(output_path)
    assert loaded.task_id == status.task_id
    assert loaded.status == status.status
