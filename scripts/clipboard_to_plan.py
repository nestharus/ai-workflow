#!/usr/bin/env python3
"""Parse a Traycer AI implementation plan from the clipboard and write structured tasks."""

import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable


def is_wsl() -> bool:
    """Check if running in Windows Subsystem for Linux."""
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except FileNotFoundError:
        return False


def decode_output(data: bytes) -> str:
    """Decode bytes trying multiple encodings."""
    for encoding in ["utf-8", "utf-16", "latin-1"]:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def get_clipboard_macos() -> str:
    """Get clipboard content on macOS using pbpaste."""
    result = subprocess.run(["pbpaste"], capture_output=True, check=True)
    return decode_output(result.stdout)


def get_clipboard_windows() -> str:
    """Get clipboard content on native Windows using PowerShell."""
    result = subprocess.run(
        ["powershell", "-command", "Get-Clipboard"],
        capture_output=True,
        check=True,
    )
    return decode_output(result.stdout)


def get_clipboard_wsl() -> str:
    """Get clipboard content in WSL using PowerShell.exe."""
    result = subprocess.run(
        ["powershell.exe", "-command", "Get-Clipboard"],
        capture_output=True,
        check=True,
    )
    return decode_output(result.stdout)


def get_clipboard_linux() -> str:
    """Get clipboard content on Linux using xclip or xsel."""
    if shutil.which("xclip"):
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            check=True,
        )
        return decode_output(result.stdout)

    if shutil.which("xsel"):
        result = subprocess.run(
            ["xsel", "--clipboard", "--output"],
            capture_output=True,
            check=True,
        )
        return decode_output(result.stdout)

    raise FileNotFoundError("Neither xclip nor xsel found. Install one of them.")


def get_clipboard_content() -> str:
    """Get clipboard content based on the current platform."""
    system = platform.system()

    try:
        if system == "Darwin":
            return get_clipboard_macos()
        if system == "Windows":
            return get_clipboard_windows()
        if system == "Linux":
            if is_wsl():
                return get_clipboard_wsl()
            return get_clipboard_linux()
        print(f"Unsupported platform: {system}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error reading clipboard: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Clipboard tool not found: {e}", file=sys.stderr)
        sys.exit(1)


SECTION_HEADERS = {
    "observations": ("### Observations",),
    "approach": ("### Approach",),
    "reasoning": ("### Reasoning", "Reasoning"),
    "mermaid": ("## Mermaid Diagram",),
    "file_changes": ("## Proposed File Changes",),
}


def parse_plan_sections(content: str) -> dict[str, str]:
    """Extract known sections from the plan content."""
    sections: dict[str, str] = {}
    # Split into lines for scanning
    lines = content.splitlines()
    # Build map of header to index
    header_indices: dict[int, str] = {}
    for idx, line in enumerate(lines):
        for key, markers in SECTION_HEADERS.items():
            if any(line.strip().startswith(marker) for marker in markers):
                header_indices[idx] = key
    if not header_indices:
        return sections

    sorted_indices = sorted(header_indices.items())
    for (start_idx, key), next_item in zip(sorted_indices, sorted_indices[1:] + [(len(lines), "")]):
        end_idx = next_item[0]
        body = "\n".join(lines[start_idx + 1 : end_idx]).strip()
        sections[key] = body

    # Reasoning may appear as a paragraph without header after Approach
    if "reasoning" not in sections and "approach" in sections:
        approach_end_idx = max(idx for idx, k in header_indices.items() if k == "approach")
        next_indices = [idx for idx, k in header_indices.items() if idx > approach_end_idx]
        next_idx = min(next_indices) if next_indices else len(lines)
        trailing_lines = lines[approach_end_idx + 1 : next_idx]
        approach_text = sections["approach"].strip()
        if trailing_lines:
            try:
                blank_idx = trailing_lines.index("")
                candidate = "\n".join(trailing_lines[blank_idx + 1 :]).strip()
            except ValueError:
                candidate = "\n".join(trailing_lines).strip()
            if candidate and candidate != approach_text:
                sections["reasoning"] = candidate

    return sections


FILE_CHANGE_PATTERN = re.compile(r"^###\s+(.+)$", re.MULTILINE)


def extract_file_changes(file_changes_body: str) -> list[dict[str, str]]:
    """Parse the Proposed File Changes section into per-file tasks."""
    tasks: list[dict[str, str]] = []
    matches = list(FILE_CHANGE_PATTERN.finditer(file_changes_body))
    if not matches:
        return tasks

    for idx, file_match in enumerate(matches):
        filepath = file_match.group(1).strip()
        start = file_match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(file_changes_body)
        body = file_changes_body[start:end].strip()
        tasks.append({"filepath": filepath, "content": body})

    return tasks


def generate_outline(sections: dict[str, str], file_changes: list[dict[str, str]]) -> str:
    """Create outline content for outline.md."""
    lines: list[str] = []
    if observations := sections.get("observations"):
        lines.append("### Observations")
        lines.append(observations.strip())
        lines.append("")
    if approach := sections.get("approach"):
        lines.append("### Approach")
        lines.append(approach.strip())
        lines.append("")
    if reasoning := sections.get("reasoning"):
        lines.append("### Reasoning")
        lines.append(reasoning.strip())
        lines.append("")
    if mermaid := sections.get("mermaid"):
        lines.append("## Mermaid Diagram")
        lines.append(mermaid.strip())
        lines.append("")

    lines.append("## File Changes")
    if file_changes:
        for change in file_changes:
            lines.append(f"- {change['filepath']}")
    else:
        lines.append("- None detected")

    return "\n".join(lines).rstrip() + "\n"


def write_task_files(output_dir: Path, file_changes: list[dict[str, str]]) -> None:
    """Write individual task files named task_XXX.md with file-specific content."""
    for idx, change in enumerate(file_changes, start=1):
        filename = output_dir / f"task_{idx:03d}.md"
        parts: Iterable[str] = (
            [f"# {change['filepath']}", "", change["content"].strip()]
            if change["content"].strip()
            else [f"# {change['filepath']}"]
        )
        filename.write_text("\n".join(parts).rstrip() + "\n")


def main() -> None:
    """Read clipboard, parse plan, and write structured tasks."""
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    tasks_root = project_root / ".tasks"
    tasks_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamp_dir = tasks_root / timestamp
    timestamp_dir.mkdir(parents=True, exist_ok=True)

    content = get_clipboard_content()

    if not content.strip():
        print("Clipboard is empty", file=sys.stderr)
        sys.exit(1)

    sections = parse_plan_sections(content)
    file_changes_body = sections.get("file_changes", "")
    file_changes = extract_file_changes(file_changes_body) if file_changes_body else []

    if not any(marker in content for marker in SECTION_HEADERS["file_changes"]):
        print("Error: '## Proposed File Changes' section not found", file=sys.stderr)
        sys.exit(1)

    outline = generate_outline(sections, file_changes)
    (timestamp_dir / "outline.md").write_text(outline)

    if file_changes:
        write_task_files(timestamp_dir, file_changes)
    else:
        print("Warning: No file changes detected", file=sys.stderr)

    print(timestamp_dir)


if __name__ == "__main__":
    main()
