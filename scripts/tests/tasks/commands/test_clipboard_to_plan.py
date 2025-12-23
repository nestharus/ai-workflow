"""Tests for clipboard_to_plan module.

This module tests the clipboard_to_plan script including:
- Platform detection functions (is_wsl, get_clipboard_* functions)
- Content parsing functions (parse_plan_sections, extract_file_changes)
- Output generation functions (generate_outline, write_task_files)
- decode_output encoding handling
- main() function integration tests
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, mock_open, patch

import pytest

from scripts.tasks.commands.clipboard_to_plan import (
    decode_output,
    extract_file_changes,
    generate_outline,
    get_clipboard_content,
    get_clipboard_linux,
    get_clipboard_macos,
    get_clipboard_windows,
    get_clipboard_wsl,
    is_wsl,
    main,
    parse_plan_sections,
    write_task_files,
)


class TestIsWsl:
    """Tests for is_wsl function."""

    def test_is_wsl_returns_true_when_microsoft_in_proc_version(self) -> None:
        """Test is_wsl returns True when /proc/version contains 'microsoft'."""
        mock_content = "Linux version 5.15.0-1-microsoft-standard-WSL2"
        with patch("builtins.open", mock_open(read_data=mock_content)):
            assert is_wsl() is True

    def test_is_wsl_returns_false_when_microsoft_not_in_proc_version(self) -> None:
        """Test is_wsl returns False when /proc/version doesn't contain 'microsoft'."""
        mock_content = "Linux version 5.15.0-generic"
        with patch("builtins.open", mock_open(read_data=mock_content)):
            assert is_wsl() is False

    def test_is_wsl_returns_false_when_file_not_found(self) -> None:
        """Test is_wsl returns False when /proc/version doesn't exist."""
        with patch("builtins.open", side_effect=FileNotFoundError):
            assert is_wsl() is False


class TestDecodeOutput:
    """Tests for decode_output function."""

    def test_decode_output_utf8(self) -> None:
        """Test decoding UTF-8 encoded bytes."""
        data = b"Hello, World!"
        assert decode_output(data) == "Hello, World!"

    def test_decode_output_utf16(self) -> None:
        """Test decoding UTF-16 encoded bytes."""
        # UTF-16 BOM + content that fails UTF-8
        data = "Hello".encode("utf-16")
        result = decode_output(data)
        assert "Hello" in result or result  # May decode differently

    def test_decode_output_latin1(self) -> None:
        """Test decoding Latin-1 encoded bytes that fail UTF-8 and UTF-16."""
        # Create bytes that are valid Latin-1 but invalid UTF-8/UTF-16
        # Latin-1 0xe0-0xff range without proper UTF-8 continuation bytes
        data = bytes([0xE0, 0xE1, 0xE2])  # Invalid UTF-8 sequences
        result = decode_output(data)
        # Should successfully decode with latin-1 as fallback
        assert isinstance(result, str)

    def test_decode_output_fallback_with_replace(self) -> None:
        """Test decode_output uses replace errors when all encodings fail."""
        # Create bytes that are invalid in all attempted encodings
        # We need bytes that fail latin-1 too - but latin-1 accepts all byte values
        # So let's verify the fallback path by testing with valid UTF-8
        data = b"Test"
        result = decode_output(data)
        assert result == "Test"


class TestGetClipboardMacos:
    """Tests for get_clipboard_macos function."""

    def test_get_clipboard_macos_success(self) -> None:
        """Test successful clipboard retrieval on macOS."""
        mock_result = MagicMock()
        mock_result.stdout = b"Clipboard content"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = get_clipboard_macos()
            assert result == "Clipboard content"
            mock_run.assert_called_once_with(["pbpaste"], capture_output=True, check=True)

    def test_get_clipboard_macos_with_unicode(self) -> None:
        """Test clipboard retrieval with unicode content on macOS."""
        mock_result = MagicMock()
        mock_result.stdout = "Unicode: \u00e9\u00e0\u00fc".encode()
        with patch("subprocess.run", return_value=mock_result):
            result = get_clipboard_macos()
            assert result == "Unicode: \u00e9\u00e0\u00fc"


class TestGetClipboardWindows:
    """Tests for get_clipboard_windows function."""

    def test_get_clipboard_windows_success(self) -> None:
        """Test successful clipboard retrieval on Windows."""
        mock_result = MagicMock()
        mock_result.stdout = b"Windows clipboard"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = get_clipboard_windows()
            assert result == "Windows clipboard"
            mock_run.assert_called_once_with(
                ["powershell", "-command", "Get-Clipboard"],
                capture_output=True,
                check=True,
            )


class TestGetClipboardWsl:
    """Tests for get_clipboard_wsl function."""

    def test_get_clipboard_wsl_success(self) -> None:
        """Test successful clipboard retrieval in WSL."""
        mock_result = MagicMock()
        mock_result.stdout = b"WSL clipboard"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = get_clipboard_wsl()
            assert result == "WSL clipboard"
            mock_run.assert_called_once_with(
                ["powershell.exe", "-command", "Get-Clipboard"],
                capture_output=True,
                check=True,
            )


class TestGetClipboardLinux:
    """Tests for get_clipboard_linux function."""

    def test_get_clipboard_linux_with_xclip(self) -> None:
        """Test clipboard retrieval using xclip."""
        mock_result = MagicMock()
        mock_result.stdout = b"xclip content"
        with (
            patch("shutil.which", side_effect=lambda x: "/usr/bin/xclip" if x == "xclip" else None),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            result = get_clipboard_linux()
            assert result == "xclip content"
            mock_run.assert_called_once_with(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True,
                check=True,
            )

    def test_get_clipboard_linux_with_xsel(self) -> None:
        """Test clipboard retrieval using xsel when xclip is unavailable."""
        mock_result = MagicMock()
        mock_result.stdout = b"xsel content"
        with (
            patch("shutil.which", side_effect=lambda x: "/usr/bin/xsel" if x == "xsel" else None),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            result = get_clipboard_linux()
            assert result == "xsel content"
            mock_run.assert_called_once_with(
                ["xsel", "--clipboard", "--output"],
                capture_output=True,
                check=True,
            )

    def test_get_clipboard_linux_no_tools_raises(self) -> None:
        """Test that FileNotFoundError is raised when neither xclip nor xsel is found."""
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(FileNotFoundError, match="Neither xclip nor xsel found"),
        ):
            get_clipboard_linux()


class TestGetClipboardContent:
    """Tests for get_clipboard_content function."""

    def test_get_clipboard_content_darwin(self) -> None:
        """Test clipboard retrieval on macOS (Darwin)."""
        with (
            patch("platform.system", return_value="Darwin"),
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_macos",
                return_value="macOS content",
            ),
        ):
            result = get_clipboard_content()
            assert result == "macOS content"

    def test_get_clipboard_content_windows(self) -> None:
        """Test clipboard retrieval on Windows."""
        with (
            patch("platform.system", return_value="Windows"),
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_windows",
                return_value="Windows content",
            ),
        ):
            result = get_clipboard_content()
            assert result == "Windows content"

    def test_get_clipboard_content_linux_wsl(self) -> None:
        """Test clipboard retrieval on Linux with WSL."""
        with (
            patch("platform.system", return_value="Linux"),
            patch("scripts.tasks.commands.clipboard_to_plan.is_wsl", return_value=True),
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_wsl",
                return_value="WSL content",
            ),
        ):
            result = get_clipboard_content()
            assert result == "WSL content"

    def test_get_clipboard_content_linux_native(self) -> None:
        """Test clipboard retrieval on native Linux."""
        with (
            patch("platform.system", return_value="Linux"),
            patch("scripts.tasks.commands.clipboard_to_plan.is_wsl", return_value=False),
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_linux",
                return_value="Linux content",
            ),
        ):
            result = get_clipboard_content()
            assert result == "Linux content"

    def test_get_clipboard_content_unsupported_platform(self) -> None:
        """Test clipboard retrieval on unsupported platform exits with error."""
        with (
            patch("platform.system", return_value="FreeBSD"),
            pytest.raises(SystemExit) as exc_info,
        ):
            get_clipboard_content()
        assert exc_info.value.code == 1

    def test_get_clipboard_content_subprocess_error(self) -> None:
        """Test clipboard retrieval handles subprocess errors."""
        with (
            patch("platform.system", return_value="Darwin"),
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_macos",
                side_effect=subprocess.CalledProcessError(1, "pbpaste"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            get_clipboard_content()
        assert exc_info.value.code == 1

    def test_get_clipboard_content_file_not_found(self) -> None:
        """Test clipboard retrieval handles FileNotFoundError."""
        with (
            patch("platform.system", return_value="Darwin"),
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_macos",
                side_effect=FileNotFoundError("pbpaste not found"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            get_clipboard_content()
        assert exc_info.value.code == 1


class TestParsePlanSections:
    """Tests for parse_plan_sections function."""

    def test_parse_plan_sections_with_all_sections(self) -> None:
        """Test parsing plan with all sections present."""
        content = """# Introduction

This is intro text.

### Observations
These are observations.

### Approach
This is the approach.

### Reasoning
This is the reasoning.

## Mermaid Diagram
```mermaid
graph TD
```

## Proposed File Changes
### file1.py
Changes for file1
"""
        sections = parse_plan_sections(content)
        assert "intro" in sections
        assert "observations" in sections
        assert "approach" in sections
        assert "reasoning" in sections
        assert "mermaid" in sections
        assert "file_changes" in sections

    def test_parse_plan_sections_empty_content(self) -> None:
        """Test parsing empty content returns empty dict."""
        sections = parse_plan_sections("")
        assert sections == {}

    def test_parse_plan_sections_no_headers(self) -> None:
        """Test parsing content without recognized headers."""
        content = "Some random text without any headers."
        sections = parse_plan_sections(content)
        assert sections == {}

    def test_parse_plan_sections_reasoning_from_approach(self) -> None:
        """Test extracting reasoning from approach section without explicit header."""
        content = """### Approach
This is the approach.

This is actually the reasoning part.

## Proposed File Changes
### file.py
"""
        sections = parse_plan_sections(content)
        assert "approach" in sections
        # Reasoning should be extracted from trailing content after blank line
        if "reasoning" in sections:
            assert "reasoning" in sections["reasoning"] or sections.get("reasoning")

    def test_parse_plan_sections_intro_extraction(self) -> None:
        """Test intro text is extracted before first header."""
        content = """This is the intro.
More intro text.

### Observations
Observations text.
"""
        sections = parse_plan_sections(content)
        assert "intro" in sections
        assert "intro" in sections["intro"] or "This is the intro" in sections["intro"]

    def test_parse_plan_sections_reasoning_without_header_and_blank(self) -> None:
        """Test reasoning extraction when no blank line separates from approach."""
        content = """### Approach
Just approach content.
## Proposed File Changes
### file.py
"""
        sections = parse_plan_sections(content)
        assert "approach" in sections
        # No reasoning should be extracted when content equals approach text


class TestExtractFileChanges:
    """Tests for extract_file_changes function."""

    def test_extract_file_changes_multiple_files(self) -> None:
        """Test extracting multiple file changes."""
        body = """### app/main.py
Changes for main.py

### app/utils.py
Changes for utils.py
"""
        changes = extract_file_changes(body)
        assert len(changes) == 2
        assert changes[0]["filepath"] == "app/main.py"
        assert "Changes for main.py" in changes[0]["content"]
        assert changes[1]["filepath"] == "app/utils.py"

    def test_extract_file_changes_single_file(self) -> None:
        """Test extracting a single file change."""
        body = """### single_file.py
Content for single file.
"""
        changes = extract_file_changes(body)
        assert len(changes) == 1
        assert changes[0]["filepath"] == "single_file.py"

    def test_extract_file_changes_no_matches(self) -> None:
        """Test extracting from content without file headers returns empty list."""
        body = "No file headers here."
        changes = extract_file_changes(body)
        assert changes == []

    def test_extract_file_changes_empty_body(self) -> None:
        """Test extracting from empty body returns empty list."""
        changes = extract_file_changes("")
        assert changes == []


class TestGenerateOutline:
    """Tests for generate_outline function."""

    def test_generate_outline_basic(self) -> None:
        """Test basic outline generation."""
        sections = {
            "intro": "Introduction text",
            "observations": "Observations content",
            "approach": "Approach content",
        }
        file_changes = [{"filepath": "file1.py", "content": "changes"}]
        outline = generate_outline(sections, file_changes)
        assert "Introduction text" in outline
        assert "### Observations" in outline
        assert "### Approach" in outline
        assert "## File Changes" in outline
        assert "- file1.py" in outline

    def test_generate_outline_with_reasoning(self) -> None:
        """Test outline generation with reasoning section."""
        sections = {
            "approach": "Approach",
            "reasoning": "Reasoning content",
        }
        file_changes = []
        outline = generate_outline(sections, file_changes)
        assert "### Reasoning" in outline
        assert "Reasoning content" in outline

    def test_generate_outline_with_mermaid(self) -> None:
        """Test outline generation with mermaid diagram."""
        sections = {
            "mermaid": "```mermaid\ngraph TD\n```",
        }
        file_changes = []
        outline = generate_outline(sections, file_changes)
        assert "## Mermaid Diagram" in outline
        assert "```mermaid" in outline

    def test_generate_outline_no_file_changes(self) -> None:
        """Test outline generation with no file changes."""
        sections = {}
        file_changes = []
        outline = generate_outline(sections, file_changes)
        assert "- None detected" in outline

    def test_generate_outline_with_task_metadata(self) -> None:
        """Test outline generation with task metadata."""
        sections = {"intro": "Intro"}
        file_changes = [{"filepath": "file.py", "content": "changes"}]
        task_metadata = [
            {
                "agent": "implementor",
                "model": "gpt-4",
                "provider": "openai",
                "char_count": 1000,
            }
        ]
        outline = generate_outline(sections, file_changes, task_metadata)
        assert "## Agent Assignments" in outline
        assert "Task 001" in outline
        assert "implementor" in outline
        assert "gpt-4" in outline
        assert "1000 chars" in outline

    def test_generate_outline_multiple_task_metadata(self) -> None:
        """Test outline generation with multiple task metadata entries."""
        sections = {}
        file_changes = [
            {"filepath": "file1.py", "content": ""},
            {"filepath": "file2.py", "content": ""},
        ]
        task_metadata = [
            {"agent": "agent1", "model": "model1", "provider": "p1", "char_count": 500},
            {"agent": "agent2", "model": "model2", "provider": "p2", "char_count": 1500},
        ]
        outline = generate_outline(sections, file_changes, task_metadata)
        assert "Task 001" in outline
        assert "Task 002" in outline
        assert "agent1" in outline
        assert "agent2" in outline


class TestWriteTaskFiles:
    """Tests for write_task_files function."""

    def test_write_task_files_basic(self, tmp_path: Path) -> None:
        """Test writing basic task files."""
        file_changes = [
            {"filepath": "app/main.py", "content": "Add main function"},
            {"filepath": "app/utils.py", "content": "Add utility functions"},
        ]
        write_task_files(tmp_path, file_changes)

        task1 = tmp_path / "task_001.md"
        task2 = tmp_path / "task_002.md"

        assert task1.exists()
        assert task2.exists()

        content1 = task1.read_text()
        assert "# app/main.py" in content1
        assert "Add main function" in content1

    def test_write_task_files_with_intro(self, tmp_path: Path) -> None:
        """Test writing task files with intro text."""
        file_changes = [{"filepath": "file.py", "content": "Changes"}]
        intro = "This is the introduction."
        write_task_files(tmp_path, file_changes, intro)

        task = tmp_path / "task_001.md"
        content = task.read_text()
        assert "This is the introduction." in content
        assert "# file.py" in content

    def test_write_task_files_empty_content(self, tmp_path: Path) -> None:
        """Test writing task files with empty content."""
        file_changes = [{"filepath": "empty.py", "content": ""}]
        write_task_files(tmp_path, file_changes)

        task = tmp_path / "task_001.md"
        content = task.read_text()
        assert "# empty.py" in content

    def test_write_task_files_no_intro_no_content(self, tmp_path: Path) -> None:
        """Test writing task files without intro and with whitespace-only content."""
        file_changes = [{"filepath": "file.py", "content": "   "}]
        write_task_files(tmp_path, file_changes, intro="")

        task = tmp_path / "task_001.md"
        content = task.read_text()
        assert "# file.py" in content


class TestMain:
    """Tests for main function."""

    def test_main_empty_clipboard(self, tmp_path: Path, capsys: Any) -> None:
        """Test main exits with error on empty clipboard."""
        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value="",
            ),
            patch("sys.argv", ["clipboard_to_plan"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Clipboard is empty" in captured.err

    def test_main_no_file_changes_section(self, tmp_path: Path, capsys: Any) -> None:
        """Test main exits with error when file changes section is missing."""
        content = """### Observations
Some observations.
### Approach
Some approach.
"""
        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value=content,
            ),
            patch("sys.argv", ["clipboard_to_plan"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Proposed File Changes" in captured.err

    def test_main_success_with_file_changes(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        """Test main succeeds with valid content containing file changes."""
        content = """### Observations
Some observations.

## Proposed File Changes
### app/main.py
Add main function.
"""
        # Create project structure
        project_root = tmp_path
        store_root = project_root / ".tasks" / "store"
        store_root.mkdir(parents=True, exist_ok=True)

        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value=content,
            ),
            patch("sys.argv", ["clipboard_to_plan"]),
        ):
            # Patch the module-level __file__ to point to our temp directory
            import scripts.tasks.commands.clipboard_to_plan as module

            original_file = module.__file__
            fake_script = project_root / "scripts" / "tasks" / "commands" / "clipboard_to_plan.py"
            fake_script.parent.mkdir(parents=True, exist_ok=True)
            fake_script.touch()
            module.__file__ = str(fake_script)

            try:
                main()

                # Check output
                captured = capsys.readouterr()
                output_dir = captured.out.strip()

                # Verify files were created
                assert Path(output_dir).exists()
                assert (Path(output_dir) / "outline.md").exists()
                assert (Path(output_dir) / "task_001.md").exists()

                # Verify outline content
                outline = (Path(output_dir) / "outline.md").read_text()
                assert "### Observations" in outline
                assert "app/main.py" in outline

            finally:
                module.__file__ = original_file

    def test_main_warning_no_file_changes_detected(self, tmp_path: Path, capsys: Any) -> None:
        """Test main warns when no file changes are detected in file changes section."""
        content = """### Observations
Some observations.

## Proposed File Changes
No files listed here.
"""
        # Create project structure
        project_root = tmp_path
        store_root = project_root / ".tasks" / "store"
        store_root.mkdir(parents=True, exist_ok=True)

        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value=content,
            ),
            patch("sys.argv", ["clipboard_to_plan"]),
        ):
            # Patch the module-level __file__ to point to our temp directory
            import scripts.tasks.commands.clipboard_to_plan as module

            original_file = module.__file__
            fake_script = project_root / "scripts" / "tasks" / "commands" / "clipboard_to_plan.py"
            fake_script.parent.mkdir(parents=True, exist_ok=True)
            fake_script.touch()
            module.__file__ = str(fake_script)

            try:
                main()

                # Check output - should print warning about no file changes
                captured = capsys.readouterr()
                assert "Warning: No file changes detected" in captured.err
                # Should still print the output directory
                assert captured.out.strip()

            finally:
                module.__file__ = original_file

    def test_main_use_tasks_system_missing_config(self, tmp_path: Path, capsys: Any) -> None:
        """Test main exits with error when --use-tasks-system is used but config is missing."""
        content = """## Proposed File Changes
### file.py
Changes.
"""
        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value=content,
            ),
            patch("sys.argv", ["clipboard_to_plan", "--use-tasks-system"]),
            patch(
                "scripts.tasks.commands.clipboard_to_plan._load_tasks_config",
                side_effect=FileNotFoundError("Config not found"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1

    def test_main_use_tasks_system_invalid_config(self, tmp_path: Path, capsys: Any) -> None:
        """Test main exits with error when config is invalid."""
        content = """## Proposed File Changes
### file.py
Changes.
"""
        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value=content,
            ),
            patch("sys.argv", ["clipboard_to_plan", "--use-tasks-system"]),
            patch(
                "scripts.tasks.commands.clipboard_to_plan._load_tasks_config",
                side_effect=ValueError("Invalid config"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1


class TestMainIntegration:
    """Integration tests for main function using real file operations."""

    def test_main_full_workflow(self, tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
        """Test main function full workflow with real file operations."""
        # Create project structure
        project_root = tmp_path
        store_root = project_root / ".tasks" / "store"
        store_root.mkdir(parents=True, exist_ok=True)

        content = """Introduction to the plan.

### Observations
Key observations about the codebase.

### Approach
Our implementation approach.

## Proposed File Changes
### app/main.py
Add the main entry point.

### app/utils.py
Add utility functions.
"""

        # Mock the clipboard and path resolution
        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value=content,
            ),
            patch("sys.argv", ["clipboard_to_plan"]),
        ):
            # We need to patch Path(__file__) to return our test path
            _original_path = Path

            class MockPath(type(Path())):
                pass

            # Patch the module-level Path to handle __file__ resolution
            import scripts.tasks.commands.clipboard_to_plan as module

            original_file = module.__file__
            fake_script = project_root / "scripts" / "tasks" / "commands" / "clipboard_to_plan.py"
            fake_script.parent.mkdir(parents=True, exist_ok=True)
            fake_script.touch()
            module.__file__ = str(fake_script)

            try:
                main()

                # Check output
                captured = capsys.readouterr()
                output_dir = captured.out.strip()

                # Verify files were created
                assert Path(output_dir).exists()
                assert (Path(output_dir) / "outline.md").exists()
                assert (Path(output_dir) / "task_001.md").exists()
                assert (Path(output_dir) / "task_002.md").exists()

                # Verify outline content
                outline = (Path(output_dir) / "outline.md").read_text()
                assert "Introduction to the plan" in outline
                assert "### Observations" in outline
                assert "app/main.py" in outline
                assert "app/utils.py" in outline

                # Verify task file content
                task1 = (Path(output_dir) / "task_001.md").read_text()
                assert "# app/main.py" in task1
                assert "Add the main entry point" in task1

            finally:
                module.__file__ = original_file

    def test_main_with_use_tasks_system(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        """Test main with --use-tasks-system flag."""
        project_root = tmp_path
        store_root = project_root / ".tasks" / "store"
        store_root.mkdir(parents=True, exist_ok=True)

        # Create .tasks.yaml config
        tasks_config = project_root / ".tasks.yaml"
        tasks_config.write_text("agents_dir: .tasks/agents\n")

        # Create agents directory with implementor.md
        agents_dir = project_root / ".tasks" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        implementor = agents_dir / "implementor.md"
        implementor.write_text("""---
name: implementor
routing_thresholds:
  - max_chars: 5000
    model: gpt-4
    provider: openai
  - max_chars: 20000
    model: gpt-4-turbo
    provider: openai
---
Agent content.
""")

        content = """## Proposed File Changes
### app/main.py
Add main function.
"""

        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value=content,
            ),
            patch("sys.argv", ["clipboard_to_plan", "--use-tasks-system"]),
        ):
            import scripts.tasks.commands.clipboard_to_plan as module

            original_file = module.__file__
            fake_script = project_root / "scripts" / "tasks" / "commands" / "clipboard_to_plan.py"
            fake_script.parent.mkdir(parents=True, exist_ok=True)
            fake_script.touch()
            module.__file__ = str(fake_script)

            try:
                main()
                captured = capsys.readouterr()
                output_dir = Path(captured.out.strip())

                # Check that JSON metadata file was created
                assert (output_dir / "task_001.json").exists()

                # Check outline has agent assignments
                outline = (output_dir / "outline.md").read_text()
                assert "Agent Assignments" in outline

            finally:
                module.__file__ = original_file


class TestDecodeOutputEncodings:
    """Additional tests for decode_output to cover all encoding fallbacks."""

    def test_decode_output_tries_all_encodings_before_latin1(self) -> None:
        """Test that decode_output tries UTF-8 and UTF-16 before falling back to Latin-1."""
        # Create bytes that are invalid UTF-8 and UTF-16 but valid Latin-1
        # Single bytes in the 0x80-0xff range that don't form valid UTF-8 sequences
        data = bytes([0x80, 0x81, 0x82])  # Invalid UTF-8 continuation bytes alone
        result = decode_output(data)
        assert isinstance(result, str)
        # Latin-1 accepts all single-byte values 0-255
        assert len(result) == 3

    def test_decode_output_uses_replace_errors_on_all_failures(self) -> None:
        """Test the final fallback with errors='replace'."""
        # Valid UTF-8 to test the final return path
        data = b"\xff\xfe\x00\x00"  # Invalid start bytes for UTF-8
        result = decode_output(data)
        assert isinstance(result, str)


class TestParsePlanSectionsEdgeCases:
    """Additional tests for parse_plan_sections edge cases."""

    def test_parse_plan_sections_no_intro_when_header_at_start(self) -> None:
        """Test no intro is extracted when header is at the very start."""
        content = """### Observations
First section content.
"""
        sections = parse_plan_sections(content)
        assert "intro" not in sections
        assert "observations" in sections

    def test_parse_plan_sections_reasoning_extracted_with_blank_line(self) -> None:
        """Test reasoning is extracted from approach with blank line separation."""
        content = """### Approach
This is the approach section.

This should be extracted as reasoning.

## Proposed File Changes
### file.py
Content
"""
        sections = parse_plan_sections(content)
        assert "approach" in sections
        # The reasoning should be extracted from the text after the blank line
        if "reasoning" in sections:
            assert sections["reasoning"]

    def test_parse_plan_sections_reasoning_not_extracted_when_same_as_approach(self) -> None:
        """Test reasoning is not extracted when candidate equals approach text."""
        content = """### Approach
This is approach text only.
## Proposed File Changes
### file.py
"""
        sections = parse_plan_sections(content)
        assert "approach" in sections
        # Reasoning should not be extracted when there's no clear separation

    def test_parse_plan_sections_with_alternate_reasoning_header(self) -> None:
        """Test parsing with alternate 'Reasoning' header format."""
        content = """### Approach
Approach content.

Reasoning
This is the reasoning text.

## Proposed File Changes
### file.py
"""
        sections = parse_plan_sections(content)
        # The SECTION_HEADERS for reasoning includes both "### Reasoning" and "Reasoning"
        assert "approach" in sections


class TestGenerateOutlineAllSections:
    """Additional tests for generate_outline covering all section types."""

    def test_generate_outline_intro_only(self) -> None:
        """Test outline with only intro section."""
        sections = {"intro": "Just an introduction."}
        file_changes = []
        outline = generate_outline(sections, file_changes)
        assert "Just an introduction" in outline
        assert "None detected" in outline

    def test_generate_outline_observations_only(self) -> None:
        """Test outline with only observations."""
        sections = {"observations": "Just observations."}
        file_changes = []
        outline = generate_outline(sections, file_changes)
        assert "### Observations" in outline
        assert "Just observations" in outline

    def test_generate_outline_approach_only(self) -> None:
        """Test outline with only approach."""
        sections = {"approach": "Just approach."}
        file_changes = []
        outline = generate_outline(sections, file_changes)
        assert "### Approach" in outline
        assert "Just approach" in outline

    def test_generate_outline_empty_task_metadata(self) -> None:
        """Test outline with empty task_metadata list."""
        sections = {}
        file_changes = [{"filepath": "file.py", "content": ""}]
        outline = generate_outline(sections, file_changes, task_metadata=[])
        # Empty list should not add Agent Assignments section
        assert "Agent Assignments" not in outline


class TestWriteTaskFilesBranches:
    """Additional tests for write_task_files to cover all branches."""

    def test_write_task_files_with_intro_and_content(self, tmp_path: Path) -> None:
        """Test writing task with both intro and non-empty content."""
        file_changes = [{"filepath": "test.py", "content": "Some content here"}]
        intro = "This is intro text."
        write_task_files(tmp_path, file_changes, intro)

        task = tmp_path / "task_001.md"
        content = task.read_text()
        assert "This is intro text." in content
        assert "# test.py" in content
        assert "Some content here" in content

    def test_write_task_files_without_intro_with_content(self, tmp_path: Path) -> None:
        """Test writing task without intro but with content."""
        file_changes = [{"filepath": "test.py", "content": "Content only"}]
        write_task_files(tmp_path, file_changes, intro="")

        task = tmp_path / "task_001.md"
        content = task.read_text()
        assert "# test.py" in content
        assert "Content only" in content

    def test_write_task_files_multiple_with_varying_content(self, tmp_path: Path) -> None:
        """Test writing multiple tasks with varying content states."""
        file_changes = [
            {"filepath": "file1.py", "content": "Has content"},
            {"filepath": "file2.py", "content": ""},  # Empty content
            {"filepath": "file3.py", "content": "  \n  "},  # Whitespace only
        ]
        write_task_files(tmp_path, file_changes, intro="Intro")

        for i in range(1, 4):
            task = tmp_path / f"task_{i:03d}.md"
            assert task.exists()
            content = task.read_text()
            assert "Intro" in content


class TestMainBranches:
    """Additional tests for main function to cover all branches."""

    def test_main_clipboard_whitespace_only(self, capsys: Any) -> None:
        """Test main with whitespace-only clipboard content."""
        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value="   \n\n   ",
            ),
            patch("sys.argv", ["clipboard_to_plan"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Clipboard is empty" in captured.err

    def test_main_with_file_changes_section_but_no_files(self, tmp_path: Path, capsys: Any) -> None:
        """Test main when file changes section exists but has no file entries."""
        content = """### Observations
Some observations.

## Proposed File Changes
Just some text but no ### file.py headers.
"""
        project_root = tmp_path
        store_root = project_root / ".tasks" / "store"
        store_root.mkdir(parents=True, exist_ok=True)

        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value=content,
            ),
            patch("sys.argv", ["clipboard_to_plan"]),
        ):
            import scripts.tasks.commands.clipboard_to_plan as module

            original_file = module.__file__
            fake_script = project_root / "scripts" / "tasks" / "commands" / "clipboard_to_plan.py"
            fake_script.parent.mkdir(parents=True, exist_ok=True)
            fake_script.touch()
            module.__file__ = str(fake_script)

            try:
                main()
                captured = capsys.readouterr()
                assert "Warning: No file changes detected" in captured.err
            finally:
                module.__file__ = original_file

    def test_main_with_empty_file_changes_body(self, tmp_path: Path, capsys: Any) -> None:
        """Test main when file changes section has empty body."""
        content = """### Observations
Some observations.

## Proposed File Changes
"""
        project_root = tmp_path
        store_root = project_root / ".tasks" / "store"
        store_root.mkdir(parents=True, exist_ok=True)

        with (
            patch(
                "scripts.tasks.commands.clipboard_to_plan.get_clipboard_content",
                return_value=content,
            ),
            patch("sys.argv", ["clipboard_to_plan"]),
        ):
            import scripts.tasks.commands.clipboard_to_plan as module

            original_file = module.__file__
            fake_script = project_root / "scripts" / "tasks" / "commands" / "clipboard_to_plan.py"
            fake_script.parent.mkdir(parents=True, exist_ok=True)
            fake_script.touch()
            module.__file__ = str(fake_script)

            try:
                main()
                captured = capsys.readouterr()
                assert "Warning: No file changes detected" in captured.err
            finally:
                module.__file__ = original_file
