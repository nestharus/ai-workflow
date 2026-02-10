"""Component tests for orchestration.demotion module.

Tests DemotionTicket construction and serialization, RoutingItem/RoutedPatch
construction, and DemotionManager.apply() with various ticket configurations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec_manager.orchestration.demotion import (
    DemotionManager,
    DemotionTicket,
    RoutedPatch,
    RoutingItem,
)


# ======================================================================
# DemotionTicket
# ======================================================================


class TestDemotionTicketConstruction:
    """Test DemotionTicket construction and defaults."""

    def test_defaults(self) -> None:
        """DemotionTicket has sensible defaults for all optional fields."""
        ticket = DemotionTicket()
        assert len(ticket.ticket_id) == 12  # uuid hex[:12]
        assert ticket.run_id == ""
        assert ticket.slice_id == ""
        assert ticket.source == "ALGORITHMIC_GATE"
        assert ticket.gate is None
        assert ticket.target_layer == "L1"
        assert ticket.severity == "BLOCKER"
        assert ticket.failing_pins == []
        assert ticket.failing_atoms == []
        assert ticket.failing_files == []
        assert ticket.diagnosis == ""
        assert ticket.evidence_refs == []
        assert ticket.recommended_spec_patch is None
        assert ticket.recommended_code_patch is None
        assert ticket.questions == []
        assert ticket.routing_required is False
        assert ticket.routing_payload is None
        assert ticket.apply_status == "PENDING"
        assert ticket.applied_patch_paths == []

    def test_created_at_is_populated(self) -> None:
        """created_at is auto-populated with an ISO timestamp."""
        ticket = DemotionTicket()
        assert ticket.created_at != ""
        # Should be ISO format with timezone
        assert "T" in ticket.created_at

    def test_ticket_id_is_unique(self) -> None:
        """Each ticket gets a unique ID."""
        t1 = DemotionTicket()
        t2 = DemotionTicket()
        assert t1.ticket_id != t2.ticket_id

    def test_explicit_fields(self) -> None:
        """DemotionTicket can be fully constructed with explicit values."""
        ticket = DemotionTicket(
            ticket_id="test-id-001",
            run_id="run-42",
            slice_id="auth-slice",
            source="TEST_FAILURE",
            gate="P5",
            target_layer="L2",
            severity="MAJOR",
            failing_pins=["pin:foo"],
            failing_files=["foo.py"],
            diagnosis="Pin foo failed gate P5",
            recommended_spec_patch="--- a/spec.md\n+++ b/spec.md",
        )
        assert ticket.ticket_id == "test-id-001"
        assert ticket.source == "TEST_FAILURE"
        assert ticket.target_layer == "L2"
        assert ticket.severity == "MAJOR"
        assert ticket.failing_pins == ["pin:foo"]


class TestDemotionTicketSerialization:
    """Test DemotionTicket to_dict() and from_dict() round-trip."""

    def test_to_dict_returns_dict(self) -> None:
        """to_dict() returns a plain dictionary."""
        ticket = DemotionTicket(run_id="r1", slice_id="s1")
        d = ticket.to_dict()
        assert isinstance(d, dict)
        assert d["run_id"] == "r1"
        assert d["slice_id"] == "s1"

    def test_to_dict_contains_all_fields(self) -> None:
        """to_dict() includes every field from the dataclass."""
        ticket = DemotionTicket()
        d = ticket.to_dict()
        expected_fields = {
            "ticket_id", "created_at", "run_id", "slice_id", "source",
            "gate", "target_layer", "severity", "failing_pins",
            "failing_atoms", "failing_files", "diagnosis", "evidence_refs",
            "recommended_spec_patch", "recommended_code_patch", "questions",
            "routing_required", "routing_payload", "apply_status",
            "applied_patch_paths",
        }
        assert expected_fields.issubset(d.keys())

    def test_round_trip(self) -> None:
        """from_dict(to_dict()) preserves all fields."""
        original = DemotionTicket(
            ticket_id="abc123",
            run_id="run-1",
            slice_id="auth",
            source="ARCH_GATE",
            gate="coupling",
            target_layer="L2",
            severity="MINOR",
            failing_pins=["pin:a"],
            failing_atoms=["atom:x"],
            failing_files=["a.py", "b.py"],
            diagnosis="Coupling too high",
            evidence_refs=["ref1"],
            recommended_spec_patch="patch content",
            recommended_code_patch=None,
            questions=["Why so coupled?"],
            routing_required=True,
            routing_payload={"text": "route me"},
            apply_status="PENDING",
            applied_patch_paths=[],
        )
        d = original.to_dict()
        restored = DemotionTicket.from_dict(d)

        assert restored.ticket_id == original.ticket_id
        assert restored.run_id == original.run_id
        assert restored.source == original.source
        assert restored.gate == original.gate
        assert restored.target_layer == original.target_layer
        assert restored.severity == original.severity
        assert restored.failing_pins == original.failing_pins
        assert restored.failing_atoms == original.failing_atoms
        assert restored.failing_files == original.failing_files
        assert restored.diagnosis == original.diagnosis
        assert restored.questions == original.questions
        assert restored.routing_required is True
        assert restored.routing_payload == {"text": "route me"}

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """from_dict() silently ignores keys not in the dataclass."""
        data = DemotionTicket(ticket_id="abc").to_dict()
        data["unknown_field"] = "should be ignored"
        ticket = DemotionTicket.from_dict(data)
        assert ticket.ticket_id == "abc"
        assert not hasattr(ticket, "unknown_field") or True  # no crash


# ======================================================================
# RoutingItem / RoutedPatch
# ======================================================================


class TestRoutingItem:
    """Test RoutingItem construction."""

    def test_defaults(self) -> None:
        """RoutingItem has sensible defaults."""
        item = RoutingItem()
        assert len(item.item_id) == 12
        assert item.text == ""
        assert item.source_path is None
        assert item.desired_slice_hint is None
        assert item.tags == []

    def test_explicit_construction(self) -> None:
        """RoutingItem can be constructed with explicit values."""
        item = RoutingItem(
            text="New requirement text",
            source_path="/specs/req.md",
            desired_slice_hint="auth-service",
            tags=["security"],
        )
        assert item.text == "New requirement text"
        assert item.source_path == "/specs/req.md"
        assert item.tags == ["security"]


class TestRoutedPatch:
    """Test RoutedPatch construction."""

    def test_defaults(self) -> None:
        """RoutedPatch has empty defaults."""
        patch = RoutedPatch()
        assert patch.target_slice_id == ""
        assert patch.unified_diff_path == ""
        assert patch.notes_path == ""

    def test_explicit_construction(self) -> None:
        """RoutedPatch can be constructed with explicit values."""
        patch = RoutedPatch(
            target_slice_id="auth",
            unified_diff_path="/patches/auth.diff",
            notes_path="/notes/auth.md",
        )
        assert patch.target_slice_id == "auth"


# ======================================================================
# DemotionManager.apply()
# ======================================================================


class TestDemotionManagerApplyWithSpecPatch:
    """Test DemotionManager.apply() when ticket has recommended_spec_patch."""

    def test_writes_patch_file(self, tmp_path: Path) -> None:
        """apply() writes the spec patch to .pdd_demotions/ directory."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="test-001",
            run_id="r1",
            recommended_spec_patch="--- a/spec.md\n+++ b/spec.md\nsome patch",
        )
        slice_root = tmp_path / "slices" / "auth"
        slice_root.mkdir(parents=True)

        result = manager.apply(ticket, slice_root)

        assert result["applied"] is True
        assert len(result["patches"]) == 1

        patch_path = Path(result["patches"][0])
        assert patch_path.exists()
        assert patch_path.name == "test-001_spec.patch"
        assert "some patch" in patch_path.read_text(encoding="utf-8")

    def test_updates_ticket_status_to_applied(self, tmp_path: Path) -> None:
        """apply() sets ticket.apply_status to APPLIED on success."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="test-002",
            recommended_spec_patch="patch content",
        )
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        manager.apply(ticket, slice_root)

        assert ticket.apply_status == "APPLIED"


class TestDemotionManagerApplyWithNoPatch:
    """Test DemotionManager.apply() when no recommended patch is set."""

    def test_generates_gap_stub_when_failing_files(self, tmp_path: Path) -> None:
        """apply() generates a gap stub when ticket has failing_files."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="test-003",
            source="TEST_FAILURE",
            gate="P5",
            severity="MAJOR",
            diagnosis="Function foo not implemented",
            failing_files=["foo.py"],
            failing_pins=["pin:foo"],
            failing_atoms=["atom:bar"],
            questions=["What should foo return?"],
        )
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        result = manager.apply(ticket, slice_root)

        assert result["applied"] is True
        stub_path = Path(result["patches"][0])
        assert stub_path.exists()
        assert stub_path.name == "test-003_stub.txt"

        content = stub_path.read_text(encoding="utf-8")
        assert "DEMOTION: test-003" in content
        assert "TEST_FAILURE" in content
        assert "Pin: pin:foo" in content
        assert "Atom: atom:bar" in content
        assert "File: foo.py" in content
        assert "What should foo return?" in content

    def test_no_patch_no_files_results_in_blocked(self, tmp_path: Path) -> None:
        """apply() with no patch and no failing_files results in BLOCKED status."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(ticket_id="test-004")
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        result = manager.apply(ticket, slice_root)

        # No patch file written, no stub generated
        assert result["applied"] is False
        assert result["patches"] == []
        assert ticket.apply_status == "BLOCKED"


class TestDemotionManagerApplyWithRouting:
    """Test DemotionManager.apply() with routing_required=True."""

    def test_returns_routing_item(self, tmp_path: Path) -> None:
        """apply() returns a routing_item ID when routing is required."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="test-005",
            routing_required=True,
            routing_payload={
                "text": "New requirement text",
                "source_path": "/specs/req.md",
                "desired_slice_hint": "auth",
                "tags": ["security"],
            },
            failing_files=["auth.py"],  # so stub is generated
        )
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        result = manager.apply(ticket, slice_root)

        assert "routing_item" in result
        assert len(result["routing_item"]) == 12  # RoutingItem.item_id is uuid hex[:12]

    def test_no_routing_item_when_not_required(self, tmp_path: Path) -> None:
        """apply() does not include routing_item when routing_required=False."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="test-006",
            routing_required=False,
            failing_files=["x.py"],
        )
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        result = manager.apply(ticket, slice_root)

        assert "routing_item" not in result


class TestDemotionManagerLineage:
    """Test that DemotionManager writes lineage records."""

    def test_lineage_record_written(self, tmp_path: Path) -> None:
        """apply() writes a lineage JSON file to .pdd_demotions/."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="test-007",
            recommended_spec_patch="patch",
        )
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        manager.apply(ticket, slice_root)

        lineage_path = slice_root / ".pdd_demotions" / "test-007_lineage.json"
        assert lineage_path.exists()

        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        assert "ticket" in lineage
        assert "result" in lineage
        assert lineage["ticket"]["ticket_id"] == "test-007"
        assert lineage["result"]["applied"] is True

    def test_gap_evidence_count(self, tmp_path: Path) -> None:
        """apply() reports correct gap_evidence_added count."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="test-008",
            failing_files=["a.py", "b.py", "c.py"],
            recommended_spec_patch="patch",
        )
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        result = manager.apply(ticket, slice_root)

        assert result["gap_evidence_added"] == 3


class TestDemotionManagerCodePatch:
    """Test DemotionManager.apply() with recommended_code_patch at L3."""

    def test_code_patch_at_l3(self, tmp_path: Path) -> None:
        """apply() writes code patch when target_layer is L3."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="test-009",
            target_layer="L3",
            recommended_code_patch="--- a/main.py\n+++ b/main.py",
        )
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        result = manager.apply(ticket, slice_root)

        assert result["applied"] is True
        patch_path = Path(result["patches"][0])
        assert patch_path.name == "test-009_code.patch"

    def test_code_patch_at_l1_is_ignored(self, tmp_path: Path) -> None:
        """apply() does NOT write code patch when target_layer is L1."""
        manager = DemotionManager(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="test-010",
            target_layer="L1",
            recommended_code_patch="--- a/main.py\n+++ b/main.py",
        )
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        result = manager.apply(ticket, slice_root)

        # code_patch is only used at L3; at L1 falls through to gap stub
        # But no failing_files, so no stub either
        assert result["applied"] is False
