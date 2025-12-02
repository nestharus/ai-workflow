"""Lint YAML documentation files for schema compliance.

Validates that YAML documentation files (identified by having `doc_id` at root)
follow the schema defined in general.yaml.schema-guidelines.yml:

- Document-level: `doc_id`, `title`, `sections` required at root
- Section-level: Root elements of `sections` list must have `id` field
- Child elements: IDs are optional for children (no lint error if missing)

Usage:
    uv run lint-yaml-docs [--path <directory>] [--fix]

Args:
    --path: Directory to search for YAML docs (default: docs/).
    --fix: Auto-fix missing section IDs by generating them from content.

Example:
    uv run lint-yaml-docs --path docs/development/
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypedDict

import yaml

from scripts.dev.utils import REPO_ROOT

# Required fields at document root level for documentation files
REQUIRED_ROOT_FIELDS = ("doc_id", "title", "sections")

# Optional fields that must be lists if present
LIST_TYPE_FIELDS = ("domain", "primary_runtime_references", "related_docs", "external_references")


class LintError(TypedDict):
    """A single lint error for a YAML documentation file."""

    file_path: str
    line: int | None
    error_type: str
    message: str


class LintResult(TypedDict):
    """Lint results for a single file."""

    file_path: str
    is_doc_file: bool
    errors: list[LintError]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for YAML documentation linting.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Lint YAML documentation files for schema compliance.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=REPO_ROOT / "docs",
        help="Directory to search for YAML docs (default: docs/).",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Auto-fix missing section IDs by generating them from content.",
    )
    return parser.parse_args(argv)


def is_documentation_file(data: dict[str, Any]) -> bool:
    """Check if a YAML structure represents a documentation file.

    A file is considered a documentation file if it has `doc_id` at the root level.

    Args:
        data: Parsed YAML data (must be a dict).

    Returns:
        True if this is a documentation file, False otherwise.
    """
    return "doc_id" in data


def _generate_id_from_title(title: str) -> str:
    """Generate a kebab-case ID from a title string.

    Args:
        title: The title to convert.

    Returns:
        A kebab-case ID suitable for use as a section ID.
    """
    # Convert to lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    # Remove leading/trailing hyphens
    slug = slug.strip("-")
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    return slug or "section"


def validate_document_root(
    data: dict[str, Any],
    file_path: str,
) -> list[LintError]:
    """Validate document-level required fields and type constraints.

    Args:
        data: Parsed YAML data.
        file_path: Relative path to the file.

    Returns:
        List of lint errors for missing required fields or type mismatches.
    """
    errors: list[LintError] = []

    for field in REQUIRED_ROOT_FIELDS:
        if field not in data:
            errors.append(
                LintError(
                    file_path=file_path,
                    line=None,
                    error_type="missing_required_field",
                    message=f"Missing required field '{field}' at document root",
                )
            )

    # Validate sections is a list if present
    if "sections" in data and not isinstance(data["sections"], list):
        errors.append(
            LintError(
                file_path=file_path,
                line=None,
                error_type="invalid_type",
                message="'sections' must be a list",
            )
        )

    # Validate optional list-type fields have correct type if present
    for field in LIST_TYPE_FIELDS:
        if field in data and not isinstance(data[field], list):
            errors.append(
                LintError(
                    file_path=file_path,
                    line=None,
                    error_type="invalid_type",
                    message=f"'{field}' must be a list, got {type(data[field]).__name__}",
                )
            )

    return errors


def validate_sections(
    sections: list[Any],
    file_path: str,
) -> list[LintError]:
    """Validate that root elements of sections have IDs.

    Args:
        sections: The sections list from the document.
        file_path: Relative path to the file.

    Returns:
        List of lint errors for sections missing IDs.
    """
    errors: list[LintError] = []

    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            errors.append(
                LintError(
                    file_path=file_path,
                    line=None,
                    error_type="invalid_section_type",
                    message=f"Section at index {index} must be a dict, got {type(section).__name__}",
                )
            )
            continue

        if "id" not in section:
            # Try to provide helpful context
            title = section.get("title", "")
            hint = f" (title: '{title}')" if title else ""
            errors.append(
                LintError(
                    file_path=file_path,
                    line=None,
                    error_type="missing_section_id",
                    message=f"Section at index {index}{hint} is missing required 'id' field",
                )
            )

    return errors


def lint_yaml_file(file_path: Path) -> LintResult:
    """Lint a single YAML file for documentation schema compliance.

    Args:
        file_path: Path to the YAML file.

    Returns:
        LintResult with file info and any errors found.
    """
    relative_path = file_path.relative_to(REPO_ROOT).as_posix()
    result = LintResult(
        file_path=relative_path,
        is_doc_file=False,
        errors=[],
    )

    try:
        content = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        result["errors"].append(
            LintError(
                file_path=relative_path,
                line=None,
                error_type="yaml_parse_error",
                message=f"Failed to parse YAML: {exc}",
            )
        )
        return result
    except Exception as exc:
        result["errors"].append(
            LintError(
                file_path=relative_path,
                line=None,
                error_type="read_error",
                message=f"Failed to read file: {exc}",
            )
        )
        return result

    # Skip non-dict files (lists, scalars)
    if not isinstance(data, dict):
        return result

    # Check if this is a documentation file
    if not is_documentation_file(data):
        return result

    result["is_doc_file"] = True

    # Validate document root
    root_errors = validate_document_root(data, relative_path)
    result["errors"].extend(root_errors)

    # Validate sections if present and is a list
    if "sections" in data and isinstance(data["sections"], list):
        section_errors = validate_sections(data["sections"], relative_path)
        result["errors"].extend(section_errors)

    return result


def find_yaml_files(search_path: Path) -> list[Path]:
    """Find all YAML files in a directory tree.

    Args:
        search_path: Root directory to search.

    Returns:
        Sorted list of YAML file paths.
    """
    yaml_files = list(search_path.rglob("*.yml")) + list(search_path.rglob("*.yaml"))
    return sorted(yaml_files)


def lint_directory(search_path: Path) -> tuple[list[LintResult], int, int]:
    """Lint all YAML documentation files in a directory.

    Args:
        search_path: Directory to search for YAML files.

    Returns:
        Tuple of (results list, doc file count, error count).
    """
    yaml_files = find_yaml_files(search_path)
    results: list[LintResult] = []
    doc_count = 0
    error_count = 0

    for yaml_file in yaml_files:
        result = lint_yaml_file(yaml_file)
        results.append(result)

        if result["is_doc_file"]:
            doc_count += 1
            error_count += len(result["errors"])

    return results, doc_count, error_count


def format_errors(results: list[LintResult]) -> str:
    """Format lint errors for display.

    Args:
        results: List of lint results.

    Returns:
        Formatted error string.
    """
    lines: list[str] = []

    for result in results:
        if not result["errors"]:
            continue

        lines.append(f"\n{result['file_path']}:")
        for error in result["errors"]:
            line_info = f":{error['line']}" if error["line"] else ""
            lines.append(f"  {error['error_type']}{line_info}: {error['message']}")

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the YAML documentation linter.

    Args:
        argv: Command line arguments.

    Returns:
        Exit code (0 for success, 1 for errors found).
    """
    args = parse_args(argv)

    search_path = args.path.resolve()
    if not search_path.exists() or not search_path.is_dir():
        print(
            f"Error: Specified path '{search_path}' does not exist or is not a directory.",
            file=sys.stderr,
        )
        return 1

    results, doc_count, error_count = lint_directory(search_path)

    if error_count > 0:
        print(f"Found {error_count} error(s) in {doc_count} documentation file(s):")
        print(format_errors(results))
        return 1

    print(f"Checked {doc_count} documentation file(s). No errors found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
