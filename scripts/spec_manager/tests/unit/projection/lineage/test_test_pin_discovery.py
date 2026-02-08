"""Tests for test-pin association discovery via AST analysis."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.projection.lineage.test_pin_discovery import (
    TestPinAssociation,
    TestPinMap,
    discover_test_pin_associations,
)
from spec_manager.schemas.pin_functions import PinFunction, PinFunctionRegistry


def _make_registry(
    pin_funcs: list[PinFunction] | None = None,
) -> PinFunctionRegistry:
    """Helper to create a PinFunctionRegistry."""
    return PinFunctionRegistry(
        schema_version="1.0",
        pin_functions=pin_funcs or [],
        import_edges=[],
        created_at="2024-01-01T00:00:00Z",
    )


def _make_pin_func(
    pin_func_id: str = "PFUNC-0001",
    function_name: str = "validate_payment",
) -> PinFunction:
    """Helper to create a PinFunction."""
    return PinFunction(
        pin_func_id=pin_func_id,
        function_name=function_name,
        module_path=f"atoms.{function_name}",
        file_path=f"atoms/{function_name}.py",
        line_start=1,
        line_end=10,
        signature=f"def {function_name}()",
        docstring=f"Docstring for {function_name}",
        content_hash="abc123",
    )


def _write_test_file(tmp_path: Path, name: str, content: str) -> Path:
    """Write a test file with the given content."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


class TestDirectImportAssociation:
    """Test discovery of direct import + call associations."""

    def test_discovers_direct_import_and_call(self, tmp_path: Path) -> None:
        """File that imports and calls a pin-function directly."""
        test_file = _write_test_file(
            tmp_path,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment():
                result = validate_payment(100.0, "USD")
                assert result is True
            """,
        )
        registry = _make_registry([_make_pin_func()])
        result = discover_test_pin_associations([test_file], registry)

        assert len(result.associations) == 1
        assoc = result.associations[0]
        assert assoc.test_function == "test_valid_payment"
        assert assoc.pin_func_id == "PFUNC-0001"
        assert assoc.pin_function_name == "validate_payment"
        assert assoc.association_type == "direct_import"
        assert assoc.confidence == 1.0

    def test_class_based_test_import_and_call(self, tmp_path: Path) -> None:
        """Class-based test (TestFoo.test_bar) that imports and calls a pin-function."""
        test_file = _write_test_file(
            tmp_path,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            class TestPayment:
                def test_valid_payment(self):
                    result = validate_payment(100.0, "USD")
                    assert result is True
            """,
        )
        registry = _make_registry([_make_pin_func()])
        result = discover_test_pin_associations([test_file], registry)

        assert len(result.associations) == 1
        assoc = result.associations[0]
        assert assoc.test_function == "TestPayment.test_valid_payment"
        assert assoc.pin_func_id == "PFUNC-0001"
        assert assoc.association_type == "direct_import"


class TestNoAssociation:
    """Test files that should produce no associations."""

    def test_import_without_call(self, tmp_path: Path) -> None:
        """File that imports from an atom module but does not call any pin-function."""
        test_file = _write_test_file(
            tmp_path,
            "test_no_call.py",
            """\
            from atoms.payment import validate_payment

            def test_something_else():
                assert 1 + 1 == 2
            """,
        )
        registry = _make_registry([_make_pin_func()])
        result = discover_test_pin_associations([test_file], registry)

        assert len(result.associations) == 0


class TestFixtureAssociation:
    """Test discovery of fixture-based associations."""

    def test_fixture_name_matches_pin_function(self, tmp_path: Path) -> None:
        """Test function has a parameter whose name matches a pin-function."""
        test_file = _write_test_file(
            tmp_path,
            "test_with_fixture.py",
            """\
            def test_payment(validate_payment):
                result = validate_payment(100.0)
                assert result is True
            """,
        )
        registry = _make_registry([_make_pin_func()])
        result = discover_test_pin_associations([test_file], registry)

        # Should find fixture_usage association (parameter name match)
        # plus potentially a direct_import if the fixture is called
        fixture_assocs = [a for a in result.associations if a.association_type == "fixture_usage"]
        assert len(fixture_assocs) == 1
        assert fixture_assocs[0].confidence == 0.7
        assert fixture_assocs[0].pin_func_id == "PFUNC-0001"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_test_files_list(self) -> None:
        """Empty list of test files produces empty map."""
        registry = _make_registry([_make_pin_func()])
        result = discover_test_pin_associations([], registry)

        assert len(result.associations) == 0
        assert result.scan_timestamp != ""

    def test_syntax_error_in_test_file(self, tmp_path: Path) -> None:
        """File with syntax error is gracefully skipped."""
        test_file = _write_test_file(
            tmp_path,
            "test_broken.py",
            """\
            def test_broken(
                # Unterminated function definition
            """,
        )
        registry = _make_registry([_make_pin_func()])
        result = discover_test_pin_associations([test_file], registry)

        assert len(result.associations) == 0

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Nonexistent file is gracefully skipped."""
        nonexistent = tmp_path / "does_not_exist.py"
        registry = _make_registry([_make_pin_func()])
        result = discover_test_pin_associations([nonexistent], registry)

        assert len(result.associations) == 0

    def test_multiple_pin_functions_in_one_test(self, tmp_path: Path) -> None:
        """A single test function calls multiple pin-functions."""
        test_file = _write_test_file(
            tmp_path,
            "test_multi.py",
            """\
            from atoms.payment import validate_payment
            from atoms.process import process_order

            def test_full_workflow():
                validate_payment(100.0, "USD")
                process_order("order-123")
            """,
        )
        registry = _make_registry(
            [
                _make_pin_func("PFUNC-0001", "validate_payment"),
                _make_pin_func("PFUNC-0002", "process_order"),
            ]
        )
        result = discover_test_pin_associations([test_file], registry)

        assert len(result.associations) == 2
        pin_ids = {a.pin_func_id for a in result.associations}
        assert pin_ids == {"PFUNC-0001", "PFUNC-0002"}

    def test_scan_timestamp_is_set(self, tmp_path: Path) -> None:
        """Scan timestamp is an ISO-8601 string."""
        registry = _make_registry()
        result = discover_test_pin_associations([], registry)
        assert result.scan_timestamp != ""
        # Should be parseable as ISO timestamp
        from datetime import datetime

        datetime.fromisoformat(result.scan_timestamp)

    def test_test_pin_map_query_methods(self, tmp_path: Path) -> None:
        """TestPinMap helper methods work correctly."""
        test_map = TestPinMap(
            associations=[
                TestPinAssociation(
                    test_file="test_a.py",
                    test_function="test_foo",
                    pin_func_id="PFUNC-0001",
                    pin_function_name="validate_payment",
                    association_type="direct_import",
                    confidence=1.0,
                ),
                TestPinAssociation(
                    test_file="test_a.py",
                    test_function="test_bar",
                    pin_func_id="PFUNC-0001",
                    pin_function_name="validate_payment",
                    association_type="direct_import",
                    confidence=1.0,
                ),
            ],
            scan_timestamp="2024-01-01T00:00:00Z",
        )

        assert len(test_map.associations_for_pin("PFUNC-0001")) == 2
        assert len(test_map.associations_for_pin("PFUNC-9999")) == 0
        assert len(test_map.associations_for_test("test_foo")) == 1
