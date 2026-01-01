import ast
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent.parent.parent.parent


class TestCallerMigration:
    def test_mcp_agent_client_imports(self) -> None:
        """Verify mcp_agent_client.py imports work with socket transport."""
        from scripts.dev.mcp_agent_client import get_mcp_client

        client = get_mcp_client()
        # Should not raise on instantiation
        assert client is not None

    def test_mcp_agent_client_uses_socket(self) -> None:
        """Verify mcp_agent_client returns a socket-based client."""
        from scripts.dev.mcp_agent_client import get_mcp_client
        from scripts.servers.mcp.client import MCPSocketClient

        client = get_mcp_client()
        # Client should be a MCPSocketClient instance
        assert isinstance(client, MCPSocketClient)

    def test_benchmark_script_help(self) -> None:
        """Verify benchmark script runs without HTTP errors."""
        result = subprocess.run(
            [
                sys.executable,
                "scripts/servers/mcp/benchmark_bridge_transport.py",
                "--help",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent.parent.parent,
        )
        assert result.returncode == 0
        # Help should mention socket (not HTTP as primary)
        assert "socket" in result.stdout.lower()

    def test_http_mcp_client_alias_works(self) -> None:
        """Verify HttpMCPClient alias works for backward compatibility."""
        from scripts.servers.mcp.client import HttpMCPClient, MCPSocketClient

        # HttpMCPClient should be an alias for MCPSocketClient
        assert HttpMCPClient is MCPSocketClient

        # Should be able to instantiate via alias
        client = HttpMCPClient(socket_path="/tmp/test.sock")
        assert client.socket_path == "/tmp/test.sock"

    def test_client_package_exports(self) -> None:
        """Verify client package exports all expected symbols."""
        from scripts.servers.mcp.client import (
            HttpMCPClient,
            MCPClientError,
            MCPSocketClient,
        )

        # All exports should be available
        assert HttpMCPClient is not None
        assert MCPSocketClient is not None
        assert MCPClientError is not None


class TestNoHttpReferences:
    def test_socket_client_no_http_library_usage(self, project_root: Path) -> None:
        """Verify socket client doesn't use HTTP libraries for transport."""
        client_file = project_root / "scripts/servers/mcp/client/http_client.py"
        content = client_file.read_text()

        # Should not use requests library
        assert "import requests" not in content
        assert "from requests" not in content

        # Should not use httpx library
        assert "import httpx" not in content
        assert "from httpx" not in content

        # Should not use urllib for HTTP calls
        assert "urllib.request" not in content

    def test_socket_client_uses_unix_socket(self, project_root: Path) -> None:
        """Verify socket client uses Unix socket transport."""
        client_file = project_root / "scripts/servers/mcp/client/http_client.py"
        content = client_file.read_text()

        # Should use socket module
        assert "import socket" in content
        # Should use AF_UNIX for Unix domain sockets
        assert "AF_UNIX" in content

    def test_mcp_agent_client_no_curl(self, project_root: Path) -> None:
        """Verify mcp_agent_client doesn't shell out to curl."""
        client_file = project_root / "scripts/dev/mcp_agent_client.py"
        content = client_file.read_text()

        # Use AST to find all docstring line ranges to skip
        docstring_lines: set[int] = set()
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                # Check for docstrings in module, class, and function definitions
                if (
                    isinstance(
                        node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                    )
                    and node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    docstring_node = node.body[0]
                    end_lineno = getattr(docstring_node, "end_lineno", None)
                    if end_lineno is None:
                        end_lineno = docstring_node.lineno
                    for line_num in range(docstring_node.lineno, end_lineno + 1):
                        docstring_lines.add(line_num)
        except SyntaxError:
            pass  # If parsing fails, proceed without docstring exclusions

        # Should not shell out to curl
        lines = content.split("\n")
        for line_num, line in enumerate(lines, start=1):
            # Skip docstring lines (identified via AST)
            if line_num in docstring_lines:
                continue
            stripped = line.strip()
            # Skip comments
            if stripped.startswith("#"):
                continue
            # No active curl subprocess calls
            assert not ("subprocess" in line and "curl" in line)


class TestDockerHealthcheckMigration:
    def test_dev_compose_uses_python_healthcheck(self, project_root: Path) -> None:
        """Verify docker-compose.dev.yml uses Python socket healthcheck."""
        compose_file = project_root / "docker-compose.dev.yml"
        if not compose_file.exists():
            pytest.skip("docker-compose.dev.yml not found")
        content = compose_file.read_text()

        # Should use Python for healthcheck
        assert "python" in content
        # Should reference socket connection
        assert "socket" in content or "AF_UNIX" in content
        # Should connect to socket path
        assert "mcp-bridge.sock" in content

    def test_prod_compose_uses_socket_healthcheck(self, project_root: Path) -> None:
        """Verify docker-compose.yml uses socket-based healthcheck."""
        compose_file = project_root / "docker-compose.yml"
        if not compose_file.exists():
            pytest.skip("docker-compose.yml not found")
        content = compose_file.read_text()

        # Should reference socket path
        assert "mcp-bridge.sock" in content
        # Healthcheck should reference socket
        assert "unix-socket" in content or "socket" in content


class TestDocumentationMigration:
    def test_architecture_docs_mention_socket(self, project_root: Path) -> None:
        """Verify architecture docs describe socket protocol."""
        arch_file = project_root / "docs/architecture/mcp-bridge-architecture.yml"
        if not arch_file.exists():
            pytest.skip("mcp-bridge-architecture.yml not found")
        content = arch_file.read_text()

        # Should mention Unix socket
        assert "Unix socket" in content or "socket" in content
        # Should mention socket path
        assert "MCP_BRIDGE_SOCKET" in content

    def test_setup_docs_mention_socket(self, project_root: Path) -> None:
        """Verify setup docs describe socket protocol."""
        setup_file = project_root / "docs/processes/mcp-background-job-setup.yml"
        if not setup_file.exists():
            pytest.skip("mcp-background-job-setup.yml not found")
        content = setup_file.read_text()

        # Should mention socket
        assert "socket" in content
        # Should have socket path example
        assert "mcp-bridge.sock" in content

    def test_dev_env_docs_mention_socket(self, project_root: Path) -> None:
        """Verify dev environment docs describe socket protocol."""
        dev_file = project_root / "docs/processes/dev-env.yml"
        if not dev_file.exists():
            pytest.skip("dev-env.yml not found")
        content = dev_file.read_text()

        # Should mention socket
        assert "socket" in content
        # Should mention socket path
        assert "mcp-sockets" in content or "mcp-bridge.sock" in content

    def test_migration_inventory_exists(self, project_root: Path) -> None:
        """Verify migration inventory document exists."""
        inventory_file = project_root / "docs/migration/http-to-socket-caller-inventory.md"
        assert inventory_file.exists(), "Migration inventory document should exist"

        content = inventory_file.read_text()
        # Should have migration guide
        assert "Migration Guide" in content
        # Should have caller inventory
        assert "Caller Inventory" in content
