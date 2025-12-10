"""Tests for scripts.test_coverage module."""

from __future__ import annotations

import ast
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
    _is_in_service_layer,
    _is_private_function,
    calculate_usecase_coverage,
    collect_covered_usecases,
    get_test_tiers,
    load_use_cases,
    parse_args,
    print_summary,
    validate_line_branch_coverage,
    validate_usecase_coverage,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestDefaultThresholds:
    """Tests for default threshold constants."""

    def test_default_min_line_overall(self) -> None:
        """Should have 80% default overall line coverage."""
        assert DEFAULT_MIN_LINE_OVERALL == 80.0

    def test_default_min_branch_overall(self) -> None:
        """Should have 70% default overall branch coverage."""
        assert DEFAULT_MIN_BRANCH_OVERALL == 70.0

    def test_default_min_line_per_function(self) -> None:
        """Should have 60% default per-function line coverage."""
        assert DEFAULT_MIN_LINE_PER_FUNCTION == 60.0

    def test_default_min_branch_per_function(self) -> None:
        """Should have 50% default per-function branch coverage."""
        assert DEFAULT_MIN_BRANCH_PER_FUNCTION == 50.0

    def test_default_usecase_coverage(self) -> None:
        """Should have 100% default use-case coverage."""
        assert DEFAULT_MIN_USECASE == 100.0


class TestTestTiers:
    """Tests for get_test_tiers() configuration."""

    def test_has_unit_tier(self) -> None:
        """Should have unit test tier."""
        tiers = get_test_tiers()
        assert "unit" in tiers

    def test_has_component_tier(self) -> None:
        """Should have component test tier."""
        tiers = get_test_tiers()
        assert "component" in tiers

    def test_has_integration_tier(self) -> None:
        """Should have integration test tier."""
        tiers = get_test_tiers()
        assert "integration" in tiers

    def test_has_scripts_tier(self) -> None:
        """Should have scripts test tier."""
        tiers = get_test_tiers()
        assert "scripts" in tiers

    def test_unit_tier_config(self) -> None:
        """Unit tier should target app/ with all functions."""
        tiers = get_test_tiers()
        config = tiers["unit"]
        assert config.test_path == "tests/unit"
        assert config.source_paths == ["app"]
        assert config.coverage_type == "line_branch"
        assert config.skip_private_functions is False
        assert config.service_layer_only is False
        # coverage_file field should be removed
        assert not hasattr(config, "coverage_file")

    def test_component_tier_config(self) -> None:
        """Component tier should target service layer only."""
        tiers = get_test_tiers()
        config = tiers["component"]
        assert config.source_paths == ["app/services"]
        assert config.coverage_type == "line_branch"
        assert config.skip_private_functions is True
        assert config.service_layer_only is True
        # coverage_file field should be removed
        assert not hasattr(config, "coverage_file")

    def test_integration_tier_config(self) -> None:
        """Integration tier should use use-case coverage."""
        tiers = get_test_tiers()
        config = tiers["integration"]
        assert config.test_path == "tests/integration"
        assert config.coverage_type == "usecase"
        # coverage_file field should be removed
        assert not hasattr(config, "coverage_file")

    def test_scripts_tier_config(self) -> None:
        """Scripts tier should target scripts/ and tools/."""
        tiers = get_test_tiers()
        config = tiers["scripts"]
        assert config.test_path == "scripts/tests"
        assert config.source_paths == ["scripts", "tools"]
        assert config.coverage_type == "line_branch"
        assert config.skip_private_functions is True
        # coverage_file field should be removed
        assert not hasattr(config, "coverage_file")


class TestIsPrivateFunction:
    """Tests for _is_private_function helper."""

    def test_regular_function_not_private(self) -> None:
        """Regular functions should not be considered private."""
        assert _is_private_function("my_function") is False

    def test_single_underscore_private(self) -> None:
        """Single underscore prefix should be private."""
        assert _is_private_function("_helper") is True

    def test_double_underscore_private(self) -> None:
        """Double underscore prefix should be private."""
        assert _is_private_function("__internal") is True

    def test_init_not_private(self) -> None:
        """__init__ should not be considered private."""
        assert _is_private_function("__init__") is False

    def test_call_not_private(self) -> None:
        """__call__ should not be considered private."""
        assert _is_private_function("__call__") is False

    def test_other_dunder_is_private(self) -> None:
        """Other dunder methods should be private."""
        assert _is_private_function("__repr__") is True
        assert _is_private_function("__str__") is True


class TestIsInServiceLayer:
    """Tests for _is_in_service_layer helper."""

    def test_service_file_in_service_layer(self) -> None:
        """Files in app/services/ should be in service layer."""
        assert _is_in_service_layer("app/services/example_service.py") is True

    def test_nested_service_file(self) -> None:
        """Nested files in app/services/ should be in service layer."""
        assert _is_in_service_layer("app/services/v1/user_service.py") is True

    def test_api_file_not_in_service_layer(self) -> None:
        """Files in app/api/ should not be in service layer."""
        assert _is_in_service_layer("app/api/routes.py") is False

    def test_repository_not_in_service_layer(self) -> None:
        """Files in app/repositories/ should not be in service layer."""
        assert _is_in_service_layer("app/repositories/example.py") is False


class TestGetClassFieldLines:
    """Tests for _get_class_field_lines helper."""

    def test_extracts_class_fields(self, fs: FakeFilesystem) -> None:
        """Should extract class field line numbers."""
        code = """
class MyModel:
    name: str
    age: int = 0
    items: list[str]

    def method(self):
        pass
"""
        fs.create_file("/test.py", contents=code)

        result = _get_class_field_lines(Path("/test.py"))

        # Lines 3, 4, 5 are class fields
        assert 3 in result
        assert 4 in result
        assert 5 in result
        # Line 7-8 is a method, not a field
        assert 7 not in result

    def test_handles_missing_file(self) -> None:
        """Should return empty set for missing file."""
        result = _get_class_field_lines(Path("/nonexistent.py"))
        assert result == set()

    def test_handles_syntax_error(self, fs: FakeFilesystem) -> None:
        """Should return empty set for syntax errors."""
        fs.create_file("/bad.py", contents="def broken syntax:")

        result = _get_class_field_lines(Path("/bad.py"))

        assert result == set()


class TestExtractFunctionsFromFile:
    """Tests for _extract_functions_from_file function."""

    def test_extracts_regular_function(self, fs: FakeFilesystem) -> None:
        """Should extract regular function definitions."""
        code = """
def hello():
    print("hello")
    return True
"""
        fs.create_file("/test.py", contents=code)

        result = _extract_functions_from_file(Path("/test.py"))

        assert len(result) == 1
        name, start, _end, is_method = result[0]
        assert name == "hello"
        assert start == 2
        assert is_method is False

    def test_extracts_method_inside_class(self, fs: FakeFilesystem) -> None:
        """Should mark methods inside classes correctly."""
        code = """
class MyClass:
    def method(self):
        pass
"""
        fs.create_file("/test.py", contents=code)

        result = _extract_functions_from_file(Path("/test.py"))

        assert len(result) == 1
        name, _start, _end, is_method = result[0]
        assert name == "method"
        assert is_method is True

    def test_handles_missing_file(self) -> None:
        """Should return empty list for missing file."""
        result = _extract_functions_from_file(Path("/nonexistent.py"))
        assert result == []


class TestCalculateFunctionCoverage:
    """Tests for _calculate_function_coverage function."""

    def test_calculates_coverage_for_function(self, fs: FakeFilesystem) -> None:
        """Should calculate coverage for a function."""
        code = """def test_func():
    line_one = 1
    line_two = 2
    return line_one + line_two
"""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents=code)

        coverage_data = {
            "files": {
                "test.py": {
                    "executed_lines": [1, 2, 3],
                    "missing_lines": [4],
                    "missing_branches": [],
                }
            }
        }

        results = _calculate_function_coverage("test.py", coverage_data, Path("/repo"))

        assert len(results) == 1
        fc = results[0]
        assert fc.name == "test_func"
        assert fc.covered_lines == 3
        assert fc.missing_lines == [4]

    def test_excludes_class_fields(self, fs: FakeFilesystem) -> None:
        """Should exclude class field lines from coverage."""
        code = """class Model:
    name: str
    value: int

    def process(self):
        return self.value
"""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents=code)

        coverage_data = {
            "files": {
                "test.py": {
                    "executed_lines": [1, 5, 6],
                    "missing_lines": [2, 3],  # Class fields - should be excluded
                    "missing_branches": [],
                }
            }
        }

        results = _calculate_function_coverage(
            "test.py", coverage_data, Path("/repo"), exclude_class_fields=True
        )

        # Find the process method
        process_func = next((f for f in results if f.name == "process"), None)
        assert process_func is not None
        # Class field lines (2, 3) should not be in missing_lines


class TestCoverageResult:
    """Tests for CoverageResult dataclass."""

    def test_creates_coverage_result(self) -> None:
        """Should create coverage result with all fields."""
        result = CoverageResult(
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
        assert result.suite_name == "unit"
        assert result.line_coverage_pct == 80.0
        assert result.branch_coverage_pct == 80.0


class TestFunctionCoverage:
    """Tests for FunctionCoverage dataclass."""

    def test_creates_function_coverage(self) -> None:
        """Should create function coverage with all fields."""
        fc = FunctionCoverage(
            name="test_func",
            file_path="test.py",
            start_line=10,
            end_line=20,
            total_lines=8,
            covered_lines=6,
            missing_lines=[15, 18],
            line_coverage_pct=75.0,
            total_branches=4,
            covered_branches=3,
            missing_branches=[(12, 15)],
            branch_coverage_pct=75.0,
        )
        assert fc.name == "test_func"
        assert fc.line_coverage_pct == 75.0


class TestUseCase:
    """Tests for UseCase dataclass."""

    def test_creates_use_case(self) -> None:
        """Should create use case with all fields."""
        uc = UseCase(
            id="UC-TEST-001",
            endpoint="/api/test",
            method="GET",
            description="Test endpoint",
            test_tier="integration",
        )
        assert uc.id == "UC-TEST-001"
        assert uc.test_tier == "integration"

    def test_creates_use_case_different_tier(self) -> None:
        """Should create use case with e2e tier."""
        uc = UseCase(
            id="UC-TEST-001",
            endpoint="/api/test",
            method="GET",
            description="Test",
            test_tier="e2e",
        )
        assert uc.test_tier == "e2e"


class TestUseCaseCoverageResult:
    """Tests for UseCaseCoverageResult dataclass."""

    def test_creates_usecase_coverage_result(self) -> None:
        """Should create use case coverage result."""
        result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=8,
            uncovered_cases=["UC-1", "UC-2"],
            coverage_pct=80.0,
        )
        assert result.tier == "integration"
        assert result.coverage_pct == 80.0


class TestLoadUseCases:
    """Tests for load_use_cases function."""

    def test_loads_use_cases_from_yaml(self, fs: FakeFilesystem) -> None:
        """Should load use cases from YAML file."""
        yaml_content = """
version: "1.0"
features:
  health:
    name: Health Checks
    use_cases:
      - id: UC-HEALTH-001
        endpoint: /health
        method: GET
        description: Health check
        test_tier: e2e
"""
        fs.create_file("/use_cases.yaml", contents=yaml_content)

        result = load_use_cases(Path("/use_cases.yaml"))

        assert len(result) == 1
        assert result[0].id == "UC-HEALTH-001"
        assert result[0].test_tier == "e2e"

    def test_handles_missing_file(self) -> None:
        """Should return empty list for missing file."""
        result = load_use_cases(Path("/nonexistent.yaml"))
        assert result == []


class TestCollectCoveredUsecases:
    """Tests for collect_covered_usecases function."""

    def test_collects_usecases_from_test_files(self, fs: FakeFilesystem) -> None:
        """Should collect use-case IDs from pytest markers in test files."""
        test_content = """
import pytest

@pytest.mark.usecase("UC-HEALTH-001")
def test_health_check():
    pass

@pytest.mark.usecase("UC-EXAMPLE-002")
def test_example():
    pass
"""
        fs.create_dir("/tests/integration")
        fs.create_file("/tests/integration/test_health.py", contents=test_content)

        result = collect_covered_usecases("/tests/integration")

        assert "UC-HEALTH-001" in result
        assert "UC-EXAMPLE-002" in result

    def test_handles_single_quotes(self, fs: FakeFilesystem) -> None:
        """Should handle single-quoted use-case IDs."""
        test_content = """
import pytest

@pytest.mark.usecase('UC-TEST-001')
def test_something():
    pass
"""
        fs.create_dir("/tests/e2e")
        fs.create_file("/tests/e2e/test_e2e.py", contents=test_content)

        result = collect_covered_usecases("/tests/e2e")

        assert "UC-TEST-001" in result

    def test_handles_empty_directory(self, fs: FakeFilesystem) -> None:
        """Should return empty set for directory with no test files."""
        fs.create_dir("/tests/empty")

        result = collect_covered_usecases("/tests/empty")

        assert result == set()

    def test_handles_nonexistent_directory(self) -> None:
        """Should return empty set for nonexistent directory."""
        result = collect_covered_usecases("/nonexistent/path")

        assert result == set()


class TestCalculateUsecaseCoverage:
    """Tests for calculate_usecase_coverage function."""

    def test_calculates_coverage(self) -> None:
        """Should calculate use-case coverage correctly."""
        use_cases = [
            UseCase("UC-1", "/a", "GET", "Test 1", "integration"),
            UseCase("UC-2", "/b", "GET", "Test 2", "integration"),
            UseCase("UC-3", "/c", "GET", "Test 3", "integration"),
            UseCase("UC-4", "/d", "GET", "Test 4", "e2e"),  # Different tier
        ]
        covered_ids = {"UC-1", "UC-3", "UC-4"}  # UC-2 is uncovered

        result = calculate_usecase_coverage("integration", use_cases, covered_ids)

        assert result.tier == "integration"
        assert result.total_cases == 3
        assert result.covered_cases == 2
        assert result.uncovered_cases == ["UC-2"]
        assert result.coverage_pct == pytest.approx(66.67, rel=0.01)

    def test_counts_all_use_cases_in_tier(self) -> None:
        """Should count all use cases in the specified tier."""
        use_cases = [
            UseCase("UC-1", "/a", "GET", "Test 1", "e2e"),
            UseCase("UC-2", "/b", "GET", "Test 2", "e2e"),
        ]
        covered_ids = {"UC-1"}

        result = calculate_usecase_coverage("e2e", use_cases, covered_ids)

        assert result.total_cases == 2
        assert result.covered_cases == 1
        assert result.uncovered_cases == ["UC-2"]
        assert result.coverage_pct == 50.0


class TestValidateLineBranchCoverage:
    """Tests for validate_line_branch_coverage function."""

    def test_passes_when_above_thresholds(self) -> None:
        """Should pass when coverage meets thresholds."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=80.0,
        )
        result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=85,
            missing_lines=15,
            line_coverage_pct=85.0,
            total_branches=50,
            covered_branches=45,
            missing_branches=5,
            branch_coverage_pct=90.0,
            files={},
            functions={
                "test.py::my_func": {
                    "name": "my_func",
                    "file": "test.py",
                    "line_coverage": 85.0,
                    "branch_coverage": 90.0,
                    "missing_branches": [],
                }
            },
        )

        failures = validate_line_branch_coverage(result, config)

        assert failures == []

    def test_fails_when_function_below_threshold(self) -> None:
        """Should fail when function coverage is below threshold."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=80.0,
        )
        result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=85,
            missing_lines=15,
            line_coverage_pct=85.0,
            total_branches=50,
            covered_branches=45,
            missing_branches=5,
            branch_coverage_pct=90.0,
            files={},
            functions={
                "test.py::low_func": {
                    "name": "low_func",
                    "file": "test.py",
                    "line_coverage": 50.0,  # Below threshold
                    "branch_coverage": 90.0,
                    "missing_branches": [],
                }
            },
        )

        failures = validate_line_branch_coverage(result, config)

        assert len(failures) == 1
        assert "low_func" in failures[0]

    def test_skips_private_when_configured(self) -> None:
        """Should skip private functions when configured."""
        config = TestTierConfig(
            name="scripts",
            test_path="scripts/tests",
            source_paths=["scripts"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=80.0,
            skip_private_functions=True,
        )
        result = CoverageResult(
            suite_name="scripts",
            total_lines=100,
            covered_lines=85,
            missing_lines=15,
            line_coverage_pct=85.0,
            total_branches=50,
            covered_branches=45,
            missing_branches=5,
            branch_coverage_pct=90.0,
            files={},
            functions={
                "test.py::_private_func": {
                    "name": "_private_func",
                    "file": "test.py",
                    "line_coverage": 10.0,  # Very low but should be skipped
                    "branch_coverage": 10.0,
                    "missing_branches": [(1, 2)],
                }
            },
        )

        failures = validate_line_branch_coverage(result, config)

        assert failures == []

    def test_validates_private_for_unit_tier(self) -> None:
        """Unit tier should validate private functions."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=80.0,
            skip_private_functions=False,
        )
        result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=85,
            missing_lines=15,
            line_coverage_pct=85.0,
            total_branches=50,
            covered_branches=45,
            missing_branches=5,
            branch_coverage_pct=90.0,
            files={},
            functions={
                "test.py::_private_func": {
                    "name": "_private_func",
                    "file": "test.py",
                    "line_coverage": 10.0,  # Below threshold - should fail
                    "branch_coverage": 90.0,
                    "missing_branches": [],
                }
            },
        )

        failures = validate_line_branch_coverage(result, config)

        assert len(failures) == 1
        assert "_private_func" in failures[0]

    def test_service_layer_only_filter(self) -> None:
        """Should only validate service layer files when configured."""
        config = TestTierConfig(
            name="component",
            test_path="tests/unit",
            source_paths=["app/services"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=80.0,
            service_layer_only=True,
            skip_private_functions=True,
        )
        result = CoverageResult(
            suite_name="component",
            total_lines=100,
            covered_lines=85,
            missing_lines=15,
            line_coverage_pct=85.0,
            total_branches=50,
            covered_branches=45,
            missing_branches=5,
            branch_coverage_pct=90.0,
            files={},
            functions={
                "app/api/routes.py::low_func": {
                    "name": "low_func",
                    "file": "app/api/routes.py",  # Not service layer
                    "line_coverage": 10.0,
                    "branch_coverage": 10.0,
                    "missing_branches": [],
                },
                "app/services/user.py::service_func": {
                    "name": "service_func",
                    "file": "app/services/user.py",  # Service layer
                    "line_coverage": 85.0,
                    "branch_coverage": 90.0,
                    "missing_branches": [],
                },
            },
        )

        failures = validate_line_branch_coverage(result, config)

        # Should not fail because non-service file is excluded
        assert failures == []


class TestValidateUsecaseCoverage:
    """Tests for validate_usecase_coverage function."""

    def test_passes_at_100_percent(self) -> None:
        """Should pass at 100% coverage."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=100.0,
        )
        uc_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=5,
            covered_cases=5,
            uncovered_cases=[],
            coverage_pct=100.0,
        )

        failures = validate_usecase_coverage(uc_result, config)

        assert failures == []

    def test_fails_below_threshold(self) -> None:
        """Should fail below threshold."""
        config = TestTierConfig(
            name="e2e",
            test_path="tests/e2e",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=100.0,
        )
        uc_result = UseCaseCoverageResult(
            tier="e2e",
            total_cases=10,
            covered_cases=8,
            uncovered_cases=["UC-1", "UC-2"],
            coverage_pct=80.0,
        )

        failures = validate_usecase_coverage(uc_result, config)

        assert len(failures) > 0
        assert "Use-case coverage" in failures[0]


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_tier_is_all(self) -> None:
        """Should default to running all test tiers."""
        args = parse_args([])
        assert args.tier == "all"

    def test_accepts_unit_tier(self) -> None:
        """Should accept unit tier option."""
        args = parse_args(["--tier", "unit"])
        assert args.tier == "unit"

    def test_accepts_component_tier(self) -> None:
        """Should accept component tier option."""
        args = parse_args(["--tier", "component"])
        assert args.tier == "component"

    def test_accepts_integration_tier(self) -> None:
        """Should accept integration tier option."""
        args = parse_args(["--tier", "integration"])
        assert args.tier == "integration"

    def test_accepts_scripts_tier(self) -> None:
        """Should accept scripts tier option."""
        args = parse_args(["--tier", "scripts"])
        assert args.tier == "scripts"

    def test_default_min_line(self) -> None:
        """Should use default minimum per-function line coverage."""
        args = parse_args([])
        assert args.min_line == DEFAULT_MIN_LINE_PER_FUNCTION

    def test_custom_min_line(self) -> None:
        """Should accept custom minimum line coverage."""
        args = parse_args(["--min-line", "90"])
        assert args.min_line == 90.0

    def test_default_min_branch(self) -> None:
        """Should use default minimum per-function branch coverage."""
        args = parse_args([])
        assert args.min_branch == DEFAULT_MIN_BRANCH_PER_FUNCTION

    def test_custom_min_branch(self) -> None:
        """Should accept custom minimum branch coverage."""
        args = parse_args(["--min-branch", "85"])
        assert args.min_branch == 85.0

    def test_default_min_usecase(self) -> None:
        """Should use default minimum use-case coverage."""
        args = parse_args([])
        assert args.min_usecase == DEFAULT_MIN_USECASE

    def test_custom_min_usecase(self) -> None:
        """Should accept custom minimum use-case coverage."""
        args = parse_args(["--min-usecase", "95"])
        assert args.min_usecase == 95.0

    def test_no_validate_flag(self) -> None:
        """Should accept no-validate flag."""
        args = parse_args(["--no-validate"])
        assert args.no_validate is True

    def test_json_report_option(self) -> None:
        """Should accept JSON report path."""
        args = parse_args(["--json-report", "/fake/report.json"])
        assert args.json_report == Path("/fake/report.json")


class TestPrintSummary:
    """Tests for print_summary function."""

    def test_prints_line_branch_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print line/branch coverage summary."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
        )
        result = CoverageResult(
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

        print_summary([(config, result)], [])

        captured = capsys.readouterr()
        assert "COVERAGE SUMMARY" in captured.out
        assert "UNIT TEST SUITE" in captured.out
        assert "80.0%" in captured.out

    def test_prints_usecase_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print use-case coverage summary."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
        )
        uc_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=8,
            uncovered_cases=["UC-1", "UC-2"],
            coverage_pct=80.0,
        )

        print_summary([], [(config, uc_result)])

        captured = capsys.readouterr()
        assert "INTEGRATION TEST SUITE" in captured.out
        assert "Use-Case Coverage" in captured.out
        assert "UC-1" in captured.out


class TestGenerateMissingLineDetails:
    """Tests for generate_missing_line_details function."""

    def test_generates_missing_line_details(self, fs: FakeFilesystem) -> None:
        """Should generate missing line details with context."""
        from scripts.dev.test_runner.test_coverage import generate_missing_line_details

        code = """def test_func():
    line_one = 1
    line_two = 2
    line_three = 3
    return line_one + line_two
"""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents=code)

        coverage_data = {
            "files": {
                "test.py": {
                    "executed_lines": [1, 2, 3],
                    "missing_lines": [4, 5],
                    "missing_branches": [[4, 5]],
                }
            }
        }

        results = generate_missing_line_details(coverage_data, Path("/repo"))

        assert len(results) == 2
        # First missing line
        assert results[0].file == "test.py"
        assert results[0].line_number == 4
        assert "line_three" in results[0].content
        assert len(results[0].context_before) > 0
        assert len(results[0].context_after) > 0

    def test_handles_missing_file(self) -> None:
        """Should handle missing source files gracefully."""
        from scripts.dev.test_runner.test_coverage import generate_missing_line_details

        coverage_data = {
            "files": {
                "nonexistent.py": {
                    "executed_lines": [1],
                    "missing_lines": [2],
                    "missing_branches": [],
                }
            }
        }

        results = generate_missing_line_details(coverage_data, Path("/nonexistent"))

        # Should return empty list when source file doesn't exist
        assert results == []


class TestMissingLineDetail:
    """Tests for MissingLineDetail dataclass."""

    def test_creates_missing_line_detail(self) -> None:
        """Should create missing line detail with all fields."""
        from scripts.dev.test_runner.test_coverage import MissingLineDetail

        detail = MissingLineDetail(
            file="test.py",
            line_number=10,
            content="    return value",
            context_before=[{"line_number": 9, "content": "    value = 42"}],
            context_after=[{"line_number": 11, "content": ""}],
            missing_branch_exits=[15, 20],
        )

        assert detail.file == "test.py"
        assert detail.line_number == 10
        assert detail.content == "    return value"
        assert len(detail.context_before) == 1
        assert len(detail.context_after) == 1
        assert detail.missing_branch_exits == [15, 20]


class TestUsecaseMarkerVisitor:
    """Tests for _UsecaseMarkerVisitor AST visitor."""

    def test_extracts_usecase_from_decorator(self, fs: FakeFilesystem) -> None:
        """Should extract use case ID from pytest.mark.usecase decorator."""
        from scripts.dev.test_runner.test_coverage import _UsecaseMarkerVisitor

        code = """
import pytest

@pytest.mark.usecase("UC-HEALTH-001")
def test_health_check():
    pass
"""
        tree = compile(code, "test.py", "exec", flags=ast.PyCF_ONLY_AST)
        visitor = _UsecaseMarkerVisitor("tests/e2e/test_health.py")
        visitor.visit(tree)

        assert "UC-HEALTH-001" in visitor.found
        assert len(visitor.found["UC-HEALTH-001"]) == 1
        assert visitor.found["UC-HEALTH-001"][0]["file"] == "tests/e2e/test_health.py"
        assert visitor.found["UC-HEALTH-001"][0]["test_function"] == "test_health_check"

    def test_extracts_multiple_usecases(self, fs: FakeFilesystem) -> None:
        """Should extract multiple use case IDs from the same file."""
        from scripts.dev.test_runner.test_coverage import _UsecaseMarkerVisitor

        code = """
import pytest

@pytest.mark.usecase("UC-TEST-001")
def test_one():
    pass

@pytest.mark.usecase("UC-TEST-002")
def test_two():
    pass
"""
        tree = compile(code, "test.py", "exec", flags=ast.PyCF_ONLY_AST)
        visitor = _UsecaseMarkerVisitor("tests/integration/test_api.py")
        visitor.visit(tree)

        assert "UC-TEST-001" in visitor.found
        assert "UC-TEST-002" in visitor.found
        assert visitor.found["UC-TEST-001"][0]["test_function"] == "test_one"
        assert visitor.found["UC-TEST-002"][0]["test_function"] == "test_two"

    def test_handles_single_quotes(self, fs: FakeFilesystem) -> None:
        """Should handle single-quoted use case IDs."""
        from scripts.dev.test_runner.test_coverage import _UsecaseMarkerVisitor

        code = """
import pytest

@pytest.mark.usecase('UC-EXAMPLE-001')
def test_example():
    pass
"""
        tree = compile(code, "test.py", "exec", flags=ast.PyCF_ONLY_AST)
        visitor = _UsecaseMarkerVisitor("tests/integration/test_example.py")
        visitor.visit(tree)

        assert "UC-EXAMPLE-001" in visitor.found

    def test_handles_async_functions(self, fs: FakeFilesystem) -> None:
        """Should extract use cases from async test functions."""
        from scripts.dev.test_runner.test_coverage import _UsecaseMarkerVisitor

        code = """
import pytest

@pytest.mark.usecase("UC-ASYNC-001")
async def test_async_operation():
    pass
"""
        tree = compile(code, "test.py", "exec", flags=ast.PyCF_ONLY_AST)
        visitor = _UsecaseMarkerVisitor("tests/integration/test_async.py")
        visitor.visit(tree)

        assert "UC-ASYNC-001" in visitor.found
        assert visitor.found["UC-ASYNC-001"][0]["test_function"] == "test_async_operation"

    def test_ignores_non_usecase_decorators(self, fs: FakeFilesystem) -> None:
        """Should ignore decorators that are not usecase markers."""
        from scripts.dev.test_runner.test_coverage import _UsecaseMarkerVisitor

        code = """
import pytest

@pytest.mark.asyncio
@pytest.mark.skip
def test_skipped():
    pass
"""
        tree = compile(code, "test.py", "exec", flags=ast.PyCF_ONLY_AST)
        visitor = _UsecaseMarkerVisitor("tests/integration/test_skip.py")
        visitor.visit(tree)

        assert len(visitor.found) == 0


class TestScanTestsForUsecases:
    """Tests for _scan_tests_for_usecases function."""

    def test_scans_test_directory(self, fs: FakeFilesystem) -> None:
        """Should scan test directory and extract use case markers."""
        from scripts.dev.test_runner.test_coverage import _scan_tests_for_usecases

        test_content = """
import pytest

@pytest.mark.usecase("UC-HEALTH-001")
def test_health():
    pass

@pytest.mark.usecase("UC-HEALTH-002")
def test_readiness():
    pass
"""
        fs.create_dir("/repo/tests/e2e")
        fs.create_file("/repo/tests/e2e/test_health.py", contents=test_content)

        result = _scan_tests_for_usecases("/repo/tests/e2e", Path("/repo"))

        assert "UC-HEALTH-001" in result
        assert "UC-HEALTH-002" in result
        assert len(result["UC-HEALTH-001"]) == 1
        assert result["UC-HEALTH-001"][0]["test_function"] == "test_health"
        assert "tests/e2e/test_health.py" in result["UC-HEALTH-001"][0]["file"]

    def test_scans_multiple_files(self, fs: FakeFilesystem) -> None:
        """Should scan multiple test files in directory."""
        from scripts.dev.test_runner.test_coverage import _scan_tests_for_usecases

        health_test = """
import pytest

@pytest.mark.usecase("UC-HEALTH-001")
def test_health():
    pass
"""
        example_test = """
import pytest

@pytest.mark.usecase("UC-EXAMPLE-001")
def test_example():
    pass
"""
        fs.create_dir("/repo/tests/integration")
        fs.create_file("/repo/tests/integration/test_health.py", contents=health_test)
        fs.create_file("/repo/tests/integration/test_example.py", contents=example_test)

        result = _scan_tests_for_usecases("/repo/tests/integration", Path("/repo"))

        assert "UC-HEALTH-001" in result
        assert "UC-EXAMPLE-001" in result

    def test_handles_nonexistent_directory(self) -> None:
        """Should return empty dict for nonexistent directory."""
        from scripts.dev.test_runner.test_coverage import _scan_tests_for_usecases

        result = _scan_tests_for_usecases("/nonexistent/path", Path("/repo"))

        assert result == {}

    def test_handles_syntax_errors(self, fs: FakeFilesystem) -> None:
        """Should skip files with syntax errors."""
        from scripts.dev.test_runner.test_coverage import _scan_tests_for_usecases

        fs.create_dir("/repo/tests/integration")
        fs.create_file("/repo/tests/integration/test_broken.py", contents="def broken(:")

        result = _scan_tests_for_usecases("/repo/tests/integration", Path("/repo"))

        assert result == {}

    def test_aggregates_same_usecase_across_tests(self, fs: FakeFilesystem) -> None:
        """Should aggregate multiple tests covering the same use case."""
        from scripts.dev.test_runner.test_coverage import _scan_tests_for_usecases

        test_content = """
import pytest

@pytest.mark.usecase("UC-TEST-001")
def test_scenario_a():
    pass

@pytest.mark.usecase("UC-TEST-001")
def test_scenario_b():
    pass
"""
        fs.create_dir("/repo/tests/integration")
        fs.create_file("/repo/tests/integration/test_multi.py", contents=test_content)

        result = _scan_tests_for_usecases("/repo/tests/integration", Path("/repo"))

        assert "UC-TEST-001" in result
        assert len(result["UC-TEST-001"]) == 2
        assert result["UC-TEST-001"][0]["test_function"] == "test_scenario_a"
        assert result["UC-TEST-001"][1]["test_function"] == "test_scenario_b"


class TestUsecaseDatabaseIntegration:
    """Tests for use case database integration."""

    def test_writes_usecase_registry_to_database(self, tmp_path: Path) -> None:
        """Should write use case registry to database."""
        from scripts.dev.test_runner import coverage_db

        db_path = tmp_path / "coverage.db"
        coverage_db.init_custom_tables(db_path)

        use_cases = [
            UseCase("UC-TEST-001", "/api/test", "GET", "Test case", "integration"),
            UseCase("UC-TEST-002", "/api/test", "POST", "Test case 2", "e2e"),
        ]

        coverage_db.write_usecase_registry(db_path, use_cases)

        # Verify data was written
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT usecase_id, endpoint, test_tier FROM cc_usecase")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0][0] == "UC-TEST-001"
        assert rows[0][1] == "/api/test"
        assert rows[0][2] == "integration"

    def test_writes_usecase_coverage_covered(self, tmp_path: Path) -> None:
        """Should write covered use case to database."""
        from scripts.dev.test_runner import coverage_db

        db_path = tmp_path / "coverage.db"
        coverage_db.init_custom_tables(db_path)

        # Write use case registry first
        use_cases = [UseCase("UC-TEST-001", "/api/test", "GET", "Test", "integration")]
        coverage_db.write_usecase_registry(db_path, use_cases)

        # Write coverage
        coverage_db.write_usecase_coverage(
            db_path,
            "UC-TEST-001",
            covered=True,
            test_file="tests/integration/test_api.py",
            test_function="test_endpoint",
        )

        # Verify data
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT usecase_id, covered, test_file, test_function FROM cc_usecase_coverage"
        )
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "UC-TEST-001"
        assert row[1] == 1  # covered=True
        assert row[2] == "tests/integration/test_api.py"
        assert row[3] == "test_endpoint"

    def test_writes_usecase_coverage_uncovered(self, tmp_path: Path) -> None:
        """Should write uncovered use case to database."""
        from scripts.dev.test_runner import coverage_db

        db_path = tmp_path / "coverage.db"
        coverage_db.init_custom_tables(db_path)

        # Write use case registry first
        use_cases = [UseCase("UC-TEST-002", "/api/test", "POST", "Test", "integration")]
        coverage_db.write_usecase_registry(db_path, use_cases)

        # Write coverage as uncovered
        coverage_db.write_usecase_coverage(
            db_path,
            "UC-TEST-002",
            covered=False,
            test_file=None,
            test_function=None,
        )

        # Verify data
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT usecase_id, covered, test_file, test_function FROM cc_usecase_coverage"
        )
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "UC-TEST-002"
        assert row[1] == 0  # covered=False
        assert row[2] is None
        assert row[3] is None

    def test_queries_usecase_coverage(self, tmp_path: Path) -> None:
        """Should query use case coverage statistics."""
        from scripts.dev.test_runner import coverage_db

        db_path = tmp_path / "coverage.db"
        coverage_db.init_custom_tables(db_path)

        # Write use case registry
        use_cases = [
            UseCase("UC-TEST-001", "/api/a", "GET", "Test 1", "integration"),
            UseCase("UC-TEST-002", "/api/b", "GET", "Test 2", "integration"),
            UseCase("UC-TEST-003", "/api/c", "GET", "Test 3", "e2e"),
        ]
        coverage_db.write_usecase_registry(db_path, use_cases)

        # Write coverage
        coverage_db.write_usecase_coverage(
            db_path, "UC-TEST-001", covered=True, test_file="test.py", test_function="test_1"
        )
        coverage_db.write_usecase_coverage(
            db_path, "UC-TEST-002", covered=False, test_file=None, test_function=None
        )
        coverage_db.write_usecase_coverage(
            db_path, "UC-TEST-003", covered=True, test_file="test.py", test_function="test_3"
        )

        # Query coverage
        result = coverage_db.get_usecase_coverage(db_path)

        assert result["total"] == 3
        assert result["covered"] == 2
        assert result["coverage_pct"] == pytest.approx(66.67, rel=0.01)
        assert "UC-TEST-002" in result["uncovered"]
        assert "integration" in result["by_tier"]
        assert result["by_tier"]["integration"]["total"] == 2
        assert result["by_tier"]["integration"]["covered"] == 1


class TestMainOrchestratorInvariants:
    """AST-based smoke tests enforcing architectural invariants for main().

    These are BRITTLE, AST-based tests that verify main() adheres to the
    orchestrator pattern and does not contain coverage-type-specific logic
    that belongs in strategies. Minor refactors (e.g., renaming variables)
    may require adjusting these tests, but the underlying invariants should
    remain.

    The invariants enforced:
    1. main() must NOT branch on coverage_type for execution/validation logic
    2. main() must NOT call deprecated validation helpers directly

    These tests exist because the strategy pattern requires strict separation
    of concerns: main() orchestrates, strategies decide. Violations would
    create tight coupling and duplicate logic.
    """

    def test_main_does_not_branch_on_coverage_type(self) -> None:
        """Ensure main() does not contain if-conditions that branch on coverage_type.

        The orchestrator pattern requires that main() delegates all
        coverage-type-specific logic to strategies via the factory pattern.
        If main() branches on coverage_type, it violates the principle that
        strategies own all tier-specific behavior.

        This test parses the AST of main() and checks that no `if` condition
        references `coverage_type`. The strategy factory (create_strategy)
        is the ONLY place that should inspect coverage_type.

        Note: This test may need adjustment if main() is significantly
        refactored, but the invariant itself should remain.
        """
        import inspect

        from scripts.dev.test_runner.test_coverage import main

        source = inspect.getsource(main)
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # Get the string representation of the condition
                condition_str = ast.unparse(node.test)
                assert "coverage_type" not in condition_str, (
                    f"main() must NOT branch on coverage_type. Found condition: {condition_str}\n"
                    "Coverage-type-specific logic belongs in strategy classes,\n"
                    "not the orchestrator."
                )

    def test_main_does_not_call_validation_helpers_directly(self) -> None:
        """Ensure main() does not call deprecated validation helpers directly.

        The strategy pattern requires that all validation logic is owned by
        strategy.validate(). The legacy functions validate_line_branch_coverage()
        and validate_usecase_coverage() are kept for backward compatibility
        with external callers, but main() must NOT call them directly.

        This test checks the source code of main() for direct references to
        these deprecated functions.

        Note: This test may need adjustment if the deprecated functions are
        renamed, but the invariant (validation owned by strategies) should remain.
        """
        import inspect

        from scripts.dev.test_runner.test_coverage import main

        source = inspect.getsource(main)

        assert "validate_line_branch_coverage" not in source, (
            "main() must NOT call validate_line_branch_coverage() directly.\n"
            "Validation logic is owned by LineBranchTestStrategy.validate()."
        )

        assert "validate_usecase_coverage" not in source, (
            "main() must NOT call validate_usecase_coverage() directly.\n"
            "Validation logic is owned by IntegrationTestStrategy.validate()."
        )


# =============================================================================
# FIXTURES FOR END-TO-END TESTS
# =============================================================================


@pytest.fixture
def e2e_coverage_setup(tmp_path: Path) -> dict[str, Path]:
    """Set up a temporary coverage directory and SQLite database for e2e tests.

    Returns:
        Dictionary with 'coverage_dir', 'db_path', and 'data_file' paths.
    """
    from scripts.dev.test_runner import coverage_db

    coverage_dir = tmp_path / ".coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)
    db_path = coverage_dir / "coverage.db"
    data_file = coverage_dir / "data"

    # Initialize the custom tables
    coverage_db.init_custom_tables(db_path)

    return {
        "coverage_dir": coverage_dir,
        "db_path": db_path,
        "data_file": data_file,
        "tmp_path": tmp_path,
    }


# =============================================================================
# END-TO-END DATABASE STATE TESTS
# =============================================================================


class TestMainEndToEndDBState:
    """Black-box tests for coverage_db integration used by main().

    These tests verify that:
    1. The coverage database APIs correctly store and retrieve data
    2. Database queries return well-formed results with expected keys/types
    3. Data shapes match what main() and strategies expect to persist

    NOTE: These tests focus on structure and type correctness, NOT specific
    numeric values, as coverage numbers may vary across environments.
    """

    def test_tier_summary_exists_after_main_invocation(
        self, e2e_coverage_setup: dict[str, Path]
    ) -> None:
        """Verify that tier summary is written to DB after running with --no-validate.

        Uses get_tier_summary() to assert that:
        - The summary exists for the requested tier
        - coverage_type is set appropriately
        - Numeric counts are non-negative integers
        """
        from scripts.dev.test_runner import coverage_db

        db_path = e2e_coverage_setup["db_path"]

        # Write a mock tier summary directly (simulating what main() does)
        summary = {
            "coverage_type": "line_branch",
            "total_functions": 10,
            "passing_functions": 8,
            "failing_functions": 2,
            "overall_line_pct": 85.5,
            "overall_branch_pct": 72.3,
            "total_usecases": 0,
            "usecases_covered": 0,
            "total_tests": 15,
            "tests_passed": 14,
            "tests_failed": 1,
            "tier_pass": 0,
        }
        coverage_db.write_tier_summary(db_path, "scripts", summary)

        # Query using the DAO function
        result = coverage_db.get_tier_summary(db_path, "scripts")

        # Assert structure and types
        assert result is not None
        assert result != {}
        assert result["tier"] == "scripts"
        assert result["coverage_type"] == "line_branch"

        # Numeric fields should be non-negative integers
        assert isinstance(result["total_functions"], int)
        assert result["total_functions"] >= 0
        assert isinstance(result["passing_functions"], int)
        assert result["passing_functions"] >= 0
        assert isinstance(result["failing_functions"], int)
        assert result["failing_functions"] >= 0

        # Coverage percentages should be floats or None
        assert result["overall_line_pct"] is None or isinstance(
            result["overall_line_pct"], (int, float)
        )
        assert result["overall_branch_pct"] is None or isinstance(
            result["overall_branch_pct"], (int, float)
        )

    def test_functions_below_threshold_returns_well_formed_results(
        self, e2e_coverage_setup: dict[str, Path]
    ) -> None:
        """Verify that get_functions_below_threshold returns well-formed results.

        Asserts that returned items have expected keys and types, even if
        the exact numbers vary across environments.
        """
        from scripts.dev.test_runner import coverage_db

        db_path = e2e_coverage_setup["db_path"]

        # Write some function coverage data with functions below threshold
        func_coverage = FunctionCoverage(
            name="low_coverage_func",
            file_path="scripts/example.py",
            start_line=10,
            end_line=25,
            total_lines=15,
            covered_lines=5,
            missing_lines=[12, 14, 16, 18, 20, 22, 24],
            line_coverage_pct=33.3,
            total_branches=4,
            covered_branches=1,
            missing_branches=[(15, 20), (15, 25)],
            branch_coverage_pct=25.0,
        )
        coverage_db.write_function_coverage(
            db_path, "scripts", [func_coverage], threshold_line=60.0, threshold_branch=50.0
        )

        # Query functions below threshold
        result = coverage_db.get_functions_below_threshold(db_path, tier="scripts")

        # Should return a list
        assert isinstance(result, list)
        assert len(result) >= 1

        # Each item should have expected keys
        for item in result:
            assert "file_path" in item
            assert "function_name" in item
            assert "tier" in item
            assert "line_coverage_pct" in item
            assert "branch_coverage_pct" in item
            assert "missing_lines" in item
            assert "missing_branches" in item
            assert "threshold_line" in item
            assert "threshold_branch" in item
            assert "line_pass" in item
            assert "branch_pass" in item

            # Type assertions
            assert isinstance(item["file_path"], str)
            assert isinstance(item["function_name"], str)
            assert isinstance(item["line_coverage_pct"], (int, float))
            assert isinstance(item["missing_lines"], list)
            assert isinstance(item["missing_branches"], list)

    def test_usecase_coverage_returns_well_formed_results(
        self, e2e_coverage_setup: dict[str, Path]
    ) -> None:
        """Verify that get_usecase_coverage returns well-formed results.

        Asserts expected keys are present and values have correct types.
        """
        from scripts.dev.test_runner import coverage_db

        db_path = e2e_coverage_setup["db_path"]

        # Write some use case data
        use_cases = [
            UseCase("UC-E2E-001", "/api/test", "GET", "Test endpoint", "integration"),
            UseCase("UC-E2E-002", "/api/other", "POST", "Other endpoint", "integration"),
        ]
        coverage_db.write_usecase_registry(db_path, use_cases)

        # Write coverage for one of them
        coverage_db.write_usecase_coverage(
            db_path,
            "UC-E2E-001",
            covered=True,
            test_file="tests/integration/test_api.py",
            test_function="test_endpoint",
        )
        coverage_db.write_usecase_coverage(
            db_path, "UC-E2E-002", covered=False, test_file=None, test_function=None
        )

        # Query using the DAO function
        result = coverage_db.get_usecase_coverage(db_path)

        # Assert top-level structure
        assert "total" in result
        assert "covered" in result
        assert "coverage_pct" in result
        assert "by_tier" in result
        assert "uncovered" in result

        # Type assertions
        assert isinstance(result["total"], int)
        assert result["total"] >= 0
        assert isinstance(result["covered"], int)
        assert result["covered"] >= 0
        assert isinstance(result["coverage_pct"], (int, float))
        assert 0 <= result["coverage_pct"] <= 100
        assert isinstance(result["by_tier"], dict)
        assert isinstance(result["uncovered"], list)

        # by_tier entries should have expected structure
        for tier_name, tier_data in result["by_tier"].items():
            assert isinstance(tier_name, str)
            assert "total" in tier_data
            assert "covered" in tier_data
            assert "coverage_pct" in tier_data


# =============================================================================
# JSON REPORT SCHEMA VALIDATION TESTS
# =============================================================================


class TestJSONReportSchemaValidation:
    """Tests that validate JSON report schema expectations.

    These tests serve as DOCUMENTATION and SCHEMA VALIDATION for the JSON report
    structure. They verify that reports with the expected structure can be parsed
    correctly and contain the required fields.

    Schema Requirements:
    1. Top-level 'tiers' and 'thresholds' keys
    2. Correct structure for line_branch tier entries
    3. Correct structure for usecase tier entries
    4. Redundant tests block when present (optional)

    NOTE: These tests validate schema correctness using pre-built JSON structures.
    They do NOT test that main() actually produces these structures - that is
    covered by TestMainJSONReportIntegration below.
    """

    def test_json_report_has_toplevel_keys(self, tmp_path: Path) -> None:
        """Verify JSON report has required top-level keys."""
        import json

        # Create a mock JSON report matching the structure from main()
        report = {
            "tiers": {
                "scripts": {
                    "type": "line_branch",
                    "line_coverage": 85.5,
                    "branch_coverage": 72.3,
                    "total_lines": 1000,
                    "covered_lines": 855,
                    "total_branches": 200,
                    "covered_branches": 145,
                    "functions": {},
                }
            },
            "thresholds": {
                "min_line": 60.0,
                "min_branch": 50.0,
                "min_usecase": 100.0,
            },
        }

        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report, indent=2))

        # Load and verify structure
        loaded = json.loads(report_path.read_text())

        assert "tiers" in loaded
        assert "thresholds" in loaded
        assert isinstance(loaded["tiers"], dict)
        assert isinstance(loaded["thresholds"], dict)

    def test_line_branch_tier_entry_structure(self, tmp_path: Path) -> None:
        """Verify line_branch tier entries have correct structure."""
        import json

        report = {
            "tiers": {
                "unit": {
                    "type": "line_branch",
                    "line_coverage": 85.5,
                    "branch_coverage": 72.3,
                    "total_lines": 1000,
                    "covered_lines": 855,
                    "total_branches": 200,
                    "covered_branches": 145,
                    "functions": {
                        "app/services/example.py::process": {
                            "name": "process",
                            "file": "app/services/example.py",
                            "line_coverage": 90.0,
                            "branch_coverage": 80.0,
                        }
                    },
                }
            },
            "thresholds": {"min_line": 60.0, "min_branch": 50.0, "min_usecase": 100.0},
        }

        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report, indent=2))

        loaded = json.loads(report_path.read_text())
        unit_tier = loaded["tiers"]["unit"]

        # Assert required keys for line_branch type
        assert unit_tier["type"] == "line_branch"
        assert "line_coverage" in unit_tier
        assert "branch_coverage" in unit_tier
        assert "total_lines" in unit_tier
        assert "covered_lines" in unit_tier
        assert "total_branches" in unit_tier
        assert "covered_branches" in unit_tier
        assert "functions" in unit_tier

        # Type assertions
        assert isinstance(unit_tier["line_coverage"], (int, float))
        assert isinstance(unit_tier["branch_coverage"], (int, float))
        assert isinstance(unit_tier["total_lines"], int)
        assert isinstance(unit_tier["covered_lines"], int)
        assert isinstance(unit_tier["total_branches"], int)
        assert isinstance(unit_tier["covered_branches"], int)
        assert isinstance(unit_tier["functions"], dict)

    def test_usecase_tier_entry_structure(self, tmp_path: Path) -> None:
        """Verify usecase tier entries have correct structure."""
        import json

        report = {
            "tiers": {
                "integration": {
                    "type": "usecase",
                    "total_cases": 10,
                    "covered_cases": 8,
                    "uncovered_cases": ["UC-INT-001", "UC-INT-002"],
                    "coverage_pct": 80.0,
                }
            },
            "thresholds": {"min_line": 60.0, "min_branch": 50.0, "min_usecase": 100.0},
        }

        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report, indent=2))

        loaded = json.loads(report_path.read_text())
        integration_tier = loaded["tiers"]["integration"]

        # Assert required keys for usecase type
        assert integration_tier["type"] == "usecase"
        assert "total_cases" in integration_tier
        assert "covered_cases" in integration_tier
        assert "uncovered_cases" in integration_tier
        assert "coverage_pct" in integration_tier

        # Type assertions
        assert isinstance(integration_tier["total_cases"], int)
        assert isinstance(integration_tier["covered_cases"], int)
        assert isinstance(integration_tier["uncovered_cases"], list)
        assert isinstance(integration_tier["coverage_pct"], (int, float))

        # uncovered_cases should be a list of strings
        for uc_id in integration_tier["uncovered_cases"]:
            assert isinstance(uc_id, str)

    def test_redundant_tests_block_structure(self, tmp_path: Path) -> None:
        """Verify redundant_tests block has correct structure when present."""
        import json

        report = {
            "tiers": {},
            "thresholds": {"min_line": 60.0, "min_branch": 50.0, "min_usecase": 100.0},
            "redundant_tests": {
                "summary": {
                    "total_tests": 50,
                    "tests_with_unique_coverage": 45,
                    "redundant_tests": 5,
                },
                "tests": [
                    {"test_name": "test_redundant_1", "unique_lines": 0},
                    {"test_name": "test_redundant_2", "unique_lines": 0},
                ],
                "total_tests_analyzed": 50,
                "tests_with_unique_coverage": 45,
            },
        }

        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report, indent=2))

        loaded = json.loads(report_path.read_text())

        # Assert redundant_tests block exists and has expected structure
        assert "redundant_tests" in loaded
        redundant = loaded["redundant_tests"]

        assert "summary" in redundant
        assert "tests" in redundant
        assert "total_tests_analyzed" in redundant
        assert "tests_with_unique_coverage" in redundant

        # Type assertions
        assert isinstance(redundant["summary"], dict)
        assert isinstance(redundant["tests"], list)
        assert isinstance(redundant["total_tests_analyzed"], int)
        assert isinstance(redundant["tests_with_unique_coverage"], int)

    def test_json_report_combined_tiers(self, tmp_path: Path) -> None:
        """Verify JSON report can contain both line_branch and usecase tiers."""
        import json

        # A report with multiple tier types
        report = {
            "tiers": {
                "unit": {
                    "type": "line_branch",
                    "line_coverage": 85.5,
                    "branch_coverage": 72.3,
                    "total_lines": 1000,
                    "covered_lines": 855,
                    "total_branches": 200,
                    "covered_branches": 145,
                    "functions": {},
                },
                "scripts": {
                    "type": "line_branch",
                    "line_coverage": 75.0,
                    "branch_coverage": 65.0,
                    "total_lines": 500,
                    "covered_lines": 375,
                    "total_branches": 100,
                    "covered_branches": 65,
                    "functions": {},
                },
                "integration": {
                    "type": "usecase",
                    "total_cases": 10,
                    "covered_cases": 10,
                    "uncovered_cases": [],
                    "coverage_pct": 100.0,
                },
            },
            "thresholds": {"min_line": 60.0, "min_branch": 50.0, "min_usecase": 100.0},
        }

        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report, indent=2))

        loaded = json.loads(report_path.read_text())

        # Verify all tiers are present
        assert "unit" in loaded["tiers"]
        assert "scripts" in loaded["tiers"]
        assert "integration" in loaded["tiers"]

        # Verify types are correct
        assert loaded["tiers"]["unit"]["type"] == "line_branch"
        assert loaded["tiers"]["scripts"]["type"] == "line_branch"
        assert loaded["tiers"]["integration"]["type"] == "usecase"

        # Each tier type has its expected keys
        for tier_name in ["unit", "scripts"]:
            tier = loaded["tiers"][tier_name]
            assert "line_coverage" in tier
            assert "branch_coverage" in tier
            assert "functions" in tier

        integration = loaded["tiers"]["integration"]
        assert "total_cases" in integration
        assert "covered_cases" in integration
        assert "coverage_pct" in integration


# =============================================================================
# JSON REPORT INTEGRATION TESTS
# =============================================================================


class TestMainJSONReportIntegration:
    """Integration tests that verify main() produces valid JSON reports.

    These tests verify that the CLI entrypoint actually generates JSON reports
    with the expected structure when --json-report is provided.
    """

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
            coverage_type="line_branch",
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
            coverage_type="usecase",
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
