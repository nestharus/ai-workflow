import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.knowledge.ministral_hunter import (
    EntityResult,
    FactResult,
    HunterError,
    HunterOutput,
    SpanResult,
    TargetEntity,
    _parse_json_response,
    _validate_hunter_output,
    invoke_hunter,
    invoke_hunter_mock,
)


class TestInvokeHunterKnowledgePath:
    def test_invoke_hunter_uses_default_knowledge_path_when_none(self, tmp_path: Path) -> None:
        """Should use REPO_ROOT/.knowledge when knowledge_path is None."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = (
            "{\n"
            '    "mode": "entities",\n'
            '    "entities": [],\n'
            '    "target_entity": null,\n'
            '    "facts": [],\n'
            '    "spans": [],\n'
            '    "done": true,\n'
            '    "reason": null\n'
            "}"
        )

        with (
            patch("subprocess.run", return_value=mock_result),
            patch("scripts.knowledge.ministral_hunter.REPO_ROOT", tmp_path),
        ):
            # Pass knowledge_path=None to trigger the default path logic
            result = invoke_hunter(
                state_text="Test",
                mode="entities",
                knowledge_path=None,  # This should trigger line 408
            )

        assert result["mode"] == "entities"
        # Verify the log directory was created under the default path
        log_dir = tmp_path / ".knowledge" / "facts" / "hunter_logs"
        assert log_dir.exists()

    def test_invoke_hunter_resolves_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should resolve relative knowledge_path against REPO_ROOT."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = (
            "{\n"
            '    "mode": "entities",\n'
            '    "entities": [],\n'
            '    "target_entity": null,\n'
            '    "facts": [],\n'
            '    "spans": [],\n'
            '    "done": true,\n'
            '    "reason": null\n'
            "}"
        )

        with (
            patch("subprocess.run", return_value=mock_result),
            patch("scripts.knowledge.ministral_hunter.REPO_ROOT", tmp_path),
        ):
            # Pass a relative path to trigger line 409-410
            result = invoke_hunter(
                state_text="Test",
                mode="entities",
                knowledge_path=Path("custom_knowledge"),  # Relative path
            )

        assert result["mode"] == "entities"
        # Verify the log directory was created under the resolved path
        log_dir = tmp_path / "custom_knowledge" / "facts" / "hunter_logs"
        assert log_dir.exists()


class TestInvokeHunterEntitiesMode:
    def test_invoke_hunter_entities_mode_returns_output(self, tmp_path: Path) -> None:
        """Should return HunterOutput with entities via subprocess."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = (
            "{\n"
            '    "mode": "entities",\n'
            '    "entities": [{"mention": "create_app", "type_hint": "FUNCTION", '
            '"evidence_span_id": "span_1"}],\n'
            '    "target_entity": null,\n'
            '    "facts": [],\n'
            '    "spans": [{"span_id": "span_1", "original_text": '
            '"The create_app function."}],\n'
            '    "done": false,\n'
            '    "reason": null\n'
            "}"
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = invoke_hunter(
                state_text="The create_app function initializes the app.",
                mode="entities",
                knowledge_path=tmp_path,
            )

            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0][0] == "uv"
            assert "--agent" in call_args[0][0]
            assert "ministral-recognizer" in call_args[0][0]

        assert result["mode"] == "entities"
        assert len(result["entities"]) == 1
        assert result["entities"][0]["mention"] == "create_app"
        assert result["done"] is False


class TestInvokeHunterFactsMode:
    def test_invoke_hunter_facts_mode_returns_facts(self, tmp_path: Path) -> None:
        """Should return HunterOutput with facts for target entity via subprocess."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = (
            "{\n"
            '    "mode": "facts",\n'
            '    "entities": [],\n'
            '    "target_entity": {"mention": "create_app", '
            '"resolved_id": "create_app"},\n'
            '    "facts": [{"fact_text": "create_app is a factory function", '
            '"evidence_span_id": "span_1", "confidence": 0.95}],\n'
            '    "spans": [{"span_id": "span_1", "original_text": '
            '"create_app is a factory function."}],\n'
            '    "done": false,\n'
            '    "reason": null\n'
            "}"
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = invoke_hunter(
                state_text="The create_app is a factory function that initializes the app.",
                target_entity="create_app",
                mode="facts",
                knowledge_path=tmp_path,
            )

            mock_run.assert_called_once()

        assert result["mode"] == "facts"
        assert result["target_entity"] is not None
        assert result["target_entity"]["mention"] == "create_app"
        assert len(result["facts"]) == 1
        assert result["facts"][0]["confidence"] == 0.95


class TestInvokeHunterErrorHandling:
    def test_invoke_hunter_timeout_raises_error(self, tmp_path: Path) -> None:
        """Should raise HunterError on subprocess timeout."""
        with (
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired("cmd", 120),
            ),
            pytest.raises(HunterError, match="timed out"),
        ):
            invoke_hunter(
                state_text="Test text",
                mode="entities",
                knowledge_path=tmp_path,
            )

    def test_invoke_hunter_subprocess_not_found_raises_error(self, tmp_path: Path) -> None:
        """Should raise HunterError when uv CLI not found."""
        with (
            patch(
                "subprocess.run",
                side_effect=FileNotFoundError("uv not found"),
            ),
            pytest.raises(HunterError, match="uv CLI not found"),
        ):
            invoke_hunter(
                state_text="Test text",
                mode="entities",
                knowledge_path=tmp_path,
            )

    def test_invoke_hunter_non_zero_exit_raises_error(self, tmp_path: Path) -> None:
        """Should raise HunterError when subprocess returns non-zero exit code."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Agent failed"
        mock_result.stdout = ""

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(HunterError, match="non-zero exit code"),
        ):
            invoke_hunter(
                state_text="Test text",
                mode="entities",
                knowledge_path=tmp_path,
            )

    def test_invoke_hunter_empty_output_raises_error(self, tmp_path: Path) -> None:
        """Should raise HunterError when subprocess returns empty output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(HunterError, match="empty output"),
        ):
            invoke_hunter(
                state_text="Test text",
                mode="entities",
                knowledge_path=tmp_path,
            )
