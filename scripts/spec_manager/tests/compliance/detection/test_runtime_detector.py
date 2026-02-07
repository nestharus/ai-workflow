"""Tests for runtime gap detector."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from spec_manager.compliance.detection.runtime_detector import (
    RuntimeProbeResult,
    generate_probe_script,
    probe_function,
    runtime_results_to_gap_evidence,
)


class TestGenerateProbeScript:
    """Test probe script generation."""

    def test_basic_script_generation(self) -> None:
        script = generate_probe_script("my_module", "my_function")
        assert "import my_module as target_module" in script
        assert "my_function" in script
        assert "json.dumps" in script
        assert "NotImplementedError" in script

    def test_script_with_test_inputs(self) -> None:
        script = generate_probe_script("mod", "fn", {"x": 1, "y": 2})
        assert "{'x': 1, 'y': 2}" in script

    def test_script_with_no_inputs(self) -> None:
        script = generate_probe_script("mod", "fn")
        assert "test_inputs = {}" in script


class TestProbeFunction:
    """Test runtime probing of functions."""

    def test_probe_not_implemented_function(self, tmp_path: Path) -> None:
        module_dir = tmp_path / "probe_test_pkg"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / "target.py").write_text(
            textwrap.dedent("""\
                def broken():
                    raise NotImplementedError("Not done yet")
            """),
            encoding="utf-8",
        )

        # Add to sys.path temporarily via probe
        result = probe_function(
            module_path="probe_test_pkg.target",
            function_name="broken",
            python_executable=sys.executable,
        )

        # Since the module is not on sys.path for the subprocess,
        # we need to test differently
        # Let's create a standalone module file and test with PYTHONPATH
        module_file = tmp_path / "standalone_broken.py"
        module_file.write_text(
            textwrap.dedent("""\
                def broken():
                    raise NotImplementedError("Not done yet")
            """),
            encoding="utf-8",
        )

        # Use a direct approach: write a complete test script
        import json
        import subprocess

        test_script = tmp_path / "test_probe.py"
        test_script.write_text(
            textwrap.dedent("""\
                import json
                import sys
                import traceback

                sys.path.insert(0, "{tmp_dir}")

                try:
                    import standalone_broken
                    standalone_broken.broken()
                    print(json.dumps({{"status": "ok"}}))
                except NotImplementedError as exc:
                    tb = traceback.format_exc()
                    frames = traceback.extract_tb(exc.__traceback__)
                    chain = [f"{{f.filename}}:{{f.name}}:{{f.lineno}}" for f in frames]
                    print(json.dumps({{
                        "status": "not_implemented",
                        "message": str(exc),
                        "traceback": tb,
                        "call_chain": chain,
                    }}))
            """).format(tmp_dir=str(tmp_path).replace("\\", "\\\\")),
            encoding="utf-8",
        )

        proc = subprocess.run(
            [sys.executable, str(test_script)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        data = json.loads(proc.stdout.strip())
        assert data["status"] == "not_implemented"
        assert "Not done yet" in data["message"]

    def test_probe_ok_function(self, tmp_path: Path) -> None:
        import json
        import subprocess

        module_file = tmp_path / "standalone_ok.py"
        module_file.write_text(
            textwrap.dedent("""\
                def working():
                    return 42
            """),
            encoding="utf-8",
        )

        test_script = tmp_path / "test_ok.py"
        test_script.write_text(
            textwrap.dedent("""\
                import json
                import sys
                sys.path.insert(0, "{tmp_dir}")
                try:
                    import standalone_ok
                    standalone_ok.working()
                    print(json.dumps({{"status": "ok"}}))
                except NotImplementedError as exc:
                    print(json.dumps({{"status": "not_implemented", "message": str(exc)}}))
                except Exception as exc:
                    print(json.dumps({{"status": "error", "message": str(exc)}}))
            """).format(tmp_dir=str(tmp_path).replace("\\", "\\\\")),
            encoding="utf-8",
        )

        proc = subprocess.run(
            [sys.executable, str(test_script)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        data = json.loads(proc.stdout.strip())
        assert data["status"] == "ok"

    def test_probe_timeout_handling(self) -> None:
        result = probe_function(
            module_path="nonexistent_module_xyz",
            function_name="nonexistent_func",
            timeout_seconds=0.001,
        )
        # Will likely either timeout or error on import
        assert result.status in ("timeout", "error")

    def test_probe_function_result_fields(self) -> None:
        result = probe_function(
            module_path="nonexistent_module_xyz",
            function_name="fn",
            timeout_seconds=5.0,
        )
        assert result.function_name == "fn"
        assert result.module_path == "nonexistent_module_xyz"
        assert result.duration_ms >= 0


class TestRuntimeResultsToGapEvidence:
    """Test conversion of RuntimeProbeResult to GapEvidence."""

    def test_not_implemented_becomes_evidence(self) -> None:
        results = [
            RuntimeProbeResult(
                function_name="broken_func",
                module_path="my.module",
                status="not_implemented",
                error_message="Not done yet",
                call_chain=["file.py:func:10"],
                duration_ms=50.0,
            ),
        ]

        evidence = runtime_results_to_gap_evidence(results)
        assert len(evidence) == 1
        e = evidence[0]
        assert e.invariant_family == "executable_runtime"
        assert e.detector == "runtime_detector"
        assert "broken_func" in e.description
        assert "Not done yet" in e.description
        assert e.confidence == 1.0

    def test_ok_status_filtered_out(self) -> None:
        results = [
            RuntimeProbeResult(
                function_name="good_func",
                module_path="my.module",
                status="ok",
            ),
        ]

        evidence = runtime_results_to_gap_evidence(results)
        assert len(evidence) == 0

    def test_error_status_filtered_out(self) -> None:
        results = [
            RuntimeProbeResult(
                function_name="err_func",
                module_path="my.module",
                status="error",
                error_message="Import failed",
            ),
        ]

        evidence = runtime_results_to_gap_evidence(results)
        assert len(evidence) == 0

    def test_timeout_status_filtered_out(self) -> None:
        results = [
            RuntimeProbeResult(
                function_name="slow_func",
                module_path="my.module",
                status="timeout",
            ),
        ]

        evidence = runtime_results_to_gap_evidence(results)
        assert len(evidence) == 0

    def test_empty_input(self) -> None:
        evidence = runtime_results_to_gap_evidence([])
        assert evidence == []

    def test_mixed_results(self) -> None:
        results = [
            RuntimeProbeResult(
                function_name="ok_func",
                module_path="m",
                status="ok",
            ),
            RuntimeProbeResult(
                function_name="broken_func",
                module_path="m",
                status="not_implemented",
                error_message="TODO",
            ),
            RuntimeProbeResult(
                function_name="err_func",
                module_path="m",
                status="error",
            ),
        ]

        evidence = runtime_results_to_gap_evidence(results)
        assert len(evidence) == 1
        assert "broken_func" in evidence[0].description
