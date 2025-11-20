# Phase 1: Builder
# Base image exists and project targets Python 3.14.
FROM python:3.14-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Set shell to strict mode
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install uv by copying the prebuilt binary from the official image
# This is the official practice from uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock README.md LICENSE ./

# Install dependencies
RUN uv sync --frozen --no-cache

# Copy application code
COPY app ./app
COPY scripts ./scripts
COPY tools ./tools

# Install the project
RUN uv pip install --no-cache .

# Phase 2: Runtime
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

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application code and scripts
COPY --from=builder --chown=appuser:appuser /app/app /app/app
COPY --from=builder --chown=appuser:appuser /app/scripts /app/scripts
COPY --from=builder --chown=appuser:appuser /app/pyproject.toml /app/pyproject.toml
COPY --from=builder --chown=appuser:appuser /app/README.md /app/README.md
COPY --from=builder --chown=appuser:appuser /app/LICENSE /app/LICENSE

# Set path to use virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start the application
CMD ["start-server", "--host", "0.0.0.0", "--port", "8000"]
