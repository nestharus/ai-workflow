from __future__ import annotations

import json
from pathlib import Path

from spec_manager.refinement.formats import LibraryCharter, LibraryEvent, LibraryEventType
from spec_manager.refinement.workflows.library_labeling import resolve_all_overlaps
from spec_manager.refinement.workflows.library_synthesis import (
    _read_library_events,
    _validate_event_monotonicity,
    _write_library_event,
    synthesize_libraries,
)
from spec_manager.refinement.workspace import Phase, WorkspaceManager, WorkspaceState


def _setup_workspace(fs, monkeypatch, run_id: str = "run_001") -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    specs_dir = base / "specs"
    fs.create_dir(specs_dir)
    (specs_dir / "alpha.md").write_text("# Alpha\n\n## Intro\nA\n", encoding="utf-8")
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("specs"))
    issues = manager.initialize(force=True)
    assert issues == []
    return manager


def test_library_event_write_and_read(fs) -> None:
    lib_dir = Path("/work/libraries/LIB-0001")
    fs.create_dir(lib_dir)

    event = LibraryEvent(
        event_type=LibraryEventType.LIBRARY_CREATED,
        timestamp="2024-01-01T00:00:00",
        lib_id="LIB-0001",
        metadata={"created_from": [], "initial_intent": "Core", "initial_files": ["F0001"]},
        previous_state=None,
    )

    _write_library_event(lib_dir, event)

    events = _read_library_events(lib_dir)
    assert len(events) == 1
    assert events[0].event_type == LibraryEventType.LIBRARY_CREATED
    assert events[0].metadata["initial_files"] == ["F0001"]


def test_library_id_allocation_persists(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch, run_id="run_002")
    assert manager.allocate_library_id() == "LIB-0001"

    state_path = Path("/work/runs/run_002/state.json")
    assert state_path.exists()

    reloaded = WorkspaceManager(run_id="run_002", input_folder=Path("specs"))
    assert "LIB-0001" in reloaded.state.allocated_library_ids
    assert reloaded.state.next_library_number == 2


def test_event_validation_detects_conflicts() -> None:
    events = [
        LibraryEvent(
            event_type=LibraryEventType.LIBRARY_CREATED,
            timestamp="2024-01-02T00:00:00",
            lib_id="LIB-0001",
            metadata={"created_from": [], "initial_intent": "", "initial_files": []},
            previous_state=None,
        ),
        LibraryEvent(
            event_type=LibraryEventType.LIBRARY_CREATED,
            timestamp="2024-01-03T00:00:00",
            lib_id="LIB-0001",
            metadata={"created_from": [], "initial_intent": "", "initial_files": []},
            previous_state=None,
        ),
        LibraryEvent(
            event_type=LibraryEventType.LIBRARY_RENAMED,
            timestamp="2024-01-01T00:00:00",
            lib_id="LIB-0001",
            metadata={"old_name": "Old", "new_name": "New", "reason": "Rename"},
            previous_state=None,
        ),
    ]

    issues = _validate_event_monotonicity(events)
    issue_types = {issue["type"] for issue in issues}
    assert "library_created_duplicate" in issue_types
    assert "library_event_timestamp_not_monotonic" in issue_types


def test_migration_creates_synthetic_events(fs, monkeypatch) -> None:
    base = Path("/work")
    fs.create_dir(base)
    run_dir = base / "runs" / "run_legacy"
    libraries_dir = run_dir / "libraries" / "LIB-0001"
    fs.create_dir(libraries_dir)
    (libraries_dir / "charter.md").write_text(
        "# Library Charter: LIB-0001\n\n## Intent\nLegacy intent\n\n## Evidence\n- [F0001::INTRO]\n",
        encoding="utf-8",
    )

    state_payload = {
        "run_id": "run_legacy",
        "input_folder": "specs",
        "schema_version": "1.0",
        "current_phase": "init",
        "mode": "snapshot",
        "phases": {},
        "history": [],
        "file_manifest": {},
        "section_manifest": {},
    }
    state_path = run_dir / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state_payload), encoding="utf-8")

    monkeypatch.chdir(base)
    state = WorkspaceState.load(state_path)

    assert "LIB-0001" in state.allocated_library_ids
    assert state.next_library_number == 2

    events_path = libraries_dir / "events.jsonl"
    assert events_path.exists()
    event_payload = json.loads(events_path.read_text(encoding="utf-8").splitlines()[0])
    assert event_payload["event_type"] == "LIBRARY_CREATED"
    assert event_payload["metadata"]["synthetic"] is True


def test_cross_cutting_overlap_records_events(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch, run_id="run_003")
    manager.state.register_library_id("LIB-0001")
    manager.state.register_library_id("LIB-0002")

    charter_a = LibraryCharter(
        lib_id="LIB-0001",
        intent="A",
        boundaries="A",
        responsibilities=[],
        evidence_sources=[{"file_id": "F0001", "sections": ["INTRO"]}],
        overlap_resolutions=[],
    )
    charter_b = LibraryCharter(
        lib_id="LIB-0002",
        intent="B",
        boundaries="B",
        responsibilities=[],
        evidence_sources=[{"file_id": "F0001", "sections": ["INTRO"]}],
        overlap_resolutions=[],
    )

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        if agent_name == "glm-library-overlap-resolver":
            return json.dumps(
                {
                    "decision": "create_cross_cutting",
                    "rationale": "Shared boundary.",
                    "affected_files": ["F0001"],
                }
            )
        raise AssertionError(f"Unexpected agent: {agent_name}")

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_labeling.run_agent",
        _run_agent,
    )

    decisions = resolve_all_overlaps([charter_a, charter_b], manager)
    assert any(decision.get("created_lib_id") == "LIB-0003" for decision in decisions)

    created_events = _read_library_events(manager.structure.libraries_dir / "LIB-0003")
    created_event = next(
        event for event in created_events if event.event_type == LibraryEventType.LIBRARY_CREATED
    )
    assert set(created_event.metadata["created_from"]) == {"LIB-0001", "LIB-0002"}

    events_a = _read_library_events(manager.structure.libraries_dir / "LIB-0001")
    events_b = _read_library_events(manager.structure.libraries_dir / "LIB-0002")
    assert any(event.event_type == LibraryEventType.LIBRARY_SPLIT for event in events_a)
    assert any(event.event_type == LibraryEventType.LIBRARY_SPLIT for event in events_b)


def test_out_of_scope_concern_produces_gap_or_dec(fs, monkeypatch) -> None:
    """Verify out-of-scope concerns generate GAP/DEC entries, not silent drops."""
    manager = _setup_workspace(fs, monkeypatch, run_id="run_qa_001")

    manager.start_phase(Phase.SUMMARIZATION)
    manager.complete_phase(Phase.SUMMARIZATION, outputs={"summaries_count": 1})

    summaries_dir = manager.structure.summaries_dir
    summaries_dir.mkdir(parents=True, exist_ok=True)

    file_id = "F0001"
    summary_content = """# File Summary: F0001
File ID: F0001

## Algorithms
- Authentication system | Handles auth | Evidence: [F0001::INTRO]

## Components
- Database migration tooling | Handles migrations | Evidence: [F0001::INTRO]

## Workflows
- User profile management | Handles profiles | Evidence: [F0001::INTRO]
"""

    (summaries_dir / f"{file_id}.what.md").write_text(summary_content, encoding="utf-8")
    manager.state.section_manifest[file_id] = ["INTRO"]
    manager._save_state()

    def _mock_run_agent(
        *, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2
    ) -> str:
        if agent_name == "glm-file-library-labeler":
            return json.dumps(
                {
                    "candidate_labels": [
                        {
                            "label": "Alpha",
                            "sections": ["[F0001::INTRO]"],
                            "confidence": 0.8,
                            "rationale": "Matches the summary.",
                        }
                    ],
                    "uncertain_labels": [],
                }
            )
        if agent_name == "opus-library-label-refiner":
            return json.dumps(
                [
                    {
                        "lib_id": "LIB-0001",
                        "final_label": "Alpha",
                        "merged_from": ["Alpha"],
                        "split_notes": "",
                        "stable_internal_id": "LIB-0001",
                    }
                ]
            )
        if agent_name == "opus-library-synthesizer":
            return (
                "## Library Index\n"
                "- LIB-0001: Core Workflow Library\n\n"
                "## Library Charters\n"
                "### LIB-0001\n"
                "#### Intent\n"
                "Own core workflow responsibilities.\n\n"
                "#### Boundaries\n"
                "Includes orchestrator and runner coordination.\n\n"
                "#### Responsibilities\n"
                "- Handle phase transitions\n\n"
                "#### Evidence\n"
                "- [F0001::INTRO]\n\n"
                "#### Overlap Resolutions\n"
                "- Workflow vs orchestration -> Assign to LIB-0001\n"
            )
        if agent_name == "glm-library-overlap-resolver":
            return json.dumps(
                {
                    "decision": "assign_to_lib_A",
                    "rationale": "Overlap belongs to library A.",
                    "affected_files": ["F0001"],
                }
            )
        if "concern-assignment-judge" in agent_name:
            return json.dumps(
                {
                    "assignments": [
                        {
                            "concern_id": "F0001:algorithm:001",
                            "file_id": "F0001",
                            "concern_type": "algorithm",
                            "concern_text": "Authentication system | Handles auth",
                            "assigned_to": ["LIB-0001"],
                            "confidence": 0.95,
                            "rationale": "[F0001::INTRO]",
                        },
                        {
                            "concern_id": "F0001:workflow:001",
                            "file_id": "F0001",
                            "concern_type": "workflow",
                            "concern_text": "User profile management | Handles profiles",
                            "assigned_to": ["LIB-0001"],
                            "confidence": 0.9,
                            "rationale": "[F0001::INTRO]",
                        },
                    ],
                    "gaps": [
                        {
                            "concern_id": "F0001:component:001",
                            "file_id": "F0001",
                            "concern_type": "component",
                            "concern_text": "Database migration tooling | Handles migrations",
                            "gap_type": "out_of_scope",
                            "rationale": "Infrastructure concerns are outside library scope.",
                            "severity": "info",
                        }
                    ],
                    "decisions": [],
                }
            )
        return "{}"

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_labeling.run_agent", _mock_run_agent
    )

    result = synthesize_libraries("run_qa_001")

    evidence_path = manager.structure.intermediates_dir / "pass_04" / "evidence.jsonl"
    assert evidence_path.exists(), "Evidence file must exist for out-of-scope concerns"

    evidence_lines = evidence_path.read_text(encoding="utf-8").splitlines()
    gap_entries = [json.loads(line) for line in evidence_lines if line.strip()]

    assert len(gap_entries) > 0, "Must have at least one GAP entry"
    assert any(
        entry.get("gap_type") == "out_of_scope"
        and "migration" in str(entry.get("concern_text", "")).lower()
        for entry in gap_entries
    ), "Out-of-scope concern must be recorded as GAP"

    issues = result.get("issues", [])
    silent_drop_issues = [i for i in issues if i.get("type") == "concern_silently_dropped"]
    assert len(silent_drop_issues) == 0, "No concerns should be silently dropped"
