"""High-level orchestration for pin-function extraction, registration, and change tracking.

Uses ``analyze_source()`` from ``spec_manager.core.code_analysis`` for
function discovery instead of the removed ``ast_extractor`` and
``import_graph`` modules.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import RawFunctionInfo, analyze_source
from spec_manager.core.pin_registry import PinRegistryIndex
from spec_manager.projection.pin_propagation import (
    PinChangePropagator,
    PropagationReport,
)
from spec_manager.schemas.pin_functions import (
    ImportEdge,
    PinFunction,
    PinFunctionRegistry,
    ProjectionType,
)


@dataclass
class PinFunctionConfig:
    """Configuration for the pin-function orchestrator."""

    atom_directories: list[str] = field(default_factory=lambda: ["atoms", "shapes"])
    algorithmic_roots: list[str] = field(default_factory=lambda: ["atoms", "shapes"])
    architectural_roots: list[str] = field(default_factory=lambda: ["services", "handlers"])
    registry_dir: str = ".spec"
    registry_filename: str = "pin_registry.json"
    max_function_lines: int = 30
    require_docstring: bool = True
    annotation_marker: str = "# @pin"
    exclude_patterns: list[str] = field(default_factory=lambda: ["test_", "_test", "conftest"])


class PinFunctionOrchestrator:
    """Orchestrates pin-function extraction, registration, and change tracking."""

    def __init__(
        self,
        project_root: Path,
        config: PinFunctionConfig | None = None,
    ) -> None:
        self._project_root = project_root
        self._config = config or PinFunctionConfig()
        self._edge_counter = 0

    @property
    def registry_path(self) -> Path:
        """Path to the pin-function registry file."""
        return self._project_root / self._config.registry_dir / self._config.registry_filename

    def scan(
        self,
        mode: str = "scan",
        pin_proposals: list[dict[str, Any]] | None = None,
        edge_proposals: list[dict[str, Any]] | None = None,
    ) -> PinFunctionRegistry:
        """Scan for pin-functions and merge LLM-sourced proposals.

        Scans the project root for atom functions via ``analyze_source()``
        (LLM-based).  Edges are exclusively LLM-sourced via proposals —
        filesystem scan no longer produces edges.

        Args:
            mode: One of ``"scan"`` (filesystem only), ``"proposals"``
                (proposals only), or ``"both"`` (merge both).
            pin_proposals: Pin proposals from the IMPLEMENT step (P9).
                Each dict should have at minimum ``function_name``,
                ``module_path``, ``file_path``.
            edge_proposals: Edge proposals from the IMPLEMENT step.
                Each dict should have ``pin_func_id``, ``arch_file_path``,
                ``arch_location``, ``projection_type``.

        Returns:
            PinFunctionRegistry with all discovered pin-functions and edges.
        """
        pin_functions: list[PinFunction] = []
        import_edges: list[ImportEdge] = []

        # Phase 1: Filesystem scan — pins only, NO edges
        if mode in ("scan", "both"):
            all_candidates: list[_AtomCandidate] = []
            for atom_dir_name in self._config.atom_directories:
                atom_dir = self._project_root / atom_dir_name
                if atom_dir.is_dir():
                    candidates = self._extract_from_directory(atom_dir)
                    all_candidates.extend(candidates)

            root_candidates = self._extract_from_directory(self._project_root, recursive=True)
            seen_keys: set[str] = {f"{c.file_path}:{c.function_name}" for c in all_candidates}
            for c in root_candidates:
                key = f"{c.file_path}:{c.function_name}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_candidates.append(c)

            pin_functions = self._candidates_to_pin_functions(all_candidates)

        # Phase 2: Merge proposals (mode="proposals" or "both")
        if mode in ("proposals", "both"):
            proposed_pins, proposed_edges = self._merge_proposals(
                pin_functions, pin_proposals or [], edge_proposals or []
            )
            pin_functions = proposed_pins
            import_edges.extend(proposed_edges)

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

    # --- Private: proposal merging ---

    def _merge_proposals(
        self,
        existing_pins: list[PinFunction],
        pin_proposals: list[dict[str, Any]],
        edge_proposals: list[dict[str, Any]],
    ) -> tuple[list[PinFunction], list[ImportEdge]]:
        """Merge P9 proposals into the scanned pin functions.

        Pin proposals that match existing functions by name+file are
        skipped (scan wins). New proposals get IDs allocated.

        Returns:
            (merged_pin_functions, new_edges)
        """
        existing_keys = {(pf.function_name, pf.file_path) for pf in existing_pins}
        merged = list(existing_pins)
        next_id = len(merged) + 1

        for proposal in pin_proposals:
            key = (proposal.get("function_name", ""), proposal.get("file_path", ""))
            if key in existing_keys:
                continue
            existing_keys.add(key)

            pf = PinFunction(
                pin_func_id=proposal.get("pin_func_id", f"PFUNC-P-{next_id:04d}"),
                function_name=proposal.get("function_name", ""),
                module_path=proposal.get("module_path", ""),
                file_path=proposal.get("file_path", ""),
                line_start=proposal.get("line_start", 0),
                line_end=proposal.get("line_end", 0),
                signature=proposal.get("signature", ""),
                docstring=proposal.get("docstring", ""),
                content_hash=proposal.get("content_hash", ""),
                is_shape=proposal.get("is_shape", False),
                store_touches=proposal.get("store_touches", []),
                evidence_atom_ids=proposal.get("evidence_atom_ids", []),
            )
            merged.append(pf)
            next_id += 1

        new_edges: list[ImportEdge] = []
        for proposal in edge_proposals:
            self._edge_counter += 1
            edge = ImportEdge(
                edge_id=proposal.get("edge_id", f"IMEDGE-P-{self._edge_counter:04d}"),
                pin_func_id=proposal.get("pin_func_id", ""),
                arch_location=proposal.get("arch_location", ""),
                arch_file_path=proposal.get("arch_file_path", ""),
                arch_line=proposal.get("arch_line", 0),
                projection_type=proposal.get("projection_type", ProjectionType.PASS_THROUGH),
                confidence=proposal.get("confidence", 0.8),
                is_direct_import=proposal.get("is_direct_import", True),
            )
            new_edges.append(edge)

        return merged, new_edges

    # --- Private: function extraction (replaces ast_extractor) ---

    def _extract_from_directory(
        self,
        dir_path: Path,
        recursive: bool = True,
    ) -> list[_AtomCandidate]:
        """Extract atom candidates from all source files in a directory."""
        from spec_manager.core.language import SOURCE_GLOBS, SOURCE_RGLOBS

        candidates: list[_AtomCandidate] = []
        patterns = SOURCE_RGLOBS if recursive else SOURCE_GLOBS
        for pattern in patterns:
            for py_file in sorted(dir_path.glob(pattern)):
                if py_file.is_file():
                    candidates.extend(self._extract_from_file(py_file, dir_path))
        return candidates

    def _extract_from_file(
        self,
        file_path: Path,
        scan_root: Path | None = None,
    ) -> list[_AtomCandidate]:
        """Extract atom candidates from a single source file using analyze_source."""
        file_name = file_path.stem
        for pat in self._config.exclude_patterns:
            if pat in file_name:
                return []

        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

        analysis = analyze_source(source, str(file_path))
        if not analysis.functions:
            return []

        module_path = self._file_to_module(file_path)
        is_convention = self._is_convention_directory(file_path)
        is_shapes_dir = "shapes" in [p.lower() for p in file_path.parts]
        source_lines = source.splitlines()

        candidates: list[_AtomCandidate] = []
        for raw_func in analysis.functions:
            detection_method = self._classify_detection(
                raw_func.name,
                is_convention,
            )
            if detection_method is None:
                continue

            docstring = ""
            if raw_func.docstring:
                docstring = raw_func.docstring.split("\n")[0].strip()

            if detection_method == "heuristic" and self._config.require_docstring and not docstring:
                continue

            body_lines = raw_func.end_line - raw_func.start_line + 1
            if detection_method == "heuristic" and body_lines > self._config.max_function_lines:
                continue

            body_source = "\n".join(source_lines[raw_func.start_line - 1 : raw_func.end_line])
            signature = _reconstruct_signature(raw_func)
            qualified_name = f"{module_path}.{raw_func.qualified_name}"

            candidates.append(
                _AtomCandidate(
                    function_name=raw_func.name,
                    qualified_name=qualified_name,
                    file_path=str(file_path),
                    module_path=module_path,
                    line_start=raw_func.start_line,
                    line_end=raw_func.end_line,
                    signature=signature,
                    docstring=docstring,
                    body_source=body_source,
                    is_shape=is_shapes_dir,
                    detection_method=detection_method,
                )
            )
        return candidates

    def _file_to_module(self, file_path: Path) -> str:
        parts = list(file_path.with_suffix("").parts)
        while parts and parts[0] in (".", ".."):
            parts.pop(0)
        return ".".join(parts)

    def _is_convention_directory(self, file_path: Path) -> bool:
        path_parts = [p.lower() for p in file_path.parts]
        return any(d.lower() in path_parts for d in self._config.atom_directories)

    def _classify_detection(
        self,
        func_name: str,
        is_convention: bool,
    ) -> str | None:
        """Classify how a function was detected as a pin candidate.

        Public functions in convention directories are candidates.
        Private functions (``_``-prefixed) are excluded.
        Public functions outside convention directories use heuristic rules.
        """
        from spec_manager.core.language import PRIVATE_PREFIX

        if func_name.startswith(PRIVATE_PREFIX):
            return None
        if is_convention:
            return "convention"
        return "heuristic"

    # --- Private: conversion ---

    def _candidates_to_pin_functions(self, candidates: list[_AtomCandidate]) -> list[PinFunction]:
        """Convert _AtomCandidate objects to PinFunction schemas."""
        pin_functions: list[PinFunction] = []
        for i, candidate in enumerate(candidates, start=1):
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
                store_touches=[],
                evidence_atom_ids=[],
            )
            pin_functions.append(pf)

        return pin_functions


# --- Module-level helpers ---


@dataclass
class _AtomCandidate:
    """A function identified as a potential pin-function atom (internal)."""

    function_name: str
    qualified_name: str
    file_path: str
    module_path: str
    line_start: int
    line_end: int
    signature: str
    docstring: str
    body_source: str
    is_shape: bool
    detection_method: str


def _reconstruct_signature(func: RawFunctionInfo) -> str:
    sig = f"({', '.join(func.args)})"
    if func.return_annotation:
        sig += f" -> {func.return_annotation}"
    return sig


__all__ = [
    "PinFunctionConfig",
    "PinFunctionOrchestrator",
]
