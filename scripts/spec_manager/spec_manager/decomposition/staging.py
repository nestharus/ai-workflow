"""Staging file operations for spec decomposition."""

from __future__ import annotations

import re
from pathlib import Path


def create_staging_file(source: Path, staging_dir: Path) -> Path:
    """Create a staging copy of a source file.

    Args:
        source: Original source file path
        staging_dir: Directory to place staged file

    Returns:
        Path to the staged file
    """
    staged_name = f"{source.stem}_staged.md"
    staged_path = staging_dir / staged_name

    content = source.read_text()
    header = f"<!-- STAGED FROM: {source} -->\n\n"
    staged_path.write_text(header + content)

    return staged_path


def _get_header_offset(lines: list[str]) -> int:
    """Get the number of header lines to skip."""
    # Staging/original/investigation files created by this tool begin with one or more
    # HTML comment lines followed by at least one blank line. We skip that prefix so
    # that line numbers remain stable and refer only to the underlying spec content.
    i = 0
    while i < len(lines) and lines[i].startswith("<!--"):
        i += 1

    # Only treat this as a header if we actually saw comment lines.
    if i == 0:
        return 0

    while i < len(lines) and lines[i].strip() == "":
        i += 1

    return i


def embed_id_at_line(staging_file: Path, line_number: int, id_str: str) -> None:
    """Embed an ID marker at a specific line in a staging file.

    The ID is inserted at the end of the line in the format: `[ID]`

    Args:
        staging_file: Path to staging file
        line_number: 1-indexed line number to mark
        id_str: ID to embed (e.g., "E-001")
    """
    content = staging_file.read_text()
    lines = content.split("\n")
    header_lines = _get_header_offset(lines)
    actual_line_idx = header_lines + line_number - 1

    if 0 <= actual_line_idx < len(lines):
        current_line = lines[actual_line_idx]
        # Don't duplicate IDs
        if f"[{id_str}]" not in current_line:
            lines[actual_line_idx] = f"{current_line} [{id_str}]"

    staging_file.write_text("\n".join(lines))


def remove_line(staging_file: Path, line_number: int, note: str | None = None) -> str:
    """Remove a line from the staging file and return its content.

    The line is replaced with a marker showing it was extracted.

    Args:
        staging_file: Path to staging file
        line_number: 1-indexed line number to remove

    Returns:
        The content that was at that line
    """
    content = staging_file.read_text()
    lines = content.split("\n")
    header_lines = _get_header_offset(lines)
    actual_line_idx = header_lines + line_number - 1

    removed_content = ""
    if 0 <= actual_line_idx < len(lines):
        removed_content = lines[actual_line_idx]
        # Replace with extraction marker (keeps line numbers stable for debugging)
        suffix = f" ({note})" if note else ""
        lines[actual_line_idx] = f"<!-- EXTRACTED: {line_number}{suffix} -->"

    staging_file.write_text("\n".join(lines))
    return removed_content


def remove_lines(staging_file: Path, line_numbers: list[int], note: str | None = None) -> list[str]:
    """Remove multiple lines from the staging file.

    Args:
        staging_file: Path to staging file
        line_numbers: List of 1-indexed line numbers to remove

    Returns:
        List of contents that were at those lines
    """
    content = staging_file.read_text()
    lines = content.split("\n")
    header_lines = _get_header_offset(lines)

    removed = []
    for line_number in sorted(line_numbers):
        actual_line_idx = header_lines + line_number - 1
        if 0 <= actual_line_idx < len(lines):
            removed.append(lines[actual_line_idx])
            suffix = f" ({note})" if note else ""
            lines[actual_line_idx] = f"<!-- EXTRACTED: {line_number}{suffix} -->"

    staging_file.write_text("\n".join(lines))
    return removed


def get_remaining_lines(staging_file: Path) -> list[dict]:
    """Get all non-extracted, non-empty lines remaining in the staging file.

    Returns:
        List of {"line": int, "text": str} for each remaining line
    """
    content = staging_file.read_text()
    lines = content.split("\n")
    header_lines = _get_header_offset(lines)

    remaining = []
    for i, line in enumerate(lines[header_lines:], start=1):
        # Skip all markers
        if line.startswith("<!-- EXTRACTED:") or "<!-- SNIPPET:" in line:
            continue
        # Skip internal file-boundary markers used by combined investigation staging
        if line.startswith("<!-- FILE:"):
            continue
        if not line.strip():
            continue
        # Skip markdown formatting only
        if line.strip() == "---":
            continue
        if line.strip().startswith("```"):
            continue
        remaining.append({"line": i, "text": line})

    return remaining


def format_content_for_agent(staging_file: Path) -> str:
    """Format staging file content for agent consumption.

    Lines are formatted as: `<line_number>: <text>`
    Skips extracted/marked lines.

    Args:
        staging_file: Path to staging file

    Returns:
        Formatted content string for agent input
    """
    remaining = get_remaining_lines(staging_file)
    formatted_lines = [f"{item['line']}: {item['text']}" for item in remaining]
    return "\n".join(formatted_lines)


def is_file_empty(staging_file: Path) -> bool:
    """Check if a staging file has been fully extracted.

    Returns:
        True if no meaningful content remains
    """
    remaining = get_remaining_lines(staging_file)
    return len(remaining) == 0


def get_line_content(staging_file: Path, line_number: int) -> str:
    """Get content at a specific line number.

    Args:
        staging_file: Path to staging file
        line_number: 1-indexed line number

    Returns:
        Content at that line
    """
    content = staging_file.read_text()
    lines = content.split("\n")
    header_lines = _get_header_offset(lines)
    actual_line_idx = header_lines + line_number - 1

    if 0 <= actual_line_idx < len(lines):
        return lines[actual_line_idx]
    return ""


def get_embedded_ids(staging_file: Path) -> dict[int, list[str]]:
    """Get all embedded IDs and their line numbers.

    Returns:
        Dict mapping line numbers to list of IDs at that line
    """
    content = staging_file.read_text()
    lines = content.split("\n")
    header_lines = _get_header_offset(lines)

    result = {}
    for i, line in enumerate(lines[header_lines:], start=1):
        ids = re.findall(r"\[([ERCXOSF]-\d{3})\]", line)
        if ids:
            result[i] = ids

    return result


def mark_relation_snippet(
    staging_file: Path,
    line_number: int,
    snippet_id: str,
    source_entity_id: str,
) -> None:
    """Mark a line as a relation snippet (don't remove yet).

    The line is marked with: <!-- SNIPPET: S-xxx for E-yyy -->

    Args:
        staging_file: Path to staging file
        line_number: 1-indexed line number
        snippet_id: Snippet ID (e.g., "S-001")
        source_entity_id: Entity this snippet relates from (e.g., "E-001")
    """
    content = staging_file.read_text()
    lines = content.split("\n")
    header_lines = _get_header_offset(lines)
    actual_line_idx = header_lines + line_number - 1

    if 0 <= actual_line_idx < len(lines):
        current_line = lines[actual_line_idx]
        # Don't mark if already marked or extracted
        if "<!-- SNIPPET:" not in current_line and "<!-- EXTRACTED:" not in current_line:
            lines[actual_line_idx] = (
                f"{current_line} <!-- SNIPPET: {snippet_id} for {source_entity_id} -->"
            )

    staging_file.write_text("\n".join(lines))


def get_staged_from_path(staging_file: Path) -> str | None:
    """Extract the original source path from a staged file header (if present)."""
    content = staging_file.read_text()
    for line in content.split("\n")[:10]:
        if line.startswith("<!-- STAGED FROM:"):
            return line.split("STAGED FROM:", 1)[1].strip().removesuffix("-->").strip()
        if line.startswith("<!-- ORIGINAL FROM:"):
            return line.split("ORIGINAL FROM:", 1)[1].strip().removesuffix("-->").strip()
    return None


def get_marked_snippets(staging_file: Path) -> list[dict]:
    """Get all lines marked as relation snippets.

    Returns:
        List of {"line": int, "text": str, "snippet_id": str, "source_entity": str}
    """
    content = staging_file.read_text()
    lines = content.split("\n")
    header_lines = _get_header_offset(lines)

    snippets = []
    pattern = r"^(.+?)\s*<!-- SNIPPET: (S-\d{3}) for (E-\d{3}) -->$"

    for i, line in enumerate(lines[header_lines:], start=1):
        match = re.match(pattern, line)
        if match:
            snippets.append(
                {
                    "line": i,
                    "text": match.group(1).strip(),
                    "snippet_id": match.group(2),
                    "source_entity": match.group(3),
                }
            )

    return snippets


def collect_and_remove_snippets(staging_file: Path) -> list[dict]:
    """Collect all marked snippets and remove them from staging.

    Returns:
        List of snippet data that was removed
    """
    content = staging_file.read_text()
    lines = content.split("\n")
    header_lines = _get_header_offset(lines)

    snippets = []
    pattern = r"^(.+?)\s*<!-- SNIPPET: (S-\d{3}) for (E-\d{3}) -->$"

    for i, line in enumerate(lines[header_lines:], start=1):
        match = re.match(pattern, line)
        if match:
            snippets.append(
                {
                    "line": i,
                    "text": match.group(1).strip(),
                    "snippet_id": match.group(2),
                    "source_entity": match.group(3),
                }
            )
            # Mark as extracted
            actual_idx = header_lines + i - 1
            lines[actual_idx] = f"<!-- EXTRACTED: {i} (snippet {match.group(2)}) -->"

    staging_file.write_text("\n".join(lines))
    return snippets


def write_snippet_staging_file(
    workspace: Path,
    source_entity_id: str,
    source_entity_name: str,
    snippets: list[dict],
    source_file: str,
) -> Path:
    """Write collected snippets to relation staging file.

    Args:
        workspace: Workspace directory
        source_entity_id: Entity ID these snippets relate from
        source_entity_name: Entity name
        snippets: List of snippet dicts
        source_file: Original source file name

    Returns:
        Path to created snippet staging file
    """
    staging_dir = workspace / "relation_staging"
    staging_dir.mkdir(exist_ok=True)

    snippet_file = staging_dir / f"{source_entity_id}_snippets.md"

    lines = [
        f"# Relation Snippets for {source_entity_id} ({source_entity_name})",
        "",
        f"Source: {source_file}",
        "",
    ]

    for snippet in snippets:
        lines.extend(
            [
                f"## {snippet['snippet_id']}",
                f"- **Line**: {snippet['line']}",
                f"- **File**: {source_file}",
                f"> {snippet['text']}",
                "",
            ]
        )

    # Append if file exists, otherwise create
    if snippet_file.exists():
        existing = snippet_file.read_text()
        snippet_file.write_text(existing + "\n" + "\n".join(lines))
    else:
        snippet_file.write_text("\n".join(lines))

    return snippet_file
