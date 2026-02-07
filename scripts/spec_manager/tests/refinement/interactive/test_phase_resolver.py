"""Tests for PhaseResolver detect-resolve-patch loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from spec_manager.refinement.interactive.input_signal import InputSignal, WorkContext
from spec_manager.refinement.interactive.phase_resolver import PhaseResolver
from spec_manager.refinement.interactive.signal_resolver import SignalResolver
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse


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


def test_no_ambiguities_passthrough(tmp_path: Path) -> None:
    """When no ambiguities are detected the text is returned unchanged."""
    resolver = MagicMock(spec=SignalResolver)

    pr = PhaseResolver(signal_resolver=resolver)

    with patch.object(
        pr._detector, "detect_signals", return_value=[]
    ) as mock_detect:
        result = pr.resolve_phase_output(tmp_path, "sectionization", "input text")

    assert result == "input text"
    resolver.resolve.assert_not_called()
    mock_detect.assert_called_once()


def test_detect_resolve_patch_loop(tmp_path: Path) -> None:
    """Signals are detected, resolved, and patched into the text."""
    signal = _make_signal()
    response = SteeringResponse(
        ambiguity_id="SIG-001",
        response_text="Use option A",
        source="steering_script",
    )

    resolver = MagicMock(spec=SignalResolver)
    resolver.resolve.return_value = response

    pr = PhaseResolver(signal_resolver=resolver)

    # First call returns a signal, second call returns empty (loop ends).
    with patch.object(
        pr._detector, "detect_signals", side_effect=[[signal], []]
    ):
        result = pr.resolve_phase_output(tmp_path, "sectionization", "input text")

    assert "## Clarifications" in result
    assert "SIG-001" in result
    assert "Use option A" in result


def test_max_iterations_respected(tmp_path: Path) -> None:
    """The loop stops after max_iterations even if signals remain."""
    signal = _make_signal()
    response = SteeringResponse(
        ambiguity_id="SIG-001",
        response_text="answer",
        source="steering_script",
    )

    resolver = MagicMock(spec=SignalResolver)
    resolver.resolve.return_value = response

    pr = PhaseResolver(signal_resolver=resolver, max_iterations=2)

    with patch.object(
        pr._detector, "detect_signals", return_value=[signal]
    ) as mock_detect:
        pr.resolve_phase_output(tmp_path, "sectionization", "input text")

    assert mock_detect.call_count == 2


def test_no_responses_stops_loop(tmp_path: Path) -> None:
    """When the resolver returns None for all signals the loop stops."""
    signal = _make_signal()

    resolver = MagicMock(spec=SignalResolver)
    resolver.resolve.return_value = None

    pr = PhaseResolver(signal_resolver=resolver)

    with patch.object(
        pr._detector, "detect_signals", return_value=[signal]
    ) as mock_detect:
        result = pr.resolve_phase_output(tmp_path, "sectionization", "input text")

    assert result == "input text"
    mock_detect.assert_called_once()


def test_phase_name_in_work_context(tmp_path: Path) -> None:
    """The work_context passed to detect_signals carries the phase_name."""
    resolver = MagicMock(spec=SignalResolver)

    pr = PhaseResolver(signal_resolver=resolver)

    with patch.object(
        pr._detector, "detect_signals", return_value=[]
    ) as mock_detect:
        pr.resolve_phase_output(tmp_path, "evidence_expansion", "text")

    call_args = mock_detect.call_args
    work_context = call_args[0][2] if len(call_args[0]) > 2 else call_args[1]["work_context"]
    assert work_context.current_phase == "evidence_expansion"


def test_library_id_in_work_context(tmp_path: Path) -> None:
    """The work_context carries the library_id when provided."""
    resolver = MagicMock(spec=SignalResolver)

    pr = PhaseResolver(signal_resolver=resolver)

    with patch.object(
        pr._detector, "detect_signals", return_value=[]
    ) as mock_detect:
        pr.resolve_phase_output(
            tmp_path, "spec_building", "text", library_id="LIB-001"
        )

    call_args = mock_detect.call_args
    work_context = call_args[0][2] if len(call_args[0]) > 2 else call_args[1]["work_context"]
    assert work_context.current_library == "LIB-001"
