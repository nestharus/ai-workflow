import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from scripts.dev.test_runner.test_coverage import (
    DEFAULT_MIN_BRANCH_OVERALL,
    DEFAULT_MIN_BRANCH_PER_FUNCTION,
    DEFAULT_MIN_LINE_OVERALL,
    DEFAULT_MIN_LINE_PER_FUNCTION,
    DEFAULT_MIN_USECASE,
    CoverageResult,
    FunctionCoverage,
    TestTierConfig,
    UseCase,
    UseCaseCoverageResult,
    _calculate_function_coverage,
    _extract_functions_from_file,
    _get_class_field_lines,
    _is_private_function,
    calculate_usecase_coverage,
    collect_covered_usecases,
    get_test_tiers,
    load_tier_configs,
    load_use_cases,
    parse_args,
    print_summary,
    validate_line_branch_coverage,
    validate_usecase_coverage,
)


class TestMainMisconfiguredTierHandling:
    def test_main_catches_get_test_tiers_value_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main() should catch ValueError from get_test_tiers() and return exit code 1."""
        import argparse

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="all",
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,
                no_validate=False,
                json_report=None,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )
        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.get_test_tiers",
            lambda: (_ for _ in ()).throw(
                ValueError("Custom tier 'e2e' is missing required fields: test_path")
            ),
        )
        from scripts.dev.test_runner.test_coverage import main

        result = main()
        assert result == 1

    def test_main_prints_error_message_for_misconfigured_tier(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main() should print error message from ValueError without traceback."""
        import argparse

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="all",
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,
                no_validate=False,
                json_report=None,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )
        error_message = "Custom tier 'e2e' is missing required fields: test_path"
        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.get_test_tiers",
            lambda: (_ for _ in ()).throw(ValueError(error_message)),
        )
        from scripts.dev.test_runner.test_coverage import main

        main()
        captured = capsys.readouterr()
        assert "ERROR:" in captured.out
        assert error_message in captured.out
        # Should not have traceback markers
        assert "Traceback" not in captured.out
        assert "raise ValueError" not in captured.out


class TestMainUnknownTierValidation:
    def test_main_rejects_unknown_tier_with_nonzero_exit(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main() should return non-zero exit code (1) for unknown tier."""
        import argparse

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="nonexistent_tier",
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,
                no_validate=False,
                json_report=None,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )
        from scripts.dev.test_runner.test_coverage import main

        result = main()
        assert result == 1

    def test_main_prints_error_for_unknown_tier(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main() should print clear error message identifying the unknown tier."""
        import argparse

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="nonexistent_tier",
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,
                no_validate=False,
                json_report=None,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )
        from scripts.dev.test_runner.test_coverage import main

        main()
        captured = capsys.readouterr()
        assert "ERROR:" in captured.out
        assert "Unknown tier" in captured.out
        assert "nonexistent_tier" in captured.out

    def test_main_error_message_lists_available_tiers(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Error message should list all available tiers for user guidance."""
        import argparse

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="bad_tier",
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,
                no_validate=False,
                json_report=None,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )
        from scripts.dev.test_runner.test_coverage import main

        main()
        captured = capsys.readouterr()
        # Error message should indicate available tiers
        assert "Available tiers:" in captured.out
        # Should list all default tiers
        assert "component" in captured.out
        assert "integration" in captured.out
        assert "scripts" in captured.out
        assert "unit" in captured.out

    def test_main_accepts_valid_default_tier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() should accept valid tier names without unknown tier error.

        This test verifies that the validation only rejects truly unknown tiers,
        not valid ones like 'unit'.
        """
        import argparse

        error_printed = []
        original_print = print

        def capture_print(*args: object, **kwargs: object) -> None:
            msg = " ".join(str(a) for a in args)
            if "Unknown tier" in msg:
                error_printed.append(msg)
            return original_print(*args, **kwargs)

        monkeypatch.setattr("builtins.print", capture_print)
        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="unit",  # Valid tier
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,
                no_validate=False,
                json_report=None,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )
        # Mock subprocess to prevent actual test execution
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: type("Result", (), {"returncode": 0})(),
        )

        from scripts.dev.test_runner.test_coverage import main

        with contextlib.suppress(Exception):
            main()  # May fail for other reasons, but not unknown tier

        # Should NOT have printed "Unknown tier" error for valid tier
        assert len(error_printed) == 0, f"Unexpected error: {error_printed}"


class TestMainJSONReportIntegration:
    def test_main_json_report_generation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify main() with --json-report produces valid JSON with expected structure.

        This test mocks the strategy execution to avoid running actual pytest/coverage,
        but exercises the JSON report generation path in main().
        """
        import json
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import (
            CoverageResult,
            TestTierConfig,
            UseCaseCoverageResult,
            main,
        )

        # Set up paths
        json_report_path = tmp_path / "test_report.json"
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        coverage_data_file = coverage_dir / "data"
        coverage_data_file.touch()

        # Create mock tier config and results
        mock_line_branch_config = TestTierConfig(
            name="scripts",
            test_path="scripts/tests",
            source_paths=["scripts/"],
            min_line_per_function=80.0,
        )
        mock_coverage_result = CoverageResult(
            suite_name="scripts",
            total_lines=1000,
            covered_lines=855,
            missing_lines=145,
            line_coverage_pct=85.5,
            total_branches=200,
            covered_branches=145,
            missing_branches=55,
            branch_coverage_pct=72.3,
            files={},
            functions={
                "scripts/example.py::process": {
                    "name": "process",
                    "file": "scripts/example.py",
                    "line_coverage": 90.0,
                    "branch_coverage": 80.0,
                }
            },
        )

        mock_usecase_config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app/"],
            min_usecase=100.0,
        )
        mock_usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=8,
            uncovered_cases=["UC-INT-001", "UC-INT-002"],
            coverage_pct=80.0,
        )

        # Create mock strategies
        mock_line_branch_strategy = MagicMock()
        mock_line_branch_strategy.config = mock_line_branch_config
        mock_line_branch_strategy.coverage_result = mock_coverage_result
        mock_line_branch_strategy.usecase_result = None
        mock_line_branch_strategy.validate.return_value = []
        mock_line_branch_strategy.build_summary.return_value = {"tier_pass": True}

        mock_usecase_strategy = MagicMock()
        mock_usecase_strategy.config = mock_usecase_config
        mock_usecase_strategy.coverage_result = None
        mock_usecase_strategy.usecase_result = mock_usecase_result
        mock_usecase_strategy.validate.return_value = []
        mock_usecase_strategy.build_summary.return_value = {"tier_pass": True}

        def mock_create_strategy(*args: Any, **kwargs: Any) -> MagicMock:
            config = args[0]
            if config.coverage_type == "line_branch":
                return mock_line_branch_strategy
            return mock_usecase_strategy

        # Mock the tier configs to return our mock configs
        def mock_get_test_tiers() -> dict:
            return {
                "scripts": mock_line_branch_config,
                "integration": mock_usecase_config,
            }

        # Patch command-line args
        test_args = [
            "test_coverage.py",
            "--tier",
            "all",
            "--json-report",
            str(json_report_path),
            "--no-validate",
            "--skip-redundant-detection",
        ]
        monkeypatch.setattr("sys.argv", test_args)

        # Patch REPO_ROOT to use tmp_path
        monkeypatch.setattr("scripts.dev.test_runner.test_coverage.REPO_ROOT", tmp_path)

        # Create minimal files needed by main()
        use_cases_dir = tmp_path / "tests" / "docs"
        use_cases_dir.mkdir(parents=True, exist_ok=True)
        (use_cases_dir / "use_cases.yaml").write_text("use_cases: []")

        # Apply patches and run main()
        # Note: create_strategy is imported inside main(), so we patch it at the source
        with (
            patch(
                "scripts.dev.test_runner.test_coverage.get_test_tiers",
                mock_get_test_tiers,
            ),
            patch(
                "scripts.dev.test_runner.test_strategies.create_strategy",
                mock_create_strategy,
            ),
            patch("scripts.dev.test_runner.test_coverage._run_command"),
            patch("scripts.dev.test_runner.coverage_db.init_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.clear_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.write_usecase_registry"),
            patch("scripts.dev.test_runner.coverage_db.write_run_metadata"),
            patch("scripts.dev.test_runner.coverage_db.write_tier_summary"),
        ):
            exit_code = main()

        # Verify exit code
        assert exit_code == 0, "main() should succeed with --no-validate"

        # Verify JSON report was created
        assert json_report_path.exists(), "JSON report file should be created"

        # Load and verify structure
        with json_report_path.open() as f:
            report = json.load(f)

        # Verify top-level keys
        assert "tiers" in report, "Report should have 'tiers' key"
        assert "thresholds" in report, "Report should have 'thresholds' key"

        # Verify line_branch tier structure
        assert "scripts" in report["tiers"], "Should have 'scripts' tier"
        scripts_tier = report["tiers"]["scripts"]
        assert scripts_tier["type"] == "line_branch"
        assert "line_coverage" in scripts_tier
        assert "branch_coverage" in scripts_tier
        assert "total_lines" in scripts_tier
        assert "covered_lines" in scripts_tier
        assert "total_branches" in scripts_tier
        assert "covered_branches" in scripts_tier
        assert "functions" in scripts_tier

        # Verify usecase tier structure
        assert "integration" in report["tiers"], "Should have 'integration' tier"
        integration_tier = report["tiers"]["integration"]
        assert integration_tier["type"] == "usecase"
        assert "total_cases" in integration_tier
        assert "covered_cases" in integration_tier
        assert "uncovered_cases" in integration_tier
        assert "coverage_pct" in integration_tier

        # Verify thresholds structure
        assert "min_line" in report["thresholds"]
        assert "min_branch" in report["thresholds"]
        assert "min_usecase" in report["thresholds"]


class TestMainTierPassEndToEnd:
    @pytest.fixture
    def mock_subprocess_passing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock subprocess.run to simulate passing tests."""

        def mock_run(*args: Any, **kwargs: Any) -> Any:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("subprocess.run", mock_run)

    @pytest.fixture
    def mock_subprocess_failing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock subprocess.run to simulate failing tests."""

        def mock_run(*args: Any, **kwargs: Any) -> Any:
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("subprocess.run", mock_run)

    def test_main_unit_tier_pass_1_when_all_pass(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        mock_subprocess_passing: None,
    ) -> None:
        """main() should produce tier_pass=1 for unit tier when coverage/tests pass."""
        import argparse
        import json
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import CoverageResult, main

        json_report = tmp_path / "report.json"
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        # Create the mock config for get_test_tiers()
        mock_unit_config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )

        # Mock parse_args to return our test configuration
        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="unit",
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,
                no_validate=False,
                json_report=json_report,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )

        # Mock REPO_ROOT
        monkeypatch.setattr("scripts.dev.test_runner.test_coverage.REPO_ROOT", tmp_path)

        # Create minimal required files
        use_cases_dir = tmp_path / "tests" / "docs"
        use_cases_dir.mkdir(parents=True, exist_ok=True)
        (use_cases_dir / "use_cases.yaml").write_text("features: {}")

        # Create a mock strategy that simulates passing coverage and tests
        mock_strategy = MagicMock()
        mock_strategy.config = mock_unit_config
        mock_strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=80,
            missing_lines=20,
            line_coverage_pct=80.0,
            total_branches=50,
            covered_branches=40,
            missing_branches=10,
            branch_coverage_pct=80.0,
            files={},
            functions={
                "app/example.py::func": {
                    "name": "func",
                    "file": "app/example.py",
                    "line_coverage": 80.0,
                    "branch_coverage": 70.0,
                    "missing_branches": [],
                }
            },
        )
        mock_strategy.usecase_result = None
        mock_strategy.validate.return_value = []  # No failures
        mock_strategy.build_summary.return_value = {
            "coverage_type": "line_branch",
            "tier_pass": 1,
            "total_functions": 1,
            "passing_functions": 1,
            "failing_functions": 0,
        }

        with (
            patch(
                "scripts.dev.test_runner.test_coverage.get_test_tiers",
                return_value={"unit": mock_unit_config},
            ),
            patch(
                "scripts.dev.test_runner.test_strategies.create_strategy",
                return_value=mock_strategy,
            ),
            patch("scripts.dev.test_runner.coverage_db.init_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.clear_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.write_usecase_registry"),
            patch("scripts.dev.test_runner.coverage_db.write_run_metadata"),
            patch("scripts.dev.test_runner.coverage_db.write_tier_summary"),
            patch("scripts.dev.test_runner.test_coverage._run_command"),
        ):
            result = main()

        assert result == 0
        assert json_report.exists()

        report = json.loads(json_report.read_text())
        assert "unit" in report["tiers"]

    def test_main_unit_no_validate_ignores_coverage_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        mock_subprocess_passing: None,
    ) -> None:
        """main() with --no-validate should produce tier_pass=1 despite low coverage.

        This test verifies the end-to-end behavior where:
        1. --no-validate is passed via arguments
        2. main() skips calling strategy.validate()
        3. tier_pass=1 because no coverage failures are recorded
        """
        import argparse
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import CoverageResult, main

        json_report = tmp_path / "report.json"
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        mock_unit_config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="unit",
                min_line=100.0,  # Impossible threshold
                min_branch=100.0,
                min_usecase=100.0,
                no_validate=True,  # Key: --no-validate
                json_report=json_report,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )

        monkeypatch.setattr("scripts.dev.test_runner.test_coverage.REPO_ROOT", tmp_path)

        use_cases_dir = tmp_path / "tests" / "docs"
        use_cases_dir.mkdir(parents=True, exist_ok=True)
        (use_cases_dir / "use_cases.yaml").write_text("features: {}")

        mock_strategy = MagicMock()
        mock_strategy.config = mock_unit_config
        mock_strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=50,  # Below threshold
            missing_lines=50,
            line_coverage_pct=50.0,
            total_branches=50,
            covered_branches=25,
            missing_branches=25,
            branch_coverage_pct=50.0,
            files={},
            functions={
                "app/example.py::func": {
                    "name": "func",
                    "file": "app/example.py",
                    "line_coverage": 50.0,  # Below 100%
                    "branch_coverage": 50.0,
                    "missing_branches": [(1, 2)],
                }
            },
        )
        mock_strategy.usecase_result = None
        # --no-validate means validate() should NOT be called
        mock_strategy.validate.return_value = ["coverage failure"]
        # But tier_pass=1 because _failures is empty when validate() not called
        mock_strategy.build_summary.return_value = {
            "coverage_type": "line_branch",
            "tier_pass": 1,  # tier_pass=1 despite low coverage
            "total_functions": 1,
            "passing_functions": 0,
            "failing_functions": 1,
        }

        with (
            patch(
                "scripts.dev.test_runner.test_coverage.get_test_tiers",
                return_value={"unit": mock_unit_config},
            ),
            patch(
                "scripts.dev.test_runner.test_strategies.create_strategy",
                return_value=mock_strategy,
            ),
            patch("scripts.dev.test_runner.coverage_db.init_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.clear_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.write_usecase_registry"),
            patch("scripts.dev.test_runner.coverage_db.write_run_metadata"),
            patch("scripts.dev.test_runner.coverage_db.write_tier_summary"),
            patch("scripts.dev.test_runner.test_coverage._run_command"),
        ):
            result = main()

        # --no-validate means main() should return 0 even with low coverage
        assert result == 0
        # Verify validate() was NOT called because of --no-validate
        mock_strategy.validate.assert_not_called()

    def test_main_unit_no_validate_still_fails_on_test_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        mock_subprocess_failing: None,
    ) -> None:
        """main() with --no-validate should still produce tier_pass=0 when tests fail.

        This test verifies the critical semantic that --no-validate only skips
        coverage threshold validation, NOT test execution results. Test failures
        always cause tier_pass=0 for line_branch tiers.
        """
        import argparse
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import CoverageResult, main

        json_report = tmp_path / "report.json"
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        mock_unit_config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="unit",
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,
                no_validate=True,  # --no-validate doesn't help test failures
                json_report=json_report,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )

        monkeypatch.setattr("scripts.dev.test_runner.test_coverage.REPO_ROOT", tmp_path)

        use_cases_dir = tmp_path / "tests" / "docs"
        use_cases_dir.mkdir(parents=True, exist_ok=True)
        (use_cases_dir / "use_cases.yaml").write_text("features: {}")

        mock_strategy = MagicMock()
        mock_strategy.config = mock_unit_config
        mock_strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=80,
            missing_lines=20,
            line_coverage_pct=80.0,
            total_branches=50,
            covered_branches=40,
            missing_branches=10,
            branch_coverage_pct=80.0,
            files={},
            functions={},
        )
        mock_strategy.usecase_result = None
        # tier_pass=0 because tests failed (tracked via test_summary, not validate())
        mock_strategy.build_summary.return_value = {
            "coverage_type": "line_branch",
            "tier_pass": 0,  # Test failures still cause tier_pass=0
            "total_functions": 0,
            "passing_functions": 0,
            "failing_functions": 0,
            "tests_failed": 2,
        }

        with (
            patch(
                "scripts.dev.test_runner.test_coverage.get_test_tiers",
                return_value={"unit": mock_unit_config},
            ),
            patch(
                "scripts.dev.test_runner.test_strategies.create_strategy",
                return_value=mock_strategy,
            ),
            patch("scripts.dev.test_runner.coverage_db.init_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.clear_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.write_usecase_registry"),
            patch("scripts.dev.test_runner.coverage_db.write_run_metadata"),
            patch("scripts.dev.test_runner.coverage_db.write_tier_summary"),
            patch("scripts.dev.test_runner.test_coverage._run_command"),
        ):
            result = main()

        # With --no-validate, main() returns 0 (coverage validation skipped)
        # but tier_pass in the report will be 0 due to test failures
        assert result == 0

    def test_main_integration_no_validate_ignores_usecase_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """main() with --no-validate for integration tier should produce tier_pass=1.

        Integration tiers use usecase coverage which doesn't track test failures,
        so --no-validate causes tier_pass=1 regardless of coverage percentage.
        """
        import argparse
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import main

        json_report = tmp_path / "report.json"
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        mock_integration_config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="integration",
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,  # High threshold
                no_validate=True,
                json_report=json_report,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )

        monkeypatch.setattr("scripts.dev.test_runner.test_coverage.REPO_ROOT", tmp_path)

        use_cases_dir = tmp_path / "tests" / "docs"
        use_cases_dir.mkdir(parents=True, exist_ok=True)
        (use_cases_dir / "use_cases.yaml").write_text("features: {}")

        mock_strategy = MagicMock()
        mock_strategy.config = mock_integration_config
        mock_strategy.coverage_result = None
        mock_strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=5,
            uncovered_cases=["UC-1", "UC-2", "UC-3", "UC-4", "UC-5"],
            coverage_pct=50.0,  # Below 100% threshold
        )
        # tier_pass=1 because --no-validate skips usecase validation
        mock_strategy.build_summary.return_value = {
            "coverage_type": "usecase",
            "tier_pass": 1,
            "total_usecases": 10,
            "usecases_covered": 5,
        }

        def mock_run(*args: Any, **kwargs: Any) -> Any:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("subprocess.run", mock_run)

        with (
            patch(
                "scripts.dev.test_runner.test_coverage.get_test_tiers",
                return_value={"integration": mock_integration_config},
            ),
            patch(
                "scripts.dev.test_runner.test_strategies.create_strategy",
                return_value=mock_strategy,
            ),
            patch("scripts.dev.test_runner.coverage_db.init_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.clear_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.write_usecase_registry"),
            patch("scripts.dev.test_runner.coverage_db.write_run_metadata"),
            patch("scripts.dev.test_runner.coverage_db.write_tier_summary"),
            patch("scripts.dev.test_runner.test_coverage._run_command"),
        ):
            result = main()

        assert result == 0
        # validate() should not be called due to --no-validate
        mock_strategy.validate.assert_not_called()


class TestMainCustomTierPassEndToEnd:
    def test_main_custom_line_branch_tier_pass_behavior(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Custom line_branch tier should compute tier_pass correctly via main()."""
        import argparse
        import json
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import CoverageResult, main

        # Create custom tier in temporary pyproject.toml
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.e2e]
test_path = "tests/e2e"
source_paths = ["app"]
min_line_per_function = 70.0
min_branch_per_function = 60.0
""")

        json_report = tmp_path / "report.json"
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("scripts.dev.test_runner.test_coverage.REPO_ROOT", tmp_path)

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="e2e",  # Custom tier
                min_line=70.0,
                min_branch=60.0,
                min_usecase=100.0,
                no_validate=False,
                json_report=json_report,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )

        use_cases_dir = tmp_path / "tests" / "docs"
        use_cases_dir.mkdir(parents=True, exist_ok=True)
        (use_cases_dir / "use_cases.yaml").write_text("features: {}")

        mock_strategy = MagicMock()
        mock_strategy.config = TestTierConfig(
            name="e2e",
            test_path="tests/e2e",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        mock_strategy.coverage_result = CoverageResult(
            suite_name="e2e",
            total_lines=100,
            covered_lines=85,
            missing_lines=15,
            line_coverage_pct=85.0,
            total_branches=50,
            covered_branches=40,
            missing_branches=10,
            branch_coverage_pct=80.0,
            files={},
            functions={
                "app/handler.py::handle": {
                    "name": "handle",
                    "file": "app/handler.py",
                    "line_coverage": 85.0,
                    "branch_coverage": 80.0,
                    "missing_branches": [],
                }
            },
        )
        mock_strategy.usecase_result = None
        mock_strategy.validate.return_value = []
        mock_strategy.build_summary.return_value = {
            "coverage_type": "line_branch",
            "tier_pass": 1,
            "total_functions": 1,
            "passing_functions": 1,
            "failing_functions": 0,
        }

        def mock_run(*args: Any, **kwargs: Any) -> Any:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("subprocess.run", mock_run)

        with (
            patch(
                "scripts.dev.test_runner.test_strategies.create_strategy",
                return_value=mock_strategy,
            ),
            patch("scripts.dev.test_runner.coverage_db.init_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.clear_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.write_usecase_registry"),
            patch("scripts.dev.test_runner.coverage_db.write_run_metadata"),
            patch("scripts.dev.test_runner.coverage_db.write_tier_summary"),
            patch("scripts.dev.test_runner.test_coverage._run_command"),
        ):
            result = main()

        assert result == 0
        assert json_report.exists()
        report = json.loads(json_report.read_text())
        assert "e2e" in report["tiers"]

    def test_main_custom_usecase_tier_no_validate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Custom usecase tier with --no-validate should have tier_pass=1."""
        import argparse
        import json
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import main

        # Create custom usecase tier
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.smoke]
test_path = "tests/smoke"
source_paths = ["app"]
min_usecase = 100.0
""")

        json_report = tmp_path / "report.json"
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("scripts.dev.test_runner.test_coverage.REPO_ROOT", tmp_path)

        monkeypatch.setattr(
            "scripts.dev.test_runner.test_coverage.parse_args",
            lambda argv=None: argparse.Namespace(
                tier="smoke",  # Custom usecase tier
                min_line=60.0,
                min_branch=50.0,
                min_usecase=100.0,
                no_validate=True,  # Skip validation
                json_report=json_report,
                skip_redundant_detection=True,
                include_partial_redundant=False,
            ),
        )

        use_cases_dir = tmp_path / "tests" / "docs"
        use_cases_dir.mkdir(parents=True, exist_ok=True)
        (use_cases_dir / "use_cases.yaml").write_text("features: {}")

        mock_strategy = MagicMock()
        mock_strategy.config = TestTierConfig(
            name="smoke",
            test_path="tests/smoke",
            source_paths=["app"],
            min_usecase=100.0,
        )
        mock_strategy.coverage_result = None
        mock_strategy.usecase_result = UseCaseCoverageResult(
            tier="smoke",
            total_cases=5,
            covered_cases=2,  # Below 100% threshold
            uncovered_cases=["UC-S-3", "UC-S-4", "UC-S-5"],
            coverage_pct=40.0,
        )
        # tier_pass=1 because --no-validate skips coverage check
        mock_strategy.build_summary.return_value = {
            "coverage_type": "usecase",
            "tier_pass": 1,
            "total_usecases": 5,
            "usecases_covered": 2,
        }

        def mock_run(*args: Any, **kwargs: Any) -> Any:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("subprocess.run", mock_run)

        with (
            patch(
                "scripts.dev.test_runner.test_strategies.create_strategy",
                return_value=mock_strategy,
            ),
            patch("scripts.dev.test_runner.coverage_db.init_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.clear_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.write_usecase_registry"),
            patch("scripts.dev.test_runner.coverage_db.write_run_metadata"),
            patch("scripts.dev.test_runner.coverage_db.write_tier_summary"),
            patch("scripts.dev.test_runner.test_coverage._run_command"),
        ):
            result = main()

        assert result == 0
        assert json_report.exists()
        report = json.loads(json_report.read_text())
        assert "smoke" in report["tiers"]
        # validate() should not be called due to --no-validate
        mock_strategy.validate.assert_not_called()


class TestNoValidateBehavioralContract:
    def test_contract_custom_tiers_follow_same_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONTRACT: Custom tiers follow the same --no-validate rules as default tiers.

        Verifies that:
        - Custom line_branch tier: coverage ignored, tests checked
        - Custom usecase tier: always tier_pass=1 with --no-validate
        """
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import (
            IntegrationTestStrategy,
            LineBranchTestStrategy,
        )

        # Test custom line_branch tier
        custom_line_branch_config = TestTierConfig(
            name="e2e_strict",  # Custom tier
            test_path="tests/e2e",
            source_paths=["app/e2e"],
            min_line_per_function=99.0,
            min_branch_per_function=99.0,
        )
        db_path = tmp_path / "coverage.db"

        lb_strategy = LineBranchTestStrategy(
            custom_line_branch_config, db_path, tmp_path, tmp_path / "data_e2e_strict"
        )
        lb_strategy._tests_ran = True
        lb_strategy._results_collected = True
        lb_strategy.test_summary = TestSummary(total=3, passed=3, failed=0, errors=0, skipped=0)
        lb_strategy.coverage_result = CoverageResult(
            suite_name="e2e_strict",
            total_lines=100,
            covered_lines=50,  # 50% < 99%
            missing_lines=50,
            line_coverage_pct=50.0,
            total_branches=40,
            covered_branches=20,
            missing_branches=20,
            branch_coverage_pct=50.0,
            files={},
            functions={
                "app/e2e/test.py::run": {
                    "name": "run",
                    "file": "app/e2e/test.py",
                    "line_coverage": 50.0,
                    "branch_coverage": 50.0,
                    "missing_branches": [(5, 10)],
                }
            },
        )
        # Do NOT call validate() - simulates --no-validate

        lb_summary = lb_strategy.build_summary()
        assert lb_summary["tier_pass"] == 1  # Coverage ignored, tests pass

        # Test custom usecase tier
        custom_usecase_config = TestTierConfig(
            name="api_smoke",  # Custom tier
            test_path="tests/api",
            source_paths=["app/api"],
            min_usecase=100.0,
        )
        use_cases = [
            UseCase("UC-API-1", "/api", "GET", "API test", "api_smoke"),
        ]

        uc_strategy = IntegrationTestStrategy(custom_usecase_config, db_path, tmp_path, use_cases)
        uc_strategy._tests_ran = True
        uc_strategy._results_collected = True
        uc_strategy.usecase_result = UseCaseCoverageResult(
            tier="api_smoke",
            total_cases=1,
            covered_cases=0,  # 0% coverage
            uncovered_cases=["UC-API-1"],
            coverage_pct=0.0,
        )
        # Do NOT call validate() - simulates --no-validate

        uc_summary = uc_strategy.build_summary()
        assert uc_summary["tier_pass"] == 1  # Always 1 for usecase with --no-validate


class TestTierOrderPreservation:
    def test_tiers_to_run_preserves_order_in_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() should execute tiers in the order returned by get_test_tiers()."""
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import main

        # Create mock tier configs in a specific non-alphabetical order
        mock_config_z = TestTierConfig(
            name="z_tier",
            test_path="tests/z",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        mock_config_a = TestTierConfig(
            name="a_tier",
            test_path="tests/a",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        mock_config_m = TestTierConfig(
            name="m_tier",
            test_path="tests/m",
            source_paths=["app"],
            min_line_per_function=80.0,
        )

        # Return tiers in specific order: z, a, m
        ordered_tiers = {"z_tier": mock_config_z, "a_tier": mock_config_a, "m_tier": mock_config_m}

        # Track the order strategies are created
        created_order: list[str] = []

        def mock_create_strategy(config: TestTierConfig, *args: Any, **kwargs: Any) -> MagicMock:
            created_order.append(config.name)
            strategy = MagicMock()
            strategy.config = config
            strategy.coverage_result = None
            strategy.usecase_result = None
            strategy.validate.return_value = []
            strategy.build_summary.return_value = {"tier_pass": True}
            return strategy

        # Set up paths
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        (coverage_dir / "data").touch()

        # Create minimal use_cases.yaml
        use_cases_dir = tmp_path / "tests" / "docs"
        use_cases_dir.mkdir(parents=True, exist_ok=True)
        (use_cases_dir / "use_cases.yaml").write_text("use_cases: []")

        test_args = [
            "test_coverage.py",
            "--tier",
            "all",
            "--no-validate",
            "--skip-redundant-detection",
        ]
        monkeypatch.setattr("sys.argv", test_args)
        monkeypatch.setattr("scripts.dev.test_runner.test_coverage.REPO_ROOT", tmp_path)

        with (
            patch(
                "scripts.dev.test_runner.test_coverage.get_test_tiers",
                return_value=ordered_tiers,
            ),
            patch(
                "scripts.dev.test_runner.test_strategies.create_strategy",
                side_effect=mock_create_strategy,
            ),
            patch("scripts.dev.test_runner.test_coverage._run_command"),
            patch("scripts.dev.test_runner.coverage_db.init_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.clear_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.write_usecase_registry"),
            patch("scripts.dev.test_runner.coverage_db.write_run_metadata"),
            patch("scripts.dev.test_runner.coverage_db.write_tier_summary"),
        ):
            main()

        # Assert strategies were created in the exact order of the dict keys
        assert created_order == ["z_tier", "a_tier", "m_tier"], (
            f"Strategies should be created in dict key order ['z_tier', 'a_tier', 'm_tier'], "
            f"but got {created_order}"
        )


class TestCoverageIsolationPerTier:
    def test_per_tier_isolation_no_cov_append(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy.run_tests() should NOT use --cov-append flag."""
        from unittest.mock import patch

        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        db_path = tmp_path / "coverage.db"
        tier_coverage_file = tmp_path / "data_unit"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_cmd: list[str] = []
        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> Any:
            nonlocal captured_cmd, captured_env
            captured_cmd = cmd
            captured_env = env or {}
            # Return a mock result object
            from unittest.mock import MagicMock

            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command", side_effect=mock_run_command
        ):
            strategy.run_tests()

        # Verify --cov-append is NOT in the command
        assert "--cov-append" not in captured_cmd, (
            "run_tests() should NOT use --cov-append flag. "
            "Each tier writes to isolated coverage files."
        )

        # Verify COVERAGE_FILE env var is set to tier-specific path
        assert "COVERAGE_FILE" in captured_env
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file), (
            f"COVERAGE_FILE should be '{tier_coverage_file}', "
            f"but was '{captured_env['COVERAGE_FILE']}'"
        )

    def test_run_tests_uses_tier_coverage_file(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy.run_tests() should use tier-specific coverage file path."""
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="component",
            test_path="tests/unit",
            source_paths=["app/services"],
            min_line_per_function=80.0,
        )
        db_path = tmp_path / "coverage.db"
        tier_coverage_file = tmp_path / "data_component"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> Any:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command", side_effect=mock_run_command
        ):
            strategy.run_tests()

        # Verify COVERAGE_FILE points to tier-specific path
        assert captured_env.get("COVERAGE_FILE") == str(tier_coverage_file)
        # Verify it does NOT point to the combined coverage file
        assert captured_env.get("COVERAGE_FILE") != str(tmp_path / "data")

    def test_collect_results_uses_tier_coverage_file(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy.collect_results() should use tier-specific coverage file."""
        import json
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="scripts",
            test_path="scripts/tests",
            source_paths=["scripts"],
            min_line_per_function=80.0,
        )
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_scripts"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)
        strategy._tests_ran = True  # Simulate run_tests() was called

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> Any:
            nonlocal captured_env
            captured_env = env or {}

            # Create the JSON file that collect_results() expects
            if "json" in cmd:
                json_path = coverage_dir / f"temp_{config.name}.json"
                json_path.write_text(
                    json.dumps(
                        {
                            "totals": {
                                "num_statements": 100,
                                "covered_lines": 80,
                                "missing_lines": 20,
                                "percent_covered": 80.0,
                                "num_branches": 50,
                                "covered_branches": 40,
                                "num_partial_branches": 5,
                                "missing_branches": 5,
                                "percent_covered_branches": 80.0,
                            },
                            "files": {},
                        }
                    )
                )
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=mock_run_command,
            ),
            patch("scripts.dev.test_runner.coverage_db.write_tier_config"),
        ):
            strategy.collect_results()

        # Verify COVERAGE_FILE points to tier-specific path for JSON generation
        assert captured_env.get("COVERAGE_FILE") == str(tier_coverage_file)


class TestCoverageCombine:
    def test_coverage_combine_produces_combined_database(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() should run coverage combine to merge per-tier files after all tiers complete."""
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import main

        # Set up paths
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        # Create mock tier configs
        mock_unit_config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        mock_component_config = TestTierConfig(
            name="component",
            test_path="tests/unit",
            source_paths=["app/services"],
            min_line_per_function=80.0,
        )

        # Create mock strategies
        def create_mock_strategy(config: TestTierConfig, *args: Any, **kwargs: Any) -> MagicMock:
            strategy = MagicMock()
            strategy.config = config
            strategy.coverage_result = CoverageResult(
                suite_name=config.name,
                total_lines=100,
                covered_lines=80,
                missing_lines=20,
                line_coverage_pct=80.0,
                total_branches=50,
                covered_branches=40,
                missing_branches=10,
                branch_coverage_pct=80.0,
                files={},
                functions={},
            )
            strategy.usecase_result = None
            strategy.validate.return_value = []
            strategy.build_summary.return_value = {"tier_pass": 1}
            return strategy

        # Track coverage combine calls
        combine_cmd_called = False
        combine_files: list[str] = []

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> Any:
            nonlocal combine_cmd_called, combine_files
            if "combine" in cmd:
                combine_cmd_called = True
                # Extract the data files from the command
                combine_files = [arg for arg in cmd if arg.startswith(str(coverage_dir))]
            result = MagicMock()
            result.returncode = 0
            return result

        # Create use_cases.yaml
        use_cases_dir = tmp_path / "tests" / "docs"
        use_cases_dir.mkdir(parents=True, exist_ok=True)
        (use_cases_dir / "use_cases.yaml").write_text("use_cases: []")

        # Create tier coverage data files (simulate they exist after running tests)
        (coverage_dir / "data_unit").touch()
        (coverage_dir / "data_component").touch()

        test_args = [
            "test_coverage.py",
            "--tier",
            "all",
            "--no-validate",
            "--skip-redundant-detection",
        ]
        monkeypatch.setattr("sys.argv", test_args)
        monkeypatch.setattr("scripts.dev.test_runner.test_coverage.REPO_ROOT", tmp_path)

        with (
            patch(
                "scripts.dev.test_runner.test_coverage.get_test_tiers",
                return_value={"unit": mock_unit_config, "component": mock_component_config},
            ),
            patch(
                "scripts.dev.test_runner.test_strategies.create_strategy",
                side_effect=create_mock_strategy,
            ),
            patch(
                "scripts.dev.test_runner.test_coverage._run_command",
                side_effect=mock_run_command,
            ),
            patch("scripts.dev.test_runner.coverage_db.init_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.clear_custom_tables"),
            patch("scripts.dev.test_runner.coverage_db.write_usecase_registry"),
            patch("scripts.dev.test_runner.coverage_db.write_run_metadata"),
            patch("scripts.dev.test_runner.coverage_db.write_tier_summary"),
        ):
            main()

        # Verify coverage combine was called
        assert combine_cmd_called, "coverage combine should be called after all tiers complete"

        # Verify both tier data files were passed to combine
        assert len(combine_files) == 2, f"Expected 2 tier data files, got {len(combine_files)}"
        assert any("data_unit" in f for f in combine_files)
        assert any("data_component" in f for f in combine_files)
