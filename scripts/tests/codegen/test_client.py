"""Tests for scripts/codegen/client.py error handling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.codegen.client import (
    init_command,
    next_command,
    process_command,
    status_command,
)


class TestInitCommandErrorHandling:
    """Tests for init_command error handling."""

    def test_init_command_returns_json_error_on_missing_state_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that init_command returns JSON error when state.yaml is missing."""
        result = init_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "error" in output
        assert output["error_type"] == "FileNotFoundError"
        assert output["error_category"] == "validation"

    def test_init_command_returns_json_error_on_load_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that init_command returns JSON error on DesignState.load exception."""
        with patch(
            "scripts.planner.state.DesignState.load",
            side_effect=ValueError("Test error"),
        ):
            result = init_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "Test error" in output["error"]
        assert output["error_type"] == "ValueError"
        assert output["error_category"] == "validation"

    def test_init_command_returns_json_error_on_save_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that init_command returns JSON error when save fails."""
        mock_state = MagicMock()
        mock_state.save.side_effect = OSError("Cannot write")
        mock_state.ticket_id = "TEST-123"

        with patch(
            "scripts.planner.state.DesignState.load",
            return_value=mock_state,
        ):
            result = init_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "Cannot write" in output["error"]
        assert output["error_type"] == "OSError"  # IOError is alias for OSError
        assert output["error_category"] == "system"

    def test_init_command_success_returns_json_with_ok_true(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that successful init_command returns JSON with ok: true."""
        mock_state = MagicMock()
        mock_state.ticket_id = "TEST-123"

        with patch(
            "scripts.planner.state.DesignState.load",
            return_value=mock_state,
        ):
            result = init_command(tmp_path)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is True
        assert output["ticket_id"] == "TEST-123"
        mock_state.save.assert_called_once()


class TestStatusCommandErrorHandling:
    """Tests for status_command error handling."""

    def test_status_command_returns_json_error_on_missing_state_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that status_command returns JSON error when state.yaml is missing."""
        result = status_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "error" in output
        assert output["error_type"] == "FileNotFoundError"
        assert output["error_category"] == "validation"

    def test_status_command_returns_json_error_on_load_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that status_command returns JSON error on DesignState.load exception."""
        with patch(
            "scripts.planner.state.DesignState.load",
            side_effect=RuntimeError("Corrupted state"),
        ):
            result = status_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "Corrupted state" in output["error"]
        assert output["error_type"] == "RuntimeError"
        assert output["error_category"] == "system"

    def test_status_command_success_returns_json_with_status_info(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that successful status_command returns JSON with status info."""
        mock_state = MagicMock()
        mock_state.ticket_id = "TEST-456"
        mock_state.phase = "executing"
        mock_state.current_layer = 2
        mock_state.units = [MagicMock(), MagicMock(), MagicMock()]
        mock_state.layer_execution = {
            "1": {"units_completed": ["unit-1"]},
            "2": {"units_completed": []},
        }
        mock_state.failures = []
        mock_state.worktree_path = "/path/to/worktree"
        mock_state.pr_url = "https://github.com/org/repo/pull/123"

        with patch(
            "scripts.planner.state.DesignState.load",
            return_value=mock_state,
        ):
            result = status_command(tmp_path)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is True
        assert output["ticket_id"] == "TEST-456"
        assert output["phase"] == "executing"
        assert output["current_layer"] == 2
        assert output["total_units"] == 3
        assert output["completed_units"] == 1
        assert output["failed_units"] == 0


class TestNextCommandErrorHandling:
    """Tests for next_command error handling."""

    def test_next_command_returns_json_error_on_missing_state_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that next_command returns JSON error when state.yaml is missing."""
        result = next_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "error" in output
        assert output["error_type"] == "FileNotFoundError"
        assert output["error_category"] == "validation"

    def test_next_command_returns_json_error_on_load_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that next_command returns JSON error on DesignState.load exception."""
        with patch(
            "scripts.planner.state.DesignState.load",
            side_effect=ValueError("Corrupted state file"),
        ):
            result = next_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "Corrupted state file" in output["error"]
        assert output["error_type"] == "ValueError"
        assert output["error_category"] == "validation"

    def test_next_command_success_returns_json_with_action(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that successful next_command returns JSON with action info."""
        mock_state = MagicMock()
        expected_action = {
            "action": "invoke-agent",
            "agent": "coder",
            "unit_id": "unit-1",
        }
        mock_state.read_next_action.return_value = expected_action

        mock_machine = MagicMock()

        with (
            patch(
                "scripts.planner.state.DesignState.load",
                return_value=mock_state,
            ),
            patch(
                "scripts.codegen.execute_plan.ExecutePlanStateMachine",
                return_value=mock_machine,
            ),
        ):
            result = next_command(tmp_path)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is True
        assert output["action"] == "invoke-agent"
        assert output["agent"] == "coder"
        assert output["unit_id"] == "unit-1"
        mock_machine.next_action.assert_called_once()


class TestProcessCommandErrorHandling:
    """Tests for process_command error handling."""

    def test_process_command_returns_json_error_on_missing_state_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that process_command returns JSON error when state.yaml is missing."""
        result = process_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "error" in output
        assert output["error_type"] == "FileNotFoundError"
        assert output["error_category"] == "validation"

    def test_process_command_returns_json_error_on_load_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that process_command returns JSON error on DesignState.load exception."""
        with patch(
            "scripts.planner.state.DesignState.load",
            side_effect=RuntimeError("Failed to parse state"),
        ):
            result = process_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "Failed to parse state" in output["error"]
        assert output["error_type"] == "RuntimeError"
        assert output["error_category"] == "system"

    def test_process_command_success_returns_json_with_action(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that successful process_command returns JSON with action info."""
        mock_state = MagicMock()
        expected_action = {
            "action": "done",
            "message": "All units completed",
        }
        mock_state.read_next_action.return_value = expected_action

        mock_machine = MagicMock()

        with (
            patch(
                "scripts.planner.state.DesignState.load",
                return_value=mock_state,
            ),
            patch(
                "scripts.codegen.execute_plan.ExecutePlanStateMachine",
                return_value=mock_machine,
            ),
        ):
            result = process_command(tmp_path)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is True
        assert output["action"] == "done"
        assert output["message"] == "All units completed"
        mock_machine.process_agent_output.assert_called_once()

    def test_process_command_returns_json_error_on_read_next_action_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that process_command returns JSON error when read_next_action fails."""
        mock_state = MagicMock()
        mock_state.read_next_action.side_effect = RuntimeError("read_next_action failed")

        mock_machine = MagicMock()

        with (
            patch(
                "scripts.planner.state.DesignState.load",
                return_value=mock_state,
            ),
            patch(
                "scripts.codegen.execute_plan.ExecutePlanStateMachine",
                return_value=mock_machine,
            ),
        ):
            result = process_command(tmp_path)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "read_next_action failed" in output["error"]
        assert output["error_type"] == "RuntimeError"
        assert output["error_category"] == "system"
