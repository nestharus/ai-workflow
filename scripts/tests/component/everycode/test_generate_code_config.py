import os
from pathlib import Path
from typing import Any

import pytest

from scripts.everycode.generate_code_config import (
    _resolve_and_merge_instructions,
    clear_project_root_cache,
    find_project_root,
    generate_config,
    load_toml,
    process_command,
    resolve_instruction_file,
)


class TestLoadToml:
    def test_loads_valid_toml_file(self, tmp_path: Path) -> None:
        """Test loading a valid TOML file."""
        toml_file = tmp_path / "valid.toml"
        toml_file.write_text('key = "value"\nnumber = 42\n')

        result = load_toml(toml_file)

        assert result == {"key": "value", "number": 42}

    def test_raises_value_error_for_missing_file(self, tmp_path: Path) -> None:
        """Test that ValueError is raised for a missing file."""
        missing_file = tmp_path / "nonexistent.toml"

        with pytest.raises(ValueError, match="Failed to read TOML file"):
            load_toml(missing_file)

    def test_raises_value_error_for_invalid_toml(self, tmp_path: Path) -> None:
        """Test that ValueError is raised for invalid TOML syntax."""
        invalid_file = tmp_path / "invalid.toml"
        invalid_file.write_text('key = "unclosed string\n')

        with pytest.raises(ValueError, match="Invalid TOML syntax in file"):
            load_toml(invalid_file)

    def test_error_includes_file_path(self, tmp_path: Path) -> None:
        """Test that error messages include the file path."""
        missing_file = tmp_path / "specific_name.toml"

        with pytest.raises(ValueError) as exc_info:
            load_toml(missing_file)

        assert "specific_name.toml" in str(exc_info.value)

    def test_error_chains_original_exception(self, tmp_path: Path) -> None:
        """Test that original exception is chained via 'from'."""
        missing_file = tmp_path / "missing.toml"

        with pytest.raises(ValueError) as exc_info:
            load_toml(missing_file)

        # Check that the original OSError is chained
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, OSError)


class TestResolveInstructionFile:
    def test_resolves_valid_file(self, tmp_path: Path) -> None:
        """Test resolving a valid instruction file."""
        instruction_file = tmp_path / "instructions.md"
        instruction_file.write_text("  Test content  \n")

        result = resolve_instruction_file(tmp_path, "instructions.md")

        assert result == "Test content"

    def test_resolves_nested_file(self, tmp_path: Path) -> None:
        """Test resolving a file in a subdirectory."""
        subdir = tmp_path / "agents"
        subdir.mkdir()
        instruction_file = subdir / "agent.md"
        instruction_file.write_text("Nested content")

        result = resolve_instruction_file(tmp_path, "agents/agent.md")

        assert result == "Nested content"

    def test_raises_file_not_found_for_missing_file(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing files."""
        with pytest.raises(FileNotFoundError, match="Instruction file not found"):
            resolve_instruction_file(tmp_path, "nonexistent.md")

    def test_prevents_path_traversal_with_double_dots(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Test that path traversal with .. is prevented.

        Security contract: ANY path containing '..' segments MUST raise ValueError,
        even if path normalization would resolve to a location inside root_dir.
        This strict check prevents directory traversal attacks and should not be
        relaxed without thorough security review.
        """
        # Create a file in a separate temp directory (pytest cleans up automatically)
        outside_dir = tmp_path_factory.mktemp("outside")
        outside_file = outside_dir / "secret.txt"
        outside_file.write_text("Secret content")

        # Compute relative path from tmp_path to outside_file
        relative_path = os.path.relpath(outside_file, tmp_path)

        # Security: Must reject any '..' regardless of final resolved location
        with pytest.raises(ValueError, match="Path traversal detected"):
            resolve_instruction_file(tmp_path, relative_path)

    def test_prevents_path_traversal_with_nested_double_dots(self, tmp_path: Path) -> None:
        """Test that nested path traversal with .. is prevented.

        Security contract: Even paths like 'subdir/../../file' that might normalize
        to a valid location inside root_dir MUST be rejected. The presence of '..'
        anywhere in the path is sufficient grounds for rejection. This is a
        defense-in-depth measure - do not relax this check without security review.
        """
        # Create a secret file inside tmp_path for automatic cleanup
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("Secret content")

        # Security: 'subdir/../../secret.txt' normalizes to '../secret.txt' which
        # could potentially resolve inside root_dir, but we reject ALL '..' usage
        with pytest.raises(ValueError, match="Path traversal detected"):
            resolve_instruction_file(tmp_path, "subdir/../../secret.txt")


class TestProcessCommand:
    def test_preserves_command_without_instruction_files(self, tmp_path: Path) -> None:
        """Test that commands without instruction file refs are unchanged."""
        command_file = tmp_path / "command.toml"
        command_file.write_text('name = "test"\nother_key = "value"\n')

        result = process_command(command_file, tmp_path)

        assert result == {"name": "test", "other_key": "value"}

    def test_resolves_orchestrator_instructions_file(self, tmp_path: Path) -> None:
        """Test resolving orchestrator_instructions_file and setting content."""
        instruction_file = tmp_path / "orchestrator.md"
        instruction_file.write_text("File content")
        command_file = tmp_path / "command.toml"
        command_file.write_text('orchestrator_instructions_file = "orchestrator.md"\n')

        result = process_command(command_file, tmp_path)

        assert "orchestrator_instructions_file" not in result
        assert result["orchestrator_instructions"] == "File content"

    def test_resolves_agent_instructions_file(self, tmp_path: Path) -> None:
        """Test resolving agent_instructions_file and setting content."""
        instruction_file = tmp_path / "agent.md"
        instruction_file.write_text("Agent instructions here")
        command_file = tmp_path / "command.toml"
        command_file.write_text('agent_instructions_file = "agent.md"\n')

        result = process_command(command_file, tmp_path)

        assert "agent_instructions_file" not in result
        assert result["agent_instructions"] == "Agent instructions here"

    def test_merges_file_content_with_existing_instructions(self, tmp_path: Path) -> None:
        """Test that file content is prepended to existing inline instructions."""
        instruction_file = tmp_path / "orchestrator.md"
        instruction_file.write_text("File content")
        command_file = tmp_path / "command.toml"
        command_file.write_text(
            'orchestrator_instructions_file = "orchestrator.md"\n'
            'orchestrator_instructions = "Existing content"\n'
        )

        result = process_command(command_file, tmp_path)

        assert "orchestrator_instructions_file" not in result
        assert result["orchestrator_instructions"] == "File content\n\nExisting content"

    def test_removes_file_keys_after_resolution(self, tmp_path: Path) -> None:
        """Test that instruction file keys are removed from result after resolution."""
        orchestrator_file = tmp_path / "orchestrator.md"
        orchestrator_file.write_text("Orchestrator content")
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("Agent content")
        command_file = tmp_path / "command.toml"
        command_file.write_text(
            'name = "test"\n'
            'orchestrator_instructions_file = "orchestrator.md"\n'
            'agent_instructions_file = "agent.md"\n'
        )

        result = process_command(command_file, tmp_path)

        assert "orchestrator_instructions_file" not in result
        assert "agent_instructions_file" not in result
        assert result["name"] == "test"
        assert result["orchestrator_instructions"] == "Orchestrator content"
        assert result["agent_instructions"] == "Agent content"

    def test_raises_error_when_existing_content_is_not_string(self, tmp_path: Path) -> None:
        """Test that ValueError is raised when existing content key is not a string."""
        instruction_file = tmp_path / "orchestrator.md"
        instruction_file.write_text("File content")

        # Create a command dict with a non-string value for orchestrator_instructions
        command: dict[str, Any] = {
            "orchestrator_instructions_file": "orchestrator.md",
            "orchestrator_instructions": ["list", "instead", "of", "string"],
        }

        with pytest.raises(
            ValueError, match="Config key 'orchestrator_instructions' must be a string"
        ):
            _resolve_and_merge_instructions(
                command, tmp_path, "orchestrator_instructions_file", "orchestrator_instructions"
            )


class TestGenerateConfig:
    def test_overwrites_non_dict_subagents_from_settings(self, tmp_path: Path) -> None:
        """Test that subagents is reset to dict if settings.toml has non-dict value."""
        # Set up directory structure
        code_dir = tmp_path / ".code"
        src_dir = code_dir / "src"
        commands_dir = src_dir / "commands"
        commands_dir.mkdir(parents=True)

        # Create settings.toml with subagents as a non-dict value (e.g., string)
        settings_path = src_dir / "settings.toml"
        settings_path.write_text('subagents = "invalid_string_value"\n')

        # Create a command file
        command_path = commands_dir / "test_command.toml"
        command_path.write_text('name = "test"\n')

        # This should not raise an error - subagents should be reset to a dict
        result = generate_config(tmp_path)

        # The output format uses inline table arrays
        assert "[subagents]" in result
        assert "commands = [" in result
        assert 'name = "test"' in result

    def test_preserves_dict_subagents_from_settings(self, tmp_path: Path) -> None:
        """Test that existing dict subagents are preserved when adding commands."""
        # Set up directory structure
        code_dir = tmp_path / ".code"
        src_dir = code_dir / "src"
        commands_dir = src_dir / "commands"
        commands_dir.mkdir(parents=True)

        # Create settings.toml with subagents as a dict with existing values
        settings_path = src_dir / "settings.toml"
        settings_path.write_text('[subagents]\nexisting_key = "existing_value"\n')

        # Create a command file
        command_path = commands_dir / "test_command.toml"
        command_path.write_text('name = "test"\n')

        result = generate_config(tmp_path)

        # Commands should be added
        assert "[subagents]" in result
        assert "commands = [" in result
        assert 'name = "test"' in result
        # Existing values should be preserved
        assert 'existing_key = "existing_value"' in result

    def test_creates_subagents_when_not_present(self, tmp_path: Path) -> None:
        """Test that subagents is created when not in settings."""
        # Set up directory structure
        code_dir = tmp_path / ".code"
        src_dir = code_dir / "src"
        commands_dir = src_dir / "commands"
        commands_dir.mkdir(parents=True)

        # Create empty settings.toml
        settings_path = src_dir / "settings.toml"
        settings_path.write_text("")

        # Create a command file
        command_path = commands_dir / "test_command.toml"
        command_path.write_text('name = "test"\n')

        result = generate_config(tmp_path)

        assert "[subagents]" in result
        assert "commands = [" in result
        assert 'name = "test"' in result

    def test_loads_agents_toml_into_config(self, tmp_path: Path) -> None:
        """Test that agents.toml is correctly loaded and merged into the generated config."""
        # Set up directory structure
        code_dir = tmp_path / ".code"
        src_dir = code_dir / "src"
        commands_dir = src_dir / "commands"
        commands_dir.mkdir(parents=True)

        # Create settings.toml (required for basic structure)
        settings_path = src_dir / "settings.toml"
        settings_path.write_text('model = "claude-3"\n')

        # Create agents.toml with sample agent definitions
        agents_path = src_dir / "agents.toml"
        agents_path.write_text(
            "[[agents]]\n"
            'name = "test-agent"\n'
            'role = "assistant"\n'
            'description = "A test agent for unit testing"\n'
            "\n"
            "[[agents]]\n"
            'name = "another-agent"\n'
            'role = "reviewer"\n'
        )

        # Create a minimal command file
        command_path = commands_dir / "dummy_command.toml"
        command_path.write_text('name = "dummy"\n')

        result = generate_config(tmp_path)

        # Verify agents are present in output (tomli_w uses inline table format)
        assert "agents = [" in result
        assert 'name = "test-agent"' in result
        assert 'role = "assistant"' in result
        assert 'description = "A test agent for unit testing"' in result
        assert 'name = "another-agent"' in result
        assert 'role = "reviewer"' in result
        # Verify settings are also present
        assert 'model = "claude-3"' in result

    def test_resolves_instruction_files_in_commands(self, tmp_path: Path) -> None:
        """Test end-to-end that command TOML with instruction file refs resolves correctly."""
        # Set up directory structure
        code_dir = tmp_path / ".code"
        src_dir = code_dir / "src"
        commands_dir = src_dir / "commands"
        agents_dir = code_dir / "agents"
        commands_dir.mkdir(parents=True)
        agents_dir.mkdir(parents=True)

        # Create settings.toml
        settings_path = src_dir / "settings.toml"
        settings_path.write_text("")

        # Create instruction files in .code/agents/
        orchestrator_instructions = agents_dir / "orchestrator.md"
        orchestrator_instructions.write_text(
            "You are an orchestrator.\nCoordinate the agents effectively."
        )

        agent_instructions = agents_dir / "worker.md"
        agent_instructions.write_text("You are a worker agent.\nComplete tasks diligently.")

        # Create a command file that references instruction files
        command_path = commands_dir / "my_command.toml"
        command_path.write_text(
            'name = "my-command"\n'
            'orchestrator_instructions_file = "agents/orchestrator.md"\n'
            'agent_instructions_file = "agents/worker.md"\n'
        )

        result = generate_config(tmp_path)

        # Verify the instructions were resolved and embedded
        assert 'name = "my-command"' in result
        assert "You are an orchestrator." in result
        assert "Coordinate the agents effectively." in result
        assert "You are a worker agent." in result
        assert "Complete tasks diligently." in result
        # Verify the file keys are NOT in the output (they should be replaced)
        assert "orchestrator_instructions_file" not in result
        assert "agent_instructions_file" not in result

    def test_raises_error_when_src_directory_missing(self, tmp_path: Path) -> None:
        """Test that generate_config raises FileNotFoundError when .code/src is missing."""
        # Create .code directory but NOT src subdirectory
        code_dir = tmp_path / ".code"
        code_dir.mkdir(parents=True)
        # Intentionally do NOT create src_dir

        with pytest.raises(FileNotFoundError, match="Source directory not found"):
            generate_config(tmp_path)

    def test_raises_error_when_code_directory_missing(self, tmp_path: Path) -> None:
        """Test that generate_config raises FileNotFoundError when .code is missing entirely."""
        # tmp_path is empty, no .code directory exists

        with pytest.raises(FileNotFoundError, match="Source directory not found"):
            generate_config(tmp_path)


class TestFindProjectRoot:
    def test_finds_git_directory(self, tmp_path: Path) -> None:
        """Test that .git directory is recognized as a project root marker."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        subdir = tmp_path / "src" / "deep" / "nested"
        subdir.mkdir(parents=True)

        result = find_project_root(subdir)

        assert result == tmp_path

    def test_finds_pyproject_toml(self, tmp_path: Path) -> None:
        """Test that pyproject.toml is recognized as a project root marker."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'test'\n")
        subdir = tmp_path / "src"
        subdir.mkdir()

        result = find_project_root(subdir)

        assert result == tmp_path

    def test_finds_setup_cfg(self, tmp_path: Path) -> None:
        """Test that setup.cfg is recognized as a project root marker."""
        setup_cfg = tmp_path / "setup.cfg"
        setup_cfg.write_text("[metadata]\nname = test\n")
        subdir = tmp_path / "lib"
        subdir.mkdir()

        result = find_project_root(subdir)

        assert result == tmp_path

    def test_finds_package_json(self, tmp_path: Path) -> None:
        """Test that package.json is recognized as a project root marker."""
        package_json = tmp_path / "package.json"
        package_json.write_text('{"name": "test"}')
        subdir = tmp_path / "src"
        subdir.mkdir()

        result = find_project_root(subdir)

        assert result == tmp_path

    def test_prefers_closest_marker(self, tmp_path: Path) -> None:
        """Test that the closest marker is found when multiple exist in hierarchy."""
        # Create marker at parent level
        parent_marker = tmp_path / "pyproject.toml"
        parent_marker.write_text("[project]\n")

        # Create nested project with its own marker
        nested = tmp_path / "packages" / "subproject"
        nested.mkdir(parents=True)
        nested_marker = nested / "pyproject.toml"
        nested_marker.write_text("[project]\n")

        deep = nested / "src"
        deep.mkdir()

        result = find_project_root(deep)

        assert result == nested

    def test_raises_when_no_marker_found(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised when no marker is found.

        Uses a fresh isolated temp directory containing no marker files.
        The directory is deeply nested so find_project_root walks up
        multiple levels before reaching filesystem root.
        """
        # Create an isolated directory structure with no marker files
        isolated = tmp_path / "isolated"
        deep = isolated / "project" / "src" / "nested"
        deep.mkdir(parents=True)

        # Verify no marker files exist in the isolated hierarchy
        # (tmp_path itself may have markers from pytest, but isolated/ does not)
        assert not (isolated / ".git").exists()
        assert not (isolated / "pyproject.toml").exists()
        assert not (isolated / "setup.cfg").exists()
        assert not (isolated / "package.json").exists()

        with pytest.raises(FileNotFoundError, match="Could not auto-detect project root"):
            find_project_root(deep)

    def test_returns_start_path_when_marker_exists_there(self, tmp_path: Path) -> None:
        """Test that start_path itself is returned if it contains a marker."""
        marker = tmp_path / ".git"
        marker.mkdir()

        result = find_project_root(tmp_path)

        assert result == tmp_path

    def test_handles_symlinks_correctly(self, tmp_path: Path) -> None:
        """Test that symlinked directories are handled correctly."""
        # Create real project root
        real_root = tmp_path / "real_project"
        real_root.mkdir()
        (real_root / "pyproject.toml").write_text("[project]\n")
        src_dir = real_root / "src"
        src_dir.mkdir()

        # Create symlink to src
        symlink_parent = tmp_path / "links"
        symlink_parent.mkdir()
        symlink = symlink_parent / "linked_src"
        symlink.symlink_to(src_dir)

        result = find_project_root(symlink)

        # Should find the real project root, not the symlink parent
        assert result == real_root

    def test_clear_cache_allows_recomputation(self, tmp_path: Path) -> None:
        """Test that clearing the cache allows the result to be recomputed."""
        # Create initial project structure
        marker = tmp_path / "pyproject.toml"
        marker.write_text("[project]\n")
        subdir = tmp_path / "src"
        subdir.mkdir()

        # First call caches the result
        result1 = find_project_root(subdir)
        assert result1 == tmp_path

        # Clear cache
        clear_project_root_cache()

        # Create a closer marker after clearing cache
        inner_marker = subdir / "pyproject.toml"
        inner_marker.write_text("[project]\n")

        # Should find the new closer marker after cache clear
        result2 = find_project_root(subdir)
        assert result2 == subdir
