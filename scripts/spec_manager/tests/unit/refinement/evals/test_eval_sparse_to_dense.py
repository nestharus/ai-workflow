"""Tests for EvalRunner sparse-to-dense evaluation with resolver integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from spec_manager.core.project_root import resolve_from_root
from spec_manager.refinement.evals.runner import EvalConfig, EvalRunner
from spec_manager.refinement.interactive.signal_resolver import SteeringOnlyResolver


def test_eval_config_resolve_ambiguities_default() -> None:
    """EvalConfig has resolve_ambiguities=False by default."""
    config = EvalConfig()
    assert config.resolve_ambiguities is False


def test_eval_config_to_dict_includes_resolve_ambiguities() -> None:
    """EvalConfig.to_dict() includes resolve_ambiguities when True."""
    config = EvalConfig(resolve_ambiguities=True)
    d = config.to_dict()
    assert "resolve_ambiguities" in d
    assert d["resolve_ambiguities"] is True


def test_eval_runner_accepts_signal_resolver() -> None:
    """EvalRunner stores an injected signal_resolver on _signal_resolver."""
    config = EvalConfig()
    mock_resolver = MagicMock()
    runner = EvalRunner(config, signal_resolver=mock_resolver)
    assert runner._signal_resolver is mock_resolver


def test_eval_runner_no_resolver_default() -> None:
    """EvalRunner._signal_resolver is None when no resolver is provided."""
    config = EvalConfig()
    runner = EvalRunner(config)
    assert runner._signal_resolver is None


def test_steering_only_resolver_used_in_sparse_eval(tmp_path: Path) -> None:
    """When sparse eval runs without an explicit resolver, a SteeringOnlyResolver is created."""
    # Load the real steering fixture to verify the path is valid
    steering_fixture = resolve_from_root(
        "scripts",
        "spec_manager",
        "spec_manager",
        "refinement",
        "evals",
        "inputs",
        "fixtures",
        "chaotic_treasury_steering.json",
    )
    assert steering_fixture.exists(), f"Fixture not found: {steering_fixture}"

    # Create minimal sparse spec YAML in tmp_path (serves as fixtures_dir)
    sparse_yaml = tmp_path / "chaotic_treasury_sparse.yaml"
    sparse_yaml.write_text(
        "spec_id: chaotic_treasury_sparse\n"
        "title: Chaotic Treasury Sparse\n"
        "description: A sparse treasury spec\n"
        "sections:\n"
        "  OVERVIEW: Overview content\n"
        "rules: []\n"
        "ground_truth: {}\n",
        encoding="utf-8",
    )

    # Copy steering fixture into tmp_path so the runner can find it
    steering_dest = tmp_path / "chaotic_treasury_steering.json"
    steering_dest.write_text(steering_fixture.read_text(encoding="utf-8"), encoding="utf-8")

    # Create the dense spec YAML that references sparse + steering
    dense_yaml = tmp_path / "chaotic_treasury.yaml"
    dense_yaml.write_text(
        "spec_id: chaotic_treasury\n"
        "title: Chaotic Treasury\n"
        "description: A treasury settlement system spec\n"
        "sections:\n"
        "  OVERVIEW: Overview content\n"
        "rules: []\n"
        "sparse_spec_path: chaotic_treasury_sparse.yaml\n"
        "steering_script_path: chaotic_treasury_steering.json\n"
        "ground_truth:\n"
        "  spec_building:\n"
        "    expected_requirements:\n"
        "      - '$1,000,000'\n"
        "      - netting threshold\n",
        encoding="utf-8",
    )

    captured_resolver = {}

    def fake_init(self, **kwargs):
        captured_resolver["signal_resolver"] = kwargs.get("signal_resolver")
        # Store attrs so .run() can succeed
        self._workspace = kwargs.get("workspace", tmp_path)
        self._max_iterations = kwargs.get("max_iterations", 1)
        self._resolver = kwargs.get("signal_resolver")
        self._detector = MagicMock()
        self._question_gen = MagicMock()
        self._patcher = MagicMock()

    def fake_run(self, spec_text):
        return spec_text + "\n$1,000,000 netting threshold"

    with (
        patch(
            "spec_manager.refinement.interactive.workflow.InteractiveWorkflow.__init__",
            fake_init,
        ),
        patch(
            "spec_manager.refinement.interactive.workflow.InteractiveWorkflow.run",
            fake_run,
        ),
    ):
        config = EvalConfig(sparse=True, spec_ids=["chaotic_treasury"])
        runner = EvalRunner(config, fixtures_dir=tmp_path)
        result = runner.run_single("chaotic_treasury")

    # The runner should have created a SteeringOnlyResolver because
    # no explicit resolver was provided but a steering script path exists.
    resolver = captured_resolver.get("signal_resolver")
    assert resolver is not None, "InteractiveWorkflow should have received a signal_resolver"
    assert isinstance(resolver, SteeringOnlyResolver)

    # The eval should have succeeded (the faked run includes the expected text)
    assert result.errors == [] or all("failed" not in e.lower() for e in result.errors)


def test_eval_config_sparse_flag() -> None:
    """EvalConfig(sparse=True) serialises the sparse flag in to_dict()."""
    config = EvalConfig(sparse=True)
    d = config.to_dict()
    assert d["sparse"] is True
