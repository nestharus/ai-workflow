"""Tests for eval judge Pydantic schemas."""

from spec_manager.schemas.eval_arch_judge import ArchJudgeOutput, ArchRisk
from spec_manager.schemas.eval_code_judge import CodeJudgeOutput, FileScore
from spec_manager.schemas.eval_pairwise_judge import PairwiseOutput
from spec_manager.schemas.eval_spec_fidelity_judge import (
    RequirementCoverage,
    SpecFidelityOutput,
)

# --- ArchJudgeOutput ---


class TestArchJudgeOutput:
    def test_construct_with_valid_data(self):
        out = ArchJudgeOutput(
            scores={"cohesion": 4, "coupling": 3, "completeness": 5},
            overall=4,
            strengths=["clean separation"],
            risks=[ArchRisk(severity="MINOR", component_id="c1", evidence="tight loop")],
            tradeoffs_noted=["latency vs throughput"],
        )
        assert out.overall == 4
        assert out.scores["cohesion"] == 4
        assert len(out.risks) == 1
        assert out.risks[0].severity == "MINOR"

    def test_defaults(self):
        out = ArchJudgeOutput()
        assert out.scores == {}
        assert out.overall == 3
        assert out.strengths == []
        assert out.risks == []
        assert out.tradeoffs_noted == []

    def test_arch_risk_defaults(self):
        risk = ArchRisk(severity="CRITICAL")
        assert risk.component_id == ""
        assert risk.evidence == ""

    def test_arch_risk_embedded(self):
        risk = ArchRisk(severity="MAJOR", component_id="svc-auth", evidence="no retry")
        out = ArchJudgeOutput(risks=[risk])
        assert out.risks[0].component_id == "svc-auth"


# --- CodeJudgeOutput ---


class TestCodeJudgeOutput:
    def test_construct_with_valid_data(self):
        fs = FileScore(
            path="src/main.py",
            scores={"readability": 4, "maintainability": 3},
            overall=4,
            notes=["well structured"],
            risks=[{"severity": "MINOR", "evidence": "long function"}],
        )
        out = CodeJudgeOutput(
            files=[fs],
            overall=4,
            systemic_risks=[{"severity": "MAJOR", "evidence": "no tests"}],
        )
        assert out.overall == 4
        assert len(out.files) == 1
        assert out.files[0].path == "src/main.py"
        assert len(out.systemic_risks) == 1

    def test_defaults(self):
        out = CodeJudgeOutput()
        assert out.files == []
        assert out.overall == 3
        assert out.systemic_risks == []

    def test_file_score_defaults(self):
        fs = FileScore(path="a.py")
        assert fs.scores == {}
        assert fs.overall == 3
        assert fs.notes == []
        assert fs.risks == []

    def test_multiple_files(self):
        files = [
            FileScore(path="a.py", overall=5),
            FileScore(path="b.py", overall=2),
        ]
        out = CodeJudgeOutput(files=files)
        assert len(out.files) == 2
        assert out.files[0].overall == 5
        assert out.files[1].overall == 2


# --- SpecFidelityOutput ---


class TestSpecFidelityOutput:
    def test_construct_with_valid_data(self):
        req = RequirementCoverage(
            requirement="must handle auth",
            status="implemented",
            evidence="see auth_handler.py",
        )
        out = SpecFidelityOutput(
            coverage_estimate=0.85,
            requirements=[req],
            missing=["logging"],
            hallucinated=["caching layer"],
        )
        assert out.coverage_estimate == 0.85
        assert len(out.requirements) == 1
        assert out.requirements[0].status == "implemented"
        assert out.missing == ["logging"]
        assert out.hallucinated == ["caching layer"]

    def test_defaults(self):
        out = SpecFidelityOutput()
        assert out.coverage_estimate == 0.0
        assert out.requirements == []
        assert out.missing == []
        assert out.hallucinated == []

    def test_requirement_coverage_defaults(self):
        rc = RequirementCoverage(requirement="must log")
        assert rc.status == "missing"
        assert rc.evidence == ""

    def test_requirement_coverage_in_output(self):
        reqs = [
            RequirementCoverage(requirement="auth", status="implemented"),
            RequirementCoverage(requirement="audit", status="partial"),
            RequirementCoverage(requirement="cache", status="missing"),
        ]
        out = SpecFidelityOutput(requirements=reqs, coverage_estimate=0.5)
        assert len(out.requirements) == 3
        statuses = [r.status for r in out.requirements]
        assert statuses == ["implemented", "partial", "missing"]


# --- PairwiseOutput ---


class TestPairwiseOutput:
    def test_construct_with_valid_data(self):
        out = PairwiseOutput(
            winner="A",
            scores={"A": {"quality": 4}, "B": {"quality": 2}},
            key_differences=["A handles edge cases"],
            risks=[{"severity": "MINOR", "evidence": "B missing validation"}],
        )
        assert out.winner == "A"
        assert out.scores["A"]["quality"] == 4
        assert len(out.key_differences) == 1

    def test_defaults(self):
        out = PairwiseOutput()
        assert out.winner == "TIE"
        assert out.scores == {}
        assert out.key_differences == []
        assert out.risks == []

    def test_winner_a(self):
        out = PairwiseOutput(winner="A")
        assert out.winner == "A"

    def test_winner_b(self):
        out = PairwiseOutput(winner="B")
        assert out.winner == "B"

    def test_winner_tie(self):
        out = PairwiseOutput(winner="TIE")
        assert out.winner == "TIE"
