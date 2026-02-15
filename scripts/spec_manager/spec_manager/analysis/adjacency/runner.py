"""Consumes relationship facts and runs adjacency graph analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from spec_manager.schemas.lineage import (
    CallRelationshipFact,
    RelationshipFacts,
    StoreRelationshipFact,
)
from spec_manager.schemas.pin_functions import PinFunctionRegistry

from .detector import (
    AdjacencyReport,
    build_unified_graph,
    detect_disconnected_components,
)
from .graph import SignalType


@dataclass
class AdjacencyAnalysisConfig:
    """Configuration for adjacency analysis from relationship facts."""

    source_dirs: list[Path] = field(default_factory=list)
    spec_dirs: list[Path] = field(default_factory=list)
    relationship_fact_paths: list[Path] = field(default_factory=list)
    relationship_facts: RelationshipFacts | None = None
    weight_overrides: dict[str, float] | None = None
    output_format: str = "json"  # "json" or "markdown"
    output_path: Path | None = None


def _candidate_relationship_paths_from_root(root: Path) -> list[Path]:
    """Return likely relationship-fact artifacts for one root path."""
    if not root.exists():
        return []
    if root.is_file():
        if root.name in {"relationship_facts.json", "pin_registry.json"}:
            return [root]
        return []
    return [
        candidate
        for candidate in (
            root / "relationship_facts.json",
            root / ".spec" / "relationship_facts.json",
            root / ".spec" / "pin_registry.json",
        )
        if candidate.exists() and candidate.is_file()
    ]


def _discover_relationship_fact_paths(config: AdjacencyAnalysisConfig) -> list[Path]:
    """Discover relationship-fact sources declared by config roots."""
    candidates: list[Path] = []
    candidates.extend(config.relationship_fact_paths)
    for root in [*config.source_dirs, *config.spec_dirs]:
        candidates.extend(_candidate_relationship_paths_from_root(root))

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _merge_relationship_facts(facts: list[RelationshipFacts]) -> RelationshipFacts:
    """Merge many fact payloads into one additive relationship payload."""
    merged = RelationshipFacts()
    for item in facts:
        merged.calls.extend(item.calls)
        merged.events.extend(item.events)
        merged.stores.extend(item.stores)
    return merged


def _facts_from_pin_registry(path: Path) -> RelationshipFacts:
    """Project pin registry data into relationship facts."""
    registry = PinFunctionRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    facts = RelationshipFacts()
    for edge in registry.import_edges:
        facts.calls.append(
            CallRelationshipFact(
                caller_pin=edge.arch_location,
                callee_pin=edge.pin_func_id,
                confidence=edge.confidence,
                evidence_pin=edge.pin_func_id,
            )
        )
    for pin in registry.pin_functions:
        for store_id in pin.store_touches:
            facts.stores.append(
                StoreRelationshipFact(
                    pin=pin.pin_func_id,
                    store_id=store_id,
                    access_type="read_write",
                )
            )
    return facts


def _load_relationship_facts(path: Path) -> RelationshipFacts:
    """Load one relationship-fact artifact file."""
    if path.name == "pin_registry.json":
        return _facts_from_pin_registry(path)

    content = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(content, dict) and isinstance(content.get("relationship_facts"), dict):
        content = content["relationship_facts"]
    return RelationshipFacts.model_validate(content)


def _has_relationship_data(facts: RelationshipFacts) -> bool:
    return bool(facts.calls or facts.events or facts.stores)


def run_adjacency_analysis(config: AdjacencyAnalysisConfig) -> AdjacencyReport:
    """Run adjacency analysis using unified relationship facts as input.

    Args:
        config: Analysis configuration

    Returns:
        AdjacencyReport with full analysis
    """
    fact_sources = _discover_relationship_fact_paths(config)
    loaded_facts = [_load_relationship_facts(path) for path in fact_sources]
    if config.relationship_facts is not None:
        loaded_facts.append(config.relationship_facts)

    relationship_facts = (
        _merge_relationship_facts(loaded_facts) if loaded_facts else RelationshipFacts()
    )

    # Convert weight overrides from string keys to SignalType multipliers.
    weight_overrides: dict[SignalType, float] | None = None
    if config.weight_overrides:
        weight_overrides = {}
        signal_type_map = {st.value: st for st in SignalType}
        for key, value in config.weight_overrides.items():
            if key in signal_type_map:
                weight_overrides[signal_type_map[key]] = value

    unified = build_unified_graph(
        relationship_facts=relationship_facts,
        weight_overrides=weight_overrides,
    )

    report = detect_disconnected_components(unified)
    if not _has_relationship_data(relationship_facts):
        report.disconnected_warnings.insert(
            0,
            "No RelationshipFacts were provided or discovered. "
            "Adjacency graph is empty until LLM relationship output is supplied.",
        )

    return report


def save_report(report: AdjacencyReport, config: AdjacencyAnalysisConfig) -> Path:
    """Save report to configured output path.

    Returns path where report was saved.
    """
    if config.output_path is None:
        output_dir = Path(".")
        if config.output_format == "markdown":
            output_path = output_dir / "adjacency_report.md"
        else:
            output_path = output_dir / "adjacency_report.json"
    else:
        output_path = config.output_path

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if config.output_format == "markdown":
        output_path.write_text(report.to_markdown(), encoding="utf-8")
    else:
        output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    return output_path
