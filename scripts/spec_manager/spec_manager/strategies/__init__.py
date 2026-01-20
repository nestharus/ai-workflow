"""
Strategy framework for spec_manager.

Strategies are the reasoning layer above tools. A strategy knows:
- What problem it solves (purpose)
- When to apply it (applies_to)
- What tools it uses
- What risk it mitigates (risk_addressed)

Usage:
    from spec_manager.strategies import StrategyRegistry, ProcessingContext, StrategyPhase

    # Create registry and load definitions
    registry = StrategyRegistry()
    registry.load_from_directory(Path("strategies/definitions"))

    # Get strategies for a context
    context = ProcessingContext(units=my_units, phase=StrategyPhase.CLEANING)
    applicable = registry.get_applicable(context)

    # Execute each
    for strategy in applicable:
        result = strategy.execute(context)
"""

from spec_manager.strategies.base import (
    StrategyPhase,
    ProcessingContext,
    StrategyResult,
    Strategy,
    Tool,
    StrategyDefinition,
)
from spec_manager.strategies.registry import (
    StrategyRegistry,
    StrategyGapEvidence,
)
from spec_manager.strategies.entity_resolution import (
    ResolutionContext,
    ResolutionResult,
    ReferenceStore,
    EntityResolver,
)

__all__ = [
    # Base classes
    "StrategyPhase",
    "ProcessingContext",
    "StrategyResult",
    "Strategy",
    "Tool",
    "StrategyDefinition",
    # Registry
    "StrategyRegistry",
    "StrategyGapEvidence",
    # Entity resolution
    "ResolutionContext",
    "ResolutionResult",
    "ReferenceStore",
    "EntityResolver",
]
