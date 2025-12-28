from pathlib import Path

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


class TestFindProjectRoot:
    def test_caches_results_for_same_resolved_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that repeated calls with the same resolved path return cached results."""
        # Create project structure
        marker = tmp_path / "pyproject.toml"
        marker.write_text("[project]\n")
        subdir = tmp_path / "src" / "nested"
        subdir.mkdir(parents=True)

        # Track how many times Path.exists is called for marker files
        marker_files = {".git", "pyproject.toml", "setup.cfg", "package.json"}
        exists_call_count = 0
        original_exists = Path.exists

        def counting_exists(self: Path) -> bool:
            nonlocal exists_call_count
            if self.name in marker_files:
                exists_call_count += 1
            return original_exists(self)

        monkeypatch.setattr(Path, "exists", counting_exists)

        # First call should walk the filesystem
        result1 = find_project_root(subdir)
        first_call_count = exists_call_count

        # Second call should return cached result without filesystem walks
        result2 = find_project_root(subdir)
        second_call_count = exists_call_count - first_call_count

        assert result1 == result2 == tmp_path
        assert first_call_count > 0, "First call should check marker files"
        assert second_call_count == 0, "Second call should use cache, not check files"
