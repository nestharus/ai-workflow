"""Spec refinement package.

Lazy imports are used for modules that depend on ``refinement.workspace``
to avoid a circular import through ``schemas.edge_list`` which imports
``refinement.formats`` at module scope.
"""

from __future__ import annotations

from spec_manager.core.agent_utils import run_agent
from spec_manager.core.gap import (
    Gap,
    GapEvidence,
    GapSynthesizer,
    GapType,
)
from spec_manager.core.gap_queue import GapQueue

_LAZY = {
    "ArtifactType": "spec_manager.refinement.repair",
    "get_repair_model": "spec_manager.refinement.repair",
    "repair_artifact": "spec_manager.refinement.repair",
    "ProgressTracker": "spec_manager.refinement.progress",
}


def __getattr__(name: str) -> object:
    mod_path = _LAZY.get(name)
    if mod_path is not None:
        import importlib

        mod = importlib.import_module(mod_path)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ArtifactType",
    "Gap",
    "GapEvidence",
    "GapQueue",
    "GapSynthesizer",
    "GapType",
    "ProgressTracker",
    "get_repair_model",
    "repair_artifact",
    "run_agent",
]
