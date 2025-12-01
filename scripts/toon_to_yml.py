"""Convert all TOON files to YAML format.

This script finds all .toon files in the docs/ directory, decodes them using
the toon_format library, and writes the equivalent YAML files alongside them.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import toon_format
import yaml
from toon_format import DecodeOptions, ToonDecodeError

from scripts.utils import REPO_ROOT


class IndentedDumper(yaml.SafeDumper):
    """Custom YAML dumper with proper sequence indentation."""

    pass


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Represent strings, using literal style for multiline content."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


IndentedDumper.add_representer(str, _str_representer)


def _increase_indent(
    dumper: yaml.SafeDumper,
    flow: bool = False,
    indentless: bool = False,
) -> None:
    """Override increase_indent to always indent sequences."""
    yaml.SafeDumper.increase_indent(dumper, flow, indentless=False)


IndentedDumper.increase_indent = _increase_indent  # type: ignore[assignment]


def dump_yaml(data: Any) -> str:  # noqa: ANN401
    """Dump data to YAML with proper indentation.

    Args:
        data: The data structure to serialize.

    Returns:
        YAML string with 2-space indentation and indented sequences.
    """
    return yaml.dump(
        data,
        Dumper=IndentedDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
        indent=2,
    )


TOON_FILE_PATTERN = "**/*.toon"
EXCLUDED_DIRS = {
    ".venv",
    ".venv2",
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "build",
    "dist",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for TOON to YAML conversion.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace with path and verbose attributes.
    """
    parser = argparse.ArgumentParser(
        description="Convert all TOON files to YAML format.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=REPO_ROOT / "docs",
        help="Root path to search for TOON files (default: docs/).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output showing each file as it is converted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be converted without writing files.",
    )
    return parser.parse_args(argv)


def find_toon_files(root_path: Path) -> list[Path]:
    """Discover all TOON files under the given path, excluding common directories.

    Args:
        root_path: Root directory to search for TOON files.

    Returns:
        Sorted list of Path objects pointing to .toon files.
    """
    files = [
        path
        for path in root_path.rglob(TOON_FILE_PATTERN)
        if path.is_file() and not any(excluded in path.parts for excluded in EXCLUDED_DIRS)
    ]
    return sorted(files)


def convert_toon_to_yaml(toon_path: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Convert a single TOON file to YAML format.

    Args:
        toon_path: Path to the TOON file to convert.
        dry_run: If True, do not write the output file.

    Returns:
        A tuple of (success, message). Message contains the output path or error.
    """
    yaml_path = toon_path.with_suffix(".yml")

    try:
        content = toon_path.read_text(encoding="utf-8")
        data = toon_format.decode(content, DecodeOptions(strict=True))
    except ToonDecodeError as exc:
        return (False, f"TOON decode error: {exc}")
    except Exception as exc:
        return (False, f"Error reading file: {exc}")

    try:
        yaml_content = dump_yaml(data)
    except Exception as exc:
        return (False, f"YAML serialization error: {exc}")

    if not dry_run:
        try:
            yaml_path.write_text(yaml_content, encoding="utf-8")
        except Exception as exc:
            return (False, f"Error writing file: {exc}")

    relative_yaml = yaml_path.relative_to(REPO_ROOT)
    return (True, str(relative_yaml))


def main() -> int:
    """Execute TOON to YAML conversion and return a process exit code.

    Returns:
        0 if all files are converted successfully, 1 if any conversion fails.
    """
    args = parse_args()
    root_path = args.path.resolve()
    toon_files = find_toon_files(root_path)

    if not toon_files:
        print(f"No TOON files found in {root_path}.")
        return 0

    action = "Would convert" if args.dry_run else "Converting"
    print(f"{action} {len(toon_files)} TOON file(s)...")

    errors: list[str] = []
    converted: int = 0

    for toon_path in toon_files:
        relative_toon = toon_path.relative_to(REPO_ROOT)
        success, message = convert_toon_to_yaml(toon_path, dry_run=args.dry_run)

        if success:
            converted += 1
            if args.verbose:
                print(f"  {relative_toon} -> {message}")
        else:
            errors.append(f"{relative_toon}: {message}")

    if errors:
        print("\nConversion errors:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)

    status = "Would convert" if args.dry_run else "Converted"
    print(f"\n{status} {converted}/{len(toon_files)} files successfully.")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
