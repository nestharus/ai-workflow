"""Integration layer: integration points, wiring, and pipeline."""

from spec_manager.labyrinth.integration.integration_points import (
    IntegrationPoint,
    IntegrationPointRegistry,
)
from spec_manager.labyrinth.integration.pipeline import Pipeline
from spec_manager.labyrinth.integration.wiring import SideEffectChain, WiringManager

__all__ = [
    "IntegrationPoint",
    "IntegrationPointRegistry",
    "Pipeline",
    "SideEffectChain",
    "WiringManager",
]
