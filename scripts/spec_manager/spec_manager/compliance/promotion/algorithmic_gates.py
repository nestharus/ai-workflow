"""Algorithmic layer gate checks for promotion gating.

Implements the five algorithmic layer cleanliness gates:
1. No remaining comments
2. No stub functions
3. All tests pass
4. Call graph connected
5. Store monogamy
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

from spec_manager.compliance.detection.comment_scanner import scan_comments
from spec_manager.compliance.detection.stub_scanner import scan_stubs
from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.core.code_analysis import analyze_source

# Regex patterns for text-based import scanning (used by check_store_monogamy)
_IMPORT_RE = re.compile(r"^\s*import\s+(.+)", re.MULTILINE)
_FROM_IMPORT_RE = re.compile(r"^\s*from\s+(\S+)\s+import\s+(.+)", re.MULTILINE)


def check_no_remaining_comments(
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: No remaining comments in algorithmic code.

    Scans algorithmic files for comments inside function bodies.
    In algorithmic code, every comment is an unimplemented spec element.

    Each finding includes:
        - file_path, line, text, enclosing_function

    Args:
        algorithmic_files: Python files in the algorithmic layer.
        gate_spec: Gate configuration (mode, threshold).

    Returns:
        GateCheckResult with passed=True only if zero spec comments found.
    """
    start = time.monotonic()
    all_findings: list[dict[str, Any]] = []

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
) -> GateCheckResult:
    """Gate: No stub functions in algorithmic code.

    Scans algorithmic files for stub functions (pass, ..., raise NotImplementedError).

    Each finding includes:
        - file_path, line, name, stub_type

    Args:
        algorithmic_files: Python files in the algorithmic layer.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with passed=True only if zero stubs found.
    """
    start = time.monotonic()
    all_findings: list[dict[str, Any]] = []

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
) -> GateCheckResult:
    """Gate: Call graph has no orphaned algorithms.

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
    start = time.monotonic()
    min_component_size = gate_spec.params.get("min_component_size", 2)
    ignore_patterns: list[str] = gate_spec.params.get("ignore_patterns", [])
    findings: list[dict[str, Any]] = []

    try:
        from spec_manager.compliance.detection.call_graph import (
            build_call_graph,
        )

        graph = build_call_graph(algorithmic_files, project_root)
        components = graph.get_connected_components()
        # Only flag if there are multiple components (disconnected graph)
        if len(components) > 1:
            # Sort by size descending, skip the largest (main component)
            sorted_components = sorted(components, key=len, reverse=True)
            for component in sorted_components[1:]:
                filtered = [
                    name for name in component if not any(pat in name for pat in ignore_patterns)
                ]
                if len(filtered) >= min_component_size:
                    findings.append(
                        {
                            "component_size": len(filtered),
                            "functions": sorted(filtered),
                        }
                    )
    except ImportError:
        # Plan 05 not yet available, degrade gracefully
        findings = _build_call_graph_fallback(
            algorithmic_files, min_component_size, ignore_patterns
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


def _build_call_graph_fallback(
    algorithmic_files: list[Path],
    min_component_size: int,
    ignore_patterns: list[str],
) -> list[dict[str, Any]]:
    """Fallback call graph analysis using analyze_source() and regex-based call extraction.

    Uses analyze_source() for function definitions and regex on source lines
    for approximate call detection, then finds disconnected components via union-find.
    """
    # Collect all defined functions and their calls
    func_defs: dict[str, str] = {}  # func_name -> file_path
    func_calls: dict[str, set[str]] = {}  # caller -> {callees}

    for file_path in algorithmic_files:
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        analysis = analyze_source(source, str(file_path))
        lines = source.splitlines()

        for func_info in analysis.functions:
            func_name = func_info.name
            func_defs[func_name] = str(file_path)

            # Extract the function body text from the source lines
            # body_start_line and end_line give us the range
            body_start = func_info.body_start_line
            body_end = func_info.end_line
            if body_start > 0 and body_end > 0 and body_end <= len(lines):
                body_lines = lines[body_start - 1 : body_end]
                body_text = "\n".join(body_lines)
            elif func_info.start_line > 0 and func_info.end_line > 0:
                body_lines = lines[func_info.start_line - 1 : func_info.end_line]
                body_text = "\n".join(body_lines)
            else:
                body_text = ""

            # Use regex to find call-like patterns in body text
            raw_calls = set(re.findall(r"\b(\w+)\s*\(", body_text))
            func_calls[func_name] = raw_calls

    # Build adjacency and find connected components via union-find
    all_funcs = set(func_defs.keys())
    if not all_funcs:
        return []

    # Filter calls to only known function names
    for caller in func_calls:
        func_calls[caller] = func_calls[caller] & all_funcs

    parent: dict[str, str] = {f: f for f in all_funcs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for caller, callees in func_calls.items():
        for callee in callees:
            if callee in all_funcs:
                union(caller, callee)

    # Group by root
    components: dict[str, list[str]] = {}
    for func in all_funcs:
        root = find(func)
        components.setdefault(root, []).append(func)

    # Only flag if there are multiple components (disconnected)
    if len(components) <= 1:
        return []

    findings: list[dict[str, Any]] = []
    # Sort components by size descending, skip the largest (main component)
    sorted_components = sorted(components.values(), key=len, reverse=True)
    for component in sorted_components[1:]:
        filtered = [name for name in component if not any(pat in name for pat in ignore_patterns)]
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
    store_patterns: list[str] = gate_spec.params.get(
        "store_patterns", ["**/stores/*.py", "**/stores/**/*.py"]
    )
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
        if module_name != "__init__":
            store_modules[module_name] = sf

    # Step 2: For each algorithmic file, find store imports
    store_importers: dict[str, set[str]] = {name: set() for name in store_modules}

    for f in algorithmic_files:
        if f in store_files:
            continue

        try:
            source = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Determine vertical slice for this file
        try:
            rel = f.relative_to(project_root)
        except ValueError:
            rel = f
        parts = rel.parts
        vertical = "/".join(parts[:vertical_depth]) if len(parts) >= vertical_depth else str(rel)

        # Scan imports using regex
        for match in _IMPORT_RE.finditer(source):
            # `import foo, bar.baz` -> extract each module
            import_text = match.group(1)
            for segment in import_text.split(","):
                segment = segment.strip()
                # Handle `import foo as bar` -> extract `foo`
                module_part = (
                    segment.split(" as ")[0].strip() if " as " in segment else segment.strip()
                )
                name = module_part.split(".")[-1]
                if name in store_modules:
                    store_importers[name].add(vertical)

        for match in _FROM_IMPORT_RE.finditer(source):
            module_path = match.group(1)
            imported_names = match.group(2)

            # Check if any part of the from-module path matches a store module
            module_parts = module_path.split(".")
            for part in module_parts:
                if part in store_modules:
                    store_importers[part].add(vertical)

            # Also check the imported names
            for segment in imported_names.split(","):
                segment = segment.strip()
                # Handle `from x import foo as bar` -> extract `foo`
                imported_name = (
                    segment.split(" as ")[0].strip() if " as " in segment else segment.strip()
                )
                if imported_name in store_modules:
                    store_importers[imported_name].add(vertical)

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
