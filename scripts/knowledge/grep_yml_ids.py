"""Search for element IDs in YAML documentation files.

This module provides a command-line tool to search for specific IDs across YAML
documentation files, returning the file paths, IDs, and associated text content.
Useful for verifying coverage and finding where information is documented.

Usage:
    uv run knowledge.grep-yml-ids --id <element-id> [--path <directory>] \
      [--exact] [--output json|table]

Args:
    --id: The element ID to search for (required). Supports partial matching by default.
    --path: Directory to search in (default: docs/development/).
    --exact: Require exact ID match (default: partial/substring match).
    --output: Output format - 'table' (default) or 'json'.

Example:
    uv run knowledge.grep-yml-ids --id url.prefix --path docs/development/project
    uv run knowledge.grep-yml-ids --id validation --output json
    uv run knowledge.grep-yml-ids --id apperror.canonical-envelope --exact
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypedDict

import yaml

from scripts.dev.utils import REPO_ROOT

TEXT_FIELDS = ("text", "description", "summary", "title")
DEVELOPMENT_DIR = REPO_ROOT / "docs" / "development"


class MatchResult(TypedDict):
    """Result of an ID match in a YAML file."""

    file_path: str
    element_id: str
    text: str
    section_id: str | None
    item_type: str | None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for YAML ID search.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Search for element IDs in YAML documentation files.",
    )
    parser.add_argument(
        "--id",
        required=True,
        help="The element ID to search for. Supports partial matching by default.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEVELOPMENT_DIR,
        help="Directory to search in (default: docs/development/).",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Require exact ID match (default: partial/substring match).",
    )
    parser.add_argument(
        "--output",
        choices=["table", "json"],
        default="table",
        help="Output format - 'table' (default) or 'json'.",
    )
    return parser.parse_args(argv)


def _validate_yaml_result(
    result: Any,  # noqa: ANN401
    file_path: Path,
) -> dict[str, Any] | list[Any]:
    """Validate that the parsed YAML result is a dict or list.

    Args:
        result: The parsed result from yaml.safe_load().
        file_path: Path to the file for error messages.

    Returns:
        The validated result as a dict or list.

    Raises:
        TypeError: If the result is not a dict or list.
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return result
    relative_path = file_path.relative_to(REPO_ROOT)
    msg = f"Unexpected YAML structure in {relative_path}: expected dict or list"
    raise TypeError(msg)


def parse_yaml_file(file_path: Path) -> dict[str, Any] | list[Any]:
    """Parse a YAML file and return its decoded structure.

    Args:
        file_path: Path to the YAML file to parse.

    Returns:
        The parsed YAML structure as a Python dict or list.

    Raises:
        yaml.YAMLError: If the file contains invalid YAML syntax.
        FileNotFoundError: If the file does not exist.
        TypeError: If the parsed result is not a dict or list.
        ValueError: If parsing fails for other reasons.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        result = yaml.safe_load(content)
    except yaml.YAMLError:
        raise
    except FileNotFoundError:
        raise
    except Exception as exc:
        relative_path = file_path.relative_to(REPO_ROOT)
        msg = f"Failed to parse {relative_path}: {exc}"
        raise ValueError(msg) from exc
    else:
        return _validate_yaml_result(result, file_path)


def _extract_text_content(element: dict[str, Any]) -> str:
    """Extract text content from a YAML element's text fields.

    Args:
        element: A dictionary element from the parsed YAML structure.

    Returns:
        Concatenated text content from available text fields, or empty string.
    """
    text_parts: list[str] = []
    for field in TEXT_FIELDS:
        if field in element:
            value = element[field]
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip())
    return " | ".join(text_parts)


def _search_structure(
    data: Any,  # noqa: ANN401
    search_id: str,
    exact: bool,
    file_path: Path,
    current_section: str | None = None,
) -> list[MatchResult]:
    """Recursively search YAML structure for matching IDs.

    Args:
        data: The parsed YAML structure (dict, list, or primitive).
        search_id: The ID to search for.
        exact: Whether to require exact match.
        file_path: Path to the source file.
        current_section: Current section ID for context.

    Returns:
        List of match results found in this structure.
    """
    results: list[MatchResult] = []
    relative_path = file_path.relative_to(REPO_ROOT).as_posix()

    if isinstance(data, dict):
        # Track section context
        section_id = current_section
        if "id" in data and isinstance(data["id"], str) and ("items" in data or "index" in data):
            # Check if this is a section (has 'items' or 'index')
            section_id = data["id"]

        # Check if this element has a matching ID
        if "id" in data:
            element_id = data["id"]
            if isinstance(element_id, str):
                matches = (element_id == search_id) if exact else (search_id in element_id)
                if matches:
                    text_content = _extract_text_content(data)
                    item_type = data.get("type")
                    results.append(
                        MatchResult(
                            file_path=relative_path,
                            element_id=element_id,
                            text=text_content,
                            section_id=section_id if section_id != element_id else None,
                            item_type=item_type if isinstance(item_type, str) else None,
                        )
                    )

        # Recurse into child elements
        for _key, value in data.items():
            child_results = _search_structure(value, search_id, exact, file_path, section_id)
            results.extend(child_results)

    elif isinstance(data, list):
        for item in data:
            child_results = _search_structure(item, search_id, exact, file_path, current_section)
            results.extend(child_results)

    return results


def search_yaml_files(
    search_id: str,
    search_path: Path,
    exact: bool = False,
) -> list[MatchResult]:
    """Search YAML files for elements with matching IDs.

    Args:
        search_id: The ID to search for.
        search_path: Directory to search in.
        exact: Whether to require exact match.

    Returns:
        List of all matching results across all YAML files.
    """
    all_results: list[MatchResult] = []

    # Find all YAML files in the search path
    yaml_files = list(search_path.rglob("*.yml")) + list(search_path.rglob("*.yaml"))

    for yaml_file in sorted(yaml_files):
        try:
            data = parse_yaml_file(yaml_file)
            results = _search_structure(data, search_id, exact, yaml_file)
            all_results.extend(results)
        except Exception as exc:
            print(f"Warning: Failed to process {yaml_file}: {exc}", file=sys.stderr)

    return all_results


def format_table(results: list[MatchResult]) -> str:
    """Format results as a human-readable table.

    Args:
        results: List of match results.

    Returns:
        Formatted table string.
    """
    if not results:
        return "No matches found."

    lines = [f"Found {len(results)} match(es):\n"]

    for i, result in enumerate(results, 1):
        lines.append(f"[{i}] {result['element_id']}")
        lines.append(f"    File: {result['file_path']}")
        if result["section_id"]:
            lines.append(f"    Section: {result['section_id']}")
        if result["item_type"]:
            lines.append(f"    Type: {result['item_type']}")
        # Truncate long text
        text = result["text"]
        if len(text) > 200:
            text = text[:200] + "..."
        lines.append(f"    Text: {text}")
        lines.append("")

    return "\n".join(lines)


def format_json(results: list[MatchResult]) -> str:
    """Format results as JSON.

    Args:
        results: List of match results.

    Returns:
        JSON string.
    """
    return json.dumps(results, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the YAML ID search.

    Args:
        argv: Command line arguments.

    Returns:
        Exit code (0 for success with matches, 1 for no matches or errors).
    """
    args = parse_args(argv)

    search_path = args.path.resolve()
    if not search_path.exists() or not search_path.is_dir():
        print(
            f"Error: Specified path '{search_path}' does not exist or is not a directory.",
            file=sys.stderr,
        )
        return 1

    results = search_yaml_files(args.id, search_path, args.exact)

    if args.output == "json":
        print(format_json(results))
    else:
        print(format_table(results))

    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
