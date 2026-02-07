# Implementation Plan: Compliance Gating for Layer Promotion

## Overview

Build the compliance gating system that enforces quality thresholds before promoting code from the algorithmic branch to the architectural branch, including algorithmic layer cleanliness checks, pin coverage verification, introduced algorithm spec enforcement, provenance tracking, and architectural quality checks.

## Current State (Problems)

1. **Compliance gating is spec-level, not layer-level.** The existing `ComplianceScorer` in `scripts/spec_manager/spec_manager/compliance/scorer.py` scores compliance for specification artifacts (sections, atoms, terms) using format compliance, annotation coverage, and ID normalization. It has no concept of algorithmic-to-architectural layer promotion. Its `compliance_gate_mode` (block/warn) and threshold system are designed for spec processing passes, not branch promotion.

2. **Coverage gate checks atom accounting, not pin coverage.** The existing `CoverageReport` and `verify_coverage_or_emit_gap` in `scripts/spec_manager/spec_manager/compliance/coverage_gate.py` track whether all `LineAtom` IDs are accounted for (mapped, remainder, or excluded). They do not verify that every architectural location pins back to an algorithmic origin or that pin-functions have corresponding architectural imports.

3. **No concept of "introduced algorithms."** The system has no way to distinguish infrastructure algorithms (retry, circuit breaking) that have no algorithmic origin from business logic atoms. The design doc (Section 12) requires that these introduced algorithms carry their own spec comments, forming a mini-algorithmic layer for infrastructure concerns.

4. **Provenance is patch-level, not function-level.** The existing `TrackedUnit.introduced_by` and `TrackedUnit.modified_by` fields (in both `scripts/spec_manager/spec_manager/core/provenance.py` and `scripts/spec_manager/spec_manager/workflow/config.py`) track which spec patches introduced or modified a unit. There is no equivalent provenance chain for individual atom functions (pin-functions) -- which plan/patch added them and the chain of modifications.

5. **No inlined-logic detection.** There is no mechanism to verify that the architectural layer calls atom functions rather than copy-pasting their logic inline. The design doc (Section 12) explicitly requires "no inlined atom logic" as an architectural quality gate.

6. **Executable gap detection exists but is not wired to promotion.** Plan 05 (`05-executable-gap-detection.md`) creates comment and stub scanners. However, the compliance scorer's `check_executable_gaps` method is an extension point that is not yet integrated into a layer-promotion gate. The existing gate system blocks spec processing passes, not branch promotion.

7. **Store monogamy is not enforced.** The design doc (Section 3, via ALGORITHM.md 8.16) requires that every store lives inside one vertical slice. There is no automated check for this constraint.

## Target State

A `LayerPromotionGate` system that:
- Runs as a prerequisite before projecting algorithmic code into the architectural branch
- Enforces the five algorithmic layer gates: no remaining comments, no stubs, all tests pass, call graph connected, store monogamy
- Verifies pin coverage: every architectural location traces back to an algorithmic origin (except classified introductions)
- Validates introduced algorithm specs: infrastructure algorithms carry their own spec comments
- Tracks provenance on atom functions: `introduced_by`, `modified_by`, `source_location` chains
- Checks architectural quality: no inlined atom logic, function recomposition verified
- Integrates with the existing compliance module via the `ComplianceScorer` and `ComplianceResult` patterns (block/warn modes)
- Produces a structured `PromotionReport` that enumerates all gate results

## Additional Info

### Relationship to Existing Plans

- **Plan 02 (Pin-Functions)**: Provides `PinFunction`, `ImportEdge`, `PinFunctionRegistry`, and `PinRegistryIndex` -- the data structures this plan's pin coverage checks consume.
- **Plan 05 (Executable Gap Detection)**: Provides comment scanner, stub scanner, call graph builder -- the tools this plan's algorithmic layer gates invoke.
- **Plan 09 (Lineage Tracking)**: Provides `LineageEdge` with transformation types -- this plan's provenance tracking extends but does not replace lineage tracking.

### Block vs. Warn Mode

The existing system uses `compliance_gate_mode: "block" | "warn"` (see `WorkflowConfig` in `scripts/spec_manager/spec_manager/workflow/config.py` L115). The promotion gate reuses this pattern: each individual check can be configured as `required` (blocker) or `advisory` (warning). A gate configuration object controls which checks are required.

### Integration Strategy

This plan extends the existing `compliance/` module rather than replacing it. New files are added under `compliance/promotion/`. The existing `ComplianceScorer` gains a new `score_promotion_compliance` method that delegates to the promotion-specific checks. This allows the existing spec-level compliance and the new promotion-level compliance to coexist.

## Plans

### Plan 1: Gate Configuration and Core Data Structures

Define the configuration schema for promotion gates and the core result types.

**Files to create:**

- `scripts/spec_manager/spec_manager/compliance/promotion/__init__.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/config.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/result.py`

**Data structures in `config.py`:**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GateMode(Enum):
    """How a gate failure is treated."""
    REQUIRED = "required"   # Failure blocks promotion
    ADVISORY = "advisory"   # Failure produces warning but does not block


class GateId(Enum):
    """Identifiers for each promotion gate check."""
    NO_REMAINING_COMMENTS = "no_remaining_comments"
    NO_STUB_FUNCTIONS = "no_stub_functions"
    ALL_TESTS_PASS = "all_tests_pass"
    CALL_GRAPH_CONNECTED = "call_graph_connected"
    STORE_MONOGAMY = "store_monogamy"
    PIN_COVERAGE = "pin_coverage"
    INTRODUCED_ALGORITHM_SPECS = "introduced_algorithm_specs"
    NO_INLINED_ATOM_LOGIC = "no_inlined_atom_logic"
    FUNCTION_RECOMPOSITION = "function_recomposition"
    PROVENANCE_COMPLETE = "provenance_complete"


@dataclass
class GateSpec:
    """Configuration for a single gate check.

    Attributes:
        gate_id: Which gate this configures.
        mode: Whether failure blocks or warns.
        threshold: Optional numeric threshold (e.g., 0.0 for zero-tolerance,
            0.95 for 95% coverage). Interpretation depends on the gate.
        enabled: Whether this gate is active.
        params: Gate-specific parameters.
    """
    gate_id: GateId
    mode: GateMode = GateMode.REQUIRED
    threshold: float = 0.0
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromotionGateConfig:
    """Full configuration for layer promotion gating.

    Attributes:
        gates: Per-gate configuration. Missing gates use defaults.
        algorithmic_roots: Directory paths treated as algorithmic code.
        architectural_roots: Directory paths treated as architectural code.
        atom_directories: Directories where atom (pin-function) files live.
        test_command: Command to run algorithmic tests (e.g., ["pytest", "tests/algorithmic/"]).
        project_root: Root of the project being analyzed.
    """
    gates: dict[GateId, GateSpec] = field(default_factory=dict)
    algorithmic_roots: list[str] = field(
        default_factory=lambda: ["algorithmic/atoms", "algorithmic/compositions",
                                 "algorithmic/stores", "algorithmic/shapes"]
    )
    architectural_roots: list[str] = field(
        default_factory=lambda: ["architectural/services", "architectural/events",
                                 "architectural/middleware", "architectural/infrastructure"]
    )
    atom_directories: list[str] = field(
        default_factory=lambda: ["algorithmic/atoms", "algorithmic/shapes"]
    )
    test_command: list[str] = field(
        default_factory=lambda: ["pytest", "tests/algorithmic/", "-x", "--tb=short"]
    )
    project_root: str = "."

    def get_gate(self, gate_id: GateId) -> GateSpec:
        """Get gate spec, returning default if not configured."""
        if gate_id in self.gates:
            return self.gates[gate_id]
        return GateSpec(gate_id=gate_id)

    @classmethod
    def default(cls) -> PromotionGateConfig:
        """Create default configuration with all gates required."""
        config = cls()
        for gate_id in GateId:
            config.gates[gate_id] = GateSpec(gate_id=gate_id)
        # Tests and call graph connectivity are advisory by default
        # (projects may not have tests or may have legitimately disconnected components)
        config.gates[GateId.ALL_TESTS_PASS].mode = GateMode.ADVISORY
        config.gates[GateId.CALL_GRAPH_CONNECTED].mode = GateMode.ADVISORY
        return config
```

**Data structures in `result.py`:**

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.gaps import Severity


@dataclass
class GateCheckResult:
    """Result of a single gate check.

    Attributes:
        gate_id: Which gate was checked.
        passed: Whether the gate passed.
        mode: The configured mode (required/advisory).
        score: Numeric score (0.0-1.0) where applicable.
        findings: Detailed findings from the check.
        summary: Human-readable summary.
        duration_ms: How long the check took.
    """
    gate_id: str
    passed: bool
    mode: str
    score: float = 1.0
    findings: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "mode": self.mode,
            "score": self.score,
            "findings": self.findings,
            "summary": self.summary,
            "duration_ms": self.duration_ms,
        }


@dataclass
class PromotionReport:
    """Aggregate report from all promotion gate checks.

    Attributes:
        passed: Whether all required gates passed.
        gate_results: Results for each gate check.
        blockers: Gate checks that failed in REQUIRED mode.
        warnings: Gate checks that failed in ADVISORY mode.
        total_duration_ms: Total time for all checks.
    """
    passed: bool
    gate_results: list[GateCheckResult] = field(default_factory=list)
    blockers: list[GateCheckResult] = field(default_factory=list)
    warnings: list[GateCheckResult] = field(default_factory=list)
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return {
            "passed": self.passed,
            "gate_results": [r.to_dict() for r in self.gate_results],
            "blockers": [r.to_dict() for r in self.blockers],
            "warnings": [r.to_dict() for r in self.warnings],
            "total_duration_ms": self.total_duration_ms,
        }

    def save(self, path: Path) -> None:
        """Write promotion report to disk as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )
```

**Integration points:**
- `GateCheckResult` follows the same pattern as `ComplianceResult` in `scripts/spec_manager/spec_manager/compliance/scorer.py` (blockers, warnings, passed, details).
- `Severity` is imported from `scripts/spec_manager/spec_manager/core/gaps.py` for consistency with the existing gap detection system.
- `PromotionGateConfig` directory paths align with the branch organization from design doc Section 6.

**Tests:** `scripts/spec_manager/tests/compliance/promotion/test_config.py`
- Verify `PromotionGateConfig.default()` creates all gates with correct default modes.
- Verify `get_gate()` returns configured spec or default.
- Verify `GateCheckResult.to_dict()` / `PromotionReport.to_dict()` serialization round-trip.
- Verify `PromotionReport.save()` writes valid JSON.

---

### Plan 2: Algorithmic Layer Gate Checks

Implement the five algorithmic layer cleanliness gates that must pass before promotion. Each gate is a standalone function that can be called independently or via the orchestrator (Plan 6).

**Files to create:**

- `scripts/spec_manager/spec_manager/compliance/promotion/algorithmic_gates.py`

**Function signatures:**

```python
from __future__ import annotations

import subprocess
from pathlib import Path

from spec_manager.compliance.promotion.config import GateId, GateSpec, PromotionGateConfig
from spec_manager.compliance.promotion.result import GateCheckResult


def check_no_remaining_comments(
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: No remaining comments in algorithmic code.

    Reuses the comment scanner from compliance/detection/comment_scanner.py.
    In algorithmic code, every comment is an unimplemented spec element.

    Each finding includes:
        - file_path, line, text, enclosing_function

    Args:
        algorithmic_files: Python files in the algorithmic layer.
        gate_spec: Gate configuration (mode, threshold).

    Returns:
        GateCheckResult with passed=True only if zero spec comments found.
    """


def check_no_stub_functions(
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: No stub functions in algorithmic code.

    Reuses the stub scanner from compliance/detection/stub_scanner.py.
    All atom functions must have real implementations.

    Each finding includes:
        - file_path, line, name, stub_type

    Args:
        algorithmic_files: Python files in the algorithmic layer.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with passed=True only if zero stubs found.
    """


def check_all_tests_pass(
    test_command: list[str],
    project_root: Path,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: All algorithmic-level tests pass.

    Runs the configured test command via subprocess.
    Captures stdout/stderr for the report.

    Args:
        test_command: Command to execute (e.g., ["pytest", "tests/algorithmic/"]).
        project_root: Working directory for test execution.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with passed=True if return code is 0.
    """


def check_call_graph_connected(
    algorithmic_files: list[Path],
    project_root: Path,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: Call graph has no orphaned algorithms.

    Reuses the call graph builder from compliance/detection/call_graph.py.
    Checks for disconnected components above the configured minimum size.

    gate_spec.params:
        - min_component_size (int, default 2): Minimum component size to flag.
        - ignore_patterns (list[str]): Function name patterns to exclude.

    Args:
        algorithmic_files: Python files to analyze.
        project_root: For module path resolution.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for each disconnected component.
    """


def check_store_monogamy(
    algorithmic_files: list[Path],
    project_root: Path,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: Each store is accessed by only one vertical slice.

    Scans algorithmic code for store access patterns and maps each store
    to the vertical slice(s) that access it. Flags stores accessed by
    multiple verticals.

    Detection strategy:
    1. Identify store definitions by convention (files in stores/ directories,
       classes inheriting from known store base classes, functions with
       store-related decorators).
    2. For each store, find all modules that import/reference it.
    3. Map importing modules to their vertical slice (determined by directory
       structure per design doc Section 9).
    4. Stores referenced by >1 vertical are violations.

    gate_spec.params:
        - store_patterns (list[str]): Glob patterns for store files
            (default ["**/stores/*.py", "**/stores/**/*.py"]).
        - vertical_depth (int): Directory depth that defines a vertical
            boundary (default 2).

    Args:
        algorithmic_files: Python files to analyze.
        project_root: Root directory.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for each store monogamy violation.
    """
```

**Implementation notes:**

- `check_no_remaining_comments` and `check_no_stub_functions` delegate to `scan_comments()` and `scan_stubs()` from Plan 05's detection modules. If those modules are not yet available, the checks degrade gracefully (returning a warning that the scanner is unavailable).
- `check_call_graph_connected` delegates to `build_call_graph()` and `CallGraph.get_connected_components()` from Plan 05.
- `check_all_tests_pass` uses `subprocess.run()` with a configurable timeout, consistent with the runtime detector pattern from Plan 05.
- `check_store_monogamy` performs AST-based import analysis similar to Plan 02's `ImportGraphBuilder`, but scoped to store access rather than pin-function usage. It maps files to vertical slices by analyzing directory paths against the recursive horizontal/vertical structure from design doc Section 9.

**Integration points:**
- Imports `scan_comments`, `scan_stubs` from `compliance.detection.comment_scanner` and `compliance.detection.stub_scanner` (Plan 05).
- Imports `build_call_graph` from `compliance.detection.call_graph` (Plan 05).
- Each function returns a `GateCheckResult` (Plan 1).

**Tests:** `scripts/spec_manager/tests/compliance/promotion/test_algorithmic_gates.py`
- Create fixture files with comments, stubs, and clean code. Verify correct pass/fail.
- Verify test runner gate captures subprocess return code and output.
- Verify call graph connectivity detection with known disconnected and connected graphs.
- Verify store monogamy detection with a fixture project where one store is imported by two verticals.

---

### Plan 3: Pin Coverage Checker

Verify that every architectural location pins back to an algorithmic origin, except for classified introduction nodes.

**Files to create:**

- `scripts/spec_manager/spec_manager/compliance/promotion/pin_coverage.py`

**Data structures:**

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PinCoverageItem:
    """Coverage status of a single architectural location.

    Attributes:
        arch_location: The architectural file:class.method or file:function.
        arch_file_path: Relative path to the architectural file.
        arch_line: Line number.
        has_pin: Whether this location has a pin-function import.
        pin_func_ids: Pin-function IDs it imports (empty if no pin).
        is_introduction: Whether this is a classified introduction
            (architectural algorithm with no algorithmic origin).
        introduction_has_spec: If is_introduction, whether it has spec comments.
    """
    arch_location: str
    arch_file_path: str
    arch_line: int
    has_pin: bool = False
    pin_func_ids: list[str] = field(default_factory=list)
    is_introduction: bool = False
    introduction_has_spec: bool = False


@dataclass
class PinCoverageReport:
    """Aggregate pin coverage report.

    Attributes:
        total_locations: Number of architectural locations scanned.
        pinned_locations: Number with pin-function imports.
        introduction_locations: Number classified as introductions.
        unpinned_locations: Number with neither pin nor introduction classification.
        coverage_ratio: pinned / (total - introductions).
        items: Per-location details.
    """
    total_locations: int
    pinned_locations: int
    introduction_locations: int
    unpinned_locations: int
    coverage_ratio: float
    items: list[PinCoverageItem] = field(default_factory=list)
```

**Function signatures:**

```python
from pathlib import Path

from spec_manager.compliance.promotion.config import GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.schemas.pin_functions import PinFunctionRegistry  # Plan 02


def build_pin_coverage_report(
    registry: PinFunctionRegistry,
    architectural_files: list[Path],
    introduction_markers: list[str] | None = None,
) -> PinCoverageReport:
    """Build a pin coverage report by scanning architectural files.

    For each function/method in each architectural file:
    1. Check if it imports any pin-functions (via registry import edges).
    2. If not, check if it is classified as an introduction
       (by marker comment, directory convention, or explicit registry entry).
    3. Record coverage status.

    Introduction detection:
    - Files in architectural/infrastructure/ are introduction candidates.
    - Functions with a "# @introduced" marker comment are introductions.
    - ImportEdge entries with projection_type=INTRODUCTION.
    - Optional introduction_markers list for custom patterns.

    Args:
        registry: The PinFunctionRegistry from Plan 02.
        architectural_files: Files to check coverage for.
        introduction_markers: Optional additional marker strings.

    Returns:
        PinCoverageReport with per-location coverage data.
    """


def check_pin_coverage(
    registry: PinFunctionRegistry,
    architectural_files: list[Path],
    gate_spec: GateSpec,
    introduction_markers: list[str] | None = None,
) -> GateCheckResult:
    """Gate: Every architectural location pins to algorithmic origin.

    Builds the pin coverage report and evaluates against the gate threshold.

    gate_spec.threshold: Minimum pin coverage ratio (default 1.0 = 100%).
    gate_spec.params:
        - introduction_markers (list[str]): Additional introduction markers.
        - exclude_patterns (list[str]): File patterns to exclude from coverage.

    Args:
        registry: PinFunctionRegistry.
        architectural_files: Architectural layer files.
        gate_spec: Gate configuration.
        introduction_markers: Additional introduction markers.

    Returns:
        GateCheckResult with findings for each unpinned location.
    """
```

**Integration points:**
- Consumes `PinFunctionRegistry` and `ImportEdge` from `scripts/spec_manager/spec_manager/schemas/pin_functions.py` (Plan 02).
- Consumes `PinRegistryIndex` from `scripts/spec_manager/spec_manager/core/pin_registry.py` (Plan 02) for efficient lookups.
- `ProjectionType.INTRODUCTION` from Plan 02 drives introduction classification.

**Tests:** `scripts/spec_manager/tests/compliance/promotion/test_pin_coverage.py`
- Create a mock registry with known pin-functions and import edges. Verify coverage report accuracy.
- Verify that INTRODUCTION edges are correctly excluded from coverage calculation.
- Verify that unpinned locations appear in findings.
- Verify threshold logic (100% required vs. 95% threshold with some unpinned).

---

### Plan 4: Introduced Algorithm Spec Checker

Verify that infrastructure algorithms (retry, circuit breaking, etc.) that have no algorithmic origin carry their own spec comments.

**Files to create:**

- `scripts/spec_manager/spec_manager/compliance/promotion/introduction_checker.py`

**Data structures:**

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IntroducedAlgorithm:
    """An architectural algorithm with no algorithmic origin.

    Attributes:
        function_name: Qualified name of the introduced function.
        file_path: File where the function is defined.
        line_start: First line.
        line_end: Last line.
        has_spec_comments: Whether the function body contains spec comments
            (which is required -- introduced algorithms must have their own spec).
        spec_comment_count: Number of spec comments found.
        has_docstring: Whether it has a docstring.
        category: Classification of the introduced algorithm type.
    """
    function_name: str
    file_path: str
    line_start: int
    line_end: int
    has_spec_comments: bool = False
    spec_comment_count: int = 0
    has_docstring: bool = False
    category: str = "unknown"  # "retry", "circuit_breaker", "routing", "serialization", etc.
```

**Function signatures:**

```python
from pathlib import Path

from spec_manager.compliance.promotion.config import GateSpec
from spec_manager.compliance.promotion.pin_coverage import PinCoverageReport
from spec_manager.compliance.promotion.result import GateCheckResult


def find_introduced_algorithms(
    pin_coverage: PinCoverageReport,
    architectural_files: list[Path],
) -> list[IntroducedAlgorithm]:
    """Find all introduced algorithms in the architectural layer.

    An introduced algorithm is a function/method in the architectural layer
    that has no pin-function import (identified via PinCoverageReport).

    For each introduced algorithm:
    1. AST-parse the file to extract the function body.
    2. Scan the body for spec comments using the comment scanner.
    3. Classify the algorithm category by heuristics (function name,
       module path, decorator patterns).

    Classification heuristics:
    - Functions in infrastructure/ -> infer from name/decorators
    - Names containing "retry", "backoff" -> "retry"
    - Names containing "circuit", "breaker" -> "circuit_breaker"
    - Names containing "route", "dispatch" -> "routing"
    - Names containing "serial", "deserial", "marshal" -> "serialization"
    - Default: "infrastructure"

    Args:
        pin_coverage: Coverage report identifying unpinned locations.
        architectural_files: Architectural files to scan.

    Returns:
        List of IntroducedAlgorithm with spec status.
    """


def check_introduced_algorithm_specs(
    pin_coverage: PinCoverageReport,
    architectural_files: list[Path],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: Introduced algorithms must have spec comments.

    Per design doc Section 12: "architectural algorithms (retry, circuit
    breaking) that have no algorithmic origin must have their own spec
    comments (they are their own mini algorithmic layer for infrastructure)."

    gate_spec.params:
        - require_docstring (bool, default True): Also require docstrings.
        - min_spec_comments (int, default 1): Minimum spec comments required.

    Args:
        pin_coverage: PinCoverageReport from pin_coverage.py.
        architectural_files: Architectural layer files.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for each introduced algorithm
        missing spec comments.
    """
```

**Implementation notes:**
- `find_introduced_algorithms` leverages the `PinCoverageReport` from Plan 3 to identify which architectural locations are introductions.
- Spec comment scanning reuses `scan_comments()` from Plan 05, but inverts the logic: for introduced algorithms, having spec comments is *required* (they document the infrastructure algorithm's intent), whereas for regular algorithmic code, having spec comments means the code is *incomplete*.
- Category classification uses simple name/path heuristics. This is intentionally kept simple; a more sophisticated classification can be added later via configurable patterns.

**Integration points:**
- Consumes `PinCoverageReport` from Plan 3.
- Reuses `scan_comments()` from `compliance.detection.comment_scanner` (Plan 05) for comment detection.

**Tests:** `scripts/spec_manager/tests/compliance/promotion/test_introduction_checker.py`
- Create a mock `PinCoverageReport` with introduction locations. Write fixture files with and without spec comments.
- Verify that introduced algorithms without spec comments are flagged.
- Verify that introduced algorithms with spec comments pass.
- Verify category classification heuristics.

---

### Plan 5: Provenance Tracking for Atom Functions

Add provenance metadata to pin-functions: `introduced_by`, `modified_by`, and `source_location` chains.

**Files to create:**

- `scripts/spec_manager/spec_manager/compliance/promotion/provenance.py`

**Data structures:**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AtomProvenance:
    """Provenance record for a single atom function.

    Mirrors TrackedUnit's provenance pattern but at the function level.

    Attributes:
        pin_func_id: Pin-function ID (e.g., "PFUNC-0001").
        function_name: Qualified function name.
        file_path: File where the function is defined.
        introduced_by: Plan/patch/commit that first created this function.
        modified_by: Ordered list of plans/patches/commits that modified it.
        source_location: Where in the spec research the function's details
            came from (file:section or evidence ID).
        content_hash: Current SHA-256 of function body.
        created_at: ISO-8601 timestamp of first detection.
        last_modified_at: ISO-8601 timestamp of last change detection.
    """
    pin_func_id: str
    function_name: str
    file_path: str
    introduced_by: str
    modified_by: list[str] = field(default_factory=list)
    source_location: str = ""
    content_hash: str = ""
    created_at: str = ""
    last_modified_at: str = ""

    def add_modification(self, modifier: str) -> None:
        """Record a modification."""
        if modifier not in self.modified_by:
            self.modified_by.append(modifier)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "pin_func_id": self.pin_func_id,
            "function_name": self.function_name,
            "file_path": self.file_path,
            "introduced_by": self.introduced_by,
            "modified_by": self.modified_by,
            "source_location": self.source_location,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "last_modified_at": self.last_modified_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AtomProvenance:
        """Deserialize from dictionary."""
        return cls(
            pin_func_id=data["pin_func_id"],
            function_name=data["function_name"],
            file_path=data["file_path"],
            introduced_by=data["introduced_by"],
            modified_by=data.get("modified_by", []),
            source_location=data.get("source_location", ""),
            content_hash=data.get("content_hash", ""),
            created_at=data.get("created_at", ""),
            last_modified_at=data.get("last_modified_at", ""),
        )


@dataclass
class ProvenanceRegistry:
    """Registry of all atom function provenance records.

    Persisted alongside the PinFunctionRegistry.

    Attributes:
        records: Provenance records keyed by pin_func_id.
        schema_version: Version of the provenance schema.
    """
    records: dict[str, AtomProvenance] = field(default_factory=dict)
    schema_version: str = "1.0"

    def get(self, pin_func_id: str) -> AtomProvenance | None:
        """Get provenance record by pin_func_id."""
        return self.records.get(pin_func_id)

    def upsert(self, provenance: AtomProvenance) -> None:
        """Insert or update a provenance record."""
        self.records[provenance.pin_func_id] = provenance

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "schema_version": self.schema_version,
            "records": {k: v.to_dict() for k, v in self.records.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceRegistry:
        """Deserialize from dictionary."""
        registry = cls(schema_version=data.get("schema_version", "1.0"))
        for key, record_data in data.get("records", {}).items():
            registry.records[key] = AtomProvenance.from_dict(record_data)
        return registry

    def save(self, path: Path) -> None:
        """Write provenance registry to disk."""
        import json
        from pathlib import Path as P
        path = P(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ProvenanceRegistry:
        """Load provenance registry from disk."""
        import json
        from pathlib import Path as P
        path = P(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
```

**Function signatures:**

```python
from pathlib import Path

from spec_manager.compliance.promotion.config import GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.schemas.pin_functions import PinFunctionRegistry


def update_provenance_from_registry(
    pin_registry: PinFunctionRegistry,
    existing_provenance: ProvenanceRegistry,
    modifier: str = "scan",
) -> ProvenanceRegistry:
    """Update provenance records based on current pin-function registry.

    For each pin-function in the registry:
    - If new (not in existing provenance): create record with introduced_by=modifier.
    - If content_hash changed: add modifier to modified_by chain.
    - If unchanged: no update.

    Args:
        pin_registry: Current PinFunctionRegistry.
        existing_provenance: Previous provenance state.
        modifier: Identifier for the current modification source.

    Returns:
        Updated ProvenanceRegistry.
    """


def check_provenance_complete(
    pin_registry: PinFunctionRegistry,
    provenance_registry: ProvenanceRegistry,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: All atom functions have complete provenance.

    Checks that every pin-function in the registry has a corresponding
    provenance record with non-empty introduced_by and source_location.

    gate_spec.params:
        - require_source_location (bool, default False): Whether
            source_location must be non-empty.

    Args:
        pin_registry: Current PinFunctionRegistry.
        provenance_registry: Current ProvenanceRegistry.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for functions missing provenance.
    """
```

**Implementation notes:**
- `AtomProvenance` mirrors the `TrackedUnit` provenance pattern (`introduced_by`, `modified_by`) but operates at the function level rather than the spec unit level.
- `ProvenanceRegistry` is persisted at `{project_root}/.spec/provenance_registry.json` alongside the pin registry.
- `update_provenance_from_registry` uses `PinFunction.content_hash` to detect changes -- if the hash differs from the stored hash, a modification is recorded.
- The `source_location` field is populated by agents during spec translation (when they convert a comment to code, they record which evidence informed the implementation). This check validates that the field was populated.

**Integration points:**
- Consumes `PinFunctionRegistry` and `PinFunction` from Plan 02.
- Follows the same provenance pattern as `TrackedUnit.introduced_by` / `TrackedUnit.modified_by` in `scripts/spec_manager/spec_manager/core/provenance.py`.
- Persistence follows the same pattern as `PinFunctionRegistry` JSON serialization.

**Tests:** `scripts/spec_manager/tests/compliance/promotion/test_provenance.py`
- Create a mock pin registry, run `update_provenance_from_registry` with no existing provenance, verify all records created with `introduced_by`.
- Modify one function's content_hash, re-run, verify `modified_by` chain updated.
- Verify `check_provenance_complete` flags functions missing provenance.
- Verify serialization round-trip (`to_dict` / `from_dict`).
- Verify `save` / `load` persistence.

---

### Plan 6: Architectural Quality Checks

Verify architectural layer quality: no inlined atom logic and function recomposition verified.

**Files to create:**

- `scripts/spec_manager/spec_manager/compliance/promotion/architectural_quality.py`

**Function signatures:**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from spec_manager.compliance.promotion.config import GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.schemas.pin_functions import PinFunctionRegistry


@dataclass
class InlinedLogicFinding:
    """A location where atom logic appears to be copy-pasted inline.

    Attributes:
        arch_file: Architectural file path.
        arch_line_start: Start line of the suspected inlined code.
        arch_line_end: End line of the suspected inlined code.
        matching_pin_func_id: Pin-function whose logic appears inlined.
        similarity_score: 0.0-1.0 indicating how similar the code is.
        detection_method: How the duplication was detected.
    """
    arch_file: str
    arch_line_start: int
    arch_line_end: int
    matching_pin_func_id: str
    similarity_score: float
    detection_method: str  # "exact_match", "ast_similarity", "fingerprint_overlap"


def check_no_inlined_atom_logic(
    pin_registry: PinFunctionRegistry,
    architectural_files: list[Path],
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: No inlined atom logic in architectural layer.

    Per design doc Section 12: "if it's an atom, it must be a function call,
    not copy-pasted code."

    Detection strategies (applied in order):
    1. Exact body match: Hash the body of each architectural function/method,
       compare against pin-function content_hash values.
    2. AST structural similarity: Normalize AST (strip names, normalize
       constants), compare tree structure. Score > 0.8 is a finding.
    3. Line fingerprint overlap: Use the existing LineAtom SHA-256
       fingerprinting. If >60% of an architectural function's line
       fingerprints match a pin-function's lines, flag it.

    gate_spec.params:
        - similarity_threshold (float, default 0.8): Minimum AST similarity
            to flag.
        - fingerprint_overlap_threshold (float, default 0.6): Minimum line
            fingerprint overlap to flag.
        - exclude_patterns (list[str]): File patterns to skip.

    Args:
        pin_registry: PinFunctionRegistry with atom content hashes.
        architectural_files: Architectural layer files to scan.
        algorithmic_files: Algorithmic layer files (for body extraction).
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for each inlined logic instance.
    """


def check_function_recomposition(
    pin_registry: PinFunctionRegistry,
    architectural_files: list[Path],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: Architectural functions correctly recompose atoms.

    Verifies that architectural code composes pin-functions via imports
    and calls rather than reimplementing logic. This is complementary to
    check_no_inlined_atom_logic but focuses on structural composition:

    For each architectural function that imports pin-functions:
    1. Verify all imported pin-functions are actually called (no dead imports).
    2. Verify call signatures match pin-function signatures (no arg mismatch).
    3. Verify no local variables shadow imported pin-function names.

    gate_spec.params:
        - check_dead_imports (bool, default True): Flag unused pin-function imports.
        - check_signature_match (bool, default True): Verify call arg counts.

    Args:
        pin_registry: PinFunctionRegistry.
        architectural_files: Architectural layer files.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for recomposition issues.
    """
```

**Implementation notes:**
- Exact body match uses SHA-256 hashes already computed by `PinFunction.content_hash`. This is O(n*m) where n=architectural functions and m=pin-functions, but both are expected to be small (hundreds, not millions).
- AST structural similarity normalizes the AST by replacing all `ast.Name` nodes with a placeholder and all `ast.Constant` nodes with type-only markers, then compares tree depth and node counts. This detects renamed-but-identical logic.
- Line fingerprint overlap reuses the `LineAtom.sha256` fingerprinting approach from `scripts/spec_manager/spec_manager/schemas/atoms.py`.
- Signature matching extracts `ast.FunctionDef.args` from both the pin-function definition and the call site, comparing positional arg count and keyword arg names.

**Integration points:**
- Consumes `PinFunctionRegistry` from Plan 02.
- AST analysis is consistent with the approach in Plan 02's `AtomFunctionExtractor`.
- Line fingerprinting follows existing `LineAtom.sha256` patterns from `scripts/spec_manager/spec_manager/schemas/atoms.py`.

**Tests:** `scripts/spec_manager/tests/compliance/promotion/test_architectural_quality.py`
- Create fixture files where an architectural file copy-pastes an atom function body. Verify detection.
- Create fixture files where an architectural file properly imports and calls atoms. Verify no false positives.
- Verify dead import detection.
- Verify signature mismatch detection.
- Verify AST similarity scoring with renamed variables.

---

### Plan 7: Promotion Orchestrator and Compliance Integration

Wire all gate checks into a single orchestrator and integrate with the existing compliance module.

**Files to create:**

- `scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py`

**Files to modify:**

- `scripts/spec_manager/spec_manager/compliance/__init__.py` -- export promotion API
- `scripts/spec_manager/spec_manager/compliance/scorer.py` -- add `score_promotion_compliance` method

**Orchestrator API:**

```python
from __future__ import annotations

import time
from pathlib import Path

from spec_manager.compliance.promotion.config import (
    GateId,
    GateMode,
    PromotionGateConfig,
)
from spec_manager.compliance.promotion.result import (
    GateCheckResult,
    PromotionReport,
)
from spec_manager.schemas.pin_functions import PinFunctionRegistry


class LayerPromotionGate:
    """Orchestrates all promotion gate checks.

    Usage:
        config = PromotionGateConfig.default()
        gate = LayerPromotionGate(config, pin_registry)
        report = gate.run_all_checks()
        if report.passed:
            # Safe to promote to architectural branch
            ...
        else:
            for blocker in report.blockers:
                print(f"BLOCKED: {blocker.gate_id}: {blocker.summary}")
    """

    def __init__(
        self,
        config: PromotionGateConfig,
        pin_registry: PinFunctionRegistry | None = None,
        provenance_registry_path: Path | None = None,
    ) -> None:
        """Initialize the promotion gate.

        Args:
            config: Gate configuration.
            pin_registry: PinFunctionRegistry for pin coverage checks.
                If None, pin-related gates are skipped with a warning.
            provenance_registry_path: Path to the provenance registry JSON.
                If None, provenance gate is skipped with a warning.
        """

    def run_all_checks(self) -> PromotionReport:
        """Run all enabled gate checks and produce a promotion report.

        Gate execution order:
        1. Algorithmic layer gates (comments, stubs, tests, call graph, stores)
        2. Pin coverage check
        3. Introduced algorithm spec check
        4. Provenance completeness check
        5. Architectural quality checks (inlined logic, recomposition)

        Returns:
            PromotionReport with all gate results.
        """

    def run_single_check(self, gate_id: GateId) -> GateCheckResult:
        """Run a single gate check by ID.

        Args:
            gate_id: Which gate to run.

        Returns:
            GateCheckResult for the specified gate.
        """

    def _resolve_files(self, roots: list[str]) -> list[Path]:
        """Resolve directory roots to Python file lists.

        Args:
            roots: Directory paths relative to project root.

        Returns:
            List of .py files found in the directories.
        """

    def _build_report(
        self,
        results: list[GateCheckResult],
        total_duration_ms: float,
    ) -> PromotionReport:
        """Build the final report from individual results.

        Separates blockers (REQUIRED mode + failed) from warnings
        (ADVISORY mode + failed). Sets passed=True only if zero blockers.

        Args:
            results: All gate check results.
            total_duration_ms: Total wall-clock time.

        Returns:
            PromotionReport.
        """
```

**Changes to `compliance/__init__.py`:**

```python
# Add to imports:
from spec_manager.compliance.promotion import (
    LayerPromotionGate,
    PromotionGateConfig,
    PromotionReport,
    GateCheckResult,
    GateId,
    GateMode,
    GateSpec,
)

# Add to __all__:
"LayerPromotionGate",
"PromotionGateConfig",
"PromotionReport",
"GateCheckResult",
"GateId",
"GateMode",
"GateSpec",
```

**Changes to `compliance/scorer.py`:**

Add a new method to `ComplianceScorer`:

```python
def score_promotion_compliance(
    self,
    config: PromotionGateConfig,
    pin_registry: PinFunctionRegistry | None = None,
    provenance_registry_path: Path | None = None,
) -> ComplianceResult:
    """Score compliance for layer promotion.

    Creates a LayerPromotionGate, runs all checks, and converts
    the PromotionReport into a ComplianceResult for compatibility
    with the existing compliance pipeline.

    Args:
        config: Promotion gate configuration.
        pin_registry: PinFunctionRegistry (optional).
        provenance_registry_path: Path to provenance registry (optional).

    Returns:
        ComplianceResult with blockers/warnings from promotion gates.
    """
```

**Integration points:**
- Orchestrator consumes all gate check functions from Plans 2-6.
- `ComplianceResult` from `scripts/spec_manager/spec_manager/compliance/scorer.py` is the bridge between promotion gating and the existing compliance pipeline.
- `PromotionReport.save()` writes to `{project_root}/.spec/promotion_report.json`.
- The existing `WorkflowConfig.compliance_gate_mode` (block/warn) maps to `GateMode.REQUIRED` / `GateMode.ADVISORY` for the overall promotion decision.

**Tests:** `scripts/spec_manager/tests/compliance/promotion/test_orchestrator.py`
- Integration test: create a fixture project with known gate pass/fail conditions, run full orchestrator, verify report accuracy.
- Verify that REQUIRED gate failures produce blockers.
- Verify that ADVISORY gate failures produce warnings but do not block.
- Verify that disabled gates are skipped.
- Verify `score_promotion_compliance` returns a valid `ComplianceResult`.
- Verify report serialization and persistence.

## Execution Instructions

Execute plans sequentially (Plan 1 through Plan 7). Each plan is independently testable but depends on types defined in prior plans.

1. **Plan 1**: Core data structures. No external dependencies beyond existing `core/gaps.py`. Test with unit tests for configuration and serialization.
2. **Plan 2**: Algorithmic gates. Depends on Plan 1 types and Plan 05 scanners (comment_scanner, stub_scanner, call_graph). If Plan 05 modules are not yet implemented, gate functions should degrade gracefully by returning advisory warnings. Test with fixture Python files.
3. **Plan 3**: Pin coverage. Depends on Plan 1 types and Plan 02 pin-function schemas. If Plan 02 is not yet implemented, create minimal mock schemas for testing. Test with mock registries and fixture architectural files.
4. **Plan 4**: Introduced algorithm checker. Depends on Plan 1 types and Plan 3's PinCoverageReport. Test with fixture infrastructure files.
5. **Plan 5**: Provenance tracking. Depends on Plan 1 types and Plan 02 pin-function schemas. Can be developed in parallel with Plans 3-4. Test with mock registries.
6. **Plan 6**: Architectural quality checks. Depends on Plan 1 types and Plan 02 pin-function schemas. Can be developed in parallel with Plans 3-5. Test with fixture files containing duplicated vs. properly imported logic.
7. **Plan 7**: Orchestrator wiring. Depends on all prior plans. Integration test end-to-end.

Plans 3, 4, 5, and 6 have no mutual dependencies and can be developed in parallel after Plan 2 is complete.

For each plan, run tests with: `uv run python -m pytest scripts/spec_manager/tests/compliance/promotion/ -v`

## Success Criteria

1. **Algorithmic gate enforcement**: Given algorithmic code with remaining comments, `check_no_remaining_comments()` returns `passed=False` with findings listing each comment's file, line, and text. Given clean algorithmic code with zero comments and zero stubs, both comment and stub gates return `passed=True`.

2. **Test gate execution**: `check_all_tests_pass()` runs the configured test command via subprocess, returns `passed=True` when exit code is 0, and `passed=False` with captured output when tests fail.

3. **Call graph connectivity**: `check_call_graph_connected()` identifies disconnected components of size >= `min_component_size` and includes them in findings.

4. **Store monogamy enforcement**: `check_store_monogamy()` detects when a store module is imported by files in multiple vertical slices and reports each violation.

5. **Pin coverage accuracy**: `check_pin_coverage()` correctly calculates coverage ratio excluding introductions. Given a registry where all architectural locations have pin imports, coverage is 1.0. Given one unpinned non-introduction location, coverage drops below 1.0 and the location appears in findings.

6. **Introduction spec enforcement**: `check_introduced_algorithm_specs()` flags introduced algorithms missing spec comments while allowing those that have spec comments to pass.

7. **Provenance completeness**: `check_provenance_complete()` flags pin-functions with no provenance record. `update_provenance_from_registry()` correctly creates new records for new functions and appends to `modified_by` for changed functions.

8. **Inlined logic detection**: `check_no_inlined_atom_logic()` detects exact body matches and AST-similar code with zero false positives on properly imported atoms.

9. **Gate mode separation**: Failed REQUIRED gates appear in `PromotionReport.blockers` and cause `passed=False`. Failed ADVISORY gates appear in `PromotionReport.warnings` and do not affect `passed`.

10. **Compliance integration**: `ComplianceScorer.score_promotion_compliance()` returns a `ComplianceResult` with promotion gate findings formatted as blockers/warnings, compatible with the existing compliance pipeline.

11. **Serialization round-trip**: `PromotionReport.to_dict()` and `ProvenanceRegistry.to_dict()` / `from_dict()` preserve all data through JSON serialization.

12. **Test coverage**: Each plan has corresponding test files with >90% line coverage of the new modules.
