"""Tests for digest builders."""

import json

from spec_manager.orchestration.digests import (
    build_architecture_digest,
    build_code_digest,
    _build_topology,
    _count_severity,
    _top_files_by_findings,
    _build_file_list,
    _load_json,
)


class TestBuildArchitectureDigest:
    def test_with_manifest(self, tmp_path):
        """Build arch digest from component manifest."""
        run_id = "test-run"
        reports = tmp_path / "reports" / "pdd" / run_id
        reports.mkdir(parents=True)
        (reports / "component_manifest.json").write_text(
            json.dumps({
                "components": [
                    {"component_id": "svc.auth", "type": "service", "depends_on": ["svc.db"]},
                    {"component_id": "svc.db", "type": "service", "depends_on": []},
                ]
            }),
            encoding="utf-8",
        )

        digest = build_architecture_digest(tmp_path, run_id)
        assert digest["run_id"] == run_id
        assert len(digest["topology"]["components"]) == 2
        assert len(digest["topology"]["edges"]) == 1
        assert digest["topology"]["edges"][0]["from"] == "svc.auth"
        assert digest["topology"]["edges"][0]["to"] == "svc.db"

    def test_empty_workspace(self, tmp_path):
        """Digest with no artifacts returns empty structures."""
        digest = build_architecture_digest(tmp_path, "empty-run")
        assert digest["run_id"] == "empty-run"
        assert digest["topology"]["components"] == []
        assert digest["topology"]["edges"] == []
        assert digest["coverage"]["requirements_total"] == 0

    def test_with_findings(self, tmp_path):
        """L2 findings are counted by severity."""
        run_id = "findings-run"
        reports = tmp_path / "reports" / "pdd" / run_id
        reports.mkdir(parents=True)
        (reports / "code_quality_report.json").write_text(
            json.dumps({
                "findings": [
                    {"severity": "MAJOR", "file": "a.py"},
                    {"severity": "MINOR", "file": "b.py"},
                    {"severity": "MAJOR", "file": "c.py"},
                ]
            }),
            encoding="utf-8",
        )

        digest = build_architecture_digest(tmp_path, run_id)
        assert digest["l2_review"]["final_findings"]["MAJOR"] == 2
        assert digest["l2_review"]["final_findings"]["MINOR"] == 1

    def test_falls_back_to_global_reports(self, tmp_path):
        """Uses global reports when run-scoped not available."""
        reports = tmp_path / "reports"
        reports.mkdir(parents=True)
        (reports / "component_manifest.json").write_text(
            json.dumps({"components": [{"component_id": "global-comp"}]}),
            encoding="utf-8",
        )

        digest = build_architecture_digest(tmp_path, "no-local")
        assert len(digest["topology"]["components"]) == 1
        assert digest["topology"]["components"][0]["id"] == "global-comp"


class TestBuildCodeDigest:
    def test_with_snapshot(self, tmp_path):
        """Build code digest from snapshot directory."""
        run_id = "code-run"
        snapshot_dir = tmp_path / ".pdd_runs" / run_id / "snapshot" / "files"
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "module.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
        (snapshot_dir / "util.py").write_text("a\nb\n", encoding="utf-8")

        digest = build_code_digest(tmp_path, run_id)
        assert digest["run_id"] == run_id
        assert digest["codebase"]["totals"]["files"] == 2
        assert digest["codebase"]["totals"]["loc"] > 0

    def test_empty_workspace(self, tmp_path):
        """Code digest with no files."""
        digest = build_code_digest(tmp_path, "empty")
        assert digest["codebase"]["totals"]["files"] == 0
        assert digest["codebase"]["totals"]["loc"] == 0

    def test_with_ci_results(self, tmp_path):
        """CI results are included."""
        run_id = "ci-run"
        ci_dir = tmp_path / ".pdd_runs" / run_id / "ci"
        ci_dir.mkdir(parents=True)
        (ci_dir / "results.json").write_text(
            json.dumps({"final_pass": True, "first_pass": False}),
            encoding="utf-8",
        )

        digest = build_code_digest(tmp_path, run_id)
        assert digest["ci"]["final_pass"] is True
        assert digest["ci"]["first_pass"] is False


class TestHelpers:
    def test_load_json_missing(self, tmp_path):
        assert _load_json(tmp_path / "nope.json") is None

    def test_load_json_corrupt(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert _load_json(bad) is None

    def test_load_json_valid(self, tmp_path):
        good = tmp_path / "good.json"
        good.write_text('{"key": "value"}', encoding="utf-8")
        result = _load_json(good)
        assert result == {"key": "value"}

    def test_build_topology(self):
        components = [
            {"component_id": "a", "type": "service", "depends_on": ["b"]},
            {"component_id": "b", "type": "lib", "depends_on": []},
        ]
        topo = _build_topology(components)
        assert len(topo["components"]) == 2
        assert len(topo["edges"]) == 1

    def test_count_severity(self):
        findings = [
            {"severity": "MAJOR"}, {"severity": "MINOR"},
            {"severity": "BLOCKER"}, {"severity": "MAJOR"},
        ]
        counts = _count_severity(findings)
        assert counts == {"BLOCKER": 1, "MAJOR": 2, "MINOR": 1}

    def test_top_files_by_findings(self):
        findings = [
            {"file": "a.py", "severity": "MAJOR"},
            {"file": "a.py", "severity": "MAJOR"},
            {"file": "b.py", "severity": "MINOR"},
            {"file": "c.py", "severity": "MAJOR"},
        ]
        top = _top_files_by_findings(findings, k=2)
        assert len(top) == 2
        assert top[0]["path"] == "a.py"

    def test_build_file_list(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
        files = _build_file_list(tmp_path)
        assert len(files) >= 1
        assert any(f["path"].endswith("main.py") for f in files)

    def test_build_file_list_empty(self, tmp_path):
        files = _build_file_list(tmp_path / "nonexistent")
        assert files == []
