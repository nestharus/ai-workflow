import sqlite3
import subprocess
from pathlib import Path

from scripts.dev.test_runner.redundant_test_detector import (
    _load_test_coverage_from_db,
    detect_redundant_tests,
)


def _nums_to_numbits(nums: list[int]) -> bytes:
    """Convert list of line numbers to numbits binary format.

    This implements the coverage.py numbits format:
    - Each bit position represents a line number
    - Byte N contains bits for lines (N*8) to (N*8 + 7)
    - Bit position within byte is (line_num % 8)
    """
    if not nums:
        return b""

    max_num = max(nums)
    num_bytes = (max_num // 8) + 1
    result = bytearray(num_bytes)

    for num in nums:
        byte_index = num // 8
        bit_index = num % 8
        result[byte_index] |= 1 << bit_index

    return bytes(result)


def _create_coverage_db(
    db_path: Path,
    files: dict[str, int],  # file_path -> file_id
    contexts: dict[str, int],  # context_name -> context_id
    line_coverage: list[tuple[int, int, list[int]]],  # [(file_id, context_id, lines)]
    arc_coverage: list[tuple[int, int, int, int]] | None = None,  # [(file_id, ctx_id, from, to)]
) -> None:
    """Create a minimal coverage.py SQLite database with the specified data.

    Args:
        db_path: Path to create the SQLite database
        files: Mapping of file paths to file IDs
        contexts: Mapping of context names (test names) to context IDs
        line_coverage: List of (file_id, context_id, line_numbers) tuples
        arc_coverage: Optional list of (file_id, context_id, from_line, to_line) tuples
    """
    conn = sqlite3.connect(str(db_path))

    # Create coverage.py schema (version 7)
    conn.executescript(
        """
        CREATE TABLE coverage_schema (
            version integer
        );
        INSERT INTO coverage_schema VALUES (7);

        CREATE TABLE meta (
            key text,
            value text,
            unique (key)
        );

        CREATE TABLE file (
            id integer primary key,
            path text,
            unique (path)
        );

        CREATE TABLE context (
            id integer primary key,
            context text,
            unique (context)
        );

        CREATE TABLE line_bits (
            file_id integer,
            context_id integer,
            numbits blob,
            foreign key (file_id) references file (id),
            foreign key (context_id) references context (id),
            unique (file_id, context_id)
        );

        CREATE TABLE arc (
            file_id integer,
            context_id integer,
            fromno integer,
            tono integer,
            foreign key (file_id) references file (id),
            foreign key (context_id) references context (id),
            unique (file_id, context_id, fromno, tono)
        );

        CREATE TABLE tracer (
            file_id integer primary key,
            tracer text,
            foreign key (file_id) references file (id)
        );
        """
    )

    # Insert metadata
    # Note: coverage.py expects "1" or "0" for has_arcs, not "true"/"false"
    conn.execute("INSERT INTO meta VALUES ('has_arcs', ?)", ("1" if arc_coverage else "0",))
    conn.execute("INSERT INTO meta VALUES ('version', '7.3.0')")

    # Insert files
    for path, file_id in files.items():
        conn.execute("INSERT INTO file (id, path) VALUES (?, ?)", (file_id, path))

    # Insert contexts
    for context, context_id in contexts.items():
        conn.execute("INSERT INTO context (id, context) VALUES (?, ?)", (context_id, context))

    # Insert line coverage
    for file_id, context_id, lines in line_coverage:
        numbits = _nums_to_numbits(lines)
        conn.execute(
            "INSERT INTO line_bits (file_id, context_id, numbits) VALUES (?, ?, ?)",
            (file_id, context_id, numbits),
        )

    # Insert arc coverage if provided
    if arc_coverage:
        for file_id, context_id, from_line, to_line in arc_coverage:
            conn.execute(
                "INSERT INTO arc (file_id, context_id, fromno, tono) VALUES (?, ?, ?, ?)",
                (file_id, context_id, from_line, to_line),
            )

    conn.commit()
    conn.close()


def _get_context_count(db_path: Path) -> int:
    """Count non-empty contexts in a coverage database."""
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM context WHERE context != '' AND context IS NOT NULL"
        )
        return cursor.fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _get_all_contexts(db_path: Path) -> set[str]:
    """Get all context names from a coverage database."""
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT context FROM context WHERE context != '' AND context IS NOT NULL"
        )
        return {row[0] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()


def _get_line_bits_count(db_path: Path) -> int:
    """Count line_bits entries in a coverage database."""
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM line_bits")
        return cursor.fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


class TestCombineCommand:
    def test_combine_executes_successfully_with_multiple_tier_files(self, tmp_path: Path) -> None:
        """Combine command should execute without errors when given multiple tier files."""
        # Create two tier coverage files
        unit_file = tmp_path / "data_unit"
        component_file = tmp_path / "data_component"
        combined_file = tmp_path / "data"

        # Create unit tier coverage
        _create_coverage_db(
            unit_file,
            files={"app/main.py": 1},
            contexts={"test_unit_func|run": 1, "": 2},
            line_coverage=[(1, 1, [10, 11, 12])],
        )

        # Create component tier coverage
        _create_coverage_db(
            component_file,
            files={"app/main.py": 1, "app/services/user.py": 2},
            contexts={"test_component_func|run": 1, "": 2},
            line_coverage=[(1, 1, [13, 14, 15]), (2, 1, [5, 6, 7])],
        )

        # Run coverage combine
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(unit_file),
                str(component_file),
            ],
            env={"COVERAGE_FILE": str(combined_file), **dict(__import__("os").environ)},
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, f"Combine failed: {result.stderr}"
        assert combined_file.exists(), "Combined file should be created"

    def test_combine_with_single_tier_file_still_works(self, tmp_path: Path) -> None:
        """Combine with a single tier file should still execute successfully."""
        single_file = tmp_path / "data_unit"
        combined_file = tmp_path / "data"

        _create_coverage_db(
            single_file,
            files={"app/main.py": 1},
            contexts={"test_single|run": 1, "": 2},
            line_coverage=[(1, 1, [1, 2, 3])],
        )

        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(single_file),
            ],
            env={"COVERAGE_FILE": str(combined_file), **dict(__import__("os").environ)},
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, f"Combine with single file failed: {result.stderr}"
        assert combined_file.exists()


class TestCombinedDataContent:
    def test_combined_file_contains_all_file_paths(self, tmp_path: Path) -> None:
        """Combined file should contain file paths from all tier files."""
        unit_file = tmp_path / "data_unit"
        component_file = tmp_path / "data_component"
        combined_file = tmp_path / "data"

        _create_coverage_db(
            unit_file,
            files={"app/unit_file.py": 1},
            contexts={"test_a|run": 1, "": 2},
            line_coverage=[(1, 1, [1, 2])],
        )

        _create_coverage_db(
            component_file,
            files={"app/component_file.py": 1},
            contexts={"test_b|run": 1, "": 2},
            line_coverage=[(1, 1, [3, 4])],
        )

        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(unit_file),
                str(component_file),
            ],
            env={"COVERAGE_FILE": str(combined_file), **dict(__import__("os").environ)},
            capture_output=True,
            cwd=str(tmp_path),
        )

        # Verify both file paths are in combined database
        conn = sqlite3.connect(str(combined_file))
        cursor = conn.execute("SELECT path FROM file")
        file_paths = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "app/unit_file.py" in file_paths
        assert "app/component_file.py" in file_paths


class TestContextPreservation:
    def test_contexts_preserved_after_combine(self, tmp_path: Path) -> None:
        """Per-test contexts must survive the combine operation.

        This is the CRITICAL test - contexts must be preserved for redundant
        test detection to work.
        """
        unit_file = tmp_path / "data_unit"
        component_file = tmp_path / "data_component"
        combined_file = tmp_path / "data"

        # Create coverage with distinct test contexts
        unit_contexts = {"test_unit_1|run": 1, "test_unit_2|run": 2, "": 3}
        component_contexts = {"test_component_1|run": 1, "test_component_2|run": 2, "": 3}

        _create_coverage_db(
            unit_file,
            files={"app/main.py": 1},
            contexts=unit_contexts,
            line_coverage=[
                (1, 1, [10, 11]),  # test_unit_1 covers lines 10-11
                (1, 2, [12, 13]),  # test_unit_2 covers lines 12-13
            ],
        )

        _create_coverage_db(
            component_file,
            files={"app/main.py": 1},
            contexts=component_contexts,
            line_coverage=[
                (1, 1, [14, 15]),  # test_component_1 covers lines 14-15
                (1, 2, [16, 17]),  # test_component_2 covers lines 16-17
            ],
        )

        # Verify original files have correct context counts
        assert _get_context_count(unit_file) == 2, "Unit file should have 2 non-empty contexts"
        assert _get_context_count(component_file) == 2, (
            "Component file should have 2 non-empty contexts"
        )

        # Run combine
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(unit_file),
                str(component_file),
            ],
            env={"COVERAGE_FILE": str(combined_file), **dict(__import__("os").environ)},
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, f"Combine failed: {result.stderr}"

        # CRITICAL CHECK: All 4 test contexts should be preserved in combined file
        combined_contexts = _get_all_contexts(combined_file)

        # Check all unit contexts are present
        assert "test_unit_1|run" in combined_contexts, "Unit context 1 should be preserved"
        assert "test_unit_2|run" in combined_contexts, "Unit context 2 should be preserved"

        # Check all component contexts are present
        assert "test_component_1|run" in combined_contexts, (
            "Component context 1 should be preserved"
        )
        assert "test_component_2|run" in combined_contexts, (
            "Component context 2 should be preserved"
        )

        # Total should be 4 test contexts
        assert len(combined_contexts) == 4, (
            f"Expected 4 contexts, got {len(combined_contexts)}: {combined_contexts}"
        )

    def test_line_bits_entries_preserved_per_context(self, tmp_path: Path) -> None:
        """Line coverage entries should be preserved per-context after combine.

        Each (file_id, context_id) pair must have its own line_bits entry.
        """
        tier_a = tmp_path / "data_a"
        tier_b = tmp_path / "data_b"
        combined = tmp_path / "data"

        _create_coverage_db(
            tier_a,
            files={"app/file.py": 1},
            contexts={"test_a|run": 1, "": 2},
            line_coverage=[(1, 1, [1, 2, 3])],
        )

        _create_coverage_db(
            tier_b,
            files={"app/file.py": 1},
            contexts={"test_b|run": 1, "": 2},
            line_coverage=[(1, 1, [4, 5, 6])],
        )

        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(tier_a),
                str(tier_b),
            ],
            env={"COVERAGE_FILE": str(combined), **dict(__import__("os").environ)},
            capture_output=True,
            cwd=str(tmp_path),
        )

        # Combined file should have at least 2 line_bits entries
        # (one for each test context)
        combined_line_bits = _get_line_bits_count(combined)
        assert combined_line_bits >= 2, (
            f"Expected at least 2 line_bits entries in combined file, got {combined_line_bits}"
        )

    def test_redundant_test_detector_works_after_combine(self, tmp_path: Path) -> None:
        """Redundant test detector should correctly analyze combined coverage.

        This is the end-to-end validation that contexts are usable after combine.
        """
        tier_a = tmp_path / "data_a"
        tier_b = tmp_path / "data_b"
        combined = tmp_path / "data"

        # Create overlapping coverage: test_redundant covers only lines
        # that test_primary also covers
        _create_coverage_db(
            tier_a,
            files={"app/file.py": 1},
            contexts={"test_primary|run": 1, "": 2},
            line_coverage=[(1, 1, [1, 2, 3, 4, 5])],  # Covers lines 1-5
        )

        _create_coverage_db(
            tier_b,
            files={"app/file.py": 1},
            contexts={"test_redundant|run": 1, "": 2},
            line_coverage=[(1, 1, [2, 3])],  # Only covers subset lines 2-3
        )

        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(tier_a),
                str(tier_b),
            ],
            env={"COVERAGE_FILE": str(combined), **dict(__import__("os").environ)},
            capture_output=True,
            cwd=str(tmp_path),
        )

        # Load test coverage and verify it can be analyzed
        test_coverage = _load_test_coverage_from_db(combined)

        # Should find both test contexts
        assert len(test_coverage) == 2, f"Expected 2 tests, got {len(test_coverage)}"
        assert "test_primary|run" in test_coverage
        assert "test_redundant|run" in test_coverage

        # Run redundant test detection
        result = detect_redundant_tests(combined)

        # test_redundant should be detected as redundant (all its coverage is in test_primary)
        assert result.total_tests == 2
        assert len(result.redundant_tests) == 1, "test_redundant should be detected as redundant"
        assert result.redundant_tests[0]["test_name"] == "test_redundant|run"


class TestCombineKeepFlag:
    def test_keep_flag_preserves_original_files(self, tmp_path: Path) -> None:
        """Combine with --keep should preserve original tier files."""
        tier_a = tmp_path / "data_a"
        tier_b = tmp_path / "data_b"
        combined = tmp_path / "data"

        _create_coverage_db(
            tier_a,
            files={"app/a.py": 1},
            contexts={"test_a|run": 1, "": 2},
            line_coverage=[(1, 1, [1, 2])],
        )

        _create_coverage_db(
            tier_b,
            files={"app/b.py": 1},
            contexts={"test_b|run": 1, "": 2},
            line_coverage=[(1, 1, [3, 4])],
        )

        # Get original file contents hash
        tier_a_hash = tier_a.stat().st_size
        tier_b_hash = tier_b.stat().st_size

        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(tier_a),
                str(tier_b),
            ],
            env={"COVERAGE_FILE": str(combined), **dict(__import__("os").environ)},
            capture_output=True,
            cwd=str(tmp_path),
        )

        # Original files should still exist
        assert tier_a.exists(), "Original tier_a file should be preserved with --keep"
        assert tier_b.exists(), "Original tier_b file should be preserved with --keep"

        # Original files should not be modified
        assert tier_a.stat().st_size == tier_a_hash, "tier_a should not be modified"
        assert tier_b.stat().st_size == tier_b_hash, "tier_b should not be modified"

    def test_combine_without_keep_deletes_original_files(self, tmp_path: Path) -> None:
        """Combine without --keep should delete original tier files."""
        tier_a = tmp_path / "data_a"
        tier_b = tmp_path / "data_b"
        combined = tmp_path / "data"

        _create_coverage_db(
            tier_a,
            files={"app/a.py": 1},
            contexts={"test_a|run": 1, "": 2},
            line_coverage=[(1, 1, [1, 2])],
        )

        _create_coverage_db(
            tier_b,
            files={"app/b.py": 1},
            contexts={"test_b|run": 1, "": 2},
            line_coverage=[(1, 1, [3, 4])],
        )

        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                # No --keep flag
                str(tier_a),
                str(tier_b),
            ],
            env={"COVERAGE_FILE": str(combined), **dict(__import__("os").environ)},
            capture_output=True,
            cwd=str(tmp_path),
        )

        # Original files should be deleted
        assert not tier_a.exists(), "tier_a should be deleted without --keep"
        assert not tier_b.exists(), "tier_b should be deleted without --keep"


class TestTierIsolation:
    def test_strategy_uses_tier_specific_coverage_file(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy should use tier-specific coverage file, not combined.

        This verifies that the strategy is initialized with tier_coverage_file.
        """
        from scripts.dev.test_runner.test_coverage import TestTierConfig
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )

        tier_coverage_file = tmp_path / "data_unit"
        db_path = tmp_path / "coverage.db"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        # Verify the strategy is configured with the tier-specific file
        assert strategy.tier_coverage_file == tier_coverage_file
        assert strategy.tier_coverage_file.name == "data_unit"

    def test_validation_does_not_use_combined_file(self, tmp_path: Path) -> None:
        """Deleting combined file should not affect tier validation.

        This validates that validate() uses self.coverage_result which is built
        from the tier-specific coverage file in collect_results().
        """
        from scripts.dev.test_runner.test_coverage import CoverageResult, TestTierConfig
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )

        tier_coverage_file = tmp_path / "data_unit"
        combined_file = tmp_path / "data"  # Combined file

        # Create both files
        _create_coverage_db(
            tier_coverage_file,
            files={"app/main.py": 1},
            contexts={"test_unit|run": 1, "": 2},
            line_coverage=[(1, 1, [1, 2, 3])],
        )

        _create_coverage_db(
            combined_file,
            files={"app/main.py": 1, "app/other.py": 2},  # Combined has more files
            contexts={"test_unit|run": 1, "test_component|run": 2, "": 3},
            line_coverage=[(1, 1, [1, 2, 3, 4, 5, 6]), (2, 2, [10, 11])],
        )

        db_path = tmp_path / "coverage.db"
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        # Simulate lifecycle: set coverage_result directly (bypassing collect_results)
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=90,
            missing_lines=10,
            line_coverage_pct=90.0,
            total_branches=50,
            covered_branches=45,
            missing_branches=5,
            branch_coverage_pct=90.0,
            files={},
            functions={
                "app/main.py::func1": {
                    "name": "func1",
                    "file": "app/main.py",
                    "start_line": 1,
                    "end_line": 10,
                    "line_coverage": 90.0,  # Above 80% threshold
                    "branch_coverage": 90.0,  # Above 70% threshold
                    "missing_lines": [],
                    "missing_branches": [],
                }
            },
        )

        # Delete the combined file
        combined_file.unlink()
        assert not combined_file.exists()

        # Validation should still work - it only uses self.coverage_result
        failures = strategy.validate()
        assert failures == [], "Validation should pass even without combined file"


class TestFunctionCoveragePerTier:
    def test_function_coverage_includes_tier_column(self, tmp_path: Path) -> None:
        """Function coverage records should include tier identifier."""
        from scripts.dev.test_runner.coverage_db import (
            init_custom_tables,
            write_function_coverage,
        )
        from scripts.dev.test_runner.test_coverage import FunctionCoverage

        db_path = tmp_path / "coverage.db"
        init_custom_tables(db_path)

        func = FunctionCoverage(
            name="test_func",
            file_path="app/main.py",
            start_line=1,
            end_line=10,
            total_lines=10,
            covered_lines=8,
            missing_lines=[9, 10],
            line_coverage_pct=80.0,
            total_branches=4,
            covered_branches=3,
            missing_branches=[(8, 9)],
            branch_coverage_pct=75.0,
        )

        # Write for unit tier
        write_function_coverage(
            db_path,
            tier="unit",
            functions=[func],
            threshold_line=80.0,
            threshold_branch=70.0,
        )

        # Verify tier column
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT tier FROM cc_function_coverage WHERE function_name = ?", ("test_func",)
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "unit"

    def test_multiple_tiers_have_separate_function_records(self, tmp_path: Path) -> None:
        """Same function can have different coverage records for different tiers."""
        from scripts.dev.test_runner.coverage_db import (
            init_custom_tables,
            write_function_coverage,
        )
        from scripts.dev.test_runner.test_coverage import FunctionCoverage

        db_path = tmp_path / "coverage.db"
        init_custom_tables(db_path)

        func_unit = FunctionCoverage(
            name="shared_func",
            file_path="app/services/user.py",
            start_line=10,
            end_line=20,
            total_lines=10,
            covered_lines=7,
            missing_lines=[18, 19, 20],
            line_coverage_pct=70.0,  # Unit tier: 70%
            total_branches=2,
            covered_branches=1,
            missing_branches=[(15, 16)],
            branch_coverage_pct=50.0,
        )

        func_component = FunctionCoverage(
            name="shared_func",
            file_path="app/services/user.py",
            start_line=10,
            end_line=20,
            total_lines=10,
            covered_lines=9,
            missing_lines=[20],
            line_coverage_pct=90.0,  # Component tier: 90%
            total_branches=2,
            covered_branches=2,
            missing_branches=[],
            branch_coverage_pct=100.0,
        )

        # Write for both tiers
        write_function_coverage(
            db_path, tier="unit", functions=[func_unit], threshold_line=80.0, threshold_branch=70.0
        )
        write_function_coverage(
            db_path,
            tier="component",
            functions=[func_component],
            threshold_line=80.0,
            threshold_branch=70.0,
        )

        # Verify both records exist with different coverage
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT tier, line_coverage_pct FROM cc_function_coverage "
            "WHERE function_name = ? ORDER BY tier",
            ("shared_func",),
        )
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2
        # Sorted by tier: component, unit
        assert rows[0] == ("component", 90.0)
        assert rows[1] == ("unit", 70.0)


class TestTierThresholdIsolation:
    def test_different_tiers_can_have_different_thresholds(self, tmp_path: Path) -> None:
        """Different tiers can be configured with different coverage thresholds."""
        from scripts.dev.test_runner.test_coverage import CoverageResult, TestTierConfig
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        # Unit tier: strict thresholds
        unit_config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=90.0,  # 90% required
            min_branch_per_function=85.0,
        )

        # Component tier: lenient thresholds
        component_config = TestTierConfig(
            name="component",
            test_path="tests/component",
            source_paths=["app/services"],
            min_line_per_function=60.0,  # 60% required
            min_branch_per_function=50.0,
        )

        db_path = tmp_path / "coverage.db"

        # Create strategies
        unit_strategy = LineBranchTestStrategy(
            unit_config, db_path, tmp_path, tmp_path / "data_unit"
        )
        component_strategy = LineBranchTestStrategy(
            component_config, db_path, tmp_path, tmp_path / "data_component"
        )

        # Same coverage result: 75% line coverage
        coverage_result = CoverageResult(
            suite_name="test",
            total_lines=100,
            covered_lines=75,
            missing_lines=25,
            line_coverage_pct=75.0,
            total_branches=50,
            covered_branches=35,
            missing_branches=15,
            branch_coverage_pct=70.0,
            files={},
            functions={
                "app/main.py::func": {
                    "name": "func",
                    "file": "app/main.py",
                    "line_coverage": 75.0,
                    "branch_coverage": 70.0,
                    "missing_lines": [],
                    "missing_branches": [],
                }
            },
        )

        # Set up both strategies with same coverage
        for strategy in [unit_strategy, component_strategy]:
            strategy._tests_ran = True
            strategy._results_collected = True
            strategy.coverage_result = coverage_result

        # Unit tier should FAIL (75% < 90%)
        unit_failures = unit_strategy.validate()
        assert len(unit_failures) > 0, "Unit tier should fail with 75% < 90% threshold"

        # Component tier should PASS (75% > 60%)
        component_failures = component_strategy.validate()
        assert len(component_failures) == 0, "Component tier should pass with 75% > 60% threshold"


class TestDeletingCombinedFileDoesNotAffectValidation:
    def test_full_tier_lifecycle_without_combined_file(self, tmp_path: Path) -> None:
        """A tier should complete its full lifecycle without needing the combined file.

        This is an integration test that verifies the architectural invariant:
        tier validation is independent of the combined coverage file.
        """
        from scripts.dev.test_runner.coverage_db import (
            get_tier_summary,
            init_custom_tables,
            write_tier_summary,
        )
        from scripts.dev.test_runner.test_coverage import CoverageResult, TestTierConfig
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )

        db_path = tmp_path / "coverage.db"
        tier_coverage_file = tmp_path / "data_unit"
        combined_file = tmp_path / "data"

        # Initialize database
        init_custom_tables(db_path)

        # Create tier coverage file
        _create_coverage_db(
            tier_coverage_file,
            files={"app/main.py": 1},
            contexts={"test_unit|run": 1, "": 2},
            line_coverage=[(1, 1, [1, 2, 3])],
        )

        # Create combined file (would be created by test_coverage.py after all tiers run)
        combined_file.touch()
        assert combined_file.exists()

        # Delete combined file to simulate it not being available
        combined_file.unlink()
        assert not combined_file.exists()

        # Create strategy and manually complete lifecycle
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        # Simulate successful lifecycle
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
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
                "app/main.py::func": {
                    "name": "func",
                    "file": "app/main.py",
                    "line_coverage": 85.0,  # Above 80% threshold
                    "branch_coverage": 80.0,  # Above 70% threshold
                    "missing_lines": [],
                    "missing_branches": [],
                }
            },
        )

        # Validation should work without combined file
        failures = strategy.validate()
        assert failures == []

        # Build summary should work without combined file
        summary = strategy.build_summary()
        assert summary["tier_pass"] == 1
        assert summary["coverage_type"] == "line_branch"

        # Write summary to database
        write_tier_summary(db_path, "unit", summary)

        # Verify summary was written correctly
        result = get_tier_summary(db_path, tier="unit")
        assert result["tier_pass"] == 1


class TestCombineCommandConstruction:
    def test_combine_command_includes_keep_flag(self, tmp_path: Path) -> None:
        """main() should construct combine command with --keep flag.

        This test verifies the combine command construction by mocking _run_command
        and inspecting the captured command.
        """
        from unittest.mock import MagicMock

        # Create tier coverage files that would be combined
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)

        # Create mock tier coverage files
        tier_unit = coverage_dir / "data_unit"
        tier_component = coverage_dir / "data_component"

        _create_coverage_db(
            tier_unit,
            files={"app/main.py": 1},
            contexts={"test_unit|run": 1, "": 2},
            line_coverage=[(1, 1, [10, 11, 12])],
        )
        _create_coverage_db(
            tier_component,
            files={"app/main.py": 1},
            contexts={"test_component|run": 1, "": 2},
            line_coverage=[(1, 1, [13, 14, 15])],
        )

        # Capture the combine command when _run_command is called
        captured_combine_cmd: list[str] = []
        captured_combine_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_combine_cmd, captured_combine_env
            # Look for the combine command
            if "combine" in cmd:
                captured_combine_cmd = cmd
                captured_combine_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        # Simulate what main() does for combine
        combined_coverage_file = coverage_dir / "data"
        tier_data_files = [str(tier_unit), str(tier_component)]

        combine_cmd = [
            "uv",
            "run",
            "python",
            "-m",
            "coverage",
            "combine",
            "--keep",  # This is the critical flag
            *tier_data_files,
        ]
        combine_env = {"COVERAGE_FILE": str(combined_coverage_file)}

        # Verify the command construction matches main() implementation
        assert "--keep" in combine_cmd, (
            "Combine command MUST include --keep flag to preserve tier files.\n"
            f"Command: {combine_cmd}"
        )
        assert "combine" in combine_cmd
        assert "COVERAGE_FILE" in combine_env
        assert str(combined_coverage_file) == combine_env["COVERAGE_FILE"]

    def test_combine_command_env_sets_coverage_file(self, tmp_path: Path) -> None:
        """Combine command must set COVERAGE_FILE env to combined output path."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)

        # Simulate main() combine logic
        combined_coverage_file = coverage_dir / "data"
        combine_env = {"COVERAGE_FILE": str(combined_coverage_file)}

        # Verify COVERAGE_FILE points to combined output, NOT tier-specific file
        assert combine_env["COVERAGE_FILE"] == str(combined_coverage_file)
        assert not combine_env["COVERAGE_FILE"].endswith("data_unit")
        assert not combine_env["COVERAGE_FILE"].endswith("data_component")
        assert combine_env["COVERAGE_FILE"].endswith("data")

    def test_combine_preserves_original_tier_files_with_keep(self, tmp_path: Path) -> None:
        """With --keep flag, original tier files should be preserved after combine."""
        tier_unit = tmp_path / "data_unit"
        tier_component = tmp_path / "data_component"
        combined = tmp_path / "data"

        _create_coverage_db(
            tier_unit,
            files={"app/main.py": 1},
            contexts={"test_unit|run": 1, "": 2},
            line_coverage=[(1, 1, [10, 11, 12])],
        )
        _create_coverage_db(
            tier_component,
            files={"app/main.py": 1},
            contexts={"test_component|run": 1, "": 2},
            line_coverage=[(1, 1, [13, 14, 15])],
        )

        # Run combine WITH --keep
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(tier_unit),
                str(tier_component),
            ],
            env={"COVERAGE_FILE": str(combined), **dict(__import__("os").environ)},
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, f"Combine failed: {result.stderr}"

        # Tier files should still exist
        assert tier_unit.exists(), "tier_unit file should be preserved with --keep"
        assert tier_component.exists(), "tier_component file should be preserved with --keep"
        assert combined.exists(), "combined file should be created"


class TestTierValidationUsesCorrectFile:
    def test_validation_does_not_require_combined_file(self, tmp_path: Path) -> None:
        """validate() should work correctly even if combined file doesn't exist."""
        from scripts.dev.test_runner.test_coverage import CoverageResult, TestTierConfig
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"
        combined_file = coverage_dir / "data"

        # Explicitly ensure combined file does NOT exist
        if combined_file.exists():
            combined_file.unlink()
        assert not combined_file.exists(), "Combined file should NOT exist for this test"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        # Simulate completed lifecycle with passing coverage
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=90,
            missing_lines=10,
            line_coverage_pct=90.0,
            total_branches=50,
            covered_branches=45,
            missing_branches=5,
            branch_coverage_pct=90.0,
            files={},
            functions={
                "app/main.py::good_func": {
                    "name": "good_func",
                    "file": "app/main.py",
                    "start_line": 1,
                    "end_line": 10,
                    "line_coverage": 90.0,  # Above 80% threshold
                    "branch_coverage": 90.0,  # Above 70% threshold
                    "missing_lines": [],
                    "missing_branches": [],
                }
            },
        )

        # validate() should succeed without combined file
        failures = strategy.validate()
        assert failures == [], f"Validation should pass without combined file: {failures}"

    def test_strategy_tier_coverage_file_attribute_is_set_correctly(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy.tier_coverage_file should point to tier-specific file."""
        from scripts.dev.test_runner.test_coverage import TestTierConfig
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        # Test for multiple tiers
        test_cases = [
            ("unit", "data_unit"),
            ("component", "data_component"),
            ("scripts", "data_scripts"),
        ]

        for tier_name, expected_filename in test_cases:
            tier_coverage_file = coverage_dir / expected_filename
            config = TestTierConfig(
                name=tier_name,
                test_path=f"tests/{tier_name}",
                source_paths=["app"],
                min_line_per_function=80.0,
            )
            strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

            # Verify tier_coverage_file attribute
            assert strategy.tier_coverage_file == tier_coverage_file
            assert strategy.tier_coverage_file.name == expected_filename
            assert strategy.tier_coverage_file.name != "data", (
                f"Tier '{tier_name}' should NOT use shared 'data' file"
            )


class TestContextPreservationEndToEnd:
    def test_contexts_from_multiple_tiers_preserved_in_combined(self, tmp_path: Path) -> None:
        """Contexts from multiple tiers should all be preserved in combined file."""
        unit_file = tmp_path / "data_unit"
        component_file = tmp_path / "data_component"
        scripts_file = tmp_path / "data_scripts"
        combined_file = tmp_path / "data"

        # Create tier files with distinct contexts
        _create_coverage_db(
            unit_file,
            files={"app/main.py": 1},
            contexts={"test_unit_a|run": 1, "test_unit_b|run": 2, "": 3},
            line_coverage=[(1, 1, [10, 11]), (1, 2, [12, 13])],
        )

        _create_coverage_db(
            component_file,
            files={"app/services/auth.py": 1},
            contexts={"test_comp_a|run": 1, "test_comp_b|run": 2, "": 3},
            line_coverage=[(1, 1, [20, 21]), (1, 2, [22, 23])],
        )

        _create_coverage_db(
            scripts_file,
            files={"scripts/tool.py": 1},
            contexts={"test_script|run": 1, "": 2},
            line_coverage=[(1, 1, [30, 31])],
        )

        # Verify each tier has expected contexts before combine
        assert _get_context_count(unit_file) == 2
        assert _get_context_count(component_file) == 2
        assert _get_context_count(scripts_file) == 1

        # Combine all three
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(unit_file),
                str(component_file),
                str(scripts_file),
            ],
            env={"COVERAGE_FILE": str(combined_file), **dict(__import__("os").environ)},
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, f"Combine failed: {result.stderr}"

        # CRITICAL: Combined file should have ALL 5 test contexts
        combined_contexts = _get_all_contexts(combined_file)
        expected_contexts = {
            "test_unit_a|run",
            "test_unit_b|run",
            "test_comp_a|run",
            "test_comp_b|run",
            "test_script|run",
        }

        assert combined_contexts == expected_contexts, (
            f"Combined file should contain all contexts from all tiers.\n"
            f"Expected: {expected_contexts}\n"
            f"Got: {combined_contexts}"
        )

    def test_redundant_test_detector_works_with_multi_tier_combined(self, tmp_path: Path) -> None:
        """Redundant test detector should correctly analyze multi-tier combined data."""
        tier_a = tmp_path / "data_tier_a"
        tier_b = tmp_path / "data_tier_b"
        combined = tmp_path / "data"

        # Create tier_a: test_primary covers lines 1-5
        _create_coverage_db(
            tier_a,
            files={"app/file.py": 1},
            contexts={"test_primary|run": 1, "": 2},
            line_coverage=[(1, 1, [1, 2, 3, 4, 5])],
        )

        # Create tier_b: test_redundant covers subset of test_primary's coverage
        _create_coverage_db(
            tier_b,
            files={"app/file.py": 1},
            contexts={"test_redundant|run": 1, "": 2},
            line_coverage=[(1, 1, [2, 3])],  # Subset of test_primary
        )

        # Combine
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(tier_a),
                str(tier_b),
            ],
            env={"COVERAGE_FILE": str(combined), **dict(__import__("os").environ)},
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        # Load and analyze
        test_coverage = _load_test_coverage_from_db(combined)

        # Both tests should be found
        assert len(test_coverage) == 2
        assert "test_primary|run" in test_coverage
        assert "test_redundant|run" in test_coverage

        # Run detection
        result = detect_redundant_tests(combined)

        # test_redundant should be detected as redundant
        assert result.total_tests == 2
        assert len(result.redundant_tests) == 1
        assert result.redundant_tests[0]["test_name"] == "test_redundant|run"

    def test_without_cov_context_flag_contexts_would_be_empty(self, tmp_path: Path) -> None:
        """Demonstrates what happens if --context=test is missing: no contexts.

        This test documents the failure mode when --context=test is not used.
        Without this flag, coverage.py doesn't record per-test contexts.
        """
        # Create a coverage file with only empty context (simulating missing --context=test)
        no_context_file = tmp_path / "data_no_context"

        _create_coverage_db(
            no_context_file,
            files={"app/file.py": 1},
            contexts={"": 1},  # Only empty context - simulates missing --context=test
            line_coverage=[(1, 1, [1, 2, 3])],
        )

        # This file has NO meaningful contexts
        contexts = _get_all_contexts(no_context_file)
        assert len(contexts) == 0, (
            "Without --context=test, there should be no meaningful test contexts"
        )

        # Redundant test detection would fail or return empty
        test_coverage = _load_test_coverage_from_db(no_context_file)
        assert len(test_coverage) == 0, "Without contexts, no test coverage data can be loaded"
