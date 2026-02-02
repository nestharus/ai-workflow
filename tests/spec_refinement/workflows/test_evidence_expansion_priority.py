from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest
from spec_manager.refinement.workflows.evidence_expansion import expand_evidence, spotcheck_evidence
from spec_manager.refinement.workspace import Phase, WorkspaceManager


def _setup_workspace(fs, monkeypatch, run_id: str = "run_001") -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    input_dir = base / "specs"
    fs.create_dir(input_dir)

    for name in ["alpha.md", "beta.md", "gamma.md", "delta.md"]:
        (input_dir / name).write_text(
            "# Spec\n\n[INTRO]\nDetails referencing (lib_001).\n",
            encoding="utf-8",
        )

    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id=run_id, input_folder=input_dir)
    issues = manager.initialize(force=True)
    assert issues == []

    for file_id in manager.state.file_manifest:
        summary_path = manager.structure.summaries_dir / f"{file_id}.what.md"
        summary_path.write_text(
            f"File Summary: {file_id}\n\n## Evidence Map\n- INTRO: [{file_id}::INTRO]\n",
            encoding="utf-8",
        )

    lib_dir = manager.structure.libraries_dir / "lib_001"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "charter.md").write_text(
        "# Library Charter\n\n## Intent\nPayments handling.\n\n"
        "## Boundaries\nPayments and billing systems.\n\n"
        "## Responsibilities\n- Process payments.\n",
        encoding="utf-8",
    )

    manager.complete_phase(Phase.LIBRARY_SYNTHESIS)
    return manager


def _write_file_labels(manager: WorkspaceManager, file_ids: list[str]) -> None:
    file_labels = {
        file_ids[0]: {
            "candidate_labels": [
                {
                    "label": "Payments",
                    "sections": [f"[{file_ids[0]}::INTRO]"],
                    "confidence": 0.8,
                    "rationale": "Directly matches payments scope.",
                }
            ],
            "uncertain_labels": [],
        },
        file_ids[1]: {
            "candidate_labels": [
                {
                    "label": "Payments",
                    "sections": [f"[{file_ids[1]}::INTRO]"],
                    "confidence": 0.5,
                    "rationale": "Possibly in scope.",
                }
            ],
            "uncertain_labels": [],
        },
        file_ids[2]: {
            "candidate_labels": [
                {
                    "label": "Payments",
                    "sections": [f"[{file_ids[2]}::INTRO]"],
                    "confidence": 0.2,
                    "rationale": "Unlikely to be in scope.",
                }
            ],
            "uncertain_labels": [],
        },
        file_ids[3]: {
            "candidate_labels": [
                {
                    "label": "Payments",
                    "sections": [f"[{file_ids[3]}::INTRO]"],
                    "confidence": 0.35,
                    "rationale": "Low-confidence match.",
                }
            ],
            "uncertain_labels": [],
        },
    }

    labels_path = manager.structure.libraries_dir / "file_labels.json"
    labels_path.write_text(json.dumps(file_labels, indent=2), encoding="utf-8")


def test_evidence_expansion_priority_flow(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    file_ids = sorted(manager.state.file_manifest.keys())
    _write_file_labels(manager, file_ids)

    calls: dict[str, list[str]] = {
        "glm-library-evidence-mapper": [],
        "glm-library-relevance-classifier": [],
        "chatgpt-evidence-gap-judge": [],
    }
    lock = threading.Lock()

    def _record_call(agent_name: str, file_id: str) -> None:
        with lock:
            calls.setdefault(agent_name, []).append(file_id)

    def _fake_run_agent(
        *, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2
    ) -> str:
        match = re.search(r"File ID: (F\d{4})", prompt)
        if not match:
            match = re.search(r"File Summary: (F\d{4})", prompt)
        file_id = match.group(1) if match else "unknown"
        _record_call(agent_name, file_id)

        if agent_name == "glm-library-relevance-classifier":
            return json.dumps(
                {
                    "relevant": "yes",
                    "rationale": "Aligned to payments responsibilities.",
                    "confidence": 0.72,
                }
            )
        if agent_name == "glm-library-evidence-mapper":
            return json.dumps(
                {
                    "file_id": file_id,
                    "relevant_sections": ["INTRO"],
                    "confidence": 0.8,
                    "rationale": f"Matches payments scope. [{file_id}::INTRO]",
                }
            )
        if agent_name == "chatgpt-evidence-gap-judge":
            return json.dumps({"missing_sections": [], "scan_complete": True})

        raise AssertionError(f"Unexpected agent: {agent_name}")

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.evidence_expansion.run_agent",
        _fake_run_agent,
    )

    expand_evidence("run_001")

    assert calls["glm-library-relevance-classifier"] == [file_ids[1]]

    mapper_calls = set(calls["glm-library-evidence-mapper"])
    assert mapper_calls == {file_ids[0], file_ids[1], file_ids[3]}
    assert file_ids[2] not in mapper_calls

    evidence_path = manager.structure.libraries_dir / "lib_001" / "evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    sources = payload.get("sources", [])
    by_file = {source.get("file_id"): source for source in sources}

    assert by_file[file_ids[0]]["priority"] == pytest.approx(0.8)
    assert by_file[file_ids[1]]["priority"] == pytest.approx(0.7)
    assert by_file[file_ids[3]]["priority"] == pytest.approx(0.35)
    assert file_ids[2] not in by_file

    assert by_file[file_ids[0]]["priority_rationale"] == "high_confidence_from_labeler"
    assert by_file[file_ids[1]]["priority_rationale"] == "classifier_confirmed"
    assert by_file[file_ids[3]]["priority_rationale"] == "low_confidence_skip"

    calls["chatgpt-evidence-gap-judge"].clear()
    spotcheck_evidence("run_001", lib_ids=["lib_001"])

    spotcheck_calls = calls["chatgpt-evidence-gap-judge"]
    assert spotcheck_calls[0] == file_ids[3]
    assert file_ids[2] in spotcheck_calls
    assert file_ids[0] not in spotcheck_calls
