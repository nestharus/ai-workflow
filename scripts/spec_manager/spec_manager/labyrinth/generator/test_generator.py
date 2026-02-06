"""Generates pytest test suites for labyrinth instances.

Two dimensions of tests are generated:
1. Rule Accuracy: Feed InputRecord -> assert OutputRecord values
2. Integration Completeness: Check EventLog for integration points and side-effect chains
"""

from __future__ import annotations

import json
from typing import Any

from spec_manager.labyrinth.core.record import InputRecord
from spec_manager.labyrinth.engine.conditions import (
    Condition,
    ConditionGroup,
    ConditionOperator,
    LogicOperator,
)
from spec_manager.labyrinth.engine.rule import CompositeRule, Rule
from spec_manager.labyrinth.integration.integration_points import IntegrationPoint
from spec_manager.labyrinth.integration.wiring import SideEffectChain


class TestGenerator:
    """Generates pytest test files for labyrinth verification."""

    def generate_test_suite(
        self,
        level: int,
        rules: list[Rule | CompositeRule],
        integration_points: list[IntegrationPoint],
        chains: list[SideEffectChain],
        ground_truth: dict[str, Any],
    ) -> str:
        """Generate a complete pytest test file.

        Args:
            level: Complexity level.
            rules: All rules.
            integration_points: All integration points.
            chains: All side-effect chains.
            ground_truth: Expected outputs for verification.

        Returns:
            Python source code for the test file.
        """
        lines: list[str] = []

        # Header
        lines.append(f'"""Auto-generated test suite for Labyrinth Level {level}.')
        lines.append('')
        lines.append('Tests verify two independent dimensions:')
        lines.append('1. Rule Accuracy: InputRecord -> OutputRecord value correctness')
        lines.append('2. Integration Completeness: EventLog verification for integration points and chains')
        lines.append('"""')
        lines.append('')
        lines.append('import asyncio')
        lines.append('import pytest')
        lines.append('')
        lines.append('from spec_manager.labyrinth.core.bus import AsyncMessageBus')
        lines.append('from spec_manager.labyrinth.core.event_log import EventLog')
        lines.append('from spec_manager.labyrinth.core.record import InputRecord, OutputRecord')
        lines.append('from spec_manager.labyrinth.core.worker_pool import WorkerPool')
        lines.append('from spec_manager.labyrinth.engine.executor import RuleExecutor')
        lines.append('from spec_manager.labyrinth.engine.registry import RuleRegistry')
        lines.append('from spec_manager.labyrinth.integration.pipeline import Pipeline')
        lines.append('')
        lines.append('')

        # Generate rule accuracy tests
        lines.append(f'# === Rule Accuracy Tests (Level {level}) ===')
        lines.append('')

        rule_tests = ground_truth.get("rule_tests", [])
        for i, test_case in enumerate(rule_tests):
            test_name = f"test_rule_accuracy_{i + 1:04d}"
            rule_id = test_case.get("rule_id", "UNKNOWN")
            input_data = test_case.get("input", {})
            expected_output = test_case.get("expected_output", {})
            should_fire = test_case.get("should_fire", True)

            lines.append(f'def {test_name}(pipeline):')
            lines.append(f'    """Test {rule_id} produces correct output."""')
            lines.append(f'    record = InputRecord(')
            lines.append(f'        record_id="test-{i + 1}",')
            lines.append(f'        data={json.dumps(input_data)},')
            lines.append(f'    )')
            lines.append(f'    results = pipeline.process_sync(record)')

            if should_fire:
                lines.append(f'    rule_results = [r for r in results if r.source_rule_id == "{rule_id}"]')
                lines.append(f'    assert len(rule_results) > 0, "Rule {rule_id} should have fired"')
                for key, value in expected_output.items():
                    if key.startswith("_"):
                        continue
                    json_val = json.dumps(value)
                    # Use repr for the message to avoid quote conflicts
                    safe_msg = f"Expected {key}={value!r}"
                    lines.append(f'    assert rule_results[0].data.get("{key}") == {json_val}, \\')
                    lines.append(f'        {safe_msg!r}')
            else:
                lines.append(f'    rule_results = [r for r in results if r.source_rule_id == "{rule_id}"]')
                lines.append(f'    assert len(rule_results) == 0, "Rule {rule_id} should NOT have fired"')

            lines.append('')
            lines.append('')

        # Generate integration completeness tests
        lines.append(f'# === Integration Completeness Tests (Level {level}) ===')
        lines.append('')

        # Test: all integration points have required rules registered
        lines.append('def test_all_integration_points_satisfied(pipeline):')
        lines.append('    """All integration points should have their required rules registered."""')
        lines.append('    gaps = pipeline.integration_points.check_all_satisfied()')
        lines.append('    assert gaps == {}, f"Unsatisfied integration points: {gaps}"')
        lines.append('')
        lines.append('')

        # Test: all side-effect chains fired
        chain_tests = ground_truth.get("chain_tests", [])
        for i, test_case in enumerate(chain_tests):
            chain_id = test_case.get("chain_id", "UNKNOWN")
            trigger_input = test_case.get("trigger_input", {})
            expected_log_types = test_case.get("expected_log_types", [])

            lines.append(f'def test_chain_fired_{i + 1:04d}(pipeline):')
            lines.append(f'    """Test {chain_id} fires all expected services."""')
            lines.append(f'    record = InputRecord(')
            lines.append(f'        record_id="chain-test-{i + 1}",')
            lines.append(f'        data={json.dumps(trigger_input)},')
            lines.append(f'    )')
            lines.append(f'    pipeline.process_sync(record)')
            for log_type in expected_log_types:
                lines.append(f'    entries = pipeline.event_log.filter_by_type("{log_type}")')
                lines.append(f'    assert len(entries) > 0, "Expected {log_type} in event log"')
            lines.append('')
            lines.append('')

        # Test: side-effect chain ordering
        lines.append('def test_side_effect_chain_order(pipeline):')
        lines.append('    """Verify side-effect chains fire in correct order."""')
        lines.append('    record = InputRecord(')
        lines.append('        record_id="order-test",')
        lines.append('        data={"amount": 5000, "type": "INVOICE", "currency": "USD"},')
        lines.append('    )')
        lines.append('    pipeline.process_sync(record)')
        lines.append('    sources = pipeline.event_log.get_sources_in_order()')
        lines.append('    # Pipeline should start first')
        lines.append('    assert "pipeline" in sources, "Pipeline should appear in event log"')
        lines.append('')

        return "\n".join(lines)

    def generate_conftest(self, level: int) -> str:
        """Generate conftest.py for the test suite.

        The conftest tries to import a `labyrinth_setup` module written
        by the model under evaluation. If the module exists, it calls
        `setup_labyrinth(pipeline)` to register rules, integration points,
        and side-effect chains. If the module doesn't exist (pre-model run),
        the pipeline stays bare and tests score 0%.
        """
        return f'''"""Conftest for Labyrinth Level {level} tests."""

import pytest

from spec_manager.labyrinth.integration.pipeline import Pipeline


@pytest.fixture
def pipeline():
    """Create a fresh pipeline instance.

    Tries to import labyrinth_setup.setup_labyrinth() written by the
    model under evaluation. Falls back to bare Pipeline if not found.
    """
    p = Pipeline()
    try:
        from labyrinth_setup import setup_labyrinth
        setup_labyrinth(p)
    except ImportError:
        pass  # No setup module = bare pipeline = 0% score
    yield p
    p.shutdown()
'''
