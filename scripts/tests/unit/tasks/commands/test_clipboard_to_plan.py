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


class TestGetClipboardMacos:
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


class TestMain:
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


class TestMainBranches:
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
