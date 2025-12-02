"""Tests for scripts.llm_coverage_report and tools.llm_coverage_report modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from scripts import llm_coverage_report as script_module
from tools import llm_coverage_report as tools_module
from tools.llm_coverage_report import (
    FunctionCoverageGap,
    MissingBranchDetail,
    MissingLineDetail,
    _build_context,
    _calculate_function_coverage_gaps,
    _collect_code_gaps,
    _collect_function_coverage_gaps,
    _collect_usecase_gaps,
    _discover_tier_coverage_files,
    _extract_functions_from_file,
    _get_class_field_lines,
    _guess_repo_root,
    _is_in_service_layer,
    _is_private_function,
    _load_coverage_json,
    _load_pytest_testpaths,
    _load_usecase_registry,
    _read_source_lines,
    _scan_tests_for_usecases,
    _UsecaseMarkerVisitor,
    build_llm_coverage_document,
    main,
    parse_args,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestMissingLineDetail:
    """Tests for MissingLineDetail dataclass."""

    def test_dataclass_fields(self) -> None:
        """Should have all expected fields."""
        detail = MissingLineDetail(
            file="test.py",
            line_number=10,
            content="test content",
            context_before=[{"line_number": 9, "content": "before"}],
            context_after=[{"line_number": 11, "content": "after"}],
            missing_branch_exits=[12, 15],
        )
        assert detail.file == "test.py"
        assert detail.line_number == 10
        assert detail.content == "test content"
        assert len(detail.context_before) == 1
        assert len(detail.context_after) == 1
        assert detail.missing_branch_exits == [12, 15]


class TestMissingBranchDetail:
    """Tests for MissingBranchDetail dataclass."""

    def test_dataclass_fields(self) -> None:
        """Should have all expected fields."""
        detail = MissingBranchDetail(
            file="test.py",
            source_line=10,
            dest_line=15,
            source_content="if x:",
            dest_content="return",
        )
        assert detail.file == "test.py"
        assert detail.source_line == 10
        assert detail.dest_line == 15
        assert detail.source_content == "if x:"
        assert detail.dest_content == "return"


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_coverage_json_path(self) -> None:
        """Should default to coverage.json."""
        args = parse_args([])
        assert args.coverage_json == Path("coverage.json")

    def test_custom_coverage_json_path(self) -> None:
        """Should accept custom coverage JSON path."""
        args = parse_args(["--coverage-json", "/custom/coverage.json"])
        assert args.coverage_json == Path("/custom/coverage.json")

    def test_short_coverage_json_flag(self) -> None:
        """Should accept -c short flag for coverage JSON."""
        args = parse_args(["-c", "/custom/cov.json"])
        assert args.coverage_json == Path("/custom/cov.json")

    def test_default_use_cases_is_none(self) -> None:
        """Should default use-cases to None."""
        args = parse_args([])
        assert args.use_cases is None

    def test_custom_use_cases_path(self) -> None:
        """Should accept custom use-cases path."""
        args = parse_args(["--use-cases", "/custom/use_cases.yaml"])
        assert args.use_cases == Path("/custom/use_cases.yaml")

    def test_short_use_cases_flag(self) -> None:
        """Should accept -u short flag for use-cases."""
        args = parse_args(["-u", "/custom/uc.yaml"])
        assert args.use_cases == Path("/custom/uc.yaml")

    def test_default_repo_root_is_none(self) -> None:
        """Should default repo-root to None."""
        args = parse_args([])
        assert args.repo_root is None

    def test_custom_repo_root(self) -> None:
        """Should accept custom repo root."""
        args = parse_args(["--repo-root", "/custom/repo"])
        assert args.repo_root == Path("/custom/repo")

    def test_short_repo_root_flag(self) -> None:
        """Should accept -r short flag for repo root."""
        args = parse_args(["-r", "/custom/repo"])
        assert args.repo_root == Path("/custom/repo")

    def test_default_output_path(self) -> None:
        """Should default output to coverage_llm.json."""
        args = parse_args([])
        assert args.output == Path("coverage_llm.json")

    def test_custom_output_path(self) -> None:
        """Should accept custom output path."""
        args = parse_args(["--output", "/custom/output.json"])
        assert args.output == Path("/custom/output.json")

    def test_short_output_flag(self) -> None:
        """Should accept -o short flag for output."""
        args = parse_args(["-o", "/custom/out.json"])
        assert args.output == Path("/custom/out.json")

    def test_default_context_radius(self) -> None:
        """Should default context radius to 2."""
        args = parse_args([])
        assert args.context_radius == 2

    def test_custom_context_radius(self) -> None:
        """Should accept custom context radius."""
        args = parse_args(["--context-radius", "5"])
        assert args.context_radius == 5

    def test_short_context_radius_flag(self) -> None:
        """Should accept -n short flag for context radius."""
        args = parse_args(["-n", "3"])
        assert args.context_radius == 3

    def test_default_tests_root_is_none(self) -> None:
        """Should default tests-root to None."""
        args = parse_args([])
        assert args.tests_root is None

    def test_single_tests_root(self) -> None:
        """Should accept single tests root."""
        args = parse_args(["--tests-root", "tests"])
        assert args.tests_root == ["tests"]

    def test_multiple_tests_roots(self) -> None:
        """Should accept multiple tests roots."""
        args = parse_args(["--tests-root", "tests", "--tests-root", "scripts/tests"])
        assert args.tests_root == ["tests", "scripts/tests"]


class TestLoadCoverageJson:
    """Tests for _load_coverage_json function."""

    def test_raises_when_file_missing(self, fs: FakeFilesystem) -> None:
        """Should raise SystemExit when coverage JSON not found."""
        with pytest.raises(SystemExit) as exc_info:
            _load_coverage_json(Path("/nonexistent/coverage.json"))
        assert "not found" in str(exc_info.value)

    def test_loads_plain_coverage_json(self, fs: FakeFilesystem) -> None:
        """Should load plain coverage.json format."""
        coverage_data = {
            "meta": {"version": "7.0"},
            "files": {"app/main.py": {"executed_lines": [1, 2, 3]}},
            "totals": {"percent_covered": 80.0},
        }
        fs.create_file("/coverage.json", contents=json.dumps(coverage_data))

        result = _load_coverage_json(Path("/coverage.json"))

        assert "files" in result
        assert "app/main.py" in result["files"]

    def test_loads_wrapped_coverage_json(self, fs: FakeFilesystem) -> None:
        """Should load wrapped coverage JSON with raw_data key."""
        inner_data = {
            "meta": {"version": "7.0"},
            "files": {"app/main.py": {"executed_lines": [1, 2, 3]}},
            "totals": {"percent_covered": 80.0},
        }
        wrapped_data = {"raw_data": inner_data}
        fs.create_file("/coverage.json", contents=json.dumps(wrapped_data))

        result = _load_coverage_json(Path("/coverage.json"))

        assert "files" in result
        assert "app/main.py" in result["files"]

    def test_raises_when_no_files_section(self, fs: FakeFilesystem) -> None:
        """Should raise SystemExit when files section is missing."""
        bad_data = {"meta": {"version": "7.0"}}
        fs.create_file("/coverage.json", contents=json.dumps(bad_data))

        with pytest.raises(SystemExit) as exc_info:
            _load_coverage_json(Path("/coverage.json"))
        assert "does not contain a 'files' section" in str(exc_info.value)


class TestReadSourceLines:
    """Tests for _read_source_lines function."""

    def test_reads_source_file(self, fs: FakeFilesystem) -> None:
        """Should read source file and return lines."""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents="line1\nline2\nline3")

        result = _read_source_lines(Path("/repo"), "test.py")

        assert result == ["line1", "line2", "line3"]

    def test_returns_none_for_missing_file(self, fs: FakeFilesystem) -> None:
        """Should return None for missing file."""
        fs.create_dir("/repo")

        result = _read_source_lines(Path("/repo"), "nonexistent.py")

        assert result is None

    def test_handles_empty_file(self, fs: FakeFilesystem) -> None:
        """Should return empty list for empty file (splitlines behavior)."""
        fs.create_dir("/repo")
        fs.create_file("/repo/empty.py", contents="")

        result = _read_source_lines(Path("/repo"), "empty.py")

        # "".splitlines() returns []
        assert result == []


class TestBuildContext:
    """Tests for _build_context function."""

    def test_builds_context_for_middle_line(self) -> None:
        """Should build context for line in middle of file."""
        lines = ["line1", "line2", "line3", "line4", "line5"]

        before, after = _build_context(lines, lineno=3, radius=1)

        assert before == [{"line_number": 2, "content": "line2"}]
        assert after == [{"line_number": 4, "content": "line4"}]

    def test_builds_context_for_first_line(self) -> None:
        """Should build context for first line with no before."""
        lines = ["line1", "line2", "line3"]

        before, after = _build_context(lines, lineno=1, radius=2)

        assert before == []
        assert len(after) == 2

    def test_builds_context_for_last_line(self) -> None:
        """Should build context for last line with no after."""
        lines = ["line1", "line2", "line3"]

        before, after = _build_context(lines, lineno=3, radius=2)

        assert len(before) == 2
        assert after == []

    def test_builds_larger_radius(self) -> None:
        """Should build context with larger radius."""
        lines = ["a", "b", "c", "d", "e", "f", "g"]

        before, after = _build_context(lines, lineno=4, radius=2)

        assert len(before) == 2
        assert len(after) == 2
        assert before[0]["content"] == "b"
        assert after[-1]["content"] == "f"


class TestCollectCodeGaps:
    """Tests for _collect_code_gaps function."""

    def test_collects_missing_lines(self, fs: FakeFilesystem) -> None:
        """Should collect missing line details."""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents="line1\nline2\nline3\nline4\nline5")

        coverage_data = {
            "meta": {"version": "7.0"},
            "files": {
                "test.py": {
                    "missing_lines": [2, 4],
                    "missing_branches": [],
                }
            },
            "totals": {"percent_covered": 60.0},
        }

        result = _collect_code_gaps(coverage_data, Path("/repo"), context_radius=1)

        assert len(result["missing_lines"]) == 2
        assert result["missing_lines"][0]["line_number"] == 2
        assert result["missing_lines"][0]["content"] == "line2"

    def test_collects_missing_branches(self, fs: FakeFilesystem) -> None:
        """Should collect missing branch details."""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents="if x:\n    pass\nelse:\n    fail")

        coverage_data = {
            "meta": {"version": "7.0"},
            "files": {
                "test.py": {
                    "missing_lines": [],
                    "missing_branches": [[1, 3]],
                }
            },
            "totals": {},
        }

        result = _collect_code_gaps(coverage_data, Path("/repo"), context_radius=1)

        assert len(result["missing_branches"]) == 1
        assert result["missing_branches"][0]["source_line"] == 1
        assert result["missing_branches"][0]["dest_line"] == 3

    def test_handles_missing_source_file(self, fs: FakeFilesystem) -> None:
        """Should handle missing source file gracefully."""
        fs.create_dir("/repo")

        coverage_data = {
            "meta": {},
            "files": {
                "nonexistent.py": {
                    "missing_lines": [],
                    "missing_branches": [[1, 3]],
                }
            },
            "totals": {},
        }

        result = _collect_code_gaps(coverage_data, Path("/repo"), context_radius=1)

        assert len(result["missing_branches"]) == 1
        assert result["missing_branches"][0]["source_content"] == ""

    def test_annotates_lines_with_branch_exits(self, fs: FakeFilesystem) -> None:
        """Should annotate missing lines with their missing branch exits."""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents="if x:\n    pass\nelse:\n    fail")

        coverage_data = {
            "meta": {},
            "files": {
                "test.py": {
                    "missing_lines": [1],
                    "missing_branches": [[1, 2], [1, 4]],
                }
            },
            "totals": {},
        }

        result = _collect_code_gaps(coverage_data, Path("/repo"), context_radius=1)

        line_detail = result["missing_lines"][0]
        assert 2 in line_detail["missing_branch_exits"]
        assert 4 in line_detail["missing_branch_exits"]

    def test_handles_invalid_branch_arcs(self, fs: FakeFilesystem) -> None:
        """Should ignore invalid branch arc formats."""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents="line1")

        coverage_data = {
            "meta": {},
            "files": {
                "test.py": {
                    "missing_lines": [],
                    "missing_branches": [[1], "invalid", [1, 2, 3]],
                }
            },
            "totals": {},
        }

        result = _collect_code_gaps(coverage_data, Path("/repo"), context_radius=1)

        # Only valid [src, dst] arcs should be processed
        assert len(result["missing_branches"]) == 0

    def test_handles_out_of_bounds_line_numbers(self, fs: FakeFilesystem) -> None:
        """Should handle line numbers outside file bounds."""
        fs.create_dir("/repo")
        fs.create_file("/repo/test.py", contents="line1\nline2")

        coverage_data = {
            "meta": {},
            "files": {
                "test.py": {
                    "missing_lines": [0, 100],  # Out of bounds
                    "missing_branches": [],
                }
            },
            "totals": {},
        }

        result = _collect_code_gaps(coverage_data, Path("/repo"), context_radius=1)

        assert len(result["missing_lines"]) == 2
        # Out of bounds lines should have empty content
        assert result["missing_lines"][0]["content"] == ""


class TestUsecaseMarkerVisitor:
    """Tests for _UsecaseMarkerVisitor class."""

    def test_finds_pytest_mark_usecase(self) -> None:
        """Should find pytest.mark.usecase markers."""
        code = """
import pytest

@pytest.mark.usecase("UC-TEST-001")
def test_example():
    pass
"""
        import ast

        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("test.py")
        visitor.visit(tree)

        assert "UC-TEST-001" in visitor.found
        assert visitor.found["UC-TEST-001"][0]["test_function"] == "test_example"

    def test_finds_mark_usecase(self) -> None:
        """Should find mark.usecase markers."""
        code = """
from pytest import mark

@mark.usecase("UC-MARK-001")
def test_with_mark():
    pass
"""
        import ast

        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("test.py")
        visitor.visit(tree)

        assert "UC-MARK-001" in visitor.found

    def test_finds_usecase_directly(self) -> None:
        """Should find bare usecase decorator."""
        code = """
@usecase("UC-BARE-001")
def test_bare():
    pass
"""
        import ast

        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("test.py")
        visitor.visit(tree)

        assert "UC-BARE-001" in visitor.found

    def test_finds_usecase_with_id_kwarg(self) -> None:
        """Should find usecase marker with id keyword argument."""
        code = """
import pytest

@pytest.mark.usecase(id="UC-KWARG-001")
def test_kwarg():
    pass
"""
        import ast

        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("test.py")
        visitor.visit(tree)

        assert "UC-KWARG-001" in visitor.found

    def test_finds_multiple_usecases_same_function(self) -> None:
        """Should find multiple usecase markers on same function."""
        code = """
import pytest

@pytest.mark.usecase("UC-MULTI-001")
@pytest.mark.usecase("UC-MULTI-002")
def test_multi():
    pass
"""
        import ast

        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("test.py")
        visitor.visit(tree)

        assert "UC-MULTI-001" in visitor.found
        assert "UC-MULTI-002" in visitor.found

    def test_finds_async_function_usecases(self) -> None:
        """Should find usecase markers on async functions."""
        code = """
import pytest

@pytest.mark.usecase("UC-ASYNC-001")
async def test_async():
    pass
"""
        import ast

        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("test.py")
        visitor.visit(tree)

        assert "UC-ASYNC-001" in visitor.found

    def test_ignores_non_uc_prefixed_markers(self) -> None:
        """Should ignore usecase markers without UC- prefix."""
        code = """
import pytest

@pytest.mark.usecase("NOT-UC-001")
def test_no_prefix():
    pass
"""
        import ast

        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("test.py")
        visitor.visit(tree)

        assert "NOT-UC-001" not in visitor.found
        assert len(visitor.found) == 0

    def test_ignores_non_usecase_decorators(self) -> None:
        """Should ignore non-usecase decorators."""
        code = """
import pytest

@pytest.mark.parametrize("x", [1, 2])
@pytest.mark.skip(reason="test")
def test_other():
    pass
"""
        import ast

        tree = ast.parse(code)
        visitor = _UsecaseMarkerVisitor("test.py")
        visitor.visit(tree)

        assert len(visitor.found) == 0


class TestScanTestsForUsecases:
    """Tests for _scan_tests_for_usecases function."""

    def test_scans_test_files(self, fs: FakeFilesystem) -> None:
        """Should scan test files for usecase markers."""
        fs.create_dir("/repo/tests")
        test_code = """
import pytest

@pytest.mark.usecase("UC-SCAN-001")
def test_scanned():
    pass
"""
        fs.create_file("/repo/tests/test_example.py", contents=test_code)

        result = _scan_tests_for_usecases(Path("/repo"), ["tests"])

        assert "UC-SCAN-001" in result
        assert result["UC-SCAN-001"][0]["file"] == "tests/test_example.py"

    def test_scans_multiple_roots(self, fs: FakeFilesystem) -> None:
        """Should scan multiple test roots."""
        fs.create_dir("/repo/tests")
        fs.create_dir("/repo/scripts/tests")

        test1 = """
import pytest

@pytest.mark.usecase("UC-ROOT1-001")
def test_one():
    pass
"""
        test2 = """
import pytest

@pytest.mark.usecase("UC-ROOT2-001")
def test_two():
    pass
"""
        fs.create_file("/repo/tests/test_one.py", contents=test1)
        fs.create_file("/repo/scripts/tests/test_two.py", contents=test2)

        result = _scan_tests_for_usecases(Path("/repo"), ["tests", "scripts/tests"])

        assert "UC-ROOT1-001" in result
        assert "UC-ROOT2-001" in result

    def test_ignores_syntax_errors(self, fs: FakeFilesystem) -> None:
        """Should ignore files with syntax errors."""
        fs.create_dir("/repo/tests")
        fs.create_file("/repo/tests/test_syntax.py", contents="def broken syntax:")
        fs.create_file(
            "/repo/tests/test_valid.py",
            contents='import pytest\n@pytest.mark.usecase("UC-VALID")\ndef test_v(): pass',
        )

        result = _scan_tests_for_usecases(Path("/repo"), ["tests"])

        assert "UC-VALID" in result

    def test_handles_missing_root(self, fs: FakeFilesystem) -> None:
        """Should handle non-existent test roots gracefully."""
        fs.create_dir("/repo")

        result = _scan_tests_for_usecases(Path("/repo"), ["nonexistent"])

        assert len(result) == 0


class TestLoadUsecaseRegistry:
    """Tests for _load_usecase_registry function."""

    def test_returns_none_for_missing_file(self, fs: FakeFilesystem) -> None:
        """Should return None when registry file is missing."""
        result = _load_usecase_registry(Path("/nonexistent.yaml"))
        assert result is None

    def test_loads_yaml_registry(self, fs: FakeFilesystem) -> None:
        """Should load YAML use-case registry."""
        registry_content = """
version: "1.0"
features:
  auth:
    name: Authentication
    use_cases:
      - id: UC-AUTH-001
        description: User login
"""
        fs.create_file("/use_cases.yaml", contents=registry_content)

        result = _load_usecase_registry(Path("/use_cases.yaml"))

        assert result is not None
        assert result["version"] == "1.0"
        assert "auth" in result["features"]

    def test_returns_empty_dict_for_empty_file(self, fs: FakeFilesystem) -> None:
        """Should return empty dict for empty YAML file."""
        fs.create_file("/empty.yaml", contents="")

        result = _load_usecase_registry(Path("/empty.yaml"))

        assert result == {}


class TestCollectUsecaseGaps:
    """Tests for _collect_usecase_gaps function."""

    def test_identifies_uncovered_usecases(self, fs: FakeFilesystem) -> None:
        """Should identify use-cases without test coverage."""
        # Create directory structure first
        fs.create_dir("/repo/tests")

        registry_content = """
version: "1.0"
features:
  auth:
    name: Authentication
    use_cases:
      - id: UC-AUTH-001
        description: User login
      - id: UC-AUTH-002
        description: User logout
"""
        fs.create_file("/repo/tests/use_cases.yaml", contents=registry_content)

        # Test that only covers UC-AUTH-001
        test_code = """
import pytest

@pytest.mark.usecase("UC-AUTH-001")
def test_login():
    pass
"""
        fs.create_file("/repo/tests/test_auth.py", contents=test_code)

        result = _collect_usecase_gaps(Path("/repo"), Path("/repo/tests/use_cases.yaml"), ["tests"])

        assert result["totals"]["total_use_cases"] == 2
        assert result["totals"]["covered_use_cases"] == 1
        assert result["totals"]["uncovered_use_cases"] == 1
        uncovered_ids = [uc["id"] for uc in result["uncovered_use_cases"]]
        assert "UC-AUTH-002" in uncovered_ids

    def test_excludes_future_usecases(self, fs: FakeFilesystem) -> None:
        """Should exclude use-cases marked as future."""
        registry_content = """
features:
  auth:
    name: Authentication
    use_cases:
      - id: UC-AUTH-001
        description: Current feature
      - id: UC-AUTH-002
        description: Future feature
        future: true
"""
        fs.create_file("/repo/use_cases.yaml", contents=registry_content)
        fs.create_dir("/repo/tests")

        result = _collect_usecase_gaps(Path("/repo"), Path("/repo/use_cases.yaml"), ["tests"])

        assert result["totals"]["total_use_cases"] == 1
        uc_ids = [uc["id"] for uc in result["use_cases"]]
        assert "UC-AUTH-002" not in uc_ids

    def test_handles_missing_registry(self, fs: FakeFilesystem) -> None:
        """Should return error for missing registry."""
        fs.create_dir("/repo")

        result = _collect_usecase_gaps(Path("/repo"), Path("/repo/nonexistent.yaml"), ["tests"])

        assert "error" in result
        assert "not found" in result["error"]

    def test_tracks_tier_statistics(self, fs: FakeFilesystem) -> None:
        """Should track statistics per test tier."""
        registry_content = """
features:
  api:
    name: API
    use_cases:
      - id: UC-API-001
        test_tier: e2e
      - id: UC-API-002
        test_tier: integration
"""
        fs.create_file("/repo/use_cases.yaml", contents=registry_content)
        fs.create_dir("/repo/tests")

        result = _collect_usecase_gaps(Path("/repo"), Path("/repo/use_cases.yaml"), ["tests"])

        assert "tier_stats" in result
        assert result["tier_stats"]["e2e"]["total"] == 1
        assert result["tier_stats"]["integration"]["total"] == 1


class TestGuessRepoRoot:
    """Tests for _guess_repo_root function."""

    def test_uses_explicit_root(self, fs: FakeFilesystem) -> None:
        """Should use explicitly provided root."""
        fs.create_dir("/explicit/repo")

        result = _guess_repo_root(Path("/explicit/repo"))

        assert result == Path("/explicit/repo")

    def test_resolves_explicit_root(self, fs: FakeFilesystem) -> None:
        """Should resolve explicit root path."""
        fs.create_dir("/repo")
        fs.create_dir("/repo/subdir")

        result = _guess_repo_root(Path("/repo/subdir/../"))

        assert "/repo" in str(result)


class TestLoadPytestTestpaths:
    """Tests for _load_pytest_testpaths function."""

    def test_returns_none_when_no_pyproject(self, fs: FakeFilesystem) -> None:
        """Should return None when pyproject.toml is missing."""
        fs.create_dir("/repo")

        result = _load_pytest_testpaths(Path("/repo"))

        assert result is None

    def test_loads_testpaths_from_pyproject(self, fs: FakeFilesystem) -> None:
        """Should load testpaths from pyproject.toml."""
        pyproject_content = """
[tool.pytest.ini_options]
testpaths = ["tests", "scripts/tests"]
"""
        fs.create_dir("/repo")
        fs.create_file("/repo/pyproject.toml", contents=pyproject_content)

        result = _load_pytest_testpaths(Path("/repo"))

        assert result == ["tests", "scripts/tests"]

    def test_handles_string_testpath(self, fs: FakeFilesystem) -> None:
        """Should handle string testpaths value."""
        pyproject_content = """
[tool.pytest.ini_options]
testpaths = "tests"
"""
        fs.create_dir("/repo")
        fs.create_file("/repo/pyproject.toml", contents=pyproject_content)

        result = _load_pytest_testpaths(Path("/repo"))

        assert result == ["tests"]


class TestBuildLlmCoverageDocument:
    """Tests for build_llm_coverage_document function."""

    def test_builds_combined_document(self, fs: FakeFilesystem) -> None:
        """Should build combined coverage document."""
        # Set up minimal coverage.json
        coverage_data = {
            "meta": {"version": "7.0"},
            "files": {},
            "totals": {"percent_covered": 100.0},
        }
        fs.create_dir("/repo")
        fs.create_file("/repo/coverage.json", contents=json.dumps(coverage_data))

        # Set up minimal use_cases.yaml
        usecase_content = """
version: "1.0"
features: {}
"""
        fs.create_file("/repo/use_cases.yaml", contents=usecase_content)
        fs.create_dir("/repo/tests")

        result = build_llm_coverage_document(
            repo_root=Path("/repo"),
            coverage_json_path=Path("/repo/coverage.json"),
            usecase_yaml_path=Path("/repo/use_cases.yaml"),
            tests_roots=["tests"],
            context_radius=2,
        )

        assert "generated_at" in result
        assert "code_coverage" in result
        assert "use_case_coverage" in result
        assert "prompting_notes" in result

    def test_includes_config(self, fs: FakeFilesystem) -> None:
        """Should include configuration in document."""
        coverage_data: dict[str, Any] = {"meta": {}, "files": {}, "totals": {}}
        fs.create_dir("/repo")
        fs.create_file("/repo/coverage.json", contents=json.dumps(coverage_data))
        fs.create_file("/repo/use_cases.yaml", contents="features: {}")
        fs.create_dir("/repo/tests")

        result = build_llm_coverage_document(
            repo_root=Path("/repo"),
            coverage_json_path=Path("/repo/coverage.json"),
            usecase_yaml_path=Path("/repo/use_cases.yaml"),
            tests_roots=["tests", "scripts/tests"],
            context_radius=3,
        )

        assert result["config"]["context_radius"] == 3
        assert "tests" in result["config"]["tests_roots"]


class TestMain:
    """Tests for main function."""

    def test_writes_output_file(self, fs: FakeFilesystem) -> None:
        """Should write output JSON file."""
        coverage_data: dict[str, Any] = {"meta": {}, "files": {}, "totals": {}}
        fs.create_dir("/repo")
        fs.create_dir("/repo/tests")
        fs.create_file("/repo/coverage.json", contents=json.dumps(coverage_data))
        fs.create_file("/repo/tests/use_cases.yaml", contents="features: {}")

        # Mock _guess_repo_root to return our fake repo
        with patch.object(tools_module, "_guess_repo_root", return_value=Path("/repo")):
            main(
                [
                    "-c",
                    "/repo/coverage.json",
                    "-o",
                    "/repo/output.json",
                    "-u",
                    "/repo/tests/use_cases.yaml",
                ]
            )

        assert Path("/repo/output.json").exists()

    def test_creates_output_directory(self, fs: FakeFilesystem) -> None:
        """Should create output directory if missing."""
        coverage_data: dict[str, Any] = {"meta": {}, "files": {}, "totals": {}}
        fs.create_dir("/repo")
        fs.create_dir("/repo/tests")
        fs.create_file("/repo/coverage.json", contents=json.dumps(coverage_data))
        fs.create_file("/repo/tests/use_cases.yaml", contents="features: {}")

        with patch.object(tools_module, "_guess_repo_root", return_value=Path("/repo")):
            main(
                [
                    "-c",
                    "/repo/coverage.json",
                    "-o",
                    "/repo/output/nested/result.json",
                    "-u",
                    "/repo/tests/use_cases.yaml",
                ]
            )

        assert Path("/repo/output/nested/result.json").exists()

    def test_prints_summary(self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print summary after writing output."""
        coverage_data: dict[str, Any] = {"meta": {}, "files": {}, "totals": {}}
        fs.create_dir("/repo")
        fs.create_dir("/repo/tests")
        fs.create_file("/repo/coverage.json", contents=json.dumps(coverage_data))
        fs.create_file("/repo/tests/use_cases.yaml", contents="features: {}")

        with patch.object(tools_module, "_guess_repo_root", return_value=Path("/repo")):
            main(
                [
                    "-c",
                    "/repo/coverage.json",
                    "-o",
                    "/repo/output.json",
                    "-u",
                    "/repo/tests/use_cases.yaml",
                ]
            )

        captured = capsys.readouterr()
        assert "Wrote LLM coverage report" in captured.out
        assert "Top-level keys" in captured.out


class TestScriptModuleWrapper:
    """Tests for scripts.llm_coverage_report wrapper module."""

    def test_debug_enabled_returns_false_by_default(self) -> None:
        """Should return False when DEBUG/VERBOSE not set."""
        with patch.dict("os.environ", {}, clear=True):
            result = script_module._debug_enabled()
        assert result is False

    def test_debug_enabled_returns_true_for_debug_1(self) -> None:
        """Should return True when DEBUG=1."""
        with patch.dict("os.environ", {"DEBUG": "1"}):
            result = script_module._debug_enabled()
        assert result is True

    def test_debug_enabled_returns_true_for_verbose_true(self) -> None:
        """Should return True when VERBOSE=true."""
        with patch.dict("os.environ", {"VERBOSE": "true"}):
            result = script_module._debug_enabled()
        assert result is True

    def test_debug_enabled_returns_true_for_debug_yes(self) -> None:
        """Should return True when DEBUG=yes."""
        with patch.dict("os.environ", {"DEBUG": "yes"}):
            result = script_module._debug_enabled()
        assert result is True

    def test_debug_enabled_returns_true_for_debug_on(self) -> None:
        """Should return True when DEBUG=on."""
        with patch.dict("os.environ", {"DEBUG": "on"}):
            result = script_module._debug_enabled()
        assert result is True

    def test_debug_enabled_returns_false_for_debug_0(self) -> None:
        """Should return False when DEBUG=0."""
        with patch.dict("os.environ", {"DEBUG": "0"}):
            result = script_module._debug_enabled()
        assert result is False

    def test_main_returns_zero_on_success(self, fs: FakeFilesystem) -> None:
        """Should return 0 on successful execution."""
        coverage_data: dict[str, Any] = {"meta": {}, "files": {}, "totals": {}}
        fs.create_dir("/repo")
        fs.create_dir("/repo/tests")
        fs.create_file("/repo/coverage.json", contents=json.dumps(coverage_data))
        fs.create_file("/repo/tests/use_cases.yaml", contents="features: {}")

        with (
            patch.object(tools_module, "_guess_repo_root", return_value=Path("/repo")),
            patch(
                "sys.argv",
                [
                    "script",
                    "-c",
                    "/repo/coverage.json",
                    "-o",
                    "/repo/output.json",
                    "-u",
                    "/repo/tests/use_cases.yaml",
                ],
            ),
        ):
            result = script_module.main()

        assert result == 0

    def test_main_returns_one_on_exception(self) -> None:
        """Should return 1 when exception occurs."""
        with patch.object(
            script_module, "generate_llm_coverage", side_effect=RuntimeError("Test error")
        ):
            result = script_module.main()
        assert result == 1

    def test_main_handles_system_exit(self) -> None:
        """Should propagate SystemExit with correct code."""
        with patch.object(script_module, "generate_llm_coverage", side_effect=SystemExit(42)):
            with pytest.raises(SystemExit) as exc_info:
                script_module.main()
            assert exc_info.value.code == 42

    def test_main_handles_non_int_system_exit(self) -> None:
        """Should normalize non-int SystemExit code to 1."""
        with patch.object(
            script_module, "generate_llm_coverage", side_effect=SystemExit("error message")
        ):
            with pytest.raises(SystemExit) as exc_info:
                script_module.main()
            assert exc_info.value.code == 1

    def test_main_prints_traceback_in_debug_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print traceback when DEBUG is enabled."""
        with (
            patch.dict("os.environ", {"DEBUG": "1"}),
            patch.object(
                script_module, "generate_llm_coverage", side_effect=RuntimeError("Test error")
            ),
        ):
            result = script_module.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Failed to generate" in captured.err
        assert "RuntimeError" in captured.err

    def test_main_hides_traceback_without_debug(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should hide traceback when DEBUG is not enabled."""
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(
                script_module, "generate_llm_coverage", side_effect=RuntimeError("Test error")
            ),
        ):
            result = script_module.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Failed to generate" in captured.err
        # Traceback should not be present without debug
        assert "Traceback" not in captured.err


class TestFunctionCoverageGap:
    """Tests for FunctionCoverageGap dataclass."""

    def test_dataclass_fields(self) -> None:
        """Should have all expected fields."""
        gap = FunctionCoverageGap(
            file="app/test.py",
            function_name="test_func",
            start_line=10,
            end_line=20,
            line_coverage_pct=60.0,
            branch_coverage_pct=50.0,
            missing_lines=[12, 15, 18],
            missing_branches=[(10, 12), (10, 15)],
            tier="unit",
            threshold=80.0,
        )
        assert gap.file == "app/test.py"
        assert gap.function_name == "test_func"
        assert gap.start_line == 10
        assert gap.end_line == 20
        assert gap.line_coverage_pct == 60.0
        assert gap.branch_coverage_pct == 50.0
        assert gap.missing_lines == [12, 15, 18]
        assert gap.missing_branches == [(10, 12), (10, 15)]
        assert gap.tier == "unit"
        assert gap.threshold == 80.0


class TestGetClassFieldLines:
    """Tests for _get_class_field_lines function."""

    def test_finds_class_field_annotations(self, fs: FakeFilesystem) -> None:
        """Should find annotated class fields."""
        code = """
class MyModel:
    name: str
    age: int
    active: bool = True
"""
        fs.create_file("/test.py", contents=code)

        result = _get_class_field_lines(Path("/test.py"))

        # Lines 3, 4, 5 are the field definitions
        assert 3 in result
        assert 4 in result
        assert 5 in result

    def test_ignores_function_definitions(self, fs: FakeFilesystem) -> None:
        """Should ignore function definitions inside classes."""
        code = """
class MyModel:
    name: str

    def __init__(self):
        pass
"""
        fs.create_file("/test.py", contents=code)

        result = _get_class_field_lines(Path("/test.py"))

        assert 3 in result  # name: str
        assert 5 not in result  # def __init__

    def test_returns_empty_for_missing_file(self, fs: FakeFilesystem) -> None:
        """Should return empty set for missing file."""
        result = _get_class_field_lines(Path("/nonexistent.py"))
        assert result == set()

    def test_returns_empty_for_syntax_error(self, fs: FakeFilesystem) -> None:
        """Should return empty set for file with syntax error."""
        fs.create_file("/bad.py", contents="def broken syntax:")

        result = _get_class_field_lines(Path("/bad.py"))

        assert result == set()

    def test_handles_nested_classes(self, fs: FakeFilesystem) -> None:
        """Should find fields in nested classes."""
        code = """
class Outer:
    outer_field: str

    class Inner:
        inner_field: int
"""
        fs.create_file("/test.py", contents=code)

        result = _get_class_field_lines(Path("/test.py"))

        assert 3 in result  # outer_field
        assert 6 in result  # inner_field


class TestExtractFunctionsFromFile:
    """Tests for _extract_functions_from_file function."""

    def test_extracts_function_definitions(self, fs: FakeFilesystem) -> None:
        """Should extract function definitions."""
        code = """
def func_one():
    pass

def func_two():
    return 1
"""
        fs.create_file("/test.py", contents=code)

        result = _extract_functions_from_file(Path("/test.py"))

        func_names = [f[0] for f in result]
        assert "func_one" in func_names
        assert "func_two" in func_names

    def test_extracts_async_functions(self, fs: FakeFilesystem) -> None:
        """Should extract async function definitions."""
        code = """
async def async_func():
    pass
"""
        fs.create_file("/test.py", contents=code)

        result = _extract_functions_from_file(Path("/test.py"))

        func_names = [f[0] for f in result]
        assert "async_func" in func_names

    def test_identifies_methods_in_class(self, fs: FakeFilesystem) -> None:
        """Should identify methods inside classes."""
        code = """
class MyClass:
    def method(self):
        pass

def standalone():
    pass
"""
        fs.create_file("/test.py", contents=code)

        result = _extract_functions_from_file(Path("/test.py"))

        # Find method and standalone
        method_entry = next(f for f in result if f[0] == "method")
        standalone_entry = next(f for f in result if f[0] == "standalone")

        # method should have is_method=True (index 3)
        assert method_entry[3] is True
        # standalone should have is_method=False
        assert standalone_entry[3] is False

    def test_returns_empty_for_missing_file(self, fs: FakeFilesystem) -> None:
        """Should return empty list for missing file."""
        result = _extract_functions_from_file(Path("/nonexistent.py"))
        assert result == []

    def test_returns_empty_for_syntax_error(self, fs: FakeFilesystem) -> None:
        """Should return empty list for file with syntax error."""
        fs.create_file("/bad.py", contents="def broken syntax:")

        result = _extract_functions_from_file(Path("/bad.py"))

        assert result == []

    def test_extracts_line_ranges(self, fs: FakeFilesystem) -> None:
        """Should extract correct start and end lines."""
        code = """
def func():
    x = 1
    y = 2
    return x + y
"""
        fs.create_file("/test.py", contents=code)

        result = _extract_functions_from_file(Path("/test.py"))

        func_entry = next(f for f in result if f[0] == "func")
        start_line, end_line = func_entry[1], func_entry[2]
        assert start_line == 2  # def func():
        assert end_line >= 5  # return x + y


class TestIsPrivateFunction:
    """Tests for _is_private_function function."""

    def test_public_function_is_not_private(self) -> None:
        """Should return False for public function."""
        assert _is_private_function("my_function") is False

    def test_single_underscore_is_private(self) -> None:
        """Should return True for single underscore prefix."""
        assert _is_private_function("_helper") is True

    def test_double_underscore_is_private(self) -> None:
        """Should return True for double underscore prefix."""
        assert _is_private_function("__internal") is True

    def test_init_is_not_private(self) -> None:
        """Should return False for __init__."""
        assert _is_private_function("__init__") is False

    def test_call_is_not_private(self) -> None:
        """Should return False for __call__."""
        assert _is_private_function("__call__") is False

    def test_other_dunder_is_private(self) -> None:
        """Should return True for other dunder methods."""
        assert _is_private_function("__str__") is True
        assert _is_private_function("__repr__") is True


class TestIsInServiceLayer:
    """Tests for _is_in_service_layer function."""

    def test_service_layer_path(self) -> None:
        """Should return True for paths in app/services."""
        assert _is_in_service_layer("app/services/user_service.py") is True
        assert _is_in_service_layer("app/services/nested/auth.py") is True

    def test_non_service_path(self) -> None:
        """Should return False for paths outside app/services."""
        assert _is_in_service_layer("app/main.py") is False
        assert _is_in_service_layer("app/api/routes.py") is False
        assert _is_in_service_layer("tests/test_service.py") is False


class TestCalculateFunctionCoverageGaps:
    """Tests for _calculate_function_coverage_gaps function."""

    def test_identifies_functions_below_threshold(self, fs: FakeFilesystem) -> None:
        """Should identify functions with coverage below threshold."""
        fs.create_dir("/repo")
        code = """
def low_coverage():
    x = 1
    y = 2
    z = 3
    return x + y + z

def full_coverage():
    return 1
"""
        fs.create_file("/repo/app/test.py", contents=code)

        coverage_data = {
            "files": {
                "app/test.py": {
                    "executed_lines": [2, 7, 8, 9],
                    "missing_lines": [3, 4, 5, 6],
                    "missing_branches": [],
                }
            }
        }

        result = _calculate_function_coverage_gaps(coverage_data, Path("/repo"), "unit", 80.0, 80.0)

        # low_coverage should be below threshold
        gap_funcs = [g.function_name for g in result]
        assert "low_coverage" in gap_funcs

    def test_excludes_class_fields(self, fs: FakeFilesystem) -> None:
        """Should exclude class field lines from coverage calculation."""
        fs.create_dir("/repo")
        code = """
class Model:
    field1: str
    field2: int

    def method(self):
        return self.field1
"""
        fs.create_file("/repo/app/test.py", contents=code)

        coverage_data = {
            "files": {
                "app/test.py": {
                    "executed_lines": [6, 7],
                    "missing_lines": [3, 4],  # Class fields
                    "missing_branches": [],
                }
            }
        }

        result = _calculate_function_coverage_gaps(coverage_data, Path("/repo"), "unit", 80.0, 80.0)

        # method should not be flagged as low coverage since class fields excluded
        gap_funcs = [g.function_name for g in result]
        # If method is executed fully, it shouldn't appear
        # The class fields shouldn't count against it
        assert "method" not in gap_funcs or result[0].line_coverage_pct >= 80.0

    def test_skips_private_functions_when_configured(self, fs: FakeFilesystem) -> None:
        """Should skip private functions when skip_private=True."""
        fs.create_dir("/repo")
        code = """
def public_func():
    pass

def _private_func():
    pass
"""
        fs.create_file("/repo/app/test.py", contents=code)

        coverage_data = {
            "files": {
                "app/test.py": {
                    "executed_lines": [],
                    "missing_lines": [2, 3, 5, 6],
                    "missing_branches": [],
                }
            }
        }

        result = _calculate_function_coverage_gaps(
            coverage_data, Path("/repo"), "component", 80.0, 80.0, skip_private=True
        )

        gap_funcs = [g.function_name for g in result]
        assert "_private_func" not in gap_funcs

    def test_filters_service_layer_only(self, fs: FakeFilesystem) -> None:
        """Should filter to service layer files when configured."""
        fs.create_dir("/repo")
        fs.create_dir("/repo/app/services")
        fs.create_dir("/repo/app/api")

        service_code = """
def service_func():
    pass
"""
        api_code = """
def api_func():
    pass
"""
        fs.create_file("/repo/app/services/svc.py", contents=service_code)
        fs.create_file("/repo/app/api/route.py", contents=api_code)

        coverage_data = {
            "files": {
                "app/services/svc.py": {
                    "executed_lines": [],
                    "missing_lines": [2, 3],
                    "missing_branches": [],
                },
                "app/api/route.py": {
                    "executed_lines": [],
                    "missing_lines": [2, 3],
                    "missing_branches": [],
                },
            }
        }

        result = _calculate_function_coverage_gaps(
            coverage_data,
            Path("/repo"),
            "component",
            80.0,
            80.0,
            service_layer_only=True,
        )

        gap_files = [g.file for g in result]
        assert "app/api/route.py" not in gap_files


class TestCollectFunctionCoverageGaps:
    """Tests for _collect_function_coverage_gaps function."""

    def test_collects_gaps_from_tier_files(self, fs: FakeFilesystem) -> None:
        """Should collect gaps from tier-specific coverage files."""
        fs.create_dir("/repo")
        code = """
def func():
    pass
"""
        fs.create_file("/repo/app/test.py", contents=code)

        coverage_data = {
            "files": {
                "app/test.py": {
                    "executed_lines": [],
                    "missing_lines": [2, 3],
                    "missing_branches": [],
                }
            }
        }
        fs.create_file("/repo/coverage_unit.json", contents=json.dumps(coverage_data))

        result = _collect_function_coverage_gaps(
            Path("/repo"),
            {"unit": Path("/repo/coverage_unit.json")},
            80.0,
            80.0,
        )

        assert "tier_summaries" in result
        assert "unit" in result["tier_summaries"]
        assert "functions_below_threshold" in result

    def test_handles_missing_coverage_file(self, fs: FakeFilesystem) -> None:
        """Should handle missing coverage files gracefully."""
        fs.create_dir("/repo")

        result = _collect_function_coverage_gaps(
            Path("/repo"),
            {"unit": Path("/repo/nonexistent.json")},
            80.0,
            80.0,
        )

        assert result["tier_summaries"]["unit"]["error"] is not None


class TestDiscoverTierCoverageFiles:
    """Tests for _discover_tier_coverage_files function."""

    def test_discovers_existing_files(self, fs: FakeFilesystem) -> None:
        """Should discover existing tier coverage files."""
        fs.create_dir("/repo")
        fs.create_file("/repo/coverage_unit.json", contents="{}")
        fs.create_file("/repo/coverage_component.json", contents="{}")

        result = _discover_tier_coverage_files(Path("/repo"))

        assert "unit" in result
        assert "component" in result
        assert result["unit"] == Path("/repo/coverage_unit.json")

    def test_returns_only_existing_files(self, fs: FakeFilesystem) -> None:
        """Should only return files that exist."""
        fs.create_dir("/repo")
        fs.create_file("/repo/coverage_unit.json", contents="{}")

        result = _discover_tier_coverage_files(Path("/repo"))

        assert "unit" in result
        assert "component" not in result
        assert "scripts" not in result

    def test_returns_empty_dict_when_no_files(self, fs: FakeFilesystem) -> None:
        """Should return empty dict when no files exist."""
        fs.create_dir("/repo")

        result = _discover_tier_coverage_files(Path("/repo"))

        assert result == {}


class TestParseArgsNewOptions:
    """Tests for new CLI options in parse_args."""

    def test_default_tier_report_is_none(self) -> None:
        """Should default tier-report to None."""
        args = parse_args([])
        assert args.tier_report is None

    def test_custom_tier_report(self) -> None:
        """Should accept custom tier report path."""
        args = parse_args(["--tier-report", "/custom/report.json"])
        assert args.tier_report == Path("/custom/report.json")

    def test_default_min_line(self) -> None:
        """Should default min-line to 80.0."""
        args = parse_args([])
        assert args.min_line == 80.0

    def test_custom_min_line(self) -> None:
        """Should accept custom min-line threshold."""
        args = parse_args(["--min-line", "90"])
        assert args.min_line == 90.0

    def test_default_min_branch(self) -> None:
        """Should default min-branch to 80.0."""
        args = parse_args([])
        assert args.min_branch == 80.0

    def test_custom_min_branch(self) -> None:
        """Should accept custom min-branch threshold."""
        args = parse_args(["--min-branch", "75"])
        assert args.min_branch == 75.0


class TestBuildLlmCoverageDocumentFunctionCoverage:
    """Tests for function_coverage in build_llm_coverage_document."""

    def test_includes_function_coverage_section(self, fs: FakeFilesystem) -> None:
        """Should include function_coverage section in output."""
        coverage_data = {
            "meta": {"version": "7.0"},
            "files": {},
            "totals": {"percent_covered": 100.0},
        }
        fs.create_dir("/repo")
        fs.create_file("/repo/coverage.json", contents=json.dumps(coverage_data))
        fs.create_file("/repo/use_cases.yaml", contents="features: {}")
        fs.create_dir("/repo/tests")

        result = build_llm_coverage_document(
            repo_root=Path("/repo"),
            coverage_json_path=Path("/repo/coverage.json"),
            usecase_yaml_path=Path("/repo/use_cases.yaml"),
            tests_roots=["tests"],
            context_radius=2,
        )

        assert "function_coverage" in result

    def test_uses_tier_coverage_files(self, fs: FakeFilesystem) -> None:
        """Should use tier-specific coverage files when provided."""
        coverage_data = {
            "meta": {"version": "7.0"},
            "files": {},
            "totals": {},
        }
        fs.create_dir("/repo")
        fs.create_file("/repo/coverage.json", contents=json.dumps(coverage_data))
        fs.create_file("/repo/coverage_unit.json", contents=json.dumps(coverage_data))
        fs.create_file("/repo/use_cases.yaml", contents="features: {}")
        fs.create_dir("/repo/tests")

        result = build_llm_coverage_document(
            repo_root=Path("/repo"),
            coverage_json_path=Path("/repo/coverage.json"),
            usecase_yaml_path=Path("/repo/use_cases.yaml"),
            tests_roots=["tests"],
            context_radius=2,
            tier_coverage_files={"unit": Path("/repo/coverage_unit.json")},
        )

        assert "function_coverage" in result
        assert "tier_summaries" in result["function_coverage"]

    def test_includes_custom_thresholds_in_config(self, fs: FakeFilesystem) -> None:
        """Should include custom thresholds in config section."""
        coverage_data: dict[str, Any] = {"meta": {}, "files": {}, "totals": {}}
        fs.create_dir("/repo")
        fs.create_file("/repo/coverage.json", contents=json.dumps(coverage_data))
        fs.create_file("/repo/use_cases.yaml", contents="features: {}")
        fs.create_dir("/repo/tests")

        result = build_llm_coverage_document(
            repo_root=Path("/repo"),
            coverage_json_path=Path("/repo/coverage.json"),
            usecase_yaml_path=Path("/repo/use_cases.yaml"),
            tests_roots=["tests"],
            context_radius=2,
            min_line=90.0,
            min_branch=85.0,
        )

        assert result["config"]["min_line_coverage"] == 90.0
        assert result["config"]["min_branch_coverage"] == 85.0
