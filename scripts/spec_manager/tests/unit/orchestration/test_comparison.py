"""Tests for comparison runner."""

import json
from unittest.mock import MagicMock

from spec_manager.orchestration.comparison import ComparisonRunner


SAMPLE_MANIFEST = {
    "comparison_id": "test-cmp",
    "entries": [
        {
            "profile_name": "opus",
            "run_id": "test-cmp.opus.00",
            "status": "completed",
            "arch_digest_path": "",
            "code_digest_path": "",
            "quality_scorecard_path": "",
            "duration_ms": 5000.0,
        },
        {
            "profile_name": "gpt5",
            "run_id": "test-cmp.gpt5.00",
            "status": "completed",
            "arch_digest_path": "",
            "code_digest_path": "",
            "quality_scorecard_path": "",
            "duration_ms": 3000.0,
        },
    ],
}


class TestComparisonRunner:
    def test_compare_no_judges(self, tmp_path):
        """Compare without judges produces summary and rankings."""
        runner = ComparisonRunner(
            workspace_root=tmp_path, comparison_id="test-cmp"
        )
        result = runner.compare(SAMPLE_MANIFEST)

        assert result["comparison_id"] == "test-cmp"
        assert len(result["runs"]) == 2
        assert len(result["summary"]) == 2
        assert "rankings" in result

    def test_compare_writes_files(self, tmp_path):
        """Comparison writes JSON and markdown."""
        runner = ComparisonRunner(
            workspace_root=tmp_path, comparison_id="write-cmp"
        )
        runner.compare(SAMPLE_MANIFEST)

        output_dir = (
            tmp_path / "reports" / "pdd" / "comparisons" / "write-cmp"
        )
        assert (output_dir / "comparison.json").exists()
        assert (output_dir / "comparison_report.md").exists()

    def test_compare_with_pairwise_judge(self, tmp_path):
        """Pairwise judges are invoked when provided."""
        mock_arch_judge = MagicMock()
        mock_arch_judge.compare.return_value = MagicMock(
            winner="A", scores={}
        )

        mock_code_judge = MagicMock()
        mock_code_judge.compare.return_value = MagicMock(
            winner="B", scores={}
        )

        # Write digest files so they can be loaded
        manifest = dict(SAMPLE_MANIFEST)
        manifest["entries"] = []
        for entry in SAMPLE_MANIFEST["entries"]:
            e = dict(entry)
            run_id = e["run_id"]
            reports = tmp_path / "reports" / "pdd" / run_id
            reports.mkdir(parents=True)

            arch_path = reports / "architecture_digest.json"
            arch_path.write_text(
                json.dumps({"topology": {}}), encoding="utf-8"
            )
            code_path = reports / "code_digest.json"
            code_path.write_text(
                json.dumps({"codebase": {}}), encoding="utf-8"
            )

            e["arch_digest_path"] = str(arch_path)
            e["code_digest_path"] = str(code_path)
            manifest["entries"].append(e)

        runner = ComparisonRunner(
            workspace_root=tmp_path, comparison_id="pair-cmp"
        )
        result = runner.compare(
            manifest,
            pairwise_arch_judge=mock_arch_judge,
            pairwise_code_judge=mock_code_judge,
        )

        assert len(result["pairwise"]) == 1
        assert result["pairwise"][0]["arch_winner"] == "A"
        assert result["pairwise"][0]["code_winner"] == "B"

    def test_rankings_from_pairwise(self, tmp_path):
        """Rankings count wins correctly."""
        runner = ComparisonRunner(
            workspace_root=tmp_path, comparison_id="rank-cmp"
        )

        # Create 3 completed entries
        manifest = {
            "comparison_id": "rank-cmp",
            "entries": [
                {
                    "profile_name": "a",
                    "run_id": "r.a.00",
                    "status": "completed",
                    "arch_digest_path": "",
                    "code_digest_path": "",
                    "quality_scorecard_path": "",
                    "duration_ms": 0,
                },
                {
                    "profile_name": "b",
                    "run_id": "r.b.00",
                    "status": "completed",
                    "arch_digest_path": "",
                    "code_digest_path": "",
                    "quality_scorecard_path": "",
                    "duration_ms": 0,
                },
                {
                    "profile_name": "c",
                    "run_id": "r.c.00",
                    "status": "completed",
                    "arch_digest_path": "",
                    "code_digest_path": "",
                    "quality_scorecard_path": "",
                    "duration_ms": 0,
                },
            ],
        }
        result = runner.compare(manifest)
        assert "arch_wins" in result["rankings"]
        assert "code_wins" in result["rankings"]

    def test_skips_failed_entries(self, tmp_path):
        """Failed entries are excluded from comparison."""
        manifest = {
            "comparison_id": "skip-cmp",
            "entries": [
                {
                    "profile_name": "ok",
                    "run_id": "r.ok.00",
                    "status": "completed",
                    "arch_digest_path": "",
                    "code_digest_path": "",
                    "quality_scorecard_path": "",
                    "duration_ms": 1000,
                },
                {
                    "profile_name": "bad",
                    "run_id": "r.bad.00",
                    "status": "failed",
                    "arch_digest_path": "",
                    "code_digest_path": "",
                    "quality_scorecard_path": "",
                    "duration_ms": 0,
                },
            ],
        }
        runner = ComparisonRunner(
            workspace_root=tmp_path, comparison_id="skip-cmp"
        )
        result = runner.compare(manifest)
        assert len(result["runs"]) == 1

    def test_report_markdown_content(self, tmp_path):
        """Markdown report contains expected sections."""
        runner = ComparisonRunner(
            workspace_root=tmp_path, comparison_id="md-cmp"
        )
        runner.compare(SAMPLE_MANIFEST)

        md = (
            tmp_path
            / "reports"
            / "pdd"
            / "comparisons"
            / "md-cmp"
            / "comparison_report.md"
        ).read_text()
        assert "Model Comparison Report" in md
        assert "Summary" in md
        assert "opus" in md
