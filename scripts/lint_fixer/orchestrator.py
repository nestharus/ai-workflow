"""Core orchestration logic for the lint-fixer workflow.

This module provides the main loop that:
1. Runs linters and collects errors
2. Hashes files with errors before agent runs
3. Invokes the lint-fixer agent to fix errors
4. Detects file changes via hash comparison
5. Dispatches stuck errors to investigator in parallel
6. Re-lints only changed files
7. Repeats until all fixed or no files changed
"""

from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import cast


def resolve_pr_context(ticket_id: str) -> tuple[Path, list[str]]:
    """Resolve working directory and files from a PR ticket.

    Args:
        ticket_id: Linear ticket ID (e.g., NES-123).

    Returns:
        Tuple of (worktree_path, list_of_files).

    Raises:
        RuntimeError: If PR resolution fails.
    """
    # Get PR info
    result = subprocess.run(
        ["uv", "run", "pr", "get-pr", ticket_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get PR info for {ticket_id}: {result.stderr}")

    try:
        pr_info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from get-pr: {e}") from e

    worktree_path = Path(pr_info.get("working_directory", "."))
    pr_number = pr_info.get("pr_number")

    if not pr_number:
        raise RuntimeError(f"No PR number found for ticket {ticket_id}")

    # Get changed files
    result = subprocess.run(
        ["uv", "run", "pr", "get-changed-files", "--pr", str(pr_number)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get changed files for PR #{pr_number}: {result.stderr}")

    try:
        files = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from get-changed-files: {e}") from e

    return worktree_path, files


def resolve_worktree(args: Namespace) -> Path:
    """Resolve the working directory from arguments.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Path to the working directory.
    """
    if args.worktree:
        return cast("Path", args.worktree).resolve()
    return Path.cwd()


def resolve_files(args: Namespace) -> list[str] | None:
    """Resolve the list of files to lint from arguments.

    Args:
        args: Parsed command-line arguments.

    Returns:
        List of files to lint, or None to lint all files.
    """
    if args.files:
        return cast("list[str]", args.files)
    return None


def run_linters(
    files: list[str] | None,
    worktree: Path,
    changed_only: bool = False,
    commit: str | None = None,
    output_format: str = "yaml",
) -> tuple[bool, str]:
    """Run the lint suite and capture output.

    Args:
        files: List of specific files to lint, or None for all files.
        worktree: Working directory to run linters in.
        changed_only: If True, only lint changed files.
        commit: If provided, only lint files from this commit.
        output_format: Output format - "yaml" for structured, "text" for human-readable.

    Returns:
        Tuple of (success, output_text).
    """
    cmd = ["uv", "run", "lint", "--output-format", output_format]

    if files:
        cmd.extend(["--files", *files])
    elif changed_only:
        cmd.append("--changed-only")
    elif commit:
        cmd.extend(["--commit", commit])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=worktree,
    )

    # Combine stdout and stderr for full output
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def get_file_hashes(files: list[str], worktree: Path) -> dict[str, str]:
    """Get SHA256 hashes of files for change detection.

    Args:
        files: List of file paths relative to worktree.
        worktree: Working directory.

    Returns:
        Dict mapping file path to hash.
    """
    import hashlib

    hashes = {}
    for file in files:
        path = worktree / file
        if path.exists():
            hashes[file] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _extract_yaml_block(output: str) -> str | None:
    """Extract the YAML errors block from mixed output.

    The lint output may contain progress messages before the YAML block.
    This function finds the `errors:` line and extracts from there to the end.

    Args:
        output: Full lint output with potential mixed content.

    Returns:
        The YAML block starting from `errors:`, or None if not found.
    """
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "errors:" or line.strip() == "errors: []":
            return "\n".join(lines[i:])
    return None


def extract_files_from_lint_output(lint_output: str) -> list[str]:
    """Extract file paths from lint output.

    Supports both YAML format (preferred) and legacy text formats.

    Args:
        lint_output: Lint output in YAML or text format.

    Returns:
        List of unique file paths mentioned in errors.
    """
    import re

    import yaml

    files = set()

    # Try to extract YAML block from mixed output
    yaml_block = _extract_yaml_block(lint_output)
    if yaml_block:
        try:
            data = yaml.safe_load(yaml_block)
            if isinstance(data, dict) and "errors" in data:
                errors = data.get("errors", [])
                if isinstance(errors, list):
                    for error in errors:
                        if isinstance(error, dict) and "file" in error:
                            files.add(error["file"])
                if files:
                    return list(files)
        except yaml.YAMLError:
            pass

    # Fall back to regex parsing for legacy text format
    for line in lint_output.splitlines():
        # Match ruff format: "   --> path/to/file.py:line:col"
        ruff_match = re.match(r"^\s*-->\s+([^\s:]+\.\w+):\d+", line)
        if ruff_match:
            files.add(ruff_match.group(1))
            continue

        # Match traditional lint format: "path/to/file.py:line:col:"
        traditional_match = re.match(r"^([^\s:]+\.\w+):\d+", line)
        if traditional_match:
            files.add(traditional_match.group(1))

    return list(files)


def format_agent_input(lint_output: str, worktree: Path) -> str:
    """Format input for the lint-fixer agent.

    Args:
        lint_output: Raw output from the lint command.
        worktree: Working directory.

    Returns:
        Input string for agent.
    """
    return f"{lint_output}\n\nWorking directory: {worktree}"


def invoke_agent(prompt: str, worktree: Path) -> tuple[bool, str]:
    """Invoke the lint-fixer agent with the given prompt.

    Args:
        prompt: The formatted error batch prompt.
        worktree: Working directory for the agent.

    Returns:
        Tuple of (success, agent_output).
    """
    result = subprocess.run(
        ["uv", "run", "python", "-m", "scripts.agents", "lint-fixer"],
        input=prompt,
        capture_output=True,
        text=True,
        cwd=worktree,
    )

    output = result.stdout + result.stderr
    return result.returncode == 0, output


def invoke_investigator(prompt: str, worktree: Path) -> tuple[bool, str]:
    """Invoke the lint-investigator agent with the given prompt.

    Args:
        prompt: The formatted error batch prompt for investigation.
        worktree: Working directory for the agent.

    Returns:
        Tuple of (success, investigation_output).
    """
    result = subprocess.run(
        ["uv", "run", "python", "-m", "scripts.agents", "lint-investigator"],
        input=prompt,
        capture_output=True,
        text=True,
        cwd=worktree,
    )

    output = result.stdout + result.stderr
    return result.returncode == 0, output


def filter_lint_output_for_files(lint_output: str, files: list[str]) -> str:
    """Filter lint output to only include errors for specific files.

    Supports both YAML format (preferred) and legacy text formats.

    Args:
        lint_output: Full lint output in YAML or text format.
        files: List of files to filter for.

    Returns:
        Filtered lint output containing only errors for specified files.
    """
    import yaml

    if not files:
        return ""

    file_set = set(files)

    # Try to extract YAML block from mixed output
    yaml_block = _extract_yaml_block(lint_output)
    if yaml_block:
        try:
            data = yaml.safe_load(yaml_block)
            if isinstance(data, dict) and "errors" in data:
                errors = data.get("errors", [])
                if isinstance(errors, list):
                    filtered_errors = [
                        e for e in errors if isinstance(e, dict) and e.get("file") in file_set
                    ]
                    if filtered_errors:
                        # Output filtered YAML
                        lines = ["errors:"]
                        for error in filtered_errors:
                            lines.append(f"  - linter: {error.get('linter', '')}")
                            lines.append(f"    file: {error.get('file', '')}")
                            lines.append(f"    line: {error.get('line', 0)}")
                            lines.append(f"    column: {error.get('column', 0)}")
                            lines.append(f"    code: {error.get('code', '')}")
                            msg = error.get("message", "")
                            if "\n" in msg or ":" in msg:
                                lines.append("    message: |")
                                for msg_line in msg.splitlines():
                                    lines.append(f"      {msg_line}")
                            else:
                                lines.append(f"    message: {msg}")
                            lines.append(
                                f"    fix_available: {str(error.get('fix_available', False)).lower()}"
                            )
                            if error.get("fix_message"):
                                lines.append(f"    fix_message: {error.get('fix_message')}")
                        return "\n".join(lines)
                    return "errors: []"
        except yaml.YAMLError:
            pass

    # Fall back to line-by-line filtering for legacy text format
    filtered_lines = []
    for line in lint_output.splitlines():
        for f in file_set:
            if line.startswith(f"{f}:"):
                filtered_lines.append(line)
                break

    return "\n".join(filtered_lines)


def _log(msg: str) -> None:
    """Log progress message to stderr for real-time visibility."""
    print(msg, file=sys.stderr, flush=True)


def print_report(
    iterations: int,
    final_success: bool,
    agent_report: str,
    investigation_reports: list[str] | None = None,
) -> None:
    """Print the final report to stdout (for calling agent) and stderr (for visibility).

    Args:
        iterations: Number of iterations completed.
        final_success: Whether linting passed in the end.
        agent_report: The agent's report text.
        investigation_reports: Optional list of investigation reports.
    """
    # Build report lines
    lines = [
        "",
        "=" * 60,
        "Lint Fix Report",
        "=" * 60,
        f"Iterations: {iterations}",
        f"Final status: {'PASS' if final_success else 'FAIL'}",
    ]

    if agent_report.strip():
        lines.append("")
        lines.append("--- Agent Report ---")
        lines.append(agent_report)

    if investigation_reports:
        lines.append("")
        lines.append("--- Investigation Reports ---")
        for i, report in enumerate(investigation_reports, 1):
            lines.append(f"\n[Investigation {i}]")
            lines.append(report)

    lines.append("=" * 60)

    report = "\n".join(lines)

    # Output to stderr for real-time visibility
    _log(report)

    # Output to stdout for calling agent to capture
    print(report)


def orchestrate(args: Namespace) -> int:
    """Main orchestration loop.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    # Handle --pr mode separately
    files: list[str] | None
    if args.pr:
        try:
            worktree, pr_files = resolve_pr_context(args.pr)
            files = pr_files
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if not files:
            _log(f"No changed files in PR for ticket {args.pr}. Skipping lint.")
            return 0
    else:
        worktree = resolve_worktree(args)
        files = resolve_files(args)

    _log(f"Working directory: {worktree}")
    if files:
        _log(f"Files to lint: {len(files)}")
        for f in files[:5]:
            _log(f"  {f}")
        if len(files) > 5:
            _log(f"  ... and {len(files) - 5} more")

    # Initial lint run
    _log("\n=== Initial lint run ===")
    success, output = run_linters(
        files,
        worktree,
        changed_only=args.changed_only,
        commit=args.commit,
    )

    if success:
        _log("No lint errors found.")
        return 0

    # Fix loop - runs until no progress or all fixed
    iteration = 0
    last_agent_report = ""
    investigation_futures: list[Future[tuple[bool, str]]] = []
    executor = ThreadPoolExecutor(max_workers=1)  # Queue investigations sequentially

    try:
        while not success:
            iteration += 1
            _log(f"\n=== Iteration {iteration} ===")

            # Get files with errors and their current hashes
            error_files = extract_files_from_lint_output(output)
            if not error_files:
                _log("No files with errors found in lint output.")
                # If we can't extract any files with errors, treat as success
                # (nothing for lint-fix to fix, even if lint exited non-zero)
                success = True
                break

            before_hashes = get_file_hashes(error_files, worktree)

            # Invoke agent with lint output
            agent_input = format_agent_input(output, worktree)
            agent_success, agent_output = invoke_agent(agent_input, worktree)
            last_agent_report = agent_output

            if not agent_success:
                _log(f"Agent failed: {agent_output}")

            # Check which files changed
            after_hashes = get_file_hashes(error_files, worktree)
            changed_files = [f for f in error_files if before_hashes.get(f) != after_hashes.get(f)]

            # Identify stuck files (errors but no changes)
            stuck_files = [f for f in error_files if before_hashes.get(f) == after_hashes.get(f)]

            # Dispatch stuck errors to investigator in parallel
            if stuck_files:
                stuck_errors = filter_lint_output_for_files(output, stuck_files)
                if stuck_errors:
                    _log(f"Dispatching {len(stuck_files)} stuck file(s) to investigator...")
                    investigation_input = format_agent_input(stuck_errors, worktree)
                    future = executor.submit(invoke_investigator, investigation_input, worktree)
                    investigation_futures.append(future)

            if not changed_files:
                _log("No files changed. Agent couldn't fix anything. Stopping.")
                break

            _log(f"Files modified: {len(changed_files)}")

            # Re-run linters only on changed files
            _log("\nRe-running linters on changed files...")
            success, output = run_linters(
                changed_files,
                worktree,
            )

            if success:
                _log("All lint errors fixed!")
                break

        # Collect investigation results
        investigation_reports: list[str] = []
        if investigation_futures:
            _log("\nWaiting for investigations to complete...")
            for future in investigation_futures:
                try:
                    _inv_success, inv_output = future.result(timeout=300)
                    if inv_output.strip():
                        investigation_reports.append(inv_output)
                except Exception as e:
                    investigation_reports.append(f"Investigation failed: {e}")

    finally:
        executor.shutdown(wait=False)

    # Print report
    print_report(iteration, success, last_agent_report, investigation_reports)

    return 0 if success else 1
