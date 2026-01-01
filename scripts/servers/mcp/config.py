"""Configuration loading for MCP Bridge.

This module handles loading MCP server configurations from YAML or JSON files,
following the Claude Code MCP specification with environment variable
substitution support.

Supports both `.mcp.yml` (preferred) and `.mcp.json` formats.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# Defer yaml import to reduce cold-start time (~200ms savings)
# Only import when actually parsing YAML files


class TransportType(str, Enum):
    """MCP transport types."""

    STDIO = "stdio"
    SSE = "sse"


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


@dataclass
class StdioServerConfig:
    """Configuration for a stdio-based MCP server.

    Follows the Claude Code MCP specification for stdio servers.
    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: TransportType = TransportType.STDIO
    # Optional fields from Claude Code spec
    disabled: bool = False
    cwd: str | None = None

    def get_full_command(self) -> str:
        """Get the full command string for spawning the process."""
        parts = [self.command, *self.args]
        return " ".join(parts)


@dataclass
class SSEServerConfig:
    """Configuration for an SSE-based MCP server.

    For servers like Linear that use HTTP SSE transport.
    """

    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    transport: TransportType = TransportType.SSE
    disabled: bool = False


ServerConfig = StdioServerConfig | SSEServerConfig


@dataclass
class MCPConfig:
    """Full MCP Bridge configuration."""

    servers: dict[str, ServerConfig] = field(default_factory=dict)


def _substitute_env_vars(value: str) -> str:
    """Substitute environment variables in a string.

    Supports multiple formats:
    - ${VAR} - Standard format
    - ${VAR:-default} - With default value
    - $VAR - Simple format (without braces)

    Args:
        value: String potentially containing env var references.

    Returns:
        String with env vars substituted.
    """
    # Pattern matches ${VAR} or ${VAR:-default}
    pattern_braces = r"\$\{([^}:]+)(?::-([^}]*))?\}"

    def replacer_braces(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2)
        env_value = os.environ.get(var_name)
        if env_value is not None:
            return env_value
        if default is not None:
            return default
        # Return empty string if var not found and no default
        return ""

    result = re.sub(pattern_braces, replacer_braces, value)

    # Also handle simple $VAR format (must come after ${} to avoid conflicts)
    pattern_simple = r"\$([A-Za-z_][A-Za-z0-9_]*)"

    def replacer_simple(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return re.sub(pattern_simple, replacer_simple, result)


def _process_env_vars(obj: Any) -> Any:
    """Recursively process environment variables in a config object.

    Args:
        obj: Config object (dict, list, or scalar).

    Returns:
        Object with env vars substituted.
    """
    if isinstance(obj, str):
        return _substitute_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _process_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_process_env_vars(item) for item in obj]
    return obj


def _parse_server_config(name: str, config: dict[str, Any]) -> ServerConfig:
    """Parse a single server configuration.

    Supports the full Claude Code MCP specification:
    - type: "stdio" or "sse"
    - command: Command to run (stdio)
    - args: Arguments list (stdio)
    - env: Environment variables (stdio)
    - url: URL for SSE servers
    - headers: HTTP headers (sse)
    - disabled: Whether server is disabled
    - cwd: Working directory (stdio)

    Args:
        name: Server name.
        config: Server config dict.

    Returns:
        Parsed ServerConfig.

    Raises:
        ConfigError: If config is invalid.
    """
    # Check if disabled
    disabled = config.get("disabled", False)

    transport_type = config.get("type", "stdio")

    if transport_type == "stdio":
        command = config.get("command")
        if not command:
            raise ConfigError(f"Server '{name}' missing required 'command' field")
        if not isinstance(command, str):
            raise ConfigError(
                f"Server '{name}': 'command' must be a string, got {type(command).__name__}"
            )

        args = config.get("args", [])
        if isinstance(args, str):
            args = [args]
        if not isinstance(args, list):
            raise ConfigError(f"Server '{name}': 'args' must be a list, got {type(args).__name__}")
        if not all(isinstance(a, str) for a in args):
            raise ConfigError(f"Server '{name}': 'args' must be a list of strings")

        env = config.get("env", {})
        if not isinstance(env, dict):
            raise ConfigError(f"Server '{name}': 'env' must be a dict, got {type(env).__name__}")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise ConfigError(f"Server '{name}': 'env' must be a dict[str, str]")

        return StdioServerConfig(
            name=name,
            command=command,
            args=args,
            env=env,
            disabled=disabled,
            cwd=config.get("cwd"),
        )

    if transport_type == "sse":
        url = config.get("url")
        if not url:
            raise ConfigError(f"Server '{name}' missing required 'url' field")

        return SSEServerConfig(
            name=name,
            url=url,
            headers=config.get("headers", {}),
            disabled=disabled,
        )

    raise ConfigError(f"Server '{name}' has unknown transport type: {transport_type}")


def _find_config_file(base_path: Path | None = None) -> Path | None:
    """Find the MCP config file.

    Search order:
    1. MCP_CONFIG_PATH environment variable
    2. .mcp.yml in base_path or current directory (and parent directories)
    3. .mcp.yaml in base_path or current directory (and parent directories)
    4. .mcp.json in base_path or current directory (and parent directories)
    5. mcp-servers.json in services/mcp-bridge (legacy)
    6. mcp-servers.json in current directory (legacy)

    Args:
        base_path: Base directory to search from.

    Returns:
        Path to config file, or None if not found.
    """
    # Check environment variable first
    env_path = os.environ.get("MCP_CONFIG_PATH")
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file():
            return path

    # Determine base directory
    if base_path is None:
        base_path = Path.cwd()

    # Search current directory and parent directories for config files
    # This allows finding .mcp.yml in project root when running from subdirs
    config_names = [".mcp.yml", ".mcp.yaml", ".mcp.json"]
    search_dir = base_path.resolve()

    while search_dir != search_dir.parent:  # Stop at filesystem root
        for config_name in config_names:
            candidate = search_dir / config_name
            if candidate.is_file():
                return candidate
        search_dir = search_dir.parent

    # Also check root
    for config_name in config_names:
        candidate = search_dir / config_name
        if candidate.is_file():
            return candidate

    # Legacy: check for mcp-servers.json in current dir or services/mcp-bridge
    legacy_candidates = [
        base_path / "mcp-servers.json",
        base_path / "services" / "mcp-bridge" / "mcp-servers.json",
    ]

    for candidate in legacy_candidates:
        if candidate.is_file():
            return candidate

    return None


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    """Load a YAML or JSON config file.

    Args:
        path: Path to config file.

    Returns:
        Parsed config dict.

    Raises:
        ConfigError: If file cannot be parsed.
    """
    # Defer yaml import to reduce cold-start time when config is empty/not used
    import yaml

    suffix = path.suffix.lower()

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()

        if suffix in (".yml", ".yaml"):
            loaded = yaml.safe_load(content)
            return loaded if isinstance(loaded, dict) else {}
        if suffix == ".json":
            loaded = json.loads(content)
            return loaded if isinstance(loaded, dict) else {}

        # Try YAML first, fall back to JSON
        try:
            loaded = yaml.safe_load(content)
            return loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            loaded = json.loads(content)
            return loaded if isinstance(loaded, dict) else {}

    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in config file: {e}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config file: {e}") from e
    except OSError as e:
        raise ConfigError(f"Failed to read config file: {e}") from e


def load_config(config_path: str | Path | None = None) -> MCPConfig:
    """Load MCP configuration from a YAML or JSON file.

    The config file follows the Claude Code MCP specification:

    YAML format (.mcp.yml):
    ```yaml
    mcpServers:
      background-job:
        type: stdio
        command: uvx
        args:
          - mcp-background-job

      firecrawl:
        type: stdio
        command: npx
        args:
          - "-y"
          - firecrawl-mcp
        env:
          FIRECRAWL_API_KEY: ${FIRECRAWL_API_KEY}

      linear:
        type: stdio
        command: npx
        args:
          - "-y"
          - mcp-remote
          - https://mcp.linear.app/sse
    ```

    JSON format (.mcp.json):
    ```json
    {
      "mcpServers": {
        "server-name": {
          "type": "stdio",
          "command": "uvx",
          "args": ["mcp-background-job"]
        }
      }
    }
    ```

    Environment variables are substituted using ${VAR}, ${VAR:-default}, or $VAR syntax.

    Args:
        config_path: Path to config file. If None, searches for config file.

    Returns:
        Parsed MCPConfig.

    Raises:
        ConfigError: If config file is invalid.
    """
    # Find config file
    if config_path is not None:
        path = Path(config_path)
        if not path.exists():
            return MCPConfig()
    else:
        found_path = _find_config_file()
        if found_path is None:
            return MCPConfig()
        path = found_path

    # Load config
    raw_config = _load_yaml_or_json(path)

    # Process environment variables
    config = _process_env_vars(raw_config)

    if not isinstance(config, dict):
        raise ConfigError(f"Config must be a mapping, got {type(config).__name__}")

    # Parse servers
    servers: dict[str, ServerConfig] = {}
    mcp_servers = config.get("mcpServers", {})

    if not isinstance(mcp_servers, dict):
        raise ConfigError(f"'mcpServers' must be a mapping, got {type(mcp_servers).__name__}")

    for name, server_config in mcp_servers.items():
        parsed = _parse_server_config(name, server_config)
        # Skip disabled servers
        if not parsed.disabled:
            servers[name] = parsed

    return MCPConfig(servers=servers)


__all__ = [
    "ConfigError",
    "MCPConfig",
    "SSEServerConfig",
    "ServerConfig",
    "StdioServerConfig",
    "TransportType",
    "load_config",
]
