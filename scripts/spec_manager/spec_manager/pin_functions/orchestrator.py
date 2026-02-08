"""High-level orchestration for pin-function extraction, registration, and change tracking.

Ties together the AST extractor, import graph builder, and change propagation
engine into user-facing operations.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from spec_manager.analysis.ast_extractor import (
    AtomCandidate,
    AtomFunctionExtractor,
    ExtractionConfig,
)
from spec_manager.analysis.import_graph import (
    ImportGraphBuilder,
    ImportGraphConfig,
)
from spec_manager.core.pin_registry import PinRegistryIndex
from spec_manager.projection.pin_propagation import (
    PinChangePropagator,
    PropagationReport,
)
from spec_manager.schemas.pin_functions import (
    ImportEdge,
    PinFunction,
    PinFunctionRegistry,
)


@dataclass
class PinFunctionConfig:
    """Configuration for the pin-function orchestrator."""

    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    import_graph: ImportGraphConfig = field(default_factory=ImportGraphConfig)
    registry_dir: str = ".spec"
    registry_filename: str = "pin_registry.json"


class PinFunctionOrchestrator:
    """Orchestrates pin-function extraction, registration, and change tracking."""

    def __init__(
        self,
        project_root: Path,
        config: PinFunctionConfig | None = None,
    ) -> None:
        self._project_root = project_root
        self._config = config or PinFunctionConfig()
        self._extractor = AtomFunctionExtractor(self._config.extraction)
        self._graph_builder = ImportGraphBuilder(self._config.import_graph)

    @property
    def registry_path(self) -> Path:
        """Path to the pin-function registry file."""
        return self._project_root / self._config.registry_dir / self._config.registry_filename

    def scan(self) -> PinFunctionRegistry:
        """Full scan: extract atoms, build import graph, produce registry.

        Scans the project root for atom functions, builds the import graph
        from architectural files, and creates a complete registry.

        Returns:
            PinFunctionRegistry with all discovered pin-functions and edges.
        """
        # Extract atom candidates from all configured directories
        all_candidates: list[AtomCandidate] = []
        for atom_dir_name in self._config.extraction.atom_directories:
            atom_dir = self._project_root / atom_dir_name
            if atom_dir.is_dir():
                candidates = self._extractor.extract_from_directory(atom_dir)
                all_candidates.extend(candidates)

        # Also scan the project root for annotated functions
        root_candidates = self._extractor.extract_from_directory(self._project_root, recursive=True)
        # Avoid duplicates
        seen_keys: set[str] = {f"{c.file_path}:{c.function_name}" for c in all_candidates}
        for c in root_candidates:
            key = f"{c.file_path}:{c.function_name}"
            if key not in seen_keys:
                seen_keys.add(key)
                all_candidates.append(c)

        # Convert candidates to PinFunction schemas
        pin_functions = self._candidates_to_pin_functions(all_candidates)

        # Build import graph from architectural directories
        import_edges: list[ImportEdge] = []
        for arch_dir_name in self._config.import_graph.architectural_roots:
            arch_dir = self._project_root / arch_dir_name
            if arch_dir.is_dir():
                edges = self._graph_builder.build_graph(pin_functions, arch_dir)
                import_edges.extend(edges)

        registry = PinFunctionRegistry(
            schema_version="1.0",
            pin_functions=pin_functions,
            import_edges=import_edges,
            created_at=datetime.now(UTC).isoformat(),
        )

        return registry

    def diff(self, old_registry_path: Path) -> PropagationReport:
        """Compare current state to previous registry and report changes.

        Args:
            old_registry_path: Path to the previous registry JSON file.

        Returns:
            PropagationReport with all changes and affected locations.
        """
        # Load old registry
        old_data = json.loads(old_registry_path.read_text(encoding="utf-8"))
        old_registry = PinFunctionRegistry.model_validate(old_data)

        # Scan current state
        new_registry = self.scan()

        # Build index from new registry for propagation
        index = PinRegistryIndex.from_registry(new_registry)
        propagator = PinChangePropagator(index)

        # Detect changes
        changes = propagator.detect_changes(old_registry, new_registry)

        # Propagate changes
        return propagator.propagate(changes)

    def query_importers(self, function_name: str) -> list[ImportEdge]:
        """Query which architectural locations import a given function.

        Args:
            function_name: The function name to look up.

        Returns:
            List of ImportEdge objects for all importing locations.
        """
        registry = self.scan()
        index = PinRegistryIndex.from_registry(registry)

        pf = index.get_by_name(function_name)
        if pf is None:
            return []

        return index.get_importers(pf.pin_func_id)

    def query_pin_functions_for(self, arch_file: str) -> list[PinFunction]:
        """Query which pin-functions a given architectural file uses.

        Args:
            arch_file: Path to the architectural file.

        Returns:
            List of PinFunction objects used by the file.
        """
        registry = self.scan()
        index = PinRegistryIndex.from_registry(registry)

        # Find all edges that reference this architectural file
        result: list[PinFunction] = []
        seen: set[str] = set()
        for edge in registry.import_edges:
            if edge.arch_file_path == arch_file and edge.pin_func_id not in seen:
                seen.add(edge.pin_func_id)
                pf = index.get_by_id(edge.pin_func_id)
                if pf is not None:
                    result.append(pf)

        return result

    def save_registry(self, registry: PinFunctionRegistry) -> Path:
        """Save a registry to disk.

        Args:
            registry: The registry to save.

        Returns:
            Path where the registry was saved.
        """
        registry_dir = self._project_root / self._config.registry_dir
        registry_dir.mkdir(parents=True, exist_ok=True)

        path = registry_dir / self._config.registry_filename
        path.write_text(
            registry.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return path

    def generate_analysis_file(self) -> str:
        """Generate the computed analysis artifact.

        Returns:
            Markdown string with the analysis report.
        """
        registry = self.scan()
        index = PinRegistryIndex.from_registry(registry)

        lines: list[str] = []
        lines.append("# Pin-Function Analysis Report")
        lines.append("")
        lines.append(f"Generated: {datetime.now(UTC).isoformat()}")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Total pin-functions: {len(registry.pin_functions)}")
        lines.append(f"- Total import edges: {len(registry.import_edges)}")

        shape_count = sum(1 for pf in registry.pin_functions if pf.is_shape)
        lines.append(f"- Shape functions (pure): {shape_count}")
        lines.append(f"- Impure functions: {len(registry.pin_functions) - shape_count}")
        lines.append("")

        # Pin-functions
        lines.append("## Pin-Functions")
        lines.append("")
        for pf in registry.pin_functions:
            shape_tag = " [SHAPE]" if pf.is_shape else ""
            lines.append(f"### {pf.function_name}{shape_tag}")
            lines.append(f"- ID: {pf.pin_func_id}")
            lines.append(f"- Module: {pf.module_path}")
            lines.append(f"- File: {pf.file_path}")
            lines.append(f"- Lines: {pf.line_start}-{pf.line_end}")
            lines.append(f"- Signature: `{pf.signature}`")
            if pf.docstring:
                lines.append(f"- Docstring: {pf.docstring}")
            importers = index.get_importers(pf.pin_func_id)
            if importers:
                lines.append(f"- Importers ({len(importers)}):")
                for edge in importers:
                    lines.append(f"  - {edge.arch_location} ({edge.projection_type})")
            lines.append("")

        # Projection type distribution
        lines.append("## Projection Type Distribution")
        lines.append("")
        type_counts: dict[str, int] = {}
        for edge in registry.import_edges:
            type_counts[edge.projection_type] = type_counts.get(edge.projection_type, 0) + 1
        for pt, count in sorted(type_counts.items()):
            lines.append(f"- {pt}: {count}")
        lines.append("")

        return "\n".join(lines)

    # --- Private helpers ---

    def _candidates_to_pin_functions(self, candidates: list[AtomCandidate]) -> list[PinFunction]:
        """Convert AtomCandidate objects to PinFunction schemas.

        Args:
            candidates: List of extracted atom candidates.

        Returns:
            List of PinFunction schema objects.
        """
        pin_functions: list[PinFunction] = []

        for i, candidate in enumerate(candidates, start=1):
            # Compute content hash from body source
            body_text = textwrap.dedent(candidate.body_source).strip()
            content_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()

            pf = PinFunction(
                pin_func_id=f"PFUNC-{i:04d}",
                function_name=candidate.function_name,
                module_path=candidate.module_path,
                file_path=candidate.file_path,
                line_start=candidate.line_start,
                line_end=candidate.line_end,
                signature=candidate.signature,
                docstring=candidate.docstring,
                content_hash=content_hash,
                is_shape=candidate.is_shape,
                store_touches=candidate.store_references,
                evidence_atom_ids=[],
            )
            pin_functions.append(pf)

        return pin_functions


__all__ = [
    "PinFunctionConfig",
    "PinFunctionOrchestrator",
]
