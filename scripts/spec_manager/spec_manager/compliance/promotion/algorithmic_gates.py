"""Algorithmic layer gate checks for promotion gating.

Implements the five algorithmic layer cleanliness gates:
1. No remaining comments
2. No stub functions
3. All tests pass
4. Call graph connected
5. Store monogamy
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.branches.gap_detection import scan_comments, scan_stubs
from spec_manager.compliance.promotion.call_graph import (
    CallGraphEdge,
    StrategyRegistry,
    build_call_graph,
)
from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.projection.lineage.builder import scan_imports_from_files

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile


def check_no_remaining_comments(
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: No remaining comments in algorithmic code.

    Scans algorithmic files for comments inside function bodies.
    In algorithmic code, every comment is an unimplemented spec element.

    When *analyzed* is provided, uses pre-loaded SourceAnalysis data
    instead of reading files and scanning independently.

    Args:
        algorithmic_files: Python files in the algorithmic layer.
        gate_spec: Gate configuration (mode, threshold).
        analyzed: Pre-loaded file analyses (optional).

    Returns:
        GateCheckResult with passed=True only if zero spec comments found.
    """
    start = time.monotonic()
    all_findings: list[dict[str, Any]] = []

    if analyzed is not None:
        for af in analyzed:
            for comment in af.analysis.comments:
                all_findings.append(
                    {
                        "file_path": af.path,
                        "line": comment.line,
                        "text": comment.text,
                        "enclosing_function": comment.enclosing_function,
                    }
                )
    else:
        for f in algorithmic_files:
            gaps = scan_comments(f)
            for gap in gaps:
                all_findings.append(
                    {
                        "file_path": gap.file_path,
                        "line": gap.line,
                        "text": gap.text,
                        "enclosing_function": gap.enclosing_function,
                    }
                )

    passed = len(all_findings) == 0
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.NO_REMAINING_COMMENTS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=1.0 if passed else 0.0,
        findings=all_findings,
        summary=(
            "No spec comments found in algorithmic code"
            if passed
            else f"Found {len(all_findings)} spec comment(s) in algorithmic code"
        ),
        duration_ms=duration,
    )


def check_no_stub_functions(
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: No stub functions in algorithmic code.

    Scans algorithmic files for stub functions (pass, ..., raise NotImplementedError).

    When *analyzed* is provided, uses pre-loaded SourceAnalysis data.

    Args:
        algorithmic_files: Python files in the algorithmic layer.
        gate_spec: Gate configuration.
        analyzed: Pre-loaded file analyses (optional).

    Returns:
        GateCheckResult with passed=True only if zero stubs found.
    """
    start = time.monotonic()
    all_findings: list[dict[str, Any]] = []

    if analyzed is not None:
        for af in analyzed:
            for func in af.analysis.functions:
                if func.is_stub:
                    all_findings.append(
                        {
                            "file_path": af.path,
                            "line": func.start_line,
                            "name": func.name,
                            "stub_type": func.stub_reason or "unknown",
                        }
                    )
    else:
        for f in algorithmic_files:
            stubs = scan_stubs(f)
            for stub in stubs:
                all_findings.append(
                    {
                        "file_path": stub.file_path,
                        "line": stub.line,
                        "name": stub.name,
                        "stub_type": stub.stub_type,
                    }
                )

    passed = len(all_findings) == 0
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.NO_STUB_FUNCTIONS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=1.0 if passed else 0.0,
        findings=all_findings,
        summary=(
            "No stub functions found in algorithmic code"
            if passed
            else f"Found {len(all_findings)} stub function(s) in algorithmic code"
        ),
        duration_ms=duration,
    )


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
    start = time.monotonic()
    timeout_seconds = gate_spec.params.get("timeout_seconds", 300)

    try:
        result = subprocess.run(
            test_command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        passed = result.returncode == 0
        output = result.stdout + result.stderr
        findings: list[dict[str, Any]] = []
        if not passed:
            findings.append(
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout[:2000],
                    "stderr": result.stderr[:2000],
                }
            )
    except subprocess.TimeoutExpired:
        passed = False
        output = f"Test command timed out after {timeout_seconds}s"
        findings = [{"error": output}]
    except FileNotFoundError:
        passed = False
        output = f"Test command not found: {test_command}"
        findings = [{"error": output}]

    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.ALL_TESTS_PASS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=1.0 if passed else 0.0,
        findings=findings,
        summary=(
            "All algorithmic tests passed" if passed else f"Test command failed: {output[:200]}"
        ),
        duration_ms=duration,
    )


def check_call_graph_connected(
    algorithmic_files: list[Path],
    project_root: Path,
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
    registry: StrategyRegistry | None = None,
) -> GateCheckResult:
    """Gate: Call graph has no orphaned algorithms.

    Checks for disconnected components above the configured minimum size.

    When *analyzed* is provided, uses pre-loaded analyses instead of
    reading files.

    gate_spec.params:
        - min_component_size (int, default 2): Minimum component size to flag.
        - ignore_patterns (list[str]): Function name patterns to exclude.
        - entry_points (list[str]): Function names or dotted paths treated as external
          execution roots when extraction misses dynamic dispatch.

    Args:
        algorithmic_files: Python files to analyze.
        project_root: For module path resolution.
        gate_spec: Gate configuration.
        analyzed: Pre-loaded file analyses (optional).

    Returns:
        GateCheckResult with findings for each disconnected component.
    """
    start = time.monotonic()
    min_component_size = gate_spec.params.get("min_component_size", 2)
    ignore_patterns: list[str] = gate_spec.params.get("ignore_patterns", [])
    entry_points: list[str] = gate_spec.params.get("entry_points", [])
    graph_result = build_call_graph(
        algorithmic_files=algorithmic_files,
        project_root=project_root,
        analyzed=analyzed,
        registry=registry,
    )
    findings = _find_disconnected_components(
        nodes=graph_result.nodes,
        edges=graph_result.edges,
        ignore_patterns=ignore_patterns,
        entry_points=entry_points,
        min_component_size=min_component_size,
    )

    passed = len(findings) == 0
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.CALL_GRAPH_CONNECTED.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=1.0 if passed else max(0.0, 1.0 - len(findings) * 0.1),
        findings=findings,
        summary=(
            "Call graph is fully connected"
            if passed
            else f"Found {len(findings)} disconnected component(s) in call graph"
        ),
        duration_ms=duration,
    )


def _find_disconnected_components(
    nodes: set[str],
    edges: list[CallGraphEdge],
    ignore_patterns: list[str] | None,
    entry_points: list[str] | None = None,
    min_component_size: int = 2,
) -> list[dict[str, Any]]:
    """Find disconnected components from extracted graph data.

    Args:
        nodes: Known function nodes from graph extraction.
        edges: Call edges to evaluate for connectivity.
        ignore_patterns: Optional name substrings excluded from findings.
        entry_points: Optional external roots.
        min_component_size: Minimum filtered component size to flag.
    """
    if not nodes:
        return []
    normalized_ignore_patterns = ignore_patterns or []

    parent: dict[str, str] = {f: f for f in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        if a not in parent or b not in parent:
            return
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for edge in edges:
        union(edge.caller, edge.callee)

    # Group by root
    components: dict[str, list[str]] = {}
    for func in nodes:
        root = find(func)
        components.setdefault(root, []).append(func)

    # Only flag if there are multiple components (disconnected)
    if len(components) <= 1:
        return []

    findings: list[dict[str, Any]] = []
    normalized_entry_points = {
        item.strip() for item in (entry_points or []) if isinstance(item, str) and item.strip()
    }
    protected_roots: set[str] = set()
    for func_name in nodes:
        short_name = func_name.rsplit(".", 1)[-1]
        if func_name in normalized_entry_points or short_name in normalized_entry_points:
            protected_roots.add(find(func_name))
        for declared in normalized_entry_points:
            if declared.endswith(".*") and func_name.startswith(declared[:-2]):
                protected_roots.add(find(func_name))

    # Legacy fallback when no entry points are declared.
    if not protected_roots and components:
        largest = sorted(components.values(), key=len, reverse=True)[0]
        protected_roots.add(find(largest[0]))

    # Sort components by size descending for deterministic findings.
    sorted_components = sorted(components.values(), key=len, reverse=True)
    for component in sorted_components:
        component_root = find(component[0])
        if component_root in protected_roots:
            continue
        filtered = [
            name for name in component if not any(pat in name for pat in normalized_ignore_patterns)
        ]
        if len(filtered) >= min_component_size:
            findings.append(
                {
                    "component_size": len(filtered),
                    "functions": sorted(filtered),
                }
            )

    return findings


def check_store_monogamy(
    algorithmic_files: list[Path],
    project_root: Path,
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: Each store is accessed by only one vertical slice.

    Scans algorithmic code for store access patterns and maps each store
    to the vertical slice(s) that access it. Flags stores accessed by
    multiple verticals.

    Detection strategy:
    1. Identify store definitions by convention (files in stores/ directories).
    2. For each store, find all modules that import/reference it.
    3. Map importing modules to their vertical slice (by directory structure).
    4. Stores referenced by >1 vertical are violations.

    gate_spec.params:
        - store_patterns (list[str]): Glob patterns for store files.
        - vertical_depth (int): Directory depth that defines a vertical boundary.

    Args:
        algorithmic_files: Python files to analyze.
        project_root: Root directory.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for each store monogamy violation.
    """
    start = time.monotonic()
    from spec_manager.core.language import SOURCE_EXTENSIONS

    _default_store_patterns = [f"**/stores/*{ext}" for ext in sorted(SOURCE_EXTENSIONS)] + [
        f"**/stores/**/*{ext}" for ext in sorted(SOURCE_EXTENSIONS)
    ]
    store_patterns: list[str] = gate_spec.params.get("store_patterns", _default_store_patterns)
    vertical_depth: int = gate_spec.params.get("vertical_depth", 2)
    findings: list[dict[str, Any]] = []

    # Step 1: Identify store modules
    store_files: set[Path] = set()
    for pattern in store_patterns:
        store_files.update(project_root.glob(pattern))
    # Also add any algorithmic files that are in a "stores" directory
    for f in algorithmic_files:
        parts = f.parts
        if "stores" in parts:
            store_files.add(f)

    if not store_files:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.STORE_MONOGAMY.value,
            passed=True,
            mode=gate_spec.mode.value,
            score=1.0,
            findings=[],
            summary="No store files found to check",
            duration_ms=duration,
        )

    # Extract store module names from store files
    store_modules: dict[str, Path] = {}
    for sf in store_files:
        # Use the stem as the store module name
        module_name = sf.stem
        from spec_manager.core.language import is_package_marker

        if not is_package_marker(sf.name):
            store_modules[module_name] = sf

    # Step 2: For each algorithmic file, find store imports using evidence-based scanning
    store_importers: dict[str, set[str]] = {name: set() for name in store_modules}

    non_store_files = [f for f in algorithmic_files if f not in store_files]
    import_records = scan_imports_from_files(non_store_files)

    for record in import_records:
        # Determine vertical slice for the importing file
        try:
            rel = Path(record.importer_file).relative_to(project_root)
        except ValueError:
            rel = Path(record.importer_file)
        parts = rel.parts
        vertical = "/".join(parts[:vertical_depth]) if len(parts) >= vertical_depth else str(rel)

        # Check if the imported name matches a store module
        if record.imported_name in store_modules:
            store_importers[record.imported_name].add(vertical)

        # Check if any part of the from-module path matches a store module
        module_parts = record.imported_from_module.split(".")
        for part in module_parts:
            if part in store_modules:
                store_importers[part].add(vertical)

    # Step 3: Flag stores accessed by multiple verticals
    for store_name, verticals in store_importers.items():
        if len(verticals) > 1:
            findings.append(
                {
                    "store_name": store_name,
                    "store_file": str(store_modules[store_name]),
                    "verticals": sorted(verticals),
                    "vertical_count": len(verticals),
                }
            )

    passed = len(findings) == 0
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.STORE_MONOGAMY.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=1.0 if passed else max(0.0, 1.0 - len(findings) * 0.2),
        findings=findings,
        summary=(
            "All stores are accessed by single vertical slices"
            if passed
            else (f"Found {len(findings)} store(s) accessed by multiple vertical slices")
        ),
        duration_ms=duration,
    )
