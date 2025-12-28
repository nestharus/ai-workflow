"""Pytest fixtures for pr command tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_git_dao_refs_match() -> Generator[MagicMock]:
    """Fixture that patches git_dao with check_refs_match returning matching refs.

    Returns a mock with check_refs_match.return_value = (True, "abc1234", "abc1234").
    """
    with patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git:
        mock_git.check_refs_match.return_value = (True, "abc1234", "abc1234")
        yield mock_git


@pytest.fixture
def mock_sandbox_git_dao_refs_match() -> Generator[MagicMock]:
    """Fixture that patches sandbox git_dao with check_refs_match returning matching refs.

    Returns a mock with check_refs_match.return_value = (True, "abc1234", "abc1234").
    """
    with patch("scripts.pr.commands.sandbox_merge_command.git_dao") as mock_git:
        mock_git.check_refs_match.return_value = (True, "abc1234", "abc1234")
        yield mock_git
