"""Tests for architectural quality checks."""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

from spec_manager.compliance.promotion.architectural_quality import (
    check_function_recomposition,
    check_no_inlined_atom_logic,
)
from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.schemas.pin_functions import (
    PinFunction,
    PinFunctionRegistry,
)


def _write_py(tmpdir: Path, name: str, content: str) -> Path:
    path = tmpdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _content_hash(code: str) -> str:
    """Compute a normalized content hash matching the detection logic."""
    lines = code.splitlines()
    normalized = "\n".join(line.strip() for line in lines if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _make_registry(
    pin_funcs: list[PinFunction] | None = None,
) -> PinFunctionRegistry:
    return PinFunctionRegistry(
        schema_version="1.0",
        pin_functions=pin_funcs or [],
        import_edges=[],
        created_at="2024-01-01T00:00:00Z",
    )


class TestCheckNoInlinedAtomLogic:
    def test_no_duplication_passes(self, tmp_path: Path) -> None:
        algo_file = _write_py(tmp_path / "algo", "compute.py", """\
            def compute(x):
                return x * 2 + 1
        """)
        arch_file = _write_py(tmp_path / "arch", "service.py", """\
            from algo.compute import compute

            def handle(request):
                return compute(request.value)
        """)
        registry = _make_registry([
            PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="compute",
                module_path="algo.compute",
                file_path=str(algo_file),
                line_start=1, line_end=2,
                signature="def compute(x)",
                docstring="",
                content_hash="unique_hash_not_matching",
            ),
        ])
        gate_spec = GateSpec(gate_id=GateId.NO_INLINED_ATOM_LOGIC)
        result = check_no_inlined_atom_logic(
            registry, [arch_file], [algo_file], gate_spec
        )
        assert result.passed is True
        assert len(result.findings) == 0

    def test_exact_body_match_detected(self, tmp_path: Path) -> None:
        # The same function body in both files
        func_body = """\
            def compute(x):
                return x * 2 + 1
        """
        algo_file = _write_py(tmp_path / "algo", "compute.py", func_body)
        arch_file = _write_py(tmp_path / "arch", "service.py", func_body)

        # Compute the hash of the function body as the detection logic would
        source = textwrap.dedent(func_body)
        lines = source.splitlines()
        normalized = "\n".join(line.strip() for line in lines if line.strip())
        body_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        registry = _make_registry([
            PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="compute",
                module_path="algo.compute",
                file_path=str(algo_file),
                line_start=1, line_end=2,
                signature="def compute(x)",
                docstring="",
                content_hash=body_hash,
            ),
        ])
        gate_spec = GateSpec(gate_id=GateId.NO_INLINED_ATOM_LOGIC)
        result = check_no_inlined_atom_logic(
            registry, [arch_file], [algo_file], gate_spec
        )
        assert result.passed is False
        assert len(result.findings) >= 1
        assert result.findings[0]["detection_method"] == "exact_match"

    def test_ast_similarity_detected(self, tmp_path: Path) -> None:
        # Same structure but different variable names
        algo_file = _write_py(tmp_path / "algo", "compute.py", """\
            def compute(value):
                result = value * 2
                output = result + 1
                return output
        """)
        arch_file = _write_py(tmp_path / "arch", "service.py", """\
            def process(data):
                temp = data * 2
                final = temp + 1
                return final
        """)
        registry = _make_registry([
            PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="compute",
                module_path="algo.compute",
                file_path=str(algo_file),
                line_start=1, line_end=4,
                signature="def compute(value)",
                docstring="",
                content_hash="different_hash",
            ),
        ])
        gate_spec = GateSpec(
            gate_id=GateId.NO_INLINED_ATOM_LOGIC,
            params={"similarity_threshold": 0.7},
        )
        result = check_no_inlined_atom_logic(
            registry, [arch_file], [algo_file], gate_spec
        )
        # AST similarity should detect this
        assert result.passed is False
        assert any(
            f["detection_method"] == "ast_similarity"
            for f in result.findings
        )

    def test_different_logic_not_flagged(self, tmp_path: Path) -> None:
        algo_file = _write_py(tmp_path / "algo", "compute.py", """\
            def compute(x, y, z):
                a = x ** 2
                b = y ** 3
                c = z ** 4
                result = a + b + c
                total = result * 100
                return total / 42
        """)
        arch_file = _write_py(tmp_path / "arch", "service.py", """\
            def handle(request):
                return request.get_value()
        """)
        registry = _make_registry([
            PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="compute",
                module_path="algo.compute",
                file_path=str(algo_file),
                line_start=1, line_end=7,
                signature="def compute(x, y, z)",
                docstring="",
                content_hash="different_hash",
            ),
        ])
        gate_spec = GateSpec(gate_id=GateId.NO_INLINED_ATOM_LOGIC)
        result = check_no_inlined_atom_logic(
            registry, [arch_file], [algo_file], gate_spec
        )
        assert result.passed is True

    def test_empty_files_passes(self) -> None:
        registry = _make_registry()
        gate_spec = GateSpec(gate_id=GateId.NO_INLINED_ATOM_LOGIC)
        result = check_no_inlined_atom_logic(registry, [], [], gate_spec)
        assert result.passed is True


class TestCheckFunctionRecomposition:
    def test_properly_imported_and_called_passes(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            from atoms.compute import compute

            def handle(x):
                return compute(x)
        """)
        registry = _make_registry([
            PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="compute",
                module_path="atoms.compute",
                file_path="atoms/compute.py",
                line_start=1, line_end=2,
                signature="def compute(x)",
                docstring="",
                content_hash="abc",
            ),
        ])
        gate_spec = GateSpec(gate_id=GateId.FUNCTION_RECOMPOSITION)
        result = check_function_recomposition(registry, [arch_file], gate_spec)
        assert result.passed is True

    def test_dead_import_detected(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            from atoms.compute import compute

            def handle(x):
                return x + 1
        """)
        registry = _make_registry([
            PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="compute",
                module_path="atoms.compute",
                file_path="atoms/compute.py",
                line_start=1, line_end=2,
                signature="def compute(x)",
                docstring="",
                content_hash="abc",
            ),
        ])
        gate_spec = GateSpec(gate_id=GateId.FUNCTION_RECOMPOSITION)
        result = check_function_recomposition(registry, [arch_file], gate_spec)
        assert result.passed is False
        assert any(f["issue_type"] == "dead_import" for f in result.findings)

    def test_shadowed_import_detected(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            from atoms.compute import compute

            def handle(x):
                compute = lambda y: y + 1
                return compute(x)
        """)
        registry = _make_registry([
            PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="compute",
                module_path="atoms.compute",
                file_path="atoms/compute.py",
                line_start=1, line_end=2,
                signature="def compute(x)",
                docstring="",
                content_hash="abc",
            ),
        ])
        gate_spec = GateSpec(gate_id=GateId.FUNCTION_RECOMPOSITION)
        result = check_function_recomposition(registry, [arch_file], gate_spec)
        assert result.passed is False
        assert any(
            f["issue_type"] == "shadowed_import" for f in result.findings
        )

    def test_no_pin_imports_passes(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            def handle(x):
                return x + 1
        """)
        registry = _make_registry([
            PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="compute",
                module_path="atoms.compute",
                file_path="atoms/compute.py",
                line_start=1, line_end=2,
                signature="def compute(x)",
                docstring="",
                content_hash="abc",
            ),
        ])
        gate_spec = GateSpec(gate_id=GateId.FUNCTION_RECOMPOSITION)
        result = check_function_recomposition(registry, [arch_file], gate_spec)
        assert result.passed is True

    def test_empty_registry_passes(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            def handle(x):
                return x
        """)
        registry = _make_registry()
        gate_spec = GateSpec(gate_id=GateId.FUNCTION_RECOMPOSITION)
        result = check_function_recomposition(registry, [arch_file], gate_spec)
        assert result.passed is True

    def test_dead_imports_check_disabled(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            from atoms.compute import compute

            def handle(x):
                return x + 1
        """)
        registry = _make_registry([
            PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="compute",
                module_path="atoms.compute",
                file_path="atoms/compute.py",
                line_start=1, line_end=2,
                signature="def compute(x)",
                docstring="",
                content_hash="abc",
            ),
        ])
        gate_spec = GateSpec(
            gate_id=GateId.FUNCTION_RECOMPOSITION,
            params={"check_dead_imports": False},
        )
        result = check_function_recomposition(registry, [arch_file], gate_spec)
        assert result.passed is True
