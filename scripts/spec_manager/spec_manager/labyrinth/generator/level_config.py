"""Complexity level configuration for labyrinth generation.

Each level scales from the previous in three independent dimensions:
- Rules count (4x per level)
- Integration points (4x per level)
- Side effect chains (4x per level)

Architecture complexity also scales:
- L1: Basic event bus, simple function calls
- L2: Async event loop + thread pool + message pipeline
- L3: Nested event loops, multi-threaded consumers, complex routing
- L4: Event sourcing, saga patterns, distributed-style messaging
- L5+: Dynamically generated with the same 4x scaling formula
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LevelConfig:
    """Configuration for a single complexity level.

    Attributes:
        level: Level number (1+).
        num_rules: Number of rules to generate.
        num_integration_points: Number of integration points.
        num_side_effect_chains: Number of side-effect chains.
        num_rule_groups: Number of rule groups.
        max_rule_dependencies: Max dependencies per rule.
        max_conditions_per_rule: Max conditions per rule.
        composite_rule_ratio: Fraction of rules that are composite.
        nested_composition_depth: Max nesting depth for composite rules.
        num_bus_topics: Number of distinct bus topics.
        target_model: Target model this level is designed to break.
    """
    level: int
    num_rules: int
    num_integration_points: int
    num_side_effect_chains: int
    num_rule_groups: int
    max_rule_dependencies: int
    max_conditions_per_rule: int
    composite_rule_ratio: float
    nested_composition_depth: int
    num_bus_topics: int
    target_model: str


LEVEL_CONFIGS: dict[int, LevelConfig] = {
    1: LevelConfig(
        level=1,
        num_rules=16,
        num_integration_points=4,
        num_side_effect_chains=2,
        num_rule_groups=4,
        max_rule_dependencies=2,
        max_conditions_per_rule=2,
        composite_rule_ratio=0.25,
        nested_composition_depth=1,
        num_bus_topics=4,
        target_model="GLM",
    ),
    2: LevelConfig(
        level=2,
        num_rules=64,
        num_integration_points=16,
        num_side_effect_chains=8,
        num_rule_groups=8,
        max_rule_dependencies=4,
        max_conditions_per_rule=4,
        composite_rule_ratio=0.3,
        nested_composition_depth=2,
        num_bus_topics=8,
        target_model="Opus",
    ),
    3: LevelConfig(
        level=3,
        num_rules=256,
        num_integration_points=64,
        num_side_effect_chains=32,
        num_rule_groups=16,
        max_rule_dependencies=8,
        max_conditions_per_rule=6,
        composite_rule_ratio=0.35,
        nested_composition_depth=3,
        num_bus_topics=16,
        target_model="GPT 5.3",
    ),
    4: LevelConfig(
        level=4,
        num_rules=1024,
        num_integration_points=256,
        num_side_effect_chains=128,
        num_rule_groups=32,
        max_rule_dependencies=12,
        max_conditions_per_rule=8,
        composite_rule_ratio=0.4,
        nested_composition_depth=4,
        num_bus_topics=32,
        target_model="Ceiling",
    ),
}


def _compute_level_config(level: int) -> LevelConfig:
    """Compute a level config dynamically using the 4x scaling formula.

    Base values at L1 are scaled by 4^(level-1) for counts.
    Other parameters scale linearly or with diminishing returns.
    """
    scale = 4 ** (level - 1)

    return LevelConfig(
        level=level,
        num_rules=16 * scale,
        num_integration_points=4 * scale,
        num_side_effect_chains=2 * scale,
        num_rule_groups=min(4 * scale, 512),
        max_rule_dependencies=min(2 + (level - 1) * 2, 24),
        max_conditions_per_rule=min(2 + level, 12),
        composite_rule_ratio=min(0.25 + (level - 1) * 0.05, 0.6),
        nested_composition_depth=min(level, 8),
        num_bus_topics=min(4 * scale, 256),
        target_model=f"L{level}",
    )


def get_level_config(level: int) -> LevelConfig:
    """Get configuration for a complexity level.

    Levels 1-4 use hand-tuned configs. Levels 5+ are computed
    dynamically using the 4x scaling formula.

    Args:
        level: Level number (1+).

    Returns:
        LevelConfig for the level.

    Raises:
        ValueError: If level is less than 1.
    """
    if level < 1:
        raise ValueError(f"Invalid level {level}. Must be >= 1.")
    if level in LEVEL_CONFIGS:
        return LEVEL_CONFIGS[level]
    return _compute_level_config(level)
