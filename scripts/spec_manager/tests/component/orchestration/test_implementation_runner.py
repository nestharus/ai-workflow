from __future__ import annotations

import json
from pathlib import Path

from spec_manager.orchestration.implementation.runner import (
    ImplementationRunner,
    ImplementationRunResult,
)
from spec_manager.orchestration.implementation.types import (
    EdgeProposal,
    PinProposal,
    TestArtifact,
    UnderSpecEvent,
)


class MockFunc:
    def __init__(
        self,
        body_start_line: int,
        line_end: int,
        qualified_name: str = "test_func",
    ) -> None:
        self.body_start_line = body_start_line
        self.line_end = line_end
        self.qualified_name = qualified_name


# ======================================================================
# ImplementationRunResult
# ======================================================================


class TestImplementationRunResult:
    def test_defaults(self) -> None:
        r = ImplementationRunResult()
        assert r.patch_path == ""
        assert r.applied_edits == []
        assert r.pin_proposals == []
        assert r.edge_proposals == []
        assert r.under_spec_events == []
        assert r.tests_added == []
        assert r.notes_path == ""
        assert r.functions_implemented == 0
        assert r.functions_skipped == 0
        assert r.errors == []

    def test_list_fields_not_shared(self) -> None:
        r1 = ImplementationRunResult()
        r2 = ImplementationRunResult()
        r1.applied_edits.append({"f": "x"})
        r1.pin_proposals.append({"pin": "p"})
        r1.edge_proposals.append({"edge": "e"})
        r1.under_spec_events.append({"kind": "k"})
        r1.tests_added.append("t.py")
        r1.errors.append({"error": "e"})
        assert r2.applied_edits == []
        assert r2.pin_proposals == []
        assert r2.edge_proposals == []
        assert r2.under_spec_events == []
        assert r2.tests_added == []
        assert r2.errors == []

    def test_mutable_fields(self) -> None:
        r = ImplementationRunResult()
        r.functions_implemented = 5
        r.functions_skipped = 2
        r.patch_path = "/tmp/patch.diff"
        r.notes_path = "/tmp/notes.md"
        assert r.functions_implemented == 5
        assert r.functions_skipped == 2
        assert r.patch_path == "/tmp/patch.diff"
        assert r.notes_path == "/tmp/notes.md"


# ======================================================================
# _apply_function_body
# ======================================================================


class TestApplyFunctionBody:
    def test_body_replacement_preserves_surrounding_code(self) -> None:
        lines = [
            "import os\n",
            "\n",
            "def test_func():\n",
            "    pass\n",
            "\n",
            "x = 1\n",
        ]
        func = MockFunc(body_start_line=4, line_end=4)
        new_body = "    return 42\n"

        result = ImplementationRunner._apply_function_body(lines, func, new_body, [])

        assert result[0] == "import os\n"
        assert result[1] == "\n"
        assert result[2] == "def test_func():\n"
        assert result[3] == "    return 42\n"
        assert result[4] == "\n"
        assert result[5] == "x = 1\n"

    def test_multi_line_body_replacement(self) -> None:
        lines = [
            "def func():\n",
            "    pass\n",
        ]
        func = MockFunc(body_start_line=2, line_end=2)
        new_body = "    x = 1\n    y = 2\n    return x + y\n"

        result = ImplementationRunner._apply_function_body(lines, func, new_body, [])

        assert result[0] == "def func():\n"
        assert result[1] == "    x = 1\n"
        assert result[2] == "    y = 2\n"
        assert result[3] == "    return x + y\n"

    def test_body_without_trailing_newline(self) -> None:
        lines = [
            "def func():\n",
            "    pass\n",
        ]
        func = MockFunc(body_start_line=2, line_end=2)
        new_body = "    return 0"

        result = ImplementationRunner._apply_function_body(lines, func, new_body, [])

        assert "    return 0\n" in result

    def test_import_injection_adds_missing_imports(self) -> None:
        lines = [
            "import os\n",
            "\n",
            "def func():\n",
            "    pass\n",
        ]
        func = MockFunc(body_start_line=4, line_end=4)
        new_body = "    return json.dumps({})\n"
        imports = ["import json"]

        result = ImplementationRunner._apply_function_body(lines, func, new_body, imports)

        text = "".join(result)
        assert "import json" in text

    def test_import_injection_does_not_duplicate(self) -> None:
        lines = [
            "import os\n",
            "\n",
            "def func():\n",
            "    pass\n",
        ]
        func = MockFunc(body_start_line=4, line_end=4)
        new_body = "    return os.getcwd()\n"
        imports = ["import os"]

        result = ImplementationRunner._apply_function_body(lines, func, new_body, imports)

        text = "".join(result)
        assert text.count("import os") == 1

    def test_invalid_body_start_line_returns_copy(self) -> None:
        lines = [
            "def func():\n",
            "    pass\n",
        ]
        func = MockFunc(body_start_line=0, line_end=2)
        new_body = "    return 1\n"

        result = ImplementationRunner._apply_function_body(lines, func, new_body, [])

        assert result == lines
        assert result is not lines

    def test_multiple_imports_injected(self) -> None:
        lines = [
            "import os\n",
            "\n",
            "def func():\n",
            "    pass\n",
        ]
        func = MockFunc(body_start_line=4, line_end=4)
        new_body = "    return 1\n"
        imports = ["import json", "import sys"]

        result = ImplementationRunner._apply_function_body(lines, func, new_body, imports)

        text = "".join(result)
        assert "import json" in text
        assert "import sys" in text

    def test_empty_imports_list(self) -> None:
        lines = [
            "def func():\n",
            "    pass\n",
        ]
        func = MockFunc(body_start_line=2, line_end=2)
        new_body = "    return 1\n"

        result = ImplementationRunner._apply_function_body(lines, func, new_body, [])

        assert result[0] == "def func():\n"
        assert result[1] == "    return 1\n"

    def test_replaces_multi_line_original_body(self) -> None:
        lines = [
            "def func():\n",
            "    x = 1\n",
            "    y = 2\n",
            "    return x + y\n",
            "\n",
            "other = True\n",
        ]
        func = MockFunc(body_start_line=2, line_end=4)
        new_body = "    return 99\n"

        result = ImplementationRunner._apply_function_body(lines, func, new_body, [])

        assert result[0] == "def func():\n"
        assert result[1] == "    return 99\n"
        assert result[2] == "\n"
        assert result[3] == "other = True\n"


# ======================================================================
# _write_artifacts
# ======================================================================


class TestWriteArtifacts:
    def test_writes_pin_proposals(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        pins = [PinProposal(pin_id="PIN-1", fqn="foo:bar", file="foo.py")]

        ImplementationRunner._write_artifacts(tmp_path, result, pins, [], [], [], [])

        path = tmp_path / "pin_proposals.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["pin_id"] == "PIN-1"

    def test_writes_edge_proposals(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        edges = [EdgeProposal(src="PIN-1", dst="PIN-2")]

        ImplementationRunner._write_artifacts(tmp_path, result, [], edges, [], [], [])

        path = tmp_path / "edge_proposals.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["src"] == "PIN-1"
        assert data[0]["dst"] == "PIN-2"

    def test_writes_under_spec_events(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        events = [UnderSpecEvent(kind="MISSING_CONSTRAINT", question="Why?")]

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], events, [], [])

        path = tmp_path / "under_spec_events.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["kind"] == "MISSING_CONSTRAINT"
        assert data[0]["question"] == "Why?"

    def test_writes_tests_added(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        tests = [TestArtifact(path="test_foo.py", purpose="unit test")]

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], [], tests, [])

        path = tmp_path / "tests_added.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["path"] == "test_foo.py"

    def test_writes_notes(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        notes = ["First note", "Second note"]

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], [], [], notes)

        path = tmp_path / "notes.md"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "First note" in content
        assert "Second note" in content
        assert "\n\n---\n\n" in content
        assert result.notes_path == str(path)

    def test_skips_empty_collections(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], [], [], [])

        assert not (tmp_path / "pin_proposals.json").exists()
        assert not (tmp_path / "edge_proposals.json").exists()
        assert not (tmp_path / "under_spec_events.json").exists()
        assert not (tmp_path / "tests_added.json").exists()
        assert not (tmp_path / "notes.md").exists()

    def test_sets_patch_path_when_pins_present(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        pins = [PinProposal(pin_id="PIN-1", fqn="f", file="f.py")]

        ImplementationRunner._write_artifacts(tmp_path, result, pins, [], [], [], [])

        assert result.patch_path == str(tmp_path / "patch.diff")

    def test_writes_all_artifacts_together(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        pins = [PinProposal(pin_id="PIN-1", fqn="f", file="f.py")]
        edges = [EdgeProposal(src="PIN-1", dst="PIN-2")]
        events = [UnderSpecEvent(question="Q")]
        tests = [TestArtifact(path="t.py", purpose="p")]
        notes = ["note"]

        ImplementationRunner._write_artifacts(tmp_path, result, pins, edges, events, tests, notes)

        assert (tmp_path / "pin_proposals.json").exists()
        assert (tmp_path / "edge_proposals.json").exists()
        assert (tmp_path / "under_spec_events.json").exists()
        assert (tmp_path / "tests_added.json").exists()
        assert (tmp_path / "notes.md").exists()

    def test_artifact_json_is_formatted(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        pins = [PinProposal(pin_id="PIN-1", fqn="f", file="f.py")]

        ImplementationRunner._write_artifacts(tmp_path, result, pins, [], [], [], [])

        content = (tmp_path / "pin_proposals.json").read_text(encoding="utf-8")
        assert "\n" in content
        assert "  " in content
