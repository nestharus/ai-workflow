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
#   docker build -t ai-workflow/sandbox-server:dev -f scripts/pr/sandbox/Dockerfile .
#
# Run:
#   mkdir -p /tmp/sandbox-sockets
#   chmod 1777 /tmp/sandbox-sockets
#   docker run -v /tmp/sandbox-sockets:/tmp -v $(pwd):/repo ai-workflow/sandbox-server:dev
#   # Socket available at /tmp/sandbox-sockets/sandbox.sock
#
# Or use docker compose (recommended):
#   docker compose -f scripts/pr/sandbox/docker-compose.yml up

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

# Copy dependency file and scripts package
COPY pyproject.toml ./pyproject.toml
COPY scripts ./scripts

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

# Install runtime dependencies (git is required) and create user
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 10000 appuser && \
    useradd -u 10000 -g appuser -s /bin/bash -m appuser && \
    chown -R appuser:appuser /app

# Copy uv for any runtime needs
COPY --from=uv /uv /usr/local/bin/uv

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy scripts package
COPY --from=builder --chown=appuser:appuser /app/scripts /app/scripts

# Set path to use virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# DEV IMAGE ONLY: Ensure socket directory is writable by appuser
RUN chmod 1777 /tmp

# Switch to non-root user
USER appuser

# Socket path for Unix domain socket communication
ENV SANDBOX_SOCKET_PATH=/tmp/sandbox.sock

# Repository path (must be mounted)
ENV SANDBOX_REPO_PATH=/repo

# Healthcheck: verify socket exists AND server responds to status requests
# Using Python to send a status request over the Unix socket proves the server
# is actually running and responsive, not just that a stale socket file exists
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket,json,os; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(os.environ['SANDBOX_SOCKET_PATH']); s.sendall(b'{\"command\":\"status\"}\\n'); r=s.recv(4096); s.close(); d=json.loads(r); exit(0 if d.get('status')=='success' else 1)" || exit 1

# Start the sandbox server
CMD ["python", "-m", "scripts.pr.sandbox.server"]
