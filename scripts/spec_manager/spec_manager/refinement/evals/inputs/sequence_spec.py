"""Sequence specification schemas for deterministic evaluation.

Sequence specs describe mathematical number sequence systems with explicit rules
that map to extractable requirements. These serve as test inputs with verifiable
ground truth for evaluating the spec refinement system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from spec_manager.refinement.evals.inputs.ground_truth import GroundTruth


@dataclass
class SequenceRule:
    """A single rule in a sequence specification.

    Rules describe mathematical properties, base cases, recurrences, constraints,
    or boundary conditions that should be extracted as requirements.

    Attributes:
        rule_id: Unique identifier (e.g., RULE-001).
        rule_type: Category of rule (base, recurrence, constraint, boundary).
        description: Natural language description of the rule.
        formal_expression: Mathematical notation (e.g., a(n) = a(n-1) + a(n-2)).
        dependencies: List of rule_ids this rule depends on.
        examples: List of (input, output) pairs demonstrating the rule.
    """

    rule_id: str
    rule_type: Literal["base", "recurrence", "constraint", "boundary"]
    description: str
    formal_expression: str
    dependencies: list[str] = field(default_factory=list)
    examples: list[tuple[int, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "description": self.description,
            "formal_expression": self.formal_expression,
            "dependencies": self.dependencies,
            "examples": self.examples,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequenceRule:
        """Deserialize from dictionary."""
        examples = data.get("examples", [])
        if examples and isinstance(examples[0], list):
            examples = [tuple(ex) for ex in examples]
        return cls(
            rule_id=data["rule_id"],
            rule_type=data["rule_type"],
            description=data["description"],
            formal_expression=data["formal_expression"],
            dependencies=data.get("dependencies", []),
            examples=examples,
        )


@dataclass
class SequenceSpec:
    """A complete sequence specification with ground truth.

    Represents a mathematical sequence system (e.g., Fibonacci, Collatz) as a
    specification document with sections, rules, and expected outputs per phase.

    Attributes:
        spec_id: Unique identifier for this spec.
        title: Human-readable title.
        description: Overview of what the sequence computes.
        sections: Section content by label (e.g., OVERVIEW, RULES, EXAMPLES).
        rules: List of SequenceRule objects.
        ground_truth: Expected outputs per phase for evaluation.
        complexity_score: Difficulty rating 1-10.
        tags: Optional categorization tags.
    """

    spec_id: str
    title: str
    description: str
    sections: dict[str, str]
    rules: list[SequenceRule]
    ground_truth: GroundTruth
    complexity_score: int = 5
    tags: list[str] = field(default_factory=list)

    def get_section_content(self, section_label: str) -> str | None:
        """Get content for a specific section."""
        return self.sections.get(section_label)

    def get_rules_by_type(self, rule_type: str) -> list[SequenceRule]:
        """Get all rules of a specific type."""
        return [rule for rule in self.rules if rule.rule_type == rule_type]

    def get_rule_by_id(self, rule_id: str) -> SequenceRule | None:
        """Get a specific rule by ID."""
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def get_all_rule_ids(self) -> list[str]:
        """Get all rule IDs in order."""
        return [rule.rule_id for rule in self.rules]

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """Build a dependency graph of rule_id -> dependent rule_ids."""
        graph: dict[str, list[str]] = {rule.rule_id: [] for rule in self.rules}
        for rule in self.rules:
            for dep_id in rule.dependencies:
                if dep_id in graph:
                    graph[dep_id].append(rule.rule_id)
        return graph

    def to_markdown(self) -> str:
        """Generate markdown representation of the spec."""
        lines = [
            f"# {self.title}",
            "",
            self.description,
            "",
        ]

        for section_label, content in self.sections.items():
            lines.append(f"## {section_label}")
            lines.append("")
            lines.append(content)
            lines.append("")

        lines.append("## Rules")
        lines.append("")
        for rule in self.rules:
            lines.append(f"### {rule.rule_id}: {rule.rule_type.upper()}")
            lines.append("")
            lines.append(rule.description)
            lines.append("")
            if rule.formal_expression:
                lines.append(f"**Formula:** `{rule.formal_expression}`")
                lines.append("")
            if rule.dependencies:
                deps = ", ".join(rule.dependencies)
                lines.append(f"**Depends on:** {deps}")
                lines.append("")
            if rule.examples:
                lines.append("**Examples:**")
                for inp, out in rule.examples:
                    lines.append(f"- f({inp}) = {out}")
                lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "spec_id": self.spec_id,
            "title": self.title,
            "description": self.description,
            "sections": self.sections,
            "rules": [rule.to_dict() for rule in self.rules],
            "ground_truth": self.ground_truth.to_dict(),
            "complexity_score": self.complexity_score,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequenceSpec:
        """Deserialize from dictionary."""
        return cls(
            spec_id=data["spec_id"],
            title=data["title"],
            description=data.get("description", ""),
            sections=data.get("sections", {}),
            rules=[SequenceRule.from_dict(r) for r in data.get("rules", [])],
            ground_truth=GroundTruth.from_dict(data.get("ground_truth", {})),
            complexity_score=data.get("complexity_score", 5),
            tags=data.get("tags", []),
        )


def load_sequence_spec(path: Path) -> SequenceSpec:
    """Load a sequence spec from a YAML or JSON file.

    Args:
        path: Path to the spec file.

    Returns:
        Loaded SequenceSpec object.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file format is invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"Spec file not found: {path}")

    content = path.read_text(encoding="utf-8")

    if path.suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(content)
    elif path.suffix == ".json":
        data = json.loads(content)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}")

    if not isinstance(data, dict):
        raise ValueError(f"Invalid spec file format: expected dict, got {type(data)}")

    return SequenceSpec.from_dict(data)


def load_sequence_specs_from_dir(directory: Path) -> list[SequenceSpec]:
    """Load all sequence specs from a directory.

    Args:
        directory: Path to directory containing spec files.

    Returns:
        List of loaded SequenceSpec objects, sorted by spec_id.
    """
    specs: list[SequenceSpec] = []

    if not directory.exists():
        return specs

    for path in sorted(directory.iterdir()):
        if path.suffix in {".yaml", ".yml", ".json"}:
            try:
                spec = load_sequence_spec(path)
                specs.append(spec)
            except (ValueError, KeyError) as exc:
                # Log warning but continue loading other specs
                import logging

                logging.warning("Failed to load spec %s: %s", path, exc)

    return sorted(specs, key=lambda s: s.spec_id)
