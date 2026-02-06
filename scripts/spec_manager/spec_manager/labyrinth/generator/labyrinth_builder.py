"""Labyrinth builder - generates complete labyrinth instances.

Orchestrates all factories to produce a complete, runnable labyrinth
at a given complexity level with reproducible randomness.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.labyrinth.engine.rule import CompositeRule, Rule
from spec_manager.labyrinth.generator.level_config import LevelConfig, get_level_config
from spec_manager.labyrinth.generator.rule_factory import RuleFactory
from spec_manager.labyrinth.generator.service_factory import ServiceFactory
from spec_manager.labyrinth.generator.spec_generator import DenseSpecGenerator, SparseSpecGenerator
from spec_manager.labyrinth.generator.steering_generator import SteeringScriptGenerator
from spec_manager.labyrinth.generator.test_generator import TestGenerator
from spec_manager.labyrinth.generator.wiring_factory import WiringFactory
from spec_manager.labyrinth.integration.integration_points import IntegrationPoint
from spec_manager.labyrinth.integration.wiring import SideEffectChain


@dataclass
class LabyrinthInstance:
    """A complete generated labyrinth instance.

    Attributes:
        level: Complexity level.
        seed: Random seed used for generation.
        config: Level configuration.
        rules: All generated rules.
        integration_points: All integration points.
        chains: All side-effect chains.
        topics: All bus topics.
        dense_spec: Complete specification markdown.
        sparse_spec: Ambiguous specification markdown.
        steering_script: Steering script for disambiguation.
        test_source: Generated pytest test source code.
        ground_truth: Ground truth data for verification.
        output_dir: Directory where files were written (if saved).
    """
    level: int
    seed: int
    config: LevelConfig
    rules: list[Rule | CompositeRule] = field(default_factory=list)
    integration_points: list[IntegrationPoint] = field(default_factory=list)
    chains: list[SideEffectChain] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    dense_spec: str = ""
    sparse_spec: str = ""
    steering_script: dict[str, Any] = field(default_factory=dict)
    test_source: str = ""
    ground_truth: dict[str, Any] = field(default_factory=dict)
    output_dir: Path | None = None


class LabyrinthBuilder:
    """Generates complete labyrinth instances at configurable complexity levels.

    Seed ensures reproducibility. Each call to build() with the same
    level and seed produces identical output.
    """

    def build(self, level: int, seed: int = 42) -> LabyrinthInstance:
        """Generate a complete labyrinth at the given complexity level.

        Args:
            level: Complexity level (1-4).
            seed: Random seed for reproducibility.

        Returns:
            LabyrinthInstance with all generated artifacts.
        """
        config = get_level_config(level)
        rng = random.Random(seed)

        # Generate rules
        rule_factory = RuleFactory(config, rng)
        rules = rule_factory.generate_rules()

        # Collect topics from rules
        topics: list[str] = []
        output_topics: list[str] = []
        for rule in rules:
            if isinstance(rule, Rule):
                topics.extend(rule.topics)
                if rule.output_topic:
                    topics.append(rule.output_topic)
                    output_topics.append(rule.output_topic)
        topics = sorted(set(topics))
        output_topics = sorted(set(output_topics))

        # Generate integration points
        wiring_factory = WiringFactory(config, rng)
        integration_points = wiring_factory.generate_integration_points(rules, topics)

        # Generate side-effect chains
        # Chains must be wired to output topics (topics rules publish TO)
        # so that rule execution actually triggers the chains
        service_factory = ServiceFactory(config, rng)
        chains = service_factory.generate_chains(output_topics)

        # Generate ground truth
        ground_truth = self._generate_ground_truth(rules, integration_points, chains, rng)

        # Generate specs
        dense_gen = DenseSpecGenerator()
        dense_spec = dense_gen.generate(level, rules, integration_points, chains, topics)

        sparse_gen = SparseSpecGenerator(rng)
        sparse_spec = sparse_gen.generate(level, rules, integration_points, chains)

        # Generate steering script
        steering_gen = SteeringScriptGenerator(rng)
        steering_script = steering_gen.generate(level, rules, integration_points, chains)

        # Generate test suite
        test_gen = TestGenerator()
        test_source = test_gen.generate_test_suite(
            level, rules, integration_points, chains, ground_truth
        )

        return LabyrinthInstance(
            level=level,
            seed=seed,
            config=config,
            rules=rules,
            integration_points=integration_points,
            chains=chains,
            topics=topics,
            dense_spec=dense_spec,
            sparse_spec=sparse_spec,
            steering_script=steering_script,
            test_source=test_source,
            ground_truth=ground_truth,
        )

    def build_and_save(
        self, level: int, seed: int = 42, output_dir: Path | None = None
    ) -> LabyrinthInstance:
        """Build a labyrinth and save all artifacts to disk.

        Args:
            level: Complexity level (1-4).
            seed: Random seed.
            output_dir: Directory to save files. Defaults to runs/labyrinth/L{level}_s{seed}.

        Returns:
            LabyrinthInstance with output_dir set.
        """
        instance = self.build(level, seed)

        if output_dir is None:
            from spec_manager.core.project_root import resolve_from_root
            output_dir = resolve_from_root("runs", "labyrinth", f"L{level}_s{seed}")

        output_dir.mkdir(parents=True, exist_ok=True)
        instance.output_dir = output_dir

        # Save dense spec
        (output_dir / "dense_spec.md").write_text(instance.dense_spec, encoding="utf-8")

        # Save sparse spec
        (output_dir / "sparse_spec.md").write_text(instance.sparse_spec, encoding="utf-8")

        # Save steering script
        (output_dir / "steering.json").write_text(
            json.dumps(instance.steering_script, indent=2), encoding="utf-8"
        )

        # Save ground truth
        (output_dir / "ground_truth.json").write_text(
            json.dumps(instance.ground_truth, indent=2), encoding="utf-8"
        )

        # Save test suite
        tests_dir = output_dir / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")
        (tests_dir / f"test_labyrinth_l{level}.py").write_text(
            instance.test_source, encoding="utf-8"
        )

        # Save conftest
        test_gen = TestGenerator()
        (tests_dir / "conftest.py").write_text(
            test_gen.generate_conftest(level), encoding="utf-8"
        )

        # Save rule manifest
        rule_manifest = self._build_rule_manifest(instance)
        (output_dir / "rule_manifest.json").write_text(
            json.dumps(rule_manifest, indent=2), encoding="utf-8"
        )

        return instance

    def _generate_ground_truth(
        self,
        rules: list[Rule | CompositeRule],
        integration_points: list[IntegrationPoint],
        chains: list[SideEffectChain],
        rng: random.Random,
    ) -> dict[str, Any]:
        """Generate ground truth data for test verification."""
        from spec_manager.labyrinth.core.record import InputRecord
        from spec_manager.labyrinth.generator.rule_factory import FIELD_VALUES

        rule_tests: list[dict[str, Any]] = []

        # Generate test cases for simple rules
        for rule in rules:
            if not isinstance(rule, Rule):
                continue
            if rule.transform is None:
                continue

            # Generate an input that should match the conditions
            matching_input = self._generate_matching_input(rule, rng)
            if matching_input is None:
                continue

            # Get expected output
            sample = InputRecord(record_id="gt", data=matching_input)
            try:
                expected = rule.transform(sample)
            except Exception:
                continue

            rule_tests.append({
                "rule_id": rule.rule_id,
                "input": matching_input,
                "expected_output": {k: v for k, v in expected.items() if not k.startswith("_")},
                "should_fire": True,
            })

        # Generate chain test cases
        # Find rules that publish to each chain's trigger topic
        # so we can generate inputs that actually cause the chain to fire
        topic_to_rule: dict[str, Rule] = {}
        for rule in rules:
            if isinstance(rule, Rule) and rule.output_topic:
                topic_to_rule[rule.output_topic] = rule

        chain_tests: list[dict[str, Any]] = []
        for chain in chains:
            trigger_rule = topic_to_rule.get(chain.trigger_topic)
            if trigger_rule is not None:
                # Generate input that satisfies the triggering rule
                trigger_input = self._generate_matching_input(trigger_rule, rng)
            else:
                # No rule publishes to this topic; use generic input
                trigger_input = {"amount": 5000, "type": "INVOICE", "currency": "USD"}
            chain_tests.append({
                "chain_id": chain.chain_id,
                "trigger_input": trigger_input or {"amount": 5000, "type": "INVOICE", "currency": "USD"},
                "expected_log_types": list(chain.expected_log_entries),
            })

        return {
            "level": rules[0].rule_id.split("-")[1] if rules else "L0",
            "rule_tests": rule_tests,
            "chain_tests": chain_tests,
            "integration_point_count": len(integration_points),
            "chain_count": len(chains),
            "total_rules": len(rules),
        }

    def _generate_matching_input(
        self, rule: Rule, rng: random.Random
    ) -> dict[str, Any] | None:
        """Generate input data that should match the rule's conditions."""
        from spec_manager.labyrinth.engine.conditions import (
            Condition,
            ConditionOperator,
        )
        from spec_manager.labyrinth.generator.rule_factory import FIELD_VALUES

        data: dict[str, Any] = {
            "amount": 5000,
            "type": "INVOICE",
            "currency": "USD",
            "status": "PENDING",
            "priority": "MEDIUM",
            "category": "TRADE",
            "region": "NA",
            "department": "TREASURY",
        }

        # Try to satisfy each condition
        for cond in rule.conditions.conditions:
            if not isinstance(cond, Condition):
                continue

            if cond.operator == ConditionOperator.EQ:
                data[cond.field_name] = cond.value
            elif cond.operator == ConditionOperator.GT:
                data[cond.field_name] = cond.value + 1
            elif cond.operator == ConditionOperator.GTE:
                data[cond.field_name] = cond.value
            elif cond.operator == ConditionOperator.LT:
                data[cond.field_name] = cond.value - 1
            elif cond.operator == ConditionOperator.LTE:
                data[cond.field_name] = cond.value
            elif cond.operator == ConditionOperator.NEQ:
                if cond.field_name in FIELD_VALUES:
                    options = [v for v in FIELD_VALUES[cond.field_name] if v != cond.value]
                    if options:
                        data[cond.field_name] = rng.choice(options)
            elif cond.operator == ConditionOperator.IN:
                if isinstance(cond.value, (list, tuple)) and cond.value:
                    data[cond.field_name] = rng.choice(cond.value)
            elif cond.operator == ConditionOperator.CONTAINS:
                data[cond.field_name] = f"contains_{cond.value}_value"

        return data

    def _build_rule_manifest(self, instance: LabyrinthInstance) -> dict[str, Any]:
        """Build a manifest of all rules for reference."""
        rules_data: list[dict[str, Any]] = []
        for rule in instance.rules:
            entry: dict[str, Any] = {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "type": "composite" if isinstance(rule, CompositeRule) else "simple",
            }
            if isinstance(rule, Rule):
                entry["group"] = rule.group
                entry["dependencies"] = rule.dependencies
                entry["topics"] = rule.topics
                entry["output_topic"] = rule.output_topic
            elif isinstance(rule, CompositeRule):
                entry["mode"] = rule.mode.value
                entry["sub_rules"] = [sr.rule_id for sr in rule.sub_rules]
            rules_data.append(entry)

        return {
            "level": instance.level,
            "seed": instance.seed,
            "total_rules": len(instance.rules),
            "total_integration_points": len(instance.integration_points),
            "total_chains": len(instance.chains),
            "rules": rules_data,
        }
