"""Tests for planner.constraints.bootstrap — parsing and seeding."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_manager.planner.constraints.bootstrap import (
    _classify_constraint_subtype,
    _parse_constraints_md,
    bootstrap_constraints_from_intake,
)
from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter
from spec_manager.planner.constraints.types import ConstraintIndexEntry


# ===================================================================
# _parse_constraints_md
# ===================================================================


class TestParseConstraintsMd:
    def test_single_marker(self):
        content = "([=CON-LIB-001]) Auth must use OAuth2\nUse RFC 6749."
        result = _parse_constraints_md(content)
        assert len(result) == 1
        eid, heading, body = result[0]
        assert eid == "CON-LIB-001"
        assert "Auth must use OAuth2" in heading
        assert "Use RFC 6749" in body

    def test_multiple_markers(self):
        content = (
            "([=CON-LIB-001]) First constraint\nBody one.\n\n"
            "([=CON-LIB-002]) Second constraint\nBody two."
        )
        result = _parse_constraints_md(content)
        assert len(result) == 2
        assert result[0][0] == "CON-LIB-001"
        assert result[1][0] == "CON-LIB-002"

    def test_empty_content(self):
        assert _parse_constraints_md("") == []

    def test_no_markers(self):
        assert _parse_constraints_md("Just some text\nwithout markers.") == []

    def test_marker_only_no_body(self):
        content = "([=CON-001]) Header only"
        result = _parse_constraints_md(content)
        assert len(result) == 1
        assert result[0][0] == "CON-001"
        assert result[0][2] == ""  # empty body

    def test_multiline_body(self):
        content = "([=CON-X]) Title\nLine 1\nLine 2\nLine 3"
        result = _parse_constraints_md(content)
        assert len(result) == 1
        assert "Line 1" in result[0][2]
        assert "Line 3" in result[0][2]

    def test_marker_case_insensitive(self):
        content = "([=con-lib-001]) Lower case marker\nBody."
        result = _parse_constraints_md(content)
        assert len(result) == 1
        assert result[0][0] == "con-lib-001"

    def test_heading_strips_marker(self):
        content = "([=CON-001]) This is the heading"
        result = _parse_constraints_md(content)
        assert "([=" not in result[0][1]
        assert "This is the heading" in result[0][1]

    def test_body_is_trimmed(self):
        content = "([=C1]) Title\n\n  body text  \n\n"
        result = _parse_constraints_md(content)
        assert result[0][2] == "body text"

    def test_marker_with_numbers(self):
        content = "([=CON-123-ABC]) Title\nBody."
        result = _parse_constraints_md(content)
        assert result[0][0] == "CON-123-ABC"


# ===================================================================
# _classify_constraint_subtype
# ===================================================================


class TestClassifyConstraintSubtype:
    def test_performance_keyword(self):
        entry = _classify_constraint_subtype("CON-1", "Latency must be under 200ms")
        assert entry.subtype == "performance"

    def test_security_keyword(self):
        entry = _classify_constraint_subtype("CON-2", "Auth tokens must be encrypted")
        assert entry.subtype == "security"

    def test_api_contract_keyword(self):
        entry = _classify_constraint_subtype("CON-3", "REST API endpoint must return JSON")
        assert entry.subtype == "api_contract"

    def test_data_model_keyword(self):
        entry = _classify_constraint_subtype("CON-4", "Database schema must have audit column")
        assert entry.subtype == "data_model"

    def test_general_fallback(self):
        entry = _classify_constraint_subtype("CON-5", "Keep things simple")
        assert entry.subtype == "general"

    def test_system_scope_from_id(self):
        entry = _classify_constraint_subtype("CON-SYS-001", "Global policy")
        assert entry.scope_hint == "system"

    def test_inter_scope_from_text(self):
        entry = _classify_constraint_subtype("CON-1", "Cross-library communication")
        assert entry.scope_hint == "inter"

    def test_intra_scope_default(self):
        entry = _classify_constraint_subtype("CON-LIB-001", "Internal detail")
        assert entry.scope_hint == "intra"

    def test_entities_extracted(self):
        entry = _classify_constraint_subtype("CON-1", "PaymentEngine must call Stripe")
        assert "PaymentEngine" in entry.entities
        assert "Stripe" in entry.entities

    def test_text_preview_truncated(self):
        long_text = "A" * 200
        entry = _classify_constraint_subtype("CON-1", long_text)
        assert entry.text_preview.endswith("...")
        assert len(entry.text_preview) < 200

    def test_text_preview_short_text(self):
        entry = _classify_constraint_subtype("CON-1", "Short")
        assert entry.text_preview == "Short"
        assert not entry.text_preview.endswith("...")

    def test_element_id_preserved(self):
        entry = _classify_constraint_subtype("CON-LIB-999", "some text")
        assert entry.element_id == "CON-LIB-999"

    def test_return_type(self):
        entry = _classify_constraint_subtype("C", "text")
        assert isinstance(entry, ConstraintIndexEntry)


# ===================================================================
# bootstrap_constraints_from_intake
# ===================================================================


class TestBootstrapConstraintsFromIntake:
    def test_single_library(self, tmp_path: Path):
        libs = tmp_path / "libraries"
        lib_a = libs / "lib_a"
        lib_a.mkdir(parents=True)
        (lib_a / "constraints.md").write_text(
            "([=CON-A-001]) Must use UTF-8\nAll text encoding is UTF-8.\n",
            encoding="utf-8",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = bootstrap_constraints_from_intake(workspace, libs)
        assert result == {"lib_a": 1}

        adapter = ConstraintStoreAdapter(workspace)
        facts = adapter.load_merged("lib_a")
        assert len(facts) == 1
        assert facts[0].constraint_id == "CON-A-001"

    def test_multiple_libraries(self, tmp_path: Path):
        libs = tmp_path / "libraries"
        for name in ["alpha", "beta"]:
            d = libs / name
            d.mkdir(parents=True)
            (d / "constraints.md").write_text(
                f"([=CON-{name.upper()}-001]) Constraint for {name}\nDetails.\n",
                encoding="utf-8",
            )
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = bootstrap_constraints_from_intake(workspace, libs)
        assert set(result.keys()) == {"alpha", "beta"}

    def test_system_constraints(self, tmp_path: Path):
        libs = tmp_path / "libraries"
        libs.mkdir()
        sys_dir = tmp_path / "system"
        sys_dir.mkdir()
        (sys_dir / "constraints.md").write_text(
            "([=CON-SYS-001]) Global logging policy\nUse structured logging.\n",
            encoding="utf-8",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = bootstrap_constraints_from_intake(workspace, libs, system_dir=sys_dir)
        assert "__system__" in result
        assert result["__system__"] == 1

    def test_empty_libraries_dir(self, tmp_path: Path):
        libs = tmp_path / "libraries"
        libs.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = bootstrap_constraints_from_intake(workspace, libs)
        assert result == {}

    def test_library_without_constraints_md(self, tmp_path: Path):
        libs = tmp_path / "libraries"
        (libs / "empty_lib").mkdir(parents=True)
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = bootstrap_constraints_from_intake(workspace, libs)
        assert result == {}

    def test_constraints_md_with_no_markers(self, tmp_path: Path):
        libs = tmp_path / "libraries"
        lib_a = libs / "lib_a"
        lib_a.mkdir(parents=True)
        (lib_a / "constraints.md").write_text("No markers here.", encoding="utf-8")
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = bootstrap_constraints_from_intake(workspace, libs)
        assert result == {}

    def test_nonexistent_system_dir(self, tmp_path: Path):
        libs = tmp_path / "libraries"
        libs.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        nonexistent = tmp_path / "nope"

        result = bootstrap_constraints_from_intake(workspace, libs, system_dir=nonexistent)
        assert result == {}
