from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

from scripts.spec_refinement.workflows.spec_building import build_specs
from scripts.spec_refinement.workspace import Phase, WorkspaceManager


def _setup_workspace(fs, monkeypatch) -> Path:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")
    manager = WorkspaceManager(run_id="run1", input_folder=input_dir)
    manager.initialize(force=True)
    manager.start_phase(Phase.LIBRARY_SYNTHESIS)
    manager.complete_phase(Phase.LIBRARY_SYNTHESIS, outputs={"libraries_count": 1})
    manager.start_phase(Phase.EVIDENCE_EXPANSION)
    manager.complete_phase(Phase.EVIDENCE_EXPANSION, outputs={"libraries_expanded": 1})

    lib_dir = manager.structure.libraries_dir / "lib_001"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "charter.md").write_text(
        "# Library Charter: lib_001\n\n## Intent\nOwn keyword behaviors.\n\n"
        "## Boundaries\nFocus on keyword scope.\n\n"
        "## Responsibilities\n- Own keyword workflows\n",
        encoding="utf-8",
    )
    (lib_dir / "evidence.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "file_id": "file_001",
                        "sections": ["INTRO"],
                        "confidence": 0.9,
                        "rationale": "Test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return input_dir


class IntegrationRunner:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def run(self, prompt: str) -> str:
        if self.mode == "strip":
            return "# Library Spec: lib_001\n\n## Requirements\n- Missing\n"
        match = re.search(r"Current Spec:\n(.*?)\n\nSource File:", prompt, re.S)
        current_spec = match.group(1).strip() if match else ""
        if self.mode == "append":
            return f"{current_spec}\n\n## Requirements\n- Own keyword workflows [file_001::INTRO]\n"
        return current_spec


class GapJudgeRunner:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs

    def run(self, prompt: str) -> str:
        if not self.outputs:
            return json.dumps({"gaps": [], "total_gaps": 0, "file_id": "file_001"})
        return self.outputs.pop(0)


def test_monotonic_integration_no_deletions(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = IntegrationRunner("strip")
    gap_judge = GapJudgeRunner([json.dumps({"gaps": [], "total_gaps": 0, "file_id": "file_001"})])

    def fake_from_agent_name(name: str, *args, **kwargs):
        return integrator if name == "glm-library-spec-integrator" else gap_judge

    with patch(
        "scripts.spec_refinement.workflows.spec_building.AgentRunner.from_agent_name",
        side_effect=fake_from_agent_name,
    ):
        result = build_specs("run1", Path("/repo/.tasks.yaml"), max_iterations=1)

    spec_path = Path("/repo/runs/run1/libraries/lib_001/spec.md")
    content = spec_path.read_text(encoding="utf-8")
    assert "## Intent" in content
    assert any(issue["type"] == "non_monotonic_integration" for issue in result["issues"])


def test_gap_detection_and_clustering(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = IntegrationRunner("append")
    gap_judge_output = json.dumps(
        {
            "gaps": [
                {
                    "source": "file_001::INTRO",
                    "missing_content": "Missing detail A",
                    "where_in_spec": "Requirements",
                    "severity": "must",
                },
                {
                    "source": "file_001::INTRO",
                    "missing_content": "Missing detail B",
                    "where_in_spec": "Constraints",
                    "severity": "should",
                },
            ],
            "total_gaps": 2,
            "file_id": "file_001",
        }
    )
    gap_judge = GapJudgeRunner([gap_judge_output])

    def fake_from_agent_name(name: str, *args, **kwargs):
        return integrator if name == "glm-library-spec-integrator" else gap_judge

    with patch(
        "scripts.spec_refinement.workflows.spec_building.AgentRunner.from_agent_name",
        side_effect=fake_from_agent_name,
    ):
        build_specs("run1", Path("/repo/.tasks.yaml"), max_iterations=1)

    gaps_path = Path("/repo/runs/run1/libraries/lib_001/gaps.md")
    gaps_content = gaps_path.read_text(encoding="utf-8")
    assert "GAP-" in gaps_content


def test_gap_closure_converges(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = IntegrationRunner("append")
    gap_outputs = [
        json.dumps(
            {
                "gaps": [
                    {
                        "source": "file_001::INTRO",
                        "missing_content": "Missing detail A",
                        "where_in_spec": "Requirements",
                        "severity": "must",
                    }
                ],
                "total_gaps": 1,
                "file_id": "file_001",
            }
        ),
        json.dumps({"gaps": [], "total_gaps": 0, "file_id": "file_001"}),
    ]
    gap_judge = GapJudgeRunner(gap_outputs)

    def fake_from_agent_name(name: str, *args, **kwargs):
        return integrator if name == "glm-library-spec-integrator" else gap_judge

    with patch(
        "scripts.spec_refinement.workflows.spec_building.AgentRunner.from_agent_name",
        side_effect=fake_from_agent_name,
    ):
        result = build_specs("run1", Path("/repo/.tasks.yaml"), max_iterations=2)

    assert result["converged_count"] == 1


def test_max_iteration_limit(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = IntegrationRunner("append")
    gap_outputs = [
        json.dumps(
            {
                "gaps": [
                    {
                        "source": "file_001::INTRO",
                        "missing_content": "Missing detail A",
                        "where_in_spec": "Requirements",
                        "severity": "must",
                    }
                ],
                "total_gaps": 1,
                "file_id": "file_001",
            }
        ),
        json.dumps(
            {
                "gaps": [
                    {
                        "source": "file_001::INTRO",
                        "missing_content": "Missing detail A",
                        "where_in_spec": "Requirements",
                        "severity": "must",
                    }
                ],
                "total_gaps": 1,
                "file_id": "file_001",
            }
        ),
    ]
    gap_judge = GapJudgeRunner(gap_outputs)

    def fake_from_agent_name(name: str, *args, **kwargs):
        return integrator if name == "glm-library-spec-integrator" else gap_judge

    with patch(
        "scripts.spec_refinement.workflows.spec_building.AgentRunner.from_agent_name",
        side_effect=fake_from_agent_name,
    ):
        result = build_specs("run1", Path("/repo/.tasks.yaml"), max_iterations=2)

    assert result["total_iterations"] == 2


def test_citation_validation(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = IntegrationRunner("strip")
    gap_judge = GapJudgeRunner([json.dumps({"gaps": [], "total_gaps": 0, "file_id": "file_001"})])

    def fake_from_agent_name(name: str, *args, **kwargs):
        return integrator if name == "glm-library-spec-integrator" else gap_judge

    with patch(
        "scripts.spec_refinement.workflows.spec_building.AgentRunner.from_agent_name",
        side_effect=fake_from_agent_name,
    ):
        result = build_specs("run1", Path("/repo/.tasks.yaml"), max_iterations=1)

    assert any(issue["type"] == "missing_evidence_pointers" for issue in result["issues"])
