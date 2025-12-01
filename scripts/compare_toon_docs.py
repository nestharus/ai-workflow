"""Compare TOON documents by extracting IDs and their associated text content.

This module provides utilities for parsing TOON files and extracting ID-to-text
mappings, enabling comparison of document content across different versions or files.
"""

from pathlib import Path
from typing import Any

import toon_format
from toon_format import DecodeOptions, ToonDecodeError

from scripts.utils import REPO_ROOT

TEXT_FIELDS = ("text", "description", "summary", "title")

ToonValue = str | int | float | bool | None | list["ToonValue"] | dict[str, "ToonValue"]
ToonStructure = dict[str, ToonValue] | list[ToonValue]


def _validate_toon_result(
    result: str | int | float | list[Any] | dict[str, Any] | None,
    file_path: Path,
) -> ToonStructure:
    """Validate that the decoded TOON result is a dict or list.

    Args:
        result: The decoded result from toon_format.decode().
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
    msg = f"Unexpected TOON structure in {relative_path}: expected dict or list"
    raise TypeError(msg)


def parse_toon_file(file_path: Path) -> ToonStructure:
    """Parse a TOON file and return its decoded structure.

    Reads the file content and decodes it using the toon_format library
    with strict validation enabled.

    Args:
        file_path: Path to the TOON file to parse.

    Returns:
        The decoded TOON structure as a Python dict or list.

    Raises:
        ToonDecodeError: If the file contains invalid TOON syntax.
        FileNotFoundError: If the file does not exist.
        TypeError: If the decoded result is not a dict or list.
        ValueError: If decoding fails for other reasons.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        result = toon_format.decode(content, DecodeOptions(strict=True))
    except ToonDecodeError:
        raise
    except FileNotFoundError:
        raise
    except Exception as exc:
        relative_path = file_path.relative_to(REPO_ROOT)
        msg = f"Failed to parse {relative_path}: {exc}"
        raise ValueError(msg) from exc
    else:
        return _validate_toon_result(result, file_path)


def _extract_text_content(element: dict[str, ToonValue]) -> str:
    """Extract text content from a TOON element's text fields.

    Checks text fields in priority order and concatenates all non-empty
    values found.

    Args:
        element: A dictionary element from the decoded TOON structure.

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


def extract_ids_and_text(
    data: ToonValue,
    parent_path: str = "",
) -> dict[str, str]:
    """Recursively extract IDs and their associated text from a TOON structure.

    Traverses the decoded TOON structure to find all elements with an 'id' field
    and extracts their text content from associated fields like 'text',
    'description', 'summary', or 'title'.

    Args:
        data: The decoded TOON structure (dict, list, or primitive).
        parent_path: Path string for debugging purposes (tracks traversal path).

    Returns:
        Dictionary mapping element IDs to their associated text content.
    """
    result: dict[str, str] = {}

    if isinstance(data, dict):
        if "id" in data:
            element_id = data["id"]
            if isinstance(element_id, str):
                text_content = _extract_text_content(data)
                result[element_id] = text_content

        for key, value in data.items():
            child_path = f"{parent_path}.{key}" if parent_path else key
            child_results = extract_ids_and_text(value, child_path)
            result.update(child_results)

    elif isinstance(data, list):
        for index, item in enumerate(data):
            child_path = f"{parent_path}[{index}]"
            child_results = extract_ids_and_text(item, child_path)
            result.update(child_results)

    return result
