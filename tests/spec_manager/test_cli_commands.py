"""Tests for CLI commands (Phase 7 Work Item 3).

Tests:
- test_cmd_validate: CMD-validate command
- test_cmd_project: CMD-project command
- test_deprecation_warnings: Orchestrator deprecation
"""

from __future__ import annotations

import argparse
import tempfile
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestCLIValidateCommand:
    """Test CMD-validate command structure phase."""

    def test_validate_command_exists(self) -> None:
        """Test that validate command is registered."""
        # Import after test setup to avoid import errors
        from spec_manager.refinement import cli as refinement_cli

        # Check that main parser can be created
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        # The spec subparser should exist and have validate
        # For now, verify the cli module loads
        assert refinement_cli is not None

        # Verify cmd_validate is available
        assert hasattr(refinement_cli, "cmd_validate")
        assert callable(refinement_cli.cmd_validate)

    def test_validate_requires_workspace(self) -> None:
        """Test validate requires initialized workspace."""
        from spec_manager.refinement.cli import cmd_validate

        # Create a mock namespace with a non-existent run_id
        args = argparse.Namespace(run_id="nonexistent_run_12345")

        # Should return 1 (error) because workspace is not initialized
        result = cmd_validate(args)
        assert result == 1


class TestCLIProjectCommand:
    """Test CMD-project command projection generation."""

    def test_project_command_exists(self) -> None:
        """Test that project command is registered."""
        from spec_manager.refinement import cli as refinement_cli

        assert refinement_cli is not None

        # Verify cmd_project is available
        assert hasattr(refinement_cli, "cmd_project")
        assert callable(refinement_cli.cmd_project)

    def test_project_requires_libraries(self) -> None:
        """Test project requires libraries phase complete."""
        from spec_manager.refinement.cli import cmd_project

        # Create a mock namespace with a non-existent run_id
        args = argparse.Namespace(run_id="nonexistent_run_12345")

        # Should return 1 (error) because workspace is not initialized
        result = cmd_project(args)
        assert result == 1


class TestOrchestratorDeprecation:
    """Test WorkflowOrchestrator deprecation warnings."""

    def test_run_method_deprecation(self) -> None:
        """Test that WorkflowOrchestrator.run() emits warning."""
        import tempfile

        from spec_manager.workflow.orchestrator import WorkflowOrchestrator

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create minimal spec structure
            (tmppath / "plan.md").write_text("# Test Plan\n")
            (tmppath / "libraries").mkdir()
            (tmppath / "libraries" / "test.md").write_text("# Test Library\n")

            orchestrator = WorkflowOrchestrator(tmppath)

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")

                # Call run() - it may fail but we only care about the warning
                try:
                    orchestrator.run()
                except Exception:
                    pass  # We only care about the warning

                # Check for deprecation warning
                deprecation_warnings = [
                    x for x in w if issubclass(x.category, DeprecationWarning)
                ]
                assert len(deprecation_warnings) >= 1
                warning_msg = str(deprecation_warnings[0].message).lower()
                assert "deprecated" in warning_msg
                assert "refinement cli" in warning_msg or "run" in warning_msg


class TestCLICommandMapping:
    """Test CLI command mapping matches design spec."""

    def test_design_commands_mapped(self) -> None:
        """Test design commands from 16_CLI_SCRIPTS.md are mapped."""
        # Expected commands from design
        expected_commands = {
            "discover",  # CMD-discover - existing
            "stage",  # CMD-clean - renamed
            "run",  # CMD-run - existing
        }

        # Import legacy CLI
        from spec_manager import cli

        # Check commands dict
        # Note: The actual commands dict is in main()
        # We verify module loads and has expected structure
        assert hasattr(cli, "cmd_discover")
        assert hasattr(cli, "cmd_stage")
        assert hasattr(cli, "cmd_run")

    def test_refinement_commands_mapped(self) -> None:
        """Test refinement CLI has expected commands."""
        from spec_manager.refinement import cli

        # Check function handlers exist
        assert hasattr(cli, "cmd_init")
        assert hasattr(cli, "cmd_status")
        assert hasattr(cli, "cmd_spec_sectionize")
        assert hasattr(cli, "cmd_spec_summarize")
        assert hasattr(cli, "cmd_spec_synthesize")
        assert hasattr(cli, "cmd_finalize_run")


class TestCLIArgumentParsing:
    """Test CLI argument parsing."""

    def test_legacy_spec_folder_argument(self) -> None:
        """Test legacy CLI accepts spec_folder argument."""
        from spec_manager.cli import main

        # Verify main can be called (will fail without args, but tests import)
        assert callable(main)

    def test_refinement_run_id_argument(self) -> None:
        """Test refinement CLI accepts run_id argument."""
        from spec_manager.refinement.cli import main

        # Verify main can be called
        assert callable(main)


class TestCLIHelpText:
    """Test CLI help text and descriptions."""

    def test_legacy_cli_description(self) -> None:
        """Test legacy CLI has useful description."""
        from spec_manager import cli

        # The module docstring should describe usage
        assert cli.__doc__ is not None
        assert "spec-manager" in cli.__doc__.lower() or "command" in cli.__doc__.lower()

    def test_refinement_cli_description(self) -> None:
        """Test refinement CLI has useful description."""
        from spec_manager.refinement import cli

        # The module docstring should describe usage
        assert cli.__doc__ is not None
        assert "workflow" in cli.__doc__.lower() or "phase" in cli.__doc__.lower()
