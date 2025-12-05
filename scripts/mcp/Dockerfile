# MCP Bridge Dockerfile (NES-47)
#
# REST-to-MCP bridge server that exposes MCP tools via HTTP.
# Image name: ai-workflow/mcp-bridge:dev (or use docker-compose)
#
# SECURITY NOTE:
#   This image is intended for LOCAL DEVELOPMENT ONLY.
#   - Must NOT be exposed to untrusted networks without authentication
#   - For non-local deployments, place behind an authenticated TLS-terminating proxy
#   - Default uvicorn host is 0.0.0.0 (required for Docker networking)
#   - docker-compose.yml binds port to 127.0.0.1 for local-only access
#
# Build:
#   docker build -t ai-workflow/mcp-bridge:dev -f scripts/mcp/Dockerfile scripts/mcp/
#
# Run:
#   docker run -p 127.0.0.1:8080:8080 ai-workflow/mcp-bridge:dev
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

# Install dependencies
RUN uv sync --frozen --no-cache --no-dev || uv pip install --no-cache -r pyproject.toml

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

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Start the application using the app module path
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
