"""Test-pin association discovery from runtime instrumentation.

This module does not parse source code to infer test→pin relationships.
Associations are accepted only from runtime execution observations provided
by a language/runtime-specific instrumentation plugin.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import PinFunctionRegistry

logger = logging.getLogger(__name__)


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
    name_to_pin: dict[str, str] = {}
    for pf in registry.pin_functions:
        name_to_pin[pf.function_name] = pf.pin_func_id
    allowed_pin_ids = {pf.pin_func_id for pf in registry.pin_functions}

    allowed_files: set[str] = {
        str(path).replace("\\", "/") for path in test_files if isinstance(path, Path)
    }

    raw_observations: list[dict[str, Any]] = []
    if runtime_observations:
        raw_observations.extend(item for item in runtime_observations if isinstance(item, dict))
    if observations_path is not None:
        raw_observations.extend(_load_observations(observations_path))

    associations: list[TestPinAssociation] = []
    seen: set[tuple[str, str, str]] = set()

    for row in raw_observations:
        assoc = _normalize_runtime_observation(
            row=row,
            name_to_pin=name_to_pin,
            allowed_pin_ids=allowed_pin_ids,
            allowed_files=allowed_files,
        )
        if assoc is None:
            continue
        key = (assoc.test_file, assoc.test_function, assoc.pin_func_id)
        if key in seen:
            continue
        seen.add(key)
        associations.append(assoc)

    test_roots = list(dict.fromkeys(str(p.parent) for p in test_files if isinstance(p, Path)))

    return TestPinMap(
        associations=associations,
        scan_timestamp=datetime.now(UTC).isoformat(),
        test_roots_scanned=test_roots,
    )


def _load_observations(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        logger.warning("Failed to load runtime test-pin observations from %s", path)
        return []
    if isinstance(loaded, list):
        return [item for item in loaded if isinstance(item, dict)]
    if isinstance(loaded, dict):
        rows = loaded.get("observations")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def _normalize_runtime_observation(
    *,
    row: dict[str, Any],
    name_to_pin: dict[str, str],
    allowed_pin_ids: set[str],
    allowed_files: set[str],
) -> TestPinAssociation | None:
    test_file = str(row.get("test_file") or row.get("test_path") or row.get("file") or "").strip()
    if not test_file:
        return None
    test_file = test_file.replace("\\", "/")

    if (
        allowed_files
        and test_file not in allowed_files
        and not any(test_file.endswith(f) for f in allowed_files)
    ):
        return None

    test_function = str(row.get("test_function") or row.get("test_name") or "").strip()
    if not test_function:
        return None

    pin_func_id = str(row.get("pin_func_id") or row.get("pin_id") or "").strip()
    pin_function_name = str(row.get("pin_function_name") or "").strip()
    if not pin_func_id:
        if pin_function_name and pin_function_name in name_to_pin:
            pin_func_id = name_to_pin[pin_function_name]
        else:
            return None
    if pin_func_id not in allowed_pin_ids:
        return None

    if not pin_function_name:
        for fn_name, resolved_id in name_to_pin.items():
            if resolved_id == pin_func_id:
                pin_function_name = fn_name
                break

    try:
        confidence = float(row.get("confidence", 1.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 1.0

    association_type = str(
        row.get("association_type") or row.get("source") or "runtime_instrumentation"
    ).strip()

    return TestPinAssociation(
        test_file=test_file,
        test_function=test_function,
        pin_func_id=pin_func_id,
        pin_function_name=pin_function_name,
        association_type=association_type or "runtime_instrumentation",
        confidence=max(0.0, min(1.0, confidence)),
    )


__all__ = [
    "RuntimeInstrumentationTestPinDiscoverer",
    "TestPinAssociation",
    "TestPinDiscoverer",
    "TestPinMap",
    "discover_test_pin_associations",
]
