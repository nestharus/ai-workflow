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

from scripts.dev.linter.linters import LINTER_NAMES


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
    linters: list[str] | None = None,
) -> tuple[bool, str]:
    """Run the lint suite and capture output.

    Args:
        files: List of specific files to lint, or None for all files.
        worktree: Working directory to run linters in.
        changed_only: If True, only lint changed files.
        commit: If provided, only lint files from this commit.
        output_format: Output format - "yaml" for structured, "text" for human-readable.
        linters: Specific linters to run, or None for all linters.

    Returns:
        Tuple of (success, output_text).
    """
    cmd = ["uv", "run", "lint", "--output-format", output_format]

    # Add specific linters if provided (must come before --files)
    if linters:
        cmd.extend(linters)

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


def extract_errors_by_linter(lint_output: str) -> dict[str, set[str]]:
    """Extract errors grouped by linter from YAML output.

    Args:
        lint_output: Lint output in YAML format.

    Returns:
        Dict mapping linter name to set of files with errors from that linter.
    """
    import yaml

    errors_by_linter: dict[str, set[str]] = {}

    yaml_block = _extract_yaml_block(lint_output)
    if not yaml_block:
        return errors_by_linter

    try:
        data = yaml.safe_load(yaml_block)
        if not isinstance(data, dict) or "errors" not in data:
            return errors_by_linter

        for error in data.get("errors", []):
            if isinstance(error, dict):
                linter = error.get("linter", "unknown")
                file = error.get("file", "")
                if file:
                    if linter not in errors_by_linter:
                        errors_by_linter[linter] = set()
                    errors_by_linter[linter].add(file)
    except yaml.YAMLError:
        pass

    return errors_by_linter


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
                            if "\n" in msg or ":" in msg or "`" in msg:
                                lines.append("    message: |")
                                for msg_line in msg.splitlines():
                                    lines.append(f"      {msg_line}")
                            else:
                                lines.append(f"    message: {msg}")
                            fix_avail = str(error.get("fix_available", False)).lower()
                            lines.append(f"    fix_available: {fix_avail}")
                            if error.get("fix_message"):
                                fix_msg = str(error.get("fix_message"))
                                if (
                                    "\n" in fix_msg
                                    or ":" in fix_msg
                                    or '"' in fix_msg
                                    or "`" in fix_msg
                                ):
                                    lines.append("    fix_message: |")
                                    for fix_line in fix_msg.splitlines():
                                        lines.append(f"      {fix_line}")
                                else:
                                    lines.append(f"    fix_message: {fix_msg}")
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


def _combine_yaml_outputs(outputs: list[str]) -> str:
    """Combine multiple YAML lint outputs into one.

    Args:
        outputs: List of YAML lint outputs from different linters.

    Returns:
        Combined YAML output with all errors.
    """
    import yaml

    all_errors: list[dict[str, object]] = []

    for output in outputs:
        yaml_block = _extract_yaml_block(output)
        if not yaml_block:
            continue

        try:
            data = yaml.safe_load(yaml_block)
            if isinstance(data, dict) and "errors" in data:
                errors = data.get("errors", [])
                if isinstance(errors, list):
                    all_errors.extend(errors)
        except yaml.YAMLError:
            continue

    if not all_errors:
        return "errors: []"

    # Output combined YAML
    lines = ["errors:"]
    for error in all_errors:
        if not isinstance(error, dict):
            continue
        lines.append(f"  - linter: {error.get('linter', '')}")
        lines.append(f"    file: {error.get('file', '')}")
        lines.append(f"    line: {error.get('line', 0)}")
        lines.append(f"    column: {error.get('column', 0)}")
        lines.append(f"    code: {error.get('code', '')}")
        msg = str(error.get("message", ""))
        if "\n" in msg or ":" in msg or "`" in msg:
            lines.append("    message: |")
            for msg_line in msg.splitlines():
                lines.append(f"      {msg_line}")
        else:
            lines.append(f"    message: {msg}")
        fix_avail = str(error.get("fix_available", False)).lower()
        lines.append(f"    fix_available: {fix_avail}")
        if error.get("fix_message"):
            fix_msg = str(error.get("fix_message"))
            if "\n" in fix_msg or ":" in fix_msg or '"' in fix_msg or "`" in fix_msg:
                lines.append("    fix_message: |")
                for fix_line in fix_msg.splitlines():
                    lines.append(f"      {fix_line}")
            else:
                lines.append(f"    fix_message: {fix_msg}")

    return "\n".join(lines)


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
    print(report)


def orchestrate(args: Namespace) -> int:
    """Main orchestration loop.

    Each linter maintains its own scope that reduces independently as files are fixed.
    After agent makes changes, each linter re-runs only on files that:
    1. Had errors from that linter, AND
    2. Were changed by the agent

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

    # Track errors per linter: {linter: set of files with errors}
    errors_by_linter = extract_errors_by_linter(output)

    # Track which linters each file has passed (don't re-run on unchanged files)
    passed_linters: dict[str, set[str]] = {}  # file -> set of linters that passed

    # Fix loop - runs until no progress or all fixed
    iteration = 0
    last_agent_report = ""
    investigation_futures: list[tuple[Future[tuple[bool, str]], set[str], dict[str, str]]] = []
    executor = ThreadPoolExecutor(max_workers=1)  # Queue investigations sequentially

    try:
        while errors_by_linter or investigation_futures:
            iteration += 1
            _log(f"\n=== Iteration {iteration} ===")

            # Check for completed investigations and process returned files
            completed_investigations: list[
                tuple[Future[tuple[bool, str]], set[str], dict[str, str]]
            ] = []
            pending_investigations: list[
                tuple[Future[tuple[bool, str]], set[str], dict[str, str]]
            ] = []
            for inv_tuple in investigation_futures:
                future, inv_files, inv_hashes = inv_tuple
                if future.done():
                    completed_investigations.append(inv_tuple)
                else:
                    pending_investigations.append(inv_tuple)
            investigation_futures = pending_investigations

            for future, inv_files, inv_hashes in completed_investigations:
                try:
                    _inv_success, inv_output = future.result(timeout=1)
                    # Check if investigator changed any files
                    new_hashes = get_file_hashes(list(inv_files), worktree)
                    changed_by_inv = {
                        f for f in inv_files if inv_hashes.get(f) != new_hashes.get(f)
                    }
                    if changed_by_inv:
                        _log(
                            f"Investigation changed {len(changed_by_inv)} file(s), resuming lint..."
                        )
                        # Clear passed linters for changed files (need to re-lint from start)
                        for f in changed_by_inv:
                            passed_linters.pop(f, None)
                        # Run all linters on changed files to discover new errors
                        inv_lint_success, inv_lint_output = run_linters(
                            list(changed_by_inv), worktree
                        )
                        if not inv_lint_success:
                            inv_errors = extract_errors_by_linter(inv_lint_output)
                            for linter, linter_files in inv_errors.items():
                                if linter not in errors_by_linter:
                                    errors_by_linter[linter] = set()
                                errors_by_linter[linter].update(linter_files)
                    else:
                        # Investigator made no changes - remove files from tracking
                        # to avoid infinite loop
                        _log(
                            f"Investigation made no changes to {len(inv_files)} file(s), "
                            "marking as unfixable"
                        )
                        for linter in list(errors_by_linter.keys()):
                            errors_by_linter[linter] -= inv_files
                            if not errors_by_linter[linter]:
                                del errors_by_linter[linter]
                except Exception as e:
                    _log(f"Investigation failed: {e}")

            # Get all files with errors (union across all linters)
            all_error_files: set[str] = set()
            for linter_files in errors_by_linter.values():
                all_error_files.update(linter_files)

            if not all_error_files:
                if investigation_futures:
                    _log("Waiting for pending investigations...")
                    continue
                _log("No files with errors remaining.")
                success = True
                break

            # Hash files before agent runs
            before_hashes = get_file_hashes(list(all_error_files), worktree)

            # Invoke agent with lint output
            agent_input = format_agent_input(output, worktree)
            agent_success, agent_output = invoke_agent(agent_input, worktree)
            last_agent_report = agent_output

            if not agent_success:
                _log(f"Agent failed: {agent_output}")

            # Detect which files changed
            after_hashes = get_file_hashes(list(all_error_files), worktree)
            changed_files = {
                f for f in all_error_files if before_hashes.get(f) != after_hashes.get(f)
            }

            # Dispatch stuck files (unchanged) to investigator before checking progress
            stuck_files = all_error_files - changed_files
            if stuck_files:
                stuck_errors = filter_lint_output_for_files(output, list(stuck_files))
                if stuck_errors and stuck_errors.strip() != "errors: []":
                    _log(f"Dispatching {len(stuck_files)} stuck file(s) to investigator...")
                    # Store hashes to detect changes when investigation completes
                    stuck_hashes = get_file_hashes(list(stuck_files), worktree)
                    investigation_input = format_agent_input(stuck_errors, worktree)
                    future = executor.submit(invoke_investigator, investigation_input, worktree)
                    investigation_futures.append((future, stuck_files, stuck_hashes))

            if not changed_files:
                if investigation_futures:
                    _log("No files changed. Waiting for investigations...")
                    continue
                _log("No files changed. Agent couldn't fix anything. Stopping.")
                break

            _log(f"Files modified: {len(changed_files)}")

            # Clear passed_linters for changed files (changes may introduce new errors)
            for f in changed_files:
                passed_linters.pop(f, None)

            # Process each linter independently
            new_errors_by_linter: dict[str, set[str]] = {}
            combined_outputs: list[str] = []
            files_advancing: set[str] = set()  # Files that passed their linter and advance

            for linter, linter_error_files in errors_by_linter.items():
                # Compute this linter's changed files
                linter_changed = set(f for f in linter_error_files if f in changed_files)
                # Unchanged files already went to investigation - don't re-track them

                # Re-run this linter on its changed files
                if linter_changed:
                    _log(f"  {linter}: re-running on {len(linter_changed)} changed file(s)")
                    linter_success, linter_output = run_linters(
                        list(linter_changed),
                        worktree,
                        linters=[linter],
                    )

                    if linter_success:
                        # All changed files passed - they advance to remaining linters
                        _log(f"  {linter}: {len(linter_changed)} file(s) passed!")
                        files_advancing.update(linter_changed)
                        # Record that these files passed this linter
                        for f in linter_changed:
                            if f not in passed_linters:
                                passed_linters[f] = set()
                            passed_linters[f].add(linter)
                    else:
                        # Extract remaining errors for this linter
                        linter_new_errors = extract_errors_by_linter(linter_output)
                        files_with_errors = linter_new_errors.get(linter, set())
                        if files_with_errors:
                            new_errors_by_linter[linter] = files_with_errors
                            combined_outputs.append(linter_output)
                        # Files that passed advance, files with errors stay
                        files_that_passed = linter_changed - files_with_errors
                        files_advancing.update(files_that_passed)
                        # Record that passed files passed this linter
                        for f in files_that_passed:
                            if f not in passed_linters:
                                passed_linters[f] = set()
                            passed_linters[f].add(linter)

            # Files that passed their linter advance to remaining linters
            # Only run linters that files haven't passed yet
            if files_advancing:
                # Group files by linters they need (excluding passed linters)
                linters_needed: dict[str, set[str]] = {}  # linter -> files that need it
                for f in files_advancing:
                    file_passed = passed_linters.get(f, set())
                    for linter in LINTER_NAMES:
                        if linter not in file_passed:
                            if linter not in linters_needed:
                                linters_needed[linter] = set()
                            linters_needed[linter].add(f)

                if linters_needed:
                    _log(
                        f"Advancing {len(files_advancing)} file(s) to "
                        f"{len(linters_needed)} linter(s)..."
                    )
                    # Run each needed linter on its files
                    for linter, linter_files in linters_needed.items():
                        linter_success, linter_output = run_linters(
                            list(linter_files),
                            worktree,
                            linters=[linter],
                        )
                        if linter_success:
                            # Record that these files passed this linter
                            for f in linter_files:
                                if f not in passed_linters:
                                    passed_linters[f] = set()
                                passed_linters[f].add(linter)
                        else:
                            # Extract errors and track them
                            linter_errors = extract_errors_by_linter(linter_output)
                            files_with_errors = linter_errors.get(linter, set())
                            if files_with_errors:
                                if linter not in new_errors_by_linter:
                                    new_errors_by_linter[linter] = set()
                                new_errors_by_linter[linter].update(files_with_errors)
                                combined_outputs.append(linter_output)
                            # Files that passed this linter
                            files_that_passed = linter_files - files_with_errors
                            for f in files_that_passed:
                                if f not in passed_linters:
                                    passed_linters[f] = set()
                                passed_linters[f].add(linter)

            # Update errors_by_linter for next iteration
            errors_by_linter = new_errors_by_linter

            # Rebuild combined output for agent
            output = _combine_yaml_outputs(combined_outputs) if combined_outputs else "errors: []"

            if not errors_by_linter:
                _log("All lint errors fixed!")
                success = True
                break

        # Collect remaining investigation results
        investigation_reports: list[str] = []
        if investigation_futures:
            _log("\nWaiting for remaining investigations to complete...")
            for future, _inv_files, _inv_hashes in investigation_futures:
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
