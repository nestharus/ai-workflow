"""Algorithmic layer gate checks for promotion gating.

Implements the five algorithmic layer cleanliness gates:
1. No remaining comments
2. No stub functions
3. All tests pass
4. Call graph connected
5. Store monogamy
"""

from __future__ import annotations

import ast
import subprocess
import time
from pathlib import Path
from typing import Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult


def _scan_comments_fallback(file_path: Path) -> list[dict[str, Any]]:
    """Fallback comment scanner when Plan 05 modules are not available.

    Scans for spec-style comments (lines starting with # that look like
    spec annotations or TODO/FIXME markers within function bodies).
    """
    findings: list[dict[str, Any]] = []
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return findings

    lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        func_name = node.name
        func_start = node.lineno
        func_end = node.end_lineno or func_start

        for line_no in range(func_start, min(func_end + 1, len(lines) + 1)):
            line = lines[line_no - 1]
            stripped = line.strip()
            if stripped.startswith("#"):
                comment_text = stripped.lstrip("#").strip()
                # Skip shebangs and encoding declarations
                if comment_text.startswith("!") or "coding" in comment_text:
                    continue
                findings.append({
                    "file_path": str(file_path),
                    "line": line_no,
                    "text": comment_text,
                    "enclosing_function": func_name,
                })

    return findings


def _scan_stubs_fallback(file_path: Path) -> list[dict[str, Any]]:
    """Fallback stub scanner when Plan 05 modules are not available.

    Detects functions with stub bodies: pass, ..., raise NotImplementedError, etc.
    """
    findings: list[dict[str, Any]] = []
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Get the body statements, skipping docstrings
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
        ):
            body = body[1:]

        if not body:
            findings.append({
                "file_path": str(file_path),
                "line": node.lineno,
                "name": node.name,
                "stub_type": "empty_body",
            })
            continue

        if len(body) == 1:
            stmt = body[0]
            # pass statement
            if isinstance(stmt, ast.Pass):
                findings.append({
                    "file_path": str(file_path),
                    "line": node.lineno,
                    "name": node.name,
                    "stub_type": "pass",
                })
            # Ellipsis (...)
            elif (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is ...
            ):
                findings.append({
                    "file_path": str(file_path),
                    "line": node.lineno,
                    "name": node.name,
                    "stub_type": "ellipsis",
                })
            # raise NotImplementedError
            elif isinstance(stmt, ast.Raise):
                exc = stmt.exc
                if exc is not None:
                    exc_name = None
                    if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                        exc_name = exc.func.id
                    elif isinstance(exc, ast.Name):
                        exc_name = exc.id
                    if exc_name == "NotImplementedError":
                        findings.append({
                            "file_path": str(file_path),
                            "line": node.lineno,
                            "name": node.name,
                            "stub_type": "not_implemented",
                        })

    return findings


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

    # Try to use Plan 05 scanner first, fall back to built-in
    try:
        from spec_manager.compliance.detection.comment_scanner import scan_comments

        for f in algorithmic_files:
            gaps = scan_comments(f)
            for gap in gaps:
                all_findings.append({
                    "file_path": gap.file_path,
                    "line": gap.line,
                    "text": gap.text,
                    "enclosing_function": gap.enclosing_function,
                })
    except ImportError:
        for f in algorithmic_files:
            all_findings.extend(_scan_comments_fallback(f))

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

    try:
        from spec_manager.compliance.detection.stub_scanner import scan_stubs

        for f in algorithmic_files:
            stubs = scan_stubs(f)
            for stub in stubs:
                all_findings.append({
                    "file_path": stub.file_path,
                    "line": stub.line,
                    "name": stub.name,
                    "stub_type": stub.stub_type,
                })
    except ImportError:
        for f in algorithmic_files:
            all_findings.extend(_scan_stubs_fallback(f))

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
            findings.append({
                "returncode": result.returncode,
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
            })
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
            "All algorithmic tests passed"
            if passed
            else f"Test command failed: {output[:200]}"
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
                    name for name in component
                    if not any(pat in name for pat in ignore_patterns)
                ]
                if len(filtered) >= min_component_size:
                    findings.append({
                        "component_size": len(filtered),
                        "functions": sorted(filtered),
                    })
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
    """Fallback call graph analysis using AST-based function/call extraction.

    Builds a simple graph of function definitions and function calls,
    then finds disconnected components via union-find.
    """
    # Collect all defined functions and their calls
    func_defs: dict[str, str] = {}  # func_name -> file_path
    func_calls: dict[str, set[str]] = {}  # caller -> {callees}

    for file_path in algorithmic_files:
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                func_defs[func_name] = str(file_path)
                calls: set[str] = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            calls.add(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            calls.add(child.func.attr)
                func_calls[func_name] = calls

    # Build adjacency and find connected components via union-find
    all_funcs = set(func_defs.keys())
    if not all_funcs:
        return []

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
        filtered = [
            name for name in component
            if not any(pat in name for pat in ignore_patterns)
        ]
        if len(filtered) >= min_component_size:
            findings.append({
                "component_size": len(filtered),
                "functions": sorted(filtered),
            })

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
    store_importers: dict[str, set[str]] = {
        name: set() for name in store_modules
    }

    for f in algorithmic_files:
        if f in store_files:
            continue

        try:
            source = f.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(f))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        # Determine vertical slice for this file
        try:
            rel = f.relative_to(project_root)
        except ValueError:
            rel = f
        parts = rel.parts
        vertical = "/".join(parts[:vertical_depth]) if len(parts) >= vertical_depth else str(rel)

        # Scan imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name.split(".")[-1]
                    if name in store_modules:
                        store_importers[name].add(vertical)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_parts = node.module.split(".")
                    # Check if any part of the import path matches a store module
                    for part in module_parts:
                        if part in store_modules:
                            store_importers[part].add(vertical)
                    # Also check imported names
                    for alias in node.names:
                        if alias.name in store_modules:
                            store_importers[alias.name].add(vertical)

    # Step 3: Flag stores accessed by multiple verticals
    for store_name, verticals in store_importers.items():
        if len(verticals) > 1:
            findings.append({
                "store_name": store_name,
                "store_file": str(store_modules[store_name]),
                "verticals": sorted(verticals),
                "vertical_count": len(verticals),
            })

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
            else (
                f"Found {len(findings)} store(s) accessed by multiple vertical slices"
            )
        ),
        duration_ms=duration,
    )
