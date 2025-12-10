"""Tests for sandbox protocol serialization."""

from __future__ import annotations

import json

import pytest

from scripts.servers.sandbox.protocol import (
    CancelRequest,
    ConflictResponse,
    ErrorResponse,
    MergeRequest,
    ProgressResponse,
    QueuedResponse,
    RebaseRequest,
    StatusRequest,
    SuccessResponse,
    parse_request,
    parse_response,
)


class TestRebaseRequest:
    """Tests for RebaseRequest."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        request = RebaseRequest(
            branch="feature-x",
            target="main",
            request_id="test-id",
        )

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["command"] == "rebase"
        assert data["branch"] == "feature-x"
        assert data["target"] == "main"
        assert data["request_id"] == "test-id"

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "command": "rebase",
            "branch": "feature-x",
            "target": "main",
            "request_id": "test-id",
        }

        request = RebaseRequest.from_dict(data)

        assert request.branch == "feature-x"
        assert request.target == "main"
        assert request.request_id == "test-id"

    def test_auto_generates_request_id(self) -> None:
        """Test that request_id is auto-generated if not provided."""
        request = RebaseRequest(branch="feature-x", target="main")

        assert request.request_id is not None
        assert len(request.request_id) > 0


class TestMergeRequest:
    """Tests for MergeRequest."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        request = MergeRequest(
            branch="feature-x",
            target="main",
            request_id="test-id",
        )

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["command"] == "merge"
        assert data["branch"] == "feature-x"
        assert data["target"] == "main"

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "command": "merge",
            "branch": "feature-x",
            "target": "main",
            "request_id": "test-id",
        }

        request = MergeRequest.from_dict(data)

        assert request.branch == "feature-x"
        assert request.target == "main"
        assert request.request_id == "test-id"


class TestStatusRequest:
    """Tests for StatusRequest."""

    def test_serialization_with_request_id(self) -> None:
        """Test serialization with specific request ID."""
        request = StatusRequest(request_id="test-id")

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["command"] == "status"
        assert data["request_id"] == "test-id"

    def test_serialization_without_request_id(self) -> None:
        """Test serialization without request ID (all statuses)."""
        request = StatusRequest()

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["command"] == "status"
        assert data["request_id"] is None


class TestCancelRequest:
    """Tests for CancelRequest."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        request = CancelRequest(request_id="test-id")

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["command"] == "cancel"
        assert data["request_id"] == "test-id"


class TestSuccessResponse:
    """Tests for SuccessResponse."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        response = SuccessResponse(
            request_id="test-id",
            result={"message": "done"},
        )

        json_str = response.to_json()
        data = json.loads(json_str)

        assert data["status"] == "success"
        assert data["request_id"] == "test-id"
        assert data["result"] == {"message": "done"}

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "status": "success",
            "request_id": "test-id",
            "result": {"key": "value"},
        }

        response = SuccessResponse.from_dict(data)

        assert response.request_id == "test-id"
        assert response.result == {"key": "value"}


class TestConflictResponse:
    """Tests for ConflictResponse."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        response = ConflictResponse(
            request_id="test-id",
            files=["file1.py", "file2.py"],
        )

        json_str = response.to_json()
        data = json.loads(json_str)

        assert data["status"] == "conflict"
        assert data["request_id"] == "test-id"
        assert data["files"] == ["file1.py", "file2.py"]

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "status": "conflict",
            "request_id": "test-id",
            "files": ["file1.py", "file2.py"],
        }

        response = ConflictResponse.from_dict(data)

        assert response.request_id == "test-id"
        assert response.files == ["file1.py", "file2.py"]

    def test_from_dict_null_files_defaults_to_empty_list(self) -> None:
        """Test that null files defaults to empty list."""
        data = {
            "status": "conflict",
            "request_id": "test-id",
            "files": None,
        }

        response = ConflictResponse.from_dict(data)

        assert response.files == []

    def test_from_dict_missing_files_defaults_to_empty_list(self) -> None:
        """Test that missing files defaults to empty list."""
        data = {
            "status": "conflict",
            "request_id": "test-id",
        }

        response = ConflictResponse.from_dict(data)

        assert response.files == []

    def test_from_dict_invalid_files_type_raises_error(self) -> None:
        """Test that non-list files raises ValueError."""
        data = {
            "status": "conflict",
            "request_id": "test-id",
            "files": "not-a-list",
        }

        with pytest.raises(ValueError, match="Invalid 'files' in conflict response"):
            ConflictResponse.from_dict(data)


class TestQueuedResponse:
    """Tests for QueuedResponse."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        response = QueuedResponse(
            request_id="test-id",
            position=3,
        )

        json_str = response.to_json()
        data = json.loads(json_str)

        assert data["status"] == "queued"
        assert data["request_id"] == "test-id"
        assert data["position"] == 3

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "status": "queued",
            "request_id": "test-id",
            "position": 3,
        }

        response = QueuedResponse.from_dict(data)

        assert response.request_id == "test-id"
        assert response.position == 3


class TestProgressResponse:
    """Tests for ProgressResponse."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        response = ProgressResponse(
            request_id="test-id",
            message="Rebasing...",
        )

        json_str = response.to_json()
        data = json.loads(json_str)

        assert data["status"] == "in_progress"
        assert data["request_id"] == "test-id"
        assert data["message"] == "Rebasing..."

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "status": "in_progress",
            "request_id": "test-id",
            "message": "Rebasing...",
        }

        response = ProgressResponse.from_dict(data)

        assert response.request_id == "test-id"
        assert response.message == "Rebasing..."


class TestErrorResponse:
    """Tests for ErrorResponse."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        response = ErrorResponse(
            request_id="test-id",
            message="Something went wrong",
        )

        json_str = response.to_json()
        data = json.loads(json_str)

        assert data["status"] == "error"
        assert data["request_id"] == "test-id"
        assert data["message"] == "Something went wrong"

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "status": "error",
            "request_id": "test-id",
            "message": "Something went wrong",
        }

        response = ErrorResponse.from_dict(data)

        assert response.request_id == "test-id"
        assert response.message == "Something went wrong"


class TestParseRequest:
    """Tests for parse_request function."""

    def test_parse_rebase_request(self) -> None:
        """Parse a rebase request."""
        data = json.dumps(
            {
                "command": "rebase",
                "branch": "feature-x",
                "target": "main",
                "request_id": "test-id",
            }
        )

        request = parse_request(data)

        assert isinstance(request, RebaseRequest)
        assert request.branch == "feature-x"
        assert request.target == "main"

    def test_parse_merge_request(self) -> None:
        """Parse a merge request."""
        data = json.dumps(
            {
                "command": "merge",
                "branch": "feature-x",
                "target": "main",
                "request_id": "test-id",
            }
        )

        request = parse_request(data)

        assert isinstance(request, MergeRequest)

    def test_parse_status_request(self) -> None:
        """Parse a status request."""
        data = json.dumps(
            {
                "command": "status",
                "request_id": "test-id",
            }
        )

        request = parse_request(data)

        assert isinstance(request, StatusRequest)

    def test_parse_cancel_request(self) -> None:
        """Parse a cancel request."""
        data = json.dumps(
            {
                "command": "cancel",
                "request_id": "test-id",
            }
        )

        request = parse_request(data)

        assert isinstance(request, CancelRequest)

    def test_invalid_json_raises_error(self) -> None:
        """Raise ValueError for invalid JSON."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_request("not json")

    def test_unknown_command_raises_error(self) -> None:
        """Raise ValueError for unknown command."""
        data = json.dumps({"command": "unknown"})

        with pytest.raises(ValueError, match="Unknown command"):
            parse_request(data)

    def test_non_object_json_raises_error(self) -> None:
        """Raise TypeError when JSON is not an object."""
        with pytest.raises(TypeError, match="expected JSON object"):
            parse_request('"just a string"')

        with pytest.raises(TypeError, match="expected JSON object"):
            parse_request("[1, 2, 3]")

    def test_missing_command_raises_error(self) -> None:
        """Raise ValueError when command field is missing."""
        data = json.dumps({"branch": "feature", "target": "main"})
        with pytest.raises(ValueError, match="Missing required field: 'command'"):
            parse_request(data)

    def test_missing_required_field_raises_error(self) -> None:
        """Raise ValueError when required fields are missing."""
        # Rebase missing 'branch'
        data = json.dumps({"command": "rebase", "target": "main"})
        with pytest.raises(ValueError, match="Missing 'branch' in rebase request"):
            parse_request(data)

        # Merge missing 'target'
        data = json.dumps({"command": "merge", "branch": "feature"})
        with pytest.raises(ValueError, match="Missing 'target' in merge request"):
            parse_request(data)

        # Cancel missing 'request_id'
        data = json.dumps({"command": "cancel"})
        with pytest.raises(ValueError, match="Missing 'request_id' in cancel request"):
            parse_request(data)


class TestParseResponse:
    """Tests for parse_response function."""

    def test_parse_success_response(self) -> None:
        """Parse a success response."""
        data = json.dumps(
            {
                "status": "success",
                "request_id": "test-id",
                "result": {},
            }
        )

        response = parse_response(data)

        assert isinstance(response, SuccessResponse)

    def test_parse_conflict_response(self) -> None:
        """Parse a conflict response."""
        data = json.dumps(
            {
                "status": "conflict",
                "request_id": "test-id",
                "files": ["file.py"],
            }
        )

        response = parse_response(data)

        assert isinstance(response, ConflictResponse)

    def test_parse_queued_response(self) -> None:
        """Parse a queued response."""
        data = json.dumps(
            {
                "status": "queued",
                "request_id": "test-id",
                "position": 1,
            }
        )

        response = parse_response(data)

        assert isinstance(response, QueuedResponse)

    def test_parse_progress_response(self) -> None:
        """Parse a progress response."""
        data = json.dumps(
            {
                "status": "in_progress",
                "request_id": "test-id",
                "message": "working",
            }
        )

        response = parse_response(data)

        assert isinstance(response, ProgressResponse)

    def test_parse_error_response(self) -> None:
        """Parse an error response."""
        data = json.dumps(
            {
                "status": "error",
                "request_id": "test-id",
                "message": "failed",
            }
        )

        response = parse_response(data)

        assert isinstance(response, ErrorResponse)

    def test_invalid_json_raises_error(self) -> None:
        """Raise ValueError for invalid JSON."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_response("not json")

    def test_unknown_status_raises_error(self) -> None:
        """Raise ValueError for unknown status."""
        data = json.dumps({"status": "unknown", "request_id": "test"})

        with pytest.raises(ValueError, match="Unknown status"):
            parse_response(data)

    def test_non_object_json_raises_error(self) -> None:
        """Raise TypeError when JSON is not an object."""
        with pytest.raises(TypeError, match="expected JSON object"):
            parse_response('"just a string"')

        with pytest.raises(TypeError, match="expected JSON object"):
            parse_response("[1, 2, 3]")

    def test_missing_status_raises_error(self) -> None:
        """Raise ValueError when status field is missing."""
        data = json.dumps({"request_id": "test-id", "result": {}})
        with pytest.raises(ValueError, match="Missing required field: 'status'"):
            parse_response(data)

    def test_missing_required_field_raises_error(self) -> None:
        """Raise ValueError when required fields are missing."""
        # Success missing 'request_id'
        data = json.dumps({"status": "success", "result": {}})
        with pytest.raises(ValueError, match="Missing 'request_id' in success response"):
            parse_response(data)

        # Queued missing 'position'
        data = json.dumps({"status": "queued", "request_id": "test"})
        with pytest.raises(ValueError, match="Missing 'position' in queued response"):
            parse_response(data)
