"""Create a zip archive from a list of files.

This module zips up a list of filenames while maintaining proper folder structure.
Each file is placed in the zip archive based on its path relative to the root path.
"""

import secrets
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def generate_unique_filename() -> str:
    """Generate a unique filename for the zip archive.

    Returns:
        A unique filename string with timestamp and random suffix.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    random_suffix = secrets.token_hex(4)
    return f"changes_{timestamp}_{random_suffix}.zip"


def create_zip_archive(
    root: Path,
    files: list[Path],
    output_path: Path,
) -> None:
    """Create a zip archive containing the specified files.

    Each file is added to the archive with its path relative to the root directory,
    maintaining the proper folder structure.

    Args:
        root: Root path for resolving relative file paths.
        files: List of file paths to include in the archive.
        output_path: Path for the output zip file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in files:
            try:
                arcname = str(file_path.relative_to(root))
                zipf.write(file_path, arcname)
            except ValueError:
                # File is not under root path, use absolute path
                zipf.write(file_path, str(file_path))


def zip_files_command(root: Path, output_dir: Path, files: list[Path]) -> int:
    """Create a zip archive from a list of files.

    Args:
        root: Root path for resolving relative file paths.
        output_dir: Directory where the zip file will be created.
        files: List of file paths to include in the archive.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    # Filter to existing files only
    existing_files = [f for f in files if f.is_file()]

    if not existing_files:
        print("No valid files to zip.", file=sys.stderr)
        return 1

    # Generate unique output filename
    filename = generate_unique_filename()
    output_path = output_dir / filename

    # Create the zip archive
    try:
        create_zip_archive(root, existing_files, output_path)
    except OSError as e:
        print(f"Error creating zip archive: {e}", file=sys.stderr)
        return 1

    # Output the full path to the zip file
    print(output_path.resolve())

    return 0
