"""Tests for algorithmic layer gate checks."""

from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

from spec_manager.compliance.promotion.algorithmic_gates import (
    check_all_tests_pass,
    check_call_graph_connected,
    check_no_remaining_comments,
    check_no_stub_functions,
    check_store_monogamy,
)
from spec_manager.compliance.promotion.config import GateId, GateMode, GateSpec


def _write_py(tmpdir: Path, name: str, content: str) -> Path:
    """Write a Python file with dedented content."""
    path = tmpdir / name
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


class TestCheckNoRemainingComments:
    def test_clean_code_passes(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "clean.py", """\
            def compute(x):
                return x + 1
        """)
        gate_spec = GateSpec(gate_id=GateId.NO_REMAINING_COMMENTS)
        result = check_no_remaining_comments([f], gate_spec)
        assert result.passed is True
        assert result.gate_id == GateId.NO_REMAINING_COMMENTS.value
        assert len(result.findings) == 0

    def test_code_with_comments_fails(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "commented.py", """\
            def compute(x):
                # This needs implementation
                return x + 1
        """)
        gate_spec = GateSpec(gate_id=GateId.NO_REMAINING_COMMENTS)
        result = check_no_remaining_comments([f], gate_spec)
        assert result.passed is False
        assert len(result.findings) >= 1
        assert result.findings[0]["enclosing_function"] == "compute"

    def test_empty_file_list_passes(self) -> None:
        gate_spec = GateSpec(gate_id=GateId.NO_REMAINING_COMMENTS)
        result = check_no_remaining_comments([], gate_spec)
        assert result.passed is True

    def test_mode_propagated(self) -> None:
        gate_spec = GateSpec(
            gate_id=GateId.NO_REMAINING_COMMENTS, mode=GateMode.ADVISORY
        )
        result = check_no_remaining_comments([], gate_spec)
        assert result.mode == "advisory"

    def test_multiple_files(self, tmp_path: Path) -> None:
        f1 = _write_py(tmp_path, "a.py", """\
            def foo():
                # comment 1
                pass
        """)
        f2 = _write_py(tmp_path, "b.py", """\
            def bar():
                # comment 2
                return 1
        """)
        gate_spec = GateSpec(gate_id=GateId.NO_REMAINING_COMMENTS)
        result = check_no_remaining_comments([f1, f2], gate_spec)
        assert result.passed is False
        assert len(result.findings) >= 2


class TestCheckNoStubFunctions:
    def test_clean_code_passes(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "impl.py", """\
            def compute(x):
                return x * 2
        """)
        gate_spec = GateSpec(gate_id=GateId.NO_STUB_FUNCTIONS)
        result = check_no_stub_functions([f], gate_spec)
        assert result.passed is True
        assert len(result.findings) == 0

    def test_pass_stub_detected(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "stub.py", """\
            def not_done():
                pass
        """)
        gate_spec = GateSpec(gate_id=GateId.NO_STUB_FUNCTIONS)
        result = check_no_stub_functions([f], gate_spec)
        assert result.passed is False
        assert any(fd["stub_type"] == "pass" for fd in result.findings)

    def test_ellipsis_stub_detected(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "ellipsis_stub.py", """\
            def placeholder():
                ...
        """)
        gate_spec = GateSpec(gate_id=GateId.NO_STUB_FUNCTIONS)
        result = check_no_stub_functions([f], gate_spec)
        assert result.passed is False
        assert any(fd["stub_type"] == "ellipsis" for fd in result.findings)

    def test_not_implemented_stub_detected(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "ni_stub.py", """\
            def todo():
                raise NotImplementedError
        """)
        gate_spec = GateSpec(gate_id=GateId.NO_STUB_FUNCTIONS)
        result = check_no_stub_functions([f], gate_spec)
        assert result.passed is False
        assert any(fd["stub_type"] == "not_implemented" for fd in result.findings)

    def test_docstring_with_pass_is_stub(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "doc_stub.py", '''\
            def documented():
                """Will be implemented later."""
                pass
        ''')
        gate_spec = GateSpec(gate_id=GateId.NO_STUB_FUNCTIONS)
        result = check_no_stub_functions([f], gate_spec)
        assert result.passed is False

    def test_empty_file_list_passes(self) -> None:
        gate_spec = GateSpec(gate_id=GateId.NO_STUB_FUNCTIONS)
        result = check_no_stub_functions([], gate_spec)
        assert result.passed is True


class TestCheckAllTestsPass:
    def test_passing_command(self, tmp_path: Path) -> None:
        gate_spec = GateSpec(gate_id=GateId.ALL_TESTS_PASS)
        result = check_all_tests_pass(
            [sys.executable, "-c", "print('ok')"],
            tmp_path,
            gate_spec,
        )
        assert result.passed is True
        assert result.gate_id == GateId.ALL_TESTS_PASS.value

    def test_failing_command(self, tmp_path: Path) -> None:
        gate_spec = GateSpec(gate_id=GateId.ALL_TESTS_PASS)
        result = check_all_tests_pass(
            [sys.executable, "-c", "import sys; sys.exit(1)"],
            tmp_path,
            gate_spec,
        )
        assert result.passed is False
        assert len(result.findings) >= 1

    def test_command_not_found(self, tmp_path: Path) -> None:
        gate_spec = GateSpec(gate_id=GateId.ALL_TESTS_PASS)
        result = check_all_tests_pass(
            ["nonexistent_command_xyz"],
            tmp_path,
            gate_spec,
        )
        assert result.passed is False

    def test_timeout(self, tmp_path: Path) -> None:
        gate_spec = GateSpec(
            gate_id=GateId.ALL_TESTS_PASS,
            params={"timeout_seconds": 1},
        )
        result = check_all_tests_pass(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            tmp_path,
            gate_spec,
        )
        assert result.passed is False
        assert any("timed out" in str(f) for f in result.findings)


class TestCheckCallGraphConnected:
    def test_connected_graph_passes(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "connected.py", """\
            def a():
                b()

            def b():
                return 1
        """)
        gate_spec = GateSpec(gate_id=GateId.CALL_GRAPH_CONNECTED)
        result = check_call_graph_connected([f], tmp_path, gate_spec)
        assert result.passed is True

    def test_disconnected_graph_fails(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "disconnected.py", """\
            def a():
                b()

            def b():
                return 1

            def orphan_x():
                orphan_y()

            def orphan_y():
                return 2
        """)
        gate_spec = GateSpec(
            gate_id=GateId.CALL_GRAPH_CONNECTED,
            params={"min_component_size": 2},
        )
        result = check_call_graph_connected([f], tmp_path, gate_spec)
        assert result.passed is False
        assert len(result.findings) >= 1

    def test_single_function_passes(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "single.py", """\
            def only_one():
                return 42
        """)
        gate_spec = GateSpec(gate_id=GateId.CALL_GRAPH_CONNECTED)
        result = check_call_graph_connected([f], tmp_path, gate_spec)
        assert result.passed is True

    def test_empty_file_list(self) -> None:
        gate_spec = GateSpec(gate_id=GateId.CALL_GRAPH_CONNECTED)
        result = check_call_graph_connected(
            [], Path("."), gate_spec
        )
        assert result.passed is True


class TestCheckStoreMonogamy:
    def test_no_stores_passes(self, tmp_path: Path) -> None:
        f = _write_py(tmp_path, "logic.py", """\
            def compute():
                return 1
        """)
        gate_spec = GateSpec(gate_id=GateId.STORE_MONOGAMY)
        result = check_store_monogamy([f], tmp_path, gate_spec)
        assert result.passed is True

    def test_store_used_by_one_vertical(self, tmp_path: Path) -> None:
        # Create store file
        stores_dir = tmp_path / "vertical_a" / "stores"
        stores_dir.mkdir(parents=True)
        store_file = _write_py(stores_dir, "user_store.py", """\
            class UserStore:
                pass
        """)

        # Create a file in the same vertical that imports it
        consumer_dir = tmp_path / "vertical_a" / "logic"
        consumer_dir.mkdir(parents=True)
        consumer = _write_py(consumer_dir, "handler.py", """\
            from stores import user_store
            def handle():
                pass
        """)

        gate_spec = GateSpec(
            gate_id=GateId.STORE_MONOGAMY,
            params={"vertical_depth": 1},
        )
        all_files = [store_file, consumer]
        result = check_store_monogamy(all_files, tmp_path, gate_spec)
        assert result.passed is True

    def test_store_used_by_multiple_verticals_fails(self, tmp_path: Path) -> None:
        # Create store file
        stores_dir = tmp_path / "vertical_a" / "stores"
        stores_dir.mkdir(parents=True)
        store_file = _write_py(stores_dir, "shared_store.py", """\
            class SharedStore:
                pass
        """)

        # Consumer in vertical_a
        dir_a = tmp_path / "vertical_a" / "logic"
        dir_a.mkdir(parents=True)
        consumer_a = _write_py(dir_a, "handler_a.py", """\
            from stores import shared_store
            def handle_a():
                pass
        """)

        # Consumer in vertical_b
        dir_b = tmp_path / "vertical_b" / "logic"
        dir_b.mkdir(parents=True)
        consumer_b = _write_py(dir_b, "handler_b.py", """\
            from stores import shared_store
            def handle_b():
                pass
        """)

        gate_spec = GateSpec(
            gate_id=GateId.STORE_MONOGAMY,
            params={"vertical_depth": 1},
        )
        all_files = [store_file, consumer_a, consumer_b]
        result = check_store_monogamy(all_files, tmp_path, gate_spec)
        assert result.passed is False
        assert len(result.findings) >= 1
        # Verify the finding contains the store name and multiple verticals
        finding = result.findings[0]
        assert finding["store_name"] == "shared_store"
        assert finding["vertical_count"] > 1
