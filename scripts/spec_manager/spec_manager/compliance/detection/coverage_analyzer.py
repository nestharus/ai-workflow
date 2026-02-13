"""Coverage analyzer for executable gap detection.

Wraps coverage.py to identify unexercised paths in algorithmic code.
Reports which functions/branches are exercised vs. not.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import analyze_source
from spec_manager.core.gap import GapEvidence


@dataclass
class FileCoverage:
    """Coverage data for a single file."""

    file_path: str
    total_statements: int
    covered_statements: int
    missing_lines: list[int]
    coverage_ratio: float


@dataclass
class FunctionCoverage:
    """Coverage data for a single function."""

    file_path: str
    function_name: str
    line_start: int
    line_end: int
    total_statements: int
    covered_statements: int
    coverage_ratio: float


@dataclass
class CoverageReport:
    """Aggregate coverage report across files."""

    files: list[FileCoverage] = field(default_factory=list)
    functions: list[FunctionCoverage] = field(default_factory=list)
    overall_ratio: float = 0.0
    uncovered_functions: list[FunctionCoverage] = field(default_factory=list)


def run_coverage(
    test_command: list[str],
    source_dirs: list[Path],
    project_root: Path,
    coverage_data_file: Path | None = None,
) -> Path:
    """Run a test command with coverage.py instrumentation.

    Executes: coverage run --source=<dirs> <test_command>
    Returns path to the .coverage data file.

    Args:
        test_command: Command to run (e.g., ["pytest", "tests/"]).
        source_dirs: Directories to measure coverage for.
        project_root: Working directory for the command.
        coverage_data_file: Optional path for .coverage file.

    Returns:
        Path to the .coverage data file.
    """
    if coverage_data_file is None:
        coverage_data_file = project_root / ".coverage"

    source_arg = ",".join(str(d) for d in source_dirs)

    cmd = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        f"--source={source_arg}",
        f"--data-file={coverage_data_file}",
        "-m",
        *test_command,
    ]

    subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=300,
    )

    return coverage_data_file


def _extract_function_ranges(source: str, filepath: str = "") -> list[tuple[str, int, int]]:
    """Extract function name and line ranges from source code.

    Uses ``analyze_source`` (language-agnostic) instead of Python AST.

    Returns list of (qualified_name, start_line, end_line).
    """
    analysis = analyze_source(source, filepath)

    ranges: list[tuple[str, int, int]] = []
    for func in analysis.functions:
        qualified = func.qualified_name or func.name
        ranges.append((qualified, func.start_line, func.end_line))

    return ranges


def _count_statements_in_range(
    source_lines: list[str],
    start: int,
    end: int,
) -> int:
    """Count non-blank, non-comment, non-decorator lines in a range.

    This is a rough approximation of statement count.
    """
    from spec_manager.core.language import COMMENT_PREFIX, DECORATOR_PREFIX

    count = 0
    for i in range(start - 1, min(end, len(source_lines))):
        line = source_lines[i].strip()
        if not line:
            continue
        if line.startswith(COMMENT_PREFIX.rstrip()):
            continue
        if line.startswith(DECORATOR_PREFIX):
            continue
        count += 1
    return count


def parse_coverage_report(
    coverage_data_file: Path,
    source_files: list[Path],
) -> CoverageReport:
    """Parse a .coverage data file into structured coverage data.

    Uses coverage.py JSON report to analyze per-file coverage, then
    cross-references with extracted function ranges for per-function
    coverage.

    Args:
        coverage_data_file: Path to .coverage file.
        source_files: Files to analyze coverage for.

    Returns:
        CoverageReport with file and function-level data.
    """
    # Generate JSON report
    json_file = coverage_data_file.parent / "coverage.json"

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                f"--data-file={coverage_data_file}",
                f"-o={json_file}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CoverageReport()

    if not json_file.exists():
        return CoverageReport()

    try:
        cov_data = json.loads(json_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return CoverageReport()
    finally:
        json_file.unlink(missing_ok=True)

    file_coverages: list[FileCoverage] = []
    function_coverages: list[FunctionCoverage] = []
    uncovered_functions: list[FunctionCoverage] = []

    total_stmts = 0
    total_covered = 0

    source_file_strs = {str(f.resolve()) for f in source_files}
    files_data = cov_data.get("files", {})

    for file_path_str, file_info in files_data.items():
        resolved = str(Path(file_path_str).resolve())
        if source_file_strs and resolved not in source_file_strs:
            continue

        summary = file_info.get("summary", {})
        num_statements = summary.get("num_statements", 0)
        covered = summary.get("covered_lines", 0)
        missing = file_info.get("missing_lines", [])

        ratio = covered / num_statements if num_statements > 0 else 1.0

        file_coverages.append(
            FileCoverage(
                file_path=file_path_str,
                total_statements=num_statements,
                covered_statements=covered,
                missing_lines=missing,
                coverage_ratio=ratio,
            )
        )

        total_stmts += num_statements
        total_covered += covered

        # Per-function coverage from analyze_source + missing lines
        try:
            source = Path(file_path_str).read_text(encoding="utf-8")
            source_lines = source.splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        function_ranges = _extract_function_ranges(source, file_path_str)
        missing_set = set(missing)

        for func_name, start, end in function_ranges:
            func_stmts = _count_statements_in_range(source_lines, start, end)
            func_missing = sum(1 for line in range(start, end + 1) if line in missing_set)
            func_covered = max(0, func_stmts - func_missing)
            func_ratio = func_covered / func_stmts if func_stmts > 0 else 1.0

            fc = FunctionCoverage(
                file_path=file_path_str,
                function_name=func_name,
                line_start=start,
                line_end=end,
                total_statements=func_stmts,
                covered_statements=func_covered,
                coverage_ratio=func_ratio,
            )
            function_coverages.append(fc)

            if func_ratio == 0.0 and func_stmts > 0:
                uncovered_functions.append(fc)

    overall_ratio = total_covered / total_stmts if total_stmts > 0 else 1.0

    return CoverageReport(
        files=file_coverages,
        functions=function_coverages,
        overall_ratio=overall_ratio,
        uncovered_functions=uncovered_functions,
    )


def coverage_to_gap_evidence(
    report: CoverageReport,
    min_function_coverage: float = 0.0,
) -> list[GapEvidence]:
    """Convert uncovered functions to GapEvidence.

    Only functions with coverage_ratio <= min_function_coverage are gaps.
    Default threshold is 0.0 (only completely uncovered functions).

    invariant_family = "executable_coverage"
    detector = "coverage_analyzer"

    Args:
        report: CoverageReport from parse_coverage_report.
        min_function_coverage: Threshold below which a function is a gap.

    Returns:
        List of GapEvidence for uncovered functions.
    """
    evidence: list[GapEvidence] = []

    candidates = (
        report.uncovered_functions
        if min_function_coverage == 0.0
        else [f for f in report.functions if f.coverage_ratio <= min_function_coverage]
    )

    for func in candidates:
        details: dict[str, Any] = {
            "function_name": func.function_name,
            "line_start": func.line_start,
            "line_end": func.line_end,
            "total_statements": func.total_statements,
            "covered_statements": func.covered_statements,
            "coverage_ratio": func.coverage_ratio,
        }
        evidence.append(
            GapEvidence(
                invariant_family="executable_coverage",
                description=(
                    f"Uncovered function: {func.function_name} "
                    f"({func.coverage_ratio:.0%} coverage, "
                    f"{func.total_statements} statements)"
                ),
                details=details,
                confidence=0.8,
                location=f"{func.file_path}:{func.line_start}-{func.line_end}",
                detector="coverage_analyzer",
            )
        )

    return evidence
