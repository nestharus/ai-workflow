"""High-level orchestration for pin-function extraction, registration, and change tracking.

Uses ``analyze_source()`` from ``spec_manager.core.code_analysis`` for
function discovery instead of the removed ``ast_extractor`` and
``import_graph`` modules.
"""

from __future__ import annotations

import hashlib
import json
import re
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

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

# Regex patterns for import detection (inlined from deleted import_graph)
_IMPORT_RE = re.compile(r"^\s*import\s+(.+)", re.MULTILINE)
_FROM_IMPORT_RE = re.compile(r"^\s*from\s+(\S+)\s+import\s+(.+)", re.MULTILINE)


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

    def scan(self) -> PinFunctionRegistry:
        """Full scan: extract atoms, build import graph, produce registry.

        Scans the project root for atom functions, builds the import graph
        from architectural files, and creates a complete registry.

        Returns:
            PinFunctionRegistry with all discovered pin-functions and edges.
        """
        # Extract atom candidates from all configured directories
        all_candidates: list[_AtomCandidate] = []
        for atom_dir_name in self._config.atom_directories:
            atom_dir = self._project_root / atom_dir_name
            if atom_dir.is_dir():
                candidates = self._extract_from_directory(atom_dir)
                all_candidates.extend(candidates)

        # Also scan the project root for annotated functions
        root_candidates = self._extract_from_directory(self._project_root, recursive=True)
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
        for arch_dir_name in self._config.architectural_roots:
            arch_dir = self._project_root / arch_dir_name
            if arch_dir.is_dir():
                edges = self._build_graph(pin_functions, arch_dir)
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

    # --- Private: function extraction (replaces ast_extractor) ---

    def _extract_from_directory(
        self,
        dir_path: Path,
        recursive: bool = True,
    ) -> list[_AtomCandidate]:
        """Extract atom candidates from all source files in a directory."""
        candidates: list[_AtomCandidate] = []
        pattern = "**/*.py" if recursive else "*.py"
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
        annotated_functions = self._find_annotated_functions(source_lines)

        candidates: list[_AtomCandidate] = []
        for raw_func in analysis.functions:
            detection_method = self._classify_detection(
                raw_func.name,
                is_convention,
                annotated_functions,
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

    def _find_annotated_functions(self, source_lines: list[str]) -> set[str]:
        annotated: set[str] = set()
        marker = self._config.annotation_marker
        for i, line in enumerate(source_lines):
            stripped = line.strip()
            if stripped == marker or stripped.startswith(marker + " "):
                for j in range(i + 1, len(source_lines)):
                    next_line = source_lines[j].strip()
                    if not next_line or next_line.startswith("#") or next_line.startswith("@"):
                        continue
                    if next_line.startswith("def ") or next_line.startswith("async def "):
                        func_name = next_line.split("(")[0].split()[-1]
                        annotated.add(func_name)
                    break
        return annotated

    def _classify_detection(
        self,
        func_name: str,
        is_convention: bool,
        annotated_functions: set[str],
    ) -> str | None:
        if func_name.startswith("_"):
            if func_name in annotated_functions:
                return "annotation"
            return None
        if func_name in annotated_functions:
            return "annotation"
        if is_convention:
            return "convention"
        return "heuristic"

    # --- Private: import graph building (replaces import_graph) ---

    def _build_graph(
        self,
        pin_functions: list[PinFunction],
        arch_directory: Path,
    ) -> list[ImportEdge]:
        """Build import graph by scanning architectural files for pin-function imports."""
        pf_by_name: dict[str, PinFunction] = {pf.function_name: pf for pf in pin_functions}

        edges: list[ImportEdge] = []
        for py_file in sorted(arch_directory.rglob("*.py")):
            if not py_file.is_file():
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            imported = self._scan_imports(source)
            for _local_name, orig_name in imported.items():
                pf = pf_by_name.get(orig_name)
                if pf is None:
                    continue
                self._edge_counter += 1
                edge = ImportEdge(
                    edge_id=f"IMEDGE-{self._edge_counter:04d}",
                    pin_func_id=pf.pin_func_id,
                    arch_location=f"{py_file}:<module>",
                    arch_file_path=str(py_file),
                    arch_line=0,
                    projection_type=ProjectionType.PASS_THROUGH,
                    confidence=1.0,
                    is_direct_import=True,
                )
                edges.append(edge)

        return edges

    def _scan_imports(self, source: str) -> dict[str, str]:
        """Scan source for import statements, return {local_name: original_name}."""
        imported: dict[str, str] = {}

        for match in _FROM_IMPORT_RE.finditer(source):
            module = match.group(1)
            if not self._is_algorithmic_module(module):
                continue
            names_str = match.group(2).strip()
            for orig, alias in _parse_import_names(names_str):
                local = alias or orig
                imported[local] = orig

        for match in _IMPORT_RE.finditer(source):
            full_line = match.group(0).strip()
            if full_line.startswith("from "):
                continue
            names_str = match.group(1).strip()
            for orig, alias in _parse_import_names(names_str):
                if not self._is_algorithmic_module(orig):
                    continue
                local = alias or orig
                imported[local] = orig

        return imported

    def _is_algorithmic_module(self, module_name: str) -> bool:
        module_parts = module_name.split(".")
        return any(root in module_parts for root in self._config.algorithmic_roots)

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


def _parse_import_names(names_str: str) -> list[tuple[str, str | None]]:
    """Parse comma-separated import names, return [(original, alias_or_None)]."""
    cleaned = names_str.strip().strip("()")
    if "#" in cleaned:
        cleaned = cleaned[: cleaned.index("#")]

    result: list[tuple[str, str | None]] = []
    for part in cleaned.split(","):
        part = part.strip()
        if not part:
            continue
        as_match = re.match(r"(\S+)\s+as\s+(\S+)", part)
        if as_match:
            result.append((as_match.group(1), as_match.group(2)))
        else:
            name = part.strip()
            if name.isidentifier() or "." in name:
                result.append((name, None))
    return result


__all__ = [
    "PinFunctionConfig",
    "PinFunctionOrchestrator",
]
