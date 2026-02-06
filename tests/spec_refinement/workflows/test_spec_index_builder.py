from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from spec_manager.refinement.workflows.spec_stabilization import (
    build_decisions_index,
    build_spec_index,
    stabilize_specs,
)
from spec_manager.refinement.workspace import Phase
from spec_manager.schemas.spec_indexes import DecisionsIndex, SpecIndex


def _create_library_with_spec(manager, lib_id, spec_content: str) -> Path:
    """Helper to create library directory and write spec.md."""
    lib_dir = manager.structure.libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "spec.md").write_text(spec_content, encoding="utf-8")
    return lib_dir


@pytest.fixture
def sample_spec_for_indexing() -> str:
    return """# Library Spec

## Details
- DTL-LIB-0001-0001: Must validate input [spec_snapshot/specs/alpha.md::SEC-F0001-0001]
- DTL-LIB-0001-0002: Must log errors referencing LIB-0002
- DTL-LIB-0001-0003: User submits request
- DTL-LIB-0001-0004: System validates and processes

## Constraints
- CON-LIB-0001-0001: Keep latency under 100ms
"""


@pytest.fixture
def sample_decisions_for_indexing() -> str:
    return """# Analysis

- ANL-LIB-0001-0001: Should we use async?
  **Status**: open
  **Question**: Should we use async processing?
  **Options**: sync, async, hybrid
  **Default**: sync
  **Context**: Performance vs complexity tradeoff
  [spec_snapshot/specs/alpha.md::SEC-F0001-0001]

- ANL-LIB-0001-0002: Database choice
  **Status**: resolved
  **Question**: Which database to use?
"""


def test_build_spec_index_extracts_all_elements() -> None:
    spec_content = """# Library Spec

## Details
- DTL-LIB-0001-0001: One
- DTL-LIB-0001-0002: Two
- DTL-LIB-0001-0003: Three
- DTL-LIB-0001-0004: Flow one
- DTL-LIB-0001-0005: Flow two

## Constraints
- CON-LIB-0001-0001: Constraint
"""

    index = build_spec_index(spec_content, "LIB-0001")

    assert len(index["elements"]) == 6


def test_build_spec_index_sets_correct_element_kinds(sample_spec_for_indexing) -> None:
    index = build_spec_index(sample_spec_for_indexing, "LIB-0001")
    kinds = {element["element_id"]: element["kind"] for element in index["elements"]}

    assert kinds["DTL-LIB-0001-0001"] == "detail"
    assert kinds["DTL-LIB-0001-0002"] == "detail"
    assert kinds["DTL-LIB-0001-0003"] == "detail"
    assert kinds["DTL-LIB-0001-0004"] == "detail"
    assert kinds["CON-LIB-0001-0001"] == "constraint"


def test_build_spec_index_extracts_citations(sample_spec_for_indexing) -> None:
    index = build_spec_index(sample_spec_for_indexing, "LIB-0001")
    element = next(item for item in index["elements"] if item["element_id"] == "DTL-LIB-0001-0001")

    assert "[spec_snapshot/specs/alpha.md::SEC-F0001-0001]" in element["citations"]


def test_build_spec_index_extracts_mentions_libs() -> None:
    spec_content = """# Library Spec

## Details
- DTL-LIB-0001-0001: Depends on LIB-0002 and LIB-0005
"""

    index = build_spec_index(spec_content, "LIB-0001")

    assert index["elements"][0]["mentions_libs"] == ["LIB-0002", "LIB-0005"]


def test_build_spec_index_removes_id_prefix_from_text() -> None:
    spec_content = """# Library Spec

## Details
- DTL-LIB-0001-0001: Must validate
"""

    index = build_spec_index(spec_content, "LIB-0001")

    assert index["elements"][0]["text"] == "Must validate"


def test_build_spec_index_preserves_raw_line(sample_spec_for_indexing) -> None:
    index = build_spec_index(sample_spec_for_indexing, "LIB-0001")
    element = next(item for item in index["elements"] if item["element_id"] == "DTL-LIB-0001-0002")

    assert element["raw_line"] == "- DTL-LIB-0001-0002: Must log errors referencing LIB-0002"


def test_build_decisions_index_extracts_all_decisions() -> None:
    decisions_content = """# Analysis

- ANL-LIB-0001-0001: Question one
- ANL-LIB-0001-0002: Question two
- ANL-LIB-0001-0003: Question three
"""

    index = build_decisions_index(decisions_content, "LIB-0001")

    assert len(index["decisions"]) == 3


def test_build_decisions_index_parses_structured_fields() -> None:
    decisions_content = """# Analysis

- ANL-LIB-0001-0001: Should we use async?
  - status: open
  - options: sync, async
  - default: sync
  - context: Performance vs complexity
"""

    index = build_decisions_index(decisions_content, "LIB-0001")
    decision = index["decisions"][0]

    assert decision["status"] == "open"
    assert decision["question"] == "Should we use async?"
    assert decision["options"] == ["sync", "async"]
    assert decision["default"] == "sync"
    assert decision["context"] == "Performance vs complexity"


def test_build_decisions_index_extracts_status() -> None:
    decisions_content = """# Analysis

- ANL-LIB-0001-0001: Should we use async?
  - status: resolved
"""

    index = build_decisions_index(decisions_content, "LIB-0001")

    assert index["decisions"][0]["status"] == "resolved"


def test_build_decisions_index_handles_minimal_decision() -> None:
    decisions_content = """# Analysis

- ANL-LIB-0001-0001: Should we use async?
"""

    index = build_decisions_index(decisions_content, "LIB-0001")
    decision = index["decisions"][0]

    assert decision["status"] == "open"
    assert decision["context"] in ("", None)
    assert decision["options"] == []
    assert decision["default"] is None


def test_build_decisions_index_extracts_citations() -> None:
    decisions_content = """# Analysis

- ANL-LIB-0001-0001: Should we use async? [spec_snapshot/specs/alpha.md::SEC-F0001-0001]
"""

    index = build_decisions_index(decisions_content, "LIB-0001")

    assert "[spec_snapshot/specs/alpha.md::SEC-F0001-0001]" in index["decisions"][0]["citations"]


def test_spec_index_validates_against_pydantic_schema(sample_spec_for_indexing) -> None:
    index = build_spec_index(sample_spec_for_indexing, "LIB-0001")

    SpecIndex.model_validate(index)


def test_decisions_index_validates_against_pydantic_schema(
    sample_decisions_for_indexing,
) -> None:
    index = build_decisions_index(sample_decisions_for_indexing, "LIB-0001")

    DecisionsIndex.model_validate(index)


def test_spec_index_rejects_invalid_element_id() -> None:
    payload = {
        "lib_id": "LIB-0001",
        "generated_at": "2024-01-15T10:30:00",
        "spec_path": "libraries/LIB-0001/spec.md",
        "elements": [
            {
                "element_id": "INVALID-ID",
                "kind": "detail",
                "section": "Details",
                "text": "Bad",
                "raw_line": "- INVALID-ID: Bad",
                "citations": [],
                "mentions_libs": [],
            }
        ],
    }

    with pytest.raises(ValidationError):
        SpecIndex.model_validate(payload)


def test_decisions_index_rejects_invalid_decision_id() -> None:
    payload = {
        "lib_id": "LIB-0001",
        "generated_at": "2024-01-15T10:30:00",
        "decisions_path": "libraries/LIB-0001/decisions.md",
        "decisions": [
            {
                "decision_id": "INVALID-ANL",
                "status": "open",
                "question": "Question?",
                "context": "",
                "options": [],
                "default": None,
                "citations": [],
            }
        ],
    }

    with pytest.raises(ValidationError):
        DecisionsIndex.model_validate(payload)


def test_spec_index_validates_iso8601_timestamp() -> None:
    payload = {
        "lib_id": "LIB-0001",
        "generated_at": "2024-01-15T10:30:00",
        "spec_path": "libraries/LIB-0001/spec.md",
        "elements": [],
    }

    SpecIndex.model_validate(payload)

    payload["generated_at"] = "15-01-2024"
    with pytest.raises(ValidationError):
        SpecIndex.model_validate(payload)


def test_write_spec_index_creates_valid_json(fs) -> None:
    lib_dir = Path("/work/libraries/LIB-0001")
    fs.create_dir(lib_dir)
    spec_content = """# Library Spec

## Details
- DTL-LIB-0001-0001: Must validate
"""
    index = build_spec_index(spec_content, "LIB-0001")

    index_path = lib_dir / "spec_index.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    parsed = json.loads(index_path.read_text(encoding="utf-8"))
    SpecIndex.model_validate(parsed)


def test_write_decisions_index_creates_valid_json(fs) -> None:
    lib_dir = Path("/work/libraries/LIB-0001")
    fs.create_dir(lib_dir)
    decisions_content = """# Analysis

- ANL-LIB-0001-0001: Should we use async?
"""
    index = build_decisions_index(decisions_content, "LIB-0001")

    index_path = lib_dir / "decisions_index.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    parsed = json.loads(index_path.read_text(encoding="utf-8"))
    DecisionsIndex.model_validate(parsed)


def test_build_aggregate_index_merges_all_libraries(spec_refinement_workspace) -> None:
    manager, _ = spec_refinement_workspace(run_id="run_index_001")
    spec_content = """# Library Spec

## Details
- Must validate input
"""

    for lib_id in ["LIB-0001", "LIB-0002", "LIB-0003"]:
        _create_library_with_spec(manager, lib_id, spec_content)

    manager.start_phase(Phase.SPEC_BUILDING)
    manager.complete_phase(Phase.SPEC_BUILDING, outputs={"built": True})

    stabilize_specs(manager.run_id, write_run_index=True)

    run_index_path = manager.structure.indexes_dir / "library_spec_index.json"
    payload = json.loads(run_index_path.read_text(encoding="utf-8"))

    assert len(payload["libraries"]) == 3
    assert all(entry["elements"] for entry in payload["libraries"])


def test_aggregate_index_preserves_lib_id_per_element(
    spec_refinement_workspace,
) -> None:
    manager, _ = spec_refinement_workspace(run_id="run_index_002")
    spec_content = """# Library Spec

## Details
- Must validate input
"""

    for lib_id in ["LIB-0001", "LIB-0002", "LIB-0003"]:
        _create_library_with_spec(manager, lib_id, spec_content)

    manager.start_phase(Phase.SPEC_BUILDING)
    manager.complete_phase(Phase.SPEC_BUILDING, outputs={"built": True})

    stabilize_specs(manager.run_id, write_run_index=True)

    run_index_path = manager.structure.indexes_dir / "library_spec_index.json"
    payload = json.loads(run_index_path.read_text(encoding="utf-8"))

    for entry in payload["libraries"]:
        lib_id = entry["lib_id"]
        for element in entry["elements"]:
            assert f"{lib_id}-" in element["element_id"]
