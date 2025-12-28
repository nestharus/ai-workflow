"""Everycode configuration generation tools.

This package provides utilities for generating .code/config.toml from
modular source files located in .code/.

Example usage:
    from scripts.everycode import generate_config, process_command

    # Generate full config
    config_content = generate_config(project_root)

    # Process a single command file
    command = process_command(command_path, code_dir)
"""

from scripts.everycode.generate_code_config import (
    clear_project_root_cache,
    find_project_root,
    generate_config,
    load_toml,
    main,
    process_command,
    resolve_instruction_file,
)

__all__ = [
    "clear_project_root_cache",
    "find_project_root",
    "generate_config",
    "load_toml",
    "main",
    "process_command",
    "resolve_instruction_file",
]
