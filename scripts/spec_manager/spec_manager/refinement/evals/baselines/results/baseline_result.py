"""Baseline result data structure."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BaselineResult:
    """Result of a single baseline evaluation run.

    Attributes:
        model_name: Model that was evaluated.
        level: Labyrinth complexity level.
        rule_accuracy: Proportion of rule tests passed.
        integration_completeness: Proportion of integration tests passed.
        rule_tests_passed: Number of rule tests passed.
        rule_tests_total: Total rule tests.
        integration_tests_passed: Number of integration tests passed.
        integration_tests_total: Total integration tests.
        duration_ms: Total execution time in milliseconds.
        broken: True when BOTH dimensions fail thresholds.
        seed: Random seed used.
        errors: Any errors encountered.
    """
    model_name: str
    level: int
    rule_accuracy: float = 0.0
    integration_completeness: float = 0.0
    rule_tests_passed: int = 0
    rule_tests_total: int = 0
    integration_tests_passed: int = 0
    integration_tests_total: int = 0
    duration_ms: float = 0.0
    broken: bool = False
    seed: int = 42
    errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "level": self.level,
            "rule_accuracy": self.rule_accuracy,
            "integration_completeness": self.integration_completeness,
            "rule_tests_passed": self.rule_tests_passed,
            "rule_tests_total": self.rule_tests_total,
            "integration_tests_passed": self.integration_tests_passed,
            "integration_tests_total": self.integration_tests_total,
            "duration_ms": self.duration_ms,
            "broken": self.broken,
            "seed": self.seed,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaselineResult:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> BaselineResult:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
