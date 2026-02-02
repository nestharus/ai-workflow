from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from spec_manager.refinement.formats import EVIDENCE_POINTER_RE, parse_evidence_pointer
from spec_manager.refinement.repair import ArtifactType
from spec_manager.refinement.validation_utils import build_file_id_lookup
from spec_manager.refinement.workflows.summarization import (
    _process_file,
    _validate_bullets_have_pointers,
    _validate_evidence_pointers,
)
from spec_manager.refinement.workspace import WorkspaceManager


def _setup_workspace(fs, monkeypatch, run_id: str = "run_001") -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    specs_dir = base / "specs"
    fs.create_dir(specs_dir)
    (specs_dir / "alpha.md").write_text(
        "# Alpha\n\n## Intro\nDetails.\n\n## User Requirements\nNeeds.\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("specs"))
    issues = manager.initialize(force=True)
    assert issues == []

    # Write per-file sections manifest with canonical section IDs
    sections_file = manager.structure.manifest_sections_dir / "F0001.sections.json"
    sections_data = {
        "file_id": "F0001",
        "sections": [
            {"section_id": "SEC-F0001-0001", "start_line": 1, "end_line": 4, "label": "Intro"},
            {
                "section_id": "SEC-F0001-0002",
                "start_line": 5,
                "end_line": 7,
                "label": "User Requirements",
            },
        ],
        "total_lines": 7,
    }
    sections_file.write_text(json.dumps(sections_data), encoding="utf-8")
    return manager


def _stub_manager(
    file_manifest: dict[str, dict[str, str]],
    sections_by_file: dict[str, list[dict[str, str]]],
    spec_snapshot_dir: Path,
) -> SimpleNamespace:
    state = SimpleNamespace(file_manifest=file_manifest)
    structure = SimpleNamespace(spec_snapshot_dir=spec_snapshot_dir)

    def _read_file_sections(file_id: str) -> dict[str, Any] | None:
        sections = sections_by_file.get(file_id)
        if sections is None:
            return None
        return {"sections": sections}

    return SimpleNamespace(
        state=state,
        structure=structure,
        read_file_sections=_read_file_sections,
    )


def _assert_valid_pointers(content: str, manager: WorkspaceManager) -> bool:
    matches = list(EVIDENCE_POINTER_RE.finditer(content))
    if not matches:
        return False
    file_id_lookup = build_file_id_lookup(
        manager.state.file_manifest,
        manager.structure.spec_snapshot_dir,
    )
    for match in matches:
        parsed = parse_evidence_pointer(match.group(0))
        if not parsed:
            return False
        resolved_file_id = file_id_lookup.get(parsed["file_ref"])
        if resolved_file_id is None:
            return False
        sections_data = manager.read_file_sections(resolved_file_id) or {}
        sections_list = sections_data.get("sections") if isinstance(sections_data, dict) else None
        if not isinstance(sections_list, list):
            return False
        valid_section_ids = {
            entry.get("section_id")
            for entry in sections_list
            if isinstance(entry, dict) and isinstance(entry.get("section_id"), str)
        }
        if parsed["section_ref"] not in valid_section_ids:
            return False
    return True


def test_validate_evidence_pointers_basename_reference(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [alpha.md::SEC-F0001-0001]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert issues == []


def test_validate_evidence_pointers_stem_reference(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [alpha::SEC-F0001-0002]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert issues == []


def test_validate_evidence_pointers_legacy_label_rejected(fs, monkeypatch) -> None:
    """Legacy labels like 'intro' or 'INTRO' are flagged as unknown."""
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [F0001::intro]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert any(issue["type"] == "unknown_section_reference" for issue in issues)


def test_validate_evidence_pointers_normalized_label_rejected(fs, monkeypatch) -> None:
    """Normalized labels like 'user-requirements' are flagged as unknown."""
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [F0001::user-requirements]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert any(issue["type"] == "unknown_section_reference" for issue in issues)


def test_validate_evidence_pointers_section_id_with_different_file_refs() -> None:
    """Canonical section IDs are accepted via basename and stem file refs."""
    file_path = Path("/work/specs/nested/alpha.md")
    spec_snapshot_dir = file_path.parents[1]
    relpath = file_path.relative_to(spec_snapshot_dir).as_posix()
    manager = _stub_manager(
        {"F0001": {"relpath": relpath, "sha256": "0" * 64}},
        {
            "F0001": [
                {"section_id": "SEC-F0001-0001", "label": "INTRO"},
                {"section_id": "SEC-F0001-0002", "label": "User Requirements"},
            ]
        },
        spec_snapshot_dir,
    )

    content = "Evidence: [alpha.md::SEC-F0001-0001]\nEvidence: [alpha::SEC-F0001-0002]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert issues == []


def test_validate_evidence_pointers_invalid_section_reports_issue() -> None:
    file_path = Path("/work/specs/nested/alpha.md")
    spec_snapshot_dir = file_path.parents[1]
    relpath = file_path.relative_to(spec_snapshot_dir).as_posix()
    manager = _stub_manager(
        {"F0001": {"relpath": relpath, "sha256": "0" * 64}},
        {
            "F0001": [
                {"section_id": "SEC-F0001-0001", "label": "INTRO"},
                {"section_id": "SEC-F0001-0002", "label": "User Requirements"},
            ]
        },
        spec_snapshot_dir,
    )

    content = "Evidence: [alpha::missing-section]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert any(issue["type"] == "unknown_section_reference" for issue in issues)


def test_summary_missing_pointers_repaired_passes(
    spec_refinement_workspace, mock_all_agents, monkeypatch
) -> None:
    manager, manifest = spec_refinement_workspace(file_count=1)
    controller = mock_all_agents(
        manifest,
        violation_rate=0.0,
        overrides={"glm-file-what-summarizer": 1.0},
    )
    file_id = sorted(manifest.keys())[0]
    file_path = manager.get_all_files()[file_id]

    invalid_output = (
        f"# File Summary: {file_id}\n"
        f"File ID: {file_id}\n\n"
        "## Algorithms\n"
        "- Validate Intake | Ensure payload sanity\n\n"
        "## Components\n"
        "- Intake API | Accept requests\n\n"
        "## Workflows\n"
        "- Intake Flow | Validate then route\n\n"
        "## Candidate Responsibilities\n"
        "- Maintain ingestion contracts\n\n"
        "## Dependencies\n"
        "- None\n\n"
        "## Evidence Map\n"
        "- None\n"
    )

    def _mock_summarizer(*, agent_name: str, prompt: str, workspace: Path, **kwargs) -> str:
        _ = agent_name
        _ = prompt
        _ = workspace
        return invalid_output

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.summarization.run_agent",
        _mock_summarizer,
    )

    initial_issues = _validate_evidence_pointers(invalid_output, manager, file_id)
    initial_issues.extend(_validate_bullets_have_pointers(invalid_output, file_id))
    assert any(
        issue["type"] in {"bullet_missing_evidence", "missing_evidence_pointers"}
        for issue in initial_issues
    )

    result = _process_file(file_id, file_path, manager)

    assert result.get("issues") == []
    assert any(
        call["artifact_type"] == ArtifactType.SUMMARY.value for call in controller.repair_calls
    )
    assert result["output_path"].exists()
    repaired_content = result["output_path"].read_text(encoding="utf-8")
    assert repaired_content != invalid_output
    assert _assert_valid_pointers(repaired_content, manager)
    assert any(record["type"] == "repair_agent_invoked" for record in result["format_evidence"])


def test_summary_invented_section_ids_blocker(
    spec_refinement_workspace, mock_all_agents, monkeypatch
) -> None:
    manager, manifest = spec_refinement_workspace(file_count=1)
    controller = mock_all_agents(manifest, violation_rate=0.0)
    file_id = sorted(manifest.keys())[0]
    file_path = manager.get_all_files()[file_id]
    file_entry = manager.state.file_manifest[file_id]
    relpath = file_entry.get("relpath") if isinstance(file_entry, dict) else str(file_entry)
    file_ref = Path(relpath).name
    invented_pointer = f"[{file_ref}::SEC-INVENTED-9999]"

    invalid_output = (
        f"# File Summary: {file_id}\n"
        f"File ID: {file_id}\n\n"
        "## Algorithms\n"
        f"- Validate Intake | Ensure payload sanity | Evidence: {invented_pointer}\n\n"
        "## Components\n"
        f"- Intake API | Accept requests | Evidence: {invented_pointer}\n\n"
        "## Workflows\n"
        f"- Intake Flow | Validate then route | Evidence: {invented_pointer}\n\n"
        "## Candidate Responsibilities\n"
        f"- Maintain ingestion contracts | Evidence: {invented_pointer}\n\n"
        "## Dependencies\n"
        "- None\n\n"
        "## Evidence Map\n"
        f"- SEC-INVENTED-9999: {invented_pointer}\n"
    )

    issues = _validate_evidence_pointers(invalid_output, manager, file_id)
    assert any(issue.get("blocker") for issue in issues)
    assert any(issue["type"] == "unknown_section_reference" for issue in issues)

    def _mock_summarizer(*, agent_name: str, prompt: str, workspace: Path, **kwargs) -> str:
        _ = agent_name
        _ = prompt
        _ = workspace
        return invalid_output

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.summarization.run_agent",
        _mock_summarizer,
    )

    result = _process_file(file_id, file_path, manager)

    assert any(issue["type"] == "repair_blocked" for issue in result["issues"])
    assert not controller.repair_calls
    assert result["output_path"].read_text(encoding="utf-8") == invalid_output


def test_summary_valid_section_ids_passes(spec_refinement_workspace, mock_all_agents) -> None:
    manager, manifest = spec_refinement_workspace(file_count=1)
    controller = mock_all_agents(manifest, violation_rate=0.0)
    file_id = sorted(manifest.keys())[0]
    file_path = manager.get_all_files()[file_id]

    result = _process_file(file_id, file_path, manager)

    assert result.get("issues") == []
    assert len(controller.repair_calls) == 0
    assert result["output_path"].exists()
    summary_content = result["output_path"].read_text(encoding="utf-8")
    assert _assert_valid_pointers(summary_content, manager)


def test_repair_agent_receives_section_id_allowlist(
    spec_refinement_workspace, mock_all_agents, monkeypatch
) -> None:
    manager, manifest = spec_refinement_workspace(file_count=1)
    mock_all_agents(manifest, violation_rate=0.0)
    file_id = sorted(manifest.keys())[0]
    file_path = manager.get_all_files()[file_id]
    file_entry = manager.state.file_manifest[file_id]
    relpath = file_entry.get("relpath") if isinstance(file_entry, dict) else str(file_entry)
    sections_data = manager.read_file_sections(file_id) or {}
    sections_list = sections_data.get("sections", []) if isinstance(sections_data, dict) else []
    section_id = next(
        entry["section_id"]
        for entry in sections_list
        if isinstance(entry, dict) and isinstance(entry.get("section_id"), str)
    )

    # Deterministic summarizer stub that always returns a repairable-but-invalid
    # summary (missing evidence pointers) so _process_file always invokes repair.
    invalid_output = (
        f"# File Summary: {file_id}\n"
        f"File ID: {file_id}\n\n"
        "## Algorithms\n"
        "- Validate Intake | Ensure payload sanity\n\n"
        "## Components\n"
        "- Intake API | Accept requests\n\n"
        "## Workflows\n"
        "- Intake Flow | Validate then route\n\n"
        "## Candidate Responsibilities\n"
        "- Maintain ingestion contracts\n\n"
        "## Dependencies\n"
        "- None\n\n"
        "## Evidence Map\n"
        "- None\n"
    )

    def _mock_summarizer(*, agent_name: str, prompt: str, workspace: Path, **kwargs) -> str:
        _ = agent_name
        _ = prompt
        _ = workspace
        return invalid_output

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.summarization.run_agent",
        _mock_summarizer,
    )

    captured_prompt: dict[str, str] = {}

    def _mock_repair_agent(*, agent_name: str, prompt: str, workspace: Path, **kwargs) -> str:
        _ = agent_name
        _ = workspace
        captured_prompt["prompt"] = prompt
        pointer = f"[spec_snapshot/{relpath}::{section_id}]"
        return (
            f"# File Summary: {file_id}\n"
            f"File ID: {file_id}\n\n"
            "## Algorithms\n"
            f"- Validate Intake | Ensure payload sanity | Evidence: {pointer}\n\n"
            "## Components\n"
            f"- Intake API | Accept requests | Evidence: {pointer}\n\n"
            "## Workflows\n"
            f"- Intake Flow | Validate then route | Evidence: {pointer}\n\n"
            "## Candidate Responsibilities\n"
            f"- Maintain ingestion contracts | Evidence: {pointer}\n\n"
            "## Dependencies\n"
            "- None\n\n"
            "## Evidence Map\n"
            f"- {section_id}: {pointer}\n"
        )

    monkeypatch.setattr("spec_manager.refinement.repair.run_agent", _mock_repair_agent)

    result = _process_file(file_id, file_path, manager)

    prompt = captured_prompt.get("prompt", "")
    assert prompt
    assert "ALLOWLISTS:" in prompt
    assert "sections:" in prompt
    assert section_id in prompt
    assert "file_refs:" in prompt
    assert "spec_snapshot/" in prompt
    assert "VALIDATION ERRORS:" in prompt
    assert result.get("issues") == []
    repaired_content = result["output_path"].read_text(encoding="utf-8")
    assert f"[spec_snapshot/{relpath}::{section_id}]" in repaired_content
