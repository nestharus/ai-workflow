"""Native asyncio socket server for MCP Bridge.

Provides a fast-starting Unix socket server that replaces the FastAPI/HTTP-based
MCP bridge with a lightweight JSONL-based protocol. Achieves <500ms cold start
compared to ~2-3 seconds for FastAPI/uvicorn.

This server:
- Uses asyncio.start_unix_server() for minimal startup overhead
- Implements JSONL framing (newline-delimited JSON)
- Enforces request size and timeout limits for security
- Reuses existing MCPStdioManager and MCPSSEClient for MCP communication
- Builds responses using protocol dataclasses for HTTP API compatibility
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

from scripts.servers.mcp.config import (
    ConfigError,
    MCPConfig,
    SSEServerConfig,
    StdioServerConfig,
    load_config,
)
from scripts.servers.mcp.manager import (
    MCPBusyError,
    MCPClient,
    MCPError,
    MCPProviderCrashedError,
    MCPStdioManager,
    MCPTimeoutError,
)
from scripts.servers.mcp.protocol import (
    CallToolRequest,
    ErrorType,
    GetServerToolRequest,
    HealthRequest,
    HealthResponse,
    ListServersRequest,
    ListToolsRequest,
    MCPCallResponse,
    Request,
    ServerInfo,
    ServersResponse,
    create_error_response,
    create_success_response,
    parse_request,
)

# Note: sse_client import is deferred to _create_client() to reduce cold-start time
# (~500ms savings from httpx import). MCPSSEError is now a subclass of MCPError,
# so we don't need to import it separately for exception handling.

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure logging for the server.

    Deferred to avoid interfering with application/test logging when imported.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


# ---------------------------------------------------------------------------
# Request Size and Timeout Constants (configurable via environment)
# ---------------------------------------------------------------------------


def _parse_env_int(key: str, default: int) -> int:
    """Parse an environment variable as an integer with graceful fallback.

    Args:
        key: Environment variable name.
        default: Default value if parsing fails or variable is unset.

    Returns:
        Parsed integer value or default.
    """
    try:
        value = int(os.environ.get(key, default))
        if value <= 0:
            logger.warning(f"{key}={value} is not positive, using default {default}")
            return default
        return value
    except ValueError:
        actual = os.environ.get(key, "<unset>")
        logger.warning(f"{key}={actual!r} is not a valid integer, using default {default}")
        return default


def _parse_env_float(key: str, default: float) -> float:
    """Parse an environment variable as a float with graceful fallback.

    Args:
        key: Environment variable name.
        default: Default value if parsing fails or variable is unset.

    Returns:
        Parsed float value or default.
    """
    try:
        value = float(os.environ.get(key, default))
        if value <= 0:
            logger.warning(f"{key}={value} is not positive, using default {default}")
            return default
        return value
    except ValueError:
        actual = os.environ.get(key, "<unset>")
        logger.warning(f"{key}={actual!r} is not a valid float, using default {default}")
        return default


MAX_REQUEST_SIZE = _parse_env_int("MCP_MAX_REQUEST_SIZE", 4 * 1024 * 1024)  # 4 MB
MAX_READ_CHUNK = 64 * 1024  # 64 KB per recv() call
REQUEST_READ_TIMEOUT = _parse_env_float("MCP_REQUEST_READ_TIMEOUT", 30.0)  # seconds
PER_READ_TIMEOUT = _parse_env_float("MCP_PER_READ_TIMEOUT", 5.0)  # seconds
SOCKET_IDLE_TIMEOUT = _parse_env_float("MCP_SOCKET_IDLE_TIMEOUT", 60.0)  # seconds

# Default socket path (can be overridden via environment)
DEFAULT_SOCKET_PATH = "/tmp/mcp-bridge.sock"


# ---------------------------------------------------------------------------
# Custom Exceptions for Request Handling
# ---------------------------------------------------------------------------


class RequestTooLargeError(Exception):
    """Raised when a request exceeds the maximum allowed size."""

    pass


class RequestTimeoutError(Exception):
    """Raised when a request read times out."""

    pass


class ConnectionIdleError(Exception):
    """Raised when a connection is idle for too long."""

    pass


class NotFoundError(Exception):
    """Raised when a server or tool is not found."""

    pass


# ---------------------------------------------------------------------------
# Client Factory (adapted from factory.py)
# ---------------------------------------------------------------------------


def _create_client(name: str, server_config: StdioServerConfig | SSEServerConfig) -> MCPClient:
    """Create an MCP client for the given server configuration.

    Args:
        name: Server name (for error messages).
        server_config: Server configuration.

    Returns:
        MCPClient instance (MCPStdioManager or MCPSSEClient).

    Raises:
        ConfigError: If server type is unknown.
    """
    if isinstance(server_config, StdioServerConfig):
        full_command = server_config.get_full_command()
        startup_timeout = 120.0 if "mcp-remote" in full_command else 10.0

        # Pass env to MCPStdioManager instead of mutating global os.environ
        # This ensures proper isolation between servers and is safe for concurrent initialization
        return MCPStdioManager(
            command=full_command,
            startup_timeout=startup_timeout,
            cwd=server_config.cwd,
            env=server_config.env if server_config.env else None,
        )

    if isinstance(server_config, SSEServerConfig):
        # Defer import to reduce cold-start time when no SSE servers configured
        from scripts.servers.mcp.sse_client import MCPSSEClient

        return MCPSSEClient(
            url=server_config.url,
            headers=server_config.headers,
        )

    raise ConfigError(f"Unknown server type for '{name}'")


# ---------------------------------------------------------------------------
# MCP Socket Server
# ---------------------------------------------------------------------------


class MCPSocketServer:
    """Native asyncio socket server for MCP Bridge.

    Provides a fast-starting Unix socket server using JSONL framing.
    Implements all MCP operations with security limits for request size
    and timeout protection against slowloris attacks.
    """

    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET_PATH,
        config_path: str | None = None,
    ) -> None:
        """Initialize the MCP socket server.

        Args:
            socket_path: Path to the Unix socket file.
            config_path: Optional path to MCP configuration file.
        """
        self.socket_path = socket_path
        self.config_path = config_path
        self.config: MCPConfig | None = None
        self.clients: dict[str, MCPClient] = {}
        self._server: asyncio.Server | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._shutdown_requested: bool = False

    async def start(self) -> None:
        """Start the socket server."""
        # Initialize asyncio primitives in async context
        self._shutdown_event = asyncio.Event()

        # Check if shutdown was requested before the event loop started
        if self._shutdown_requested:
            self._shutdown_event.set()
            return

        # Wrap all initialization in try/finally to ensure shutdown() always runs
        # on failure. This prevents leaking initialized MCPClients if startup
        # fails partway through (e.g., after some clients init but socket bind fails).
        try:
            # Load configuration
            await self._load_config()

            # Initialize MCP clients
            await self._init_clients()

            socket_path = self.socket_path

            # 1. Ensure parent directory exists with appropriate permissions
            #    Using 0o777 is intentional for IPC scenarios where Docker runs as root
            #    and host CLI runs as non-root user
            parent_dir = Path(socket_path).parent
            parent_dir.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(parent_dir, 0o777)  # noqa: S103
            except PermissionError:
                # Permission denied (e.g., /tmp in non-root CI environments)
                # This is expected and safe to ignore - /tmp is already world-writable
                logger.debug(f"Cannot chmod parent directory {parent_dir} (permission denied)")
            except OSError as e:
                # Other OS errors (e.g., read-only filesystem) - log but continue
                logger.debug(f"Cannot chmod parent directory {parent_dir}: {e}")

            # 2. Remove existing socket file if present (stale from previous run)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(socket_path)

            # 3. Bind the socket
            self._server = await asyncio.start_unix_server(
                self._handle_client,
                path=socket_path,
            )

            # 4. Set socket file permissions to world-writable
            #    Using 0o777 is intentional for cross-user access
            os.chmod(socket_path, 0o777)  # noqa: S103

            logger.info(f"Server listening on {socket_path}")

            # Wait for shutdown signal
            await self._shutdown_event.wait()
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shut down the server gracefully."""
        # Close server and wait for connections to finish
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Close all MCP clients
        for name, client in self.clients.items():
            try:
                logger.info(f"Shutting down MCP server '{name}'...")
                client.close()
            except Exception:
                logger.exception(f"Error closing client '{name}'")

        self.clients.clear()
        self.config = None

        # Remove socket file to avoid stale socket on next startup
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.socket_path)

        logger.info("Server shutdown complete")

    def request_shutdown(self) -> None:
        """Signal the server to shut down.

        Safe to call before start() - sets a flag that start() will check,
        ensuring early signals are not dropped.
        """
        self._shutdown_requested = True
        if self._shutdown_event is not None:
            self._shutdown_event.set()

    async def _load_config(self) -> None:
        """Load MCP configuration from file."""
        config_path = self.config_path or os.environ.get("MCP_CONFIG_PATH")
        if config_path:
            logger.info(f"Loading MCP configuration from {config_path}")
        else:
            logger.info("Searching for MCP configuration file...")

        try:
            self.config = load_config(config_path)
            logger.info(f"Loaded {len(self.config.servers)} server(s) from config")
        except ConfigError as e:
            logger.warning(f"Failed to load config: {e}. Starting with no servers.")
            self.config = MCPConfig()

        if not self.config.servers:
            legacy_command = os.environ.get("MCP_COMMAND")
            if legacy_command:
                logger.info(f"Using legacy MCP_COMMAND: {legacy_command}")
                self.config.servers["default"] = StdioServerConfig(
                    name="default",
                    command=legacy_command,
                )

    async def _init_clients(self) -> None:
        """Initialize MCP clients for all configured servers."""
        if self.config is None:
            return

        loop = asyncio.get_running_loop()
        for name, server_config in self.config.servers.items():
            try:
                logger.info(f"Initializing MCP server '{name}'...")
                # Run blocking client initialization in thread pool
                client = await loop.run_in_executor(
                    None,
                    _create_client,
                    name,
                    server_config,
                )
                self.clients[name] = client
                logger.info(f"MCP server '{name}' initialized successfully")
            except Exception:
                logger.exception(f"Failed to initialize server '{name}'")

        logger.info(f"MCP Bridge started with {len(self.clients)} server(s)")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        # Per-connection buffer to preserve bytes across _read_request calls
        connection_buffer = bytearray()
        try:
            while True:
                try:
                    request_bytes = await self._read_request(reader, writer, connection_buffer)
                except (RequestTooLargeError, RequestTimeoutError, ConnectionIdleError):
                    # Error response already sent by _read_request
                    break

                if request_bytes is None:
                    # Connection closed by client
                    break

                # Process the request
                response_json = await self._process_request(request_bytes)
                writer.write(response_json.encode() + b"\n")
                await writer.drain()

        except Exception:
            logger.exception("Error handling client")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _read_request(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        connection_buffer: bytearray,
    ) -> bytes | None:
        """Read a complete JSONL request with size and timeout enforcement.

        Uses a persistent connection_buffer to preserve bytes across calls,
        ensuring pipelined JSONL frames received in a single recv() are all
        processed sequentially.

        Args:
            reader: The asyncio stream reader.
            writer: The asyncio stream writer (for error responses).
            connection_buffer: Persistent buffer shared across calls for this
                connection. Modified in-place to preserve unread bytes.

        Returns:
            The complete request bytes (excluding newline), or None if connection closed.

        Raises:
            RequestTooLargeError: If request exceeds MAX_REQUEST_SIZE
            RequestTimeoutError: If request not completed within REQUEST_READ_TIMEOUT
            ConnectionIdleError: If no data received within SOCKET_IDLE_TIMEOUT
        """
        # Check if we already have a complete line in the buffer from a previous read
        if b"\n" in connection_buffer:
            line, _, remaining = connection_buffer.partition(b"\n")
            connection_buffer.clear()
            connection_buffer.extend(remaining)
            return bytes(line)

        start_time = asyncio.get_running_loop().time()

        while True:
            # Check total read timeout
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed > REQUEST_READ_TIMEOUT:
                msg = f"Request read timeout after {REQUEST_READ_TIMEOUT}s (slow-drip protection)"
                await self._send_error_and_close(
                    writer,
                    request_id=None,
                    error_type=ErrorType.BAD_REQUEST,
                    message=msg,
                )
                raise RequestTimeoutError(f"Request not completed within {REQUEST_READ_TIMEOUT}s")

            # Choose timeout based on whether we have partial data:
            # - Empty buffer: use SOCKET_IDLE_TIMEOUT (60s) for idle connections
            # - Partial data: use PER_READ_TIMEOUT (5s) for slow-drip protection
            read_timeout = SOCKET_IDLE_TIMEOUT if len(connection_buffer) == 0 else PER_READ_TIMEOUT

            # Read with appropriate timeout
            try:
                chunk = await asyncio.wait_for(
                    reader.read(MAX_READ_CHUNK),
                    timeout=read_timeout,
                )
            except TimeoutError:
                # No data received within timeout window
                if len(connection_buffer) == 0:
                    # Connection idle - no partial data, just waiting
                    await self._send_error_and_close(
                        writer,
                        request_id=None,
                        error_type=ErrorType.BAD_REQUEST,
                        message=f"Connection idle timeout after {SOCKET_IDLE_TIMEOUT}s",
                    )
                    raise ConnectionIdleError(
                        f"No data received within {SOCKET_IDLE_TIMEOUT}s"
                    ) from None
                else:
                    # Partial data received but stalled - slow-drip attack
                    msg = (
                        f"Incomplete request: data stalled with "
                        f"{len(connection_buffer)} bytes buffered"
                    )
                    await self._send_error_and_close(
                        writer,
                        request_id=None,
                        error_type=ErrorType.BAD_REQUEST,
                        message=msg,
                    )
                    raise RequestTimeoutError(
                        f"Request stalled with {len(connection_buffer)} bytes buffered"
                    ) from None

            if not chunk:
                # Connection closed by client
                return None

            connection_buffer.extend(chunk)

            # Check size limit BEFORE looking for newline
            if len(connection_buffer) > MAX_REQUEST_SIZE:
                msg = (
                    f"Request too large: {len(connection_buffer)} bytes exceeds "
                    f"{MAX_REQUEST_SIZE} byte limit"
                )
                await self._send_error_and_close(
                    writer,
                    request_id=None,
                    error_type=ErrorType.BAD_REQUEST,
                    message=msg,
                )
                raise RequestTooLargeError(
                    f"Request size {len(connection_buffer)} exceeds {MAX_REQUEST_SIZE}"
                )

            # Check for complete message (newline-terminated)
            if b"\n" in connection_buffer:
                line, _, remaining = connection_buffer.partition(b"\n")
                # Preserve remaining bytes for subsequent requests
                connection_buffer.clear()
                connection_buffer.extend(remaining)
                return bytes(line)

        # Should not reach here
        return None

    async def _send_error_and_close(
        self,
        writer: asyncio.StreamWriter,
        request_id: str | None,
        error_type: ErrorType,
        message: str,
    ) -> None:
        """Send error response and close the connection."""
        response = create_error_response(
            request_id=request_id or "unknown",
            error_type=error_type,
            message=message,
        )
        try:
            writer.write(response.to_json().encode() + b"\n")
            await writer.drain()
        except Exception:  # noqa: S110
            # Best effort - connection may already be broken, silently ignore
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def _process_request(self, request_bytes: bytes) -> str:
        """Process a request and return JSON response string.

        Args:
            request_bytes: Raw request bytes (excluding newline).

        Returns:
            JSON response string.
        """
        request_id: str | None = None

        try:
            # Parse the request
            request_str = request_bytes.decode("utf-8")
            request = parse_request(request_str)
            request_id = request.id

            # Dispatch to handler
            result = await self._dispatch_request(request)

            # Build success response
            response = create_success_response(
                request_id=request_id,
                result=result,
            )
            return response.to_json()

        except (ValueError, TypeError) as e:
            # Request parsing or type error
            return create_error_response(
                request_id=request_id or "unknown",
                error_type=ErrorType.BAD_REQUEST,
                message=str(e),
            ).to_json()
        except NotFoundError as e:
            return create_error_response(
                request_id=request_id or "unknown",
                error_type=ErrorType.NOT_FOUND,
                message=str(e),
            ).to_json()
        except MCPBusyError as e:
            logger.warning(f"Provider busy: {e}")
            return create_error_response(
                request_id=request_id or "unknown",
                error_type=ErrorType.BUSY,
                message=str(e),
                details={"retry_after_ms": e.retry_after_ms},
            ).to_json()
        except MCPProviderCrashedError as e:
            logger.exception("Provider crashed")
            return create_error_response(
                request_id=request_id or "unknown",
                error_type=ErrorType.PROVIDER_CRASHED,
                message=str(e),
            ).to_json()
        except MCPTimeoutError as e:
            logger.warning(f"Request timed out: {e}")
            return create_error_response(
                request_id=request_id or "unknown",
                error_type=ErrorType.TIMEOUT,
                message=str(e),
            ).to_json()
        except MCPError as e:
            # MCPSSEError is now a subclass of MCPError, so MCPError catches both
            logger.exception("MCP communication error")
            return create_error_response(
                request_id=request_id or "unknown",
                error_type=ErrorType.JSONRPC_ERROR,
                message=str(e),
            ).to_json()
        except Exception as e:
            logger.exception("Unexpected error processing request")
            return create_error_response(
                request_id=request_id or "unknown",
                error_type=ErrorType.INTERNAL,
                message=f"Internal error: {e}",
            ).to_json()

    async def _dispatch_request(self, request: Request) -> dict[str, Any]:
        """Dispatch a request to the appropriate handler.

        Args:
            request: Parsed request object.

        Returns:
            Result dictionary to be wrapped in SuccessEnvelope.

        Raises:
            NotFoundError: If server or tool not found.
            MCPBusyError: If provider is busy.
            MCPProviderCrashedError: If provider crashed.
            MCPTimeoutError: If request timed out.
            MCPError: For other MCP errors (including SSE client errors).
        """
        if isinstance(request, ListServersRequest):
            return self._handle_list_servers(request)
        elif isinstance(request, ListToolsRequest):
            return await self._handle_list_tools(request)
        elif isinstance(request, GetServerToolRequest):
            return await self._handle_get_server_tool(request)
        elif isinstance(request, CallToolRequest):
            return await self._handle_call_tool(request)
        elif isinstance(request, HealthRequest):
            return self._handle_health(request)
        else:
            raise TypeError(f"Unknown request type: {type(request).__name__}")

    def _get_client(self, server: str) -> MCPClient:
        """Get the MCP client for a server name.

        Args:
            server: Server name.

        Returns:
            MCPClient instance.

        Raises:
            NotFoundError: If server not found.
        """
        if server not in self.clients:
            raise NotFoundError(f"Server '{server}' not found")
        return self.clients[server]

    def _handle_list_servers(self, request: ListServersRequest) -> dict[str, Any]:
        """Handle list_servers request.

        Args:
            request: ListServersRequest.

        Returns:
            ServersResponse as dict.
        """
        servers = []
        for name, client in self.clients.items():
            server_config = self.config.servers.get(name) if self.config else None
            transport = server_config.transport.value if server_config else "unknown"
            servers.append(
                ServerInfo(
                    name=name,
                    transport=transport,
                    healthy=client.is_alive(),
                )
            )
        return ServersResponse(servers=servers).to_dict()

    async def _handle_list_tools(self, request: ListToolsRequest) -> dict[str, Any]:
        """Handle list_tools request.

        Args:
            request: ListToolsRequest.

        Returns:
            Tools list dict (pass-through from MCP).

        Raises:
            NotFoundError: If server not found.
        """
        client = self._get_client(request.server)
        # Run blocking call in thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, client.list_tools)
        return result  # Pass through raw dict (matches HTTP route behavior)

    async def _handle_get_server_tool(self, request: GetServerToolRequest) -> dict[str, Any]:
        """Handle get_server_tool request.

        Note: This method calls list_tools and iterates to find the tool by name.
        The MCPClient protocol does not expose a direct get_tool() method, so we
        must fetch all tools and filter. Caching is intentionally not implemented
        to keep the server simple and stateless - tool lists can change between
        calls (tools added/removed), and caching would require TTL management,
        invalidation logic, and async-safe data structures. For typical usage
        patterns where get_server_tool is called occasionally, the simplicity
        tradeoff is acceptable.

        Args:
            request: GetServerToolRequest.

        Returns:
            Tool dict.

        Raises:
            NotFoundError: If server or tool not found.
        """
        client = self._get_client(request.server)
        # Run blocking call in thread pool (MCPClient.list_tools is synchronous)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, client.list_tools)
        for tool in result.get("tools") or []:
            if tool.get("name") == request.tool_name:
                tool_dict: dict[str, Any] = tool
                return tool_dict  # Return tool dict directly (matches HTTP route behavior)
        raise NotFoundError(f"Tool '{request.tool_name}' not found on server '{request.server}'")

    async def _handle_call_tool(self, request: CallToolRequest) -> dict[str, Any]:
        """Handle call_tool request.

        Args:
            request: CallToolRequest.

        Returns:
            MCPCallResponse as dict.

        Raises:
            NotFoundError: If server not found.
            MCPBusyError: If provider is busy.
            MCPProviderCrashedError: If provider crashed.
            MCPTimeoutError: If request timed out.
            MCPError: For other MCP errors.
        """
        client = self._get_client(request.server)
        # Run blocking call in thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: client.call_tool(
                name=request.tool,
                arguments=request.arguments,
                timeout=request.timeout_seconds,
            ),
        )
        return MCPCallResponse(result=result).to_dict()

    def _handle_health(self, request: HealthRequest) -> dict[str, Any]:
        """Handle health request.

        Returns HealthResponse with:
          - status="ok", provider="running" when at least one provider is alive
          - status="degraded", provider="down" when no providers are alive

        This mirrors the HTTP API health_check() behavior.

        Args:
            request: HealthRequest.

        Returns:
            HealthResponse as dict.
        """
        if any(client.is_alive() for client in self.clients.values()):
            return HealthResponse(status="ok", provider="running").to_dict()
        return HealthResponse(status="degraded", provider="down").to_dict()


# ---------------------------------------------------------------------------
# Server Entry Point
# ---------------------------------------------------------------------------


async def run_server(
    socket_path: str = DEFAULT_SOCKET_PATH,
    config_path: str | None = None,
) -> None:
    """Run the MCP socket server.

    Args:
        socket_path: Path to the Unix socket file.
        config_path: Optional path to MCP configuration file.
    """
    server = MCPSocketServer(
        socket_path=socket_path,
        config_path=config_path,
    )

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def handle_signal() -> None:
        logger.info("Received shutdown signal")
        server.request_shutdown()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, RuntimeError):
            logger.debug("Signal handlers not supported; skipping registration for %s", sig)

    await server.start()


def main() -> None:
    """Entry point for the MCP socket server."""
    _configure_logging()
    socket_path = os.environ.get("MCP_BRIDGE_SOCKET", DEFAULT_SOCKET_PATH)
    config_path = os.environ.get("MCP_CONFIG_PATH")

    logger.info(f"Starting MCP socket server with socket={socket_path}")

    try:
        asyncio.run(run_server(socket_path, config_path))
    except KeyboardInterrupt:
        logger.info("Server interrupted")
        sys.exit(0)


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_SOCKET_PATH",
    "MCPSocketServer",
    "main",
    "run_server",
]
