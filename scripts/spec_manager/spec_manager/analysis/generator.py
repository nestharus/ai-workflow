"""Analysis file generator -- orchestrates all analysis components.

This is the main entry point. It composes the import scanner,
projection classifier, adjacency builder, and data flow extractor
into a single computed artifact.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spec_manager.analysis.adjacency.adapters import (
    cooccurrence_from_atom_sections,
    graph_to_atom_adjacency,
    store_touch_from_definitions,
)
from spec_manager.analysis.adjacency.detector import build_unified_graph
from spec_manager.analysis.data_flow import extract_all_data_flows
from spec_manager.analysis.import_scanner import (
    build_atom_registry,
    scan_directory_imports,
)
from spec_manager.analysis.projection_classifier import (
    classify_all_imports,
    detect_introductions,
)
from spec_manager.schemas.lineage import (
    AnalysisFileSchema,
    AtomAnalysisEntry,
    OrphanedArchEntry,
)

logger = logging.getLogger(__name__)


def generate_analysis_file(
    algorithmic_dir: Path,
    architectural_dir: Path,
    atom_to_section: dict[str, dict[str, str]] | None = None,
    store_definitions: dict[str, list[str]] | None = None,
    run_id: str = "",
) -> AnalysisFileSchema:
    """Generate the complete analysis file artifact.

    This is the core function. It:
    1. Builds the atom registry from algorithmic sources
    2. Scans architectural sources for atom imports
    3. Classifies each import as pass-through/wrap/smear
    4. Detects introductions (architectural code with no atom source)
    5. Builds adjacency graph (co-occurrence + store-touch)
    6. Extracts data flow summaries
    7. Flags unimplemented atoms (no architectural imports)
    8. Assembles everything into AnalysisFileSchema

    Args:
        algorithmic_dir: Root of algorithmic layer source files.
        architectural_dir: Root of architectural layer source files.
        atom_to_section: Optional pre-built atom-to-section index.
        store_definitions: Optional store-to-atoms mapping.
        run_id: Run identifier for the artifact.

    Returns:
        Complete AnalysisFileSchema artifact.
    """
    # 1. Build atom registry.
    atom_registry = build_atom_registry(algorithmic_dir)
    atom_names = set(atom_registry.keys())
    logger.info("Atom registry: %d atoms from %s", len(atom_names), algorithmic_dir)

    # 2. Scan architectural sources.
    hits = scan_directory_imports(architectural_dir, atom_names)
    logger.info("Import hits: %d from %s", len(hits), architectural_dir)

    # 3. Classify imports.
    arch_sources: dict[str, str] = {}
    if architectural_dir.exists():
        for py_file in architectural_dir.rglob("*.py"):
            try:
                arch_sources[str(py_file)] = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

    lineage_edges = classify_all_imports(hits, arch_sources, atom_names)

    # 4. Detect introductions.
    arch_files = sorted(arch_sources.keys())
    introduction_files = detect_introductions(arch_files, lineage_edges)

    # 5. Build adjacency graph.
    cooccurrence_graph = cooccurrence_from_atom_sections(atom_to_section or {})
    store_graph = (
        store_touch_from_definitions(atom_registry, store_definitions)
        if store_definitions
        else None
    )
    unified = build_unified_graph(
        cooccurrence_graph=cooccurrence_graph,
        store_graph=store_graph,
    )
    all_atom_ids = (
        set(atom_to_section.keys()) | set(atom_registry.keys())
        if atom_to_section
        else set(atom_registry.keys())
    )
    adjacency_map = graph_to_atom_adjacency(unified, all_atom_ids)

    # 6. Extract data flow summaries.
    data_flows = extract_all_data_flows(atom_registry, store_definitions)

    # 7. Assemble per-atom entries.
    # Group lineage edges by atom.
    edges_by_atom: dict[str, list[Any]] = {}
    for edge in lineage_edges:
        edges_by_atom.setdefault(edge.from_atom, []).append(edge)

    atoms: list[AtomAnalysisEntry] = []
    for atom_name in sorted(atom_registry.keys()):
        meta = atom_registry[atom_name]
        forward_traces = edges_by_atom.get(atom_name, [])
        is_unimplemented = len(forward_traces) == 0

        entry = AtomAnalysisEntry(
            atom_id=atom_name,
            atom_file=meta["file"],
            forward_traces=forward_traces,
            adjacency=adjacency_map.get(atom_name),
            data_flow=data_flows.get(atom_name),
            is_unimplemented=is_unimplemented,
        )
        atoms.append(entry)

    # 8. Build orphaned architecture entries.
    orphaned: list[OrphanedArchEntry] = []
    for intro_file in introduction_files:
        orphaned.append(
            OrphanedArchEntry(
                location=intro_file,
                description="Architectural file with no atom imports",
                suggested_action="investigate",
            )
        )

    # Compute summary statistics.
    total_atoms = len(atoms)
    implemented = sum(1 for a in atoms if not a.is_unimplemented)
    unimplemented = total_atoms - implemented
    pass_through_count = sum(
        1 for e in lineage_edges if e.transformation == "pass_through"
    )
    wrap_count = sum(1 for e in lineage_edges if e.transformation == "wrap")
    smear_count = sum(1 for e in lineage_edges if e.transformation == "smear")
    introduction_count = len(orphaned)

    summary: dict[str, int | float] = {
        "total_atoms": total_atoms,
        "implemented_atoms": implemented,
        "unimplemented_atoms": unimplemented,
        "orphaned_architecture": introduction_count,
        "pass_through_imports": pass_through_count,
        "wrap_imports": wrap_count,
        "smear_imports": smear_count,
        "total_lineage_edges": len(lineage_edges),
    }

    generated_at = datetime.now(timezone.utc).isoformat()

    return AnalysisFileSchema(
        run_id=run_id,
        generated_at=generated_at,
        atoms=atoms,
        orphaned_architecture=orphaned,
        summary=summary,
    )


def write_analysis_json(
    analysis: AnalysisFileSchema,
    output_path: Path,
) -> None:
    """Write analysis artifact as JSON.

    Args:
        analysis: The analysis schema to serialize.
        output_path: Destination file path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(analysis.model_dump(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_analysis_json(input_path: Path) -> AnalysisFileSchema:
    """Read and validate an analysis artifact.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated AnalysisFileSchema.
    """
    content = input_path.read_text(encoding="utf-8")
    return AnalysisFileSchema.model_validate(json.loads(content))
