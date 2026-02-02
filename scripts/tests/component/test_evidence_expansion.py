from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

from spec_manager.refinement.formats import (
    parse_evidence_mapper_output,
    parse_evidence_spotcheck_output,
)
from spec_manager.refinement.workflows.evidence_expansion import (
    expand_evidence,
    spotcheck_evidence,
)
from spec_manager.refinement.workspace import Phase, WorkspaceManager


def _make_summary_output(file_id: str, section: str, keyword: str) -> str:
    return (
        f"# File Summary: {file_id}\n"
        f"File ID: {file_id}\n\n"
        "## Algorithms\n"
        f"- Algo | {keyword} behavior | Evidence: [{file_id}::{section}]\n\n"
        "## Components\n"
        f"- Component | {keyword} data | Evidence: [{file_id}::{section}]\n\n"
        "## Workflows\n"
        f"- Workflow | {keyword} tasks | Evidence: [{file_id}::{section}]\n\n"
        "## Candidate Responsibilities\n"
        f"- {keyword} ownership | Evidence: [{file_id}::{section}]\n\n"
        "## Dependencies\n"
        "- dep-one\n\n"
        "## Evidence Map\n"
        f"- {section}: [{file_id}::{section}]\n"
    )


def _fake_run_agent(outputs: dict[str, str]):
    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        match = re.search(r"File ID: (F\d{4})", prompt)
        if not match:
            raise RuntimeError("Missing file id in prompt")
        file_id = match.group(1)
        return outputs[file_id]

    return _run_agent


def _setup_workspace(fs, monkeypatch) -> WorkspaceManager:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")
    manager = WorkspaceManager(run_id="run1", input_folder=input_dir)
    manager.initialize(force=True)
    manager.start_phase(Phase.LIBRARY_SYNTHESIS)
    manager.complete_phase(Phase.LIBRARY_SYNTHESIS, outputs={"libraries_count": 1})

    lib_dir = manager.structure.libraries_dir / "LIB-0001"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "charter.md").write_text(
        "# Library Charter: LIB-0001\n\n## Intent\nCore keyword service.\n\n"
        "## Boundaries\nFocus on keyword behaviors.\n\n"
        "## Responsibilities\n- Own keyword workflows\n",
        encoding="utf-8",
    )
    (lib_dir / "evidence.json").write_text(json.dumps({"sources": []}), encoding="utf-8")
    return manager


def test_parse_evidence_mapper_output() -> None:
    payload = {
        "file_id": "F0001",
        "relevant_sections": ["INTRO"],
        "confidence": 0.8,
        "rationale": "Matches charter responsibilities.",
    }
    result = parse_evidence_mapper_output(json.dumps(payload))
    assert result["file_id"] == "F0001"
    assert result["confidence"] == 0.8


def test_parse_evidence_spotcheck_output() -> None:
    payload = {
        "missing_sections": [{"section_label": "INTRO", "rationale": "Missing", "confidence": 0.9}],
        "scan_complete": True,
    }
    result = parse_evidence_spotcheck_output(json.dumps(payload))
    assert result["scan_complete"] is True


def test_expand_evidence_validates_sections(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    summary_path = manager.structure.summaries_dir / "F0001.what.md"
    summary_path.write_text(_make_summary_output("F0001", "INTRO", "keyword"), encoding="utf-8")

    outputs = {
        "F0001": json.dumps(
            {
                "file_id": "F0001",
                "relevant_sections": ["UNKNOWN"],
                "confidence": 0.9,
                "rationale": "Test",
            }
        )
    }

    with patch(
        "spec_manager.refinement.workflows.evidence_expansion.run_agent",
        side_effect=_fake_run_agent(outputs),
    ):
        result = expand_evidence("run1")

    assert any(issue["type"] == "unknown_section_reference" for issue in result["issues"])


def test_expand_evidence_parallel_processing(fs, monkeypatch) -> None:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")
    (input_dir / "b.md").write_text("## Details\n[DETAILS]\n", encoding="utf-8")
    manager = WorkspaceManager(run_id="run1", input_folder=input_dir)
    manager.initialize(force=True)
    manager.start_phase(Phase.LIBRARY_SYNTHESIS)
    manager.complete_phase(Phase.LIBRARY_SYNTHESIS, outputs={"libraries_count": 1})

    lib_dir = manager.structure.libraries_dir / "LIB-0001"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "charter.md").write_text(
        "# Library Charter: LIB-0001\n\n## Intent\nCore keyword service.\n\n"
        "## Boundaries\nFocus on keyword behaviors.\n\n"
        "## Responsibilities\n- Own keyword workflows\n",
        encoding="utf-8",
    )
    (lib_dir / "evidence.json").write_text(json.dumps({"sources": []}), encoding="utf-8")

    summary_dir = manager.structure.summaries_dir
    (summary_dir / "F0001.what.md").write_text(
        _make_summary_output("F0001", "INTRO", "keyword"),
        encoding="utf-8",
    )
    (summary_dir / "F0002.what.md").write_text(
        _make_summary_output("F0002", "DETAILS", "keyword"),
        encoding="utf-8",
    )

    outputs = {
        "F0001": json.dumps(
            {
                "file_id": "F0001",
                "relevant_sections": ["INTRO"],
                "confidence": 0.8,
                "rationale": "Maps intent.",
            }
        ),
        "F0002": json.dumps(
            {
                "file_id": "F0002",
                "relevant_sections": ["DETAILS"],
                "confidence": 0.9,
                "rationale": "Maps boundaries.",
            }
        ),
    }

    with patch(
        "spec_manager.refinement.workflows.evidence_expansion.run_agent",
        side_effect=_fake_run_agent(outputs),
    ):
        result = expand_evidence("run1")

    assert result["libraries_expanded"] == 1
    assert result["evidence_sources_added"] > 0


def test_spotcheck_evidence_adds_missing_sections(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    summary_path = manager.structure.summaries_dir / "F0001.what.md"
    summary_path.write_text(_make_summary_output("F0001", "INTRO", "keyword"), encoding="utf-8")

    lib_dir = manager.structure.libraries_dir / "LIB-0001"
    evidence_path = lib_dir / "evidence.json"
    evidence_path.write_text(
        json.dumps(
            {"sources": [{"file_id": "F0001", "sections": [], "confidence": 0.4, "rationale": ""}]}
        ),
        encoding="utf-8",
    )

    spotcheck_output = json.dumps(
        {
            "missing_sections": [
                {"section_label": "INTRO", "rationale": "Missing", "confidence": 0.95}
            ],
            "scan_complete": True,
        }
    )

    def _run_spotcheck(
        *, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2
    ) -> str:
        return spotcheck_output

    with patch(
        "spec_manager.refinement.workflows.evidence_expansion.run_agent",
        side_effect=_run_spotcheck,
    ):
        result = spotcheck_evidence("run1")

    assert result["missing_sections_added"] > 0
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    sources = payload.get("sources", [])
    assert any("INTRO" in source.get("sections", []) for source in sources)
