#!/usr/bin/env python3
"""Parse a Traycer AI implementation plan from the clipboard and write structured tasks.

When the --use-tasks-system flag is enabled, this script integrates with the .tasks
routing system to generate task metadata JSON files alongside the task markdown files.
Each agent defines its own `routing_thresholds` in its frontmatter to map prompt
character counts to runner/model combinations.
"""

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def is_wsl() -> bool:
    """Check if running in Windows Subsystem for Linux."""
    try:
        with open("/proc/version") as f:
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


def _count_task_chars(task_path: Path) -> int:
    """Count total characters in a task file.

    Args:
        task_path: Path to the task file.

    Returns:
        Number of characters in the file content.
    """
    content = task_path.read_text(encoding="utf-8")
    return len(content)


def _load_tasks_config(project_root: Path) -> dict[str, Any]:
    """Load and validate the .tasks.yaml configuration file.

    Args:
        project_root: Path to the project root directory.

    Returns:
        Parsed configuration dictionary with 'agents_dir' key.

    Raises:
        FileNotFoundError: If .tasks.yaml is not found in the project root.
        ValueError: If the YAML is invalid or missing required keys.
    """
    config_path = project_root / ".tasks.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {config_path}: {e}") from e

    if not isinstance(config, dict):
        raise ValueError(f"Expected dict in {config_path}, got {type(config).__name__}")

    required_keys = ["agents_dir"]
    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        raise ValueError(f"Missing required keys in {config_path}: {missing_keys}")

    return config


def _generate_task_metadata(
    task_path: Path,
    config_path: Path,
    agent_name: str = "implementor",
) -> dict[str, Any]:
    """Generate metadata for a task file based on agent's routing thresholds.

    Counts the characters in the task file and routes to the appropriate
    model and provider based on the agent's `routing_thresholds` from its
    frontmatter. When routing is not available or returns None, uses fallback
    values.

    Args:
        task_path: Path to the task markdown file.
        config_path: Path to the .tasks.yaml configuration file.
        agent_name: Name of the agent to assign (default: "implementor").

    Returns:
        Dictionary with keys: 'runner', 'agent', 'model', 'provider',
        'prompt_file', 'char_count'. If routing returns None or the agent
        has no routing_thresholds, uses fallback values:
        model="factory/gpt-5.1-high", provider="opencode".
    """
    from scripts.dev.agent_runner import AgentRunner

    char_count = _count_task_chars(task_path)

    # Load agent frontmatter to access routing_thresholds
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    # Resolve agents_dir the same way as AgentRunner.from_agent_name()
    agents_dir_path = Path(config["agents_dir"])
    agents_dir = (
        agents_dir_path if agents_dir_path.is_absolute() else config_path.parent / agents_dir_path
    )
    agent_path = agents_dir / f"{agent_name}.md"

    model = "factory/gpt-5.1-high"
    provider = "opencode"

    try:
        agent_config = AgentRunner.load_frontmatter(agent_path)
        routing_thresholds = agent_config.get("routing_thresholds")

        if routing_thresholds:
            routing_result = AgentRunner.select_from_routing_thresholds(
                routing_thresholds, char_count
            )
            if routing_result is not None:
                model, provider = routing_result
    except (FileNotFoundError, ValueError, KeyError):
        pass  # Use fallback values

    return {
        "runner": "agent.tasks",
        "agent": agent_name,
        "model": model,
        "provider": provider,
        "prompt_file": task_path.name,
        "char_count": char_count,
    }


def _write_task_metadata_files(
    output_dir: Path,
    task_metadata: list[dict[str, Any]],
) -> None:
    """Write JSON metadata files for each task.

    For each task, creates a corresponding task_XXX.json file containing
    agent assignment and routing information. Uses precomputed metadata to
    ensure consistency with the Agent Assignments section in outline.md.

    Args:
        output_dir: Directory containing task markdown files.
        task_metadata: Precomputed list of metadata dicts for each task.
    """
    for idx, metadata in enumerate(task_metadata, start=1):
        metadata_path = output_dir / f"task_{idx:03d}.json"
        with metadata_path.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            f.write("\n")


def parse_plan_sections(content: str) -> dict[str, str]:
    """Extract known sections from the plan content.

    Captures the intro text (everything before the first header) in
    sections["intro"].
    """
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

    # Extract intro text (everything before the first header)
    first_header_idx = min(header_indices.keys())
    if first_header_idx > 0:
        intro_text = "\n".join(lines[:first_header_idx]).strip()
        if intro_text:
            sections["intro"] = intro_text

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


def generate_outline(
    sections: dict[str, str],
    file_changes: list[dict[str, str]],
    task_metadata: list[dict[str, Any]] | None = None,
) -> str:
    """Create outline content for outline.md.

    Args:
        sections: Parsed sections from the plan content.
        file_changes: List of file change dicts with 'filepath' and 'content' keys.
        task_metadata: Optional list of metadata dicts for each task, containing
            'agent', 'model', 'provider', and 'char_count' keys. When provided,
            an "Agent Assignments" section is added to the outline.

    Returns:
        Formatted outline content as a string.
    """
    lines: list[str] = []
    if intro := sections.get("intro"):
        lines.append(intro)
        lines.append("")
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

    if task_metadata:
        lines.append("## Agent Assignments")
        for idx, metadata in enumerate(task_metadata, start=1):
            agent = metadata["agent"]
            model = metadata["model"]
            provider = metadata["provider"]
            char_count = metadata["char_count"]
            lines.append(f"- Task {idx:03d}: {agent} ({model}, {provider}) - {char_count} chars")
        lines.append("")

    lines.append("## File Changes")
    if file_changes:
        for change in file_changes:
            lines.append(f"- {change['filepath']}")
    else:
        lines.append("- None detected")

    return "\n".join(lines).rstrip() + "\n"


def write_task_files(output_dir: Path, file_changes: list[dict[str, str]], intro: str = "") -> None:
    """Write individual task files named task_XXX.md with file-specific content.

    Args:
        output_dir: Directory to write task files to.
        file_changes: List of file change dicts with 'filepath' and 'content' keys.
        intro: Optional intro text to include at the start of each task file.
    """
    for idx, change in enumerate(file_changes, start=1):
        filename = output_dir / f"task_{idx:03d}.md"
        parts: list[str] = []
        if intro:
            parts.append(intro)
            parts.append("")
        parts.append(f"# {change['filepath']}")
        if change["content"].strip():
            parts.append("")
            parts.append(change["content"].strip())
        filename.write_text("\n".join(parts).rstrip() + "\n")


def main() -> None:
    """Read clipboard, parse plan, and write structured tasks."""
    parser = argparse.ArgumentParser(
        description="Parse Traycer AI implementation plans from clipboard"
    )
    parser.add_argument(
        "--use-tasks-system",
        action="store_true",
        default=False,
        help="Enable .tasks integration: load agent routing from frontmatter, "
        "generate task metadata JSON files with agent/model/provider assignments, "
        "and include Agent Assignments section in outline.md",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent.parent

    store_root = project_root / ".tasks" / "store"
    store_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamp_dir = store_root / timestamp
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

    # Load tasks config if --use-tasks-system is enabled
    config_path: Path | None = None
    if args.use_tasks_system:
        try:
            _load_tasks_config(project_root)
            config_path = project_root / ".tasks.yaml"
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Generate initial outline without task metadata
    task_metadata: list[dict[str, Any]] | None = None
    outline = generate_outline(sections, file_changes, task_metadata)
    (timestamp_dir / "outline.md").write_text(outline)

    if file_changes:
        intro = sections.get("intro", "")
        write_task_files(timestamp_dir, file_changes, intro)

        # Generate metadata after task files are written (so we can count chars)
        if args.use_tasks_system and config_path is not None:
            task_metadata = [
                _generate_task_metadata(timestamp_dir / f"task_{idx:03d}.md", config_path)
                for idx in range(1, len(file_changes) + 1)
            ]
            # Write JSON files using precomputed metadata (ensures consistency
            # with Agent Assignments section in outline.md)
            _write_task_metadata_files(timestamp_dir, task_metadata)

            # Regenerate outline with task metadata
            outline = generate_outline(sections, file_changes, task_metadata)
            (timestamp_dir / "outline.md").write_text(outline)
    else:
        print("Warning: No file changes detected", file=sys.stderr)

    print(timestamp_dir)


if __name__ == "__main__":
    main()
