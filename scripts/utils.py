"""Shared utilities for review wrapper scripts."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_timestamp() -> str:
    """Return a UTC timestamp string in ISO 8601 basic format."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
