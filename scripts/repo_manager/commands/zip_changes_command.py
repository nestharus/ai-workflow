"""Orchestrate getting changed files and creating a zip archive.

This module combines the functionality of getting changed files and
creating a zip archive, storing the result in .tmp/ with a unique name.
"""

import sys
from pathlib import Path

from scripts.repo_manager.commands.get_changed_files_command import (
    GitCommandError,
    get_all_changed_files,
)
from scripts.repo_manager.commands.zip_files_command import (
    create_zip_archive,
    generate_unique_filename,
)


def zip_changes_command(root: Path, output_dir: Path) -> int:
    """Create a zip archive of all changed files and print the zip file path.

    This orchestrates getting all changed files (staged, unstaged, untracked)
    and creating a zip archive stored in .tmp/ with a unique name.

    Args:
        root: Root path for git operations and relative file paths.
        output_dir: Directory where the zip file will be created (default: .tmp/).

    Returns:
        Exit code (0 for success, 1 for failure). Prints the full path to the
        created zip file on success.
    """
    try:
        files = get_all_changed_files(root)
    except GitCommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not files:
        print("No changed files found.", file=sys.stderr)
        return 1

    # Generate unique output filename
    filename = generate_unique_filename()
    output_path = root / output_dir / filename

    # Create the zip archive
    try:
        create_zip_archive(root, files, output_path)
    except OSError as e:
        print(f"Error creating zip archive: {e}", file=sys.stderr)
        return 1

    # Output the full path to the zip file
    print(output_path.resolve())

    return 0
