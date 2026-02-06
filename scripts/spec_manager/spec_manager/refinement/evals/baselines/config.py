"""Configuration for baseline evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from spec_manager.core.project_root import resolve_from_root


@dataclass
class BaselineConfig:
    """Configuration for a baseline evaluation run.

    Attributes:
        level: Labyrinth complexity level (1-4).
        seed: Random seed for reproducibility.
        model: Model name (glm, opus, gpt).
        output_dir: Directory for outputs.
        timeout_seconds: Max time for model execution.
    """
    level: int = 1
    seed: int = 42
    model: str = "glm"
    output_dir: Path = field(
        default_factory=lambda: resolve_from_root("runs", "labyrinth", "baselines")
    )
    timeout_seconds: int = 600

    def workspace_dir(self) -> Path:
        """Get the workspace directory for this run."""
        return self.output_dir / f"L{self.level}_s{self.seed}_{self.model}"
