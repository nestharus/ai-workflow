from __future__ import annotations

import json
from pathlib import Path

from spec_manager.refinement.formats import LibraryCharter, LibraryEvent, LibraryEventType
from spec_manager.refinement.workflows.library_labeling import resolve_all_overlaps
from spec_manager.refinement.workflows.library_synthesis import (
    _read_library_events,
    _validate_event_monotonicity,
    _write_library_event,
)
from spec_manager.refinement.workspace import WorkspaceManager, WorkspaceState


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
    lib_dir = Path("/work/libraries/lib_001")
    fs.create_dir(lib_dir)

    event = LibraryEvent(
        event_type=LibraryEventType.LIBRARY_CREATED,
        timestamp="2024-01-01T00:00:00",
        lib_id="lib_001",
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
    assert manager.allocate_library_id() == "lib_001"

    state_path = Path("/work/runs/run_002/state.json")
    assert state_path.exists()

    reloaded = WorkspaceManager(run_id="run_002", input_folder=Path("specs"))
    assert "lib_001" in reloaded.state.allocated_library_ids
    assert reloaded.state.next_library_number == 2


def test_event_validation_detects_conflicts() -> None:
    events = [
        LibraryEvent(
            event_type=LibraryEventType.LIBRARY_CREATED,
            timestamp="2024-01-02T00:00:00",
            lib_id="lib_001",
            metadata={"created_from": [], "initial_intent": "", "initial_files": []},
            previous_state=None,
        ),
        LibraryEvent(
            event_type=LibraryEventType.LIBRARY_CREATED,
            timestamp="2024-01-03T00:00:00",
            lib_id="lib_001",
            metadata={"created_from": [], "initial_intent": "", "initial_files": []},
            previous_state=None,
        ),
        LibraryEvent(
            event_type=LibraryEventType.LIBRARY_RENAMED,
            timestamp="2024-01-01T00:00:00",
            lib_id="lib_001",
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
    libraries_dir = run_dir / "libraries" / "lib_001"
    fs.create_dir(libraries_dir)
    (libraries_dir / "charter.md").write_text(
        "# Library Charter: lib_001\n\n## Intent\nLegacy intent\n\n## Evidence\n- [F0001::INTRO]\n",
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

    assert "lib_001" in state.allocated_library_ids
    assert state.next_library_number == 2

    events_path = libraries_dir / "events.jsonl"
    assert events_path.exists()
    event_payload = json.loads(events_path.read_text(encoding="utf-8").splitlines()[0])
    assert event_payload["event_type"] == "LIBRARY_CREATED"
    assert event_payload["metadata"]["synthetic"] is True


def test_cross_cutting_overlap_records_events(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch, run_id="run_003")
    manager.state.register_library_id("lib_001")
    manager.state.register_library_id("lib_002")

    charter_a = LibraryCharter(
        lib_id="lib_001",
        intent="A",
        boundaries="A",
        responsibilities=[],
        evidence_sources=[{"file_id": "F0001", "sections": ["INTRO"]}],
        overlap_resolutions=[],
    )
    charter_b = LibraryCharter(
        lib_id="lib_002",
        intent="B",
        boundaries="B",
        responsibilities=[],
        evidence_sources=[{"file_id": "F0001", "sections": ["INTRO"]}],
        overlap_resolutions=[],
    )

    def _run_agent(
        *, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2
    ) -> str:
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
    assert any(decision.get("created_lib_id") == "lib_003" for decision in decisions)

    created_events = _read_library_events(manager.structure.libraries_dir / "lib_003")
    created_event = next(
        event
        for event in created_events
        if event.event_type == LibraryEventType.LIBRARY_CREATED
    )
    assert set(created_event.metadata["created_from"]) == {"lib_001", "lib_002"}

    events_a = _read_library_events(manager.structure.libraries_dir / "lib_001")
    events_b = _read_library_events(manager.structure.libraries_dir / "lib_002")
    assert any(event.event_type == LibraryEventType.LIBRARY_SPLIT for event in events_a)
    assert any(event.event_type == LibraryEventType.LIBRARY_SPLIT for event in events_b)
