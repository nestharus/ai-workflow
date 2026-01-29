#!/usr/bin/env python3
"""Generate .code/config.toml from source files.

Source structure:
    .code/src/
    ├── settings.toml              # Global settings (model, projects, etc.)
    ├── agents.toml                # [[agents]] definitions
    └── commands/
        └── <command-name>.toml    # [[subagents.commands]] with file refs

Command TOML files can reference instruction files:
    orchestrator_instructions_file = "agents/prd/chunk-refiner.md"
    agent_instructions_file = "agents/prd/chunk-refiner-agent.md"

These paths are relative to .code/ directory.

Usage:
    uv run code-config
    uv run code-config --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found]

import tomli_w


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file and return its contents.

    Args:
        path: Path to the TOML file to load.

    Returns:
        The parsed TOML contents as a dictionary.

    Raises:
        ValueError: If the file cannot be read or contains invalid TOML.
    """
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except OSError as err:
        msg = f"Failed to read TOML file: {path}"
        raise ValueError(msg) from err
    except tomllib.TOMLDecodeError as err:
        msg = f"Invalid TOML syntax in file: {path}"
        raise ValueError(msg) from err


def resolve_instruction_file(base_dir: Path, file_ref: str) -> str:
    """Resolve an instruction file reference and return its content.

    Args:
        base_dir: The base directory for resolving file references.
        file_ref: A relative path to the instruction file.

    Returns:
        The content of the instruction file, stripped of leading/trailing whitespace.

    Raises:
        ValueError: If the file reference escapes the base directory (path traversal).
        FileNotFoundError: If the instruction file does not exist.
    """
    resolved_base = base_dir.resolve()
    resolved_path = (base_dir / file_ref).resolve(strict=False)

    # Prevent path traversal by verifying resolved path is under base_dir
    try:
        resolved_path.relative_to(resolved_base)
    except ValueError as e:
        msg = f"Path traversal detected: {file_ref!r} escapes base directory {base_dir}"
        raise ValueError(msg) from e

    if not resolved_path.exists():
        msg = f"Instruction file not found: {resolved_path}"
        raise FileNotFoundError(msg)
    return resolved_path.read_text(encoding="utf-8").strip()


def _resolve_and_merge_instructions(
    command: dict[str, Any],
    code_dir: Path,
    file_key: str,
    content_key: str,
) -> None:
    """Resolve an instruction file and merge it with existing content.

    Args:
        command: The command dictionary to modify in place.
        code_dir: The base directory for resolving file references.
        file_key: The key for the file reference (e.g., "orchestrator_instructions_file").
        content_key: The key for the content (e.g., "orchestrator_instructions").

    Raises:
        ValueError: If the existing content_key value is not a string or None.
    """
    if file_key not in command:
        return

    file_ref = command.pop(file_key)
    content = resolve_instruction_file(code_dir, file_ref)
    existing = command.get(content_key, "")

    # Defensive type check: ensure existing content is a string
    if existing is not None and not isinstance(existing, str):
        msg = (
            f"Config key {content_key!r} must be a string, "
            f"got {type(existing).__name__}: {existing!r}"
        )
        raise ValueError(msg)

    if existing:
        command[content_key] = f"{content}\n\n{existing}"
    else:
        command[content_key] = content


def process_command(
    command_path: Path,
    code_dir: Path,
) -> dict[str, Any]:
    """Process a command TOML file, resolving any instruction file references."""
    command = load_toml(command_path)

    _resolve_and_merge_instructions(
        command, code_dir, "orchestrator_instructions_file", "orchestrator_instructions"
    )
    _resolve_and_merge_instructions(
        command, code_dir, "agent_instructions_file", "agent_instructions"
    )

    return command


def generate_config(project_root: Path) -> str:
    """Generate the config.toml content from source files."""
    code_dir = project_root / ".code"
    src_dir = code_dir / "src"

    if not src_dir.exists():
        msg = f"Source directory not found: {src_dir}"
        raise FileNotFoundError(msg)

    config: dict[str, Any] = {}

    # 1. Load global settings
    settings_path = src_dir / "settings.toml"
    if settings_path.exists():
        settings = load_toml(settings_path)
        config.update(settings)

    # 2. Load agent definitions
    agents_path = src_dir / "agents.toml"
    if agents_path.exists():
        agents_config = load_toml(agents_path)
        if "agents" in agents_config:
            config["agents"] = agents_config["agents"]

    # 3. Load and process command definitions
    commands_dir = src_dir / "commands"
    if commands_dir.exists():
        commands: list[dict[str, Any]] = []
        for command_file in sorted(commands_dir.glob("*.toml")):
            command = process_command(command_file, code_dir)
            commands.append(command)

        if commands:
            # Ensure subagents is a dict before assigning commands
            if "subagents" not in config or not isinstance(config["subagents"], dict):
                config["subagents"] = {}
            config["subagents"]["commands"] = commands

    # Generate TOML output
    output = tomli_w.dumps(config)

    # Add header comment
    header = """\
# =============================================================================
# GENERATED FILE - DO NOT EDIT DIRECTLY
# =============================================================================
# This file is auto-generated by: scripts/everycode/generate_code_config.py
#
# To modify, edit the source files in .code/src/ and regenerate:
#   uv run code-config
#
# Source files:
#   .code/src/settings.toml    - Global settings
#   .code/src/agents.toml      - Agent definitions
#   .code/src/commands/*.toml  - Subagent command definitions
# =============================================================================

"""
    return header + output


# Module-level cache for find_project_root results
_project_root_cache: dict[Path, Path] = {}


def clear_project_root_cache() -> None:
    """Clear the find_project_root cache.

    This is primarily useful for testing to ensure cache isolation between tests.
    """
    _project_root_cache.clear()


def find_project_root(start_path: Path | None = None) -> Path:
    """Find the project root by walking up from start_path looking for marker files.

    Results are cached per normalized start_path to avoid repeated filesystem walks.
    Intermediate directories visited during the upward walk are also cached, so
    subsequent calls from those directories hit the cache.

    Args:
        start_path: Starting directory for the search. Defaults to the current
            working directory (Path.cwd()), which is appropriate for CLI usage.
            Pass an explicit path when calling from a known location.

    Returns:
        The first directory containing a marker file (.git, pyproject.toml,
        setup.cfg, or package.json).

    Raises:
        FileNotFoundError: If no project root marker is found before reaching
            the filesystem root.
    """
    marker_files = (".git", "pyproject.toml", "setup.cfg", "package.json")
    current = (start_path or Path.cwd()).resolve()

    # Check cache first using the normalized (resolved) path as key
    if current in _project_root_cache:
        return _project_root_cache[current]

    # Track all visited directories during the upward walk
    visited: list[Path] = []

    while True:
        # Check if we've reached a cached directory during traversal
        if current in _project_root_cache:
            root = _project_root_cache[current]
            # Cache all visited paths to this root
            for path in visited:
                _project_root_cache[path] = root
            return root

        visited.append(current)

        for marker in marker_files:
            if (current / marker).exists():
                # Cache all visited paths to this root
                for path in visited:
                    _project_root_cache[path] = current
                return current

        parent = current.parent
        if parent == current:
            # Reached filesystem root without finding a marker
            msg = (
                "Could not auto-detect project root. No marker files found "
                f"({', '.join(marker_files)}). Please specify --project-root explicitly."
            )
            raise FileNotFoundError(msg)
        current = parent


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate .code/config.toml from source files",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if config.toml is up-to-date without writing",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (default: auto-detect)",
    )
    args = parser.parse_args()

    # Find project root
    if args.project_root:
        project_root = args.project_root
    else:
        try:
            project_root = find_project_root()
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    config_path = project_root / ".code" / "config.toml"

    try:
        generated = generate_config(project_root)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.check:
        # Check mode: compare with existing file
        if not config_path.exists():
            print("config.toml does not exist, needs generation")
            return 1
        existing = config_path.read_text(encoding="utf-8")
        if existing != generated:
            print("config.toml is out of date, run without --check to regenerate")
            return 1
        print("config.toml is up to date")
        return 0

    # Write the generated config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(generated, encoding="utf-8")
    print(f"Generated: {config_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
