from pathlib import Path

import pytest

from scripts.dev.test_runner.test_files import (
    _HAS_FULL_MATCH,
    FAILED_LINE_PATTERN,
    FAILURE_HEADER_PATTERN,
    REPO_ROOT,
    TierConfig,
    _extract_short_test_name,
    _find_failed_tests_for_file,
    _find_repo_root,
    _glob_pattern_to_regex,
    _test_path_matches_file,
    _validate_tier_config,
    file_matches_tier,
    find_test_files,
    match_pattern,
    normalize_path,
    run_tests,
    run_tests_for_files,
)


class TestNormalizePath:
    def test_posix_path_unchanged(self) -> None:
        """POSIX paths remain unchanged."""
        assert normalize_path("app/core/factory.py") == "app/core/factory.py"

    def test_windows_backslash_converted(self) -> None:
        """Windows backslashes are converted to forward slashes."""
        assert normalize_path("app\\core\\factory.py") == "app/core/factory.py"

    def test_mixed_slashes_normalized(self) -> None:
        """Mixed slashes are normalized to forward slashes."""
        assert normalize_path("app/core\\models\\factory.py") == "app/core/models/factory.py"

    def test_absolute_path_converted_to_relative(self) -> None:
        """Absolute paths within repo root are converted to repo-relative."""
        absolute_path = str(REPO_ROOT / "app" / "core" / "factory.py")
        result = normalize_path(absolute_path)
        assert result == "app/core/factory.py"

    def test_absolute_path_outside_repo_unchanged(self) -> None:
        """Absolute paths outside repo root remain unchanged (after backslash normalization)."""
        # Use a path that definitely won't be inside REPO_ROOT
        outside_path = "/some/other/project/app/core/factory.py"
        result = normalize_path(outside_path)
        # Path should be returned with forward slashes but otherwise unchanged
        assert result == "/some/other/project/app/core/factory.py"

    def test_absolute_path_with_backslashes_converted_to_relative(self) -> None:
        """Absolute paths with backslashes within repo root are converted to repo-relative.

        This tests the scenario where a path uses backslash separators (as on Windows)
        but resolves to the same location as REPO_ROOT. Works on all platforms because
        backslashes are normalized to forward slashes before path resolution.
        """
        # Build a backslash-separated path from REPO_ROOT
        repo_str = str(REPO_ROOT).replace("/", "\\")
        absolute_path = f"{repo_str}\\app\\core\\factory.py"
        result = normalize_path(absolute_path)
        assert result == "app/core/factory.py"


class TestFindRepoRoot:
    def test_finds_repo_root_with_pyproject_toml(self, tmp_path: Path) -> None:
        """Finds repo root when pyproject.toml exists."""
        # Create a fake repo structure
        repo_root = tmp_path / "my_repo"
        repo_root.mkdir()
        (repo_root / "pyproject.toml").touch()
        nested_dir = repo_root / "src" / "lib" / "module"
        nested_dir.mkdir(parents=True)

        result = _find_repo_root(nested_dir)
        assert result == repo_root

    def test_finds_repo_root_with_git_directory(self, tmp_path: Path) -> None:
        """Finds repo root when .git directory exists."""
        repo_root = tmp_path / "my_repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        nested_dir = repo_root / "src" / "lib" / "module"
        nested_dir.mkdir(parents=True)

        result = _find_repo_root(nested_dir)
        assert result == repo_root

    def test_prefers_pyproject_toml_over_git_at_same_level(self, tmp_path: Path) -> None:
        """When both markers exist at the same level, returns that directory."""
        repo_root = tmp_path / "my_repo"
        repo_root.mkdir()
        (repo_root / "pyproject.toml").touch()
        (repo_root / ".git").mkdir()
        nested_dir = repo_root / "src"
        nested_dir.mkdir()

        result = _find_repo_root(nested_dir)
        assert result == repo_root

    def test_finds_nearest_marker_when_nested_repos(self, tmp_path: Path) -> None:
        """Finds the nearest repo root when there are nested repositories."""
        outer_repo = tmp_path / "outer"
        outer_repo.mkdir()
        (outer_repo / "pyproject.toml").touch()

        inner_repo = outer_repo / "subprojects" / "inner"
        inner_repo.mkdir(parents=True)
        (inner_repo / "pyproject.toml").touch()

        deep_dir = inner_repo / "src" / "module"
        deep_dir.mkdir(parents=True)

        result = _find_repo_root(deep_dir)
        assert result == inner_repo

    def test_default_start_path_uses_module_directory(self) -> None:
        """When no start_path is given, uses the module's parent directory."""
        # The actual REPO_ROOT should be valid and contain pyproject.toml
        assert REPO_ROOT.exists()
        assert (REPO_ROOT / "pyproject.toml").exists() or (REPO_ROOT / ".git").exists()

    def test_handles_start_path_at_repo_root(self, tmp_path: Path) -> None:
        """Handles when start_path is already at the repo root."""
        repo_root = tmp_path / "my_repo"
        repo_root.mkdir()
        (repo_root / "pyproject.toml").touch()

        result = _find_repo_root(repo_root)
        assert result == repo_root


class TestMatchPatternWithNormalizedPaths:
    def test_simple_glob_match(self) -> None:
        """Simple glob pattern matches."""
        assert match_pattern("app/core/factory.py", "app/**/*.py")

    def test_negation_pattern_raises_value_error(self) -> None:
        """Negation patterns raise ValueError with helpful message."""
        with pytest.raises(ValueError) as exc_info:
            match_pattern("app/core/factory.py", "!app/migrations/**")

        error_msg = str(exc_info.value)
        assert "Negation patterns are not allowed" in error_msg
        assert "!app/migrations/**" in error_msg

    def test_double_star_matches_deep_path(self) -> None:
        """Double star matches arbitrary depth."""
        assert match_pattern("app/core/models/deep/file.py", "app/**/*.py")

    def test_single_star_does_not_match_slash(self) -> None:
        """Single star does not match directory separator."""
        assert not match_pattern("app/core/factory.py", "app/*.py")

    def test_exact_match(self) -> None:
        """Exact pattern matches exactly."""
        assert match_pattern("app/core/factory.py", "app/core/factory.py")

    def test_no_match_different_path(self) -> None:
        """Non-matching path returns False."""
        assert not match_pattern("scripts/dev/linter.py", "app/**/*.py")


class TestFileMatchesTierWithNormalizedPaths:
    def test_tier_matches_with_posix_path(self) -> None:
        """Tier pattern matching works with POSIX paths."""
        tier = TierConfig(
            name="unit",
            test_path="tests/unit",
            source_patterns=["app/**/*.py"],
        )
        # Should match with POSIX path
        assert file_matches_tier("app/core/factory.py", tier)

    def test_tier_exclusion_works(self) -> None:
        """Exclusion patterns work correctly."""
        tier = TierConfig(
            name="unit",
            test_path="tests/unit",
            source_patterns=["app/**/*.py", "!app/migrations/**"],
        )
        assert file_matches_tier("app/core/factory.py", tier)
        assert not file_matches_tier("app/migrations/0001_initial.py", tier)

    def test_scripts_tier_matches(self) -> None:
        """Scripts tier pattern matching works."""
        tier = TierConfig(
            name="scripts",
            test_path="scripts/tests",
            source_patterns=["scripts/**/*.py", "!scripts/tests/**"],
        )
        assert file_matches_tier("scripts/dev/linter/lint_cli.py", tier)
        assert not file_matches_tier("scripts/tests/dev/test_linter.py", tier)


class TestPytestOutputParsing:
    def test_failed_line_pattern_simple(self) -> None:
        """FAILED line regex matches simple case."""
        line = "FAILED tests/unit/app/test_foo.py::test_bar"
        match = FAILED_LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(1) == "tests/unit/app/test_foo.py::test_bar"

    def test_failed_line_pattern_with_reason(self) -> None:
        """FAILED line regex matches with reason."""
        line = "FAILED tests/unit/app/test_foo.py::test_bar - AssertionError"
        match = FAILED_LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(1) == "tests/unit/app/test_foo.py::test_bar"

    def test_failed_line_pattern_no_match(self) -> None:
        """FAILED line regex does not match non-failure lines."""
        line = "PASSED tests/unit/app/test_foo.py::test_bar"
        match = FAILED_LINE_PATTERN.match(line)
        assert match is None

    def test_failure_header_pattern(self) -> None:
        """Failure header regex matches underscore-wrapped test names."""
        line = "_____ test_foo _____"
        match = FAILURE_HEADER_PATTERN.match(line)
        assert match is not None
        assert match.group(1) == "test_foo"

    def test_failure_header_pattern_long_underscores(self) -> None:
        """Failure header regex matches with many underscores."""
        line = "_________________________ test_something_complex _________________________"
        match = FAILURE_HEADER_PATTERN.match(line)
        assert match is not None
        assert match.group(1) == "test_something_complex"

    def test_failure_header_pattern_no_match(self) -> None:
        """Failure header regex does not match regular lines."""
        line = "Some regular output line"
        match = FAILURE_HEADER_PATTERN.match(line)
        assert match is None


class TestFailureHeaderRegexClassAndParametrized:
    def test_failure_header_pattern_class_method(self) -> None:
        """Failure header regex matches class-based test methods."""
        line = "_________________________ TestClass::test_method _________________________"
        match = FAILURE_HEADER_PATTERN.match(line)
        assert match is not None
        assert match.group(1) == "TestClass::test_method"

    def test_failure_header_pattern_nested_class_method(self) -> None:
        """Failure header regex matches nested class test methods."""
        line = "_____ TestOuter::TestInner::test_nested _____"
        match = FAILURE_HEADER_PATTERN.match(line)
        assert match is not None
        assert match.group(1) == "TestOuter::TestInner::test_nested"

    def test_failure_header_pattern_parametrized_simple(self) -> None:
        """Failure header regex matches parametrized test with simple param."""
        line = "_________________________ test_foo[param1] _________________________"
        match = FAILURE_HEADER_PATTERN.match(line)
        assert match is not None
        assert match.group(1) == "test_foo[param1]"

    def test_failure_header_pattern_parametrized_multiple_params(self) -> None:
        """Failure header regex matches parametrized test with multiple params."""
        line = "_____ test_validate[input1-expected1-True] _____"
        match = FAILURE_HEADER_PATTERN.match(line)
        assert match is not None
        assert match.group(1) == "test_validate[input1-expected1-True]"

    def test_failure_header_pattern_class_parametrized(self) -> None:
        """Failure header regex matches class method with parametrized test."""
        line = (
            "_________________________ TestValidator::test_check[case1] _________________________"
        )
        match = FAILURE_HEADER_PATTERN.match(line)
        assert match is not None
        assert match.group(1) == "TestValidator::test_check[case1]"


class TestFailedTestPathMatching:
    def test_exact_path_match(self) -> None:
        """Test exact path matching using path components."""
        file_tests = ["tests/unit/app/core/test_factory.py"]
        file_tests_parts = [Path(ft).parts for ft in file_tests]
        failed_test = "tests/unit/app/core/test_factory.py::test_something"

        assert _test_path_matches_file(failed_test, file_tests_parts)

    def test_no_false_positive_substring_match(self) -> None:
        """Verify substring matching false positives are avoided."""
        # Old substring matching would incorrectly match these
        file_tests = ["tests/unit/test_foo.py"]
        file_tests_parts = [Path(ft).parts for ft in file_tests]
        failed_test = "tests/unit/other/test_foobar.py::test_something"

        # Should NOT match because test_foobar.py != test_foo.py
        assert not _test_path_matches_file(failed_test, file_tests_parts)

    def test_path_suffix_matching(self) -> None:
        """Test that path suffix matching works correctly."""
        # Test that we match when path ends with our test file parts
        file_tests = ["app/core/test_factory.py"]
        file_tests_parts = [Path(ft).parts for ft in file_tests]
        failed_test = "/absolute/path/app/core/test_factory.py::test_x"

        assert _test_path_matches_file(failed_test, file_tests_parts)


class TestTestPathMatchesFile:
    def test_exact_path_match(self) -> None:
        """Test exact path matching."""
        from pathlib import Path

        file_tests_parts = [Path("tests/unit/app/test_foo.py").parts]
        assert _test_path_matches_file("tests/unit/app/test_foo.py::test_bar", file_tests_parts)

    def test_suffix_path_match(self) -> None:
        """Test path suffix matching."""
        from pathlib import Path

        file_tests_parts = [Path("app/test_foo.py").parts]
        assert _test_path_matches_file("/abs/path/app/test_foo.py::test_bar", file_tests_parts)

    def test_no_match_different_file(self) -> None:
        """Test that different files do not match."""
        from pathlib import Path

        file_tests_parts = [Path("tests/unit/test_foo.py").parts]
        assert not _test_path_matches_file(
            "tests/unit/test_bar.py::test_something", file_tests_parts
        )

    def test_no_false_positive_substring(self) -> None:
        """Test that substring matches are rejected."""
        from pathlib import Path

        file_tests_parts = [Path("tests/test_foo.py").parts]
        # test_foobar.py should NOT match test_foo.py
        assert not _test_path_matches_file("tests/test_foobar.py::test_something", file_tests_parts)

    def test_empty_file_tests_parts(self) -> None:
        """Test with empty file_tests_parts."""
        assert not _test_path_matches_file("tests/test_foo.py::test_bar", [])


class TestFindFailedTestsForFile:
    def test_finds_matching_failed_tests(self) -> None:
        """Test that matching failed tests are found."""
        failed_tests = [
            "tests/unit/app/test_foo.py::test_one",
            "tests/unit/app/test_bar.py::test_two",
            "tests/unit/app/test_foo.py::test_three",
        ]
        file_tests = ["tests/unit/app/test_foo.py"]

        result = _find_failed_tests_for_file(failed_tests, file_tests)

        assert len(result) == 2
        assert "tests/unit/app/test_foo.py::test_one" in result
        assert "tests/unit/app/test_foo.py::test_three" in result

    def test_returns_empty_list_when_no_matches(self) -> None:
        """Test that empty list is returned when no matches."""
        failed_tests = ["tests/unit/app/test_bar.py::test_one"]
        file_tests = ["tests/unit/app/test_foo.py"]

        result = _find_failed_tests_for_file(failed_tests, file_tests)

        assert result == []

    def test_returns_empty_list_when_no_file_tests(self) -> None:
        """Test that empty list is returned when file_tests is empty."""
        failed_tests = ["tests/unit/app/test_foo.py::test_one"]

        result = _find_failed_tests_for_file(failed_tests, [])

        assert result == []

    def test_returns_empty_list_when_no_failed_tests(self) -> None:
        """Test that empty list is returned when failed_tests is empty."""
        file_tests = ["tests/unit/app/test_foo.py"]

        result = _find_failed_tests_for_file([], file_tests)

        assert result == []


class TestRunTestsExceptionHandling:
    def test_returns_empty_list_when_no_test_files(self) -> None:
        """Test that empty test files returns success tuple."""
        passed, exit_code, output, failed_tests = run_tests([])

        assert passed is True
        assert exit_code == 0
        assert output == "No test files to run"
        assert failed_tests == []


class TestExtractShortTestName:
    def test_simple_test_identifier(self) -> None:
        """Extract short name from simple path::test_name format."""
        assert _extract_short_test_name("tests/unit/test_foo.py::test_bar") == "test_bar"

    def test_class_method_identifier(self) -> None:
        """Extract short name from path::TestClass::test_method format.

        Pytest failure headers show 'TestClass::test_method' for class methods,
        so we need to preserve the full class::method format.
        """
        result = _extract_short_test_name("tests/unit/test_foo.py::TestClass::test_method")
        assert result == "TestClass::test_method"

    def test_nested_class_method(self) -> None:
        """Extract short name from nested class format.

        Preserves the full hierarchy after the file path.
        """
        result = _extract_short_test_name(
            "tests/unit/test_foo.py::TestOuter::TestInner::test_nested"
        )
        assert result == "TestOuter::TestInner::test_nested"

    def test_parametrized_test(self) -> None:
        """Extract short name from parametrized test."""
        result = _extract_short_test_name("tests/unit/test_foo.py::test_validate[input1]")
        assert result == "test_validate[input1]"

    def test_parametrized_with_multiple_params(self) -> None:
        """Extract short name from parametrized test with multiple params."""
        result = _extract_short_test_name(
            "tests/unit/test_foo.py::test_validate[input1-expected1-True]"
        )
        assert result == "test_validate[input1-expected1-True]"

    def test_class_parametrized_method(self) -> None:
        """Extract short name from class method with parameters.

        Preserves the class::method[params] format that pytest shows in headers.
        """
        result = _extract_short_test_name(
            "tests/unit/test_foo.py::TestValidator::test_check[case1]"
        )
        assert result == "TestValidator::test_check[case1]"

    def test_already_short_name(self) -> None:
        """Return input unchanged if already a short name (no ::)."""
        assert _extract_short_test_name("test_foo") == "test_foo"

    def test_parametrized_short_name(self) -> None:
        """Return parametrized short name unchanged."""
        assert _extract_short_test_name("test_foo[param]") == "test_foo[param]"


class TestRunTestsForFilesEmptyTiers:
    def test_raises_error_when_no_tiers_configured(self) -> None:
        """Test that empty tier configuration raises a clear error."""
        with pytest.raises(ValueError) as exc_info:
            run_tests_for_files(["app/core/factory.py"], tiers=[])

        assert "No tier configurations found" in str(exc_info.value)
        assert "pyproject.toml" in str(exc_info.value)


class TestGlobPatternToRegex:
    def test_simple_glob_match(self) -> None:
        """Simple glob pattern matches."""
        regex = _glob_pattern_to_regex("app/**/*.py")
        assert regex.match("app/core/factory.py") is not None

    def test_double_star_matches_deep_path(self) -> None:
        """Double star matches arbitrary depth."""
        regex = _glob_pattern_to_regex("app/**/*.py")
        assert regex.match("app/core/models/deep/file.py") is not None

    def test_single_star_does_not_match_slash(self) -> None:
        """Single star does not match directory separator."""
        regex = _glob_pattern_to_regex("app/*.py")
        assert regex.match("app/core/factory.py") is None

    def test_single_star_matches_filename(self) -> None:
        """Single star matches within a single path component."""
        regex = _glob_pattern_to_regex("app/*.py")
        assert regex.match("app/factory.py") is not None

    def test_exact_match(self) -> None:
        """Exact pattern matches exactly."""
        regex = _glob_pattern_to_regex("app/core/factory.py")
        assert regex.match("app/core/factory.py") is not None

    def test_no_match_different_path(self) -> None:
        """Non-matching path returns None."""
        regex = _glob_pattern_to_regex("app/**/*.py")
        assert regex.match("scripts/dev/linter.py") is None

    def test_double_star_at_start(self) -> None:
        """Double star at start of pattern matches any leading path."""
        regex = _glob_pattern_to_regex("**/*.py")
        assert regex.match("app/core/factory.py") is not None
        assert regex.match("scripts/dev/linter.py") is not None

    def test_double_star_in_middle(self) -> None:
        """Double star in middle matches any intermediate directories."""
        regex = _glob_pattern_to_regex("app/**/test_*.py")
        assert regex.match("app/core/test_factory.py") is not None
        assert regex.match("app/core/models/test_base.py") is not None

    def test_question_mark_matches_single_char(self) -> None:
        """Question mark matches single non-slash character."""
        regex = _glob_pattern_to_regex("app/?.py")
        assert regex.match("app/a.py") is not None
        assert regex.match("app/ab.py") is None

    def test_escapes_regex_special_chars(self) -> None:
        """Regex special characters are escaped properly."""
        regex = _glob_pattern_to_regex("app/file.name.py")
        assert regex.match("app/file.name.py") is not None
        # Without proper escaping, . would match any character
        assert regex.match("app/fileXname.py") is None

    def test_character_class_preserves_inner_content(self) -> None:
        """Character class inner content is preserved without re-escaping."""
        # [a.b] should match 'a', '.', or 'b' - not 'a', '\\.', or 'b'
        regex = _glob_pattern_to_regex("file[a.b].py")
        assert regex.match("filea.py") is not None
        assert regex.match("file..py") is not None
        assert regex.match("fileb.py") is not None
        # Should NOT match other characters
        assert regex.match("filec.py") is None

    def test_character_class_negation_converted(self) -> None:
        """Character class negation (!) is converted to regex negation (^)."""
        regex = _glob_pattern_to_regex("file[!abc].py")
        # Should NOT match a, b, or c
        assert regex.match("filea.py") is None
        assert regex.match("fileb.py") is None
        assert regex.match("filec.py") is None
        # Should match other characters
        assert regex.match("filed.py") is not None
        assert regex.match("filex.py") is not None

    def test_character_class_with_range(self) -> None:
        """Character class with range is preserved."""
        regex = _glob_pattern_to_regex("file[a-z].py")
        assert regex.match("filea.py") is not None
        assert regex.match("filez.py") is not None
        # Uppercase should not match
        assert regex.match("fileA.py") is None

    def test_character_class_with_literal_closing_bracket_at_start(self) -> None:
        """Character class with literal ] at start is handled."""
        # []abc] means ], a, b, or c
        regex = _glob_pattern_to_regex("file[]abc].py")
        assert regex.match("file].py") is not None
        assert regex.match("filea.py") is not None
        assert regex.match("fileb.py") is not None
        assert regex.match("filec.py") is not None

    def test_character_class_with_negation_and_closing_bracket(self) -> None:
        """Character class with negation and literal ] at start is handled."""
        # [!]abc] means NOT ], a, b, or c
        regex = _glob_pattern_to_regex("file[!]abc].py")
        assert regex.match("file].py") is None
        assert regex.match("filea.py") is None
        assert regex.match("filed.py") is not None

    def test_character_class_special_chars_inside_are_literal(self) -> None:
        """Special regex chars inside character class are treated as literals."""
        # [.*+] should match '.', '*', or '+' literally
        regex = _glob_pattern_to_regex("file[.*+].py")
        assert regex.match("file..py") is not None
        assert regex.match("file*.py") is not None
        assert regex.match("file+.py") is not None
        # Should NOT match other characters
        assert regex.match("filea.py") is None

    def test_character_class_with_escaped_hyphen(self) -> None:
        """Backslash-escaped hyphen inside character class is treated as literal."""
        # [a\-z] should match 'a', '-', or 'z' (not a range)
        regex = _glob_pattern_to_regex(r"file[a\-z].py")
        assert regex.match("filea.py") is not None
        assert regex.match("file-.py") is not None
        assert regex.match("filez.py") is not None
        # Should NOT match characters in between (since it's not a range)
        assert regex.match("fileb.py") is None
        assert regex.match("filem.py") is None

    def test_character_class_with_escaped_backslash(self) -> None:
        """Backslash-escaped backslash inside character class is treated as literal."""
        # [a\\b] should match 'a', '\', or 'b'
        regex = _glob_pattern_to_regex(r"file[a\\b].py")
        assert regex.match("filea.py") is not None
        assert regex.match("file\\.py") is not None
        assert regex.match("fileb.py") is not None
        assert regex.match("filec.py") is None

    def test_character_class_with_escaped_caret(self) -> None:
        """Backslash-escaped caret inside character class is treated as literal."""
        # [a\^b] should match 'a', '^', or 'b'
        regex = _glob_pattern_to_regex(r"file[a\^b].py")
        assert regex.match("filea.py") is not None
        assert regex.match("file^.py") is not None
        assert regex.match("fileb.py") is not None
        assert regex.match("filec.py") is None

    def test_character_class_with_escaped_closing_bracket(self) -> None:
        """Backslash-escaped closing bracket inside character class is treated as literal."""
        # [a\]b] should match 'a', ']', or 'b'
        regex = _glob_pattern_to_regex(r"file[a\]b].py")
        assert regex.match("filea.py") is not None
        assert regex.match("file].py") is not None
        assert regex.match("fileb.py") is not None
        assert regex.match("filec.py") is None

    def test_unterminated_character_class_treated_as_literal(self) -> None:
        """Unterminated character class (no closing ]) treats [ as literal."""
        # [abc without closing ] should treat [ as literal
        regex = _glob_pattern_to_regex("file[abc")
        assert regex.match("file[abc") is not None
        # Should NOT match what it would if it were a valid character class
        assert regex.match("filea") is None

    def test_unterminated_character_class_with_negation(self) -> None:
        """Unterminated negated character class treats [ as literal."""
        regex = _glob_pattern_to_regex("file[!abc")
        assert regex.match("file[!abc") is not None

    def test_unterminated_character_class_at_end_of_pattern(self) -> None:
        """Unterminated character class at end of pattern."""
        regex = _glob_pattern_to_regex("file[")
        assert regex.match("file[") is not None

    def test_multiple_escaped_characters_in_class(self) -> None:
        """Multiple escaped characters in same character class."""
        # [a\-b\^c] should match 'a', '-', 'b', '^', or 'c'
        regex = _glob_pattern_to_regex(r"file[a\-b\^c].py")
        assert regex.match("filea.py") is not None
        assert regex.match("file-.py") is not None
        assert regex.match("fileb.py") is not None
        assert regex.match("file^.py") is not None
        assert regex.match("filec.py") is not None
        assert regex.match("filed.py") is None


class TestValidateTierConfig:
    def test_valid_config_passes(self) -> None:
        """Valid tier configuration passes validation without error."""
        tier_data = {
            "test_path": "tests/unit",
            "source_paths": ["app/**/*.py"],
        }
        # Should not raise
        _validate_tier_config("unit", tier_data)

    def test_missing_test_path_raises_error(self) -> None:
        """Missing test_path field raises ValueError with tier name."""
        tier_data = {
            "source_paths": ["app/**/*.py"],
        }
        with pytest.raises(ValueError) as exc_info:
            _validate_tier_config("unit", tier_data)
        assert "Tier 'unit'" in str(exc_info.value)
        assert "missing required field 'test_path'" in str(exc_info.value)

    def test_missing_source_paths_raises_error(self) -> None:
        """Missing source_paths field raises ValueError with tier name."""
        tier_data = {
            "test_path": "tests/unit",
        }
        with pytest.raises(ValueError) as exc_info:
            _validate_tier_config("scripts", tier_data)
        assert "Tier 'scripts'" in str(exc_info.value)
        assert "missing required field 'source_paths'" in str(exc_info.value)

    def test_test_path_wrong_type_raises_error(self) -> None:
        """Non-string test_path raises TypeError with type name."""
        tier_data = {
            "test_path": 123,
            "source_paths": ["app/**/*.py"],
        }
        with pytest.raises(TypeError) as exc_info:
            _validate_tier_config("unit", tier_data)
        assert "Tier 'unit'" in str(exc_info.value)
        assert "'test_path' must be a string" in str(exc_info.value)
        assert "got int" in str(exc_info.value)

    def test_test_path_empty_string_raises_error(self) -> None:
        """Empty test_path string raises ValueError."""
        tier_data = {
            "test_path": "",
            "source_paths": ["app/**/*.py"],
        }
        with pytest.raises(ValueError) as exc_info:
            _validate_tier_config("unit", tier_data)
        assert "Tier 'unit'" in str(exc_info.value)
        assert "'test_path' must be a non-empty string" in str(exc_info.value)

    def test_test_path_whitespace_only_raises_error(self) -> None:
        """Whitespace-only test_path raises ValueError."""
        tier_data = {
            "test_path": "   ",
            "source_paths": ["app/**/*.py"],
        }
        with pytest.raises(ValueError) as exc_info:
            _validate_tier_config("unit", tier_data)
        assert "'test_path' must be a non-empty string" in str(exc_info.value)

    def test_source_paths_wrong_type_raises_error(self) -> None:
        """Non-list source_paths raises TypeError with type name."""
        tier_data = {
            "test_path": "tests/unit",
            "source_paths": "app/**/*.py",
        }
        with pytest.raises(TypeError) as exc_info:
            _validate_tier_config("unit", tier_data)
        assert "Tier 'unit'" in str(exc_info.value)
        assert "'source_paths' must be a list" in str(exc_info.value)
        assert "got str" in str(exc_info.value)

    def test_source_paths_empty_list_raises_error(self) -> None:
        """Empty source_paths list raises ValueError."""
        tier_data = {
            "test_path": "tests/unit",
            "source_paths": [],
        }
        with pytest.raises(ValueError) as exc_info:
            _validate_tier_config("unit", tier_data)
        assert "Tier 'unit'" in str(exc_info.value)
        assert "'source_paths' must be a non-empty list" in str(exc_info.value)

    def test_source_paths_item_wrong_type_raises_error(self) -> None:
        """Non-string item in source_paths raises TypeError with index."""
        tier_data = {
            "test_path": "tests/unit",
            "source_paths": ["app/**/*.py", 123, "scripts/**/*.py"],
        }
        with pytest.raises(TypeError) as exc_info:
            _validate_tier_config("unit", tier_data)
        assert "Tier 'unit'" in str(exc_info.value)
        assert "'source_paths[1]' must be a string" in str(exc_info.value)
        assert "got int" in str(exc_info.value)

    def test_multiple_patterns_valid(self) -> None:
        """Multiple valid patterns pass validation."""
        tier_data = {
            "test_path": "tests/unit",
            "source_paths": ["app/**/*.py", "!app/migrations/**", "lib/**/*.py"],
        }
        # Should not raise
        _validate_tier_config("unit", tier_data)

    def test_error_includes_tier_name_for_all_errors(self) -> None:
        """All validation errors include the tier name."""
        # Test cases with expected exception type
        test_cases: list[tuple[dict[str, object], type[Exception]]] = [
            ({"source_paths": ["app/**/*.py"]}, ValueError),  # missing test_path
            ({"test_path": "tests/unit"}, ValueError),  # missing source_paths
            ({"test_path": None, "source_paths": ["app/**/*.py"]}, TypeError),  # wrong type
            ({"test_path": "tests/unit", "source_paths": {}}, TypeError),  # wrong type
        ]
        for tier_data, exc_type in test_cases:
            with pytest.raises(exc_type) as exc_info:
                _validate_tier_config("my-tier", tier_data)
            assert "Tier 'my-tier'" in str(exc_info.value)
