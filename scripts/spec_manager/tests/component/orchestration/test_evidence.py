"""Component tests for orchestration.evidence module.

Tests EvidenceBundle construction, save/load round-trip, Ref types,
and iter_dir path computation.
"""

from __future__ import annotations

import json
from pathlib import Path

from spec_manager.orchestration.evidence import (
    DemotionsRef,
    DiffRef,
    EvidenceBundle,
    FactsRef,
    GapReportRef,
    GatesReportRef,
    GraphDeltaRef,
    GraphSnapshotRef,
    ImplementationRef,
    IntegrationRef,
    ManifestRef,
    PinsSnapshotRef,
    PlanRef,
    PromotionReportRef,
    ProvenanceBlock,
    RefinementRef,
    SourceIndexRef,
    TestsRef,
    UnderSpecRef,
    VerificationRef,
)


# ======================================================================
# Ref type construction
# ======================================================================


class TestRefTypeConstruction:
    """Test that all Ref dataclasses construct with correct defaults."""

    def test_manifest_ref_defaults(self) -> None:
        """ManifestRef initializes with empty fields."""
        ref = ManifestRef()
        assert ref.path == ""
        assert ref.files == []
        assert ref.slice_patterns == []
        assert ref.generated_files == []

    def test_diff_ref_defaults(self) -> None:
        """DiffRef initializes with empty fields."""
        ref = DiffRef()
        assert ref.path == ""
        assert ref.base_commit == ""
        assert ref.head_commit == ""
        assert ref.changed_files == []
        assert ref.content_hash == ""

    def test_provenance_block_defaults(self) -> None:
        """ProvenanceBlock initializes with empty fields."""
        ref = ProvenanceBlock()
        assert ref.path == ""
        assert ref.entries == []

    def test_source_index_ref_defaults(self) -> None:
        """SourceIndexRef initializes with empty fields."""
        ref = SourceIndexRef()
        assert ref.path == ""
        assert ref.entries == []

    def test_facts_ref_defaults(self) -> None:
        """FactsRef initializes with empty dicts and lists."""
        ref = FactsRef()
        assert ref.path == ""
        assert ref.functions == {}
        assert ref.stores == {}
        assert ref.atoms == {}
        assert ref.constraints_refs == []
        assert ref.llm_claims == []

    def test_gap_report_ref_defaults(self) -> None:
        """GapReportRef initializes with empty lists."""
        ref = GapReportRef()
        assert ref.path == ""
        assert ref.open_gaps == []
        assert ref.stagnation == {}

    def test_plan_ref_defaults(self) -> None:
        """PlanRef initializes with empty lists."""
        ref = PlanRef()
        assert ref.path == ""
        assert ref.intentions == []
        assert ref.edit_targets == []
        assert ref.test_plan == []
        assert ref.risks == []

    def test_implementation_ref_defaults(self) -> None:
        """ImplementationRef initializes with empty lists."""
        ref = ImplementationRef()
        assert ref.patch_path == ""
        assert ref.result_path == ""
        assert ref.applied_edits == []
        assert ref.pin_proposals == []
        assert ref.edge_proposals == []
        assert ref.under_spec_events == []
        assert ref.tests_added == []

    def test_under_spec_ref_defaults(self) -> None:
        """UnderSpecRef initializes with empty lists."""
        ref = UnderSpecRef()
        assert ref.path == ""
        assert ref.decisions == []
        assert ref.blockers == []

    def test_pins_snapshot_ref_defaults(self) -> None:
        """PinsSnapshotRef initializes with default version."""
        ref = PinsSnapshotRef()
        assert ref.path == ""
        assert ref.snapshot_hash == ""
        assert ref.schema_version == "1"

    def test_graph_snapshot_ref_defaults(self) -> None:
        """GraphSnapshotRef initializes with default version."""
        ref = GraphSnapshotRef()
        assert ref.path == ""
        assert ref.snapshot_hash == ""
        assert ref.schema_version == "1"

    def test_graph_delta_ref_defaults(self) -> None:
        """GraphDeltaRef initializes with empty fields."""
        ref = GraphDeltaRef()
        assert ref.path == ""
        assert ref.delta_type == ""
        assert ref.produced_by == ""

    def test_promotion_report_ref_defaults(self) -> None:
        """PromotionReportRef initializes with empty path."""
        ref = PromotionReportRef()
        assert ref.path == ""

    def test_gates_report_ref_defaults(self) -> None:
        """GatesReportRef initializes with empty lists."""
        ref = GatesReportRef()
        assert ref.path == ""
        assert ref.gates == []

    def test_refinement_ref_defaults(self) -> None:
        """RefinementRef initializes with empty path."""
        ref = RefinementRef()
        assert ref.path == ""

    def test_integration_ref_defaults(self) -> None:
        """IntegrationRef initializes with empty path."""
        ref = IntegrationRef()
        assert ref.path == ""

    def test_tests_ref_defaults(self) -> None:
        """TestsRef initializes with empty paths."""
        ref = TestsRef()
        assert ref.slice_path == ""
        assert ref.full_path == ""

    def test_verification_ref_defaults(self) -> None:
        """VerificationRef initializes with empty path."""
        ref = VerificationRef()
        assert ref.path == ""

    def test_demotions_ref_defaults(self) -> None:
        """DemotionsRef initializes with empty lists."""
        ref = DemotionsRef()
        assert ref.path == ""
        assert ref.emitted == []
        assert ref.applied == []
        assert ref.pending == []


# ======================================================================
# Ref types with data
# ======================================================================


class TestRefTypesWithData:
    """Test Ref dataclasses can be constructed with explicit data."""

    def test_manifest_ref_with_files(self) -> None:
        """ManifestRef can hold file entries."""
        ref = ManifestRef(
            path="manifest.json",
            files=[{"path": "a.py", "hash": "abc"}],
            slice_patterns=["**/*.py"],
            generated_files=["gen.py"],
        )
        assert len(ref.files) == 1
        assert ref.files[0]["path"] == "a.py"

    def test_graph_delta_ref_with_data(self) -> None:
        """GraphDeltaRef stores delta metadata."""
        ref = GraphDeltaRef(
            path="delta.json",
            delta_type="pin_proposal",
            produced_by="PromoteStep",
        )
        assert ref.delta_type == "pin_proposal"
        assert ref.produced_by == "PromoteStep"

    def test_list_fields_not_shared(self) -> None:
        """Mutable default fields are not shared across instances."""
        r1 = ManifestRef()
        r2 = ManifestRef()
        r1.files.append({"path": "x.py"})
        assert r2.files == []


# ======================================================================
# EvidenceBundle construction
# ======================================================================


class TestEvidenceBundleConstruction:
    """Test EvidenceBundle construction and default values."""

    def test_defaults(self) -> None:
        """EvidenceBundle initializes with empty/default fields."""
        bundle = EvidenceBundle()
        assert bundle.run_id == ""
        assert bundle.slice_id == ""
        assert bundle.iteration == 0
        assert bundle.created_at == ""
        assert bundle.mode == "auto"
        assert bundle.workspace_root == ""
        assert bundle.slice_root == ""
        assert bundle.status == "IN_PROGRESS"

    def test_nested_refs_are_default_instances(self) -> None:
        """All nested Ref fields are default-constructed instances."""
        bundle = EvidenceBundle()
        assert isinstance(bundle.manifest, ManifestRef)
        assert isinstance(bundle.diff, DiffRef)
        assert isinstance(bundle.provenance, ProvenanceBlock)
        assert isinstance(bundle.source_index, SourceIndexRef)
        assert isinstance(bundle.facts, FactsRef)
        assert isinstance(bundle.gaps, GapReportRef)
        assert isinstance(bundle.plan, PlanRef)
        assert isinstance(bundle.implementation, ImplementationRef)
        assert isinstance(bundle.under_spec, UnderSpecRef)
        assert isinstance(bundle.pins_snapshot, PinsSnapshotRef)
        assert isinstance(bundle.graph_snapshot, GraphSnapshotRef)
        assert isinstance(bundle.graph_deltas, list)
        assert isinstance(bundle.promotion, PromotionReportRef)
        assert isinstance(bundle.gates, GatesReportRef)
        assert isinstance(bundle.refinement, RefinementRef)
        assert isinstance(bundle.integration, IntegrationRef)
        assert isinstance(bundle.tests, TestsRef)
        assert isinstance(bundle.verification, VerificationRef)
        assert isinstance(bundle.demotions, DemotionsRef)

    def test_construction_with_identity(self) -> None:
        """EvidenceBundle can be constructed with identity fields."""
        bundle = EvidenceBundle(
            run_id="run-42",
            slice_id="slice-auth",
            iteration=3,
            mode="interactive",
            workspace_root="/tmp/ws",
            slice_root="/tmp/ws/slices/auth",
        )
        assert bundle.run_id == "run-42"
        assert bundle.slice_id == "slice-auth"
        assert bundle.iteration == 3
        assert bundle.mode == "interactive"

    def test_nested_refs_not_shared(self) -> None:
        """Each EvidenceBundle has its own Ref instances."""
        b1 = EvidenceBundle()
        b2 = EvidenceBundle()
        b1.manifest.files.append({"path": "x.py"})
        assert b2.manifest.files == []


# ======================================================================
# iter_dir
# ======================================================================


class TestEvidenceBundleIterDir:
    """Test EvidenceBundle.iter_dir path computation."""

    def test_iter_dir_format(self, tmp_path: Path) -> None:
        """iter_dir returns .pdd_runs/<run_id>/slices/<slice_id>/iter_NNN."""
        bundle = EvidenceBundle(
            run_id="run-1",
            slice_id="auth-service",
            iteration=5,
        )
        result = bundle.iter_dir(tmp_path)
        expected = tmp_path / ".pdd_runs" / "run-1" / "slices" / "auth-service" / "iter_005"
        assert result == expected

    def test_iter_dir_zero_padded(self, tmp_path: Path) -> None:
        """Iteration number is zero-padded to 3 digits."""
        bundle = EvidenceBundle(run_id="r", slice_id="s", iteration=1)
        assert bundle.iter_dir(tmp_path).name == "iter_001"

        bundle2 = EvidenceBundle(run_id="r", slice_id="s", iteration=99)
        assert bundle2.iter_dir(tmp_path).name == "iter_099"

        bundle3 = EvidenceBundle(run_id="r", slice_id="s", iteration=100)
        assert bundle3.iter_dir(tmp_path).name == "iter_100"


# ======================================================================
# save / load round-trip
# ======================================================================


class TestEvidenceBundleSaveLoad:
    """Test EvidenceBundle save/load serialization round-trip."""

    def test_save_creates_bundle_json(self, tmp_path: Path) -> None:
        """save() creates bundle.json at the correct path."""
        bundle = EvidenceBundle(
            run_id="run-1",
            slice_id="auth",
            iteration=1,
        )
        result_path = bundle.save(tmp_path)

        expected = tmp_path / ".pdd_runs" / "run-1" / "slices" / "auth" / "iter_001" / "bundle.json"
        assert result_path == expected
        assert result_path.exists()

    def test_save_creates_valid_json(self, tmp_path: Path) -> None:
        """save() writes valid JSON content."""
        bundle = EvidenceBundle(run_id="run-1", slice_id="s1", iteration=1)
        result_path = bundle.save(tmp_path)

        data = json.loads(result_path.read_text(encoding="utf-8"))
        assert data["run_id"] == "run-1"
        assert data["slice_id"] == "s1"
        assert data["iteration"] == 1

    def test_save_creates_intermediate_directories(self, tmp_path: Path) -> None:
        """save() creates all intermediate directories if needed."""
        bundle = EvidenceBundle(run_id="deep-run", slice_id="deep-slice", iteration=42)
        result_path = bundle.save(tmp_path)
        assert result_path.parent.exists()

    def test_round_trip_identity_fields(self, tmp_path: Path) -> None:
        """save() then load() preserves identity fields."""
        original = EvidenceBundle(
            run_id="run-42",
            slice_id="auth-slice",
            iteration=7,
            mode="interactive",
            workspace_root="/ws",
            slice_root="/ws/auth",
            status="COMPLETE",
        )
        path = original.save(tmp_path)
        loaded = EvidenceBundle.load(path)

        assert loaded.run_id == original.run_id
        assert loaded.slice_id == original.slice_id
        assert loaded.iteration == original.iteration
        assert loaded.mode == original.mode
        assert loaded.workspace_root == original.workspace_root
        assert loaded.slice_root == original.slice_root
        assert loaded.status == original.status

    def test_round_trip_manifest_data(self, tmp_path: Path) -> None:
        """save() then load() preserves manifest data."""
        original = EvidenceBundle(run_id="r", slice_id="s", iteration=1)
        original.manifest = ManifestRef(
            path="m.json",
            files=[{"path": "a.py", "hash": "abc"}],
        )
        path = original.save(tmp_path)
        loaded = EvidenceBundle.load(path)

        assert loaded.manifest.path == "m.json"
        assert len(loaded.manifest.files) == 1
        assert loaded.manifest.files[0]["path"] == "a.py"

    def test_round_trip_gaps_data(self, tmp_path: Path) -> None:
        """save() then load() preserves gap report data."""
        original = EvidenceBundle(run_id="r", slice_id="s", iteration=1)
        original.gaps = GapReportRef(
            open_gaps=[{"file": "x.py", "kind": "stub"}],
        )
        path = original.save(tmp_path)
        loaded = EvidenceBundle.load(path)

        assert len(loaded.gaps.open_gaps) == 1
        assert loaded.gaps.open_gaps[0]["file"] == "x.py"

    def test_round_trip_graph_deltas(self, tmp_path: Path) -> None:
        """save() then load() preserves graph deltas list."""
        original = EvidenceBundle(run_id="r", slice_id="s", iteration=1)
        original.graph_deltas = [
            GraphDeltaRef(path="d1.json", delta_type="pin_proposal", produced_by="P5"),
        ]
        path = original.save(tmp_path)
        loaded = EvidenceBundle.load(path)

        assert len(loaded.graph_deltas) == 1
        delta = loaded.graph_deltas[0]
        assert delta.path == "d1.json"
        assert delta.delta_type == "pin_proposal"
