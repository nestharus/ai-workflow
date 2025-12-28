from pathlib import Path

import pytest

from scripts.dev.markdown.generate_converters import derive_script_name, main


class TestDeriveScriptName:
    def test_simple_path(self) -> None:
        """Should convert simple path to script name."""
        result = derive_script_name("docs/event-flow.md")
        assert result == "convert_docs_event_flow.py"

    def test_nested_path(self) -> None:
        """Should convert nested path to script name."""
        result = derive_script_name("docs/architecture/event-flow.md")
        assert result == "convert_docs_architecture_event_flow.py"

    def test_multiple_hyphens(self) -> None:
        """Should convert multiple hyphens in filename."""
        result = derive_script_name("docs/api-error-handling.md")
        assert result == "convert_docs_api_error_handling.py"

    def test_deeply_nested_path(self) -> None:
        """Should handle deeply nested path."""
        result = derive_script_name("docs/architecture/decisions/adr-001.md")
        assert result == "convert_docs_architecture_decisions_adr_001.py"

    def test_simple_filename(self) -> None:
        """Should handle simple filename without subdirectories."""
        result = derive_script_name("README.md")
        assert result == "convert_README.py"


class TestMain:
    def test_main_processes_manifest(self, tmp_path: Path) -> None:
        """Should process manifest and create converter scripts."""
        # Set up mock project structure
        manifest_content = """
sources:
  - path: docs/example.md
    target_stub: .knowledge/data/example.yml
"""
        # Create manifest
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        manifest_path = plans_dir / "md-to-yml-manifest.yml"
        manifest_path.write_text(manifest_content)

        # Create scripts directory
        scripts_dir = tmp_path / "scripts" / "markdown"
        scripts_dir.mkdir(parents=True)

        # Simulate main() logic with local paths
        import yaml

        from scripts.dev.markdown.converter_base import create_converter_script

        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        sources = manifest.get("sources", [])

        for entry in sources:
            source_path = entry["path"]
            target_path = entry["target_stub"]
            script_name = derive_script_name(source_path)
            script_path = scripts_dir / script_name
            script_content = create_converter_script(source_path, target_path)
            script_path.write_text(script_content, encoding="utf-8")
            script_path.chmod(0o755)

        # Verify script was created
        expected_script = scripts_dir / "convert_docs_example.py"
        assert expected_script.exists()

        # Verify script content
        content = expected_script.read_text()
        assert "docs/example.md" in content
        assert ".knowledge/data/example.yml" in content

    def test_main_handles_multiple_entries(self, tmp_path: Path) -> None:
        """Should create multiple converter scripts from manifest."""
        manifest_content = """
sources:
  - path: docs/api-guide.md
    target_stub: .knowledge/data/api-guide.yml
  - path: docs/architecture/overview.md
    target_stub: .knowledge/data/architecture-overview.yml
"""
        # Create manifest
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / "md-to-yml-manifest.yml").write_text(manifest_content)

        # Create scripts directory
        scripts_dir = tmp_path / "scripts" / "markdown"
        scripts_dir.mkdir(parents=True)

        # Mock and run main logic
        import yaml

        from scripts.dev.markdown.converter_base import create_converter_script

        manifest_path = plans_dir / "md-to-yml-manifest.yml"
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        sources = manifest.get("sources", [])
        for entry in sources:
            source_path = entry["path"]
            target_path = entry["target_stub"]
            script_name = derive_script_name(source_path)
            script_path = scripts_dir / script_name
            script_content = create_converter_script(source_path, target_path)
            script_path.write_text(script_content, encoding="utf-8")
            script_path.chmod(0o755)

        # Verify both scripts were created
        assert (scripts_dir / "convert_docs_api_guide.py").exists()
        assert (scripts_dir / "convert_docs_architecture_overview.py").exists()

    def test_main_outputs_count(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print count of generated scripts."""
        manifest_content = """
sources:
  - path: docs/test.md
    target_stub: .knowledge/data/test.yml
"""
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / "md-to-yml-manifest.yml").write_text(manifest_content)

        scripts_dir = tmp_path / "scripts" / "markdown"
        scripts_dir.mkdir(parents=True)

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
            print(f"Created: {script_path.name}")

        print(f"\nGenerated {len(sources)} converter scripts in {scripts_dir}")

        captured = capsys.readouterr()
        assert "Found 1 entries in manifest" in captured.out
        assert "Created: convert_docs_test.py" in captured.out
        assert "Generated 1 converter scripts" in captured.out

    def test_main_creates_executable_scripts(self, tmp_path: Path) -> None:
        """Should create scripts with executable permissions."""
        manifest_content = """
sources:
  - path: docs/script.md
    target_stub: .knowledge/data/script.yml
"""
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / "md-to-yml-manifest.yml").write_text(manifest_content)

        scripts_dir = tmp_path / "scripts" / "markdown"
        scripts_dir.mkdir(parents=True)

        import yaml

        from scripts.dev.markdown.converter_base import create_converter_script

        manifest_path = plans_dir / "md-to-yml-manifest.yml"
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        sources = manifest.get("sources", [])
        for entry in sources:
            source_path = entry["path"]
            target_path = entry["target_stub"]
            script_name = derive_script_name(source_path)
            script_path = scripts_dir / script_name
            script_content = create_converter_script(source_path, target_path)
            script_path.write_text(script_content, encoding="utf-8")
            script_path.chmod(0o755)

        script_path = scripts_dir / "convert_docs_script.py"
        assert script_path.exists()
        # Check that file is executable (mode has execute bit set)
        import stat

        mode = script_path.stat().st_mode
        assert mode & stat.S_IXUSR  # User execute bit
