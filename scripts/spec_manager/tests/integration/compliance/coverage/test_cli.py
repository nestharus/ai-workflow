"""Tests for the coverage CLI subcommand."""

from __future__ import annotations

import argparse

from spec_manager.compliance.coverage.cli import (
    handle_coverage_command,
    setup_coverage_parser,
)


class TestSetupCoverageParser:
    def test_registers_coverage_subcommand(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        setup_coverage_parser(subparsers)

        # Verify 'coverage entity-gaps' can be parsed
        args = parser.parse_args(["coverage", "entity-gaps", "test-run"])
        assert args.command == "coverage"
        assert args.coverage_command == "entity-gaps"
        assert args.run_id == "test-run"

    def test_default_arguments(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        setup_coverage_parser(subparsers)

        args = parser.parse_args(["coverage", "entity-gaps", "my-run"])
        assert args.input_folder == "."
        assert args.threshold == 0.0
        assert args.format == "text"
        assert args.output is None

    def test_custom_arguments(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        setup_coverage_parser(subparsers)

        args = parser.parse_args(
            [
                "coverage",
                "entity-gaps",
                "my-run",
                "--input-folder",
                "/tmp/input",
                "--threshold",
                "0.8",
                "--format",
                "json",
                "--output",
                "/tmp/report.json",
            ]
        )
        assert args.input_folder == "/tmp/input"
        assert args.threshold == 0.8
        assert args.format == "json"
        assert args.output == "/tmp/report.json"


class TestHandleCoverageCommand:
    def test_unknown_subcommand_returns_error(self) -> None:
        args = argparse.Namespace(coverage_command="nonexistent")
        result = handle_coverage_command(args)
        assert result == 1
