"""Tests for CollapseEngine: codebase ingestion to Layer 1."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from spec_manager.branches.collapse import CollapseEngine, CollapseResult
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.types import AtomKind


@pytest.fixture
def layout(tmp_path: Path) -> BranchLayout:
    bl = BranchLayout(run_root=tmp_path)
    bl.initialize()
    return bl


@pytest.fixture
def engine(layout: BranchLayout) -> CollapseEngine:
    return CollapseEngine(layout)


def _mock_classify(func_info, body_source):
    """Deterministic mock for _llm_classify used in tests.

    Maps function names to expected classifications so tests remain
    deterministic without an actual LLM.
    """
    name = func_info.name.lower()
    # Shape: pure functions with a single return
    if name in ("add", "multiply", "helper"):
        return AtomKind.SHAPE
    # Store: functions that interact with databases/persistence
    if "database" in name or "save" in name or "db" in body_source.lower():
        return AtomKind.STORE
    # Architectural: middleware, retry, routing
    if "middleware" in name or "retry" in name or "handler" in name:
        return None
    # Default: algorithm
    return AtomKind.ALGORITHM


def _patch_llm_classify():
    """Patch _llm_classify with deterministic mock."""
    return patch(
        "spec_manager.branches.collapse._llm_classify",
        side_effect=_mock_classify,
    )


class TestClassification:
    """Tests for LLM-based function classification."""

    def test_classifies_pure_function_as_shape(
        self,
        engine: CollapseEngine,
        tmp_path: Path,
    ) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "math_utils.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n",
            encoding="utf-8",
        )
        with _patch_llm_classify():
            result = engine.collapse(src_dir)
        assert len(result.extracted_shapes) >= 1
        shape_names = [s.function_name for s in result.extracted_shapes]
        assert "add" in shape_names

    def test_classifies_store_function(
        self,
        engine: CollapseEngine,
        tmp_path: Path,
    ) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "data.py").write_text(
            "def save_to_database(record):\n"
            "    db = connect_database()\n"
            "    db.insert(record)\n"
            "    db.commit()\n",
            encoding="utf-8",
        )
        with _patch_llm_classify():
            result = engine.collapse(src_dir)
        assert len(result.extracted_stores) >= 1

    def test_classifies_middleware_as_architectural(
        self,
        engine: CollapseEngine,
        tmp_path: Path,
    ) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "middleware.py").write_text(
            "def retry_middleware(handler, request, response):\n"
            "    for attempt in range(3):\n"
            "        try:\n"
            "            return handler(request)\n"
            "        except Exception:\n"
            "            if attempt == 2:\n"
            "                raise\n",
            encoding="utf-8",
        )
        with _patch_llm_classify():
            result = engine.collapse(src_dir)
        # Should be classified as architectural remnant
        assert len(result.architectural_remnants) >= 1

    def test_classifies_algorithm(
        self,
        engine: CollapseEngine,
        tmp_path: Path,
    ) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "process.py").write_text(
            "def process_order(order):\n"
            "    validated = validate(order)\n"
            "    enriched = enrich(validated)\n"
            "    result = transform(enriched)\n"
            "    return result\n",
            encoding="utf-8",
        )
        with _patch_llm_classify():
            result = engine.collapse(src_dir)
        assert len(result.extracted_atoms) >= 1

    def test_llm_failure_defaults_to_algorithm(
        self,
        engine: CollapseEngine,
        tmp_path: Path,
    ) -> None:
        """When the LLM agent fails, _llm_classify defaults to ALGORITHM."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "utils.py").write_text(
            "def compute(x):\n    return x * 2\n",
            encoding="utf-8",
        )
        with patch(
            "spec_manager.core.agent_utils.run_agent",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result = engine.collapse(src_dir)
        # _llm_classify catches the exception and returns ALGORITHM
        assert len(result.extracted_atoms) >= 1
        atom_names = [a.function_name for a in result.extracted_atoms]
        assert "compute" in atom_names


class TestCollapseWorkflow:
    """Tests for the full collapse workflow."""

    def test_empty_directory(self, engine: CollapseEngine, tmp_path: Path) -> None:
        src_dir = tmp_path / "empty_src"
        src_dir.mkdir()
        result = engine.collapse(src_dir)
        assert result.extracted_atoms == []
        assert result.extracted_stores == []
        assert result.extracted_shapes == []
        assert len(result.warnings) >= 1  # "No Python files"

    def test_nonexistent_directory(self, engine: CollapseEngine, tmp_path: Path) -> None:
        result = engine.collapse(tmp_path / "nonexistent")
        assert len(result.warnings) >= 1

    def test_skips_init_files(self, engine: CollapseEngine, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "__init__.py").write_text("x = 1\n", encoding="utf-8")
        result = engine.collapse(src_dir)
        assert result.extracted_atoms == []
        assert result.architectural_remnants == []

    def test_handles_syntax_errors(self, engine: CollapseEngine, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        result = engine.collapse(src_dir)
        assert any("Syntax error" in w for w in result.warnings)

    def test_extracts_class_methods(self, engine: CollapseEngine, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "service.py").write_text(
            "class Calculator:\n"
            "    def multiply(self, a: int, b: int) -> int:\n"
            "        return a * b\n",
            encoding="utf-8",
        )
        with _patch_llm_classify():
            result = engine.collapse(src_dir)
        # The method should be extracted (either as shape or algorithm)
        all_extracted = result.extracted_atoms + result.extracted_shapes + result.extracted_stores
        assert len(all_extracted) >= 1

    def test_atom_descriptor_fields(self, engine: CollapseEngine, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "utils.py").write_text(
            "def helper(x: int) -> int:\n    return x * 2\n",
            encoding="utf-8",
        )
        with _patch_llm_classify():
            result = engine.collapse(src_dir)
        all_extracted = result.extracted_atoms + result.extracted_shapes + result.extracted_stores
        assert len(all_extracted) >= 1

        desc = all_extracted[0]
        assert desc.atom_id.startswith("utils.py:")
        assert desc.introduced_by == "collapse"
        assert desc.content_hash != ""
        assert desc.signature != ""


class TestCollapseWithLabyrinth:
    """Integration test against the labyrinth codebase."""

    def test_collapse_labyrinth(self, engine: CollapseEngine) -> None:
        labyrinth_dir = (
            Path(__file__).resolve().parents[4] / "spec_manager" / "spec_manager" / "labyrinth"
        )
        if not labyrinth_dir.exists():
            pytest.skip("Labyrinth codebase not found")

        with _patch_llm_classify():
            result = engine.collapse(labyrinth_dir)

        # Should find functions across multiple categories
        total = (
            len(result.extracted_atoms)
            + len(result.extracted_stores)
            + len(result.extracted_shapes)
            + len(result.architectural_remnants)
        )
        assert total > 0, "Should find at least some functions"

        # Labyrinth has async bus code (architectural)
        # and record dataclasses (shapes) and services
        assert len(result.extracted_shapes) + len(result.extracted_atoms) > 0
        assert len(result.warnings) == 0 or all("Syntax error" not in w for w in result.warnings)


class TestCollapseResultSerialization:
    """Tests for CollapseResult serialization."""

    def test_roundtrip(self) -> None:
        from spec_manager.branches.types import AtomDescriptor

        atom = AtomDescriptor(
            atom_id="test:func",
            kind=AtomKind.ALGORITHM,
            file_path="test.py",
            function_name="func",
            signature="()",
            content_hash="abc",
            introduced_by="collapse",
        )
        original = CollapseResult(
            extracted_atoms=[atom],
            extracted_stores=[],
            extracted_shapes=[],
            architectural_remnants=["middleware.py:retry"],
            ambiguous_code=["utils.py:helper"],
            warnings=["No files in subdir"],
        )
        data = original.to_dict()
        restored = CollapseResult.from_dict(data)
        assert len(restored.extracted_atoms) == 1
        assert restored.architectural_remnants == ["middleware.py:retry"]
        assert restored.warnings == ["No files in subdir"]
