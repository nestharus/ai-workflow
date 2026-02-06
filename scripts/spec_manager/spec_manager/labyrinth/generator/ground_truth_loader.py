"""Loads ground truth into a Pipeline for self-test validation.

Given a LabyrinthInstance's rules, integration points, and chains,
this module registers everything into a live Pipeline so that
generated tests pass at 100%.
"""

from __future__ import annotations

from typing import Any

from spec_manager.labyrinth.engine.rule import CompositeRule, Rule
from spec_manager.labyrinth.integration.integration_points import IntegrationPoint
from spec_manager.labyrinth.integration.pipeline import Pipeline
from spec_manager.labyrinth.integration.wiring import SideEffectChain


def load_ground_truth(
    pipeline: Pipeline,
    rules: list[Rule | CompositeRule],
    integration_points: list[IntegrationPoint],
    chains: list[SideEffectChain],
) -> None:
    """Load all ground truth artifacts into a live pipeline.

    Registers rules, integration points, and side-effect chains so that
    the generated test suite passes at 100%.

    Args:
        pipeline: Pipeline instance to populate.
        rules: All generated rules (simple + composite).
        integration_points: All integration points with required_rules.
        chains: All side-effect chains to wire.
    """
    # Register all rules in the rule registry
    for rule in rules:
        pipeline.rule_registry.register(rule)

    # Register all integration points and mark required rules as registered
    for ip in integration_points:
        pipeline.integration_points.add(ip)
        # Register all required rules at this integration point
        for rule_id in ip.required_rules:
            ip.register_rule(rule_id)

    # Wire all side-effect chains
    for chain in chains:
        pipeline.wiring.add_chain(chain)


def load_ground_truth_from_json(
    pipeline: Pipeline,
    ground_truth: dict[str, Any],
    rules: list[Rule | CompositeRule],
    integration_points: list[IntegrationPoint],
    chains: list[SideEffectChain],
) -> None:
    """Load ground truth using JSON data for verification metadata.

    Same as load_ground_truth but accepts the ground_truth dict for
    any additional verification context. Currently delegates directly
    to load_ground_truth since the JSON is used by tests, not the loader.

    Args:
        pipeline: Pipeline instance to populate.
        ground_truth: Ground truth JSON dict (for reference).
        rules: All generated rules.
        integration_points: All integration points.
        chains: All side-effect chains.
    """
    load_ground_truth(pipeline, rules, integration_points, chains)
