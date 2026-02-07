"""Test-pin association discovery via AST analysis.

Scans test files to find which test functions exercise which pin-functions
by analyzing imports and call sites. Produces a mapping of test functions
to pin-function IDs.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import PinFunctionRegistry

logger = logging.getLogger(__name__)


@dataclass
class TestPinAssociation:
    """A discovered association between a test function and a pin-function.

    Attributes:
        test_file: Path to the test file.
        test_function: Fully qualified test function name (e.g., "TestClass.test_method").
        pin_func_id: The pin-function ID being exercised.
        pin_function_name: The pin-function's Python name.
        association_type: "direct_import", "indirect_call", or "fixture_usage".
        confidence: 0.0-1.0 confidence in the association.
    """

    test_file: str
    test_function: str
    pin_func_id: str
    pin_function_name: str
    association_type: str
    confidence: float


@dataclass
class TestPinMap:
    """Complete mapping of test functions to pin-functions.

    Attributes:
        associations: All discovered test-pin associations.
        scan_timestamp: ISO-8601 timestamp of when the scan was performed.
        test_roots_scanned: Directories that were scanned.
    """

    associations: list[TestPinAssociation] = field(default_factory=list)
    scan_timestamp: str = ""
    test_roots_scanned: list[str] = field(default_factory=list)

    def associations_for_pin(self, pin_func_id: str) -> list[TestPinAssociation]:
        """Return all associations for a given pin-function ID."""
        return [a for a in self.associations if a.pin_func_id == pin_func_id]

    def associations_for_test(self, test_function: str) -> list[TestPinAssociation]:
        """Return all associations for a given test function."""
        return [a for a in self.associations if a.test_function == test_function]


def discover_test_pin_associations(
    test_files: list[Path],
    registry: PinFunctionRegistry,
) -> TestPinMap:
    """Discover which test functions exercise which pin-functions.

    Uses AST analysis to find imports and call sites in test files that
    reference pin-function atoms.

    Args:
        test_files: List of test file paths to scan.
        registry: The pin-function registry providing function name to ID mapping.

    Returns:
        A TestPinMap with all discovered associations.
    """
    # Build lookup: {function_name: pin_func_id}
    name_to_pin: dict[str, str] = {}
    for pf in registry.pin_functions:
        name_to_pin[pf.function_name] = pf.pin_func_id

    associations: list[TestPinAssociation] = []
    test_roots: list[str] = []

    for test_file in test_files:
        test_roots_set: set[str] = set()
        if test_file.parent not in test_roots_set:
            test_roots_set.add(str(test_file.parent))
            test_roots.append(str(test_file.parent))

        file_associations = _scan_test_file(test_file, name_to_pin)
        associations.extend(file_associations)

    # Deduplicate test roots
    unique_roots = list(dict.fromkeys(test_roots))

    return TestPinMap(
        associations=associations,
        scan_timestamp=datetime.now(timezone.utc).isoformat(),
        test_roots_scanned=unique_roots,
    )


def _scan_test_file(
    test_file: Path,
    name_to_pin: dict[str, str],
) -> list[TestPinAssociation]:
    """Scan a single test file for pin-function associations.

    Args:
        test_file: Path to the test file.
        name_to_pin: Mapping of function_name to pin_func_id.

    Returns:
        List of associations found in the file.
    """
    if not test_file.exists() or test_file.suffix != ".py":
        return []

    try:
        source = test_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(test_file))
    except (SyntaxError, UnicodeDecodeError):
        logger.warning("Failed to parse test file: %s", test_file)
        return []

    # Step 1: Walk imports to find which pin-function names are imported
    imported_pins: dict[str, str] = {}  # local_name -> pin_func_id
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name
                if alias.name in name_to_pin:
                    imported_pins[local_name] = name_to_pin[alias.name]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name
                if alias.name in name_to_pin:
                    imported_pins[local_name] = name_to_pin[alias.name]

    # Step 2: Walk all test functions and look for calls to imported pins
    associations: list[TestPinAssociation] = []
    file_str = str(test_file)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            # Class-based tests
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("test_"):
                        qualified_name = f"{node.name}.{item.name}"
                        assocs = _find_associations_in_function(
                            item,
                            qualified_name,
                            file_str,
                            imported_pins,
                            name_to_pin,
                        )
                        associations.extend(assocs)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                # Check if this is a top-level test function (not inside a class)
                # We already handle class-based tests above, so skip if parent is a class
                # Since ast.walk doesn't give parent info, we check by looking at module body
                if _is_top_level_function(tree, node):
                    assocs = _find_associations_in_function(
                        node,
                        node.name,
                        file_str,
                        imported_pins,
                        name_to_pin,
                    )
                    associations.extend(assocs)

    return associations


def _is_top_level_function(tree: ast.Module, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if a function node is at the top level of the module (not inside a class).

    Args:
        tree: The module AST.
        func_node: The function node to check.

    Returns:
        True if the function is at module level.
    """
    for node in tree.body:
        if node is func_node:
            return True
    return False


def _find_associations_in_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    qualified_name: str,
    file_str: str,
    imported_pins: dict[str, str],
    name_to_pin: dict[str, str],
) -> list[TestPinAssociation]:
    """Find pin-function associations in a test function body.

    Checks both direct calls to imported pin-functions and fixture-based
    usage via parameter names.

    Args:
        func_node: The AST node of the test function.
        qualified_name: Fully qualified test function name.
        file_str: Path to the test file as string.
        imported_pins: Mapping of local import names to pin_func_id.
        name_to_pin: Mapping of function_name to pin_func_id.

    Returns:
        List of associations found.
    """
    associations: list[TestPinAssociation] = []
    seen_pins: set[str] = set()  # Avoid duplicate associations

    # Check calls in function body
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            called_name = _extract_call_name(node)
            if called_name is not None and called_name in imported_pins:
                pin_id = imported_pins[called_name]
                if pin_id not in seen_pins:
                    seen_pins.add(pin_id)
                    # Resolve the original function name from pin_id
                    pin_func_name = _resolve_pin_func_name(
                        pin_id, called_name, name_to_pin
                    )
                    associations.append(
                        TestPinAssociation(
                            test_file=file_str,
                            test_function=qualified_name,
                            pin_func_id=pin_id,
                            pin_function_name=pin_func_name,
                            association_type="direct_import",
                            confidence=1.0,
                        )
                    )

    # Check fixture-based associations via parameter names
    for arg in func_node.args.args:
        param_name = arg.arg
        if param_name in name_to_pin:
            pin_id = name_to_pin[param_name]
            if pin_id not in seen_pins:
                seen_pins.add(pin_id)
                associations.append(
                    TestPinAssociation(
                        test_file=file_str,
                        test_function=qualified_name,
                        pin_func_id=pin_id,
                        pin_function_name=param_name,
                        association_type="fixture_usage",
                        confidence=0.7,
                    )
                )

    return associations


def _extract_call_name(node: ast.Call) -> str | None:
    """Extract the simple function name from a Call node.

    Handles both simple calls (func()) and attribute calls (obj.func()).

    Args:
        node: The AST Call node.

    Returns:
        The function name string, or None if not extractable.
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _resolve_pin_func_name(
    pin_id: str,
    local_name: str,
    name_to_pin: dict[str, str],
) -> str:
    """Resolve the original pin-function name from a pin ID.

    Args:
        pin_id: The pin-function ID.
        local_name: The local import name used in the test.
        name_to_pin: Mapping of function_name to pin_func_id.

    Returns:
        The original function name, or local_name as fallback.
    """
    for func_name, pid in name_to_pin.items():
        if pid == pin_id:
            return func_name
    return local_name


__all__ = [
    "TestPinAssociation",
    "TestPinMap",
    "discover_test_pin_associations",
]
