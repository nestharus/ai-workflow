from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from spec_manager.refinement.formats import (
    parse_architecture_mapping,
    parse_architecture_proposal,
    parse_architecture_selection,
)
from spec_manager.refinement.workspace import Phase, WorkspaceManager

from scripts.spec_refinement.workflows.architecture import (
    _validate_architecture_citations,
    map_libraries_to_architecture,
    propose_architectures,
    select_architecture,
)


def _setup_workspace(fs, monkeypatch, run_id: str = "run_001") -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    input_dir = base / "input"
    fs.create_dir(input_dir)
    (input_dir / "spec.md").write_text("# Spec\n\n## Intro\nDetails.")
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id=run_id, input_folder=input_dir)
    issues = manager.initialize(force=True)
    assert issues == []
    return manager


def _create_library(manager: WorkspaceManager, lib_id: str) -> None:
    lib_dir = manager.structure.libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "charter.md").write_text(
        "# Library Charter\n\n## Intent\nTest intent.\n\n## Responsibilities\n- Do work.\n",
        encoding="utf-8",
    )
    (lib_dir / "spec.md").write_text(
        "# Library Spec\n\n## Constraints\n- Must be fast.\n",
        encoding="utf-8",
    )


def _patch_agent_runner(monkeypatch, output: str) -> None:
    from scripts.spec_refinement.workflows import architecture as arch_module

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return output

    monkeypatch.setattr(arch_module, "run_agent", _run_agent)


def test_propose_architectures_requires_completed_sublibrary_phase(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    _create_library(manager, "lib_001")

    with pytest.raises(RuntimeError):
        propose_architectures("run_001")


def test_propose_architectures_generates_candidates(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    _create_library(manager, "lib_001")
    manager.complete_phase(Phase.SUBLIBRARY_DETECTION)

    output = textwrap.dedent(
        """
        [
          {
            "arch_id": "arch_001",
            "pattern": "layered",
            "description": "Layered architecture",
            "components": [{"name": "API", "responsibilities": ["Serve requests"]}],
            "communication": "sync",
            "deployment": "single",
            "citations": ["[lib_001::spec.md::CONSTRAINTS]"],
            "tradeoffs": {"advantages": ["simple"], "disadvantages": ["coupled"]}
          }
        ]
        """
    )
    _patch_agent_runner(monkeypatch, output)

    result = propose_architectures("run_001")
    assert result["candidates_created"] == 1

    candidate_path = manager.structure.architecture_dir / "candidates" / "arch_001.md"
    assert candidate_path.exists()
    assert "Layered architecture" in candidate_path.read_text(encoding="utf-8")


def test_select_architecture_validates_citations(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    _create_library(manager, "lib_001")
    manager.complete_phase(Phase.ARCHITECTURE_PROPOSAL)

    candidates_dir = manager.structure.architecture_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    (candidates_dir / "arch_001.md").write_text(
        "# Architecture Candidate: arch_001\n\n## Description\nTest candidate.\n",
        encoding="utf-8",
    )

    output = textwrap.dedent(
        """
        {
          "selected_arch_id": "arch_001",
          "rationale": "Uses constraint [lib_001::spec.md::MISSING]",
          "rejected_architectures": [],
          "implementation_risks": ["risk"],
          "evolution_notes": ["note"]
        }
        """
    )
    _patch_agent_runner(monkeypatch, output)

    result = select_architecture("run_001")
    assert result["selected_arch_id"] == "arch_001"

    refreshed = WorkspaceManager(run_id="run_001", input_folder=Path("."))
    issues = refreshed.state.phases[Phase.ARCHITECTURE_SELECTION.value].issues
    assert any(issue["type"] == "unknown_section_reference" for issue in issues)


def test_map_libraries_validates_coverage(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    _create_library(manager, "lib_001")
    _create_library(manager, "lib_002")
    manager.complete_phase(Phase.ARCHITECTURE_SELECTION)

    selected_path = manager.structure.architecture_dir / "selected.md"
    selected_path.write_text("# Selected Architecture: arch_001", encoding="utf-8")

    output = textwrap.dedent(
        """
        # Architecture Mapping

        ## Architecture: arch_001

        Example architecture.

        ## Component Mappings

        ### Component: API

        **Responsibilities**: Serve requests

        **Libraries**:
        - lib_001: API layer [lib_001::spec.md::CONSTRAINTS]

        ## Cross-Component Dependencies

        - API -> Data: storage [lib_001::spec.md::CONSTRAINTS]

        ## Unmapped Libraries

        - lib_002: not mapped
        """
    )
    _patch_agent_runner(monkeypatch, output)

    result = map_libraries_to_architecture("run_001")
    assert "lib_002" in result["unmapped_libraries"]


def test_architecture_citation_validation(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    _create_library(manager, "lib_001")

    content = "Decision [lib_001::spec.md::CONSTRAINTS] and [lib_999::spec.md::X]"
    issues = _validate_architecture_citations(content, manager)
    assert any(issue["type"] == "unknown_library" for issue in issues)

    missing = _validate_architecture_citations("No citations here.", manager)
    assert any(issue["type"] == "missing_citations" for issue in missing)


def test_architecture_parsers() -> None:
    proposal_json = textwrap.dedent(
        """
        [
          {
            "arch_id": "arch_001",
            "pattern": "layered",
            "description": "Layered architecture",
            "components": [{"name": "API", "responsibilities": ["Serve"]}],
            "communication": "sync",
            "deployment": "single",
            "citations": ["[lib_001::spec.md::CONSTRAINTS]"],
            "tradeoffs": {"advantages": ["simple"], "disadvantages": ["coupled"]}
          }
        ]
        """
    )
    candidates = parse_architecture_proposal(proposal_json)
    assert candidates[0].arch_id == "arch_001"

    selection_json = textwrap.dedent(
        """
        {
          "selected_arch_id": "arch_001",
          "rationale": "Reason [lib_001::spec.md::CONSTRAINTS]",
          "rejected_architectures": [],
          "implementation_risks": [],
          "evolution_notes": []
        }
        """
    )
    selection = parse_architecture_selection(selection_json)
    assert selection["selected_arch_id"] == "arch_001"

    mapping_md = textwrap.dedent(
        """
        # Architecture Mapping

        ## Architecture: arch_001

        Desc.

        ## Component Mappings

        ### Component: API

        **Responsibilities**: Serve

        **Libraries**:
        - lib_001: API layer [lib_001::spec.md::CONSTRAINTS]

        ## Cross-Component Dependencies

        - API -> Data: storage [lib_001::spec.md::CONSTRAINTS]

        ## Unmapped Libraries

        - None
        """
    )
    mapping = parse_architecture_mapping(mapping_md)
    assert mapping["component_mappings"]["API"] == ["lib_001"]
    assert mapping["dependencies"]
    assert mapping["unmapped_libraries"] == []
