"""Test-pin alignment checker.

High-level orchestration that ties together test-pin discovery,
baseline management, and drift detection into a single pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.projection.lineage.builder import AtomDefinition
from spec_manager.projection.lineage.drift_detector import (
    PinDrift,
    PinDriftDetector,
)
from spec_manager.projection.lineage.table import ProjectionLineageTable
from spec_manager.projection.lineage.test_pin_baseline import (
    build_baseline,
    load_baseline,
    save_baseline,
    update_baseline,
)
from spec_manager.projection.lineage.test_pin_discovery import (
    discover_test_pin_associations,
)

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import PinFunctionRegistry


@dataclass
class TestPinCheckResult:
    """Result of test-pin alignment check.

    Attributes:
        drift_items: Detected test signature drift items.
        total_pin_functions: Total number of pin-functions in the registry.
        pin_functions_with_tests: Number of pin-functions with associated tests.
        pin_functions_without_tests: Number of pin-functions without associated tests.
        test_coverage_ratio: Ratio of pin-functions with tests to total.
        associations_found: Total number of test-pin associations discovered.
        baseline_updated: Whether the baseline was updated during this check.
    """

    drift_items: list[PinDrift] = field(default_factory=list)
    total_pin_functions: int = 0
    pin_functions_with_tests: int = 0
    pin_functions_without_tests: int = 0
    test_coverage_ratio: float = 0.0
    associations_found: int = 0
    baseline_updated: bool = False


def check_test_pin_alignment(
    registry: PinFunctionRegistry,
    test_roots: list[Path],
    baseline_path: Path,
    update_baseline_flag: bool = False,
) -> TestPinCheckResult:
    """Run full test-pin validation pipeline.

    1. Discover test-pin associations (Plan 1).
    2. Load existing baseline (Plan 2).
    3. Detect test signature drift (Plan 3).
    4. Optionally update baseline.

    Args:
        registry: The pin-function registry.
        test_roots: Directories to scan for test files.
        baseline_path: Path to the baseline JSON file.
        update_baseline_flag: Whether to update the baseline after checking.

    Returns:
        TestPinCheckResult with drift findings and coverage stats.
    """
    # Step 1: Discover test files
    test_files = _collect_test_files(test_roots)

    # Step 2: Discover test-pin associations
    test_pin_map = discover_test_pin_associations(test_files, registry)

    # Step 3: Load existing baseline
    baseline_store = load_baseline(baseline_path)

    # Step 4: Build atoms for the drift detector
    atoms = _build_atoms_from_registry(registry)
    lineage_table = ProjectionLineageTable()
    detector = PinDriftDetector(lineage_table, atoms)

    # Step 5: Detect test signature drift
    drift_items = detector.detect_test_signature_drift(baseline_store, test_pin_map)

    # Step 6: Compute coverage statistics
    total_pin_functions = len(registry.pin_functions)
    pin_ids_with_tests = {a.pin_func_id for a in test_pin_map.associations}
    pin_functions_with_tests = len(pin_ids_with_tests)
    pin_functions_without_tests = total_pin_functions - pin_functions_with_tests
    test_coverage_ratio = (
        pin_functions_with_tests / total_pin_functions if total_pin_functions > 0 else 0.0
    )

    # Step 7: Optionally update baseline
    baseline_updated = False
    if update_baseline_flag:
        if not baseline_store.baselines:
            # No existing baseline -- create new one
            new_store = build_baseline(test_pin_map)
            save_baseline(new_store, baseline_path)
            baseline_updated = True
        else:
            updated_store, _changes = update_baseline(baseline_store, test_pin_map, force=True)
            save_baseline(updated_store, baseline_path)
            baseline_updated = True

    return TestPinCheckResult(
        drift_items=drift_items,
        total_pin_functions=total_pin_functions,
        pin_functions_with_tests=pin_functions_with_tests,
        pin_functions_without_tests=pin_functions_without_tests,
        test_coverage_ratio=test_coverage_ratio,
        associations_found=len(test_pin_map.associations),
        baseline_updated=baseline_updated,
    )


def _collect_test_files(test_roots: list[Path]) -> list[Path]:
    """Collect all test Python files from the given roots.

    Args:
        test_roots: Directories to scan.

    Returns:
        List of test file paths.
    """
    test_files: list[Path] = []
    for root in test_roots:
        if root.is_dir():
            for py_file in sorted(root.rglob("*.py")):
                if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
                    test_files.append(py_file)
        elif root.is_file() and root.suffix == ".py":
            test_files.append(root)
    return test_files


def _build_atoms_from_registry(
    registry: PinFunctionRegistry,
) -> list[AtomDefinition]:
    """Convert pin-functions from the registry to AtomDefinitions.

    Args:
        registry: The pin-function registry.

    Returns:
        List of AtomDefinition entries.
    """
    atoms: list[AtomDefinition] = []
    for pf in registry.pin_functions:
        atoms.append(
            AtomDefinition(
                atom_id=pf.pin_func_id,
                function_name=pf.function_name,
                file_path=pf.file_path,
                module_path=pf.module_path,
                signature_hash=pf.content_hash,
            )
        )
    return atoms


__all__ = [
    "TestPinCheckResult",
    "check_test_pin_alignment",
]
