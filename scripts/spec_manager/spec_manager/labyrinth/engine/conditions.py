"""Condition predicates for rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from spec_manager.labyrinth.core.record import InputRecord


class ConditionOperator(str, Enum):
    """Operators for comparing field values."""

    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    CONTAINS = "contains"


class LogicOperator(str, Enum):
    """Logical operators for combining conditions."""

    AND = "and"
    OR = "or"


@dataclass(frozen=True)
class Condition:
    """A single predicate on an input record field.

    Attributes:
        field_name: Name of the field to check in InputRecord.data.
        operator: Comparison operator.
        value: Value to compare against.
    """

    field_name: str
    operator: ConditionOperator
    value: Any

    def evaluate(self, record: InputRecord) -> bool:
        """Evaluate this condition against an input record."""
        actual = record.get(self.field_name)
        if actual is None:
            return False

        if self.operator == ConditionOperator.EQ:
            return actual == self.value
        elif self.operator == ConditionOperator.NEQ:
            return actual != self.value
        elif self.operator == ConditionOperator.GT:
            return actual > self.value
        elif self.operator == ConditionOperator.GTE:
            return actual >= self.value
        elif self.operator == ConditionOperator.LT:
            return actual < self.value
        elif self.operator == ConditionOperator.LTE:
            return actual <= self.value
        elif self.operator == ConditionOperator.IN:
            return actual in self.value
        elif self.operator == ConditionOperator.CONTAINS:
            return self.value in actual
        return False


@dataclass
class ConditionGroup:
    """A group of conditions combined with a logical operator.

    Supports nested groups for complex boolean logic.

    Attributes:
        logic: How to combine the conditions (AND/OR).
        conditions: List of Condition or ConditionGroup instances.
    """

    logic: LogicOperator = LogicOperator.AND
    conditions: list[Condition | ConditionGroup] = field(default_factory=list)

    def evaluate(self, record: InputRecord) -> bool:
        """Evaluate all conditions against an input record."""
        if not self.conditions:
            return True

        results = [c.evaluate(record) for c in self.conditions]

        if self.logic == LogicOperator.AND:
            return all(results)
        return any(results)

    def add(self, condition: Condition | ConditionGroup) -> None:
        """Add a condition to the group."""
        self.conditions.append(condition)
