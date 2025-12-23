"""Tests for MCP Bridge configuration loading."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import pytest

from scripts.servers.mcp.app.core.config import (
    ConfigError,
    MCPConfig,
    SSEServerConfig,
    StdioServerConfig,
    _substitute_env_vars,
    load_config,
)


class TestSubstituteEnvVars:
    """Tests for environment variable substitution."""

    def test_substitute_braces_with_value(self):
        """Test ${VAR} substitution when variable exists."""
        with patch.dict(os.environ, {"MY_VAR": "my_value"}):
            result = _substitute_env_vars("prefix_${MY_VAR}_suffix")
            assert result == "prefix_my_value_suffix"

    def test_substitute_braces_with_default(self):
        """Test ${VAR:-default} substitution when variable doesn't exist."""
        # Make sure the variable doesn't exist
        env = os.environ.copy()
        if "MISSING_VAR" in env:
            del env["MISSING_VAR"]
        with patch.dict(os.environ, env, clear=True):
            result = _substitute_env_vars("prefix_${MISSING_VAR:-default_value}_suffix")
            assert result == "prefix_default_value_suffix"

    def test_substitute_braces_missing_no_default(self):
        """Test ${VAR} substitution when variable doesn't exist and no default - returns empty."""
        env = os.environ.copy()
        if "REALLY_MISSING" in env:
            del env["REALLY_MISSING"]
        with patch.dict(os.environ, env, clear=True):
            result = _substitute_env_vars("prefix_${REALLY_MISSING}_suffix")
            assert result == "prefix__suffix"

    def test_substitute_simple_format(self):
        """Test $VAR simple format substitution."""
        with patch.dict(os.environ, {"SIMPLE_VAR": "simple_value"}):
            result = _substitute_env_vars("prefix_$SIMPLE_VAR_end")
            # Note: SIMPLE_VAR_end is treated as the variable name
            # Let's use a clearer case
            result = _substitute_env_vars("prefix/$SIMPLE_VAR/suffix")
            assert result == "prefix/simple_value/suffix"

    def test_substitute_simple_format_missing(self):
        """Test $VAR simple format when variable doesn't exist - returns empty."""
        env = os.environ.copy()
        if "ANOTHER_MISSING" in env:
            del env["ANOTHER_MISSING"]
        with patch.dict(os.environ, env, clear=True):
            result = _substitute_env_vars("prefix/$ANOTHER_MISSING/suffix")
            assert result == "prefix//suffix"


class TestGetFullCommand:
    """Tests for StdioServerConfig.get_full_command."""

    def test_get_full_command_no_args(self):
        """Test get_full_command with no arguments."""
        config = StdioServerConfig(
            name="test",
            command="echo",
        )
        assert config.get_full_command() == "echo"

    def test_get_full_command_with_args(self):
        """Test get_full_command with arguments."""
        config = StdioServerConfig(
            name="test",
            command="uvx",
            args=["mcp-background-job", "--port", "8080"],
        )
        assert config.get_full_command() == "uvx mcp-background-job --port 8080"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_nonexistent_path_returns_empty(self):
        """Test that load_config with nonexistent path returns empty config."""
        config = load_config("/nonexistent/path/config.yml")
        assert isinstance(config, MCPConfig)
        assert len(config.servers) == 0

    def test_load_config_no_file_found_returns_empty(self):
        """Test that load_config with no config file found returns empty config."""
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.dict(os.environ, {"MCP_CONFIG_PATH": ""}),
        ):
            # Use tmpdir as base to avoid finding real config files
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                config = load_config(None)
                assert isinstance(config, MCPConfig)
                assert len(config.servers) == 0
            finally:
                os.chdir(original_cwd)

    def test_load_config_list_yaml_returns_empty(self):
        """Test that load_config returns empty config when YAML is a list (not dict)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("- item1\n- item2\n")
            f.flush()
            try:
                # _load_yaml_or_json returns {} for non-dict content
                config = load_config(f.name)
                assert isinstance(config, MCPConfig)
                # No servers because mcpServers key doesn't exist
                assert len(config.servers) == 0
            finally:
                os.unlink(f.name)

    def test_load_config_invalid_mcp_servers_type(self):
        """Test that load_config raises ConfigError when mcpServers is not a mapping."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("mcpServers:\n  - server1\n  - server2\n")
            f.flush()
            try:
                with pytest.raises(ConfigError, match="'mcpServers' must be a mapping"):
                    load_config(f.name)
            finally:
                os.unlink(f.name)

    def test_load_config_valid_stdio_server(self):
        """Test loading a valid stdio server config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
mcpServers:
  test-server:
    type: stdio
    command: echo
    args:
      - hello
      - world
    env:
      MY_VAR: value
""")
            f.flush()
            try:
                config = load_config(f.name)
                assert "test-server" in config.servers
                server = config.servers["test-server"]
                assert isinstance(server, StdioServerConfig)
                assert server.command == "echo"
                assert server.args == ["hello", "world"]
                assert server.env == {"MY_VAR": "value"}
            finally:
                os.unlink(f.name)

    def test_load_config_valid_sse_server(self):
        """Test loading a valid SSE server config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
mcpServers:
  linear:
    type: sse
    url: https://mcp.linear.app/sse
    headers:
      Authorization: Bearer token
""")
            f.flush()
            try:
                config = load_config(f.name)
                assert "linear" in config.servers
                server = config.servers["linear"]
                assert isinstance(server, SSEServerConfig)
                assert server.url == "https://mcp.linear.app/sse"
                assert server.headers == {"Authorization": "Bearer token"}
            finally:
                os.unlink(f.name)

    def test_load_config_disabled_server_skipped(self):
        """Test that disabled servers are not included in the config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
mcpServers:
  enabled-server:
    type: stdio
    command: echo
  disabled-server:
    type: stdio
    command: echo
    disabled: true
""")
            f.flush()
            try:
                config = load_config(f.name)
                assert "enabled-server" in config.servers
                assert "disabled-server" not in config.servers
            finally:
                os.unlink(f.name)

    def test_load_config_json_format(self):
        """Test loading a JSON config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("""{
  "mcpServers": {
    "test-server": {
      "type": "stdio",
      "command": "echo"
    }
  }
}""")
            f.flush()
            try:
                config = load_config(f.name)
                assert "test-server" in config.servers
            finally:
                os.unlink(f.name)

    def test_load_config_env_var_substitution(self):
        """Test environment variable substitution in config values."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
mcpServers:
  test-server:
    type: stdio
    command: echo
    env:
      API_KEY: ${TEST_API_KEY}
""")
            f.flush()
            try:
                with patch.dict(
                    os.environ, {"TEST_API_KEY": "secret123"}
                ):  # pragma: allowlist secret
                    config = load_config(f.name)
                    server = config.servers["test-server"]
                    assert isinstance(server, StdioServerConfig)
                    assert server.env["API_KEY"] == "secret123"  # pragma: allowlist secret
            finally:
                os.unlink(f.name)

    def test_load_config_from_env_path(self):
        """Test loading config from MCP_CONFIG_PATH environment variable."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
mcpServers:
  env-server:
    type: stdio
    command: echo
""")
            f.flush()
            try:
                with patch.dict(os.environ, {"MCP_CONFIG_PATH": f.name}):
                    # Call with None to trigger search
                    config = load_config(None)
                    assert "env-server" in config.servers
            finally:
                os.unlink(f.name)


class TestParseServerConfig:
    """Tests for server config parsing edge cases."""

    def test_missing_command_raises_error(self):
        """Test that missing command in stdio server raises ConfigError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
mcpServers:
  test-server:
    type: stdio
""")
            f.flush()
            try:
                with pytest.raises(ConfigError, match="missing required 'command'"):
                    load_config(f.name)
            finally:
                os.unlink(f.name)

    def test_missing_url_raises_error(self):
        """Test that missing url in SSE server raises ConfigError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
mcpServers:
  test-server:
    type: sse
""")
            f.flush()
            try:
                with pytest.raises(ConfigError, match="missing required 'url'"):
                    load_config(f.name)
            finally:
                os.unlink(f.name)

    def test_unknown_transport_raises_error(self):
        """Test that unknown transport type raises ConfigError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
mcpServers:
  test-server:
    type: unknown_transport
    command: echo
""")
            f.flush()
            try:
                with pytest.raises(ConfigError, match="unknown transport type"):
                    load_config(f.name)
            finally:
                os.unlink(f.name)
