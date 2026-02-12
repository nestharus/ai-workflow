"""Tests for run snapshot."""

import json

from spec_manager.evaluation.snapshot import snapshot_run


class TestSnapshotRun:
    def test_basic_snapshot(self, tmp_path):
        """Snapshot copies reports and writes manifest."""
        run_id = "snap-test"
        reports = tmp_path / "reports" / "pdd" / run_id
        reports.mkdir(parents=True)
        (reports / "test_report.json").write_text('{"key": "val"}', encoding="utf-8")

        manifest_path = snapshot_run(tmp_path, run_id)
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["run_id"] == run_id
        assert manifest["file_count"] >= 1

        # Verify COMPLETE marker
        complete = tmp_path / ".pdd_runs" / run_id / "snapshot" / "COMPLETE"
        assert complete.exists()

    def test_snapshot_preserves_hashes(self, tmp_path):
        """SHA-256 hashes are recorded for each file."""
        run_id = "hash-test"
        reports = tmp_path / "reports" / "pdd" / run_id
        reports.mkdir(parents=True)
        content = '{"data": 42}'
        (reports / "data.json").write_text(content, encoding="utf-8")

        manifest_path = snapshot_run(tmp_path, run_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert len(manifest["files"]) >= 1
        entry = manifest["files"][0]
        assert "sha256" in entry
        assert len(entry["sha256"]) == 64  # hex SHA-256

    def test_snapshot_copies_files(self, tmp_path):
        """Files are actually copied to snapshot directory."""
        run_id = "copy-test"
        reports = tmp_path / "reports" / "pdd" / run_id
        reports.mkdir(parents=True)
        (reports / "report.json").write_text('{"x": 1}', encoding="utf-8")

        snapshot_run(tmp_path, run_id)

        copied = tmp_path / ".pdd_runs" / run_id / "snapshot" / "files" / "reports" / "report.json"
        assert copied.exists()
        assert json.loads(copied.read_text(encoding="utf-8")) == {"x": 1}

    def test_snapshot_includes_slices(self, tmp_path):
        """Slice evidence is included in snapshot."""
        run_id = "slice-test"
        slices = tmp_path / ".pdd_runs" / run_id / "slices"
        slices.mkdir(parents=True)
        (slices / "slice1.json").write_text('{"evidence": true}', encoding="utf-8")

        manifest_path = snapshot_run(tmp_path, run_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["file_count"] >= 1

    def test_empty_run(self, tmp_path):
        """Snapshot with no artifacts still writes manifest."""
        run_id = "empty"
        manifest_path = snapshot_run(tmp_path, run_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["file_count"] == 0
        assert manifest["files"] == []

    def test_snapshot_includes_demotions(self, tmp_path):
        """Demotion ledger is included in snapshot."""
        run_id = "demo-test"
        demotions = tmp_path / ".pdd_runs" / run_id / "demotions"
        demotions.mkdir(parents=True)
        (demotions / "ledger.jsonl").write_text('{"ticket": 1}\n', encoding="utf-8")

        manifest_path = snapshot_run(tmp_path, run_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["file_count"] >= 1
