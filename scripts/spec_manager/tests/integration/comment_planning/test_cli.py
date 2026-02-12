"""Tests for planning.algo_cli module."""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

from spec_manager.comment_planning.algo_cli import (
    cmd_decompose,
    cmd_scan,
    handle_plan_v2_command,
    setup_plan_v2_parser,
)


class TestSetupParser:
    """Tests for CLI parser setup."""

    def test_setup_creates_subcommands(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        setup_plan_v2_parser(subparsers)

        # Should be able to parse plan-v2 subcommands
        args = parser.parse_args(["plan-v2", "scan", "--directory", "/tmp"])
        assert args.command == "plan-v2"
        assert args.plan_v2_command == "scan"

    def test_insert_subcommand(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        setup_plan_v2_parser(subparsers)

        args = parser.parse_args(
            [
                "plan-v2",
                "insert",
                "--file",
                "/test.py",
                "--function",
                "process",
                "--intention",
                "add validation",
            ]
        )
        assert args.plan_v2_command == "insert"
        assert args.file == "/test.py"
        assert args.function == "process"
        assert args.intention == "add validation"

    def test_reverse_subcommand(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        setup_plan_v2_parser(subparsers)

        args = parser.parse_args(
            [
                "plan-v2",
                "reverse",
                "--file",
                "/test.py",
                "--function",
                "process",
                "--start-line",
                "5",
                "--end-line",
                "10",
            ]
        )
        assert args.plan_v2_command == "reverse"
        assert args.start_line == 5
        assert args.end_line == 10

    def test_adjacency_subcommand(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        setup_plan_v2_parser(subparsers)

        args = parser.parse_args(
            [
                "plan-v2",
                "adjacency",
                "--file",
                "/test.py",
                "--function",
                "process",
                "--directory",
                "/src",
            ]
        )
        assert args.plan_v2_command == "adjacency"
        assert args.directory == "/src"

    def test_decompose_subcommand(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        setup_plan_v2_parser(subparsers)

        args = parser.parse_args(
            [
                "plan-v2",
                "decompose",
                "--intention",
                "add fraud detection",
                "--file",
                "/test.py",
                "--function",
                "validate",
            ]
        )
        assert args.plan_v2_command == "decompose"
        assert args.intention == "add fraud detection"


class TestCmdScan:
    """Tests for cmd_scan command."""

    def test_scan_directory(self, tmp_path: Path) -> None:
        code = textwrap.dedent("""\
            def process(data):
                # validate input parameters
                return data

            def stub():
                pass
        """)
        py_file = tmp_path / "test_module.py"
        py_file.write_text(code, encoding="utf-8")

        args = argparse.Namespace(
            directory=str(tmp_path),
            json=False,
        )
        exit_code = cmd_scan(args)
        assert exit_code == 0

    def test_scan_nonexistent_directory(self) -> None:
        args = argparse.Namespace(
            directory="/nonexistent/path",
            json=False,
        )
        exit_code = cmd_scan(args)
        assert exit_code == 1

    def test_scan_json_output(self, tmp_path: Path) -> None:
        code = textwrap.dedent("""\
            def f():
                # compute result
                pass
        """)
        (tmp_path / "mod.py").write_text(code, encoding="utf-8")

        args = argparse.Namespace(
            directory=str(tmp_path),
            json=True,
        )
        exit_code = cmd_scan(args)
        assert exit_code == 0


class TestCmdDecompose:
    """Tests for cmd_decompose command."""

    def test_decompose_intention(self, tmp_path: Path) -> None:
        code = textwrap.dedent("""\
            def process(data):
                return data
        """)
        py_file = tmp_path / "test_mod.py"
        py_file.write_text(code, encoding="utf-8")

        args = argparse.Namespace(
            intention="validate input and transform data",
            file=str(py_file),
            function="process",
        )
        exit_code = cmd_decompose(args)
        assert exit_code == 0

    def test_decompose_file_not_found(self) -> None:
        args = argparse.Namespace(
            intention="test",
            file="/nonexistent.py",
            function="f",
        )
        exit_code = cmd_decompose(args)
        assert exit_code == 1

    def test_decompose_function_not_found(self, tmp_path: Path) -> None:
        code = "def f(): pass\n"
        py_file = tmp_path / "test.py"
        py_file.write_text(code, encoding="utf-8")

        args = argparse.Namespace(
            intention="test",
            file=str(py_file),
            function="nonexistent",
        )
        exit_code = cmd_decompose(args)
        assert exit_code == 1


class TestHandlePlanV2Command:
    """Tests for command routing."""

    def test_unknown_command(self) -> None:
        args = argparse.Namespace(plan_v2_command="unknown_cmd")
        exit_code = handle_plan_v2_command(args)
        assert exit_code == 1
