r"""Orchestrate parallel test-debugger agents for coverage improvement.

This script:
1. Runs the batching script to create batch files
2. Launches N test-debugger agents in parallel
3. Waits for them to complete
4. Re-runs test-coverage and rebatches
5. Repeats until all functions pass or no progress is made

Usage:
    uv run python scripts/dev/test_runner/run_coverage_batches.py \
        [--tier TIER] [--parallel N] [--max-iterations M]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import TypedDict

    class ManifestDict(TypedDict):
        """Manifest structure from batch_coverage_gaps.py."""

        total_batches: int
        total_functions: int
        batch_files: list[str]


def run_test_coverage(tier: str | None = None) -> dict[str, dict[str, int | bool]]:
    """Run test-coverage and return summary from database."""
    cmd = ["uv", "run", "test-coverage", "--no-validate"]
    if tier:
        cmd.extend(["--tier", tier])

    print(f"\n{'=' * 60}")
    print("Running test-coverage...")
    print(f"{'=' * 60}\n")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"test-coverage output:\n{result.stdout}\n{result.stderr}")

    # Query database for summary
    import sqlite3

    conn = sqlite3.connect(".coverage/coverage.db")
    cursor = conn.cursor()

    summary: dict[str, dict[str, int | bool]] = {}
    if tier:
        cursor.execute(
            """SELECT tier, failing_functions, total_functions, tier_pass
            FROM cc_tier_summary WHERE tier = ?""",
            (tier,),
        )
    else:
        cursor.execute(
            "SELECT tier, failing_functions, total_functions, tier_pass FROM cc_tier_summary"
        )

    for row in cursor.fetchall():
        summary[row[0]] = {
            "failing": row[1],
            "total": row[2],
            "pass": bool(row[3]),
        }
    conn.close()
    return summary


def run_batching(tier: str | None, batch_size: int = 10) -> ManifestDict | None:
    """Run the batching script and return manifest."""
    cmd = [
        "uv",
        "run",
        "python",
        "scripts/dev/test_runner/batch_coverage_gaps.py",
        "--batch-size",
        str(batch_size),
    ]
    if tier:
        cmd.extend(["--tier", tier])

    print(f"\n{'=' * 60}")
    print("Creating batches...")
    print(f"{'=' * 60}\n")

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return None

    manifest_path = Path(".tmp/test_batches/manifest.json")
    if manifest_path.exists():
        return cast("ManifestDict", json.loads(manifest_path.read_text()))
    return None


def generate_agent_prompt(batch_file: str, tier: str | None) -> str:
    """Generate the prompt for a test-debugger agent working on a batch."""
    _ = tier  # Reserved for future tier-specific prompts
    return f"""IMPORTANT: This is a coverage improvement task, NOT a test debugging task.

Read the batch file at `.tmp/test_batches/{batch_file}` to get the list of
functions needing coverage improvement.

The batch file contains:
- `functions_by_test_file`: Mapping from test file paths to source functions
- Each function entry has: `source_file`, `function_name`, `missing_lines`,
  `missing_branches`

Your workflow:
1. Read the batch file to understand which functions need coverage
2. For each test file in `functions_by_test_file`:
   a. Read the corresponding source file(s) to understand the code
   b. Read the existing test file (if it exists)
   c. Add or modify tests to cover the `missing_lines` and `missing_branches`
3. Run pytest WITHOUT COVERAGE to verify your tests work:
   `uv run pytest <test_file> -v`
   CRITICAL: NEVER use --cov flags - coverage is measured separately at the end.
4. Report what you improved

Focus on writing meaningful tests that exercise the uncovered code paths.
The goal is to get each function's line coverage >= 80% and branch coverage
>= 70%.

Key rules:
- Do NOT change source code - only add/modify tests
- Do NOT skip tests or mark them as expected failures
- Do NOT change coverage thresholds or test settings
- Write tests that actually exercise the missing lines/branches
- NEVER run pytest with --cov flags (causes conflicts with parallel agents)

The worktree is: .

Report your results in this format:
```
Status: IMPROVED|PARTIAL|BLOCKED

Functions Improved:
- <source_file>::<function> - added tests for lines X, Y, Z

Remaining Issues:
- <function>: <why it cannot be improved>
```
"""


def print_summary(summary: dict[str, dict[str, int | bool]], iteration: int) -> None:
    """Print a nice summary of current state."""
    print(f"\n{'=' * 60}")
    print(f"Iteration {iteration} Summary")
    print(f"{'=' * 60}")
    for tier, data in sorted(summary.items()):
        status = "PASS" if data["pass"] else "FAIL"
        print(f"  {tier}: {status} ({data['failing']}/{data['total']} failing)")


def main() -> None:
    """Orchestrate parallel coverage improvement."""
    parser = argparse.ArgumentParser(description="Orchestrate parallel coverage improvement")
    parser.add_argument(
        "--tier", choices=["unit", "component", "scripts"], help="Only process specific tier"
    )
    parser.add_argument(
        "--parallel", type=int, default=4, help="Number of parallel agents (default: 4)"
    )
    parser.add_argument(
        "--max-iterations", type=int, default=5, help="Maximum iterations (default: 5)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=10, help="Target batch size (default: 10)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show commands without running agents"
    )
    args = parser.parse_args()

    print(f"""
{"=" * 60}
Coverage Improvement Orchestrator
{"=" * 60}
Tier: {args.tier or "all"}
Parallel agents: {args.parallel}
Max iterations: {args.max_iterations}
Batch size: {args.batch_size}
""")

    for iteration in range(1, args.max_iterations + 1):
        print(f"\n{'#' * 60}")
        print(f"# ITERATION {iteration}")
        print(f"{'#' * 60}")

        # Run test-coverage to get current state
        summary = run_test_coverage(args.tier)
        print_summary(summary, iteration)

        # Check if we're done
        all_pass = all(data["pass"] for data in summary.values())
        if all_pass:
            print("\n All tiers passing! Done.")
            return

        # Create batches
        manifest = run_batching(args.tier, args.batch_size)
        if not manifest or manifest["total_batches"] == 0:
            print("\n No batches to process. Exiting.")
            return

        total_batches = manifest["total_batches"]
        print(f"\nCreated {total_batches} batches with {manifest['total_functions']} functions")

        # Process batches in groups of N
        batch_files = manifest["batch_files"]

        if args.dry_run:
            print("\n[DRY RUN] Would launch agents for batches:")
            for i, batch_file in enumerate(batch_files, 1):
                print(f"  Agent {i}: {batch_file}")
            print("\n[DRY RUN] Skipping actual agent execution")
            continue

        print("\nTo run agents in parallel, use Claude Code Task tool:")
        print("-" * 60)
        for i, batch_file in enumerate(batch_files[: args.parallel], 1):
            prompt = generate_agent_prompt(batch_file, args.tier)
            print(f"\nAgent {i} (batch: {batch_file}):")
            print("  Task(subagent_type='test-debugger', prompt='''")
            print(prompt.strip())
            print("''')")
        print("-" * 60)
        print(f"\nNote: Launch {min(args.parallel, len(batch_files))} agents in parallel")
        print("After they complete, run this script again for the next iteration")

        # Since we can't actually launch Task agents from here, we output instructions
        break  # Exit after showing instructions for first batch

    print("\nOrchestration complete. Run agents as shown above.")


if __name__ == "__main__":
    main()
