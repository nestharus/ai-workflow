"""Tests for InteractiveWorkflow with injected signal resolvers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from spec_manager.refinement.interactive.input_signal import InputSignal, WorkContext
from spec_manager.refinement.interactive.signal_resolver import (
    InteractiveSignalResolver,
    PlannerSignalResolver,
    SignalResolver,
)
from spec_manager.refinement.interactive.spec_patcher import SpecPatcher, SteeringResponse
from spec_manager.refinement.interactive.workflow import InteractiveWorkflow


def _make_signal(signal_id: str = "SIG-001") -> InputSignal:
    ctx = WorkContext(
        current_phase="test",
        current_library=None,
        current_task="test",
        iteration=1,
    )
    return InputSignal(
        signal_id=signal_id,
        signal_type="ambiguity",
        encountered_text="test text",
        encountered_location="spec::test",
        work_context=ctx,
        goal="test",
        question="test?",
    )


def test_injected_resolver_is_used(tmp_path: Path) -> None:
    """When a custom resolver is injected, the workflow delegates to it."""
    signal = _make_signal()

    mock_resolver = MagicMock(spec=SignalResolver)
    mock_resolver.resolve.return_value = SteeringResponse(
        ambiguity_id="SIG-001",
        response_text="resolved",
        source="mock",
    )

    call_count = 0

    def _detect_signals(spec_text, workspace, work_context):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [signal]
        return []

    with patch.object(
        __import__(
            "spec_manager.refinement.interactive.ambiguity_detector",
            fromlist=["AmbiguityDetector"],
        ).AmbiguityDetector,
        "detect_signals",
        side_effect=_detect_signals,
    ):
        workflow = InteractiveWorkflow(
            workspace=tmp_path,
            signal_resolver=mock_resolver,
        )
        result = workflow.run("spec text")

    mock_resolver.resolve.assert_called_once_with(signal)
    assert "Clarifications" in result
    assert "resolved" in result


def test_backward_compat_auto_mode(tmp_path: Path) -> None:
    """When interactive=False and no resolver, workflow uses PlannerSignalResolver."""
    workflow = InteractiveWorkflow(
        workspace=tmp_path,
        interactive=False,
    )
    assert isinstance(workflow._resolver, PlannerSignalResolver)


def test_backward_compat_interactive_mode(tmp_path: Path) -> None:
    """When interactive=True and no resolver, workflow uses InteractiveSignalResolver."""
    workflow = InteractiveWorkflow(
        workspace=tmp_path,
        interactive=True,
    )
    assert isinstance(workflow._resolver, InteractiveSignalResolver)


def test_resolver_overrides_interactive_flag(tmp_path: Path) -> None:
    """An explicit resolver takes precedence over the interactive flag."""
    mock_resolver = MagicMock(spec=SignalResolver)
    workflow = InteractiveWorkflow(
        workspace=tmp_path,
        interactive=True,
        signal_resolver=mock_resolver,
    )
    assert workflow._resolver is mock_resolver
    assert not isinstance(workflow._resolver, InteractiveSignalResolver)


def test_no_signals_returns_original(tmp_path: Path) -> None:
    """When no ambiguities are detected the original text is returned."""
    mock_resolver = MagicMock(spec=SignalResolver)

    with patch.object(
        __import__(
            "spec_manager.refinement.interactive.ambiguity_detector",
            fromlist=["AmbiguityDetector"],
        ).AmbiguityDetector,
        "detect_signals",
        return_value=[],
    ):
        workflow = InteractiveWorkflow(
            workspace=tmp_path,
            signal_resolver=mock_resolver,
        )
        result = workflow.run("original spec")

    assert result == "original spec"
    mock_resolver.resolve.assert_not_called()


def test_resolver_returns_none_stops(tmp_path: Path) -> None:
    """When the resolver returns None unresolved ambiguities raise an error."""
    signal = _make_signal()

    mock_resolver = MagicMock(spec=SignalResolver)
    mock_resolver.resolve.return_value = None

    with patch.object(
        __import__(
            "spec_manager.refinement.interactive.ambiguity_detector",
            fromlist=["AmbiguityDetector"],
        ).AmbiguityDetector,
        "detect_signals",
        return_value=[signal],
    ):
        workflow = InteractiveWorkflow(
            workspace=tmp_path,
            signal_resolver=mock_resolver,
        )
        with (
            patch.object(SpecPatcher, "apply") as mock_apply,
            pytest.raises(
                RuntimeError,
                match="Interactive refinement stopped with unresolved ambiguities: SIG-001",
            ),
        ):
            workflow.run("original spec")

    mock_apply.assert_not_called()
