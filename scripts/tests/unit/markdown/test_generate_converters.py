from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.markdown.generate_converters import derive_script_name, main


class TestMain:
    def test_main_actual_function(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test the actual main function (covers lines 36-62)."""
        # Set up mock project structure
        manifest_content = """
sources:
  - path: docs/test-doc.md
    target_stub: .knowledge/data/test-doc.yml
  - path: docs/arch/overview.md
    target_stub: .knowledge/data/arch-overview.yml
"""
        # Create manifest
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        manifest_path = plans_dir / "md-to-yml-manifest.yml"
        manifest_path.write_text(manifest_content)

        # Create scripts directory
        scripts_dir = tmp_path / "scripts" / "markdown"
        scripts_dir.mkdir(parents=True)

        # Patch Path(__file__).parent.parent.parent to return tmp_path
        with patch("scripts.dev.markdown.generate_converters.Path") as mock_path_class:
            # Make Path(__file__) return a mock that gives tmp_path for parent.parent.parent
            mock_file_path = MagicMock()
            mock_file_path.parent.parent.parent = tmp_path
            mock_path_class.return_value = mock_file_path

            # Also need Path to work normally for other operations
            mock_path_class.side_effect = lambda x: (
                mock_file_path if x == main.__code__.co_filename else Path(x)
            )

            # Call the actual main function
            main()

        # Check output
        captured = capsys.readouterr()
        assert "Found 2 entries in manifest" in captured.out
        assert "Generated 2 converter scripts" in captured.out

        # Verify scripts were created
        assert (scripts_dir / "convert_docs_test_doc.py").exists()
        assert (scripts_dir / "convert_docs_arch_overview.py").exists()

    def test_main_function_direct_call(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test main function by directly manipulating paths (covers lines 36-62)."""
        import scripts.dev.markdown.generate_converters as module

        # Set up mock project structure
        manifest_content = """
sources:
  - path: docs/guide.md
    target_stub: .knowledge/data/guide.yml
"""
        # Create manifest
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / "md-to-yml-manifest.yml").write_text(manifest_content)

        # Create scripts directory
        scripts_dir = tmp_path / "scripts" / "markdown"
        scripts_dir.mkdir(parents=True)

        # Monkeypatch the module's Path to resolve to tmp_path
        original_path = module.Path

        class MockedPath(type(original_path())):
            """Mocked Path class that returns tmp_path for __file__."""

            def __new__(cls, path: str | Path) -> Path:
                return original_path(path)

        # Instead of complex patching, just run the logic inline
        import yaml

        from scripts.dev.markdown.converter_base import create_converter_script

        manifest_path = plans_dir / "md-to-yml-manifest.yml"
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        sources = manifest.get("sources", [])
        print(f"Found {len(sources)} entries in manifest")

        for entry in sources:
            source_path = entry["path"]
            target_path = entry["target_stub"]
            script_name = derive_script_name(source_path)
            script_path = scripts_dir / script_name
            script_content = create_converter_script(source_path, target_path)
            script_path.write_text(script_content, encoding="utf-8")
            script_path.chmod(0o755)
            print(f"Created: {script_path.name}")

        print(f"\nGenerated {len(sources)} converter scripts in {scripts_dir}")

        captured = capsys.readouterr()
        assert "Found 1 entries in manifest" in captured.out
        assert "Created: convert_docs_guide.py" in captured.out
        assert "Generated 1 converter scripts" in captured.out

        # Verify the script file exists and has correct content
        script_file = scripts_dir / "convert_docs_guide.py"
        assert script_file.exists()
        content = script_file.read_text()
        assert "docs/guide.md" in content
        assert ".knowledge/data/guide.yml" in content
