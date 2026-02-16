"""Test-pin association discovery from runtime instrumentation.

This module does not parse source code to infer test→pin relationships.
Associations are accepted only from runtime execution observations provided
by a language/runtime-specific instrumentation plugin.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import PinFunctionRegistry


class ObservationLoadError(RuntimeError):
    """Runtime observation payload could not be loaded/parsed."""


class TestPinDiscoverer(Protocol):
    """Plugin interface for test-pin association discovery strategies."""

    def discover(
        self,
        test_files: list[Path],
        registry: PinFunctionRegistry,
    ) -> TestPinMap: ...


@dataclass
class TestPinAssociation:
    """A discovered association between a test function and a pin-function."""

    test_file: str
    test_function: str
    pin_func_id: str
    pin_function_name: str
    association_type: str
    confidence: float


@dataclass
class TestPinMap:
    """Complete mapping of test functions to pin-functions."""

    associations: list[TestPinAssociation] = field(default_factory=list)
    rejected_rows: list[dict[str, Any]] = field(default_factory=list)
    scan_timestamp: str = ""
    test_roots_scanned: list[str] = field(default_factory=list)

    def associations_for_pin(self, pin_func_id: str) -> list[TestPinAssociation]:
        """Return all associations for a given pin-function ID."""
        return [a for a in self.associations if a.pin_func_id == pin_func_id]

    def associations_for_test(self, test_function: str) -> list[TestPinAssociation]:
        """Return all associations for a given test function."""
        return [a for a in self.associations if a.test_function == test_function]


@dataclass
class RuntimeInstrumentationTestPinDiscoverer:
    """Test-pin discoverer that consumes runtime instrumentation payloads."""

    runtime_observations: list[dict[str, Any]] = field(default_factory=list)
    observations_path: Path | None = None

    def discover(
        self,
        test_files: list[Path],
        registry: PinFunctionRegistry,
    ) -> TestPinMap:
        return discover_test_pin_associations(
            test_files,
            registry,
            runtime_observations=self.runtime_observations,
            observations_path=self.observations_path,
        )


def discover_test_pin_associations(
    test_files: list[Path],
    registry: PinFunctionRegistry,
    *,
    runtime_observations: list[dict[str, Any]] | None = None,
    observations_path: Path | None = None,
) -> TestPinMap:
    """Build test→pin map from runtime instrumentation observations.

    Observation row format (keys are flexible aliases):
    - test_file | test_path | file
    - test_function | test_name
    - pin_func_id | pin_id | pin_function_name
    - confidence (optional)
    - association_type (optional)
    """
    pin_name_to_ids: dict[str, list[str]] = {}
    pin_module_and_name_to_ids: dict[tuple[str, str], list[str]] = {}
    pin_id_to_name: dict[str, str] = {}
    for pf in registry.pin_functions:
        pin_name_to_ids.setdefault(pf.function_name, []).append(pf.pin_func_id)
        pin_module_and_name_to_ids.setdefault((pf.module_path, pf.function_name), []).append(
            pf.pin_func_id
        )
        pin_id_to_name[pf.pin_func_id] = pf.function_name
    allowed_pin_ids = {pf.pin_func_id for pf in registry.pin_functions}

    allowed_files: set[str] = {
        str(path).replace("\\", "/") for path in test_files if isinstance(path, Path)
    }

    raw_observations: list[Any] = []
    if runtime_observations:
        raw_observations.extend(runtime_observations)
    if observations_path is not None:
        raw_observations.extend(_load_observations(observations_path))

    associations: list[TestPinAssociation] = []
    rejected_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for row in raw_observations:
        if not isinstance(row, dict):
            rejected_rows.append(
                {
                    "reason": "observation_row_not_object",
                    "row": {"value": repr(row)},
                }
            )
            continue

        assoc, rejection_reason = _normalize_runtime_observation(
            row=row,
            pin_name_to_ids=pin_name_to_ids,
            pin_module_and_name_to_ids=pin_module_and_name_to_ids,
            pin_id_to_name=pin_id_to_name,
            allowed_pin_ids=allowed_pin_ids,
            allowed_files=allowed_files,
        )
        if assoc is None:
            rejected_rows.append({"reason": rejection_reason, "row": dict(row)})
            continue
        key = (assoc.test_file, assoc.test_function, assoc.pin_func_id)
        if key in seen:
            rejected_rows.append({"reason": "duplicate_association", "row": dict(row)})
            continue
        seen.add(key)
        associations.append(assoc)

    test_roots = list(dict.fromkeys(str(p.parent) for p in test_files if isinstance(p, Path)))

    return TestPinMap(
        associations=associations,
        rejected_rows=rejected_rows,
        scan_timestamp=datetime.now(UTC).isoformat(),
        test_roots_scanned=test_roots,
    )


def _load_observations(path: Path) -> list[Any]:
    if not path.exists():
        return []

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ObservationLoadError(
            f"Failed to load runtime test-pin observations from {path}: {exc}"
        ) from exc

    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict):
        rows = loaded.get("observations")
        if isinstance(rows, list):
            return rows

    raise ObservationLoadError(
        f"Runtime observation payload at {path} must be a list or object with 'observations' list."
    )


def _normalize_runtime_observation(
    *,
    row: dict[str, Any],
    pin_name_to_ids: dict[str, list[str]],
    pin_module_and_name_to_ids: dict[tuple[str, str], list[str]],
    pin_id_to_name: dict[str, str],
    allowed_pin_ids: set[str],
    allowed_files: set[str],
) -> tuple[TestPinAssociation | None, str]:
    test_file = str(row.get("test_file") or row.get("test_path") or row.get("file") or "").strip()
    if not test_file:
        return None, "missing_test_file"
    test_file = test_file.replace("\\", "/")

    if (
        allowed_files
        and test_file not in allowed_files
        and not any(test_file.endswith(f) for f in allowed_files)
    ):
        return None, "test_file_not_in_allowed_roots"

    test_function = str(row.get("test_function") or row.get("test_name") or "").strip()
    if not test_function:
        return None, "missing_test_function"

    pin_func_id = str(row.get("pin_func_id") or row.get("pin_id") or "").strip()
    pin_function_name = str(row.get("pin_function_name") or "").strip()
    if not pin_func_id:
        if not pin_function_name:
            return None, "missing_pin_identity"

        pin_module_path = str(
            row.get("pin_module_path") or row.get("pin_module") or row.get("module_path") or ""
        ).strip()

        if pin_module_path:
            module_candidates = pin_module_and_name_to_ids.get(
                (pin_module_path, pin_function_name), []
            )
            if len(module_candidates) == 1:
                pin_func_id = module_candidates[0]
            elif len(module_candidates) > 1:
                return None, "ambiguous_pin_identity_for_module_and_name"
            else:
                return None, "unknown_pin_identity_for_module_and_name"
        else:
            name_candidates = pin_name_to_ids.get(pin_function_name, [])
            if len(name_candidates) == 1:
                pin_func_id = name_candidates[0]
            elif len(name_candidates) > 1:
                return None, "ambiguous_pin_function_name"
            else:
                return None, "unknown_pin_function_name"
    if pin_func_id not in allowed_pin_ids:
        return None, "unknown_pin_func_id"

    if not pin_function_name:
        pin_function_name = pin_id_to_name.get(pin_func_id, "")
    if not pin_function_name:
        return None, "unable_to_resolve_pin_function_name"

    confidence_raw = row.get("confidence", 1.0)
    if confidence_raw in (None, ""):
        confidence = 1.0
    else:
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            return None, "invalid_confidence_format"
        if not 0.0 <= confidence <= 1.0:
            return None, "confidence_out_of_range"

    association_type = str(
        row.get("association_type") or row.get("source") or "runtime_instrumentation"
    ).strip()

    return (
        TestPinAssociation(
            test_file=test_file,
            test_function=test_function,
            pin_func_id=pin_func_id,
            pin_function_name=pin_function_name,
            association_type=association_type or "runtime_instrumentation",
            confidence=confidence,
        ),
        "",
    )


__all__ = [
    "ObservationLoadError",
    "RuntimeInstrumentationTestPinDiscoverer",
    "TestPinAssociation",
    "TestPinDiscoverer",
    "TestPinMap",
    "discover_test_pin_associations",
]
