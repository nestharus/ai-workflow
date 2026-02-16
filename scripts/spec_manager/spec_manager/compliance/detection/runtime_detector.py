"""Runtime gap detector for executable gap detection.

Executes algorithmic code in a subprocess sandbox and catches
NotImplementedError at runtime as proof of gaps.

NOTE: This module is inherently Python-specific (generates probe scripts).
The probe script generation, module-path resolution, and subprocess invocation
all assume a Python runtime.  See ``spec_manager.core.language`` for the
centralised language constants used elsewhere.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from spec_manager.branches.gap_detection import StubFunction
from spec_manager.core.gap import GapEvidence

# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class ExecutableGapDetector(Protocol):
    """Plugin interface for runtime gap detection strategies.

    Any implementation must be able to probe stub functions and convert
    the results into ``GapEvidence`` items.
    """

    def probe_stubs(
        self,
        stubs: list[StubFunction],
        project_root: Path,
        timeout_seconds: float = 5.0,
    ) -> list[RuntimeProbeResult]: ...

    def results_to_gap_evidence(
        self,
        results: list[RuntimeProbeResult],
    ) -> list[GapEvidence]: ...


@dataclass
class RuntimeGap:
    """A function that raised NotImplementedError at runtime."""

    file_path: str
    function_name: str
    error_message: str
    traceback_summary: str
    call_chain: list[str]


@dataclass
class RuntimeProbeResult:
    """Result of probing a single function."""

    function_name: str
    module_path: str
    status: Literal["ok", "not_implemented", "error", "timeout", "unprobeable"]
    error_message: str = ""
    traceback_summary: str = ""
    call_chain: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


def generate_probe_script(
    module_path: str,
    function_name: str,
    test_inputs: dict[str, Any] | None = None,
) -> str:
    """Generate a Python script that imports and calls the target function.

    The script:
    1. Imports the module
    2. Calls the function with test_inputs (or no args if None)
    3. Prints a JSON result: {"status": "ok"} or {"status": "not_implemented", ...}
    4. Catches NotImplementedError specially, all others as "error"

    Args:
        module_path: Dotted module path (e.g., "spec_manager.intake.router")
        function_name: Function to call within the module
        test_inputs: Optional keyword arguments to pass

    Returns:
        Python source code string for the probe script.
    """
    inputs_repr = repr(test_inputs) if test_inputs else "{}"

    script = textwrap.dedent(f"""\
        import json
        import sys
        import traceback

        def main():
            try:
                import {module_path} as target_module
            except Exception as exc:
                result = {{
                    "status": "error",
                    "message": f"Import failed: {{exc}}",
                    "traceback": traceback.format_exc(),
                    "call_chain": [],
                }}
                print(json.dumps(result))
                return

            func = getattr(target_module, "{function_name}", None)
            if func is None:
                # Try splitting on dots for class.method
                parts = "{function_name}".split(".")
                obj = target_module
                try:
                    for part in parts:
                        obj = getattr(obj, part)
                    func = obj
                except AttributeError:
                    result = {{
                        "status": "error",
                        "message": "Function not found: {function_name}",
                        "traceback": "",
                        "call_chain": [],
                    }}
                    print(json.dumps(result))
                    return

            test_inputs = {inputs_repr}
            try:
                func(**test_inputs)
                result = {{"status": "ok", "message": "", "traceback": "", "call_chain": []}}
            except NotImplementedError as exc:
                tb = traceback.format_exc()
                frames = traceback.extract_tb(exc.__traceback__)
                call_chain = [f"{{f.filename}}:{{f.name}}:{{f.lineno}}" for f in frames]
                result = {{
                    "status": "not_implemented",
                    "message": str(exc),
                    "traceback": tb,
                    "call_chain": call_chain,
                }}
            except TypeError as exc:
                if "argument" in str(exc) or "required" in str(exc):
                    result = {{
                        "status": "unprobeable",
                        "message": f"Cannot probe without proper arguments: {{exc}}",
                        "traceback": "",
                        "call_chain": [],
                    }}
                else:
                    result = {{
                        "status": "error",
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                        "call_chain": [],
                    }}
            except Exception as exc:
                result = {{
                    "status": "error",
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                    "call_chain": [],
                }}

            print(json.dumps(result))

        if __name__ == "__main__":
            main()
    """)
    return script


def probe_function(
    module_path: str,
    function_name: str,
    test_inputs: dict[str, Any] | None = None,
    timeout_seconds: float = 5.0,
    python_executable: str | None = None,
    project_root: Path | None = None,
) -> RuntimeProbeResult:
    """Run a function in a subprocess and check for NotImplementedError.

    Generates a probe script, runs it via subprocess.run() with timeout,
    parses JSON output.

    Args:
        module_path: Dotted module path.
        function_name: Function name to probe.
        test_inputs: Optional arguments.
        timeout_seconds: Maximum execution time.
        python_executable: Path to Python interpreter (defaults to sys.executable).

    Returns:
        RuntimeProbeResult with status and error details.
    """
    if python_executable is None:
        python_executable = sys.executable

    script = generate_probe_script(module_path, function_name, test_inputs)

    start_time = time.monotonic()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(script)
        tmp_path = tmp.name

    try:
        execution_env = None
        execution_cwd = None
        if project_root is not None:
            root = str(project_root.resolve())
            execution_env = dict(os.environ)
            existing_path = execution_env.get("PYTHONPATH")
            execution_env["PYTHONPATH"] = (
                root if not existing_path else f"{root}{os.pathsep}{existing_path}"
            )
            execution_cwd = root

        result = subprocess.run(
            [python_executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=execution_cwd,
            env=execution_env,
        )
        duration_ms = (time.monotonic() - start_time) * 1000

        stdout = result.stdout.strip()
        if not stdout:
            return RuntimeProbeResult(
                function_name=function_name,
                module_path=module_path,
                status="error",
                error_message=f"No output from probe script. stderr: {result.stderr[:500]}",
                duration_ms=duration_ms,
            )

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return RuntimeProbeResult(
                function_name=function_name,
                module_path=module_path,
                status="error",
                error_message=f"Invalid JSON from probe: {stdout[:500]}",
                duration_ms=duration_ms,
            )

        return RuntimeProbeResult(
            function_name=function_name,
            module_path=module_path,
            status=data.get("status", "error"),
            error_message=data.get("message", ""),
            traceback_summary=data.get("traceback", ""),
            call_chain=data.get("call_chain", []),
            duration_ms=duration_ms,
        )

    except subprocess.TimeoutExpired:
        duration_ms = (time.monotonic() - start_time) * 1000
        return RuntimeProbeResult(
            function_name=function_name,
            module_path=module_path,
            status="timeout",
            error_message=f"Probe timed out after {timeout_seconds}s",
            duration_ms=duration_ms,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _filepath_to_module_path(filepath: str, project_root: Path) -> str | None:
    """Convert a file path to a dotted module path relative to project root.

    Args:
        filepath: Absolute or relative path to a Python file.
        project_root: Root of the Python project.

    Returns:
        Dotted module path or None if conversion fails.
    """
    try:
        rel = Path(filepath).resolve().relative_to(project_root.resolve())
    except ValueError:
        return None

    parts = list(rel.parts)
    from pathlib import PurePosixPath

    from spec_manager.core.language import is_package_marker, is_source_file

    if not parts:
        return None
    last = parts[-1]
    last_suffix = PurePosixPath(last).suffix  # e.g. ".py"
    if not is_source_file(last_suffix):
        return None

    parts[-1] = last[: -len(last_suffix)]  # strip extension
    if is_package_marker(last):
        parts = parts[:-1]
    if not parts:
        return None

    return ".".join(parts)


def probe_stubs(
    stubs: list[StubFunction],
    project_root: Path,
    timeout_seconds: float = 5.0,
) -> list[RuntimeProbeResult]:
    """Probe all stub functions discovered by the stub scanner.

    Converts file paths to module paths, probes each stub.
    Stubs of type "not_implemented" are prioritized (most likely to confirm).

    Args:
        stubs: List of StubFunction from branches.gap_detection.
        project_root: Root of the Python project for module path resolution.
        timeout_seconds: Per-function timeout.

    Returns:
        List of RuntimeProbeResult.
    """
    # Sort so not_implemented stubs come first
    sorted_stubs = sorted(stubs, key=lambda s: (0 if s.stub_type == "not_implemented" else 1))

    results: list[RuntimeProbeResult] = []
    for stub in sorted_stubs:
        module_path = _filepath_to_module_path(stub.file_path, project_root)
        if module_path is None:
            results.append(
                RuntimeProbeResult(
                    function_name=stub.name,
                    module_path="",
                    status="error",
                    error_message=f"Could not resolve module path for {stub.file_path}",
                )
            )
            continue

        result = probe_function(
            module_path=module_path,
            function_name=stub.name,
            timeout_seconds=timeout_seconds,
            project_root=project_root,
        )
        results.append(result)

    return results


def runtime_results_to_gap_evidence(
    results: list[RuntimeProbeResult],
) -> list[GapEvidence]:
    """Convert RuntimeProbeResult list to GapEvidence.

    "not_implemented" becomes a confirmed executable runtime gap.
    "unprobeable" becomes indeterminate evidence so unresolved runtime
    coverage is not silently dropped.
    invariant_family = "executable_runtime"
    detector = "runtime_detector"

    Args:
        results: List of RuntimeProbeResult.

    Returns:
        List of GapEvidence for confirmed runtime gaps.
    """
    evidence: list[GapEvidence] = []
    for result in results:
        if result.status == "not_implemented":
            details: dict[str, Any] = {
                "module_path": result.module_path,
                "error_message": result.error_message,
                "call_chain": result.call_chain,
                "duration_ms": result.duration_ms,
            }
            evidence.append(
                GapEvidence(
                    invariant_family="executable_runtime",
                    description=(
                        f"NotImplementedError at runtime: {result.function_name}"
                        + (f" - {result.error_message}" if result.error_message else "")
                    ),
                    details=details,
                    confidence=1.0,
                    location=f"{result.module_path}:{result.function_name}",
                    detector="runtime_detector",
                )
            )
            continue

        if result.status == "unprobeable":
            evidence.append(
                GapEvidence(
                    invariant_family="executable_runtime",
                    description=(
                        f"Runtime probe is indeterminate for {result.function_name}"
                        + (f": {result.error_message}" if result.error_message else "")
                    ),
                    details={
                        "gap_type": "uncertainty_marker",
                        "evidence_type": "indeterminate",
                        "probe_status": result.status,
                        "module_path": result.module_path,
                        "error_message": result.error_message,
                        "duration_ms": result.duration_ms,
                    },
                    confidence=1.0,
                    location=f"{result.module_path}:{result.function_name}",
                    detector="runtime_detector",
                )
            )
    return evidence


# ---------------------------------------------------------------------------
# Concrete implementation
# ---------------------------------------------------------------------------


class SubprocessRuntimeDetector:
    """Concrete ``ExecutableGapDetector`` that probes stubs via subprocess.

    Delegates to the module-level ``probe_stubs`` and
    ``runtime_results_to_gap_evidence`` functions.
    """

    def probe_stubs(
        self,
        stubs: list[StubFunction],
        project_root: Path,
        timeout_seconds: float = 5.0,
    ) -> list[RuntimeProbeResult]:
        """Probe all stub functions via subprocess sandbox."""
        return probe_stubs(stubs, project_root, timeout_seconds)

    def results_to_gap_evidence(
        self,
        results: list[RuntimeProbeResult],
    ) -> list[GapEvidence]:
        """Convert runtime probe results to gap evidence."""
        return runtime_results_to_gap_evidence(results)
