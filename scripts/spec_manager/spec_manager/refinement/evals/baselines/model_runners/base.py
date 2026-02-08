"""Base protocol and types for model runners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ModelOutput:
    """Output from a model runner.

    Attributes:
        model_name: Name of the model.
        diff: Git diff of changes made.
        stdout: Raw stdout from the model process.
        stderr: Raw stderr from the model process.
        returncode: Process return code.
        duration_ms: Execution time in milliseconds.
        success: Whether the model completed without errors.
    """

    model_name: str
    diff: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    duration_ms: float = 0.0
    success: bool = True


class ModelRunner(Protocol):
    """Protocol for model runners."""

    def invoke(self, spec_text: str, codebase_path: Path, workspace: Path) -> ModelOutput:
        """Invoke the model with a spec and codebase.

        Args:
            spec_text: The specification text (dense spec).
            codebase_path: Path to the labyrinth codebase.
            workspace: Working directory for the model.

        Returns:
            ModelOutput with diff and execution details.
        """
        ...
