"""Tests for import graph builder (Plan 3)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from spec_manager.analysis.import_graph import (
    ImportGraphBuilder,
    ImportGraphConfig,
    ImportReference,
    UsageSite,
)
from spec_manager.schemas.pin_functions import ImportEdge, PinFunction


def _make_pin_function(
    pin_func_id: str = "PFUNC-0001",
    function_name: str = "validate_payment",
    **kwargs,
) -> PinFunction:
    defaults = dict(
        pin_func_id=pin_func_id,
        function_name=function_name,
        module_path="atoms.payment",
        file_path="atoms/payment.py",
        line_start=10,
        line_end=25,
        signature="(data: dict) -> bool",
        docstring="Validate payment.",
        content_hash="a" * 64,
    )
    defaults.update(kwargs)
    return PinFunction(**defaults)


def _write_py(directory: Path, filename: str, content: str) -> Path:
    file_path = directory / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(textwrap.dedent(content), encoding="utf-8")
    return file_path


class TestScanFileImports:
    """Tests for scanning individual files for imports."""

    @pytest.fixture()
    def builder(self) -> ImportGraphBuilder:
        config = ImportGraphConfig(
            algorithmic_roots=["atoms", "shapes"],
            architectural_roots=["services", "handlers"],
        )
        return ImportGraphBuilder(config)

    def test_detect_import_from(self, builder, tmp_path):
        source = """\
        from atoms.payment import validate_payment

        def handler(event):
            result = validate_payment(event.data)
            return result
        """
        path = _write_py(tmp_path, "handler.py", source)
        refs = builder.scan_file_imports(path)

        assert len(refs) == 1
        assert refs[0].pin_func_name == "validate_payment"
        assert refs[0].import_module == "atoms.payment"

    def test_detect_module_import(self, builder, tmp_path):
        source = """\
        import atoms.payment

        def handler(event):
            atoms.payment.validate_payment(event.data)
        """
        path = _write_py(tmp_path, "handler.py", source)
        refs = builder.scan_file_imports(path)

        assert len(refs) >= 1

    def test_detect_aliased_import(self, builder, tmp_path):
        source = """\
        from atoms.payment import validate_payment as vp

        def handler(event):
            return vp(event.data)
        """
        path = _write_py(tmp_path, "handler.py", source)
        refs = builder.scan_file_imports(path)

        assert len(refs) == 1
        assert refs[0].alias == "vp"
        assert refs[0].pin_func_name == "validate_payment"

    def test_usage_sites_detected(self, builder, tmp_path):
        source = """\
        from atoms.payment import validate_payment

        def handler(event):
            result = validate_payment(event.data)
            return result

        def other_handler(event):
            validate_payment(event.payload)
        """
        path = _write_py(tmp_path, "handler.py", source)
        refs = builder.scan_file_imports(path)

        assert len(refs) == 1
        assert len(refs[0].usage_sites) == 2

    def test_no_algorithmic_import(self, builder, tmp_path):
        source = """\
        from utils.helpers import format_date

        def handler(event):
            return format_date(event.timestamp)
        """
        path = _write_py(tmp_path, "handler.py", source)
        refs = builder.scan_file_imports(path)

        assert len(refs) == 0

    def test_syntax_error_returns_empty(self, builder, tmp_path):
        path = tmp_path / "bad.py"
        path.write_text("from atoms import (\n", encoding="utf-8")
        refs = builder.scan_file_imports(path)
        assert refs == []


class TestProjectionTypeClassification:
    """Tests for projection type classification logic."""

    @pytest.fixture()
    def builder(self) -> ImportGraphBuilder:
        return ImportGraphBuilder()

    def test_pass_through_direct_call(self, builder):
        ref = ImportReference(
            pin_func_name="validate",
            import_module="atoms.pay",
            file_path="handler.py",
            import_line=1,
        )
        usage = UsageSite(
            line=5,
            enclosing_function="handle",
            call_pattern="direct",
        )
        result = builder.classify_projection_type(ref, usage)
        assert result == "pass_through"

    def test_wrap_decorated_function(self, builder):
        ref = ImportReference(
            pin_func_name="validate",
            import_module="atoms.pay",
            file_path="handler.py",
            import_line=1,
        )
        usage = UsageSite(
            line=5,
            enclosing_function="handle",
            call_pattern="wrapped",
        )
        result = builder.classify_projection_type(ref, usage)
        assert result == "middleware_wrap"

    def test_wrap_partial_application(self, builder):
        ref = ImportReference(
            pin_func_name="validate",
            import_module="atoms.pay",
            file_path="handler.py",
            import_line=1,
        )
        usage = UsageSite(
            line=5,
            enclosing_function="handle",
            call_pattern="partial",
        )
        result = builder.classify_projection_type(ref, usage)
        assert result == "middleware_wrap"


class TestSmearDetection:
    """Tests for detecting smeared functions (multiple pin-functions in one handler)."""

    @pytest.fixture()
    def builder(self) -> ImportGraphBuilder:
        return ImportGraphBuilder()

    def test_detect_smear(self, builder):
        refs = [
            ImportReference(
                pin_func_name="func_a",
                import_module="atoms.a",
                file_path="handler.py",
                import_line=1,
                usage_sites=[
                    UsageSite(line=10, enclosing_function="process"),
                ],
            ),
            ImportReference(
                pin_func_name="func_b",
                import_module="atoms.b",
                file_path="handler.py",
                import_line=2,
                usage_sites=[
                    UsageSite(line=12, enclosing_function="process"),
                ],
            ),
        ]

        smeared = builder.detect_smeared_functions(refs)
        assert len(smeared) == 1
        assert smeared[0][0] == "process"
        assert set(smeared[0][1]) == {"func_a", "func_b"}

    def test_no_smear_single_import(self, builder):
        refs = [
            ImportReference(
                pin_func_name="func_a",
                import_module="atoms.a",
                file_path="handler.py",
                import_line=1,
                usage_sites=[
                    UsageSite(line=10, enclosing_function="process"),
                ],
            ),
        ]

        smeared = builder.detect_smeared_functions(refs)
        assert len(smeared) == 0


class TestBuildGraph:
    """Tests for full import graph building."""

    def test_build_graph_with_matching_functions(self, tmp_path):
        # Create an architectural file that imports from atoms
        arch_dir = tmp_path / "services"
        arch_dir.mkdir()
        source = """\
        from atoms.payment import validate_payment

        def handler(event):
            return validate_payment(event.data)
        """
        _write_py(arch_dir, "payment_handler.py", source)

        pin_functions = [
            _make_pin_function(
                pin_func_id="PFUNC-0001",
                function_name="validate_payment",
            ),
        ]

        config = ImportGraphConfig(
            algorithmic_roots=["atoms"],
            architectural_roots=["services"],
        )
        builder = ImportGraphBuilder(config)
        edges = builder.build_graph(pin_functions, arch_dir)

        assert len(edges) >= 1
        assert edges[0].pin_func_id == "PFUNC-0001"
        assert edges[0].projection_type == "pass_through"

    def test_build_graph_no_matches(self, tmp_path):
        arch_dir = tmp_path / "services"
        arch_dir.mkdir()
        source = """\
        from utils import helper

        def handler(event):
            return helper(event.data)
        """
        _write_py(arch_dir, "handler.py", source)

        pin_functions = [
            _make_pin_function(
                pin_func_id="PFUNC-0001",
                function_name="validate_payment",
            ),
        ]

        config = ImportGraphConfig(algorithmic_roots=["atoms"])
        builder = ImportGraphBuilder(config)
        edges = builder.build_graph(pin_functions, arch_dir)

        assert len(edges) == 0

    def test_smear_detection_in_build(self, tmp_path):
        """Test that build_graph detects smeared functions."""
        arch_dir = tmp_path / "services"
        arch_dir.mkdir()
        source = """\
        from atoms.a import func_a
        from atoms.b import func_b

        def process(data):
            a_result = func_a(data)
            b_result = func_b(data)
            return a_result + b_result
        """
        _write_py(arch_dir, "processor.py", source)

        pin_functions = [
            _make_pin_function(
                pin_func_id="PFUNC-0001",
                function_name="func_a",
                module_path="atoms.a",
            ),
            _make_pin_function(
                pin_func_id="PFUNC-0002",
                function_name="func_b",
                module_path="atoms.b",
                content_hash="b" * 64,
            ),
        ]

        config = ImportGraphConfig(algorithmic_roots=["atoms"])
        builder = ImportGraphBuilder(config)
        edges = builder.build_graph(pin_functions, arch_dir)

        assert len(edges) >= 2
        # Both edges pointing to the same location should be SMEAR
        smear_edges = [e for e in edges if e.projection_type == "smear"]
        assert len(smear_edges) >= 2

    def test_wrapped_function_detection(self, tmp_path):
        """Test that decorated functions are classified as WRAP."""
        arch_dir = tmp_path / "services"
        arch_dir.mkdir()
        source = """\
        from atoms.payment import validate_payment
        from functools import wraps

        def retry(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                return f(*args, **kwargs)
            return wrapper

        @retry
        def handler(data):
            return validate_payment(data)
        """
        _write_py(arch_dir, "handler.py", source)

        pin_functions = [
            _make_pin_function(
                pin_func_id="PFUNC-0001",
                function_name="validate_payment",
            ),
        ]

        config = ImportGraphConfig(algorithmic_roots=["atoms"])
        builder = ImportGraphBuilder(config)
        edges = builder.build_graph(pin_functions, arch_dir)

        wrap_edges = [e for e in edges if e.projection_type == "middleware_wrap"]
        assert len(wrap_edges) >= 1


class TestIntroductionDetection:
    """Tests for INTRODUCTION projection type."""

    def test_introduction_is_absence(self):
        """INTRODUCTION means no edges from algorithmic layer.
        It is detected by examining files that have no pin-function imports.
        """
        # A file with no pin-function imports is an introduction
        config = ImportGraphConfig(algorithmic_roots=["atoms"])
        builder = ImportGraphBuilder(config)

        ref = ImportReference(
            pin_func_name="helper",
            import_module="utils.helpers",
            file_path="services/handler.py",
            import_line=1,
        )

        # Refs from non-algorithmic modules should not produce edges
        # INTRODUCTION is detected at the graph level, not per-import
        assert not builder._is_algorithmic_module("utils.helpers")
