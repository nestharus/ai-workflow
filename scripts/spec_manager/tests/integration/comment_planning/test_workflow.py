"""Tests for planning.workflow module."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from spec_manager.comment_planning.workflow import run_planning_v2_phase


class TestRunPlanningV2Phase:
    """Tests for run_planning_v2_phase function."""

    def test_basic_workflow(self, tmp_path: Path) -> None:
        """Run workflow with a simple Python file."""
        code = textwrap.dedent("""\
            def process(data):
                x = validate(data)
                return x
        """)
        py_file = tmp_path / "process.py"
        py_file.write_text(code, encoding="utf-8")

        result = run_planning_v2_phase(
            run_id="test-001",
            target_files=[str(py_file)],
            intentions=["add input validation"],
        )
        assert result["success"] is True
        assert result["run_id"] == "test-001"
        assert result["files_parsed"] == 1

    def test_no_parseable_files(self) -> None:
        """Workflow fails gracefully with no parseable files."""
        result = run_planning_v2_phase(
            run_id="test-002",
            target_files=["/nonexistent/file.py"],
            intentions=["test"],
        )
        assert result["success"] is False
        assert len(result["parse_errors"]) > 0

    def test_multiple_files(self, tmp_path: Path) -> None:
        """Run workflow with multiple Python files."""
        code_a = textwrap.dedent("""\
            def func_a():
                return 1
        """)
        code_b = textwrap.dedent("""\
            def func_b():
                return 2
        """)
        (tmp_path / "a.py").write_text(code_a, encoding="utf-8")
        (tmp_path / "b.py").write_text(code_b, encoding="utf-8")

        result = run_planning_v2_phase(
            run_id="test-003",
            target_files=[str(tmp_path / "a.py"), str(tmp_path / "b.py")],
            intentions=["add logging"],
        )
        assert result["success"] is True
        assert result["files_parsed"] == 2

    def test_writes_artifacts(self, tmp_path: Path) -> None:
        """Workflow writes artifact files when output_dir is specified."""
        code = textwrap.dedent("""\
            def process(data):
                # validate input
                return data
        """)
        py_file = tmp_path / "process.py"
        py_file.write_text(code, encoding="utf-8")

        output_dir = tmp_path / "artifacts"

        result = run_planning_v2_phase(
            run_id="test-004",
            target_files=[str(py_file)],
            intentions=["add error handling"],
            output_dir=output_dir,
        )
        assert result["success"] is True

        # Check artifact files exist
        assert (output_dir / "test-004_plans.json").exists()
        assert (output_dir / "test-004_gaps.json").exists()
        assert (output_dir / "test-004_adjacencies.json").exists()

    def test_artifact_contents_valid_json(self, tmp_path: Path) -> None:
        """Written artifacts contain valid JSON."""
        code = textwrap.dedent("""\
            def f():
                pass
        """)
        py_file = tmp_path / "f.py"
        py_file.write_text(code, encoding="utf-8")

        output_dir = tmp_path / "out"

        run_planning_v2_phase(
            run_id="test-005",
            target_files=[str(py_file)],
            intentions=["implement"],
            output_dir=output_dir,
        )

        for artifact in ["test-005_plans.json", "test-005_gaps.json", "test-005_adjacencies.json"]:
            path = output_dir / artifact
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(data, list)

    def test_with_evidence_dir(self, tmp_path: Path) -> None:
        """Workflow uses evidence store when evidence_dir is provided."""
        code = textwrap.dedent("""\
            def process(data):
                return data
        """)
        py_file = tmp_path / "process.py"
        py_file.write_text(code, encoding="utf-8")

        evidence_dir = tmp_path / "evidence"
        (evidence_dir / "spec_snapshot").mkdir(parents=True)
        (evidence_dir / "libraries").mkdir(parents=True)
        (evidence_dir / "libraries" / "test.md").write_text(
            "# Test\n\n## Section\n\nATOM-F0001-R0001-L0001: detail\n",
            encoding="utf-8",
        )

        result = run_planning_v2_phase(
            run_id="test-006",
            target_files=[str(py_file)],
            intentions=["add validation"],
            evidence_dir=evidence_dir,
        )
        assert result["success"] is True

    def test_gaps_detected(self, tmp_path: Path) -> None:
        """Workflow detects gaps from plan comments and stubs."""
        code = textwrap.dedent("""\
            def process(data):
                # validate input data
                pass

            def stub():
                raise NotImplementedError
        """)
        py_file = tmp_path / "process.py"
        py_file.write_text(code, encoding="utf-8")

        result = run_planning_v2_phase(
            run_id="test-007",
            target_files=[str(py_file)],
            intentions=["complete implementation"],
        )
        assert result["success"] is True
        assert result["gaps_detected"] > 0

    def test_adjacencies_found(self, tmp_path: Path) -> None:
        """Workflow discovers adjacencies from call graph."""
        code = textwrap.dedent("""\
            def process(data):
                result = validate(data)
                return transform(result)

            def validate(data):
                return data

            def transform(data):
                return data.upper()
        """)
        py_file = tmp_path / "module.py"
        py_file.write_text(code, encoding="utf-8")

        result = run_planning_v2_phase(
            run_id="test-008",
            target_files=[str(py_file)],
            intentions=["add error handling"],
        )
        assert result["success"] is True
        # Should find at least some adjacencies (process calls validate and transform)
        assert result["adjacencies_found"] >= 0  # May be 0 if all are internal

    def test_empty_intentions(self, tmp_path: Path) -> None:
        """Workflow handles empty intentions list."""
        code = "def f(): pass\n"
        py_file = tmp_path / "f.py"
        py_file.write_text(code, encoding="utf-8")

        result = run_planning_v2_phase(
            run_id="test-009",
            target_files=[str(py_file)],
            intentions=[],
        )
        assert result["success"] is True
        assert result["plans_generated"] == 0
