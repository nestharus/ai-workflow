"""Consumes relationship facts and runs adjacency graph analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from spec_manager.schemas.lineage import (
    ReferenceRelationshipFact,
    RelationshipFacts,
    StoreRelationshipFact,
)
from spec_manager.schemas.pin_functions import PinFunctionRegistry

from .detector import (
    AdjacencyReport,
    build_unified_graph,
    detect_disconnected_components,
)
from .extractors.cooccurrence import build_cooccurrence_verifier_graph
from .graph import AdjacencyGraph, SignalType


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


_SOURCE_KIND_PIN_REGISTRY = "pin_registry_projection"
_SOURCE_KIND_RELATIONSHIP_FACTS = "relationship_facts_artifact"
_SOURCE_KIND_INLINE = "inline_relationship_facts"
_SOURCE_PRECEDENCE: dict[str, int] = {
    _SOURCE_KIND_PIN_REGISTRY: 0,
    _SOURCE_KIND_RELATIONSHIP_FACTS: 1,
    _SOURCE_KIND_INLINE: 2,
}


@dataclass(frozen=True)
class _LoadedFactSource:
    facts: RelationshipFacts
    source_kind: str
    source_path: Path | None = None


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


def _source_rank(source_kind: str) -> int:
    return _SOURCE_PRECEDENCE.get(source_kind, -1)


def _source_label(source: _LoadedFactSource) -> str:
    if source.source_path is None:
        return source.source_kind
    return f"{source.source_kind}:{source.source_path}"


def _merge_relationship_facts(
    sources: list[_LoadedFactSource],
) -> tuple[RelationshipFacts, list[str]]:
    """Merge many fact payloads into one authoritative relationship payload."""

    conflicts: list[str] = []

    calls: dict[tuple[str, str], tuple[object, _LoadedFactSource]] = {}
    references: dict[tuple[str, str], tuple[object, _LoadedFactSource]] = {}
    events: dict[tuple[str, str, str], tuple[object, _LoadedFactSource]] = {}
    stores: dict[tuple[str, str, str], tuple[object, _LoadedFactSource]] = {}

    def choose_fact(
        selected: dict[tuple[str, ...], tuple[object, _LoadedFactSource]],
        key: tuple[str, ...],
        fact: object,
        incoming_source: _LoadedFactSource,
        fact_kind: str,
    ) -> None:
        existing = selected.get(key)
        if existing is None:
            selected[key] = (fact, incoming_source)
            return

        existing_fact, existing_source = existing
        if existing_fact == fact:
            return

        existing_rank = _source_rank(existing_source.source_kind)
        incoming_rank = _source_rank(incoming_source.source_kind)
        key_display = ", ".join(key)

        if incoming_rank > existing_rank:
            selected[key] = (fact, incoming_source)
            conflicts.append(
                f"{fact_kind} ({key_display}): chose {_source_label(incoming_source)} "
                f"over {_source_label(existing_source)}",
            )
            return

        conflicts.append(
            f"{fact_kind} ({key_display}): kept {_source_label(existing_source)} "
            f"over {_source_label(incoming_source)}",
        )

    for source in sources:
        for call in source.facts.calls:
            choose_fact(
                selected=calls,
                key=(call.caller_pin, call.callee_pin),
                fact=call,
                incoming_source=source,
                fact_kind="call",
            )
        for reference in source.facts.references:
            choose_fact(
                selected=references,
                key=(reference.referrer_pin, reference.referenced_id),
                fact=reference,
                incoming_source=source,
                fact_kind="reference",
            )
        for event in source.facts.events:
            choose_fact(
                selected=events,
                key=(event.emitter_pin, event.event_id, event.consumer_pin or ""),
                fact=event,
                incoming_source=source,
                fact_kind="event",
            )
        for store in source.facts.stores:
            choose_fact(
                selected=stores,
                key=(store.pin, store.store_id, store.access_type),
                fact=store,
                incoming_source=source,
                fact_kind="store",
            )

    merged = RelationshipFacts(
        calls=[fact for fact, _ in calls.values()],
        references=[fact for fact, _ in references.values()],
        events=[fact for fact, _ in events.values()],
        stores=[fact for fact, _ in stores.values()],
    )
    return merged, conflicts


def _facts_from_pin_registry(path: Path) -> RelationshipFacts:
    """Project pin registry data into relationship facts."""
    registry = PinFunctionRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    facts = RelationshipFacts()
    for edge in registry.import_edges:
        facts.references.append(
            ReferenceRelationshipFact(
                referrer_pin=edge.arch_location,
                referenced_id=edge.pin_func_id,
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


def _load_relationship_facts(path: Path) -> _LoadedFactSource:
    """Load one relationship-fact artifact file."""
    if path.name == "pin_registry.json":
        return _LoadedFactSource(
            facts=_facts_from_pin_registry(path),
            source_kind=_SOURCE_KIND_PIN_REGISTRY,
            source_path=path,
        )

    content = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(content, dict) and isinstance(content.get("relationship_facts"), dict):
        content = content["relationship_facts"]
    return _LoadedFactSource(
        facts=RelationshipFacts.model_validate(content),
        source_kind=_SOURCE_KIND_RELATIONSHIP_FACTS,
        source_path=path,
    )


def _candidate_spec_paths_from_root(root: Path) -> list[Path]:
    """Return markdown spec files for one root path."""
    if not root.exists():
        return []
    if root.is_file():
        return [root] if root.suffix.lower() == ".md" else []
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def _discover_spec_markdown_paths(config: AdjacencyAnalysisConfig) -> list[Path]:
    candidates: list[Path] = []
    for root in config.spec_dirs:
        candidates.extend(_candidate_spec_paths_from_root(root))

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _has_relationship_data(facts: RelationshipFacts) -> bool:
    return bool(facts.calls or facts.references or facts.events or facts.stores)


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
        loaded_facts.append(
            _LoadedFactSource(
                facts=config.relationship_facts,
                source_kind=_SOURCE_KIND_INLINE,
                source_path=None,
            )
        )

    merge_conflicts: list[str] = []
    if loaded_facts:
        relationship_facts, merge_conflicts = _merge_relationship_facts(loaded_facts)
    else:
        relationship_facts = RelationshipFacts()

    # Convert weight overrides from string keys to SignalType multipliers.
    weight_overrides: dict[SignalType, float] | None = None
    if config.weight_overrides:
        weight_overrides = {}
        signal_type_map = {st.value: st for st in SignalType}
        unknown_keys = sorted(set(config.weight_overrides) - set(signal_type_map))
        if unknown_keys:
            supported = ", ".join(sorted(signal_type_map))
            unknown = ", ".join(unknown_keys)
            raise ValueError(
                f"Unknown weight_overrides keys: {unknown}. Supported signal types: {supported}.",
            )

        for key, value in config.weight_overrides.items():
            try:
                multiplier = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid weight override for '{key}': expected numeric value, got {value!r}.",
                ) from exc
            weight_overrides[signal_type_map[key]] = multiplier

    unified = build_unified_graph(
        relationship_facts=relationship_facts,
        weight_overrides=weight_overrides,
    )

    spec_paths = _discover_spec_markdown_paths(config)
    cooccurrence_graph = (
        build_cooccurrence_verifier_graph(spec_paths) if spec_paths else AdjacencyGraph()
    )
    partial_graphs = {
        SignalType.CALL: unified.filter_by_signal_type({SignalType.CALL}),
        SignalType.REFERENCE: unified.filter_by_signal_type({SignalType.REFERENCE}),
        SignalType.EVENT: unified.filter_by_signal_type({SignalType.EVENT}),
        SignalType.STORE_TOUCH: unified.filter_by_signal_type({SignalType.STORE_TOUCH}),
        SignalType.CO_OCCURRENCE: cooccurrence_graph,
    }

    report = detect_disconnected_components(unified, partial_graphs=partial_graphs)
    if merge_conflicts:
        report.disconnected_warnings.insert(
            0,
            "Relationship fact merge resolved conflicting facts by source authority "
            f"({len(merge_conflicts)} conflicts).",
        )
        for conflict in merge_conflicts[:10]:
            report.disconnected_warnings.append(f"Merge detail: {conflict}")
        if len(merge_conflicts) > 10:
            report.disconnected_warnings.append(
                f"Merge detail: {len(merge_conflicts) - 10} additional conflicts omitted.",
            )

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
