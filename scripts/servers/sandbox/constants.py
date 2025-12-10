"""Shared constants for the sandbox package.

Centralizes configuration constants used by both client and server
to avoid circular dependency issues.
"""

from __future__ import annotations

# Default socket path (matches docker-compose bind mount location)
# Container: /tmp/sandbox.sock -> Host: /tmp/sandbox-sockets/sandbox.sock
DEFAULT_SOCKET_PATH = "/tmp/sandbox-sockets/sandbox.sock"
