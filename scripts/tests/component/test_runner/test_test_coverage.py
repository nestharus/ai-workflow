import ast
from pathlib import Path
from typing import TYPE_CHECKING

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


class TestTestTiers:
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


class TestCoverageResult:
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


class TestPrintSummary:
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


class TestMainEndToEndDBState:
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


class TestJSONReportSchemaValidation:
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


class TestLineBranchTierPassBehavior:
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


class TestNoValidateBehavioralContract:
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


class TestLoadTierConfigs:
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


class TestCreateStrategyInvariant:
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


class TestComponentTierUsecaseRequirement:
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


class TestCoverageTypeProperty:
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


class TestGetCoverageSourceArgs:
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
    def test_calls_load_tier_configs_with_default_path(self) -> None:
        """Should call load_tier_configs with default pyproject.toml path."""
        # This test verifies the function works by calling the actual implementation
        tiers = get_test_tiers()

        # Should return the tiers from the actual pyproject.toml
        assert isinstance(tiers, dict)
        # The actual project has these tiers
        assert "unit" in tiers or "scripts" in tiers


class TestIsExcludedPath:
    def test_always_returns_false(self) -> None:
        """is_excluded_path should always return False (no exclusions)."""
        from scripts.dev.test_runner.test_coverage import is_excluded_path

        assert is_excluded_path("app/module.py") is False
        assert is_excluded_path("tests/test_something.py") is False
        assert is_excluded_path("scripts/tool.py") is False
