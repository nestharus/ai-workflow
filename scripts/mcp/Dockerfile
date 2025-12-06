# MCP Bridge Dockerfile (NES-47, NES-68)
#
# REST-to-MCP bridge server that exposes MCP tools via Unix socket.
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
#   docker build -t ai-workflow/mcp-bridge:dev -f scripts/mcp/Dockerfile scripts/mcp/
#
# Run (Unix socket - recommended for Docker):
#   mkdir -p /tmp/mcp-sockets
#   docker run -v /tmp/mcp-sockets:/tmp ai-workflow/mcp-bridge:dev
#   # Socket available at /tmp/mcp-sockets/mcp-bridge.sock
#
# Run (HTTP mode - for host-based uvicorn without Docker):
#   uvicorn app.main:app --host 127.0.0.1 --port 8080
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

# Copy dependency file
COPY pyproject.toml ./pyproject.toml

# Install dependencies using uv sync.
# Fails fast if dependencies cannot be resolved (no fallback).
# --frozen ensures lockfile is not modified
# --no-cache prevents caching to keep image size down
# --no-dev excludes development dependencies
RUN uv sync --frozen --no-cache --no-dev

# Copy application code (new structure)
COPY app ./app
COPY client ./client

# Phase 2: Runtime
# This is using the same image as the builder
FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime dependencies (curl for healthcheck; unpinned for timely security fixes) and create user
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 10000 appuser && \
    useradd -u 10000 -g appuser -s /bin/bash -m appuser && \
    chown -R appuser:appuser /app

# Copy uv and uvx for mcp-background-job
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=uv /uvx /usr/local/bin/uvx

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application code
COPY --from=builder --chown=appuser:appuser /app/app /app/app
COPY --from=builder --chown=appuser:appuser /app/client /app/client

# Set path to use virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# DEV IMAGE ONLY: Ensure socket directory is writable by appuser for arbitrary
# host-mounted socket directories. Do NOT copy this pattern to production images.
RUN chmod 1777 /tmp

# Switch to non-root user
USER appuser

# Socket path for Unix domain socket communication
ENV MCP_BRIDGE_SOCKET=/tmp/mcp-bridge.sock

# Add healthcheck using Unix socket
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f --unix-socket ${MCP_BRIDGE_SOCKET} http://localhost/health || exit 1

# Start the application using Unix socket
# Shell form required for MCP_BRIDGE_SOCKET variable expansion (acceptable for local dev image)
# hadolint ignore=DL3025
CMD uvicorn app.main:app --uds ${MCP_BRIDGE_SOCKET}
