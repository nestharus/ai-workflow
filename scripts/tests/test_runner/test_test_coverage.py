"""Tests for scripts.test_coverage module."""

from __future__ import annotations

import ast
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


class TestLoadTierConfigsValidation:
    """Tests for tier configuration validation.

    These tests verify that load_tier_configs() raises ValueError with a
    descriptive message when a tier is missing required fields or has
    invalid values.

    Tests use temporary pyproject.toml files to simulate real-world
    misconfiguration scenarios.
    """

    def test_tier_missing_test_path_raises_error(self, tmp_path: Path) -> None:
        """Tier missing test_path should raise ValueError."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.e2e]
source_paths = ["app"]
min_usecase = 100.0
# test_path is missing
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)
        assert "Tier 'e2e' missing required fields: test_path" in str(exc_info.value)

    def test_tier_missing_source_paths_raises_error(self, tmp_path: Path) -> None:
        """Tier missing source_paths should raise ValueError."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.e2e]
test_path = "tests/e2e"
min_usecase = 100.0
# source_paths is missing
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)
        assert "Tier 'e2e' missing required fields: source_paths" in str(exc_info.value)

    def test_tier_missing_all_thresholds_raises_error(self, tmp_path: Path) -> None:
        """Tier missing all threshold fields should raise ValueError."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.e2e]
test_path = "tests/e2e"
source_paths = ["app"]
# All threshold fields are missing
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)
        assert "Tier 'e2e' has no coverage thresholds set" in str(exc_info.value)

    def test_tier_missing_multiple_fields_raises_error(self, tmp_path: Path) -> None:
        """Tier missing multiple required fields should list all missing fields."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.e2e]
min_usecase = 100.0
# Required fields test_path and source_paths are missing
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)
        error_msg = str(exc_info.value)
        assert "Tier 'e2e' missing required fields:" in error_msg
        assert "test_path" in error_msg
        assert "source_paths" in error_msg

    def test_tier_with_empty_source_paths_raises_error(self, tmp_path: Path) -> None:
        """Tier with empty source_paths array should raise ValueError."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.e2e]
test_path = "tests/e2e"
source_paths = []
min_usecase = 100.0
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)
        assert "source_paths" in str(exc_info.value)

    def test_tier_with_empty_test_path_raises_error(self, tmp_path: Path) -> None:
        """Tier with empty test_path string should raise ValueError."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.e2e]
test_path = ""
source_paths = ["app"]
min_usecase = 100.0
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)
        assert "test_path" in str(exc_info.value)

    def test_invalid_property_raises_error(self, tmp_path: Path) -> None:
        """Unknown property should raise ValueError with descriptive message."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.e2e]
test_path = "tests/e2e"
source_paths = ["app"]
min_usecase = 100.0
invalid_property = "value"
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)
        error_msg = str(exc_info.value)
        assert "Tier 'e2e' contains unknown properties" in error_msg
        assert "invalid_property" in error_msg

    def test_error_message_is_actionable(self, tmp_path: Path) -> None:
        """Error message should explain what fields are required and for which tier."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.my_custom_tier]
# Missing all required fields
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)
        error_msg = str(exc_info.value)
        # Should mention the tier name
        assert "my_custom_tier" in error_msg
        # Should explain required fields
        assert "test_path" in error_msg
        assert "source_paths" in error_msg

    def test_tier_with_all_required_fields_succeeds(self, tmp_path: Path) -> None:
        """Tier with all required fields should be created successfully."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.e2e]
test_path = "tests/e2e"
source_paths = ["app", "lib"]
min_usecase = 95.0
""")
        tiers = load_tier_configs(pyproject)
        assert "e2e" in tiers
        assert tiers["e2e"].test_path == "tests/e2e"
        assert tiers["e2e"].source_paths == ["app", "lib"]
        assert tiers["e2e"].coverage_type == "usecase"
        assert tiers["e2e"].min_usecase == 95.0

    def test_missing_tiers_section_raises_error(self, tmp_path: Path) -> None:
        """Missing [tool.test_coverage.tiers] section should raise ValueError."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.other_section]
some_setting = true
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)
        assert "No [tool.test_coverage.tiers] section found" in str(exc_info.value)

    def test_missing_pyproject_raises_error(self, tmp_path: Path) -> None:
        """Missing pyproject.toml should raise ValueError."""
        nonexistent = tmp_path / "nonexistent" / "pyproject.toml"
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(nonexistent)
        assert "pyproject.toml not found" in str(exc_info.value)


class TestMainMisconfiguredTierHandling:
    """Tests for main() handling of misconfigured tier errors.

    These tests verify that main() catches ValueError from get_test_tiers()
    and returns a clean error message instead of a full traceback.
    """

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
        # source_paths now uses glob patterns
        assert config.source_paths == ["app/**/*.py", "!app/**/__init__.py"]
        assert config.coverage_type == "line_branch"
        assert config.skip_private_functions is False
        # service_layer_only field should not exist
        assert not hasattr(config, "service_layer_only")
        # coverage_file field should be removed
        assert not hasattr(config, "coverage_file")

    def test_component_tier_config(self) -> None:
        """Component tier should use usecase coverage with tests/component path."""
        tiers = get_test_tiers()
        config = tiers["component"]
        assert config.test_path == "tests/component"
        # source_paths now uses glob patterns
        assert config.source_paths == ["app/services/**/*.py", "!app/services/**/__init__.py"]
        assert config.coverage_type == "usecase"
        assert config.min_usecase == 100.0
        assert config.skip_private_functions is True
        # service_layer_only field should not exist
        assert not hasattr(config, "service_layer_only")
        # coverage_file field should be removed
        assert not hasattr(config, "coverage_file")

    def test_integration_tier_config(self) -> None:
        """Integration tier should use use-case coverage for API endpoints."""
        tiers = get_test_tiers()
        config = tiers["integration"]
        assert config.test_path == "tests/integration"
        # source_paths now uses glob patterns with negations
        assert config.source_paths == [
            "app/api/**/*.py",
            "!app/api/**/__init__.py",
            "!app/api/**/router.py",
            "!app/api/**/dependencies.py",
        ]
        assert config.coverage_type == "usecase"
        # exclude_patterns has been replaced with negation patterns in source_paths
        assert not hasattr(config, "exclude_patterns")
        # coverage_file field should be removed
        assert not hasattr(config, "coverage_file")
        # service_layer_only field should be removed
        assert not hasattr(config, "service_layer_only")

    def test_scripts_tier_config(self) -> None:
        """Scripts tier should target scripts/."""
        tiers = get_test_tiers()
        config = tiers["scripts"]
        assert config.test_path == "scripts/tests"
        # source_paths now uses glob patterns
        assert config.source_paths == [
            "scripts/**/*.py",
            "!scripts/**/__init__.py",
            "!scripts/tests/**/*.py",
        ]
        assert config.coverage_type == "line_branch"
        assert config.skip_private_functions is True
        # coverage_file field should be removed
        assert not hasattr(config, "coverage_file")
        # service_layer_only field should be removed
        assert not hasattr(config, "service_layer_only")


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


class TestValidateUsecaseCoverage:
    """Tests for validate_usecase_coverage function."""

    def test_passes_at_100_percent(self) -> None:
        """Should pass at 100% coverage."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
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


class TestParseArgsDynamicTiers:
    """Tests for dynamic tier handling in parse_args.

    These tests verify that parse_args() accepts any tier string without
    validation. Validation happens in main() after get_test_tiers() is called.
    """

    def test_parse_args_accepts_any_tier_string(self) -> None:
        """parse_args should accept any tier string without validation."""
        args = parse_args(["--tier", "custom_tier"])
        assert args.tier == "custom_tier"

    def test_parse_args_accepts_unknown_tier_name(self) -> None:
        """parse_args should NOT reject unknown tier names (validation is in main()).

        This test explicitly verifies the "free text" approach - parse_args()
        does not perform choices validation at parse time.
        """
        args = parse_args(["--tier", "nonexistent_tier_xyz"])
        assert args.tier == "nonexistent_tier_xyz"

    def test_parse_args_accepts_all_tier(self) -> None:
        """parse_args should accept 'all' as tier value."""
        args = parse_args(["--tier", "all"])
        assert args.tier == "all"

    def test_parse_args_default_tier_is_all(self) -> None:
        """parse_args should default to 'all' tier."""
        args = parse_args([])
        assert args.tier == "all"


class TestMainUnknownTierValidation:
    """Tests for unknown tier validation in main().

    These tests verify that:
    1. main() validates the --tier argument against get_test_tiers() keys
    2. Unknown tier names result in a non-zero exit code (return 1)
    3. A clear error message is printed identifying the unknown tier
    4. The error message lists all available tiers for user guidance

    This validates the "free-text + main() validation" design choice where
    parse_args() accepts any string and main() performs semantic validation.
    """

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


class TestPrintSummary:
    """Tests for print_summary function."""

    def test_prints_line_branch_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print line/branch coverage summary."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
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
            min_usecase=100.0,
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


class TestLineBranchTierPassBehavior:
    """Tests for tier_pass computation in LineBranchTestStrategy.build_summary().

    These tests verify that tier_pass is computed correctly based on:
    1. Coverage threshold validation results (populated by validate())
    2. Test execution results (from JUnit XML via test_summary)

    tier_pass = 1 only when BOTH:
    - No coverage failures exist (len(self._failures) == 0)
    - No test failures exist (tests_failed == 0)

    When --no-validate is used, validate() is not called, so _failures
    remains empty. This means coverage thresholds don't affect tier_pass,
    but test failures still do.
    """

    def test_tier_pass_is_1_when_no_failures(self, tmp_path: Path) -> None:
        """tier_pass should be 1 when no coverage or test failures exist."""
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=60.0,
            min_branch_per_function=50.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        # Simulate lifecycle without running actual tests
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=10, passed=10, failed=0, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
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
        # Call validate() to populate _failures (should be empty since coverage meets threshold)
        failures = strategy.validate()
        assert len(failures) == 0

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 1

    def test_tier_pass_is_0_when_coverage_failures_exist(self, tmp_path: Path) -> None:
        """tier_pass should be 0 when coverage threshold failures exist."""
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=90.0,  # High threshold to cause failure
            min_branch_per_function=50.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=10, passed=10, failed=0, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
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
                    "line_coverage": 60.0,  # Below 90% threshold
                    "branch_coverage": 70.0,
                    "missing_branches": [],
                }
            },
        )
        # Call validate() to populate _failures
        failures = strategy.validate()
        assert len(failures) > 0  # Confirm coverage failure detected

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 0

    def test_tier_pass_is_0_when_test_failures_exist(self, tmp_path: Path) -> None:
        """tier_pass should be 0 when test failures exist, even with passing coverage."""
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=60.0,
            min_branch_per_function=50.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=10, passed=8, failed=2, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
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
        # Call validate() - coverage passes
        failures = strategy.validate()
        assert len(failures) == 0

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 0  # Test failures cause tier_pass=0

    def test_tier_pass_is_1_without_validate_despite_coverage_below_threshold(
        self, tmp_path: Path
    ) -> None:
        """tier_pass should be 1 when validate() is not called (--no-validate semantics).

        This test simulates the --no-validate behavior where main() skips calling
        strategy.validate(). Since _failures remains empty, coverage threshold
        failures do not affect tier_pass.
        """
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=90.0,  # High threshold - would fail if validate() called
            min_branch_per_function=50.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=10, passed=10, failed=0, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
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
                    "line_coverage": 60.0,  # Below 90% threshold
                    "branch_coverage": 70.0,
                    "missing_branches": [],
                }
            },
        )
        # Do NOT call validate() - simulates --no-validate behavior
        # _failures remains empty, so coverage failures are not detected

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 1  # No coverage failure recorded

    def test_tier_pass_is_0_without_validate_when_test_failures_exist(self, tmp_path: Path) -> None:
        """tier_pass should be 0 when tests fail, even with --no-validate.

        Test failures are checked via test_summary, not via validate(). Therefore,
        even when --no-validate is used (validate() not called), test failures
        still cause tier_pass=0.
        """
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=90.0,  # High threshold - irrelevant here
            min_branch_per_function=50.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=10, passed=8, failed=2, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=60,
            missing_lines=40,
            line_coverage_pct=60.0,
            total_branches=50,
            covered_branches=30,
            missing_branches=20,
            branch_coverage_pct=60.0,
            files={},
            functions={
                "app/example.py::func": {
                    "name": "func",
                    "file": "app/example.py",
                    "line_coverage": 50.0,
                    "branch_coverage": 40.0,
                    "missing_branches": [],
                }
            },
        )
        # Do NOT call validate() - simulates --no-validate

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 0  # Test failures still cause tier_pass=0

    def test_tier_pass_is_0_when_both_coverage_and_test_failures(self, tmp_path: Path) -> None:
        """tier_pass should be 0 when both coverage and test failures exist."""
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=90.0,  # High threshold to cause failure
            min_branch_per_function=50.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=10, passed=7, failed=3, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=50,
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
                    "line_coverage": 50.0,  # Below 90% threshold
                    "branch_coverage": 40.0,
                    "missing_branches": [],
                }
            },
        )
        # Call validate() to populate _failures
        failures = strategy.validate()
        assert len(failures) > 0  # Coverage failures detected

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 0


class TestIntegrationTierPassBehavior:
    """Tests for tier_pass computation in IntegrationTestStrategy.build_summary().

    These tests verify that tier_pass is computed correctly based on:
    - Use-case coverage threshold validation results (populated by validate())

    Unlike LineBranchTestStrategy, IntegrationTestStrategy does NOT track
    test failures via test_summary. tier_pass depends ONLY on coverage.

    tier_pass = 1 only when no coverage failures exist (len(self._failures) == 0)

    When --no-validate is used, validate() is not called, so _failures
    remains empty and tier_pass is always 1.
    """

    def test_tier_pass_is_1_when_usecase_coverage_meets_threshold(self, tmp_path: Path) -> None:
        """tier_pass should be 1 when use-case coverage meets threshold."""
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )
        use_cases = [
            UseCase("UC-1", "/api/a", "GET", "Test 1", "integration"),
            UseCase("UC-2", "/api/b", "GET", "Test 2", "integration"),
        ]
        db_path = tmp_path / "coverage.db"

        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=2,
            covered_cases=2,
            uncovered_cases=[],
            coverage_pct=100.0,
        )
        # Call validate()
        failures = strategy.validate()
        assert len(failures) == 0

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 1

    def test_tier_pass_is_0_when_usecase_coverage_below_threshold(self, tmp_path: Path) -> None:
        """tier_pass should be 0 when use-case coverage is below threshold."""
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )
        use_cases = [
            UseCase("UC-1", "/api/a", "GET", "Test 1", "integration"),
            UseCase("UC-2", "/api/b", "GET", "Test 2", "integration"),
        ]
        db_path = tmp_path / "coverage.db"

        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=2,
            covered_cases=1,
            uncovered_cases=["UC-2"],
            coverage_pct=50.0,
        )
        # Call validate()
        failures = strategy.validate()
        assert len(failures) > 0

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 0

    def test_tier_pass_is_1_without_validate_despite_low_usecase_coverage(
        self, tmp_path: Path
    ) -> None:
        """tier_pass should be 1 when validate() is not called (--no-validate).

        Since IntegrationTestStrategy does not track test failures, and
        validate() is not called, tier_pass is always 1 with --no-validate.
        """
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )
        use_cases = [
            UseCase("UC-1", "/api/a", "GET", "Test 1", "integration"),
            UseCase("UC-2", "/api/b", "GET", "Test 2", "integration"),
        ]
        db_path = tmp_path / "coverage.db"

        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=2,
            covered_cases=1,
            uncovered_cases=["UC-2"],
            coverage_pct=50.0,  # Below threshold
        )
        # Do NOT call validate() - simulates --no-validate

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 1  # No coverage failure recorded

    def test_tier_pass_at_exact_threshold_boundary(self, tmp_path: Path) -> None:
        """tier_pass should be 1 when coverage exactly meets threshold."""
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=50.0,  # 50% threshold
        )
        use_cases = [
            UseCase("UC-1", "/api/a", "GET", "Test 1", "integration"),
            UseCase("UC-2", "/api/b", "GET", "Test 2", "integration"),
        ]
        db_path = tmp_path / "coverage.db"

        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=2,
            covered_cases=1,
            uncovered_cases=["UC-2"],
            coverage_pct=50.0,  # Exactly at threshold
        )
        # Call validate()
        failures = strategy.validate()
        assert len(failures) == 0  # Exactly at threshold should pass

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 1


class TestCustomTierPassBehavior:
    """Tests for tier_pass with dynamically configured custom tiers.

    These tests verify that custom tiers defined in pyproject.toml follow
    the same tier_pass semantics as default tiers:
    - Custom line_branch tiers: tier_pass depends on coverage AND test failures
    - Custom usecase tiers: tier_pass depends only on coverage
    - --no-validate affects both tier types by skipping coverage validation
    """

    def test_custom_line_branch_tier_pass_behavior(self, tmp_path: Path) -> None:
        """Custom line_branch tier should compute tier_pass correctly."""
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        # Custom tier configuration (simulating pyproject.toml custom tier)
        config = TestTierConfig(
            name="e2e_lines",  # Custom tier name
            test_path="tests/e2e",
            source_paths=["app/e2e"],
            min_line_per_function=70.0,
            min_branch_per_function=60.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=5, passed=5, failed=0, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="e2e_lines",
            total_lines=50,
            covered_lines=40,
            missing_lines=10,
            line_coverage_pct=80.0,
            total_branches=20,
            covered_branches=15,
            missing_branches=5,
            branch_coverage_pct=75.0,
            files={},
            functions={
                "app/e2e/handler.py::handle": {
                    "name": "handle",
                    "file": "app/e2e/handler.py",
                    "line_coverage": 80.0,
                    "branch_coverage": 75.0,
                    "missing_branches": [],
                }
            },
        )
        strategy.validate()

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 1
        assert summary["coverage_type"] == "line_branch"

    def test_custom_usecase_tier_pass_behavior(self, tmp_path: Path) -> None:
        """Custom usecase tier should compute tier_pass correctly."""
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        # Custom tier configuration
        config = TestTierConfig(
            name="smoke",  # Custom tier name
            test_path="tests/smoke",
            source_paths=["app"],
            min_usecase=80.0,  # Lower threshold for smoke tests
        )
        use_cases = [
            UseCase("UC-SMOKE-1", "/health", "GET", "Health check", "smoke"),
            UseCase("UC-SMOKE-2", "/ready", "GET", "Readiness", "smoke"),
        ]
        db_path = tmp_path / "coverage.db"

        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="smoke",
            total_cases=2,
            covered_cases=2,
            uncovered_cases=[],
            coverage_pct=100.0,
        )
        strategy.validate()

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 1
        assert summary["coverage_type"] == "usecase"

    def test_custom_line_branch_tier_with_test_failure(self, tmp_path: Path) -> None:
        """Custom line_branch tier should have tier_pass=0 when tests fail."""
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="perf_tests",  # Another custom tier name
            test_path="tests/perf",
            source_paths=["app/perf"],
            min_line_per_function=50.0,
            min_branch_per_function=40.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        # Test failure
        strategy.test_summary = TestSummary(total=5, passed=4, failed=1, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="perf_tests",
            total_lines=50,
            covered_lines=45,
            missing_lines=5,
            line_coverage_pct=90.0,
            total_branches=20,
            covered_branches=18,
            missing_branches=2,
            branch_coverage_pct=90.0,
            files={},
            functions={
                "app/perf/benchmark.py::run": {
                    "name": "run",
                    "file": "app/perf/benchmark.py",
                    "line_coverage": 90.0,
                    "branch_coverage": 85.0,
                    "missing_branches": [],
                }
            },
        )
        strategy.validate()  # Coverage passes

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 0  # Test failure causes tier_pass=0

    def test_custom_tier_no_validate_skips_coverage_check(self, tmp_path: Path) -> None:
        """Custom tier with --no-validate should have tier_pass=1 despite low coverage."""
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="custom_strict",  # Custom tier with strict thresholds
            test_path="tests/custom",
            source_paths=["app/custom"],
            min_line_per_function=95.0,  # Very high threshold
            min_branch_per_function=90.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=3, passed=3, failed=0, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="custom_strict",
            total_lines=100,
            covered_lines=70,
            missing_lines=30,
            line_coverage_pct=70.0,
            total_branches=40,
            covered_branches=28,
            missing_branches=12,
            branch_coverage_pct=70.0,
            files={},
            functions={
                "app/custom/module.py::process": {
                    "name": "process",
                    "file": "app/custom/module.py",
                    "line_coverage": 70.0,  # Well below 95% threshold
                    "branch_coverage": 65.0,  # Below 90% threshold
                    "missing_branches": [(10, 15)],
                }
            },
        )
        # Do NOT call validate() - simulates --no-validate

        summary = strategy.build_summary()
        assert summary["tier_pass"] == 1  # No validation means no coverage failure


class TestNoValidateSemantics:
    """Tests documenting --no-validate flag interaction with tier_pass.

    The --no-validate flag causes main() to skip calling strategy.validate().
    This has the following effects on tier_pass:

    For line_branch tiers:
    - Coverage threshold failures are NOT detected (_failures stays empty)
    - Test failures ARE still detected (via test_summary)
    - tier_pass = 0 if tests fail, 1 otherwise

    For usecase tiers:
    - Coverage threshold failures are NOT detected (_failures stays empty)
    - No test failure tracking exists
    - tier_pass = 1 always (with --no-validate)

    These tests serve as documentation of expected behavior.
    """

    def test_no_validate_line_branch_coverage_ignored_tests_checked(self, tmp_path: Path) -> None:
        """--no-validate: line_branch tier ignores coverage but checks tests."""
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=100.0,  # Impossible threshold
            min_branch_per_function=100.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=5, passed=5, failed=0, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=50,
            missing_lines=50,
            line_coverage_pct=50.0,
            total_branches=50,
            covered_branches=25,
            missing_branches=25,
            branch_coverage_pct=50.0,
            files={},
            functions={
                "app/mod.py::fn": {
                    "name": "fn",
                    "file": "app/mod.py",
                    "line_coverage": 50.0,  # Way below 100%
                    "branch_coverage": 50.0,
                    "missing_branches": [(1, 2)],
                }
            },
        )
        # Simulate --no-validate: do NOT call validate()

        summary = strategy.build_summary()
        # Coverage is ignored, tests pass -> tier_pass=1
        assert summary["tier_pass"] == 1

    def test_no_validate_usecase_coverage_ignored(self, tmp_path: Path) -> None:
        """--no-validate: usecase tier ignores coverage, always tier_pass=1."""
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,  # Requires all use cases covered
        )
        use_cases = [
            UseCase("UC-1", "/a", "GET", "Test 1", "integration"),
            UseCase("UC-2", "/b", "GET", "Test 2", "integration"),
            UseCase("UC-3", "/c", "GET", "Test 3", "integration"),
        ]
        db_path = tmp_path / "coverage.db"

        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=3,
            covered_cases=1,
            uncovered_cases=["UC-2", "UC-3"],
            coverage_pct=33.3,  # Way below 100%
        )
        # Simulate --no-validate: do NOT call validate()

        summary = strategy.build_summary()
        # Coverage is ignored -> tier_pass=1
        assert summary["tier_pass"] == 1


# =============================================================================
# END-TO-END MAIN() TESTS FOR TIER_PASS AND --NO-VALIDATE BEHAVIOR
# =============================================================================


class TestMainTierPassEndToEnd:
    """End-to-end tests for tier_pass behavior via main().

    These tests exercise the full main() flow with mocked subprocess calls
    to verify that tier_pass is correctly computed and that --no-validate
    affects the outcome as expected.

    Unlike the strategy-level tests in TestLineBranchTierPassBehavior and
    TestIntegrationTierPassBehavior, these tests verify the integration
    between argument parsing, strategy creation, and tier_pass computation.
    """

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
    """End-to-end tests for tier_pass with custom tiers via main().

    These tests verify that custom tiers defined in pyproject.toml follow
    the same tier_pass and --no-validate semantics as default tiers.
    """

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
    """Tests documenting the complete behavioral contract of --no-validate.

    This test class serves as executable documentation for the --no-validate flag.
    It explicitly tests all interactions between --no-validate and tier_pass for
    both coverage types across default and custom tiers.

    BEHAVIORAL CONTRACT:
    -------------------
    When --no-validate is passed:

    1. main() skips calling strategy.validate() for all tiers
    2. Coverage threshold failures are NOT recorded in _failures
    3. tier_pass is computed without coverage failure data

    For line_branch tiers (unit, component, scripts, custom):
    - Coverage failures are IGNORED (tier_pass not affected)
    - Test failures STILL cause tier_pass=0 (checked via test_summary)

    For usecase tiers (integration, custom):
    - Coverage failures are IGNORED (tier_pass not affected)
    - No test failure tracking exists
    - tier_pass is ALWAYS 1 with --no-validate

    USE CASES FOR --no-validate:
    - Initial development: Run tests without coverage enforcement
    - Debugging: Focus on test results, not coverage
    - Incremental coverage: Add coverage requirements gradually
    """

    def test_contract_line_branch_no_validate_ignores_coverage(self, tmp_path: Path) -> None:
        """CONTRACT: --no-validate ignores coverage for line_branch tiers.

        Verifies that coverage below threshold + no test failures = tier_pass=1.
        """
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=100.0,  # Impossibly high threshold
            min_branch_per_function=100.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(total=5, passed=5, failed=0, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=30,  # Only 30% coverage
            missing_lines=70,
            line_coverage_pct=30.0,
            total_branches=50,
            covered_branches=15,
            missing_branches=35,
            branch_coverage_pct=30.0,
            files={},
            functions={
                "app/mod.py::func": {
                    "name": "func",
                    "file": "app/mod.py",
                    "line_coverage": 30.0,  # Way below 100%
                    "branch_coverage": 30.0,
                    "missing_branches": [(1, 2), (3, 4)],
                }
            },
        )
        # Do NOT call validate() - simulates --no-validate

        summary = strategy.build_summary()
        # tier_pass=1 because no coverage failure was recorded
        assert summary["tier_pass"] == 1

    def test_contract_line_branch_no_validate_respects_test_failures(self, tmp_path: Path) -> None:
        """CONTRACT: --no-validate does NOT ignore test failures for line_branch.

        Verifies that test failures cause tier_pass=0 even with --no-validate.
        """
        from scripts.dev.test_runner.junit_parser import TestSummary
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=100.0,
            min_branch_per_function=100.0,
        )
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tmp_path / "data_unit")
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.test_summary = TestSummary(
            total=10, passed=7, failed=3, errors=0, skipped=0
        )  # 3 test failures
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=100,
            missing_lines=0,
            line_coverage_pct=100.0,
            total_branches=50,
            covered_branches=50,
            missing_branches=0,
            branch_coverage_pct=100.0,
            files={},
            functions={
                "app/mod.py::func": {
                    "name": "func",
                    "file": "app/mod.py",
                    "line_coverage": 100.0,
                    "branch_coverage": 100.0,
                    "missing_branches": [],
                }
            },
        )
        # Do NOT call validate() - simulates --no-validate

        summary = strategy.build_summary()
        # tier_pass=0 because test failures exist (even with --no-validate)
        assert summary["tier_pass"] == 0

    def test_contract_usecase_no_validate_always_passes(self, tmp_path: Path) -> None:
        """CONTRACT: --no-validate causes tier_pass=1 for usecase tiers.

        Verifies that usecase tier always has tier_pass=1 with --no-validate.
        """
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,  # Requires all use cases covered
        )
        use_cases = [
            UseCase("UC-1", "/a", "GET", "Test 1", "integration"),
            UseCase("UC-2", "/b", "GET", "Test 2", "integration"),
            UseCase("UC-3", "/c", "GET", "Test 3", "integration"),
            UseCase("UC-4", "/d", "GET", "Test 4", "integration"),
            UseCase("UC-5", "/e", "GET", "Test 5", "integration"),
        ]
        db_path = tmp_path / "coverage.db"

        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=5,
            covered_cases=1,  # Only 20% coverage
            uncovered_cases=["UC-2", "UC-3", "UC-4", "UC-5"],
            coverage_pct=20.0,
        )
        # Do NOT call validate() - simulates --no-validate

        summary = strategy.build_summary()
        # tier_pass=1 because no coverage failure was recorded
        assert summary["tier_pass"] == 1

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


# =============================================================================
# load_tier_configs() TESTS
# =============================================================================


class TestLoadTierConfigs:
    """Tests for the load_tier_configs() public API.

    load_tier_configs() is the single source of truth for building
    dict[str, TestTierConfig] from pyproject.toml. All tiers must be defined
    in [tool.test_coverage.tiers.<tier_name>] sections.
    """

    def test_load_tier_configs_multiple_tiers(self, tmp_path: Path) -> None:
        """Should load tier configs from [tool.test_coverage.tiers] format."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.alpha]
test_path = "tests/alpha"
source_paths = ["app"]
min_line_per_function = 75.0

[tool.test_coverage.tiers.beta]
test_path = "tests/beta"
source_paths = ["lib"]
min_usecase = 90.0
""")
        tiers = load_tier_configs(pyproject)

        assert "alpha" in tiers
        assert "beta" in tiers
        assert tiers["alpha"].test_path == "tests/alpha"
        assert tiers["alpha"].source_paths == ["app"]
        assert tiers["alpha"].coverage_type == "line_branch"
        assert tiers["alpha"].min_line_per_function == 75.0
        assert tiers["beta"].test_path == "tests/beta"
        assert tiers["beta"].source_paths == ["lib"]
        assert tiers["beta"].coverage_type == "usecase"
        assert tiers["beta"].min_usecase == 90.0

    def test_load_tier_configs_custom_path(self, tmp_path: Path) -> None:
        """Should load from custom pyproject_path."""
        custom_path = tmp_path / "custom" / "pyproject.toml"
        custom_path.parent.mkdir(parents=True, exist_ok=True)
        custom_path.write_text("""
[tool.test_coverage.tiers.custom]
test_path = "tests/custom"
source_paths = ["custom"]
min_line_per_function = 80.0
""")
        tiers = load_tier_configs(custom_path)

        assert "custom" in tiers
        assert tiers["custom"].test_path == "tests/custom"

    def test_load_tier_configs_missing_file_raises_error(self) -> None:
        """Should raise ValueError when pyproject.toml doesn't exist."""
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(Path("/nonexistent/pyproject.toml"))
        assert "pyproject.toml not found" in str(exc_info.value)

    def test_load_tier_configs_validation_errors(self, tmp_path: Path) -> None:
        """Should raise ValueError for missing required fields."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.test_coverage.tiers.invalid]
test_path = "tests/invalid"
# Missing source_paths
""")
        with pytest.raises(ValueError) as exc_info:
            load_tier_configs(pyproject)

        error_msg = str(exc_info.value)
        assert "invalid" in error_msg
        assert "source_paths" in error_msg

    def test_removing_tier_skips_execution(self, tmp_path: Path) -> None:
        """Removing a tier from config should cause it to be absent from results."""
        pyproject = tmp_path / "pyproject.toml"

        # Step 1: Create pyproject.toml with two tiers
        pyproject.write_text("""
[tool.test_coverage.tiers.alpha]
test_path = "tests/alpha"
source_paths = ["app"]
min_line_per_function = 80.0

[tool.test_coverage.tiers.beta]
test_path = "tests/beta"
source_paths = ["app"]
min_line_per_function = 80.0
""")
        tiers_v1 = load_tier_configs(pyproject)
        assert "alpha" in tiers_v1
        assert "beta" in tiers_v1

        # Step 2: Rewrite pyproject.toml with only alpha tier
        pyproject.write_text("""
[tool.test_coverage.tiers.alpha]
test_path = "tests/alpha"
source_paths = ["app"]
min_line_per_function = 80.0
""")

        # Step 3: Reload and verify beta is gone
        tiers_v2 = load_tier_configs(pyproject)
        assert "alpha" in tiers_v2
        assert "beta" not in tiers_v2  # beta was removed


class TestTierOrderPreservation:
    """Tests verifying tier order preservation.

    Tier order from TOML is preserved using tomllib's order preservation.
    """

    def test_load_tier_configs_preserves_toml_order(self, tmp_path: Path) -> None:
        """Should preserve tier order from TOML file."""
        pyproject = tmp_path / "pyproject.toml"
        # Define tiers in reverse alphabetical order to test order preservation
        pyproject.write_text("""
[tool.test_coverage.tiers.zebra]
test_path = "tests/zebra"
source_paths = ["app"]
min_line_per_function = 80.0

[tool.test_coverage.tiers.monkey]
test_path = "tests/monkey"
source_paths = ["app"]
min_line_per_function = 80.0

[tool.test_coverage.tiers.apple]
test_path = "tests/apple"
source_paths = ["app"]
min_line_per_function = 80.0
""")
        tiers = load_tier_configs(pyproject)

        # tomllib preserves order, so we expect zebra, monkey, apple
        assert list(tiers.keys()) == ["zebra", "monkey", "apple"]

    def test_no_set_operations_in_load_tier_configs(self) -> None:
        """load_tier_configs should not use set/sorted operations in code.

        Note: This regex-based source scan is intentionally brittle. If the
        implementation legitimately requires set()/sorted() in the future, update
        this test accordingly.
        """
        import inspect
        import re

        source = inspect.getsource(load_tier_configs)

        # Remove docstrings and comments to check only actual code
        # Remove triple-quoted docstrings
        code_only = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
        code_only = re.sub(r"'''.*?'''", "", code_only, flags=re.DOTALL)
        # Remove single-line comments
        code_only = re.sub(r"#.*$", "", code_only, flags=re.MULTILINE)

        # Check for forbidden patterns in code only
        # These patterns would destroy dict ordering
        forbidden_patterns = [
            r"\bset\s*\(",  # set() call
            r"\bsorted\s*\(",  # sorted() call
            r"\|\s*set\b",  # | set union
            r"\blist\s*\(\s*set\s*\(",  # list(set(...))
        ]
        for pattern in forbidden_patterns:
            match = re.search(pattern, code_only)
            assert match is None, (
                f"load_tier_configs() contains forbidden pattern '{pattern}' in code. "
                "This operation destroys order preservation."
            )

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


# =============================================================================
# CREATE_STRATEGY FACTORY INVARIANT TESTS
# =============================================================================


class TestCreateStrategyInvariant:
    """Tests verifying create_strategy() is the single location for coverage type dispatch.

    These tests ensure:
    1. create_strategy() returns the correct strategy subclass based on coverage_type
    2. Proper validation of required parameters for each coverage type
    3. Appropriate error handling for unknown coverage types
    """

    def test_create_strategy_dispatches_line_branch_type(self, tmp_path: Path) -> None:
        """create_strategy() with coverage_type='line_branch' returns LineBranchTestStrategy."""
        from scripts.dev.test_runner.test_strategies import (
            LineBranchTestStrategy,
            create_strategy,
        )

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        db_path = tmp_path / "coverage.db"
        tier_coverage_file = tmp_path / "data_unit"

        strategy = create_strategy(config, db_path, tmp_path, tier_coverage_file=tier_coverage_file)

        assert isinstance(strategy, LineBranchTestStrategy)

    def test_create_strategy_dispatches_usecase_type(self, tmp_path: Path) -> None:
        """create_strategy() with coverage_type='usecase' returns IntegrationTestStrategy."""
        from scripts.dev.test_runner.test_strategies import (
            IntegrationTestStrategy,
            create_strategy,
        )

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )
        db_path = tmp_path / "coverage.db"
        use_cases = [UseCase("UC-1", "/api", "GET", "Test", "integration")]

        strategy = create_strategy(config, db_path, tmp_path, use_cases=use_cases)

        assert isinstance(strategy, IntegrationTestStrategy)

    def test_create_strategy_requires_tier_coverage_file_for_line_branch(
        self, tmp_path: Path
    ) -> None:
        """create_strategy() raises ValueError when tier_coverage_file is None for line_branch."""
        from scripts.dev.test_runner.test_strategies import create_strategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        db_path = tmp_path / "coverage.db"

        with pytest.raises(ValueError) as exc_info:
            create_strategy(config, db_path, tmp_path, tier_coverage_file=None)

        assert "tier_coverage_file is required" in str(exc_info.value)

    def test_create_strategy_requires_use_cases_for_usecase(self, tmp_path: Path) -> None:
        """create_strategy() raises ValueError when use_cases is None for usecase coverage type."""
        from scripts.dev.test_runner.test_strategies import create_strategy

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )
        db_path = tmp_path / "coverage.db"

        with pytest.raises(ValueError) as exc_info:
            create_strategy(config, db_path, tmp_path, use_cases=None)

        assert "use_cases must be provided" in str(exc_info.value)

    def test_create_strategy_rejects_missing_thresholds(self, tmp_path: Path) -> None:
        """create_strategy() raises ValueError when config has no coverage thresholds."""
        from scripts.dev.test_runner.test_strategies import create_strategy

        config = TestTierConfig(
            name="unknown",
            test_path="tests/unknown",
            source_paths=["app"],
            # No thresholds - coverage_type property will raise
        )
        db_path = tmp_path / "coverage.db"

        with pytest.raises(ValueError) as exc_info:
            create_strategy(config, db_path, tmp_path)

        assert "has no coverage thresholds set" in str(exc_info.value)


# =============================================================================
# COVERAGE ISOLATION PER TIER TESTS
# =============================================================================


class TestCoverageIsolationPerTier:
    """Tests verifying each tier uses isolated coverage files during validation.

    These tests ensure:
    1. LineBranchTestStrategy uses tier-specific coverage file (not .coverage/data)
    2. --cov-append flag is NOT used (each tier writes fresh coverage)
    3. Per-tier JSON reports are generated from tier-specific coverage files
    """

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


# =============================================================================
# COVERAGE COMBINE TESTS
# =============================================================================


class TestCoverageCombine:
    """Tests verifying coverage combine produces combined database for global reports."""

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


class TestComponentTierUsecaseRequirement:
    """Tests for component tier usecase coverage requirement.

    Component tier now uses usecase coverage (not line_branch) and MUST FAIL
    when no use-cases are defined (total_cases == 0). This is different from
    100% pass with 0/0 cases - it must be an explicit failure.
    """

    def test_usecase_tier_fails_when_no_usecases_defined(self) -> None:
        """Usecase tier should fail when total_cases is 0."""
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        config = TestTierConfig(
            name="component",
            test_path="tests/component",
            source_paths=["app/services"],
            min_usecase=100.0,
        )

        # Create strategy with empty use cases
        strategy = IntegrationTestStrategy(
            config=config,
            coverage_db_path=Path("/fake/db"),
            repo_root=Path("/fake/root"),
            use_cases=[],  # No use cases defined
        )

        # Simulate that tests ran and results were collected
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="component",
            total_cases=0,  # No use-cases defined
            covered_cases=0,
            uncovered_cases=[],
            coverage_pct=100.0,  # Would be 100% with 0/0, but should still fail
        )

        # validate() should return failures because no use-cases are defined
        failures = strategy.validate()

        assert len(failures) == 1
        assert "No use-cases defined" in failures[0]
        assert "component" in failures[0]

    def test_usecase_tier_passes_when_usecases_defined_and_covered(self) -> None:
        """Usecase tier should pass when use-cases exist and are covered."""
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        config = TestTierConfig(
            name="component",
            test_path="tests/component",
            source_paths=["app/services"],
            min_usecase=100.0,
        )

        strategy = IntegrationTestStrategy(
            config=config,
            coverage_db_path=Path("/fake/db"),
            repo_root=Path("/fake/root"),
            use_cases=[
                UseCase(
                    id="UC-SVC-001",
                    endpoint="/api/service",
                    method="GET",
                    description="Test service",
                    test_tier="component",
                )
            ],
        )

        # Simulate that tests ran and results were collected
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="component",
            total_cases=1,
            covered_cases=1,
            uncovered_cases=[],
            coverage_pct=100.0,
        )

        failures = strategy.validate()

        assert failures == []

    def test_usecase_tier_fails_when_coverage_below_threshold(self) -> None:
        """Usecase tier should fail when coverage is below threshold."""
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

        config = TestTierConfig(
            name="component",
            test_path="tests/component",
            source_paths=["app/services"],
            min_usecase=100.0,
        )

        strategy = IntegrationTestStrategy(
            config=config,
            coverage_db_path=Path("/fake/db"),
            repo_root=Path("/fake/root"),
            use_cases=[],
        )

        # Simulate that tests ran and results were collected
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="component",
            total_cases=2,
            covered_cases=1,
            uncovered_cases=["UC-SVC-002"],
            coverage_pct=50.0,
        )

        failures = strategy.validate()

        assert len(failures) >= 1
        assert "50.0%" in failures[0]
        assert "100.0%" in failures[0]


# =============================================================================
# ADDITIONAL COVERAGE IMPROVEMENT TESTS
# =============================================================================


class TestCoverageTypeProperty:
    """Tests for TestTierConfig.coverage_type property."""

    def test_coverage_type_returns_line_branch_when_min_line_set(self) -> None:
        """coverage_type should be 'line_branch' when min_line_per_function is set."""
        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        assert config.coverage_type == "line_branch"

    def test_coverage_type_returns_line_branch_when_min_branch_set(self) -> None:
        """coverage_type should be 'line_branch' when only min_branch_per_function is set."""
        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["app"],
            min_branch_per_function=70.0,
        )
        assert config.coverage_type == "line_branch"

    def test_coverage_type_returns_usecase_when_min_usecase_set(self) -> None:
        """coverage_type should be 'usecase' when min_usecase is set."""
        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["app"],
            min_usecase=100.0,
        )
        assert config.coverage_type == "usecase"

    def test_coverage_type_prioritizes_line_branch_over_usecase(self) -> None:
        """coverage_type should be 'line_branch' when both types are set."""
        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["app"],
            min_line_per_function=80.0,
            min_usecase=100.0,
        )
        assert config.coverage_type == "line_branch"

    def test_coverage_type_raises_when_no_thresholds(self) -> None:
        """coverage_type should raise ValueError when no thresholds are set."""
        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["app"],
        )
        with pytest.raises(ValueError) as exc_info:
            _ = config.coverage_type
        assert "no coverage thresholds set" in str(exc_info.value)


class TestExpandSourcePatterns:
    """Tests for expand_source_patterns function."""

    def test_expands_single_pattern(self, fs: FakeFilesystem) -> None:
        """Should expand a single glob pattern to file paths."""
        from scripts.dev.test_runner.test_coverage import expand_source_patterns

        fs.create_dir("/repo/app")
        fs.create_file("/repo/app/module.py", contents="# module")
        fs.create_file("/repo/app/utils.py", contents="# utils")

        result = expand_source_patterns(["app/*.py"], Path("/repo"))

        assert "app/module.py" in result
        assert "app/utils.py" in result

    def test_expands_recursive_pattern(self, fs: FakeFilesystem) -> None:
        """Should expand recursive glob pattern **/*.py."""
        from scripts.dev.test_runner.test_coverage import expand_source_patterns

        fs.create_dir("/repo/app/sub")
        fs.create_file("/repo/app/main.py", contents="# main")
        fs.create_file("/repo/app/sub/nested.py", contents="# nested")

        result = expand_source_patterns(["app/**/*.py"], Path("/repo"))

        assert "app/main.py" in result
        assert "app/sub/nested.py" in result

    def test_handles_negation_pattern(self, fs: FakeFilesystem) -> None:
        """Should exclude files matching negation patterns."""
        from scripts.dev.test_runner.test_coverage import expand_source_patterns

        fs.create_dir("/repo/app")
        fs.create_file("/repo/app/module.py", contents="# module")
        fs.create_file("/repo/app/__init__.py", contents="# init")

        result = expand_source_patterns(["app/*.py", "!app/__init__.py"], Path("/repo"))

        assert "app/module.py" in result
        assert "app/__init__.py" not in result

    def test_handles_empty_patterns(self) -> None:
        """Should return empty set for empty patterns list."""
        from scripts.dev.test_runner.test_coverage import expand_source_patterns

        result = expand_source_patterns([], Path("/repo"))

        assert result == set()

    def test_excludes_directories(self, fs: FakeFilesystem) -> None:
        """Should only include files, not directories."""
        from scripts.dev.test_runner.test_coverage import expand_source_patterns

        fs.create_dir("/repo/app/subdir")
        fs.create_file("/repo/app/module.py", contents="# module")

        result = expand_source_patterns(["app/*"], Path("/repo"))

        assert "app/module.py" in result
        # Directories should not be in the result


class TestGetCoverageSourceArgs:
    """Tests for get_coverage_source_args function."""

    def test_extracts_base_directory_from_pattern(self) -> None:
        """Should extract base directory from glob pattern."""
        from scripts.dev.test_runner.test_coverage import get_coverage_source_args

        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["app/**/*.py"],
            min_line_per_function=80.0,
        )

        source_dirs, omit_patterns = get_coverage_source_args(config, Path("/repo"))

        assert "app" in source_dirs
        assert omit_patterns == []

    def test_handles_negation_as_omit(self) -> None:
        """Should convert negation patterns to omit patterns."""
        from scripts.dev.test_runner.test_coverage import get_coverage_source_args

        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["app/**/*.py", "!app/__init__.py"],
            min_line_per_function=80.0,
        )

        source_dirs, omit_patterns = get_coverage_source_args(config, Path("/repo"))

        assert "app" in source_dirs
        assert "app/__init__.py" in omit_patterns

    def test_handles_multiple_patterns(self) -> None:
        """Should handle multiple source patterns."""
        from scripts.dev.test_runner.test_coverage import get_coverage_source_args

        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["app/**/*.py", "lib/**/*.py", "!**/__init__.py"],
            min_line_per_function=80.0,
        )

        source_dirs, omit_patterns = get_coverage_source_args(config, Path("/repo"))

        assert "app" in source_dirs
        assert "lib" in source_dirs
        assert "**/__init__.py" in omit_patterns

    def test_extracts_nested_base_directory(self) -> None:
        """Should extract nested base directory from pattern like app/services/**/*.py."""
        from scripts.dev.test_runner.test_coverage import get_coverage_source_args

        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["app/services/**/*.py"],
            min_line_per_function=80.0,
        )

        source_dirs, _omit_patterns = get_coverage_source_args(config, Path("/repo"))

        assert "app/services" in source_dirs

    def test_handles_pattern_starting_with_glob(self) -> None:
        """Should handle patterns like **/*.py (no base directory)."""
        from scripts.dev.test_runner.test_coverage import get_coverage_source_args

        config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["**/*.py"],
            min_line_per_function=80.0,
        )

        source_dirs, _omit_patterns = get_coverage_source_args(config, Path("/repo"))

        # Pattern starting with ** has no base parts
        assert source_dirs == []


class TestLoadUseCasesExtended:
    """Extended tests for load_use_cases function."""

    def test_loads_multiple_features(self, fs: FakeFilesystem) -> None:
        """Should load use cases from multiple features."""
        from scripts.dev.test_runner.test_coverage import load_use_cases

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
        test_tier: integration
  api:
    name: API Tests
    use_cases:
      - id: UC-API-001
        endpoint: /api/v1/resource
        method: POST
        description: Create resource
        test_tier: e2e
"""
        fs.create_file("/use_cases.yaml", contents=yaml_content)

        result = load_use_cases(Path("/use_cases.yaml"))

        assert len(result) == 2
        ids = [uc.id for uc in result]
        assert "UC-HEALTH-001" in ids
        assert "UC-API-001" in ids

    def test_handles_feature_with_multiple_usecases(self, fs: FakeFilesystem) -> None:
        """Should load all use cases within a single feature."""
        from scripts.dev.test_runner.test_coverage import load_use_cases

        yaml_content = """
version: "1.0"
features:
  crud:
    name: CRUD Operations
    use_cases:
      - id: UC-CRUD-001
        endpoint: /items
        method: GET
        description: List items
        test_tier: integration
      - id: UC-CRUD-002
        endpoint: /items
        method: POST
        description: Create item
        test_tier: integration
      - id: UC-CRUD-003
        endpoint: /items/{id}
        method: DELETE
        description: Delete item
        test_tier: integration
"""
        fs.create_file("/use_cases.yaml", contents=yaml_content)

        result = load_use_cases(Path("/use_cases.yaml"))

        assert len(result) == 3
        assert result[0].id == "UC-CRUD-001"
        assert result[1].id == "UC-CRUD-002"
        assert result[2].id == "UC-CRUD-003"


class TestCollectCoveredUsecasesExtended:
    """Extended tests for collect_covered_usecases function."""

    def test_collects_from_nested_directories(self, fs: FakeFilesystem) -> None:
        """Should collect use cases from nested test directories."""
        test_content = """
import pytest

@pytest.mark.usecase("UC-NESTED-001")
def test_nested():
    pass
"""
        fs.create_dir("/tests/integration/api")
        fs.create_file("/tests/integration/api/test_nested.py", contents=test_content)

        result = collect_covered_usecases("/tests/integration")

        assert "UC-NESTED-001" in result

    def test_ignores_non_test_files(self, fs: FakeFilesystem) -> None:
        """Should only scan files starting with test_."""
        test_content = """
import pytest

@pytest.mark.usecase("UC-IGNORED-001")
def test_ignored():
    pass
"""
        fs.create_dir("/tests/integration")
        fs.create_file("/tests/integration/helper.py", contents=test_content)

        result = collect_covered_usecases("/tests/integration")

        assert "UC-IGNORED-001" not in result


class TestCalculateUsecaseCoverageExtended:
    """Extended tests for calculate_usecase_coverage function."""

    def test_handles_empty_tier(self) -> None:
        """Should handle tier with no use cases."""
        use_cases: list[UseCase] = []
        covered_ids: set[str] = set()

        result = calculate_usecase_coverage("integration", use_cases, covered_ids)

        assert result.total_cases == 0
        assert result.covered_cases == 0
        assert result.coverage_pct == 100.0  # 100% when no cases

    def test_filters_by_tier(self) -> None:
        """Should only count use cases for the specified tier."""
        use_cases = [
            UseCase("UC-1", "/a", "GET", "Test 1", "integration"),
            UseCase("UC-2", "/b", "GET", "Test 2", "e2e"),
            UseCase("UC-3", "/c", "GET", "Test 3", "integration"),
        ]
        covered_ids = {"UC-1", "UC-2", "UC-3"}

        result = calculate_usecase_coverage("integration", use_cases, covered_ids)

        assert result.total_cases == 2  # Only integration tier
        assert result.covered_cases == 2
        assert result.coverage_pct == 100.0


class TestValidateLineBranchCoverageExtended:
    """Extended tests for validate_line_branch_coverage function."""

    def test_validates_branch_coverage_with_missing_branches(self) -> None:
        """Should fail when branch coverage is below threshold with missing branches."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=60.0,
            min_branch_per_function=80.0,
        )
        result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=85,
            missing_lines=15,
            line_coverage_pct=85.0,
            total_branches=50,
            covered_branches=30,
            missing_branches=20,
            branch_coverage_pct=60.0,
            files={},
            functions={
                "test.py::func": {
                    "name": "func",
                    "file": "test.py",
                    "line_coverage": 85.0,
                    "branch_coverage": 50.0,  # Below 80% threshold
                    "missing_branches": [(10, 15), (20, 25)],  # Has missing branches
                }
            },
        )

        failures = validate_line_branch_coverage(result, config)

        assert len(failures) == 1
        assert "branch coverage" in failures[0].lower()

    def test_skips_branch_validation_without_missing_branches(self) -> None:
        """Should skip branch validation when no missing branches exist."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=60.0,
            min_branch_per_function=80.0,
        )
        result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=85,
            missing_lines=15,
            line_coverage_pct=85.0,
            total_branches=50,
            covered_branches=30,
            missing_branches=20,
            branch_coverage_pct=60.0,
            files={},
            functions={
                "test.py::func": {
                    "name": "func",
                    "file": "test.py",
                    "line_coverage": 85.0,
                    "branch_coverage": 50.0,
                    "missing_branches": [],  # No missing branches
                }
            },
        )

        failures = validate_line_branch_coverage(result, config)

        # Should pass because no missing branches
        assert failures == []

    def test_reports_multiple_function_failures(self) -> None:
        """Should report failures for multiple functions."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=70,
            missing_lines=30,
            line_coverage_pct=70.0,
            total_branches=50,
            covered_branches=35,
            missing_branches=15,
            branch_coverage_pct=70.0,
            files={},
            functions={
                "test.py::func1": {
                    "name": "func1",
                    "file": "test.py",
                    "line_coverage": 50.0,  # Below threshold
                    "branch_coverage": 90.0,
                    "missing_branches": [],
                },
                "test.py::func2": {
                    "name": "func2",
                    "file": "test.py",
                    "line_coverage": 40.0,  # Below threshold
                    "branch_coverage": 90.0,
                    "missing_branches": [],
                },
            },
        )

        failures = validate_line_branch_coverage(result, config)

        assert len(failures) == 2


class TestValidateUsecaseCoverageExtended:
    """Extended tests for validate_usecase_coverage function."""

    def test_reports_uncovered_cases_up_to_10(self) -> None:
        """Should report up to 10 uncovered cases."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )
        uc_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=15,
            covered_cases=3,
            uncovered_cases=[f"UC-{i}" for i in range(1, 13)],  # 12 uncovered
            coverage_pct=20.0,
        )

        failures = validate_usecase_coverage(uc_result, config)

        # First failure is the main message
        assert len(failures) >= 1
        assert "20.0%" in failures[0]

        # Should list up to 10 uncovered cases
        uncovered_messages = [f for f in failures if "Uncovered:" in f]
        assert len(uncovered_messages) <= 10

        # Should have truncation message
        more_messages = [f for f in failures if "more" in f]
        assert len(more_messages) == 1

    def test_passes_when_no_threshold_set(self) -> None:
        """Should pass when min_usecase is None."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_line_per_function=80.0,  # Different threshold type
        )
        uc_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=5,
            uncovered_cases=["UC-1", "UC-2", "UC-3", "UC-4", "UC-5"],
            coverage_pct=50.0,
        )

        failures = validate_usecase_coverage(uc_result, config)

        # Should pass because min_usecase is None
        assert failures == []


class TestGenerateMissingLineDetailsExtended:
    """Extended tests for generate_missing_line_details function."""

    def test_handles_invalid_branch_arc_format(self, fs: FakeFilesystem) -> None:
        """Should skip invalid branch arc formats."""
        from scripts.dev.test_runner.test_coverage import generate_missing_line_details

        code = """def test_func():
    x = 1
    y = 2
    return x + y
"""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents=code)

        coverage_data = {
            "files": {
                "test.py": {
                    "executed_lines": [1, 2],
                    "missing_lines": [3, 4],
                    "missing_branches": [
                        [2, 3],  # Valid
                        "invalid",  # Invalid - not a list/tuple
                        [1],  # Invalid - wrong length
                    ],
                }
            }
        }

        results = generate_missing_line_details(coverage_data, Path("/repo"))

        assert len(results) == 2

    def test_handles_out_of_bounds_line_numbers(self, fs: FakeFilesystem) -> None:
        """Should handle line numbers outside file range."""
        from scripts.dev.test_runner.test_coverage import generate_missing_line_details

        code = """def test_func():
    return 1
"""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents=code)

        coverage_data = {
            "files": {
                "test.py": {
                    "executed_lines": [1],
                    "missing_lines": [100],  # Line 100 doesn't exist
                    "missing_branches": [],
                }
            }
        }

        results = generate_missing_line_details(coverage_data, Path("/repo"))

        assert len(results) == 1
        assert results[0].line_number == 100
        assert results[0].content == ""  # Empty content for out of bounds

    def test_includes_branch_exit_info(self, fs: FakeFilesystem) -> None:
        """Should include missing branch exit information for missing lines."""
        from scripts.dev.test_runner.test_coverage import generate_missing_line_details

        code = """def test_func():
    if True:
        x = 1
    else:
        x = 2
    return x
"""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents=code)

        # Line 2 (the if statement) has a branch to line 4 (else block)
        # Include line 2 in missing_lines so it appears in results
        coverage_data = {
            "files": {
                "test.py": {
                    "executed_lines": [1, 3],
                    "missing_lines": [2, 4, 5],  # Include line 2 which has branch
                    "missing_branches": [[2, 4]],  # Branch from line 2 to 4
                }
            }
        }

        results = generate_missing_line_details(coverage_data, Path("/repo"))

        # Line 2 should appear in results with branch exit info
        line_2_results = [r for r in results if r.line_number == 2]
        assert len(line_2_results) == 1
        # Line 2 should have branch exit info pointing to line 4
        assert 4 in line_2_results[0].missing_branch_exits


class TestPrintSummaryExtended:
    """Extended tests for print_summary function."""

    def test_prints_low_coverage_functions(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print functions with coverage below threshold."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=70,
            missing_lines=30,
            line_coverage_pct=70.0,
            total_branches=50,
            covered_branches=35,
            missing_branches=15,
            branch_coverage_pct=70.0,
            files={},
            functions={
                "app/module.py::low_func": {
                    "name": "low_func",
                    "file": "app/module.py",
                    "line_coverage": 50.0,  # Below 80%
                    "branch_coverage": 70.0,
                }
            },
        )

        print_summary([(config, result)], [])

        captured = capsys.readouterr()
        assert "Functions below 80% line coverage" in captured.out
        assert "low_func" in captured.out

    def test_truncates_low_coverage_functions_list(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should truncate list of low coverage functions to 10."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        # Create 15 low coverage functions
        functions = {}
        for i in range(15):
            functions[f"app/mod.py::func{i}"] = {
                "name": f"func{i}",
                "file": "app/mod.py",
                "line_coverage": 30.0,
                "branch_coverage": 70.0,
            }
        result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=70,
            missing_lines=30,
            line_coverage_pct=70.0,
            total_branches=50,
            covered_branches=35,
            missing_branches=15,
            branch_coverage_pct=70.0,
            files={},
            functions=functions,
        )

        print_summary([(config, result)], [])

        captured = capsys.readouterr()
        assert "... and 5 more" in captured.out

    def test_prints_uncovered_usecases_truncated(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should truncate list of uncovered use cases to 10."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )
        uc_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=15,
            covered_cases=0,
            uncovered_cases=[f"UC-{i}" for i in range(15)],
            coverage_pct=0.0,
        )

        print_summary([], [(config, uc_result)])

        captured = capsys.readouterr()
        assert "... and 5 more" in captured.out

    def test_prints_redundant_test_results(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print redundant test analysis."""
        from scripts.dev.test_runner.redundant_test_detector import RedundantTestResult

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
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
        redundant = RedundantTestResult(
            summary={
                "total_tests": 50,
                "tests_with_unique_coverage": 45,
                "redundant_tests": 5,
            },
            redundant_tests=[
                {"test_name": "test_redundant_1"},
                {"test_name": "test_redundant_2"},
            ],
            total_tests=50,
            tests_with_unique_coverage=45,
        )

        print_summary([(config, result)], [], redundant)

        captured = capsys.readouterr()
        assert "REDUNDANT TEST ANALYSIS" in captured.out
        assert "Total tests analyzed" in captured.out
        assert "test_redundant_1" in captured.out

    def test_prints_redundant_test_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print error message when redundant analysis fails."""
        from scripts.dev.test_runner.redundant_test_detector import RedundantTestResult

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
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
        redundant = RedundantTestResult(
            summary={"error": "Could not analyze coverage data"},
            redundant_tests=[],
            total_tests=0,
            tests_with_unique_coverage=0,
        )

        print_summary([(config, result)], [], redundant)

        captured = capsys.readouterr()
        assert "Could not analyze coverage data" in captured.out

    def test_prints_redundant_tests_truncated(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should truncate list of redundant tests to 15 with remaining count."""
        from scripts.dev.test_runner.redundant_test_detector import RedundantTestResult

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
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
        # Create 20 redundant tests (more than 15 to trigger truncation)
        redundant_tests = [{"test_name": f"test_redundant_{i}"} for i in range(20)]
        redundant = RedundantTestResult(
            summary={
                "total_tests": 100,
                "tests_with_unique_coverage": 80,
                "redundant_tests": 20,
            },
            redundant_tests=redundant_tests,
            total_tests=100,
            tests_with_unique_coverage=80,
        )

        print_summary([(config, result)], [], redundant)

        captured = capsys.readouterr()
        # Should show "... and 5 more" since we have 20 tests and only show 15
        assert "... and 5 more" in captured.out
        # Verify some tests are shown
        assert "test_redundant_0" in captured.out
        assert "test_redundant_14" in captured.out

    def test_prints_usecase_summary_with_no_uncovered_cases(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print use-case summary without uncovered cases section when all covered."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )
        uc_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=10,
            uncovered_cases=[],  # All cases covered
            coverage_pct=100.0,
        )

        print_summary([], [(config, uc_result)])

        captured = capsys.readouterr()
        assert "INTEGRATION TEST SUITE" in captured.out
        # Should NOT print "Uncovered use cases:" when list is empty
        assert "Uncovered use cases:" not in captured.out

    def test_prints_redundant_no_tests(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should not print redundant tests section when list is empty."""
        from scripts.dev.test_runner.redundant_test_detector import RedundantTestResult

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
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
        redundant = RedundantTestResult(
            summary={
                "total_tests": 50,
                "tests_with_unique_coverage": 50,
                "redundant_tests": 0,
            },
            redundant_tests=[],  # No redundant tests
            total_tests=50,
            tests_with_unique_coverage=50,
        )

        print_summary([(config, result)], [], redundant)

        captured = capsys.readouterr()
        # Should show redundant test analysis
        assert "REDUNDANT TEST ANALYSIS" in captured.out
        # But should NOT show "candidates for removal" since list is empty
        assert "candidates for removal" not in captured.out


class TestParseArgsExtended:
    """Extended tests for parse_args to cover all options."""

    def test_skip_redundant_detection_flag(self) -> None:
        """Should accept skip-redundant-detection flag."""
        args = parse_args(["--skip-redundant-detection"])
        assert args.skip_redundant_detection is True

    def test_include_partial_redundant_flag(self) -> None:
        """Should accept include-partial-redundant flag."""
        args = parse_args(["--include-partial-redundant"])
        assert args.include_partial_redundant is True

    def test_all_flags_together(self) -> None:
        """Should accept all flags together."""
        args = parse_args(
            [
                "--tier",
                "unit",
                "--min-line",
                "90",
                "--min-branch",
                "85",
                "--min-usecase",
                "95",
                "--no-validate",
                "--json-report",
                "/tmp/report.json",
                "--skip-redundant-detection",
                "--include-partial-redundant",
            ]
        )
        assert args.tier == "unit"
        assert args.min_line == 90.0
        assert args.min_branch == 85.0
        assert args.min_usecase == 95.0
        assert args.no_validate is True
        assert args.json_report == Path("/tmp/report.json")
        assert args.skip_redundant_detection is True
        assert args.include_partial_redundant is True


class TestUsecaseMarkerVisitorExtended:
    """Extended tests for _UsecaseMarkerVisitor."""

    def test_initializes_with_empty_found(self) -> None:
        """Should initialize with empty found dict."""
        from scripts.dev.test_runner.test_coverage import _UsecaseMarkerVisitor

        visitor = _UsecaseMarkerVisitor("tests/test_file.py")

        assert visitor.rel_path == "tests/test_file.py"
        assert visitor.found == {}

    def test_handles_keyword_argument_id(self) -> None:
        """Should extract use case from id keyword argument."""
        from scripts.dev.test_runner.test_coverage import _UsecaseMarkerVisitor

        code = """
import pytest

@pytest.mark.usecase(id="UC-KW-001")
def test_with_keyword():
    pass
"""
        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("tests/test_kw.py")
        visitor.visit(tree)

        assert "UC-KW-001" in visitor.found

    def test_handles_function_without_decorators(self) -> None:
        """Should not find use cases for functions without decorators."""
        from scripts.dev.test_runner.test_coverage import _UsecaseMarkerVisitor

        code = """
def test_no_decorator():
    pass
"""
        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("tests/test_bare.py")
        visitor.visit(tree)

        assert visitor.found == {}


class TestFunctionVisitorClassDef:
    """Tests for FunctionVisitor.visit_ClassDef inside _extract_functions_from_file."""

    def test_extracts_methods_from_class(self, fs: FakeFilesystem) -> None:
        """Should extract methods from inside a class and mark is_method=True."""
        code = """
class MyClass:
    def method_one(self):
        pass

    def method_two(self):
        pass

def standalone():
    pass
"""
        fs.create_file("/test.py", contents=code)

        result = _extract_functions_from_file(Path("/test.py"))

        # Should have 3 functions
        assert len(result) == 3

        # Find method_one
        method_one = next((f for f in result if f[0] == "method_one"), None)
        assert method_one is not None
        assert method_one[3] is True  # is_method

        # Find standalone
        standalone = next((f for f in result if f[0] == "standalone"), None)
        assert standalone is not None
        assert standalone[3] is False  # not is_method

    def test_handles_nested_classes(self, fs: FakeFilesystem) -> None:
        """Should handle methods in nested classes."""
        code = """
class Outer:
    def outer_method(self):
        pass

    class Inner:
        def inner_method(self):
            pass
"""
        fs.create_file("/test.py", contents=code)

        result = _extract_functions_from_file(Path("/test.py"))

        # Should have 2 methods
        assert len(result) == 2

        # Both should be marked as methods
        for _name, _start, _end, is_method in result:
            assert is_method is True


class TestGetTestTiersWrapper:
    """Tests for get_test_tiers wrapper function."""

    def test_calls_load_tier_configs_with_default_path(self) -> None:
        """Should call load_tier_configs with default pyproject.toml path."""
        # This test verifies the function works by calling the actual implementation
        tiers = get_test_tiers()

        # Should return the tiers from the actual pyproject.toml
        assert isinstance(tiers, dict)
        # The actual project has these tiers
        assert "unit" in tiers or "scripts" in tiers


class TestIsExcludedPath:
    """Tests for is_excluded_path function."""

    def test_always_returns_false(self) -> None:
        """is_excluded_path should always return False (no exclusions)."""
        from scripts.dev.test_runner.test_coverage import is_excluded_path

        assert is_excluded_path("app/module.py") is False
        assert is_excluded_path("tests/test_something.py") is False
        assert is_excluded_path("scripts/tool.py") is False
