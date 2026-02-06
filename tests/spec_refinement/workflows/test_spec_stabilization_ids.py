from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from spec_manager.refinement.workflows.spec_stabilization import (
    allocate_element_id,
    insert_decision_ids,
    insert_element_ids,
    load_id_counters,
    save_id_counters,
    stabilize_specs,
)
from spec_manager.refinement.workspace import Phase

from tests.spec_refinement.fixtures.test_corpus import create_test_corpus


def _create_library_with_spec(manager, lib_id, spec_content: str) -> Path:
    """Helper to create library directory and write spec.md."""
    lib_dir = manager.structure.libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "spec.md").write_text(spec_content, encoding="utf-8")
    return lib_dir


def _load_id_counters(lib_dir: Path) -> dict[str, int]:
    """Helper to load id_counters.json."""
    from spec_manager.refinement.workflows.spec_stabilization import load_id_counters

    return load_id_counters(lib_dir)


def _assert_valid_element_id(element_id: str, lib_id: str, kind: str) -> None:
    """Helper to validate element ID format."""
    if kind == "detail":
        assert re.match(rf"^DTL-{re.escape(lib_id)}-\d{{4}}$", element_id)
    elif kind == "constraint":
        assert re.match(rf"^CON-{re.escape(lib_id)}-\d{{4}}$", element_id)
    elif kind == "analysis":
        assert re.match(rf"^ANL-{re.escape(lib_id)}-\d{{4}}$", element_id)
    elif kind == "overview":
        assert re.match(rf"^OVW-{re.escape(lib_id)}-\d{{4}}$", element_id)


@pytest.fixture
def sample_spec_without_ids() -> str:
    return """# Library Spec

## Details
- Must validate input
- Must log errors

## Constraints
- Keep latency under 100ms
"""


@pytest.fixture
def sample_spec_with_partial_ids() -> str:
    return """# Library Spec

## Details
- DTL-LIB-0001-0001: Existing requirement
- Must add new requirement

## Overview
- OVW-LIB-0001-0001: Existing overview
"""


@pytest.fixture
def corpus_spec(fs) -> str:
    base = Path("/corpus")
    create_test_corpus(fs, base)
    return (base / "alpha.md").read_text(encoding="utf-8")


def test_load_id_counters_creates_default_when_missing(fs) -> None:
    lib_dir = Path("/work/libs/LIB-0001")
    fs.create_dir(lib_dir)

    counters = load_id_counters(lib_dir)

    assert counters == {"DTL": 0, "CON": 0, "ANL": 0, "OVW": 0}


def test_save_and_load_id_counters_roundtrip(fs) -> None:
    lib_dir = Path("/work/libs/LIB-0001")
    fs.create_dir(lib_dir)
    counters = {"DTL": 5, "CON": 3, "ANL": 1, "OVW": 2}

    save_id_counters(lib_dir, counters)

    loaded = load_id_counters(lib_dir)
    assert loaded == counters


def test_allocate_element_id_increments_counter() -> None:
    counters = {"DTL": 10}

    element_id = allocate_element_id("LIB-0001", "DTL", counters)

    assert element_id == "DTL-LIB-0001-0011"
    assert counters["DTL"] == 11


def test_insert_element_ids_adds_ids_to_id_less_bullets(sample_spec_without_ids) -> None:
    counters = {"DTL": 0, "CON": 0, "ANL": 0, "OVW": 0}

    updated, _ = insert_element_ids(sample_spec_without_ids, "LIB-0001", counters)

    assert "- DTL-LIB-0001-0001: Must validate input" in updated


def test_insert_element_ids_preserves_existing_ids(sample_spec_with_partial_ids) -> None:
    counters = {"DTL": 1, "CON": 0, "ANL": 0, "OVW": 1}

    updated, _ = insert_element_ids(sample_spec_with_partial_ids, "LIB-0001", counters)

    assert "- DTL-LIB-0001-0001: Existing requirement" in updated
    assert "- DTL-LIB-0001-0002: Must add new requirement" in updated
    assert "- OVW-LIB-0001-0001: Existing overview" in updated
    assert counters["DTL"] == 2
    assert counters["OVW"] == 1


def test_insert_element_ids_handles_all_sections() -> None:
    spec_content = """# Library Spec

## Details
- Must validate input

## Overview
- System overview item

## Constraints
- Keep latency under 100ms

## Analysis
- Open question about design
"""
    counters = {"DTL": 0, "CON": 0, "ANL": 0, "OVW": 0}

    updated, _ = insert_element_ids(spec_content, "LIB-0001", counters)

    assert "- DTL-LIB-0001-0001: Must validate input" in updated
    assert "- OVW-LIB-0001-0001: System overview item" in updated
    assert "- CON-LIB-0001-0001: Keep latency under 100ms" in updated
    assert "- ANL-LIB-0001-0001: Open question about design" in updated


def test_insert_element_ids_handles_spec_without_all_sections() -> None:
    spec_content = """# Library Spec

## Details
- Must validate input

## Constraints
- Keep latency under 100ms
"""
    counters = {"DTL": 0, "CON": 0, "ANL": 0, "OVW": 0}

    updated, _ = insert_element_ids(spec_content, "LIB-0001", counters)

    assert "- DTL-LIB-0001-0001: Must validate input" in updated
    assert "- CON-LIB-0001-0001: Keep latency under 100ms" in updated


def test_insert_decision_ids_adds_ids_to_decisions() -> None:
    decisions_content = """# Decisions

- Should we use async?
"""
    counters = {"DTL": 0, "CON": 0, "ANL": 0, "OVW": 0}

    updated, _ = insert_decision_ids(decisions_content, "", "LIB-0001", counters)

    assert "- ANL-LIB-0001-0001: Should we use async?" in updated


def test_insert_decision_ids_preserves_existing_decision_ids() -> None:
    decisions_content = """# Decisions

- ANL-LIB-0001-0003: Existing decision
"""
    counters = {"DTL": 0, "CON": 0, "ANL": 3, "OVW": 0}

    updated, _ = insert_decision_ids(decisions_content, "", "LIB-0001", counters)

    assert "- ANL-LIB-0001-0003: Existing decision" in updated
    assert counters["ANL"] == 3


def test_extract_decisions_from_spec_when_decisions_md_empty() -> None:
    spec_content = """# Library Spec

## Analysis
- Should we use async?
"""
    counters = {"DTL": 0, "CON": 0, "ANL": 0, "OVW": 0}

    updated, assigned = insert_decision_ids("", spec_content, "LIB-0001", counters)

    assert updated.startswith("# Decisions")
    assert "- ANL-LIB-0001-0001: Should we use async?" in updated
    assert assigned == 1


def test_stabilization_is_idempotent(sample_spec_without_ids) -> None:
    counters = {"DTL": 0, "CON": 0, "ANL": 0, "OVW": 0}

    first, _ = insert_element_ids(sample_spec_without_ids, "LIB-0001", counters)
    second, _ = insert_element_ids(first, "LIB-0001", counters)

    assert first == second


def test_counter_persistence_across_runs(fs) -> None:
    lib_dir = Path("/work/libraries/LIB-0001")
    fs.create_dir(lib_dir)
    spec_content = """# Library Spec

## Details
- First requirement
"""

    counters = load_id_counters(lib_dir)
    updated, _ = insert_element_ids(spec_content, "LIB-0001", counters)
    save_id_counters(lib_dir, counters)

    updated_with_new = updated.replace(
        "First requirement\n",
        "First requirement\n- New requirement\n",
    )
    counters_next = load_id_counters(lib_dir)
    updated_next, _ = insert_element_ids(updated_with_new, "LIB-0001", counters_next)

    assert "- DTL-LIB-0001-0002: New requirement" in updated_next


def test_id_counters_isolated_per_library(spec_refinement_workspace, corpus_spec, fs) -> None:
    manager, _ = spec_refinement_workspace(run_id="run_ids")
    spec_content = corpus_spec.replace(
        "- Must record audit trail entries.\n",
        "- Must record audit trail entries.\n- Must emit metrics.\n",
    )

    lib_dir_1 = _create_library_with_spec(manager, "LIB-0001", spec_content)
    counters_1 = _load_id_counters(lib_dir_1)
    updated_1, _ = insert_element_ids(spec_content, "LIB-0001", counters_1)
    save_id_counters(lib_dir_1, counters_1)

    lib_dir_2 = _create_library_with_spec(manager, "LIB-0002", spec_content)
    counters_2 = _load_id_counters(lib_dir_2)
    updated_2, _ = insert_element_ids(spec_content, "LIB-0002", counters_2)
    save_id_counters(lib_dir_2, counters_2)

    assert "DTL-LIB-0001" in updated_1
    assert "DTL-LIB-0002" in updated_2
    assert load_id_counters(lib_dir_1)["DTL"] == 3
    assert load_id_counters(lib_dir_2)["DTL"] == 3


def test_id_uniqueness_within_library() -> None:
    requirements = "\n".join([f"- Requirement {idx}" for idx in range(1, 11)])
    spec_content = f"""# Library Spec

## Details
{requirements}
"""
    counters = {"DTL": 0, "CON": 0, "ANL": 0, "OVW": 0}

    updated, _ = insert_element_ids(spec_content, "LIB-0001", counters)

    ids = re.findall(r"DTL-LIB-0001-\d{4}", updated)
    assert ids == [f"DTL-LIB-0001-{idx:04d}" for idx in range(1, 11)]
    for element_id in ids:
        _assert_valid_element_id(element_id, "LIB-0001", "detail")


def test_stabilize_specs_full_pipeline_idempotent(spec_refinement_workspace) -> None:
    """Running stabilize_specs twice produces identical spec.md, decisions.md, indexes, and counters."""
    manager, _ = spec_refinement_workspace(run_id="run_idempotent")

    spec_content = """# Library Spec

## Details
- Must validate input
- Must log errors

## Overview
- User submits request

## Constraints
- Keep latency under 100ms
"""
    decisions_content = """# Decisions

- Database choice question
"""

    for lib_id in ["LIB-0001", "LIB-0002"]:
        lib_dir = _create_library_with_spec(manager, lib_id, spec_content)
        (lib_dir / "decisions.md").write_text(decisions_content, encoding="utf-8")

    manager.start_phase(Phase.SPEC_BUILDING)
    manager.complete_phase(Phase.SPEC_BUILDING, outputs={"built": True})

    # --- First run ---
    result_1 = stabilize_specs(manager.run_id, write_run_index=True)
    assert result_1["success"]

    first_run: dict[str, object] = {}
    for lib_id in ["LIB-0001", "LIB-0002"]:
        lib_dir = manager.structure.libraries_dir / lib_id
        first_run[f"{lib_id}/spec.md"] = (lib_dir / "spec.md").read_text(encoding="utf-8")
        first_run[f"{lib_id}/decisions.md"] = (lib_dir / "decisions.md").read_text(encoding="utf-8")
        first_run[f"{lib_id}/id_counters.json"] = json.loads(
            (lib_dir / "id_counters.json").read_text(encoding="utf-8")
        )
        first_run[f"{lib_id}/spec_index.json"] = json.loads(
            (lib_dir / "spec_index.json").read_text(encoding="utf-8")
        )
        first_run[f"{lib_id}/decisions_index.json"] = json.loads(
            (lib_dir / "decisions_index.json").read_text(encoding="utf-8")
        )

    run_index_path = manager.structure.indexes_dir / "library_spec_index.json"
    first_run_index = json.loads(run_index_path.read_text(encoding="utf-8"))

    # --- Second run ---
    result_2 = stabilize_specs(manager.run_id, write_run_index=True)
    assert result_2["success"]

    # Second run should assign zero new IDs (all already present).
    assert result_2["elements_assigned"] == 0
    assert result_2["decisions_assigned"] == 0

    for lib_id in ["LIB-0001", "LIB-0002"]:
        lib_dir = manager.structure.libraries_dir / lib_id

        # spec.md and decisions.md must be byte-identical.
        assert (lib_dir / "spec.md").read_text(encoding="utf-8") == first_run[f"{lib_id}/spec.md"]
        assert (lib_dir / "decisions.md").read_text(encoding="utf-8") == first_run[
            f"{lib_id}/decisions.md"
        ]

        # id_counters.json must preserve counter values across runs.
        counters_2 = json.loads((lib_dir / "id_counters.json").read_text(encoding="utf-8"))
        assert counters_2 == first_run[f"{lib_id}/id_counters.json"]

        # Index content must match (generated_at timestamps may differ).
        spec_idx_1 = first_run[f"{lib_id}/spec_index.json"]
        spec_idx_2 = json.loads((lib_dir / "spec_index.json").read_text(encoding="utf-8"))
        assert spec_idx_2["lib_id"] == spec_idx_1["lib_id"]
        assert spec_idx_2["spec_path"] == spec_idx_1["spec_path"]
        assert spec_idx_2["elements"] == spec_idx_1["elements"]

        dec_idx_1 = first_run[f"{lib_id}/decisions_index.json"]
        dec_idx_2 = json.loads((lib_dir / "decisions_index.json").read_text(encoding="utf-8"))
        assert dec_idx_2["lib_id"] == dec_idx_1["lib_id"]
        assert dec_idx_2["decisions_path"] == dec_idx_1["decisions_path"]
        assert dec_idx_2["decisions"] == dec_idx_1["decisions"]

    # Run-level aggregate index must match.
    run_index_2 = json.loads(run_index_path.read_text(encoding="utf-8"))
    assert len(run_index_2["libraries"]) == len(first_run_index["libraries"])
    for entry_1, entry_2 in zip(
        first_run_index["libraries"], run_index_2["libraries"], strict=True
    ):
        assert entry_1["lib_id"] == entry_2["lib_id"]
        assert entry_1["elements"] == entry_2["elements"]
