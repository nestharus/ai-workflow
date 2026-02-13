"""Test-pin association discovery via source analysis.

Scans test files to find which test functions exercise which pin-functions
by analyzing imports and call sites. Produces a mapping of test functions
to pin-function IDs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from spec_manager.core.code_analysis import RawFunctionInfo, analyze_source

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import PinFunctionRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class TestPinDiscoverer(Protocol):
    """Plugin interface for test-pin association discovery strategies.

    Any implementation must accept a list of test files and a pin-function
    registry, and return a ``TestPinMap``.
    """

    def discover(
        self,
        test_files: list[Path],
        registry: PinFunctionRegistry,
    ) -> TestPinMap: ...


# ---------------------------------------------------------------------------
# Regex patterns for import and call-site extraction
# ---------------------------------------------------------------------------

# Matches: from foo.bar import name1, name2 as alias2
_IMPORT_FROM_RE = re.compile(r"^\s*from\s+\S+\s+import\s+(.+)$", re.MULTILINE)
# Matches: import foo.bar, baz as qux
_IMPORT_RE = re.compile(r"^\s*import\s+(.+)$", re.MULTILINE)
# Matches function calls: identifier( or obj.identifier(
_CALL_RE = re.compile(r"(?:^|[^.\w])(\w+)\s*\(", re.MULTILINE)
# Also capture attribute calls: obj.method(
_ATTR_CALL_RE = re.compile(r"\.(\w+)\s*\(", re.MULTILINE)


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

    Uses source analysis and regex to find imports and call sites in test
    files that reference pin-function atoms.

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
        scan_timestamp=datetime.now(UTC).isoformat(),
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
    from spec_manager.core.language import is_source_file

    if not test_file.exists() or not is_source_file(test_file.suffix):
        return []

    try:
        source = test_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        logger.warning("Failed to read test file: %s", test_file)
        return []

    # Use analyze_source to get function info
    try:
        analysis = analyze_source(source, filepath=str(test_file))
    except Exception:
        logger.warning("Failed to analyze test file: %s", test_file)
        return []

    # Step 1: Extract imports via regex to find which pin-function names are imported
    imported_pins: dict[str, str] = {}  # local_name -> pin_func_id
    imported_pins.update(_extract_imported_pins(source, name_to_pin))

    # Step 2: Walk all test functions and look for calls to imported pins
    associations: list[TestPinAssociation] = []
    file_str = str(test_file)
    source_lines = source.splitlines()

    for func_info in analysis.functions:
        # Determine qualified test function name and whether it's a test
        qualified_name = func_info.qualified_name
        func_name = func_info.name

        if not func_name.startswith("test_"):
            continue

        # Check if this is a class method (qualified_name contains ".")
        # or a top-level function
        is_class_method = "." in qualified_name
        if is_class_method:
            # Only include if parent class starts with "Test"
            class_name = qualified_name.rsplit(".", 1)[0]
            if not class_name.startswith("Test"):
                continue

        # Extract function body source lines for call analysis
        body_source = _extract_function_body(source_lines, func_info)

        assocs = _find_associations_in_function(
            func_info,
            body_source,
            qualified_name,
            file_str,
            imported_pins,
            name_to_pin,
        )
        associations.extend(assocs)

    return associations


def _extract_imported_pins(source: str, name_to_pin: dict[str, str]) -> dict[str, str]:
    """Extract pin-function imports from source using regex.

    Args:
        source: The source code text.
        name_to_pin: Mapping of function_name to pin_func_id.

    Returns:
        Mapping of local_name to pin_func_id for imported pin-functions.
    """
    imported_pins: dict[str, str] = {}

    # Handle "from X import a, b as c, d"
    for match in _IMPORT_FROM_RE.finditer(source):
        names_part = match.group(1).strip().rstrip("\\")
        for name_spec in names_part.split(","):
            name_spec = name_spec.strip()
            if not name_spec:
                continue
            # Handle "name as alias"
            parts = name_spec.split(" as ")
            original_name = parts[0].strip()
            local_name = parts[-1].strip() if len(parts) > 1 else original_name
            if original_name in name_to_pin:
                imported_pins[local_name] = name_to_pin[original_name]

    # Handle "import foo.bar, baz as qux"
    for match in _IMPORT_RE.finditer(source):
        # Skip "from X import Y" lines (already handled)
        line = match.group(0).strip()
        if line.startswith("from "):
            continue
        names_part = match.group(1).strip()
        for name_spec in names_part.split(","):
            name_spec = name_spec.strip()
            if not name_spec:
                continue
            parts = name_spec.split(" as ")
            original_name = parts[0].strip()
            local_name = parts[-1].strip() if len(parts) > 1 else original_name
            if original_name in name_to_pin:
                imported_pins[local_name] = name_to_pin[original_name]

    return imported_pins


def _extract_function_body(source_lines: list[str], func_info: RawFunctionInfo) -> str:
    """Extract the source text of a function body.

    Args:
        source_lines: All lines of the source file.
        func_info: The function info from analyze_source.

    Returns:
        The function body as a string.
    """
    start = func_info.start_line - 1  # Convert to 0-indexed
    end = func_info.end_line  # end_line is inclusive, so this gets all lines
    if start < 0:
        start = 0
    if end > len(source_lines):
        end = len(source_lines)
    return "\n".join(source_lines[start:end])


def _find_associations_in_function(
    func_info: RawFunctionInfo,
    body_source: str,
    qualified_name: str,
    file_str: str,
    imported_pins: dict[str, str],
    name_to_pin: dict[str, str],
) -> list[TestPinAssociation]:
    """Find pin-function associations in a test function body.

    Checks both direct calls to imported pin-functions and fixture-based
    usage via parameter names.

    Args:
        func_info: The function info from analyze_source.
        body_source: The source text of the function body.
        qualified_name: Fully qualified test function name.
        file_str: Path to the test file as string.
        imported_pins: Mapping of local import names to pin_func_id.
        name_to_pin: Mapping of function_name to pin_func_id.

    Returns:
        List of associations found.
    """
    associations: list[TestPinAssociation] = []
    seen_pins: set[str] = set()  # Avoid duplicate associations

    # Check calls in function body using regex
    called_names: set[str] = set()
    for m in _CALL_RE.finditer(body_source):
        called_names.add(m.group(1))
    for m in _ATTR_CALL_RE.finditer(body_source):
        called_names.add(m.group(1))

    for called_name in called_names:
        if called_name in imported_pins:
            pin_id = imported_pins[called_name]
            if pin_id not in seen_pins:
                seen_pins.add(pin_id)
                pin_func_name = _resolve_pin_func_name(pin_id, called_name, name_to_pin)
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
    for param_name in func_info.args:
        # Strip annotation if present (args may include "self", "amount: float", etc.)
        clean_name = param_name.split(":")[0].strip()
        if clean_name in name_to_pin:
            pin_id = name_to_pin[clean_name]
            if pin_id not in seen_pins:
                seen_pins.add(pin_id)
                associations.append(
                    TestPinAssociation(
                        test_file=file_str,
                        test_function=qualified_name,
                        pin_func_id=pin_id,
                        pin_function_name=clean_name,
                        association_type="fixture_usage",
                        confidence=0.7,
                    )
                )

    return associations


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


# ---------------------------------------------------------------------------
# Concrete implementation
# ---------------------------------------------------------------------------


class SourceAnalysisTestPinDiscoverer:
    """Concrete ``TestPinDiscoverer`` using regex and ``analyze_source``.

    Delegates to the module-level ``discover_test_pin_associations``
    function.
    """

    def discover(
        self,
        test_files: list[Path],
        registry: PinFunctionRegistry,
    ) -> TestPinMap:
        """Discover test-pin associations via source analysis."""
        return discover_test_pin_associations(test_files, registry)


__all__ = [
    "SourceAnalysisTestPinDiscoverer",
    "TestPinAssociation",
    "TestPinDiscoverer",
    "TestPinMap",
    "discover_test_pin_associations",
]
