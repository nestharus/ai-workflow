"""Tests for AST-based atom function extractor (Plan 2)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from spec_manager.analysis.ast_extractor import (
    AtomCandidate,
    AtomFunctionExtractor,
    ExtractionConfig,
)


@pytest.fixture()
def extractor() -> AtomFunctionExtractor:
    return AtomFunctionExtractor()


@pytest.fixture()
def custom_extractor() -> AtomFunctionExtractor:
    config = ExtractionConfig(
        atom_directories=["atoms", "shapes"],
        max_function_lines=30,
        require_docstring=True,
        annotation_marker="# @pin",
        exclude_patterns=["test_", "_test", "conftest"],
    )
    return AtomFunctionExtractor(config)


def _write_py(tmp_path: Path, filename: str, content: str) -> Path:
    """Write a Python file with dedented content."""
    file_path = tmp_path / filename
    file_path.write_text(textwrap.dedent(content), encoding="utf-8")
    return file_path


class TestExtractFromFile:
    """Tests for extracting atom candidates from a single file."""

    def test_mixed_functions(self, extractor, tmp_path):
        """Test extraction from a file with mixed functions (some atoms, some not)."""
        source = """\
        def validate_payment(data: dict) -> bool:
            \"\"\"Validate a payment.\"\"\"
            return data.get("amount", 0) > 0

        def _private_helper():
            return 42

        class PaymentProcessor:
            def process(self, data):
                \"\"\"Process payment data.\"\"\"
                pass
        """
        path = _write_py(tmp_path, "payment.py", source)
        candidates = extractor.extract_from_file(path)

        # Should find validate_payment (heuristic: small, has docstring)
        # _private_helper is private and skipped
        # PaymentProcessor.process is a method but process is not private
        names = {c.function_name for c in candidates}
        assert "validate_payment" in names
        assert "_private_helper" not in names

    def test_convention_based_detection(self, extractor, tmp_path):
        """Test that files in atom_directories use convention detection."""
        atoms_dir = tmp_path / "atoms"
        atoms_dir.mkdir()
        source = """\
        def compute_total(items: list) -> float:
            \"\"\"Sum item prices.\"\"\"
            return sum(i["price"] for i in items)
        """
        path = _write_py(atoms_dir, "pricing.py", source)
        candidates = extractor.extract_from_file(path)

        assert len(candidates) == 1
        assert candidates[0].detection_method == "convention"
        assert candidates[0].function_name == "compute_total"

    def test_annotation_based_detection(self, extractor, tmp_path):
        """Test # @pin annotation marks a function."""
        source = """\
        # @pin
        def important_calculation(x: int, y: int) -> int:
            \"\"\"Critical calculation.\"\"\"
            return x + y
        """
        path = _write_py(tmp_path, "calc.py", source)
        candidates = extractor.extract_from_file(path)

        assert len(candidates) >= 1
        annotated = [c for c in candidates if c.detection_method == "annotation"]
        assert len(annotated) == 1
        assert annotated[0].function_name == "important_calculation"

    def test_annotation_overrides_private(self, extractor, tmp_path):
        """Test # @pin allows extracting private functions."""
        source = """\
        # @pin
        def _internal_validator(data: dict) -> bool:
            \"\"\"Internal validation.\"\"\"
            return bool(data)
        """
        path = _write_py(tmp_path, "validators.py", source)
        candidates = extractor.extract_from_file(path)

        assert len(candidates) == 1
        assert candidates[0].function_name == "_internal_validator"
        assert candidates[0].detection_method == "annotation"

    def test_heuristic_requires_docstring(self, extractor, tmp_path):
        """Test that heuristic detection requires a docstring by default."""
        source = """\
        def no_docstring_func(x):
            return x * 2
        """
        path = _write_py(tmp_path, "funcs.py", source)
        candidates = extractor.extract_from_file(path)

        # Should not be detected because no docstring
        no_doc = [c for c in candidates if c.function_name == "no_docstring_func"]
        assert len(no_doc) == 0

    def test_heuristic_max_lines(self, tmp_path):
        """Test that heuristic detection respects max_function_lines."""
        config = ExtractionConfig(max_function_lines=5, require_docstring=False)
        ext = AtomFunctionExtractor(config)

        source = """\
        def short_func(x):
            return x

        def long_func(x):
            a = x + 1
            b = a + 2
            c = b + 3
            d = c + 4
            e = d + 5
            f = e + 6
            return f
        """
        path = _write_py(tmp_path, "funcs.py", source)
        candidates = ext.extract_from_file(path)

        names = {c.function_name for c in candidates}
        assert "short_func" in names
        assert "long_func" not in names

    def test_exclusion_patterns(self, extractor, tmp_path):
        """Test that files matching exclusion patterns are skipped."""
        source = """\
        def test_something():
            \"\"\"A test function.\"\"\"
            assert True
        """
        path = _write_py(tmp_path, "test_module.py", source)
        candidates = extractor.extract_from_file(path)
        assert candidates == []

    def test_conftest_excluded(self, extractor, tmp_path):
        source = """\
        def some_fixture():
            \"\"\"A fixture.\"\"\"
            return 42
        """
        path = _write_py(tmp_path, "conftest.py", source)
        candidates = extractor.extract_from_file(path)
        assert candidates == []

    def test_syntax_error_file(self, extractor, tmp_path):
        """Test that files with syntax errors return empty list."""
        path = tmp_path / "bad.py"
        path.write_text("def broken(:\n    pass\n", encoding="utf-8")
        candidates = extractor.extract_from_file(path)
        assert candidates == []

    def test_nonexistent_file(self, extractor, tmp_path):
        """Test that nonexistent files return empty list."""
        path = tmp_path / "nonexistent.py"
        candidates = extractor.extract_from_file(path)
        assert candidates == []


class TestShapeDetection:
    """Tests for pure function (shape) detection."""

    def test_pure_function_is_shape(self, extractor, tmp_path):
        source = """\
        def add(x: int, y: int) -> int:
            \"\"\"Add two numbers.\"\"\"
            return x + y
        """
        path = _write_py(tmp_path, "math_funcs.py", source)
        candidates = extractor.extract_from_file(path)

        assert len(candidates) >= 1
        add_func = [c for c in candidates if c.function_name == "add"][0]
        assert add_func.is_shape is True

    def test_global_disqualifies_shape(self, extractor, tmp_path):
        source = """\
        counter = 0
        def increment():
            \"\"\"Increment global counter.\"\"\"
            global counter
            counter += 1
        """
        path = _write_py(tmp_path, "state.py", source)
        candidates = extractor.extract_from_file(path)

        inc_func = [c for c in candidates if c.function_name == "increment"][0]
        assert inc_func.is_shape is False

    def test_io_call_disqualifies_shape(self, extractor, tmp_path):
        source = """\
        def log_result(msg: str) -> None:
            \"\"\"Log a message.\"\"\"
            print(msg)
        """
        path = _write_py(tmp_path, "logging_funcs.py", source)
        candidates = extractor.extract_from_file(path)

        log_func = [c for c in candidates if c.function_name == "log_result"][0]
        assert log_func.is_shape is False

    def test_attribute_mutation_disqualifies_shape(self, extractor, tmp_path):
        source = """\
        def modify_config(cfg):
            \"\"\"Modify a config.\"\"\"
            cfg.debug = True
            return cfg
        """
        path = _write_py(tmp_path, "config.py", source)
        candidates = extractor.extract_from_file(path)

        mod_func = [c for c in candidates if c.function_name == "modify_config"][0]
        assert mod_func.is_shape is False

    def test_self_mutation_allowed_for_shape(self, extractor, tmp_path):
        """self.attr = val should NOT disqualify shape."""
        source = """\
        class Calculator:
            def reset(self) -> None:
                \"\"\"Reset calculator state.\"\"\"
                self.total = 0
        """
        path = _write_py(tmp_path, "calc.py", source)
        candidates = extractor.extract_from_file(path)

        reset = [c for c in candidates if c.function_name == "reset"]
        if reset:
            assert reset[0].is_shape is True


class TestSignatureExtraction:
    """Tests for function signature extraction."""

    def test_simple_args(self, extractor, tmp_path):
        source = """\
        def func(a, b, c):
            \"\"\"Simple.\"\"\"
            pass
        """
        path = _write_py(tmp_path, "sigs.py", source)
        candidates = extractor.extract_from_file(path)
        sig = candidates[0].signature
        assert "(a, b, c)" == sig

    def test_typed_args(self, extractor, tmp_path):
        source = """\
        def func(x: int, y: str) -> bool:
            \"\"\"Typed.\"\"\"
            pass
        """
        path = _write_py(tmp_path, "sigs.py", source)
        candidates = extractor.extract_from_file(path)
        sig = candidates[0].signature
        assert "x: int" in sig
        assert "y: str" in sig
        assert "-> bool" in sig

    def test_default_values(self, extractor, tmp_path):
        source = """\
        def func(x: int = 10, y: str = "hello"):
            \"\"\"Defaults.\"\"\"
            pass
        """
        path = _write_py(tmp_path, "sigs.py", source)
        candidates = extractor.extract_from_file(path)
        sig = candidates[0].signature
        assert "x: int = 10" in sig
        assert "y: str = 'hello'" in sig

    def test_kwargs(self, extractor, tmp_path):
        source = """\
        def func(*args, **kwargs):
            \"\"\"Var args.\"\"\"
            pass
        """
        path = _write_py(tmp_path, "sigs.py", source)
        candidates = extractor.extract_from_file(path)
        sig = candidates[0].signature
        assert "*args" in sig
        assert "**kwargs" in sig

    def test_return_annotation(self, extractor, tmp_path):
        source = """\
        def func() -> None:
            \"\"\"No return.\"\"\"
            pass
        """
        path = _write_py(tmp_path, "sigs.py", source)
        candidates = extractor.extract_from_file(path)
        sig = candidates[0].signature
        assert "-> None" in sig


class TestBodyHash:
    """Tests for deterministic body hash computation."""

    def test_deterministic_hash(self, extractor, tmp_path):
        source = """\
        def func(x):
            \"\"\"Do something.\"\"\"
            return x + 1
        """
        path = _write_py(tmp_path, "hash.py", source)
        candidates1 = extractor.extract_from_file(path)
        candidates2 = extractor.extract_from_file(path)

        # Hash from body_source should be deterministic
        import hashlib
        import textwrap

        body1 = textwrap.dedent(candidates1[0].body_source).strip()
        body2 = textwrap.dedent(candidates2[0].body_source).strip()
        hash1 = hashlib.sha256(body1.encode()).hexdigest()
        hash2 = hashlib.sha256(body2.encode()).hexdigest()

        assert hash1 == hash2
        assert len(hash1) == 64

    def test_different_bodies_different_hashes(self, extractor, tmp_path):
        source1 = """\
        def func(x):
            \"\"\"Version 1.\"\"\"
            return x + 1
        """
        source2 = """\
        def func(x):
            \"\"\"Version 2.\"\"\"
            return x + 2
        """
        import hashlib
        import textwrap

        path1 = _write_py(tmp_path, "v1.py", source1)
        path2 = _write_py(tmp_path, "v2.py", source2)
        c1 = extractor.extract_from_file(path1)
        c2 = extractor.extract_from_file(path2)

        body1 = textwrap.dedent(c1[0].body_source).strip()
        body2 = textwrap.dedent(c2[0].body_source).strip()
        hash1 = hashlib.sha256(body1.encode()).hexdigest()
        hash2 = hashlib.sha256(body2.encode()).hexdigest()

        assert hash1 != hash2


class TestExtractFromDirectory:
    """Tests for directory-level extraction."""

    def test_recursive_extraction(self, extractor, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        source = """\
        def inner_func(x):
            \"\"\"Inner function.\"\"\"
            return x
        """
        _write_py(tmp_path, "top.py", source)
        _write_py(sub, "bottom.py", source)

        candidates = extractor.extract_from_directory(tmp_path, recursive=True)
        files = {c.file_path for c in candidates}
        assert len(files) == 2

    def test_non_recursive_extraction(self, extractor, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        source = """\
        def inner_func(x):
            \"\"\"Inner function.\"\"\"
            return x
        """
        _write_py(tmp_path, "top.py", source)
        _write_py(sub, "bottom.py", source)

        candidates = extractor.extract_from_directory(tmp_path, recursive=False)
        files = {c.file_path for c in candidates}
        assert len(files) == 1


class TestStoreReferences:
    """Tests for store reference detection."""

    def test_detect_db_reference(self, extractor, tmp_path):
        source = """\
        def save_data(db, record):
            \"\"\"Save to database.\"\"\"
            db.insert(record)
        """
        path = _write_py(tmp_path, "dao.py", source)
        candidates = extractor.extract_from_file(path)

        save = [c for c in candidates if c.function_name == "save_data"][0]
        assert "db" in save.store_references

    def test_detect_cache_reference(self, extractor, tmp_path):
        source = """\
        def get_cached(cache, key):
            \"\"\"Get from cache.\"\"\"
            return cache.get(key)
        """
        path = _write_py(tmp_path, "caching.py", source)
        candidates = extractor.extract_from_file(path)

        cached = [c for c in candidates if c.function_name == "get_cached"][0]
        assert "cache" in cached.store_references


class TestCalledFunctions:
    """Tests for called function detection."""

    def test_detect_called_functions(self, extractor, tmp_path):
        source = """\
        def orchestrator(data):
            \"\"\"Orchestrate processing.\"\"\"
            validated = validate(data)
            result = compute(validated)
            return format_output(result)
        """
        path = _write_py(tmp_path, "orch.py", source)
        candidates = extractor.extract_from_file(path)

        orch = [c for c in candidates if c.function_name == "orchestrator"][0]
        assert "validate" in orch.called_functions
        assert "compute" in orch.called_functions
        assert "format_output" in orch.called_functions
