from __future__ import annotations

from pathlib import Path

from spec_manager.refinement.repair import ArtifactType, repair_artifact
from spec_manager.refinement.workspace import WorkspaceManager


def _setup_workspace(fs, monkeypatch, run_id: str) -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    input_dir = base / "input"
    fs.create_dir(input_dir)
    (input_dir / "spec.md").write_text("# Spec\n\n## Intro\nSeed content.", encoding="utf-8")
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id=run_id, input_folder=input_dir)
    issues = manager.initialize(force=True)
    assert issues == []
    return manager


def test_repair_artifact_patch_output(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch, run_id="run_patch_output")
    captured: dict[str, str] = {}

    def _fake_run_agent(*, agent_name: str, prompt: str, workspace: Path, **_kwargs: object) -> str:
        captured["agent_name"] = agent_name
        assert workspace == manager.workspace_path
        return "diff --git a/file.txt b/file.txt\n"

    monkeypatch.setattr("spec_manager.refinement.repair.run_agent", _fake_run_agent)

    output, evidence = repair_artifact(
        output="invalid",
        errors=[{"type": "invalid_patch", "message": "bad"}],
        allowlists={},
        artifact_type=ArtifactType.PATCH_OUTPUT,
        model_override="gpt-5.2-low",
        manager=manager,
    )

    assert output.startswith("diff --git")
    assert captured["agent_name"] == "chatgpt-patch-repairer"
    assert evidence


def test_repair_artifact_patch_audit(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch, run_id="run_patch_audit")
    captured: dict[str, str] = {}

    def _fake_run_agent(*, agent_name: str, prompt: str, workspace: Path, **_kwargs: object) -> str:
        captured["agent_name"] = agent_name
        assert workspace == manager.workspace_path
        return "{\"verdict\": \"pass\", \"issues\": 0}"

    monkeypatch.setattr("spec_manager.refinement.repair.run_agent", _fake_run_agent)

    output, evidence = repair_artifact(
        output="invalid",
        errors=[{"type": "invalid_audit", "message": "bad"}],
        allowlists={},
        artifact_type=ArtifactType.PATCH_AUDIT,
        model_override="gpt-5.2-low",
        manager=manager,
    )

    assert "verdict" in output
    assert captured["agent_name"] == "chatgpt-patch-audit-judge"
    assert evidence
