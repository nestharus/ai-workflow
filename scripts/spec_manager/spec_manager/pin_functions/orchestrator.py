"""High-level orchestration for pin-function proposal materialization.

Pins and projection edges are sourced from IMPLEMENT-step proposals.
This module verifies and normalizes those proposals into PinFunctionRegistry.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

    algorithmic_roots: list[str] = field(default_factory=lambda: ["atoms", "shapes"])
    architectural_roots: list[str] = field(default_factory=lambda: ["services", "handlers"])
    registry_dir: str = ".spec"
    registry_filename: str = "pin_registry.json"


class PinFunctionOrchestrator:
    """Orchestrates proposal verification, registration, and change tracking."""

    def __init__(
        self,
        project_root: Path,
        config: PinFunctionConfig | None = None,
    ) -> None:
        self._project_root = project_root
        self._config = config or PinFunctionConfig()

    @property
    def registry_path(self) -> Path:
        """Path to the pin-function registry file."""
        return self._project_root / self._config.registry_dir / self._config.registry_filename

    @property
    def previous_registry_path(self) -> Path:
        """Path to the previous pin-function registry snapshot."""
        path = self.registry_path
        return path.with_name(f"{path.stem}.previous{path.suffix}")

    def scan(
        self,
        *,
        pin_proposals: list[dict[str, Any]] | None = None,
        edge_proposals: list[dict[str, Any]] | None = None,
        pin_proposals_path: str | Path | None = None,
        edge_proposals_path: str | Path | None = None,
        changed_files: list[str] | None = None,
    ) -> PinFunctionRegistry:
        """Build the pin registry from verified proposals.

        Args:
            pin_proposals: Pin proposals from IMPLEMENT output.
            edge_proposals: Edge proposals from IMPLEMENT output.
            pin_proposals_path: Optional JSON file path containing pin proposals.
            edge_proposals_path: Optional JSON file path containing edge proposals.
            changed_files: Optional changed-file list used for proposal diff-coverage verification.

        Returns:
            PinFunctionRegistry with all materialized pin-functions and edges.
        """
        loaded_pin_proposals = self._load_proposals(pin_proposals_path)
        loaded_edge_proposals = self._load_proposals(edge_proposals_path)

        existing_registry = self.load_registry() if self.registry_path.exists() else None
        existing_pins = existing_registry.pin_functions if existing_registry is not None else []
        existing_edges = existing_registry.import_edges if existing_registry is not None else []

        merged_pins, import_edges = self._merge_proposals(
            existing_pins=existing_pins,
            existing_edges=existing_edges,
            pin_proposals=loaded_pin_proposals + (pin_proposals or []),
            edge_proposals=loaded_edge_proposals + (edge_proposals or []),
            changed_files=changed_files,
        )

        return PinFunctionRegistry(
            schema_version="1.0",
            pin_functions=merged_pins,
            import_edges=import_edges,
            created_at=datetime.now(UTC).isoformat(),
        )

    def load_registry(self) -> PinFunctionRegistry:
        """Load the persisted pin registry from disk."""
        path = self.registry_path
        if not path.exists():
            raise FileNotFoundError(
                f"Pin registry not found at {path}. "
                "Promotion must materialize the registry before query/diff/report operations."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return PinFunctionRegistry.model_validate(data)

    @staticmethod
    def _load_proposals(path: str | Path | None) -> list[dict[str, Any]]:
        """Load proposal payloads from a JSON file path.

        Raises when the path is present but unreadable or invalid.
        """
        if path is None:
            return []

        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"Failed to read proposal file {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Proposal file {path} is not valid JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise TypeError(f"Proposal file {path} must contain a JSON list")

        result: list[dict[str, Any]] = []
        for idx, item in enumerate(payload):
            if not isinstance(item, dict):
                raise TypeError(f"Proposal file {path} has non-object entry at index {idx}")
            result.append(item)
        return result

    def diff(self, old_registry_path: Path) -> PropagationReport:
        """Compare current state to previous registry and report changes."""
        old_data = json.loads(old_registry_path.read_text(encoding="utf-8"))
        old_registry = PinFunctionRegistry.model_validate(old_data)

        new_registry = self.load_registry()

        index = PinRegistryIndex.from_registry(new_registry)
        propagator = PinChangePropagator(index)

        changes = propagator.detect_changes(old_registry, new_registry)
        return propagator.propagate(changes)

    def query_importers(self, function_name: str) -> list[ImportEdge]:
        """Query which architectural locations import a given function."""
        registry = self.load_registry()
        index = PinRegistryIndex.from_registry(registry)

        pf = index.get_by_name(function_name)
        if pf is None:
            return []

        return index.get_importers(pf.pin_func_id)

    def query_pin_functions_for(self, arch_file: str) -> list[PinFunction]:
        """Query which pin-functions a given architectural file uses."""
        registry = self.load_registry()
        index = PinRegistryIndex.from_registry(registry)
        normalized_arch_file = self._normalize_project_relative_path(arch_file)

        result: list[PinFunction] = []
        seen: set[str] = set()
        for edge in registry.import_edges:
            if edge.arch_file_path == normalized_arch_file and edge.pin_func_id not in seen:
                seen.add(edge.pin_func_id)
                pf = index.get_by_id(edge.pin_func_id)
                if pf is not None:
                    result.append(pf)

        return result

    def save_registry(self, registry: PinFunctionRegistry) -> Path:
        """Save a registry to disk."""
        registry_dir = self._project_root / self._config.registry_dir
        registry_dir.mkdir(parents=True, exist_ok=True)

        path = registry_dir / self._config.registry_filename
        previous_path = self.previous_registry_path
        if path.exists():
            path.replace(previous_path)
        path.write_text(
            registry.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return path

    def generate_analysis_file(self) -> str:
        """Generate the computed analysis artifact."""
        registry = self.load_registry()
        index = PinRegistryIndex.from_registry(registry)

        lines: list[str] = []
        lines.append("# Pin-Function Analysis Report")
        lines.append("")
        lines.append(f"Generated: {datetime.now(UTC).isoformat()}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Total pin-functions: {len(registry.pin_functions)}")
        lines.append(f"- Total import edges: {len(registry.import_edges)}")

        shape_count = sum(1 for pf in registry.pin_functions if pf.is_shape)
        lines.append(f"- Shape functions (pure): {shape_count}")
        lines.append(f"- Impure functions: {len(registry.pin_functions) - shape_count}")
        lines.append("")

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

        lines.append("## Projection Type Distribution")
        lines.append("")
        type_counts: dict[str, int] = {}
        for edge in registry.import_edges:
            key = str(edge.projection_type)
            type_counts[key] = type_counts.get(key, 0) + 1
        for pt, count in sorted(type_counts.items()):
            lines.append(f"- {pt}: {count}")
        lines.append("")

        return "\n".join(lines)

    def _merge_proposals(
        self,
        existing_pins: list[PinFunction],
        existing_edges: list[ImportEdge],
        pin_proposals: list[dict[str, Any]],
        edge_proposals: list[dict[str, Any]],
        *,
        changed_files: list[str] | None = None,
    ) -> tuple[list[PinFunction], list[ImportEdge]]:
        """Materialize verified proposals into registry schemas."""
        existing_by_key = {(pf.function_name, pf.file_path): pf for pf in existing_pins}
        used_pin_ids: set[str] = {pf.pin_func_id for pf in existing_pins}
        merged_by_key: dict[tuple[str, str], PinFunction] = dict(existing_by_key)
        proposed_by_key: dict[tuple[str, str], PinFunction] = {}
        merged_edges_by_id: dict[str, ImportEdge] = {edge.edge_id: edge for edge in existing_edges}

        next_pin_seq = self._next_pin_sequence(used_pin_ids)
        normalized_pin_proposals = self._verify_pin_proposals(pin_proposals)

        for proposal in normalized_pin_proposals:
            key = (proposal["function_name"], proposal["file_path"])
            proposed_pin_id = proposal["pin_func_id"]

            if not proposed_pin_id:
                existing = existing_by_key.get(key)
                if existing is not None:
                    proposed_pin_id = existing.pin_func_id
                else:
                    proposed_pin_id = f"PFUNC-P-{next_pin_seq:04d}"
                    next_pin_seq += 1

            conflicting_key = next(
                (
                    existing_key
                    for existing_key, pin in merged_by_key.items()
                    if pin.pin_func_id == proposed_pin_id and existing_key != key
                ),
                None,
            )
            if conflicting_key is not None:
                raise ValueError(
                    "pin_proposals contain duplicate pin_func_id for different functions: "
                    f"{proposed_pin_id}"
                )

            used_pin_ids.add(proposed_pin_id)
            pin = PinFunction(
                pin_func_id=proposed_pin_id,
                function_name=proposal["function_name"],
                module_path=proposal["module_path"],
                file_path=proposal["file_path"],
                line_start=proposal["line_start"],
                line_end=proposal["line_end"],
                signature=proposal["signature"],
                docstring=proposal["docstring"],
                content_hash=proposal["content_hash"],
                is_shape=proposal["is_shape"],
                store_touches=proposal["store_touches"],
                evidence_atom_ids=proposal["evidence_atom_ids"],
            )
            merged_by_key[key] = pin
            proposed_by_key[key] = pin

        merged_pins = list(merged_by_key.values())
        pin_ids = {pin.pin_func_id for pin in merged_pins}
        new_edges = self._verify_edge_proposals(
            edge_proposals=edge_proposals,
            pin_ids=pin_ids,
            existing_edge_ids=set(merged_edges_by_id),
        )
        self._verify_diff_coverage(list(proposed_by_key.values()), new_edges, changed_files)
        for edge in new_edges:
            merged_edges_by_id[edge.edge_id] = edge

        merged_edges = list(merged_edges_by_id.values())
        dangling_edge_ids = sorted(
            edge.edge_id for edge in merged_edges if edge.pin_func_id not in pin_ids
        )
        if dangling_edge_ids:
            raise ValueError(
                "Pin registry contains edges targeting missing pin_func_id values: "
                + ", ".join(dangling_edge_ids)
            )

        return merged_pins, merged_edges

    def _next_pin_sequence(self, used_pin_ids: set[str]) -> int:
        highest = 0
        for pin_id in used_pin_ids:
            if pin_id.startswith("PFUNC-P-"):
                suffix = pin_id.removeprefix("PFUNC-P-")
            elif pin_id.startswith("PFUNC-"):
                suffix = pin_id.removeprefix("PFUNC-")
            else:
                continue
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return highest + 1

    def _verify_pin_proposals(self, pin_proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen_keys: set[tuple[str, str]] = set()
        verified: list[dict[str, Any]] = []

        for idx, proposal in enumerate(pin_proposals):
            function_name = str(proposal.get("function_name", "")).strip()
            if not function_name:
                raise ValueError(f"pin_proposals[{idx}] missing function_name")

            file_path = self._normalize_project_relative_path(proposal.get("file_path", ""))
            if not file_path:
                raise ValueError(f"pin_proposals[{idx}] missing file_path")

            module_path = str(proposal.get("module_path", "")).strip()
            if not module_path:
                module_path = self._file_to_module(self._project_root / file_path)
            if not module_path:
                raise ValueError(f"pin_proposals[{idx}] missing module_path for {function_name}")

            line_start = self._coerce_positive_int(
                proposal.get("line_start"), field="line_start", idx=idx
            )
            line_end = self._coerce_positive_int(
                proposal.get("line_end"), field="line_end", idx=idx
            )
            if line_end < line_start:
                raise ValueError(
                    f"pin_proposals[{idx}] has invalid span: "
                    f"line_end ({line_end}) < line_start ({line_start})"
                )

            source_file = self._project_root / file_path
            if not source_file.exists() or not source_file.is_file():
                raise ValueError(f"pin_proposals[{idx}] points to missing source file: {file_path}")
            try:
                source_lines = source_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                raise ValueError(
                    f"pin_proposals[{idx}] cannot read source file {file_path}: {exc}"
                ) from exc
            if line_end > len(source_lines):
                raise ValueError(
                    f"pin_proposals[{idx}] span {line_start}-{line_end} exceeds file length "
                    f"({len(source_lines)}) for {file_path}"
                )

            anchor_window_start = max(line_start - 2, 1)
            anchor_window_end = min(line_start + 2, len(source_lines))
            anchor_window = "\n".join(
                source_lines[anchor_window_start - 1 : anchor_window_end]
            ).lower()
            if function_name.lower() not in anchor_window:
                raise ValueError(
                    f"pin_proposals[{idx}] anchor mismatch for {function_name} "
                    f"at {file_path}:{line_start}"
                )

            span_source = "\n".join(source_lines[line_start - 1 : line_end])
            canonical_hash = hashlib.sha256(
                textwrap.dedent(span_source).strip().encode("utf-8")
            ).hexdigest()
            proposal_hash = str(proposal.get("content_hash", "")).strip()
            if proposal_hash and proposal_hash != canonical_hash:
                raise ValueError(
                    f"pin_proposals[{idx}] has stale content_hash for {function_name} "
                    f"in {file_path}"
                )

            key = (function_name, file_path)
            if key in seen_keys:
                raise ValueError(
                    f"pin_proposals contains duplicate function/file entry: "
                    f"{function_name} @ {file_path}"
                )
            seen_keys.add(key)

            verified.append(
                {
                    "pin_func_id": str(proposal.get("pin_func_id", "")).strip(),
                    "function_name": function_name,
                    "module_path": module_path,
                    "file_path": file_path,
                    "line_start": line_start,
                    "line_end": line_end,
                    "signature": str(proposal.get("signature", "")).strip(),
                    "docstring": str(proposal.get("docstring", "")).strip(),
                    "content_hash": proposal_hash or canonical_hash,
                    "is_shape": bool(proposal.get("is_shape", False)),
                    "store_touches": self._coerce_string_list(
                        proposal.get("store_touches", []),
                        field="store_touches",
                        idx=idx,
                    ),
                    "evidence_atom_ids": self._coerce_string_list(
                        proposal.get("evidence_atom_ids", []),
                        field="evidence_atom_ids",
                        idx=idx,
                    ),
                }
            )
        return verified

    def _verify_edge_proposals(
        self,
        *,
        edge_proposals: list[dict[str, Any]],
        pin_ids: set[str],
        existing_edge_ids: set[str],
    ) -> list[ImportEdge]:
        seen_edge_ids: set[str] = set()
        used_edge_ids: set[str] = set(existing_edge_ids)
        materialized: list[ImportEdge] = []

        next_edge_seq = self._next_edge_sequence(used_edge_ids)
        for idx, proposal in enumerate(edge_proposals):
            resolved_pin_id = str(proposal.get("pin_func_id", "")).strip()
            if not resolved_pin_id:
                raise ValueError(f"edge_proposals[{idx}] missing pin_func_id")
            if resolved_pin_id not in pin_ids:
                raise ValueError(
                    f"edge_proposals[{idx}] references unknown pin_func_id {resolved_pin_id!r}"
                )

            arch_file_path = self._normalize_project_relative_path(
                proposal.get("arch_file_path") or proposal.get("arch_location") or ""
            )
            if not arch_file_path:
                raise ValueError(f"edge_proposals[{idx}] missing arch_file_path")

            arch_location = str(proposal.get("arch_location", "")).strip() or arch_file_path
            arch_line_raw = proposal.get("arch_line")
            if arch_line_raw in (None, "") and ":" in arch_location:
                line_candidate = arch_location.rsplit(":", 1)[-1]
                if line_candidate.isdigit():
                    arch_line_raw = int(line_candidate)
            if arch_line_raw in (None, ""):
                arch_line_raw = 0
            arch_line = self._coerce_non_negative_int(arch_line_raw, field="arch_line", idx=idx)

            projection_raw = proposal.get("projection_type")
            if not isinstance(projection_raw, str) or not projection_raw.strip():
                raise ValueError(f"edge_proposals[{idx}] missing projection_type")
            try:
                projection_type = ProjectionType(projection_raw.strip().lower())
            except ValueError as exc:
                raise ValueError(
                    f"edge_proposals[{idx}] has unsupported projection_type {projection_raw!r}"
                ) from exc

            confidence = self._coerce_confidence(proposal.get("confidence", 1.0), idx=idx)
            edge_id = str(proposal.get("edge_id", "")).strip()
            if not edge_id:
                while True:
                    candidate = f"IMEDGE-P-{next_edge_seq:04d}"
                    next_edge_seq += 1
                    if candidate not in used_edge_ids:
                        edge_id = candidate
                        break

            if edge_id in seen_edge_ids:
                raise ValueError(f"edge_proposals contains duplicate edge_id: {edge_id}")
            seen_edge_ids.add(edge_id)
            used_edge_ids.add(edge_id)

            materialized.append(
                ImportEdge(
                    edge_id=edge_id,
                    pin_func_id=resolved_pin_id,
                    arch_location=arch_location,
                    arch_file_path=arch_file_path,
                    arch_line=arch_line,
                    projection_type=projection_type,
                    confidence=confidence,
                    is_direct_import=bool(proposal.get("is_direct_import", True)),
                )
            )

        return materialized

    @staticmethod
    def _next_edge_sequence(used_edge_ids: set[str]) -> int:
        highest = 0
        for edge_id in used_edge_ids:
            if edge_id.startswith("IMEDGE-P-"):
                suffix = edge_id.removeprefix("IMEDGE-P-")
            elif edge_id.startswith("IMEDGE-"):
                suffix = edge_id.removeprefix("IMEDGE-")
            else:
                continue
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return highest + 1

    def _verify_diff_coverage(
        self,
        pin_functions: list[PinFunction],
        edges: list[ImportEdge],
        changed_files: list[str] | None,
    ) -> None:
        if not changed_files:
            return

        from spec_manager.core.language import SOURCE_EXTENSIONS

        changed_source_files = {
            self._normalize_project_relative_path(path)
            for path in changed_files
            if isinstance(path, str) and Path(path).suffix in SOURCE_EXTENSIONS
        }
        changed_source_files.discard("")
        if not changed_source_files:
            return

        covered_files: set[str] = {
            self._normalize_project_relative_path(pin.file_path) for pin in pin_functions
        }
        covered_files.update(
            self._normalize_project_relative_path(edge.arch_file_path) for edge in edges
        )
        covered_files.discard("")

        uncovered = sorted(changed_source_files - covered_files)
        if uncovered:
            raise ValueError(
                "Pin/edge proposals do not cover changed source files: " + ", ".join(uncovered)
            )

    def _normalize_project_relative_path(self, file_path: Any) -> str:
        raw = str(file_path or "").strip()
        if not raw:
            return ""
        candidate = Path(raw)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(self._project_root)
            except ValueError as exc:
                raise ValueError(
                    f"Path {raw!r} is outside project root {self._project_root}"
                ) from exc
        normalized = candidate.as_posix()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if ":" in normalized:
            possible_path, _, suffix = normalized.partition(":")
            if Path(possible_path).suffix and suffix:
                normalized = possible_path
        return normalized

    @staticmethod
    def _coerce_positive_int(value: Any, *, field: str, idx: int) -> int:
        try:
            coerced = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"pin_proposals[{idx}] has invalid {field}: {value!r}") from exc
        if coerced <= 0:
            raise ValueError(f"pin_proposals[{idx}] has non-positive {field}: {coerced}")
        return coerced

    @staticmethod
    def _coerce_non_negative_int(value: Any, *, field: str, idx: int) -> int:
        try:
            coerced = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"edge_proposals[{idx}] has invalid {field}: {value!r}") from exc
        if coerced < 0:
            raise ValueError(f"edge_proposals[{idx}] has negative {field}: {coerced}")
        return coerced

    @staticmethod
    def _coerce_confidence(value: Any, *, idx: int) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"edge_proposals[{idx}] has invalid confidence: {value!r}") from exc
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError(
                f"edge_proposals[{idx}] confidence must be within [0.0, 1.0], got {confidence}"
            )
        return confidence

    @staticmethod
    def _coerce_string_list(value: Any, *, field: str, idx: int) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError(f"pin_proposals[{idx}] field {field} must be a list")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError(f"pin_proposals[{idx}] field {field} must contain only strings")
            text = item.strip()
            if text:
                result.append(text)
        return result

    def _file_to_module(self, file_path: Path) -> str:
        parts = list(file_path.with_suffix("").parts)
        while parts and parts[0] in (".", ".."):
            parts.pop(0)
        return ".".join(parts)


__all__ = [
    "PinFunctionConfig",
    "PinFunctionOrchestrator",
]
