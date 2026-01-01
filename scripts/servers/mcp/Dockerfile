# MCP Bridge Dockerfile
#
# Socket-based MCP bridge server that exposes MCP tools via Unix socket.
# Image name: ai-workflow/mcp-bridge:dev (or use docker-compose)
#
# SOCKET PATH SEMANTICS:
#   The socket path inside the container is /tmp/mcp-bridge.sock (set via
#   MCP_BRIDGE_SOCKET env var). When using docker-compose or docker run,
#   mount a host directory to /tmp to access the socket from the host.
#   Example: docker run -v /tmp/mcp-sockets:/tmp ...
#   The socket will be available at /tmp/mcp-sockets/mcp-bridge.sock on host.
#
# SECURITY NOTE:
#   This image is intended for LOCAL DEVELOPMENT ONLY.
#   - Must NOT be exposed to untrusted networks without authentication
#   - Unix socket provides inherent network isolation
#   - For production, implement proper authentication
#
# Build:
#   docker build -t ai-workflow/mcp-bridge:dev -f scripts/servers/mcp/Dockerfile scripts/servers/mcp/
#
# Run (Unix socket - recommended for Docker):
#   mkdir -p /tmp/mcp-sockets
#   chmod 1777 /tmp/mcp-sockets  # Required: appuser (UID 10000) must have write access
#   docker run -v /tmp/mcp-sockets:/tmp ai-workflow/mcp-bridge:dev
#   # Socket available at /tmp/mcp-sockets/mcp-bridge.sock
#
# NOTE: When using host bind mounts (as above), the host directory must be
# writable by UID 10000 (appuser). Named volumes (used by docker-compose) do
# not require this step as Docker manages permissions automatically.
#
# Or use docker-compose (recommended):
#   docker-compose up mcp-bridge

# Pinned uv version for reproducible builds.
ARG UV_VERSION=0.9.12
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# Phase 1: Builder
# Base image exists and project targets Python 3.14.
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
# Fails fast if dependencies cannot be resolved (no fallback).
# --frozen ensures lockfile is not modified
# --no-cache prevents caching to keep image size down
# --no-dev excludes development dependencies
RUN uv sync --frozen --no-cache --no-dev

# Copy application code maintaining import structure
# The server uses absolute imports like scripts.servers.mcp.config
# so we recreate the package structure under /app
COPY server ./scripts/servers/mcp/server
COPY server_impl.py ./scripts/servers/mcp/server_impl.py
COPY protocol.py ./scripts/servers/mcp/protocol.py
COPY config.py ./scripts/servers/mcp/config.py
COPY manager.py ./scripts/servers/mcp/manager.py
COPY sse_client.py ./scripts/servers/mcp/sse_client.py
COPY __init__.py ./scripts/servers/mcp/__init__.py
COPY healthcheck.py ./scripts/servers/mcp/healthcheck.py
# Create parent package __init__.py files
RUN mkdir -p scripts/servers && \
    touch scripts/__init__.py && \
    touch scripts/servers/__init__.py

# Phase 2: Runtime
# This is using the same image as the builder
FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime dependencies (unpinned for timely security fixes) and create user
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 10000 appuser && \
    useradd -u 10000 -g appuser -s /bin/bash -m appuser && \
    chown -R appuser:appuser /app

# Copy uv and uvx for mcp-background-job
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=uv /uvx /usr/local/bin/uvx

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application code with package structure
COPY --from=builder --chown=appuser:appuser /app/scripts /app/scripts

# Set path to use virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# DEV IMAGE ONLY: Ensure socket directory is writable by appuser for arbitrary
# host-mounted socket directories. Do NOT copy this pattern to production images.
RUN chmod 1777 /tmp

# Switch to non-root user
USER appuser

# Socket path for Unix domain socket communication
ENV MCP_BRIDGE_SOCKET=/tmp/mcp-bridge.sock

# Add healthcheck using external script for maintainability
# Sends JSONL health request via Unix socket and checks response status
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "/app/scripts/servers/mcp/healthcheck.py"]

# Start the socket server using exec form for proper signal handling
CMD ["python", "-m", "scripts.servers.mcp.server"]
