"""Run configuration and state persistence for PDD lifecycle.

Persists run inputs (``run_config.json``) and mutable state
(``run_state.json``) under ``.pdd_runs/<run_id>/``.

Usage::

    state_mgr = RunStateManager(workspace_root=Path("."), run_id="abc")
    state_mgr.write_config(RunConfig(mode="auto", ...))
    state_mgr.update_state(active_layer="l1")
    current = state_mgr.read_state()
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RunConfig:
    """Immutable run configuration written once at pipeline start."""

    run_id: str = ""
    mode: str = "auto"
    input_folder: str = ""
    max_iterations_by_layer: dict[str, int] = field(
        default_factory=lambda: {"l1": 20, "l2": 30, "l3": 15}
    )
    max_approval_iterations: int = 3
    max_transition_rounds: int = 3
    stagnation_threshold: int = 3
    retry_budget: int = 3
    test_commands: dict[str, str] = field(default_factory=dict)
    model_ids: dict[str, str] = field(default_factory=dict)
    model_profile_name: str = ""
    enable_snapshots: bool = True
    enable_quality_scoring: bool = False
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunConfig:
        return cls(
            **{
                k: v
                for k, v in data.items()
                if k in {f.name for f in __import__("dataclasses").fields(cls)}
            }
        )


@dataclass
class RunState:
    """Mutable run state updated after each layer/transition."""

    run_id: str = ""
    active_layer: str = ""
    phase: str = ""  # e.g., "intake", "l1", "l1_l2_transition", "l2", "qa"
    layers_completed: list[str] = field(default_factory=list)
    transitions_completed: list[str] = field(default_factory=list)
    shas: dict[str, str] = field(default_factory=dict)  # layer → clean SHA
    budgets_consumed: dict[str, int] = field(default_factory=dict)
    total_iterations: int = 0
    total_demotions: int = 0
    stagnated_slices: list[str] = field(default_factory=list)
    blocked_slices: list[str] = field(default_factory=list)
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        return cls(
            **{
                k: v
                for k, v in data.items()
                if k in {f.name for f in __import__("dataclasses").fields(cls)}
            }
        )


class RunStateManager:
    """Reads/writes run config and state files."""

    def __init__(self, workspace_root: Path, run_id: str) -> None:
        self.workspace_root = workspace_root
        self.run_id = run_id
        self._run_dir = workspace_root / ".pdd_runs" / run_id

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def config_path(self) -> Path:
        return self._run_dir / "run_config.json"

    @property
    def state_path(self) -> Path:
        return self._run_dir / "run_state.json"

    def write_config(self, config: RunConfig) -> Path:
        """Write run_config.json (called once at pipeline start)."""
        self._run_dir.mkdir(parents=True, exist_ok=True)
        if not config.created_at:
            config.created_at = time.time()
        self.config_path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        return self.config_path

    def read_config(self) -> RunConfig | None:
        """Read run_config.json, or None if not found."""
        if not self.config_path.exists():
            return None
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        return RunConfig.from_dict(data)

    def update_state(self, **kwargs: Any) -> Path:
        """Update run_state.json with the given fields."""
        state = self.read_state() or RunState(run_id=self.run_id)
        for key, value in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, value)
        state.updated_at = time.time()
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        return self.state_path

    def read_state(self) -> RunState | None:
        """Read run_state.json, or None if not found."""
        if not self.state_path.exists():
            return None
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return RunState.from_dict(data)

    def ensure_directories(self) -> None:
        """Create the standard run directory structure."""
        dirs = [
            self._run_dir / "slices",
            self._run_dir / "demotions",
            self._run_dir / "ci" / "l1" / "batches",
            self._run_dir / "ci" / "l2" / "batches",
            self._run_dir / "ci" / "l3" / "batches",
        ]
        reports_dir = self.workspace_root / "reports" / "pdd" / self.run_id
        dirs.extend(
            [
                reports_dir / "architecture",
                reports_dir / "quality",
                reports_dir / "alignment",
            ]
        )
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
