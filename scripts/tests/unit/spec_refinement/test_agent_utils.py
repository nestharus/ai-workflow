"""Unit tests for spec_manager.refinement.agent_utils.run_agent.

All tests mock subprocess.run so no real agents or LLMs are invoked.
Filesystem operations use pyfakefs (the ``fs`` fixture).
time.sleep is patched to avoid real delays.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from spec_manager.refinement.agent_utils import PROJECT_ROOT, run_agent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completed_process(
    *,
    returncode: int = 0,
    stdout: str | None = "",
    stderr: str = "",
) -> MagicMock:
    """Build a fake ``subprocess.CompletedProcess``."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


# ---------------------------------------------------------------------------
# 1. Successful agent run
# ---------------------------------------------------------------------------


def test_successful_run_returns_stdout(fs: object) -> None:
    """A successful agent run returns stripped stdout."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    fake_result = _make_completed_process(stdout="  agent output\n")

    with (
        patch("spec_manager.refinement.agent_utils.subprocess.run", return_value=fake_result),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=1000.0),
    ):
        output = run_agent(
            agent_name="test-agent",
            prompt="hello",
            workspace=workspace,
        )

    assert output == "agent output"


def test_successful_run_creates_prompt_file(fs: object) -> None:
    """The prompt text is written to a file inside workspace/agent_prompts/."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    fake_result = _make_completed_process(stdout="ok")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=fake_result,
        ),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=1234.567),
    ):
        run_agent(
            agent_name="my-agent",
            prompt="the prompt body",
            workspace=workspace,
        )

    prompts_dir = workspace / "agent_prompts"
    assert prompts_dir.is_dir()

    # Filename encodes agent_name and millisecond timestamp
    expected_file = prompts_dir / "my-agent_1234567.txt"
    assert expected_file.exists()
    assert expected_file.read_text(encoding="utf-8") == "the prompt body"


# ---------------------------------------------------------------------------
# 2. Non-zero exit code raises RuntimeError after retries
# ---------------------------------------------------------------------------


def test_nonzero_exit_raises_after_retries(fs: object) -> None:
    """When every attempt returns a non-zero exit code, RuntimeError is raised."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    fail = _make_completed_process(returncode=1, stderr="boom")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=fail,
        ),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError, match=rf"Agent failed.*exit=1"):
            run_agent(
                agent_name="fail-agent",
                prompt="go",
                workspace=workspace,
            )


def test_nonzero_exit_error_includes_stderr(fs: object) -> None:
    """The RuntimeError message includes the stderr output."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    fail = _make_completed_process(returncode=2, stderr="  detailed error  ")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=fail,
        ),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError, match=rf"stderr=detailed error"):
            run_agent(
                agent_name="err-agent",
                prompt="go",
                workspace=workspace,
            )


# ---------------------------------------------------------------------------
# 3. Empty output raises RuntimeError after retries
# ---------------------------------------------------------------------------


def test_empty_stdout_raises_after_retries(fs: object) -> None:
    """When stdout is empty on every attempt, RuntimeError is raised."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    empty = _make_completed_process(returncode=0, stdout="")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=empty,
        ),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError, match=rf"empty output"):
            run_agent(
                agent_name="empty-agent",
                prompt="go",
                workspace=workspace,
            )


def test_whitespace_only_stdout_counts_as_empty(fs: object) -> None:
    """Whitespace-only stdout is treated the same as empty."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    ws = _make_completed_process(returncode=0, stdout="   \n  \t  ")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=ws,
        ),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError, match=rf"empty output"):
            run_agent(
                agent_name="ws-agent",
                prompt="go",
                workspace=workspace,
            )


def test_none_stdout_counts_as_empty(fs: object) -> None:
    """When stdout is None, it is treated as empty output."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    none_out = _make_completed_process(returncode=0, stdout=None)
    none_out.stdout = None

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=none_out,
        ),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError, match=rf"empty output"):
            run_agent(
                agent_name="none-agent",
                prompt="go",
                workspace=workspace,
            )


# ---------------------------------------------------------------------------
# 4. Retry behavior
# ---------------------------------------------------------------------------


def test_retries_up_to_max_retries_on_failure(fs: object) -> None:
    """subprocess.run is called exactly max_retries times when every attempt fails."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    fail = _make_completed_process(returncode=1, stderr="err")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=fail,
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep") as mock_sleep,
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError):
            run_agent(
                agent_name="retry-agent",
                prompt="go",
                workspace=workspace,
                max_retries=3,
            )

    assert mock_run.call_count == 3
    # Exponential back-off: 2**0, 2**1, 2**2
    mock_sleep.assert_has_calls([call(1), call(2), call(4)])


def test_retries_with_empty_output(fs: object) -> None:
    """subprocess.run is called max_retries times when output is always empty."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    empty = _make_completed_process(returncode=0, stdout="")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=empty,
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep") as mock_sleep,
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError):
            run_agent(
                agent_name="retry-agent",
                prompt="go",
                workspace=workspace,
                max_retries=2,
            )

    assert mock_run.call_count == 2
    # Exponential back-off: 2**0, 2**1
    mock_sleep.assert_has_calls([call(1), call(2)])


def test_no_sleep_on_immediate_success(fs: object) -> None:
    """time.sleep is never called when the first attempt succeeds."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    ok = _make_completed_process(stdout="good")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=ok,
        ),
        patch("spec_manager.refinement.agent_utils.time.sleep") as mock_sleep,
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        run_agent(
            agent_name="fast-agent",
            prompt="go",
            workspace=workspace,
        )

    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Prompt file creation details
# ---------------------------------------------------------------------------


def test_prompt_dir_created_with_parents(fs: object) -> None:
    """The agent_prompts directory is created even when workspace does not exist yet."""
    workspace = Path("/deep/nested/workspace")
    workspace.mkdir(parents=True)

    ok = _make_completed_process(stdout="done")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=ok,
        ),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=5000.0),
    ):
        run_agent(
            agent_name="nested-agent",
            prompt="deep prompt",
            workspace=workspace,
        )

    assert (workspace / "agent_prompts").is_dir()


def test_prompt_file_encoding_utf8(fs: object) -> None:
    """Prompt files are written with UTF-8 encoding, supporting non-ASCII text."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    ok = _make_completed_process(stdout="done")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=ok,
        ),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=2000.0),
    ):
        run_agent(
            agent_name="utf8-agent",
            prompt="Summarize the Ubersicht-Modul",
            workspace=workspace,
        )

    prompt_file = workspace / "agent_prompts" / "utf8-agent_2000000.txt"
    content = prompt_file.read_text(encoding="utf-8")
    assert "Ubersicht-Modul" in content


# ---------------------------------------------------------------------------
# 6. Command construction
# ---------------------------------------------------------------------------


def test_command_includes_agent_name_and_project_root(fs: object) -> None:
    """The subprocess command includes agent_name, --file, and --project flags."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    ok = _make_completed_process(stdout="result")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=ok,
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=99.0),
    ):
        run_agent(
            agent_name="cmd-agent",
            prompt="check cmd",
            workspace=workspace,
        )

    # Inspect the first positional argument (the command list)
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "uv"
    assert cmd[1] == "run"
    assert cmd[2] == "agents"
    assert cmd[3] == "cmd-agent"
    assert cmd[4] == "--file"
    # cmd[5] is the prompt file path
    assert cmd[5].endswith(".txt")
    assert "cmd-agent" in cmd[5]
    assert cmd[6] == "--project"
    assert cmd[7] == str(PROJECT_ROOT)


def test_command_passes_correct_kwargs(fs: object) -> None:
    """subprocess.run is called with cwd, capture_output, text, and check=False."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    ok = _make_completed_process(stdout="ok")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=ok,
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        run_agent(
            agent_name="kw-agent",
            prompt="go",
            workspace=workspace,
        )

    kwargs = mock_run.call_args[1]
    assert kwargs["cwd"] == PROJECT_ROOT
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False


# ---------------------------------------------------------------------------
# 7. Single retry success (fail first, succeed second)
# ---------------------------------------------------------------------------


def test_succeeds_on_second_attempt_after_failure(fs: object) -> None:
    """If the first attempt fails but the second succeeds, the output is returned."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    fail = _make_completed_process(returncode=1, stderr="transient")
    ok = _make_completed_process(returncode=0, stdout="recovered")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            side_effect=[fail, ok],
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep") as mock_sleep,
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        output = run_agent(
            agent_name="flaky-agent",
            prompt="retry me",
            workspace=workspace,
            max_retries=3,
        )

    assert output == "recovered"
    assert mock_run.call_count == 2
    # Only one sleep call (after the first failure: 2**0 = 1)
    mock_sleep.assert_called_once_with(1)


def test_succeeds_on_second_attempt_after_empty_output(fs: object) -> None:
    """If the first attempt returns empty but the second has output, the output is returned."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    empty = _make_completed_process(returncode=0, stdout="")
    ok = _make_completed_process(returncode=0, stdout="finally got something")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            side_effect=[empty, ok],
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep") as mock_sleep,
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        output = run_agent(
            agent_name="delayed-agent",
            prompt="patience",
            workspace=workspace,
            max_retries=2,
        )

    assert output == "finally got something"
    assert mock_run.call_count == 2
    mock_sleep.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# 8. max_retries=1 means only one attempt
# ---------------------------------------------------------------------------


def test_max_retries_one_no_retry_on_failure(fs: object) -> None:
    """With max_retries=1, only one attempt is made and failure raises immediately."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    fail = _make_completed_process(returncode=1, stderr="once")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=fail,
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep") as mock_sleep,
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError, match=rf"Agent failed"):
            run_agent(
                agent_name="once-agent",
                prompt="try once",
                workspace=workspace,
                max_retries=1,
            )

    assert mock_run.call_count == 1
    # Single attempt with exponential back-off: sleep(2**0) = sleep(1)
    mock_sleep.assert_called_once_with(1)


def test_max_retries_one_success(fs: object) -> None:
    """With max_retries=1, a successful first attempt returns normally."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    ok = _make_completed_process(stdout="one shot")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=ok,
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep") as mock_sleep,
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        output = run_agent(
            agent_name="one-agent",
            prompt="just once",
            workspace=workspace,
            max_retries=1,
        )

    assert output == "one shot"
    assert mock_run.call_count == 1
    mock_sleep.assert_not_called()


def test_max_retries_one_empty_output_raises(fs: object) -> None:
    """With max_retries=1 and empty output, RuntimeError is raised after one attempt."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    empty = _make_completed_process(returncode=0, stdout="  ")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=empty,
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError, match=rf"empty output"):
            run_agent(
                agent_name="empty-once",
                prompt="try",
                workspace=workspace,
                max_retries=1,
            )

    assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# Edge case: default max_retries value
# ---------------------------------------------------------------------------


def test_default_max_retries_is_two(fs: object) -> None:
    """The default max_retries=2 means two attempts before raising."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    fail = _make_completed_process(returncode=1, stderr="nope")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            return_value=fail,
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError):
            run_agent(
                agent_name="default-agent",
                prompt="go",
                workspace=workspace,
                # max_retries not specified -- should default to 2
            )

    assert mock_run.call_count == 2


# ---------------------------------------------------------------------------
# Edge case: mixed failure modes across retries
# ---------------------------------------------------------------------------


def test_nonzero_exit_then_empty_then_success(fs: object) -> None:
    """First attempt fails with exit code, second returns empty, third succeeds."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    fail = _make_completed_process(returncode=1, stderr="err")
    empty = _make_completed_process(returncode=0, stdout="")
    ok = _make_completed_process(returncode=0, stdout="final answer")

    with (
        patch(
            "spec_manager.refinement.agent_utils.subprocess.run",
            side_effect=[fail, empty, ok],
        ) as mock_run,
        patch("spec_manager.refinement.agent_utils.time.sleep") as mock_sleep,
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        output = run_agent(
            agent_name="mixed-agent",
            prompt="keep trying",
            workspace=workspace,
            max_retries=3,
        )

    assert output == "final answer"
    assert mock_run.call_count == 3
    # Back-off: 2**0=1 after fail, 2**1=2 after empty
    mock_sleep.assert_has_calls([call(1), call(2)])


def test_fallback_error_when_last_error_is_none(fs: object) -> None:
    """When max_retries=0 the fallback RuntimeError is raised (defensive branch)."""
    workspace = Path("/workspace")
    workspace.mkdir(parents=True)

    with (
        patch("spec_manager.refinement.agent_utils.subprocess.run"),
        patch("spec_manager.refinement.agent_utils.time.sleep"),
        patch("spec_manager.refinement.agent_utils.time.time", return_value=0.0),
    ):
        with pytest.raises(RuntimeError, match=rf"Agent failed"):
            run_agent(
                agent_name="zero-agent",
                prompt="no tries",
                workspace=workspace,
                max_retries=0,
            )
