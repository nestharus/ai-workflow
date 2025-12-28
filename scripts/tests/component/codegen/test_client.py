import json
from pathlib import Path

import pytest

from scripts.codegen.client import (
    init_command,
    next_command,
    process_command,
    status_command,
)


class TestInitCommandErrorHandling:
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


class TestStatusCommandErrorHandling:
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


class TestNextCommandErrorHandling:
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


class TestProcessCommandErrorHandling:
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
