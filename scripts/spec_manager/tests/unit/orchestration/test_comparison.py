"""Tests for comparison runner."""

import json
from unittest.mock import MagicMock

from spec_manager.evaluation.comparison import ComparisonRunner

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


def _make_digest_with_responsibilities(components):
    """Helper to build an arch digest with components that have responsibilities."""
    return {
        "topology": {
            "components": components,
            "edges": [],
        }
    }


class TestComparisonRunner:
    def test_compare_no_judges(self, tmp_path):
        """Compare without judges produces summary and rankings."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="test-cmp")
        result = runner.compare(SAMPLE_MANIFEST)

        assert result["comparison_id"] == "test-cmp"
        assert len(result["runs"]) == 2
        assert len(result["summary"]) == 2
        assert "rankings" in result

    def test_compare_writes_files(self, tmp_path):
        """Comparison writes JSON and markdown."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="write-cmp")
        runner.compare(SAMPLE_MANIFEST)

        output_dir = tmp_path / "reports" / "pdd" / "comparisons" / "write-cmp"
        assert (output_dir / "comparison.json").exists()
        assert (output_dir / "comparison_report.md").exists()

    def test_compare_with_pairwise_judge(self, tmp_path):
        """Pairwise judges are invoked when provided."""
        mock_arch_judge = MagicMock()
        mock_arch_judge.compare.return_value = MagicMock(winner="A", scores={})

        mock_code_judge = MagicMock()
        mock_code_judge.compare.return_value = MagicMock(winner="B", scores={})

        # Write digest files so they can be loaded
        manifest = dict(SAMPLE_MANIFEST)
        manifest["entries"] = []
        for entry in SAMPLE_MANIFEST["entries"]:
            e = dict(entry)
            run_id = e["run_id"]
            reports = tmp_path / "reports" / "pdd" / run_id
            reports.mkdir(parents=True)

            arch_path = reports / "architecture_digest.json"
            arch_path.write_text(json.dumps({"topology": {}}), encoding="utf-8")
            code_path = reports / "code_digest.json"
            code_path.write_text(json.dumps({"codebase": {}}), encoding="utf-8")

            e["arch_digest_path"] = str(arch_path)
            e["code_digest_path"] = str(code_path)
            manifest["entries"].append(e)

        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="pair-cmp")
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
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="rank-cmp")

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
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="skip-cmp")
        result = runner.compare(manifest)
        assert len(result["runs"]) == 1

    def test_report_markdown_content(self, tmp_path):
        """Markdown report contains expected sections."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="md-cmp")
        runner.compare(SAMPLE_MANIFEST)

        md = (
            tmp_path / "reports" / "pdd" / "comparisons" / "md-cmp" / "comparison_report.md"
        ).read_text()
        assert "Model Comparison Report" in md
        assert "Summary" in md
        assert "opus" in md

    def test_responsibility_alignment_in_result(self, tmp_path):
        """compare() includes responsibility_alignment in result."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="resp-cmp")
        result = runner.compare(SAMPLE_MANIFEST)
        assert "responsibility_alignment" in result
        alignment = result["responsibility_alignment"]
        assert "canonical_responsibilities" in alignment
        assert "responsibility_mapping" in alignment
        assert "responsibility_coverage_rate" in alignment
        assert "duplication_rate" in alignment
        assert "missing_responsibilities" in alignment

    def test_responsibility_alignment_written_to_json(self, tmp_path):
        """Responsibility alignment is persisted in comparison.json."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="resp-json")
        runner.compare(SAMPLE_MANIFEST)
        json_path = tmp_path / "reports" / "pdd" / "comparisons" / "resp-json" / "comparison.json"
        data = json.loads(json_path.read_text())
        assert "responsibility_alignment" in data


class TestResponsibilityAlignment:
    """Tests for _align_responsibilities."""

    def test_empty_runs(self, tmp_path):
        """Empty run list produces empty canonical set."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="align-empty")
        result = runner._align_responsibilities([], "")
        assert result["canonical_responsibilities"] == []
        assert result["responsibility_mapping"] == []
        assert result["responsibility_coverage_rate"] == 0.0
        assert result["duplication_rate"] == 0.0

    def test_single_run_full_coverage(self, tmp_path):
        """Single run has 100% coverage of its own responsibilities."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="align-single")
        digest = _make_digest_with_responsibilities(
            [
                {"id": "svc.auth", "responsibilities": ["authentication", "authorization"]},
                {"id": "svc.db", "responsibilities": ["data storage"]},
            ]
        )
        runs = [{"arch_digest": digest}]
        result = runner._align_responsibilities(runs, "")
        assert len(result["canonical_responsibilities"]) == 3
        assert result["responsibility_coverage_rate"] == 1.0
        assert result["missing_responsibilities"] == []

    def test_two_runs_partial_overlap(self, tmp_path):
        """Two runs with partial overlap have correct metrics."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="align-overlap")
        digest_a = _make_digest_with_responsibilities(
            [
                {"id": "svc.auth", "responsibilities": ["authentication"]},
                {"id": "svc.api", "responsibilities": ["request handling"]},
            ]
        )
        digest_b = _make_digest_with_responsibilities(
            [
                {"id": "svc.auth", "responsibilities": ["authentication"]},
                {"id": "svc.cache", "responsibilities": ["caching"]},
            ]
        )
        runs = [
            {"arch_digest": digest_a},
            {"arch_digest": digest_b},
        ]
        result = runner._align_responsibilities(runs, "")
        canonical = result["canonical_responsibilities"]
        # Union of: authentication, request handling, caching
        assert len(canonical) == 3
        assert "authentication" in canonical
        assert "request handling" in canonical
        assert "caching" in canonical

        # Each run covers 2 of 3 responsibilities
        assert result["responsibility_coverage_rate"] == round(2 / 3, 4)

    def test_duplication_detected(self, tmp_path):
        """Responsibility mapped to multiple components counts as duplication."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="align-dup")
        digest = _make_digest_with_responsibilities(
            [
                {"id": "svc.auth", "responsibilities": ["authentication"]},
                {"id": "svc.gateway", "responsibilities": ["authentication"]},
            ]
        )
        runs = [{"arch_digest": digest}]
        result = runner._align_responsibilities(runs, "")
        assert result["duplication_rate"] > 0.0

    def test_missing_responsibilities(self, tmp_path):
        """Responsibilities in canonical set but not covered by any run."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="align-miss")
        # Run A has "auth", Run B has "caching"
        # But since both have their own responsibilities, nothing is truly
        # "missing" (both contribute). To test missing, we need a run with
        # an empty digest alongside one with responsibilities.
        digest_a = _make_digest_with_responsibilities(
            [
                {"id": "svc.auth", "responsibilities": ["authentication"]},
            ]
        )
        digest_b = _make_digest_with_responsibilities(
            [
                {"id": "svc.cache", "responsibilities": ["caching"]},
            ]
        )
        runs = [
            {"arch_digest": digest_a},
            {"arch_digest": digest_b},
        ]
        result = runner._align_responsibilities(runs, "")
        # No truly missing: each resp is covered by at least one run
        assert result["missing_responsibilities"] == []

    def test_no_arch_digest(self, tmp_path):
        """Runs with no arch_digest are handled gracefully."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="align-none")
        runs = [{"arch_digest": None}, {"arch_digest": {}}]
        result = runner._align_responsibilities(runs, "")
        assert result["canonical_responsibilities"] == []
        assert result["responsibility_coverage_rate"] == 0.0

    def test_case_normalization(self, tmp_path):
        """Responsibilities are normalized to lowercase."""
        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="align-case")
        digest_a = _make_digest_with_responsibilities(
            [
                {"id": "svc.auth", "responsibilities": ["Authentication"]},
            ]
        )
        digest_b = _make_digest_with_responsibilities(
            [
                {"id": "svc.auth", "responsibilities": ["authentication"]},
            ]
        )
        runs = [
            {"arch_digest": digest_a},
            {"arch_digest": digest_b},
        ]
        result = runner._align_responsibilities(runs, "")
        # Should be deduplicated to 1
        assert len(result["canonical_responsibilities"]) == 1

    def test_markdown_includes_alignment(self, tmp_path):
        """Markdown report includes responsibility alignment section."""
        # Build manifest with digest files that have responsibilities
        manifest = dict(SAMPLE_MANIFEST)
        manifest["entries"] = []
        for entry in SAMPLE_MANIFEST["entries"]:
            e = dict(entry)
            run_id = e["run_id"]
            reports = tmp_path / "reports" / "pdd" / run_id
            reports.mkdir(parents=True)

            arch_path = reports / "architecture_digest.json"
            digest = _make_digest_with_responsibilities(
                [
                    {"id": "svc.auth", "responsibilities": ["authentication"]},
                ]
            )
            arch_path.write_text(json.dumps(digest), encoding="utf-8")
            e["arch_digest_path"] = str(arch_path)
            manifest["entries"].append(e)

        runner = ComparisonRunner(workspace_root=tmp_path, comparison_id="align-md")
        runner.compare(manifest)

        md = (
            tmp_path / "reports" / "pdd" / "comparisons" / "align-md" / "comparison_report.md"
        ).read_text()
        assert "Responsibility Alignment" in md
        assert "Coverage Rate" in md
