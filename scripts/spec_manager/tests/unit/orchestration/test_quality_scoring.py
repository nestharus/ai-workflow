"""Tests for quality scoring framework."""

import json
from pathlib import Path

from spec_manager.orchestration.quality_scoring import (
    ArchitectureQualityScorer,
    CodeQualityScorer,
    QualityMetric,
    QualityReporter,
    QualityScorecard,
    SpecFidelityScorer,
    _clamp01,
    _quality_status,
    _threshold_status,
)


SAMPLE_ARCH_DIGEST = {
    "topology": {
        "components": [
            {"id": "svc.auth", "type": "service", "depends_on": ["svc.db"]},
            {"id": "svc.db", "type": "service", "depends_on": []},
            {"id": "svc.api", "type": "service", "depends_on": ["svc.auth"]},
        ],
        "edges": [
            {"from": "svc.auth", "to": "svc.db"},
            {"from": "svc.api", "to": "svc.auth"},
        ],
    },
    "coverage": {"requirements_total": 10, "requirements_mapped": 8, "unmapped_requirements": []},
    "l2_review": {"final_findings": {"BLOCKER": 0, "MAJOR": 1, "MINOR": 3}},
}

SAMPLE_CODE_DIGEST = {
    "codebase": {
        "files": [
            {"path": "auth.py", "loc": 200},
            {"path": "db.py", "loc": 150},
            {"path": "api.py", "loc": 300},
        ],
        "totals": {"files": 3, "loc": 650},
    },
    "l3_review": {
        "final_findings": {"BLOCKER": 0, "MAJOR": 2, "MINOR": 5},
        "top_files": [],
    },
    "ci": {"final_pass": True},
}


class TestHelpers:
    def test_clamp01(self):
        assert _clamp01(0.5) == 0.5
        assert _clamp01(-0.1) == 0.0
        assert _clamp01(1.5) == 1.0

    def test_threshold_status(self):
        assert _threshold_status(0.9) == "PASS"
        assert _threshold_status(0.8) == "PASS"
        assert _threshold_status(0.7) == "WARN"
        assert _threshold_status(0.65) == "WARN"
        assert _threshold_status(0.5) == "FAIL"

    def test_quality_status(self):
        assert _quality_status(0.9, False, False) == "PASS"
        assert _quality_status(0.9, True, False) == "FAIL"
        assert _quality_status(0.9, False, True) == "WARN"
        assert _quality_status(0.5, False, False) == "FAIL"


class TestQualityMetric:
    def test_to_dict(self):
        m = QualityMetric(name="test", raw=1.0, score=0.8, status="PASS", detail="ok")
        d = m.to_dict()
        assert d["name"] == "test"
        assert d["score"] == 0.8


class TestQualityScorecard:
    def test_to_dict(self):
        sc = QualityScorecard(
            run_id="r1",
            arch_quality_score=0.85,
            code_quality_score=0.75,
            overall_status="WARN",
        )
        d = sc.to_dict()
        assert d["run_id"] == "r1"
        assert d["arch_quality_score"] == 0.85
        assert d["overall_status"] == "WARN"


class TestArchitectureQualityScorer:
    def test_compute_metrics(self):
        scorer = ArchitectureQualityScorer()
        metrics = scorer.compute(SAMPLE_ARCH_DIGEST)
        names = [m.name for m in metrics]
        assert "arch.graph_health" in names
        assert "arch.coupling" in names
        assert "arch.completeness" in names
        assert "arch.l2_severity" in names

    def test_mechanical_score(self):
        scorer = ArchitectureQualityScorer()
        metrics = scorer.compute(SAMPLE_ARCH_DIGEST)
        score = scorer.mechanical_score(metrics)
        assert 0.0 <= score <= 1.0

    def test_empty_digest(self):
        scorer = ArchitectureQualityScorer()
        metrics = scorer.compute({"topology": {"components": [], "edges": []}, "coverage": {}, "l2_review": {}})
        score = scorer.mechanical_score(metrics)
        assert 0.0 <= score <= 1.0

    def test_cycle_detection(self):
        scorer = ArchitectureQualityScorer()
        components = [
            {"id": "a", "depends_on": ["b"]},
            {"id": "b", "depends_on": ["a"]},
        ]
        edges = [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]
        assert scorer._detect_cycles(components, edges) is True

    def test_no_cycles(self):
        scorer = ArchitectureQualityScorer()
        components = [
            {"id": "a", "depends_on": ["b"]},
            {"id": "b", "depends_on": []},
        ]
        edges = [{"from": "a", "to": "b"}]
        assert scorer._detect_cycles(components, edges) is False

    def test_completeness_full_coverage(self):
        scorer = ArchitectureQualityScorer()
        digest = {
            "topology": {"components": [], "edges": []},
            "coverage": {"requirements_total": 10, "requirements_mapped": 10},
            "l2_review": {"final_findings": {}},
        }
        metrics = scorer.compute(digest)
        completeness = next(m for m in metrics if m.name == "arch.completeness")
        assert completeness.score == 1.0

    def test_high_severity_findings(self):
        scorer = ArchitectureQualityScorer()
        digest = {
            "topology": {"components": [], "edges": []},
            "coverage": {},
            "l2_review": {"final_findings": {"BLOCKER": 3, "MAJOR": 5, "MINOR": 10}},
        }
        metrics = scorer.compute(digest)
        severity = next(m for m in metrics if m.name == "arch.l2_severity")
        assert severity.score < 0.5  # High severity should produce low score


class TestCodeQualityScorer:
    def test_compute_metrics(self):
        scorer = CodeQualityScorer()
        metrics = scorer.compute(SAMPLE_CODE_DIGEST)
        names = [m.name for m in metrics]
        assert "code.issue_density" in names
        assert "code.file_size_outliers" in names
        assert "code.churn" in names

    def test_mechanical_score(self):
        scorer = CodeQualityScorer()
        metrics = scorer.compute(SAMPLE_CODE_DIGEST)
        score = scorer.mechanical_score(metrics)
        assert 0.0 <= score <= 1.0

    def test_empty_digest(self):
        scorer = CodeQualityScorer()
        metrics = scorer.compute({"codebase": {"files": [], "totals": {"loc": 0}}, "l3_review": {}})
        score = scorer.mechanical_score(metrics)
        assert 0.0 <= score <= 1.0


class TestSpecFidelityScorer:
    def test_with_output(self):
        scorer = SpecFidelityScorer()
        metrics = scorer.compute({
            "coverage_estimate": 0.85,
            "missing": ["Feature X"],
            "hallucinated": [],
        })
        assert len(metrics) == 1
        assert metrics[0].score == 0.85
        assert metrics[0].status == "PASS"

    def test_with_hallucinations(self):
        scorer = SpecFidelityScorer()
        metrics = scorer.compute({
            "coverage_estimate": 0.9,
            "missing": [],
            "hallucinated": ["Invented feature"],
        })
        assert metrics[0].status == "WARN"

    def test_no_output(self):
        scorer = SpecFidelityScorer()
        metrics = scorer.compute(None)
        assert metrics[0].status == "FAIL"


class TestQualityReporter:
    def test_compute_no_judges(self):
        reporter = QualityReporter(workspace_root=Path("/tmp"), run_id="test")
        scorecard = reporter.compute(SAMPLE_ARCH_DIGEST, SAMPLE_CODE_DIGEST)
        assert isinstance(scorecard, QualityScorecard)
        assert scorecard.run_id == "test"
        assert 0.0 <= scorecard.arch_quality_score <= 1.0
        assert 0.0 <= scorecard.code_quality_score <= 1.0

    def test_compute_with_judges(self):
        reporter = QualityReporter(workspace_root=Path("/tmp"), run_id="test")
        scorecard = reporter.compute(
            SAMPLE_ARCH_DIGEST,
            SAMPLE_CODE_DIGEST,
            arch_judge_output={"overall": 4, "risks": [], "scores": {}, "strengths": []},
            code_judge_output={"overall": 4, "systemic_risks": [], "files": []},
            spec_judge_output={"coverage_estimate": 0.9, "missing": [], "hallucinated": []},
        )
        assert scorecard.arch_quality_score > 0.5
        assert scorecard.code_quality_score > 0.5
        assert scorecard.spec_fidelity_score == 0.9

    def test_compute_fail_on_critical(self):
        reporter = QualityReporter(workspace_root=Path("/tmp"), run_id="test")
        scorecard = reporter.compute(
            SAMPLE_ARCH_DIGEST,
            SAMPLE_CODE_DIGEST,
            arch_judge_output={
                "overall": 4,
                "risks": [{"severity": "CRITICAL", "component_id": "x", "evidence": "e"}],
                "scores": {},
                "strengths": [],
            },
        )
        assert scorecard.overall_status == "FAIL"

    def test_write(self, tmp_path):
        reporter = QualityReporter(workspace_root=tmp_path, run_id="write-test")
        scorecard = reporter.compute(SAMPLE_ARCH_DIGEST, SAMPLE_CODE_DIGEST)
        json_path, md_path = reporter.write(scorecard)
        assert json_path.exists()
        assert md_path.exists()
        data = json.loads(json_path.read_text())
        assert data["run_id"] == "write-test"
        assert "Quality Scorecard" in md_path.read_text()

    def test_overall_pass_when_all_good(self):
        reporter = QualityReporter(workspace_root=Path("/tmp"), run_id="test")
        scorecard = reporter.compute(
            SAMPLE_ARCH_DIGEST,
            SAMPLE_CODE_DIGEST,
            arch_judge_output={"overall": 5, "risks": [], "scores": {}, "strengths": []},
            code_judge_output={"overall": 5, "systemic_risks": [], "files": []},
            spec_judge_output={"coverage_estimate": 0.95, "missing": [], "hallucinated": []},
        )
        assert scorecard.overall_status == "PASS"
