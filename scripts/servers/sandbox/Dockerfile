# Sandbox Server Dockerfile
#
# Socket server for queue-based rebase/merge operations in an isolated sandbox.
# Image name: ai-workflow/sandbox-server:dev (or use docker compose)
#
# SOCKET PATH SEMANTICS:
#   The socket path inside the container is /tmp/sandbox.sock (set via
#   SANDBOX_SOCKET_PATH env var). When using docker compose or docker run,
#   mount a host directory to /tmp to access the socket from the host.
#   Example: docker run -v /tmp/sandbox-sockets:/tmp ...
#   The socket will be available at /tmp/sandbox-sockets/sandbox.sock on host.
#
# REPO PATH SEMANTICS:
#   The repository must be mounted at /repo inside the container.
#   The sandbox will be created at /repo/.git/sandbox/
#
# SECURITY NOTE:
#   This image is intended for LOCAL DEVELOPMENT ONLY.
#   - Must NOT be exposed to untrusted networks without authentication
#   - Unix socket provides inherent network isolation
#   - For production, implement proper authentication
#
# Build:
#   docker build -t ai-workflow/sandbox-server:dev -f scripts/servers/sandbox/Dockerfile scripts/servers/sandbox/
#
# Run:
#   mkdir -p /tmp/sandbox-sockets
#   chmod 1777 /tmp/sandbox-sockets
#   docker run -v /tmp/sandbox-sockets:/tmp -v $(pwd):/repo ai-workflow/sandbox-server:dev
#   # Socket available at /tmp/sandbox-sockets/sandbox.sock
#
# Or use docker compose (recommended):
#   docker compose -p ai-workflow-devtools -f docker-compose.dev.yml up sandbox-server

# Pinned uv version for reproducible builds.
ARG UV_VERSION=0.9.12
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# Phase 1: Builder
FROM python:3.14-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Set shell to strict mode
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install uv by copying the prebuilt binary from the official image.
COPY --from=uv /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv sync.
# --frozen ensures lockfile is not modified
# --no-cache prevents caching to keep image size down
# --no-dev excludes development dependencies
RUN uv sync --frozen --no-cache --no-dev

# Phase 2: Runtime
FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime dependencies (git, ssh, gnupg for signing) and create user
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates openssh-client gnupg && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 10000 appuser && \
    useradd -u 10000 -g appuser -s /bin/bash -m appuser && \
    chown -R appuser:appuser /app

# Copy uv for any runtime needs
COPY --from=uv /uv /usr/local/bin/uv

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Create the module structure to match repo imports (scripts.servers.sandbox.*)
# This allows the same import statements to work in both Docker and repo
RUN mkdir -p /app/scripts/servers/sandbox

# Copy application code to module path
COPY --chown=appuser:appuser __init__.py constants.py operations.py protocol.py client.py server.py /app/scripts/servers/sandbox/

# Create __init__.py files for parent packages
RUN touch /app/scripts/__init__.py /app/scripts/servers/__init__.py

# Set path to use virtual environment and PYTHONPATH for module resolution
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

# DEV IMAGE ONLY: Ensure socket directory is writable by appuser and configure git
# Using '*' allows both /repo and any subdirectories like /repo/.git/sandbox
RUN chmod 1777 /tmp && \
    git config --global --add safe.directory '*'

# Switch to non-root user
USER appuser

# Re-configure git safe.directory for appuser (global config is per-user)
RUN git config --global --add safe.directory '*'

# Socket path for Unix domain socket communication
ENV SANDBOX_SOCKET_PATH=/tmp/sandbox.sock

# Repository path (must be mounted)
ENV SANDBOX_REPO_PATH=/repo

# Healthcheck: verify socket exists AND server responds to status requests
# Using Python to send a status request over the Unix socket proves the server
# is actually running and responsive, not just that a stale socket file exists
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket,json,os; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(os.environ['SANDBOX_SOCKET_PATH']); s.sendall(b'{\"command\":\"status\"}\\n'); r=s.recv(4096); s.close(); d=json.loads(r); exit(0 if d.get('status')=='success' else 1)" || exit 1

# Start the sandbox server as a module
CMD ["python", "-m", "scripts.servers.sandbox.server"]
