"""Tests for projection generator (ALG-PROJ-0001).

Tests:
- test_generate_plan_basic: Basic plan generation
- test_generate_plan_with_pins: Pin insertion
- test_pin_offsets_correct: Offset accuracy
- test_group_by_library: Library grouping
- test_projection_roundtrip: Save and load
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from spec_manager.projection.generator import (
    ProjectionGenerator,
    generate_plan_from_libraries,
    load_projection_pins,
    save_projection,
)
from spec_manager.schemas.derived_elements import DerivedElement
from spec_manager.schemas.projection import ProjectionPolicy
from spec_manager.schemas.spec_index_v2 import Library


class TestProjectionGenerator:
    """Test ProjectionGenerator class."""

    def test_generate_empty_plan(self) -> None:
        """Test generating plan with no libraries."""
        generator = ProjectionGenerator()
        artifact = generator.generate_plan([], [])

        assert artifact.kind == "PLAN_MD"
        assert artifact.generated_from == "LIBRARIES"
        assert "# Plan" in artifact.content
        assert artifact.pins == []

    def test_generate_plan_with_library(self) -> None:
        """Test generating plan with a single library."""
        generator = ProjectionGenerator()

        library = Library(
            lib_id="LIB-0001",
            name="Authentication",
            description="User authentication system",
        )
        element = DerivedElement(
            elem_id="REQ-LIB-0001-0001",
            kind="REQ",
            lib_id="LIB-0001",
            title="Login requirement",
            body="Users must be able to login.",
            evidence_atom_ids=["ATOM-1"],
        )

        artifact = generator.generate_plan([library], [element])

        assert "Authentication" in artifact.content
        assert "REQ-LIB-0001-0001" in artifact.content
        assert "Login requirement" in artifact.content
        assert len(artifact.pins) > 0

    def test_pin_insertion(self) -> None:
        """Test that pins are inserted with correct format."""
        policy = ProjectionPolicy(include_pins=True)
        generator = ProjectionGenerator(policy)

        library = Library(
            lib_id="LIB-0001",
            name="Test Library",
        )
        artifact = generator.generate_plan([library], [])

        # Check pin format in content
        assert "[@pin:PIN-" in artifact.content
        assert "target:LIBRARY:LIB-0001]" in artifact.content

    def test_no_pins_when_disabled(self) -> None:
        """Test pins not inserted when disabled."""
        policy = ProjectionPolicy(include_pins=False)
        generator = ProjectionGenerator(policy)

        library = Library(
            lib_id="LIB-0001",
            name="Test Library",
        )
        artifact = generator.generate_plan([library], [])

        assert "[@pin:" not in artifact.content
        assert artifact.pins == []

    def test_pin_counter_reset(self) -> None:
        """Test pin counter resets between generations."""
        generator = ProjectionGenerator()
        library = Library(lib_id="LIB-0001", name="Test")

        artifact1 = generator.generate_plan([library], [])
        artifact2 = generator.generate_plan([library], [])

        # Both should start with PIN-0001
        assert artifact1.pins[0].pin_id == "PIN-0001"
        assert artifact2.pins[0].pin_id == "PIN-0001"

    def test_multiple_libraries_grouped(self) -> None:
        """Test multiple libraries are grouped correctly."""
        generator = ProjectionGenerator()

        libraries = [
            Library(lib_id="LIB-0001", name="Auth"),
            Library(lib_id="LIB-0002", name="Data"),
        ]
        elements = [
            DerivedElement(
                elem_id="REQ-LIB-0001-0001",
                kind="REQ",
                lib_id="LIB-0001",
                title="Auth req",
                body="Auth body",
                evidence_atom_ids=["ATOM-1"],  # Required per CON-0005
            ),
            DerivedElement(
                elem_id="REQ-LIB-0002-0001",
                kind="REQ",
                lib_id="LIB-0002",
                title="Data req",
                body="Data body",
                evidence_atom_ids=["ATOM-2"],  # Required per CON-0005
            ),
        ]

        artifact = generator.generate_plan(libraries, elements)

        # Check both libraries appear
        assert "## Auth" in artifact.content
        assert "## Data" in artifact.content

        # Check elements are under correct libraries
        auth_pos = artifact.content.find("## Auth")
        data_pos = artifact.content.find("## Data")
        auth_req_pos = artifact.content.find("REQ-LIB-0001-0001")
        data_req_pos = artifact.content.find("REQ-LIB-0002-0001")

        assert auth_pos < auth_req_pos < data_pos
        assert data_pos < data_req_pos


class TestConvenienceFunction:
    """Test generate_plan_from_libraries convenience function."""

    def test_basic_usage(self) -> None:
        """Test basic usage of convenience function."""
        library = Library(lib_id="LIB-0001", name="Test")
        artifact = generate_plan_from_libraries([library], [])

        assert artifact.kind == "PLAN_MD"
        assert artifact.generated_from == "LIBRARIES"

    def test_custom_policy(self) -> None:
        """Test custom policy is applied."""
        library = Library(lib_id="LIB-0001", name="Test")
        policy = ProjectionPolicy(include_pins=False, include_metadata=False)

        artifact = generate_plan_from_libraries([library], [], policy)

        assert "[@pin:" not in artifact.content
        assert "<!-- projection_id:" not in artifact.content


class TestSaveAndLoad:
    """Test save and load functions."""

    def test_save_projection(self) -> None:
        """Test saving projection to disk."""
        library = Library(lib_id="LIB-0001", name="Test")
        artifact = generate_plan_from_libraries([library], [])

        with tempfile.TemporaryDirectory() as tmpdir:
            content_path = Path(tmpdir) / "plan.md"
            pins_path = Path(tmpdir) / "plan_pins.json"

            save_projection(artifact, content_path, pins_path)

            assert content_path.exists()
            assert pins_path.exists()

            # Verify content
            content = content_path.read_text(encoding="utf-8")
            assert "# Plan" in content

            # Verify pins JSON
            pins_data = json.loads(pins_path.read_text(encoding="utf-8"))
            assert pins_data["projection_id"] == artifact.projection_id
            assert "pins" in pins_data

    def test_load_projection_pins(self) -> None:
        """Test loading pins from JSON file."""
        library = Library(lib_id="LIB-0001", name="Test")
        artifact = generate_plan_from_libraries([library], [])

        with tempfile.TemporaryDirectory() as tmpdir:
            pins_path = Path(tmpdir) / "pins.json"
            save_projection(artifact, Path(tmpdir) / "plan.md", pins_path)

            loaded_pins = load_projection_pins(pins_path)

            assert len(loaded_pins) == len(artifact.pins)
            if loaded_pins:
                assert loaded_pins[0].pin_id == artifact.pins[0].pin_id

    def test_save_without_pins_file(self) -> None:
        """Test saving only content, no pins file."""
        library = Library(lib_id="LIB-0001", name="Test")
        artifact = generate_plan_from_libraries([library], [])

        with tempfile.TemporaryDirectory() as tmpdir:
            content_path = Path(tmpdir) / "plan.md"

            save_projection(artifact, content_path, pins_path=None)

            assert content_path.exists()
            assert not (Path(tmpdir) / "plan_pins.json").exists()
