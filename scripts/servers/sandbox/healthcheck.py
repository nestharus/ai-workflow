#!/usr/bin/env python3
"""Docker healthcheck script for Sandbox Server.

Connects to the sandbox server Unix socket and sends a status request.
Exits 0 on success, non-zero on failure.
"""

import json
import os
import socket
import sys


def main() -> int:
    """Check sandbox server health via Unix socket."""
    socket_path = os.environ.get("SANDBOX_SOCKET_PATH", "/tmp/sandbox.sock")

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            sock.connect(socket_path)
            sock.sendall(b'{"command":"status"}\n')
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    # EOF received before newline - incomplete response
                    partial = buf.decode("utf-8", errors="replace")
                    print(
                        f"healthcheck failed: incomplete response (EOF before newline), "
                        f"partial data: {partial!r}",
                        file=sys.stderr,
                    )
                    return 1
                buf += chunk
            response = buf.split(b"\n", 1)[0]

        data = json.loads(response)

        if data.get("status") == "success":
            return 0

        print(f"healthcheck failed: unexpected response {data}", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"healthcheck failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
