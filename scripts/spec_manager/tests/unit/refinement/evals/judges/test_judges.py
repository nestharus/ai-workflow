"""Tests for judge modules."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from spec_manager.refinement.evals.judges.arch_quality import ArchitectureQualityJudge
from spec_manager.refinement.evals.judges.code_quality import CodeQualityJudge
from spec_manager.refinement.evals.judges.spec_fidelity import SpecFidelityJudge
from spec_manager.refinement.evals.judges.pairwise import PairwiseArchJudge, PairwiseCodeJudge
from spec_manager.schemas.eval_arch_judge import ArchJudgeOutput
from spec_manager.schemas.eval_code_judge import CodeJudgeOutput
from spec_manager.schemas.eval_spec_fidelity_judge import SpecFidelityOutput
from spec_manager.schemas.eval_pairwise_judge import PairwiseOutput


SAMPLE_ARCH_DIGEST = {
    "run_id": "test-1",
    "topology": {
        "components": [
            {"id": "svc.auth", "type": "service", "summary": "Auth service", "depends_on": ["svc.db"]},
            {"id": "svc.db", "type": "service", "summary": "Database", "depends_on": []},
        ],
        "edges": [{"from": "svc.auth", "to": "svc.db", "kind": "import"}],
    },
    "coverage": {"requirements_total": 10, "requirements_mapped": 8, "unmapped_requirements": []},
    "l2_review": {"final_findings": {"BLOCKER": 0, "MAJOR": 1, "MINOR": 3}},
}

SAMPLE_CODE_DIGEST = {
    "run_id": "test-1",
    "codebase": {
        "files": [
            {"path": "auth.py", "loc": 200, "sha256": "abc", "role_hint": ""},
            {"path": "db.py", "loc": 150, "sha256": "def", "role_hint": ""},
            {"path": "util.py", "loc": 50, "sha256": "ghi", "role_hint": ""},
        ],
        "totals": {"files": 3, "loc": 400},
    },
    "l3_review": {
        "final_findings": {"BLOCKER": 0, "MAJOR": 2, "MINOR": 5},
        "top_files": [{"path": "auth.py", "MAJOR": 2, "MINOR": 1}],
    },
    "ci": {"final_pass": True, "first_pass": False},
}

VALID_ARCH_RESPONSE = json.dumps({
    "scores": {"cohesion": 4, "coupling": 3, "completeness": 5, "consistency": 4, "clarity": 3, "extensibility": 4},
    "overall": 4,
    "strengths": ["Good separation of concerns"],
    "risks": [{"severity": "MINOR", "component_id": "svc.auth", "evidence": "High coupling"}],
    "tradeoffs_noted": ["Simple over complex"],
})

VALID_CODE_RESPONSE = json.dumps({
    "files": [
        {"path": "auth.py", "scores": {"readability": 4, "maintainability": 3, "error_handling": 4, "consistency": 4, "contract_clarity": 3}, "overall": 4, "notes": [], "risks": []},
    ],
    "overall": 4,
    "systemic_risks": [],
})

VALID_SPEC_RESPONSE = json.dumps({
    "coverage_estimate": 0.85,
    "requirements": [{"requirement": "Auth must support OAuth", "status": "implemented", "evidence": "auth.py"}],
    "missing": ["Rate limiting"],
    "hallucinated": [],
})

VALID_PAIRWISE_RESPONSE = json.dumps({
    "winner": "A",
    "scores": {
        "A": {"architecture": 4, "code": 4, "spec_fidelity": 4, "risk_profile": 3},
        "B": {"architecture": 3, "code": 3, "spec_fidelity": 3, "risk_profile": 4},
    },
    "key_differences": ["A has better coupling"],
    "risks": [],
})

# All judge modules delegate to JudgeClient which imports run_agent into client.py.
_PATCH_TARGET = "spec_manager.refinement.evals.judges.client.run_agent"


class TestArchitectureQualityJudge:
    @patch(_PATCH_TARGET)
    def test_evaluate(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_ARCH_RESPONSE
        judge = ArchitectureQualityJudge(workspace=tmp_path)
        result = judge.evaluate(SAMPLE_ARCH_DIGEST)
        assert isinstance(result, ArchJudgeOutput)
        assert result.overall == 4
        assert result.scores["cohesion"] == 4

    @patch(_PATCH_TARGET)
    def test_builds_prompt(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_ARCH_RESPONSE
        judge = ArchitectureQualityJudge(workspace=tmp_path)
        judge.evaluate(SAMPLE_ARCH_DIGEST)
        prompt = mock_agent.call_args[1]["prompt"]
        assert "Architecture Quality" in prompt
        assert "svc.auth" in prompt

    @patch(_PATCH_TARGET)
    def test_with_empty_digest(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_ARCH_RESPONSE
        judge = ArchitectureQualityJudge(workspace=tmp_path)
        result = judge.evaluate({"topology": {"components": [], "edges": []}, "coverage": {}, "l2_review": {}})
        assert isinstance(result, ArchJudgeOutput)


class TestCodeQualityJudge:
    @patch(_PATCH_TARGET)
    def test_evaluate(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_CODE_RESPONSE
        judge = CodeQualityJudge(workspace=tmp_path)
        result = judge.evaluate(SAMPLE_CODE_DIGEST)
        assert isinstance(result, CodeJudgeOutput)
        assert result.overall == 4

    @patch(_PATCH_TARGET)
    def test_samples_by_loc(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_CODE_RESPONSE
        judge = CodeQualityJudge(workspace=tmp_path, sample_budget=2)
        sampled = judge._sample_files(SAMPLE_CODE_DIGEST)
        # Top by LOC should include auth.py (200) and db.py (150)
        paths = [f["path"] for f in sampled]
        assert "auth.py" in paths

    @patch(_PATCH_TARGET)
    def test_with_snapshot(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_CODE_RESPONSE
        snapshot = tmp_path / "snap"
        snapshot.mkdir()
        (snapshot / "auth.py").write_text("def login(): pass\n", encoding="utf-8")

        judge = CodeQualityJudge(workspace=tmp_path)
        result = judge.evaluate(SAMPLE_CODE_DIGEST, snapshot_dir=snapshot)
        assert isinstance(result, CodeJudgeOutput)
        prompt = mock_agent.call_args[1]["prompt"]
        assert "def login" in prompt

    @patch(_PATCH_TARGET)
    def test_empty_digest(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_CODE_RESPONSE
        judge = CodeQualityJudge(workspace=tmp_path)
        result = judge.evaluate({"codebase": {"files": [], "totals": {"files": 0, "loc": 0}}, "l3_review": {}, "ci": {}})
        assert isinstance(result, CodeJudgeOutput)


class TestSpecFidelityJudge:
    @patch(_PATCH_TARGET)
    def test_evaluate(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_SPEC_RESPONSE
        judge = SpecFidelityJudge(workspace=tmp_path)
        result = judge.evaluate(
            spec_summary={"requirements": ["Auth must support OAuth", "Rate limiting"]},
            code_digest=SAMPLE_CODE_DIGEST,
        )
        assert isinstance(result, SpecFidelityOutput)
        assert result.coverage_estimate == 0.85

    @patch(_PATCH_TARGET)
    def test_prompt_includes_requirements(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_SPEC_RESPONSE
        judge = SpecFidelityJudge(workspace=tmp_path)
        judge.evaluate(
            spec_summary={"requirements": ["Must authenticate users"]},
            code_digest=SAMPLE_CODE_DIGEST,
        )
        prompt = mock_agent.call_args[1]["prompt"]
        assert "Must authenticate users" in prompt


class TestPairwiseJudges:
    @patch(_PATCH_TARGET)
    def test_arch_compare(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_PAIRWISE_RESPONSE
        judge = PairwiseArchJudge(workspace=tmp_path)
        result = judge.compare(SAMPLE_ARCH_DIGEST, SAMPLE_ARCH_DIGEST)
        assert isinstance(result, PairwiseOutput)
        assert result.winner == "A"

    @patch(_PATCH_TARGET)
    def test_code_compare(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_PAIRWISE_RESPONSE
        judge = PairwiseCodeJudge(workspace=tmp_path)
        result = judge.compare(SAMPLE_CODE_DIGEST, SAMPLE_CODE_DIGEST)
        assert isinstance(result, PairwiseOutput)
        assert result.winner == "A"

    @patch(_PATCH_TARGET)
    def test_prompt_is_blinded(self, mock_agent, tmp_path):
        mock_agent.return_value = VALID_PAIRWISE_RESPONSE
        judge = PairwiseArchJudge(workspace=tmp_path)
        judge.compare(SAMPLE_ARCH_DIGEST, SAMPLE_ARCH_DIGEST)
        prompt = mock_agent.call_args[1]["prompt"]
        assert "Output A" in prompt
        assert "Output B" in prompt
        assert "blinded" in prompt.lower()
