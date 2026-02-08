"""Tests for the post-completion hollow-out hooks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

from spec_manager.refinement.hollowed_spec.hooks import (
    on_spec_completed,
    rebuild_evidence_index,
)

SAMPLE_SPEC = """\
# Test Library

## Overview

This is a test library for unit testing the hollow-out hooks.
It contains multiple sections and paragraphs.

## Details

### Feature A

Feature A provides authentication using ENT-0001 registry.
Users authenticate with OAuth2 tokens.

### Feature B

Feature B handles payment processing.
Transactions are validated before processing.

## Error Handling

Errors are logged and reported to the monitoring system.
"""


def _mock_manager(
    tmp_path: Path, lib_id: str = "LIB-0001", spec_content: str = SAMPLE_SPEC
) -> MagicMock:
    """Create a mock WorkspaceManager with real filesystem paths."""
    manager = MagicMock()

    # Set up the directory structure
    libraries_dir = tmp_path / "libraries"
    workspace_dir = tmp_path / "workspace"

    lib_dir = libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)

    spec_path = lib_dir / "spec.md"
    spec_path.write_text(spec_content, encoding="utf-8")

    # Mock the structure properties
    type(manager.structure).libraries_dir = PropertyMock(return_value=libraries_dir)
    type(manager.structure).workspace_dir = PropertyMock(return_value=workspace_dir)

    return manager


def test_on_spec_completed_creates_hollowed_spec(tmp_path: Path):
    """Verify hollowed_spec.json is written."""
    manager = _mock_manager(tmp_path)
    on_spec_completed("LIB-0001", manager)

    hollowed_path = tmp_path / "workspace" / "evidence_store" / "LIB-0001" / "hollowed_spec.json"
    assert hollowed_path.exists()

    data = json.loads(hollowed_path.read_text(encoding="utf-8"))
    assert data["lib_id"] == "LIB-0001"
    assert data["spec_hash"]  # non-empty
    assert len(data["sections"]) > 0
    assert len(data["paragraphs"]) > 0


def test_on_spec_completed_updates_index(tmp_path: Path):
    """Verify evidence index is updated."""
    manager = _mock_manager(tmp_path)
    on_spec_completed("LIB-0001", manager)

    index_path = tmp_path / "workspace" / "indexes" / "evidence_store_index.json"
    assert index_path.exists()

    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert "LIB-0001" in data["specs"]
    assert len(data["global_keyword_index"]) > 0


def test_rebuild_index_from_multiple_specs(tmp_path: Path):
    """Verify rebuild scans all hollowed specs."""
    # Create two hollowed specs manually
    manager = _mock_manager(tmp_path)

    spec_a = "# Library A\n\n## Auth\n\nAuthentication via tokens."
    spec_b = "# Library B\n\n## Payments\n\nPayment processing pipeline."

    # Hollow both
    manager_a = _mock_manager(tmp_path, "LIB-0001", spec_a)
    on_spec_completed("LIB-0001", manager_a)

    manager_b = _mock_manager(tmp_path, "LIB-0002", spec_b)
    on_spec_completed("LIB-0002", manager_b)

    # Now rebuild
    count = rebuild_evidence_index(manager)
    assert count == 2

    index_path = tmp_path / "workspace" / "indexes" / "evidence_store_index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert "LIB-0001" in data["specs"]
    assert "LIB-0002" in data["specs"]


def test_hook_is_idempotent(tmp_path: Path):
    """Calling twice with same spec content produces same result."""
    manager = _mock_manager(tmp_path)

    on_spec_completed("LIB-0001", manager)
    hollowed_path = tmp_path / "workspace" / "evidence_store" / "LIB-0001" / "hollowed_spec.json"
    data1 = json.loads(hollowed_path.read_text(encoding="utf-8"))

    # Second call - should skip because hash is same
    on_spec_completed("LIB-0001", manager)
    data2 = json.loads(hollowed_path.read_text(encoding="utf-8"))

    assert data1["spec_hash"] == data2["spec_hash"]
    assert data1["lib_id"] == data2["lib_id"]


def test_hook_re_hollows_on_content_change(tmp_path: Path):
    """Verify spec_hash check triggers re-hollow."""
    manager = _mock_manager(tmp_path)
    on_spec_completed("LIB-0001", manager)

    hollowed_path = tmp_path / "workspace" / "evidence_store" / "LIB-0001" / "hollowed_spec.json"
    data1 = json.loads(hollowed_path.read_text(encoding="utf-8"))
    hash1 = data1["spec_hash"]

    # Change the spec content
    new_spec = "# Updated Library\n\n## New Feature\n\nCompletely different content."
    spec_path = tmp_path / "libraries" / "LIB-0001" / "spec.md"
    spec_path.write_text(new_spec, encoding="utf-8")

    on_spec_completed("LIB-0001", manager)
    data2 = json.loads(hollowed_path.read_text(encoding="utf-8"))
    hash2 = data2["spec_hash"]

    assert hash1 != hash2  # Different content = different hash
    assert data2["sections"][0]["heading"] == "Updated Library"


def test_missing_spec_md_skips(tmp_path: Path):
    """When spec.md doesn't exist, hook returns without error."""
    manager = MagicMock()
    libraries_dir = tmp_path / "libraries"
    lib_dir = libraries_dir / "LIB-MISSING"
    lib_dir.mkdir(parents=True, exist_ok=True)
    # No spec.md created

    type(manager.structure).libraries_dir = PropertyMock(return_value=libraries_dir)
    type(manager.structure).workspace_dir = PropertyMock(return_value=tmp_path / "workspace")

    # Should not raise
    on_spec_completed("LIB-MISSING", manager)

    hollowed_path = tmp_path / "workspace" / "evidence_store" / "LIB-MISSING" / "hollowed_spec.json"
    assert not hollowed_path.exists()
