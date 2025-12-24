"""Tests for scripts/dev/linter/linters/checkov.py - run function."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.dev.linter.linters.checkov import CheckovLinter


class TestCheckovLinterRun:
    """Tests for CheckovLinter.run method covering lines 33-54."""

    def test_returns_failure_when_openapi_schema_missing(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns failure when OpenAPI schema is missing (lines 33-38)."""
        linter = CheckovLinter()

        with (
            patch("scripts.dev.linter.linters.checkov.OPENAPI_SCHEMA", tmp_path / "missing.json"),
        ):
            result = linter.run()

            assert result.success is False
            captured = capsys.readouterr()
            assert "OpenAPI schema missing" in captured.err
            assert "generate" in captured.err

    def test_runs_checkov_when_schema_exists(self, tmp_path: Path) -> None:
        """Test run executes checkov when OpenAPI schema exists (lines 40-54)."""
        linter = CheckovLinter()

        # Create the schema file
        schema_file = tmp_path / "openapi.json"
        schema_file.write_text('{"openapi": "3.0.0"}')

        with (
            patch("scripts.dev.linter.linters.checkov.OPENAPI_SCHEMA", schema_file),
            patch("scripts.dev.linter.linters.checkov.CHECKOV_CONFIG", tmp_path / ".checkov.yaml"),
            patch(
                "scripts.dev.linter.linters.checkov.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.checkov.run_checked") as mock_run,
        ):
            result = linter.run()

            assert result.success is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "checkov" in call_args
            assert "--framework" in call_args
            assert "openapi" in call_args

    def test_skips_when_no_openapi_in_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test run skips when no openapi.json in files list."""
        linter = CheckovLinter()

        assert linter.supports_file_filtering is True

        # Create the schema file
        schema_file = tmp_path / "openapi.json"
        schema_file.write_text('{"openapi": "3.0.0"}')

        with (
            patch("scripts.dev.linter.linters.checkov.OPENAPI_SCHEMA", schema_file),
            patch("scripts.dev.linter.linters.checkov.CHECKOV_CONFIG", tmp_path / ".checkov.yaml"),
            patch(
                "scripts.dev.linter.linters.checkov.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.checkov.run_checked") as mock_run,
        ):
            # Files without openapi.json should cause linter to skip
            result = linter.run(files=["some_file.py"])

            assert result.success is True
            mock_run.assert_not_called()  # Should skip, not run checkov
            captured = capsys.readouterr()
            assert "skipping checkov linter" in captured.out

    def test_uses_config_file(self, tmp_path: Path) -> None:
        """Test run uses checkov config file (line 47)."""
        linter = CheckovLinter()

        # Create the schema file
        schema_file = tmp_path / "openapi.json"
        schema_file.write_text('{"openapi": "3.0.0"}')

        config_file = tmp_path / ".checkov.yaml"

        with (
            patch("scripts.dev.linter.linters.checkov.OPENAPI_SCHEMA", schema_file),
            patch("scripts.dev.linter.linters.checkov.CHECKOV_CONFIG", config_file),
            patch(
                "scripts.dev.linter.linters.checkov.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.checkov.run_checked") as mock_run,
        ):
            result = linter.run()

            assert result.success is True
            call_args = mock_run.call_args[0][0]
            assert "--config-file" in call_args
            assert str(config_file) in call_args
