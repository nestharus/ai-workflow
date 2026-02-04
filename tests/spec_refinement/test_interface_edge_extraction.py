from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest
from spec_manager.refinement.workflows.interfaces import (
    _extract_edges_via_llm,
    _merge_and_deduplicate_edges,
    _scan_spec_indexes_for_lib_mentions,
    extract_interface_edges,
)
from spec_manager.refinement.workspace import Phase, WorkspaceManager
from spec_manager.schemas.edge_list import allocate_edge_id

from tests.spec_refinement.fixtures.test_corpus import create_interface_test_libraries

pytestmark = [pytest.mark.interfaces, pytest.mark.edge_extraction]


def _setup_interface_workspace(fs, monkeypatch, run_id: str = "run_interfaces"):
    base = Path("/work")
    fs.create_dir(base)
    input_dir = base / "specs"
    fs.create_dir(input_dir)
    (input_dir / "input.md").write_text("# Input\n\n## Intro\nSeed\n", encoding="utf-8")

    monkeypatch.chdir(base)
    manager = WorkspaceManager(run_id=run_id, input_folder=input_dir)
    issues = manager.initialize(force=True)
    assert issues == []

    manifest = create_interface_test_libraries(fs, run_id=run_id)
    for lib_id in manifest["library_ids"]:
        manager.state.register_library_id(lib_id)
    manager.save_state()

    manager.start_phase(Phase.LIBRARY_STRUCTURE_REVIEW)
    manager.complete_phase(Phase.LIBRARY_STRUCTURE_REVIEW, outputs={"libraries": 3})
    manager.start_phase(Phase.ARCHITECTURE_MAPPING)
    manager.complete_phase(Phase.ARCHITECTURE_MAPPING, outputs={"mapped": 3})

    return manager, manifest


def _create_library_with_cross_refs(
    manager: WorkspaceManager,
    lib_id: str,
    provider_libs: list[str],
    fs=None,
) -> list[str]:
    manager.state.register_library_id(lib_id)
    absolute_lib_dir = Path.cwd() / manager.structure.libraries_dir / lib_id
    relative_lib_dir = manager.structure.libraries_dir / lib_id
    lib_dirs = [absolute_lib_dir]
    if relative_lib_dir != absolute_lib_dir:
        lib_dirs.append(relative_lib_dir)

    if fs is not None:
        for lib_dir in lib_dirs:
            if not lib_dir.exists():
                fs.create_dir(str(lib_dir))
    else:
        absolute_lib_dir.mkdir(parents=True, exist_ok=True)

    lib_suffix = lib_id.split("-", 1)[1]
    elements = []
    spec_lines = [f"# Library Spec: {lib_id}", "", "## Requirements"]
    for index, provider in enumerate(provider_libs, start=1):
        element_id = f"REQ-LIB-{lib_suffix}-{index:04d}"
        text = f"Depends on {provider} for integration."
        line = f"- {element_id}: {text} [{lib_id}::spec.md::{element_id}]"
        spec_lines.append(line)
        elements.append(
            {
                "element_id": element_id,
                "kind": "requirement",
                "section": "Requirements",
                "text": text,
                "raw_line": line,
                "citations": [f"[{lib_id}::spec.md::{element_id}]"],
                "mentions_libs": [provider],
            }
        )
    if not provider_libs:
        spec_lines.append(f"- REQ-LIB-{lib_suffix}-0001: Standalone requirement.")
        elements.append(
            {
                "element_id": f"REQ-LIB-{lib_suffix}-0001",
                "kind": "requirement",
                "section": "Requirements",
                "text": "Standalone requirement.",
                "raw_line": f"- REQ-LIB-{lib_suffix}-0001: Standalone requirement.",
                "citations": [f"[{lib_id}::spec.md::REQ-LIB-{lib_suffix}-0001]"],
                "mentions_libs": [],
            }
        )

    spec_content = "\n".join(spec_lines).rstrip() + "\n"
    charter_content = f"# Library Charter: {lib_id}\n\n## Intent\nIntent.\n"
    if fs is not None:
        for lib_dir in lib_dirs:
            spec_path = lib_dir / "spec.md"
            charter_path = lib_dir / "charter.md"
            if not spec_path.exists():
                fs.create_file(str(spec_path), contents=spec_content)
            if not charter_path.exists():
                fs.create_file(str(charter_path), contents=charter_content)
    else:
        (absolute_lib_dir / "spec.md").write_text(spec_content, encoding="utf-8")
        (absolute_lib_dir / "charter.md").write_text(charter_content, encoding="utf-8")
    spec_index = {
        "lib_id": lib_id,
        "generated_at": "2024-01-01T00:00:00",
        "spec_path": f"libraries/{lib_id}/spec.md",
        "elements": elements,
    }
    spec_index_payload = json.dumps(spec_index, indent=2)
    if fs is not None:
        for lib_dir in lib_dirs:
            index_path = lib_dir / "spec_index.json"
            if not index_path.exists():
                fs.create_file(str(index_path), contents=spec_index_payload)
    else:
        (absolute_lib_dir / "spec_index.json").write_text(spec_index_payload, encoding="utf-8")

    manager.save_state()
    return [element["element_id"] for element in elements]


def _mock_edge_extractor(monkeypatch, edges_by_lib: dict[str, list[dict[str, object]]]) -> None:
    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, **_kwargs) -> str:
        assert agent_name == "glm-interface-edge-extractor"
        match = re.search(r"## Library ID\s+(LIB-\d{4})", prompt)
        lib_id = match.group(1) if match else "LIB-0001"
        edges = edges_by_lib.get(lib_id, [])
        return json.dumps({"edges": edges})

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.interfaces.run_agent",
        _run_agent,
    )


def test_deterministic_edge_scanning_finds_explicit_mentions(fs, monkeypatch) -> None:
    manager, _manifest = _setup_interface_workspace(fs, monkeypatch)

    edges = _scan_spec_indexes_for_lib_mentions(manager)

    assert ("LIB-0001", "LIB-0002") in edges
    assert ("LIB-0001", "LIB-0003") in edges

    edge_ids = [allocate_edge_id(*edge_key) for edge_key in edges]
    assert all(edge_id.startswith("EDGE-LIB-") for edge_id in edge_ids)

    consumer_elements = edges[("LIB-0001", "LIB-0002")]["consumer_elements"]
    assert "REQ-LIB-0001-0001" in consumer_elements


def test_deterministic_scanning_ignores_self_references(fs, monkeypatch) -> None:
    manager, _manifest = _setup_interface_workspace(fs, monkeypatch, run_id="run_self")
    _create_library_with_cross_refs(manager, "LIB-0100", ["LIB-0100"])

    edges = _scan_spec_indexes_for_lib_mentions(manager)

    assert ("LIB-0100", "LIB-0100") not in edges


def test_llm_edge_extraction_with_mock_agent(fs, monkeypatch) -> None:
    manager, _manifest = _setup_interface_workspace(fs, monkeypatch, run_id="run_llm")

    edges_by_lib = {
        "LIB-0001": [
            {
                "provider_lib": "LIB-0002",
                "consumer_elements": ["REQ-LIB-0001-0001"],
                "kind": "api",
                "summary": "Valid edge.",
                "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
            },
            {
                "provider_lib": "LIB-9999",
                "consumer_elements": ["REQ-LIB-0001-0001"],
                "kind": "api",
                "summary": "Invalid provider.",
                "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
            },
            {
                "provider_lib": "LIB-0003",
                "consumer_elements": ["REQ-LIB-0001-9999"],
                "kind": "events",
                "summary": "Missing consumer elements.",
                "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
            },
        ]
    }

    _mock_edge_extractor(monkeypatch, edges_by_lib)

    edges = _extract_edges_via_llm(manager, manager.allocated_library_ids)

    assert ("LIB-0001", "LIB-0002") in edges
    assert ("LIB-0001", "LIB-9999") not in edges
    assert ("LIB-0001", "LIB-0003") not in edges


def test_edge_deduplication_merges_consumer_elements() -> None:
    deterministic = {
        ("LIB-0001", "LIB-0002"): {
            "consumer_lib": "LIB-0001",
            "provider_lib": "LIB-0002",
            "consumer_elements": ["REQ-LIB-0001-0001"],
            "provider_elements": [],
            "kind": "other",
            "summary": "",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    }
    llm = {
        ("LIB-0001", "LIB-0002"): {
            "consumer_lib": "LIB-0001",
            "provider_lib": "LIB-0002",
            "consumer_elements": ["REQ-LIB-0001-0002"],
            "provider_elements": [],
            "kind": "api",
            "summary": "",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0002]"],
        }
    }

    merged = _merge_and_deduplicate_edges(deterministic, llm)

    assert len(merged) == 1
    edge = merged[0]
    assert set(edge.consumer_elements) == {"REQ-LIB-0001-0001", "REQ-LIB-0001-0002"}
    assert "[LIB-0001::spec.md::REQ-LIB-0001-0001]" in edge.evidence
    assert "[LIB-0001::spec.md::REQ-LIB-0001-0002]" in edge.evidence


def test_edge_kind_resolution_prefers_specific() -> None:
    deterministic = {
        ("LIB-0001", "LIB-0002"): {
            "consumer_lib": "LIB-0001",
            "provider_lib": "LIB-0002",
            "consumer_elements": ["REQ-LIB-0001-0001"],
            "provider_elements": [],
            "kind": "other",
            "summary": "",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    }
    llm = {
        ("LIB-0001", "LIB-0002"): {
            "consumer_lib": "LIB-0001",
            "provider_lib": "LIB-0002",
            "consumer_elements": ["REQ-LIB-0001-0001"],
            "provider_elements": [],
            "kind": "api",
            "summary": "",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    }

    merged = _merge_and_deduplicate_edges(deterministic, llm)
    assert merged[0].kind == "api"

    deterministic[("LIB-0001", "LIB-0002")]["kind"] = "events"
    llm[("LIB-0001", "LIB-0002")]["kind"] = "api"

    merged = _merge_and_deduplicate_edges(deterministic, llm)
    assert merged[0].kind == "events"


def test_edge_extraction_handles_missing_spec_index(fs, monkeypatch) -> None:
    manager, _manifest = _setup_interface_workspace(fs, monkeypatch, run_id="run_missing")
    missing_dir = manager.structure.libraries_dir / "LIB-0099"
    missing_dir.mkdir(parents=True, exist_ok=True)
    (missing_dir / "spec.md").write_text("# Missing\n", encoding="utf-8")
    manager.state.register_library_id("LIB-0099")
    manager.save_state()

    _mock_edge_extractor(monkeypatch, {})

    output = extract_interface_edges(manager.run_id)
    issues = output.get("issues", [])

    assert any(
        issue.get("lib_id") == "LIB-0099" and issue.get("error_type") == "missing_spec_index"
        for issue in issues
    )


def test_parallel_llm_extraction_with_rate_limiting(fs, monkeypatch) -> None:
    base = Path("/work")
    fs.create_dir(base)
    input_dir = base / "specs"
    fs.create_dir(input_dir)
    (input_dir / "input.md").write_text("# Input\n", encoding="utf-8")
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id="run_parallel", input_folder=input_dir)
    issues = manager.initialize(force=True)
    assert issues == []

    lib_ids = [f"LIB-00{idx:02d}" for idx in range(1, 6)]
    for idx, lib_id in enumerate(lib_ids):
        provider = lib_ids[(idx + 1) % len(lib_ids)]
        _create_library_with_cross_refs(manager, lib_id, [provider], fs=fs)

    for lib_id in lib_ids:
        lib_dir = Path.cwd() / manager.structure.libraries_dir / lib_id
        assert (lib_dir / "spec_index.json").exists()
        assert (lib_dir / "charter.md").exists()

    from spec_manager.schemas.spec_indexes import SpecElement, SpecIndex

    def _fake_spec_index(lib_dir: Path) -> SpecIndex:
        lib_id = lib_dir.name
        suffix = lib_id.split("-", 1)[1]
        element_id = f"REQ-LIB-{suffix}-0001"
        element = SpecElement(
            element_id=element_id,
            kind="requirement",
            section="Requirements",
            text="Parallel edge requirement.",
            raw_line=f"- {element_id}: Parallel edge requirement.",
        )
        return SpecIndex(
            lib_id=lib_id,
            generated_at="2024-01-01T00:00:00",
            spec_path=f"libraries/{lib_id}/spec.md",
            elements=[element],
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.interfaces._read_spec_index",
        _fake_spec_index,
    )

    current = 0
    max_concurrent = 0
    lock = threading.Lock()

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, **_kwargs) -> str:
        nonlocal current, max_concurrent
        assert agent_name == "glm-interface-edge-extractor"
        match = re.search(r"## Library ID\s+(LIB-\d{4})", prompt)
        lib_id = match.group(1) if match else lib_ids[0]
        suffix = lib_id.split("-", 1)[1]
        consumer_element = f"REQ-LIB-{suffix}-0001"
        edge = {
            "provider_lib": lib_ids[0] if lib_id != lib_ids[0] else lib_ids[1],
            "consumer_elements": [consumer_element],
            "kind": "api",
            "summary": "Parallel edge.",
            "evidence": [f"[{lib_id}::spec.md::{consumer_element}]"],
        }
        with lock:
            current += 1
            max_concurrent = max(max_concurrent, current)
        time.sleep(0.05)
        with lock:
            current -= 1
        return json.dumps({"edges": [edge]})

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.interfaces.run_agent",
        _run_agent,
    )

    edges = _extract_edges_via_llm(manager, set(lib_ids))

    assert len(edges) == len(lib_ids)
    assert max_concurrent > 1
