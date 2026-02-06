from __future__ import annotations

import json
from pathlib import Path

import pytest
from spec_manager.refinement.formats import _extract_json_payload
from spec_manager.refinement.workflows.interfaces import build_interface_graph
from spec_manager.refinement.workspace import Phase, PhaseStatus
from spec_manager.schemas.edge_list import (
    EdgeListSchema,
    EdgeSchema,
    read_edge_list_json,
    read_interface_index_json,
    validate_edge_list_completeness,
)
from spec_manager.schemas.interface_contract import (
    InterfaceContractSchema,
    read_interface_contract_json,
)

pytestmark = [pytest.mark.interfaces, pytest.mark.workflow_smoke]


def _complete_prerequisites(manager) -> None:
    manager.start_phase(Phase.LIBRARY_STRUCTURE_REVIEW)
    manager.complete_phase(Phase.LIBRARY_STRUCTURE_REVIEW, outputs={"libraries": 3})
    manager.start_phase(Phase.ARCHITECTURE_MAPPING)
    manager.complete_phase(Phase.ARCHITECTURE_MAPPING, outputs={"mapped": 3})


def _create_architecture_mapping(manager) -> None:
    arch_dir = manager.structure.architecture_dir
    arch_dir.mkdir(parents=True, exist_ok=True)

    selected = """# Selected Architecture

## Components
- API Layer: Handles API requests
- Event Layer: Handles event emissions
"""
    mapping = """# Architecture Mapping

## Architecture
arch_001

## Component Mappings

### Component: API Layer
- LIB-0001: Consumer responsibilities
- LIB-0002: Provider APIs

### Component: Event Layer
- LIB-0003: Provider events
"""
    (arch_dir / "selected.md").write_text(selected, encoding="utf-8")
    (arch_dir / "mapping.md").write_text(mapping, encoding="utf-8")


def _assert_contract_files_valid(run_dir: Path, edge_id: str) -> InterfaceContractSchema:
    parts = edge_id.split("-")
    consumer_lib = f"{parts[1]}-{parts[2]}"
    contracts_dir = run_dir / "libraries" / consumer_lib / "interfaces"

    md_path = contracts_dir / f"{edge_id}.md"
    json_path = contracts_dir / f"{edge_id}.json"

    assert md_path.exists()
    assert json_path.exists()

    content = md_path.read_text(encoding="utf-8")
    for section in [
        "## Purpose",
        "## Provided Interfaces",
        "## Consumed By",
        "## Data Contract",
        "## Operational Concerns",
        "## Open Questions",
        "## Evidence",
    ]:
        assert section in content

    contract = read_interface_contract_json(json_path)
    assert contract.edge_id == edge_id
    return contract


def test_build_interfaces_creates_edge_list(interface_workspace, mock_interface_agents) -> None:
    manager, manifest = interface_workspace(run_id="run_edges")
    _complete_prerequisites(manager)
    mock_interface_agents(manifest)

    build_interface_graph(manager.run_id)

    edge_list_path = manager.structure.indexes_dir / "edge_list.json"
    assert edge_list_path.exists()

    edge_list = read_edge_list_json(edge_list_path)
    assert len(edge_list.edges) == len(manifest["expected_edges"])
    assert len({edge.edge_id for edge in edge_list.edges}) == len(edge_list.edges)


def test_build_interfaces_creates_interface_index(
    interface_workspace, mock_interface_agents
) -> None:
    manager, _manifest = interface_workspace(run_id="run_index")
    _complete_prerequisites(manager)
    mock_interface_agents(_manifest)

    build_interface_graph(manager.run_id)

    interface_index_path = manager.structure.indexes_dir / "interface_index.json"
    assert interface_index_path.exists()

    interface_index = read_interface_index_json(interface_index_path)
    assert "LIB-0001" in interface_index.edges_by_consumer
    assert "LIB-0002" in interface_index.edges_by_provider
    assert interface_index.contract_files


def test_build_interfaces_creates_contract_files(
    interface_workspace, mock_interface_agents
) -> None:
    manager, manifest = interface_workspace(run_id="run_contracts")
    _complete_prerequisites(manager)
    mock_interface_agents(manifest)

    build_interface_graph(manager.run_id)

    edge_list = read_edge_list_json(manager.structure.indexes_dir / "edge_list.json")
    for edge in edge_list.edges:
        _assert_contract_files_valid(manager.run_root, edge.edge_id)


def test_build_interfaces_validates_contracts(interface_workspace, mock_interface_agents) -> None:
    manager, manifest = interface_workspace(run_id="run_validate")
    _complete_prerequisites(manager)
    controller = mock_interface_agents(manifest, contract_violation_mode="invalid_element_ids")

    result = build_interface_graph(manager.run_id)

    assert any(
        call["agent_name"] == "chatgpt-interface-contract-repairer" for call in controller.call_log
    )
    assert result["validation_stats"]["contracts_validated"] > 0


def test_build_interfaces_repair_loop_succeeds(interface_workspace, mock_interface_agents) -> None:
    manager, manifest = interface_workspace(run_id="run_repair_success")
    _complete_prerequisites(manager)

    failing_edge = manifest["expected_edges"][0]["edge_id"]
    controller = mock_interface_agents(
        manifest,
        contract_overrides={failing_edge: "invalid_element_ids"},
    )

    result = build_interface_graph(manager.run_id)

    repair_calls = [
        call
        for call in controller.call_log
        if call["agent_name"] == "chatgpt-interface-contract-repairer"
    ]
    assert len(repair_calls) == 1
    assert result["validation_stats"]["repairs_attempted"] == 1
    assert result["validation_stats"]["repairs_succeeded"] == 1


def test_build_interfaces_repair_loop_fails_after_max_retries(
    interface_workspace, mock_interface_agents
) -> None:
    manager, manifest = interface_workspace(run_id="run_repair_fail")
    _complete_prerequisites(manager)

    controller = mock_interface_agents(
        manifest,
        contract_violation_mode="invalid_element_ids",
        overrides={"chatgpt-interface-contract-repairer": 1.0},
    )

    result = build_interface_graph(manager.run_id)

    interface_index = read_interface_index_json(
        manager.structure.indexes_dir / "interface_index.json"
    )
    assert interface_index.contract_files == {}
    assert result["validation_errors"]
    assert any(
        call["agent_name"] == "chatgpt-interface-contract-repairer" for call in controller.call_log
    )


def test_build_interfaces_handles_no_edges(interface_workspace, mock_interface_agents) -> None:
    manager, manifest = interface_workspace(run_id="run_no_edges")
    _complete_prerequisites(manager)

    spec_index_path = manager.structure.libraries_dir / "LIB-0001" / "spec_index.json"
    payload = json.loads(spec_index_path.read_text(encoding="utf-8"))
    for element in payload.get("elements", []):
        element["text"] = element["text"].replace("LIB-0002", "provider")
        element["text"] = element["text"].replace("LIB-0003", "provider")
        element["mentions_libs"] = []
    spec_index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    empty_edges = {lib_id: [] for lib_id in manifest["library_ids"]}
    mock_interface_agents(manifest, edges_by_lib=empty_edges)

    build_interface_graph(manager.run_id)

    edge_list = read_edge_list_json(manager.structure.indexes_dir / "edge_list.json")
    interface_index = read_interface_index_json(
        manager.structure.indexes_dir / "interface_index.json"
    )

    assert edge_list.edges == []
    assert interface_index.edges_by_consumer == {}
    assert interface_index.edges_by_provider == {}
    assert interface_index.contract_files == {}


def test_build_interfaces_phase_tracking(interface_workspace, mock_interface_agents) -> None:
    from pathlib import Path

    from spec_manager.refinement.workspace import WorkspaceManager

    manager, manifest = interface_workspace(run_id="run_phase")
    _complete_prerequisites(manager)
    mock_interface_agents(manifest)

    build_interface_graph(manager.run_id)

    # Reload state from disk since build_interface_graph uses its own manager instance
    refreshed = WorkspaceManager(run_id=manager.run_id, input_folder=Path("."))
    phase_result = refreshed.state.phases[Phase.INTERFACES.value]
    assert phase_result.status == PhaseStatus.COMPLETED
    assert phase_result.started_at is not None
    assert phase_result.completed_at is not None
    assert phase_result.outputs["edge_list_path"]
    assert phase_result.outputs["interface_index_path"]
    assert "contract_count" in phase_result.outputs
    assert "validation_stats" in phase_result.outputs


def test_build_interfaces_prerequisite_validation(interface_workspace) -> None:
    manager, _manifest = interface_workspace(run_id="run_prereq")

    with pytest.raises(RuntimeError, match="Library structure review"):
        build_interface_graph(manager.run_id)


def test_build_interfaces_uses_architecture_mapping(
    interface_workspace, mock_interface_agents
) -> None:
    manager, manifest = interface_workspace(run_id="run_arch")
    _create_architecture_mapping(manager)
    _complete_prerequisites(manager)
    controller = mock_interface_agents(manifest)

    build_interface_graph(manager.run_id)

    prompts = [
        call["prompt"]
        for call in controller.call_log
        if call["agent_name"] == "opus-interface-contract-writer"
    ]
    assert prompts

    bundle = json.loads(_extract_json_payload(prompts[0]))
    architecture = bundle.get("architecture")
    assert architecture and architecture.get("provider_component")

    edge_list = read_edge_list_json(manager.structure.indexes_dir / "edge_list.json")
    contract = _assert_contract_files_valid(manager.run_root, edge_list.edges[0].edge_id)
    assert "API Layer" in contract.provided[0].details


def test_build_interfaces_includes_decisions_in_contracts(
    interface_workspace, mock_interface_agents
) -> None:
    manager, manifest = interface_workspace(run_id="run_decisions")
    _complete_prerequisites(manager)
    mock_interface_agents(manifest)

    build_interface_graph(manager.run_id)

    edge_list = read_edge_list_json(manager.structure.indexes_dir / "edge_list.json")
    contract = _assert_contract_files_valid(manager.run_root, edge_list.edges[0].edge_id)
    assert contract.open_questions
    assert all(question.startswith("ANL-") for question in contract.open_questions)


def test_edge_list_completeness_validation() -> None:
    edge = EdgeSchema.model_validate(
        {
            "edge_id": "EDGE-LIB-0001-LIB-0002",
            "consumer_lib": "LIB-0001",
            "provider_lib": "LIB-0002",
            "kind": "api",
            "consumer_elements": ["DTL-LIB-0001-9999"],
            "provider_elements": ["DTL-LIB-0002-0001"],
            "summary": "",
            "evidence": ["[LIB-0001::spec.md::DTL-LIB-0001-9999]"],
        }
    )
    edge_list_model = EdgeListSchema(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        edges=[edge],
    )
    spec_indexes = {
        "LIB-0001": {"elements": [{"element_id": "DTL-LIB-0001-0001"}]},
        "LIB-0002": {"elements": [{"element_id": "DTL-LIB-0002-0001"}]},
    }

    errors = validate_edge_list_completeness(edge_list_model, set(spec_indexes), spec_indexes)
    assert errors
    assert errors[0]["edge_id"] == "EDGE-LIB-0001-LIB-0002"
    assert errors[0]["context"]["consumer_lib"] == "LIB-0001"
    assert errors[0]["context"]["provider_lib"] == "LIB-0002"


def test_interface_index_omits_failed_contracts(interface_workspace, mock_interface_agents) -> None:
    manager, manifest = interface_workspace(run_id="run_index_omit")
    _complete_prerequisites(manager)

    failing_edge = manifest["expected_edges"][0]["edge_id"]
    controller = mock_interface_agents(
        manifest,
        contract_overrides={failing_edge: "invalid_element_ids"},
        overrides={"chatgpt-interface-contract-repairer": 1.0},
    )

    build_interface_graph(manager.run_id)

    interface_index = read_interface_index_json(
        manager.structure.indexes_dir / "interface_index.json"
    )

    assert failing_edge in interface_index.edges_by_consumer["LIB-0001"]
    assert failing_edge in interface_index.edges_by_provider["LIB-0002"]
    assert failing_edge not in interface_index.contract_files
    assert interface_index.contract_files
    assert any(
        call["agent_name"] == "chatgpt-interface-contract-repairer" for call in controller.call_log
    )


def test_deterministic_and_llm_edges_merged(interface_workspace, mock_interface_agents) -> None:
    manager, manifest = interface_workspace(run_id="run_merge")
    _complete_prerequisites(manager)

    edges_by_lib = {
        "LIB-0001": [
            {
                "provider_lib": "LIB-0002",
                "consumer_elements": ["DTL-LIB-0001-0001", "DTL-LIB-0001-0002"],
                "kind": "api",
                "summary": "LLM edge.",
                "evidence": ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
            }
        ]
    }
    mock_interface_agents(manifest, edges_by_lib=edges_by_lib)

    build_interface_graph(manager.run_id)

    edge_list = read_edge_list_json(manager.structure.indexes_dir / "edge_list.json")
    merged_edge = next(edge for edge in edge_list.edges if edge.edge_id == "EDGE-LIB-0001-LIB-0002")
    assert set(merged_edge.consumer_elements) == {"DTL-LIB-0001-0001", "DTL-LIB-0001-0002"}
