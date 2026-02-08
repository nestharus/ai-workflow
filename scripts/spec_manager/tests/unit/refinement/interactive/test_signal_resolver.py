"""Tests for the signal resolver system."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from spec_manager.core.project_root import resolve_from_root
from spec_manager.refinement.interactive.input_signal import InputSignal, WorkContext
from spec_manager.refinement.interactive.signal_resolver import (
    AutoSignalResolver,
    FileSignalResolver,
    InteractiveSignalResolver,
    SignalResolver,
    SteeringOnlyResolver,
    create_resolver,
)
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse
from spec_manager.refinement.interactive.steering.steering_script import SteeringScript

STEERING_FIXTURE = resolve_from_root(
    "scripts",
    "spec_manager",
    "spec_manager",
    "refinement",
    "evals",
    "inputs",
    "fixtures",
    "chaotic_treasury_steering.json",
)


def _make_signal(
    signal_id: str = "SIG-001",
    question: str = "test?",
    encountered_text: str = "test text",
) -> InputSignal:
    ctx = WorkContext(
        current_phase="test",
        current_library=None,
        current_task="test",
        iteration=1,
    )
    return InputSignal(
        signal_id=signal_id,
        signal_type="ambiguity",
        encountered_text=encountered_text,
        encountered_location="spec::test",
        work_context=ctx,
        goal="test",
        question=question,
    )


def test_auto_resolver_delegates_to_auto_responder() -> None:
    """AutoSignalResolver delegates resolve() to AutoResponder.respond()."""
    signal = _make_signal()
    expected = SteeringResponse(
        ambiguity_id="SIG-001",
        response_text="auto answer",
        source="steering_script",
    )

    with patch(
        "spec_manager.refinement.interactive.steering.auto_responder.AutoResponder.respond",
        return_value=expected,
    ) as mock_respond:
        resolver = AutoSignalResolver()
        result = resolver.resolve(signal)

    mock_respond.assert_called_once_with(signal)
    assert result is expected


def test_interactive_resolver_auto_first() -> None:
    """InteractiveSignalResolver uses auto-responder result when available."""
    signal = _make_signal()
    expected = SteeringResponse(
        ambiguity_id="SIG-001",
        response_text="auto answer",
        source="steering_script",
    )

    with (
        patch(
            "spec_manager.refinement.interactive.steering.auto_responder.AutoResponder.respond",
            return_value=expected,
        ),
        patch(
            "spec_manager.refinement.interactive.steering.interactive_io.InteractiveIO.ask_signal",
        ) as mock_ask,
    ):
        resolver = InteractiveSignalResolver()
        result = resolver.resolve(signal)

    mock_ask.assert_not_called()
    assert result is expected


def test_interactive_resolver_fallback_to_stdin() -> None:
    """InteractiveSignalResolver falls back to InteractiveIO when auto returns None."""
    signal = _make_signal()
    stdin_response = SteeringResponse(
        ambiguity_id="SIG-001",
        response_text="human answer",
        source="interactive",
    )

    with (
        patch(
            "spec_manager.refinement.interactive.steering.auto_responder.AutoResponder.respond",
            return_value=None,
        ),
        patch(
            "spec_manager.refinement.interactive.steering.interactive_io.InteractiveIO.ask_signal",
            return_value=stdin_response,
        ) as mock_ask,
    ):
        resolver = InteractiveSignalResolver()
        result = resolver.resolve(signal)

    mock_ask.assert_called_once()
    assert result is stdin_response


def test_steering_only_resolver_matches() -> None:
    """SteeringOnlyResolver returns a response for a matching signal."""
    script = SteeringScript.from_file(STEERING_FIXTURE)
    resolver = SteeringOnlyResolver(script)

    signal = _make_signal(encountered_text="netting threshold")
    result = resolver.resolve(signal)

    assert result is not None
    assert "$1,000,000" in result.response_text


def test_steering_only_resolver_no_match() -> None:
    """SteeringOnlyResolver returns None for an unrelated signal."""
    script = SteeringScript.from_file(STEERING_FIXTURE)
    resolver = SteeringOnlyResolver(script)

    signal = _make_signal(
        encountered_text="xyzzy foobarbaz qqqqq",
        question="completely unrelated gibberish?",
    )
    result = resolver.resolve(signal)

    assert result is None


def test_steering_only_resolver_type_check() -> None:
    """SteeringOnlyResolver raises TypeError for non-SteeringScript input."""
    with pytest.raises(TypeError, match="Expected SteeringScript"):
        SteeringOnlyResolver(steering_script="not a steering script")


def test_file_resolver_posts_and_reads(tmp_path: Path) -> None:
    """FileSignalResolver posts signals and reads matching responses."""
    signal = _make_signal()
    expected = SteeringResponse(
        ambiguity_id="SIG-001",
        response_text="file answer",
        source="human",
    )

    with (
        patch(
            "spec_manager.refinement.interactive.signal_exchange.SignalExchange.wait_for_responses",
            return_value=[expected],
        ) as mock_wait,
        patch(
            "spec_manager.refinement.interactive.signal_exchange.SignalExchange.post_signals",
        ) as mock_post,
    ):
        resolver = FileSignalResolver(signals_dir=tmp_path)
        result = resolver.resolve(signal)

    mock_post.assert_called_once_with([signal])
    mock_wait.assert_called_once()
    assert result is expected


def test_create_resolver_auto() -> None:
    """create_resolver('auto') returns an AutoSignalResolver."""
    resolver = create_resolver("auto")
    assert isinstance(resolver, AutoSignalResolver)


def test_create_resolver_interactive() -> None:
    """create_resolver('interactive') returns an InteractiveSignalResolver."""
    resolver = create_resolver("interactive")
    assert isinstance(resolver, InteractiveSignalResolver)


def test_create_resolver_steering_only() -> None:
    """create_resolver('steering-only') with steering_path returns SteeringOnlyResolver."""
    resolver = create_resolver("steering-only", steering_path=STEERING_FIXTURE)
    assert isinstance(resolver, SteeringOnlyResolver)


def test_create_resolver_file(tmp_path: Path) -> None:
    """create_resolver('file') with workspace returns FileSignalResolver."""
    resolver = create_resolver("file", workspace=tmp_path)
    assert isinstance(resolver, FileSignalResolver)


def test_create_resolver_unknown_mode() -> None:
    """create_resolver raises ValueError for an unknown mode."""
    with pytest.raises(ValueError, match="Unknown resolver mode"):
        create_resolver("unknown")


def test_create_resolver_steering_only_no_path() -> None:
    """create_resolver('steering-only') without steering_path raises ValueError."""
    with pytest.raises(ValueError, match="steering_path is required"):
        create_resolver("steering-only")


def test_create_resolver_file_no_workspace() -> None:
    """create_resolver('file') without workspace raises ValueError."""
    with pytest.raises(ValueError, match="workspace is required"):
        create_resolver("file")


def test_signal_resolver_protocol_check() -> None:
    """All four resolver implementations satisfy the SignalResolver protocol."""
    script = SteeringScript.from_file(STEERING_FIXTURE)

    auto = AutoSignalResolver()
    interactive = InteractiveSignalResolver()
    steering = SteeringOnlyResolver(script)
    file_resolver = FileSignalResolver(signals_dir=Path("/tmp/test-signals"))

    assert isinstance(auto, SignalResolver)
    assert isinstance(interactive, SignalResolver)
    assert isinstance(steering, SignalResolver)
    assert isinstance(file_resolver, SignalResolver)
