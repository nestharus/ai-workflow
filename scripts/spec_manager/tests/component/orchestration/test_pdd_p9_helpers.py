"""Tests for PddOrchestrator Phase 9 helper methods.

Tests _extract_body, _insert_imports, _apply_function_body,
_build_project_context, and _build_implementation_prompt to verify
fixes for:
- Bug 1: Agent uses edits instead of body field
- Bug 2: Import insertion inside module docstring
- Bug 3: Import insertion shifting line numbers during bottom-up processing
- Bug 4: No cross-file context in implementation prompt
- Bug 5: No retry on empty body (tested via prompt is_retry flag)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator

# ======================================================================
# _extract_body
# ======================================================================


class TestExtractBody:
    def test_returns_body_when_present(self) -> None:
        data = {"body": "        return 42\n"}
        assert PddOrchestrator._extract_body(data) == "        return 42\n"

    def test_empty_body_falls_back_to_edits(self) -> None:
        data = {
            "body": "",
            "edits": [
                {
                    "unified_diff": (
                        "--- a/foo.py\n"
                        "+++ b/foo.py\n"
                        "@@ -10,2 +10,3 @@\n"
                        "-        pass\n"
                        "+        count = 0\n"
                        "+        return count\n"
                    ),
                },
            ],
        }
        result = PddOrchestrator._extract_body(data)
        assert "count = 0" in result
        assert "return count" in result

    def test_missing_body_falls_back_to_edits(self) -> None:
        data = {
            "edits": [
                {
                    "unified_diff": ("+++ b/foo.py\n@@ -5,1 +5,2 @@\n+        x = 1\n"),
                },
            ],
        }
        result = PddOrchestrator._extract_body(data)
        assert "x = 1" in result

    def test_empty_body_empty_edits_returns_empty(self) -> None:
        data = {"body": "", "edits": []}
        assert PddOrchestrator._extract_body(data) == ""

    def test_no_body_no_edits_returns_empty(self) -> None:
        data = {}
        assert PddOrchestrator._extract_body(data) == ""

    def test_whitespace_only_body_falls_back(self) -> None:
        data = {
            "body": "   \n  ",
            "edits": [
                {
                    "unified_diff": ("@@ -1,1 +1,1 @@\n+        return True\n"),
                },
            ],
        }
        result = PddOrchestrator._extract_body(data)
        assert "return True" in result

    def test_diff_headers_excluded_from_body(self) -> None:
        data = {
            "body": "",
            "edits": [
                {
                    "unified_diff": (
                        "--- a/module.py\n"
                        "+++ b/module.py\n"
                        "@@ -10,2 +10,3 @@\n"
                        "+        result = []\n"
                    ),
                },
            ],
        }
        result = PddOrchestrator._extract_body(data)
        assert "---" not in result
        assert "+++" not in result
        assert "@@" not in result
        assert "result = []" in result


# ======================================================================
# _insert_imports
# ======================================================================


class TestInsertImports:
    def test_inserts_after_last_import(self) -> None:
        lines = [
            '"""Module doc."""\n',
            "\n",
            "import os\n",
            "from pathlib import Path\n",
            "\n",
            "def foo():\n",
            "    pass\n",
        ]
        result = PddOrchestrator._insert_imports(lines, ["import json"])
        text = "".join(result)
        # json should appear after "from pathlib import Path"
        json_idx = text.index("import json")
        path_idx = text.index("from pathlib import Path")
        foo_idx = text.index("def foo")
        assert json_idx > path_idx
        assert json_idx < foo_idx

    def test_skips_already_present_imports(self) -> None:
        lines = [
            "import os\n",
            "\n",
            "def foo():\n",
        ]
        result = PddOrchestrator._insert_imports(lines, ["import os"])
        assert result == lines

    def test_deduplicates_imports(self) -> None:
        lines = [
            "import os\n",
            "\n",
        ]
        result = PddOrchestrator._insert_imports(
            lines, ["import json", "import json", "import json"]
        )
        text = "".join(result)
        assert text.count("import json") == 1

    def test_no_imports_returns_unchanged(self) -> None:
        lines = ["def foo():\n", "    pass\n"]
        result = PddOrchestrator._insert_imports(lines, [])
        assert result == lines

    def test_does_not_insert_inside_docstring(self) -> None:
        lines = [
            '"""Module docstring.\n',
            "\n",
            "More description.\n",
            '"""\n',
            "\n",
            "import os\n",
            "\n",
            "def foo():\n",
        ]
        result = PddOrchestrator._insert_imports(lines, ["import json"])
        text = "".join(result)
        # import json must appear AFTER the closing docstring
        json_idx = text.index("import json")
        docstring_end_idx = text.index('"""', text.index('"""') + 3)
        assert json_idx > docstring_end_idx

    def test_inserts_after_docstring_when_no_imports_exist(self) -> None:
        lines = [
            '"""Module doc."""\n',
            "\n",
            "X = 1\n",
        ]
        result = PddOrchestrator._insert_imports(lines, ["import time"])
        text = "".join(result)
        # Should be after the docstring
        assert text.index("import time") > text.index('"""')


# ======================================================================
# _apply_function_body (no import insertion)
# ======================================================================


class TestApplyFunctionBody:
    def _make_func(
        self,
        line_start: int,
        line_end: int,
        body_start_line: int,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            line_start=line_start,
            line_end=line_end,
            body_start_line=body_start_line,
        )

    def test_replaces_body_preserving_signature(self) -> None:
        lines = [
            "def foo():\n",  # 1
            '    """Docstring."""\n',  # 2
            "    pass\n",  # 3
        ]
        func = self._make_func(1, 3, 3)
        result = PddOrchestrator._apply_function_body(
            lines,
            func,
            "    return 42\n",
            [],
        )
        assert result[0] == "def foo():\n"
        assert result[1] == '    """Docstring."""\n'
        assert result[2] == "    return 42\n"
        assert len(result) == 3

    def test_does_not_insert_imports(self) -> None:
        """_apply_function_body ignores imports_needed to avoid line drift."""
        lines = [
            "def foo():\n",
            "    pass\n",
        ]
        func = self._make_func(1, 2, 2)
        result = PddOrchestrator._apply_function_body(
            lines,
            func,
            "    return 1\n",
            ["import json"],
        )
        text = "".join(result)
        assert "import json" not in text

    def test_replaces_multiline_body(self) -> None:
        lines = [
            "def foo():\n",
            "    # spec comment\n",
            "    pass\n",
        ]
        func = self._make_func(1, 3, 2)
        new_body = "    x = 1\n    y = 2\n    return x + y\n"
        result = PddOrchestrator._apply_function_body(
            lines,
            func,
            new_body,
            [],
        )
        assert result[0] == "def foo():\n"
        assert "x = 1" in "".join(result)
        assert "return x + y" in "".join(result)

    def test_negative_body_start_returns_copy(self) -> None:
        lines = ["def foo():\n", "    pass\n"]
        func = self._make_func(1, 2, 0)  # body_start_line=0 -> idx=-1
        result = PddOrchestrator._apply_function_body(
            lines,
            func,
            "    return 1\n",
            [],
        )
        assert result == lines
        assert result is not lines

    def test_bottom_up_preserves_earlier_functions(self) -> None:
        """Simulate bottom-up: process func2 then func1, no import drift."""
        lines = [
            "import os\n",  # 1
            "\n",  # 2
            "def func1():\n",  # 3
            "    # spec1\n",  # 4
            "    pass\n",  # 5
            "\n",  # 6
            "def func2():\n",  # 7
            "    # spec2\n",  # 8
            "    pass\n",  # 9
        ]
        func2 = self._make_func(7, 9, 8)
        func1 = self._make_func(3, 5, 4)

        # Process bottom-up: func2 first
        lines = PddOrchestrator._apply_function_body(
            lines,
            func2,
            "    return 2\n",
            [],
        )
        # Then func1 — line numbers should still be valid
        lines = PddOrchestrator._apply_function_body(
            lines,
            func1,
            "    return 1\n",
            [],
        )

        text = "".join(lines)
        assert "def func1():" in text
        assert "return 1" in text
        assert "def func2():" in text
        assert "return 2" in text
        # Old bodies should be gone
        assert "# spec1" not in text
        assert "# spec2" not in text
        assert "pass" not in text


# ======================================================================
# _build_project_context
# ======================================================================


class TestBuildProjectContext:
    def _make_project_state(self, tmp_path: Path) -> SimpleNamespace:
        """Create a fake project state with two files."""
        # File A
        file_a = tmp_path / "service_a.py"
        file_a.write_text(
            '"""Service A."""\n'
            "\n"
            "import os\n"
            "\n"
            "class ServiceA:\n"
            '    """Service A class."""\n'
            "\n"
            "    def method_one(self) -> None:\n"
            "        pass\n"
            "\n"
            "    def method_two(self, x: int) -> int:\n"
            "        pass\n",
            encoding="utf-8",
        )
        file_a_state = SimpleNamespace(
            functions=[
                SimpleNamespace(line_start=8, qualified_name="ServiceA.method_one"),
                SimpleNamespace(line_start=11, qualified_name="ServiceA.method_two"),
            ],
        )
        # File B
        file_b = tmp_path / "service_b.py"
        file_b.write_text(
            '"""Service B."""\n'
            "\n"
            "from decimal import Decimal\n"
            "\n"
            'THRESHOLD = Decimal("100")\n'
            "\n"
            "class ServiceB:\n"
            "\n"
            "    def handle(self) -> bool:\n"
            "        pass\n",
            encoding="utf-8",
        )
        file_b_state = SimpleNamespace(
            functions=[
                SimpleNamespace(line_start=9, qualified_name="ServiceB.handle"),
            ],
        )
        return SimpleNamespace(
            files={
                str(file_a): file_a_state,
                str(file_b): file_b_state,
            }
        )

    def test_excludes_current_file(self, tmp_path: Path) -> None:
        state = self._make_project_state(tmp_path)
        file_a_path = str(tmp_path / "service_a.py")
        result = PddOrchestrator._build_project_context(state, file_a_path)
        assert "service_a.py" not in result
        assert "service_b.py" in result

    def test_includes_other_files_header_and_methods(self, tmp_path: Path) -> None:
        state = self._make_project_state(tmp_path)
        file_b_path = str(tmp_path / "service_b.py")
        result = PddOrchestrator._build_project_context(state, file_b_path)
        assert "service_a.py" in result
        assert "import os" in result
        assert "method_one" in result
        assert "method_two" in result

    def test_includes_constants_and_imports(self, tmp_path: Path) -> None:
        state = self._make_project_state(tmp_path)
        file_a_path = str(tmp_path / "service_a.py")
        result = PddOrchestrator._build_project_context(state, file_a_path)
        assert "THRESHOLD" in result
        assert "Decimal" in result

    def test_empty_current_file_returns_all(self, tmp_path: Path) -> None:
        state = self._make_project_state(tmp_path)
        result = PddOrchestrator._build_project_context(state, "nonexistent.py")
        assert "service_a.py" in result
        assert "service_b.py" in result


# ======================================================================
# _build_implementation_prompt
# ======================================================================


class TestBuildImplementationPrompt:
    def _make_func(self) -> SimpleNamespace:
        return SimpleNamespace(
            line_start=5,
            line_end=7,
            qualified_name="MyClass.my_method",
            spec_comments=[
                SimpleNamespace(text="Must handle cross-service events"),
            ],
        )

    def _make_file_state(self) -> SimpleNamespace:
        return SimpleNamespace(
            functions=[
                SimpleNamespace(
                    line_start=5,
                    qualified_name="MyClass.my_method",
                ),
                SimpleNamespace(
                    line_start=9,
                    qualified_name="MyClass.other_method",
                ),
            ],
        )

    def _make_file_content(self) -> str:
        return (
            '"""Module doc."""\n'
            "import os\n"
            "\n"
            "class MyClass:\n"
            "    def my_method(self) -> None:\n"
            "        # Must handle cross-service events\n"
            "        pass\n"
            "\n"
            "    def other_method(self) -> int:\n"
            "        return 1\n"
        )

    def test_includes_project_context_section(self) -> None:
        orch = PddOrchestrator.__new__(PddOrchestrator)
        result = orch._build_implementation_prompt(
            self._make_func(),
            self._make_file_content(),
            self._make_file_state(),
            project_context="### event_pipeline.py\n```\nclass EventPipeline:\n```\n",
        )
        assert "## OTHER FILES IN PROJECT" in result
        assert "EventPipeline" in result

    def test_no_project_context_omits_section(self) -> None:
        orch = PddOrchestrator.__new__(PddOrchestrator)
        result = orch._build_implementation_prompt(
            self._make_func(),
            self._make_file_content(),
            self._make_file_state(),
        )
        assert "## OTHER FILES IN PROJECT" not in result

    def test_retry_adds_emphasis(self) -> None:
        orch = PddOrchestrator.__new__(PddOrchestrator)
        result = orch._build_implementation_prompt(
            self._make_func(),
            self._make_file_content(),
            self._make_file_state(),
            is_retry=True,
        )
        assert "MUST provide a non-empty implementation" in result

    def test_no_retry_no_emphasis(self) -> None:
        orch = PddOrchestrator.__new__(PddOrchestrator)
        result = orch._build_implementation_prompt(
            self._make_func(),
            self._make_file_content(),
            self._make_file_state(),
            is_retry=False,
        )
        assert "MUST provide a non-empty implementation" not in result

    def test_includes_requirements(self) -> None:
        orch = PddOrchestrator.__new__(PddOrchestrator)
        result = orch._build_implementation_prompt(
            self._make_func(),
            self._make_file_content(),
            self._make_file_state(),
        )
        assert "Must handle cross-service events" in result

    def test_includes_other_methods(self) -> None:
        orch = PddOrchestrator.__new__(PddOrchestrator)
        result = orch._build_implementation_prompt(
            self._make_func(),
            self._make_file_content(),
            self._make_file_state(),
        )
        assert "other_method" in result
