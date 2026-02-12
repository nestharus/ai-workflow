"""Tests for multi-model runner."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from spec_manager.orchestration.model_profile import ModelProfile
from spec_manager.orchestration.multi_model_runner import (
    MultiModelRunConfig,
    MultiModelRunner,
    RunManifestEntry,
)


class TestRunManifestEntry:
    def test_defaults(self):
        entry = RunManifestEntry()
        assert entry.profile_name == ""
        assert entry.status == ""

    def test_fields(self):
        entry = RunManifestEntry(
            profile_name="opus",
            run_id="cmp.opus.00",
            replicate=0,
            status="completed",
            duration_ms=5000.0,
        )
        assert entry.profile_name == "opus"
        assert entry.run_id == "cmp.opus.00"


class TestMultiModelRunConfig:
    def test_defaults(self):
        config = MultiModelRunConfig()
        assert config.comparison_id == ""
        assert config.profiles == []
        assert config.runs_per_model == 1
        assert config.compute_quality is True


_PATCH_PREFIX = "spec_manager.orchestration.multi_model_runner"


class TestMultiModelRunner:
    @patch(f"{_PATCH_PREFIX}.PddLifecycle")
    @patch(f"{_PATCH_PREFIX}.WorkspaceManager")
    @patch(f"{_PATCH_PREFIX}.snapshot_run")
    @patch(f"{_PATCH_PREFIX}.build_architecture_digest")
    @patch(f"{_PATCH_PREFIX}.build_code_digest")
    @patch(f"{_PATCH_PREFIX}.QualityReporter")
    def test_run_single_profile(
        self,
        mock_reporter_cls,
        mock_code_digest,
        mock_arch_digest,
        mock_snapshot,
        mock_ws_cls,
        mock_lifecycle_cls,
        tmp_path,
    ):
        """Run with a single profile produces manifest."""
        mock_arch_digest.return_value = {"run_id": "test", "topology": {}}
        mock_code_digest.return_value = {"run_id": "test", "codebase": {}}
        mock_snapshot.return_value = tmp_path / "snapshot.json"

        mock_reporter = MagicMock()
        mock_reporter.compute.return_value = MagicMock(to_dict=lambda: {})
        mock_reporter.write.return_value = (tmp_path / "q.json", tmp_path / "q.md")
        mock_reporter_cls.return_value = mock_reporter

        runner = MultiModelRunner(
            workspace_root=tmp_path,
            input_folder=tmp_path / "specs",
        )
        profiles = [ModelProfile(name="opus", producer_model_id="claude-opus-4")]
        manifest = runner.run(profiles, comparison_id="test-cmp")

        assert manifest["comparison_id"] == "test-cmp"
        assert len(manifest["entries"]) == 1
        assert manifest["entries"][0]["profile_name"] == "opus"
        assert manifest["entries"][0]["status"] == "completed"

    @patch(f"{_PATCH_PREFIX}.PddLifecycle")
    @patch(f"{_PATCH_PREFIX}.WorkspaceManager")
    @patch(f"{_PATCH_PREFIX}.snapshot_run")
    @patch(f"{_PATCH_PREFIX}.build_architecture_digest")
    @patch(f"{_PATCH_PREFIX}.build_code_digest")
    @patch(f"{_PATCH_PREFIX}.QualityReporter")
    def test_run_multiple_profiles(
        self,
        mock_reporter_cls,
        mock_code_digest,
        mock_arch_digest,
        mock_snapshot,
        mock_ws_cls,
        mock_lifecycle_cls,
        tmp_path,
    ):
        """Run with multiple profiles produces entries for each."""
        mock_arch_digest.return_value = {"run_id": "test", "topology": {}}
        mock_code_digest.return_value = {"run_id": "test", "codebase": {}}
        mock_snapshot.return_value = tmp_path / "snapshot.json"

        mock_reporter = MagicMock()
        mock_reporter.compute.return_value = MagicMock(to_dict=lambda: {})
        mock_reporter.write.return_value = (tmp_path / "q.json", tmp_path / "q.md")
        mock_reporter_cls.return_value = mock_reporter

        runner = MultiModelRunner(
            workspace_root=tmp_path,
            input_folder=tmp_path / "specs",
        )
        profiles = [
            ModelProfile(name="opus", producer_model_id="claude-opus-4"),
            ModelProfile(name="gpt5", producer_model_id="gpt-5.3"),
        ]
        manifest = runner.run(profiles, comparison_id="multi-cmp")

        assert len(manifest["entries"]) == 2
        names = [e["profile_name"] for e in manifest["entries"]]
        assert "opus" in names
        assert "gpt5" in names

    @patch(f"{_PATCH_PREFIX}.PddLifecycle")
    @patch(f"{_PATCH_PREFIX}.WorkspaceManager")
    def test_run_handles_failure(self, mock_ws_cls, mock_lifecycle_cls, tmp_path):
        """Failed pipeline run records 'failed' status."""
        mock_lifecycle_cls.return_value.run.side_effect = RuntimeError("boom")

        runner = MultiModelRunner(
            workspace_root=tmp_path,
            input_folder=tmp_path / "specs",
        )
        profiles = [ModelProfile(name="broken", producer_model_id="nope")]
        manifest = runner.run(profiles, comparison_id="fail-cmp")

        assert manifest["entries"][0]["status"] == "failed"

    def test_manifest_written_to_disk(self, tmp_path):
        """Manifest JSON file is written."""
        with (
            patch(f"{_PATCH_PREFIX}.PddLifecycle"),
            patch(f"{_PATCH_PREFIX}.WorkspaceManager"),
            patch(f"{_PATCH_PREFIX}.snapshot_run") as mock_snap,
            patch(f"{_PATCH_PREFIX}.build_architecture_digest") as mock_ad,
            patch(f"{_PATCH_PREFIX}.build_code_digest") as mock_cd,
            patch(f"{_PATCH_PREFIX}.QualityReporter") as mock_qr,
        ):
            mock_ad.return_value = {}
            mock_cd.return_value = {}
            mock_snap.return_value = tmp_path / "s.json"
            mock_qr_inst = MagicMock()
            mock_qr_inst.compute.return_value = MagicMock(to_dict=lambda: {})
            mock_qr_inst.write.return_value = (
                tmp_path / "q.json",
                tmp_path / "q.md",
            )
            mock_qr.return_value = mock_qr_inst

            runner = MultiModelRunner(
                workspace_root=tmp_path,
                input_folder=tmp_path,
            )
            runner.run([ModelProfile(name="t")], comparison_id="disk-test")

            manifest_path = (
                tmp_path
                / "reports"
                / "pdd"
                / "comparisons"
                / "disk-test"
                / "manifest.json"
            )
            assert manifest_path.exists()
