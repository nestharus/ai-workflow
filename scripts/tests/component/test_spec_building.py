from __future__ import annotations

import json
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
                        "file_id": "F0001",
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


def _patch_output(operations: list[dict[str, object]]) -> str:
    return json.dumps(operations)


class PatchRunner:
    def __init__(self, operations: list[dict[str, object]]) -> None:
        self.operations = operations

    def run(self, prompt: str) -> str:
        return _patch_output(self.operations)


class GapJudgeRunner:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs

    def run(self, prompt: str) -> str:
        if not self.outputs:
            return json.dumps({"gaps": [], "total_gaps": 0, "file_id": "F0001"})
        return self.outputs.pop(0)


def test_gap_detection_and_clustering(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = PatchRunner(
        [
            {
                "op": "add",
                "section": "Requirements",
                "bullet_index": None,
                "content": "Own keyword workflows",
                "citations": ["[F0001::INTRO]"],
            }
        ]
    )
    gap_judge_output = json.dumps(
        {
            "gaps": [
                {
                    "source": "F0001::INTRO",
                    "missing_content": "Missing detail A",
                    "where_in_spec": "Requirements",
                    "severity": "must",
                },
                {
                    "source": "F0001::INTRO",
                    "missing_content": "Missing detail B",
                    "where_in_spec": "Constraints",
                    "severity": "should",
                },
            ],
            "total_gaps": 2,
            "file_id": "F0001",
        }
    )
    gap_judge = GapJudgeRunner([gap_judge_output])

    def _run_agent(
        *,
        agent_name: str,
        prompt: str,
        workspace: Path,
        max_retries: int = 2,
        structured_schema: object | None = None,
        **_: object,
    ) -> str:
        if agent_name == "glm-library-spec-integrator":
            return integrator.run(prompt)
        return gap_judge.run(prompt)

    with patch(
        "scripts.spec_refinement.workflows.spec_building.run_agent",
        side_effect=_run_agent,
    ):
        build_specs("run1", max_iterations=1)

    gaps_path = Path("/repo/runs/run1/libraries/lib_001/gaps.md")
    gaps_content = gaps_path.read_text(encoding="utf-8")
    assert "GAP-" in gaps_content


def test_gap_closure_converges(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = PatchRunner(
        [
            {
                "op": "add",
                "section": "Requirements",
                "bullet_index": None,
                "content": "Own keyword workflows",
                "citations": ["[F0001::INTRO]"],
            }
        ]
    )
    gap_outputs = [
        json.dumps(
            {
                "gaps": [
                    {
                        "source": "F0001::INTRO",
                        "missing_content": "Missing detail A",
                        "where_in_spec": "Requirements",
                        "severity": "must",
                    }
                ],
                "total_gaps": 1,
                "file_id": "F0001",
            }
        ),
        json.dumps({"gaps": [], "total_gaps": 0, "file_id": "F0001"}),
    ]
    gap_judge = GapJudgeRunner(gap_outputs)

    def _run_agent(
        *,
        agent_name: str,
        prompt: str,
        workspace: Path,
        max_retries: int = 2,
        structured_schema: object | None = None,
        **_: object,
    ) -> str:
        if agent_name == "glm-library-spec-integrator":
            return integrator.run(prompt)
        return gap_judge.run(prompt)

    with patch(
        "scripts.spec_refinement.workflows.spec_building.run_agent",
        side_effect=_run_agent,
    ):
        result = build_specs("run1", max_iterations=2)

    assert result["converged_count"] == 1


def test_max_iteration_limit(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = PatchRunner(
        [
            {
                "op": "add",
                "section": "Requirements",
                "bullet_index": None,
                "content": "Own keyword workflows",
                "citations": ["[F0001::INTRO]"],
            }
        ]
    )
    gap_outputs = [
        json.dumps(
            {
                "gaps": [
                    {
                        "source": "F0001::INTRO",
                        "missing_content": "Missing detail A",
                        "where_in_spec": "Requirements",
                        "severity": "must",
                    }
                ],
                "total_gaps": 1,
                "file_id": "F0001",
            }
        ),
        json.dumps(
            {
                "gaps": [
                    {
                        "source": "F0001::INTRO",
                        "missing_content": "Missing detail A",
                        "where_in_spec": "Requirements",
                        "severity": "must",
                    }
                ],
                "total_gaps": 1,
                "file_id": "F0001",
            }
        ),
    ]
    gap_judge = GapJudgeRunner(gap_outputs)

    def _run_agent(
        *,
        agent_name: str,
        prompt: str,
        workspace: Path,
        max_retries: int = 2,
        structured_schema: object | None = None,
        **_: object,
    ) -> str:
        if agent_name == "glm-library-spec-integrator":
            return integrator.run(prompt)
        return gap_judge.run(prompt)

    with patch(
        "scripts.spec_refinement.workflows.spec_building.run_agent",
        side_effect=_run_agent,
    ):
        result = build_specs("run1", max_iterations=2)

    assert result["total_iterations"] == 2


def test_citation_validation(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = PatchRunner(
        [
            {
                "op": "add",
                "section": "Requirements",
                "bullet_index": None,
                "content": "Missing citation",
                "citations": [],
            }
        ]
    )
    gap_judge = GapJudgeRunner([json.dumps({"gaps": [], "total_gaps": 0, "file_id": "F0001"})])

    def _run_agent(
        *,
        agent_name: str,
        prompt: str,
        workspace: Path,
        max_retries: int = 2,
        structured_schema: object | None = None,
        **_: object,
    ) -> str:
        if agent_name == "glm-library-spec-integrator":
            return integrator.run(prompt)
        return gap_judge.run(prompt)

    with (
        patch(
            "scripts.spec_refinement.workflows.spec_building.run_agent",
            side_effect=_run_agent,
        ),
        patch(
            "scripts.spec_refinement.workflows.repair.run_agent",
            return_value=integrator.run(""),
        ),
    ):
        result = build_specs("run1", max_iterations=1)

    issue_types = {issue["type"] for issue in result["issues"]}
    assert "missing_citation" in issue_types or "missing_evidence_pointers" in issue_types


def test_repair_invalid_patch_citations(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)
    integrator = PatchRunner(
        [
            {
                "op": "add",
                "section": "Requirements",
                "bullet_index": None,
                "content": "Own keyword workflows",
                "citations": ["[F0001::MISSING]"],
            }
        ]
    )
    repaired_patch = _patch_output(
        [
            {
                "op": "add",
                "section": "Requirements",
                "bullet_index": None,
                "content": "Own keyword workflows",
                "citations": ["[F0001::INTRO]"],
            }
        ]
    )
    gap_judge = GapJudgeRunner([json.dumps({"gaps": [], "total_gaps": 0, "file_id": "F0001"})])

    def _run_agent(
        *,
        agent_name: str,
        prompt: str,
        workspace: Path,
        max_retries: int = 2,
        structured_schema: object | None = None,
        **_: object,
    ) -> str:
        if agent_name == "glm-library-spec-integrator":
            return integrator.run(prompt)
        return gap_judge.run(prompt)

    with (
        patch(
            "scripts.spec_refinement.workflows.spec_building.run_agent",
            side_effect=_run_agent,
        ),
        patch(
            "scripts.spec_refinement.workflows.repair.run_agent",
            return_value=repaired_patch,
        ),
    ):
        result = build_specs("run1", max_iterations=1)

    spec_path = Path("/repo/runs/run1/libraries/lib_001/spec.md")
    content = spec_path.read_text(encoding="utf-8")
    assert "[F0001::INTRO]" in content
    assert not any(issue["type"] == "unknown_section_reference" for issue in result["issues"])
