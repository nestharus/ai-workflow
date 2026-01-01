#!/usr/bin/env python3
"""Docker healthcheck script for MCP Bridge.

Connects to the MCP bridge Unix socket and sends a health check request.
Exits 0 on success, non-zero on failure.
"""

import json
import os
import socket
import sys

MAX_RESPONSE_SIZE = 65536  # 64KB limit for health check response


def main() -> int:
    """Check MCP bridge health via Unix socket."""
    socket_path = os.environ.get("MCP_BRIDGE_SOCKET", "/tmp/mcp-bridge.sock")

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            sock.connect(socket_path)
            sock.sendall(b'{"method":"health","id":"hc"}\n')
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_RESPONSE_SIZE:
                    print(
                        f"healthcheck failed: response exceeded {MAX_RESPONSE_SIZE} bytes",
                        file=sys.stderr,
                    )
                    return 1
            response = buf.split(b"\n", 1)[0]

        data = json.loads(response)
        result = data.get("result") or {}

        if data.get("status") == "success" and result.get("status") == "ok":
            return 0

        print(f"healthcheck failed: unexpected response {data}", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"healthcheck failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
