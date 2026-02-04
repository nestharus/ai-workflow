from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.refinement.workspace import WorkspaceManager

from tests.spec_refinement.fixtures.agent_mocks import MockAgentController
from tests.spec_refinement.fixtures.test_corpus import create_interface_test_libraries


@pytest.fixture
def interface_workspace(fs, monkeypatch):
    def _factory(*, run_id: str = "run_interfaces"):
        base = Path("/work")
        fs.create_dir(base)
        input_dir = base / "specs"
        fs.create_dir(input_dir)
        (input_dir / "input.md").write_text(
            "# Input\n\n## Intro\nSeed content.\n", encoding="utf-8"
        )

        monkeypatch.chdir(base)
        manager = WorkspaceManager(run_id=run_id, input_folder=input_dir)
        issues = manager.initialize(force=True)
        assert issues == []

        manifest = create_interface_test_libraries(fs, run_id=run_id)
        for lib_id in manifest["library_ids"]:
            manager.state.register_library_id(lib_id)
        manager.save_state()

        return manager, manifest

    return _factory


@pytest.fixture
def mock_interface_agents(monkeypatch):
    def _apply(
        manifest: dict[str, dict[str, object]],
        *,
        violation_rate: float = 0.0,
        edge_violation_mode: str | None = None,
        contract_violation_mode: str | None = None,
        overrides: dict[str, float] | None = None,
        edges_by_lib: dict[str, list[dict[str, object]]] | None = None,
        contract_overrides: dict[str, str] | None = None,
    ) -> MockAgentController:
        controller = MockAgentController(manifest=manifest, violation_rate=violation_rate)
        controller.interface_edge_violation_mode = edge_violation_mode
        controller.interface_contract_violation_mode = contract_violation_mode
        controller.interface_edges_by_lib = edges_by_lib
        if contract_overrides:
            controller.interface_contract_overrides.update(contract_overrides)
        if overrides:
            controller.violation_overrides.update(overrides)

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.interfaces.run_agent",
            controller.dispatch,
        )
        monkeypatch.setattr(
            "spec_manager.refinement.repair.run_agent",
            controller.dispatch,
        )
        return controller

    return _apply
