"""Tests for scripts/knowledge/render_plan_manager.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.knowledge.render_plan_manager import validate_render_plan_schema


class TestValidateRenderPlanSchema:
    """Tests for validate_render_plan_schema() function."""

    def test_valid_plan(self) -> None:
        """Test validation of a completely valid render plan."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": False,
            },
            "determinism": {
                "ordering": ["priority", "timestamp"],
            },
            "steps": [
                {"id": "step1", "instruction": "First step"},
                {"id": "step2", "instruction": "Second step"},
            ],
        }

        errors = validate_render_plan_schema(plan)
        assert errors == []

    def test_missing_required_fields(self) -> None:
        """Test validation with missing required fields."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
        }

        errors = validate_render_plan_schema(plan)
        assert len(errors) >= 1
        assert any("Missing required fields" in e for e in errors)

    def test_invalid_render_engine(self) -> None:
        """Test validation with invalid render_engine value."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "invalid_engine",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": False,
            },
            "determinism": {"ordering": []},
            "steps": [{"id": "s1", "instruction": "test"}],
        }

        errors = validate_render_plan_schema(plan)
        assert len(errors) == 1
        assert "Invalid render_engine" in errors[0]

    def test_inputs_not_dict(self) -> None:
        """Test validation when inputs is not a dict."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": "invalid",  # Should be dict
            "determinism": {"ordering": []},
            "steps": [{"id": "s1", "instruction": "test"}],
        }

        errors = validate_render_plan_schema(plan)
        assert any("'inputs' must be a dict" in e for e in errors)

    def test_inputs_missing_field(self) -> None:
        """Test validation when inputs is missing required fields."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                # Missing use_semantic_facts
            },
            "determinism": {"ordering": []},
            "steps": [{"id": "s1", "instruction": "test"}],
        }

        errors = validate_render_plan_schema(plan)
        assert any("use_semantic_facts" in e for e in errors)

    def test_inputs_field_not_bool(self) -> None:
        """Test validation when input field is not a boolean."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": "yes",  # Should be bool
                "use_semantic_facts": False,
            },
            "determinism": {"ordering": []},
            "steps": [{"id": "s1", "instruction": "test"}],
        }

        errors = validate_render_plan_schema(plan)
        assert any("must be a boolean" in e for e in errors)

    def test_determinism_not_dict(self) -> None:
        """Test validation when determinism is not a dict."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": False,
            },
            "determinism": "invalid",  # Should be dict
            "steps": [{"id": "s1", "instruction": "test"}],
        }

        errors = validate_render_plan_schema(plan)
        assert any("'determinism' must be a dict" in e for e in errors)

    def test_determinism_missing_ordering(self) -> None:
        """Test validation when determinism is missing ordering field."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": False,
            },
            "determinism": {},  # Missing 'ordering'
            "steps": [{"id": "s1", "instruction": "test"}],
        }

        errors = validate_render_plan_schema(plan)
        assert any("must contain 'ordering'" in e for e in errors)

    def test_determinism_ordering_not_list(self) -> None:
        """Test validation when determinism.ordering is not a list (line 146)."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": False,
            },
            "determinism": {
                "ordering": "not_a_list",  # Should be list
            },
            "steps": [{"id": "s1", "instruction": "test"}],
        }

        errors = validate_render_plan_schema(plan)
        assert any("'determinism.ordering' must be a list" in e for e in errors)

    def test_steps_not_list(self) -> None:
        """Test validation when steps is not a list."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": False,
            },
            "determinism": {"ordering": []},
            "steps": "not_a_list",  # Should be list
        }

        errors = validate_render_plan_schema(plan)
        assert any("'steps' must be a list" in e for e in errors)

    def test_step_not_dict(self) -> None:
        """Test validation when a step is not a dict (line 156)."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": False,
            },
            "determinism": {"ordering": []},
            "steps": [
                "not_a_dict",  # Should be dict
            ],
        }

        errors = validate_render_plan_schema(plan)
        assert any("Step 0 must be a dict" in e for e in errors)

    def test_step_missing_id(self) -> None:
        """Test validation when a step is missing 'id' field."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": False,
            },
            "determinism": {"ordering": []},
            "steps": [
                {"instruction": "test"},  # Missing 'id'
            ],
        }

        errors = validate_render_plan_schema(plan)
        assert any("missing required field 'id'" in e for e in errors)

    def test_step_missing_instruction(self) -> None:
        """Test validation when a step is missing 'instruction' field."""
        plan = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": False,
            },
            "determinism": {"ordering": []},
            "steps": [
                {"id": "step1"},  # Missing 'instruction'
            ],
        }

        errors = validate_render_plan_schema(plan)
        assert any("missing required field 'instruction'" in e for e in errors)


class TestLoadRenderPlan:
    """Tests for load_render_plan function."""

    def test_load_valid_plan(self, tmp_path: Path) -> None:
        """Test loading a valid render plan."""
        from scripts.knowledge.render_plan_manager import load_render_plan

        # Create a valid plan file
        plan_content = """
render_plan_id: prose.paragraph.v1
render_engine: text_llm
artifact_kind: prose/paragraph
inputs:
  use_structural_fieldfacts: true
  use_semantic_facts: false
determinism:
  ordering:
    - priority
steps:
  - id: step1
    instruction: First step
"""
        plan_path = tmp_path / "prose.paragraph.v1.yml"
        plan_path.write_text(plan_content)

        plan = load_render_plan("prose.paragraph.v1", tmp_path)

        assert plan["render_plan_id"] == "prose.paragraph.v1"
        assert plan["render_engine"] == "text_llm"

    def test_load_nonexistent_plan(self, tmp_path: Path) -> None:
        """Test loading a plan that doesn't exist (lines 183-185)."""
        from scripts.knowledge.render_plan_manager import load_render_plan

        with pytest.raises(FileNotFoundError) as exc_info:
            load_render_plan("nonexistent.plan", tmp_path)

        assert "Render plan not found" in str(exc_info.value)

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        """Test loading a plan with invalid YAML (lines 190-192)."""
        from scripts.knowledge.render_plan_manager import load_render_plan

        # Create a file with invalid YAML
        plan_path = tmp_path / "invalid.yml"
        plan_path.write_text("invalid: yaml: content: [")

        with pytest.raises(ValueError) as exc_info:
            load_render_plan("invalid", tmp_path)

        assert "Invalid YAML" in str(exc_info.value)

    def test_load_non_dict_content(self, tmp_path: Path) -> None:
        """Test loading a plan where content is not a dict (lines 194-196)."""
        from scripts.knowledge.render_plan_manager import load_render_plan

        # Create a file with non-dict content
        plan_path = tmp_path / "list_content.yml"
        plan_path.write_text("- item1\n- item2")

        with pytest.raises(TypeError) as exc_info:
            load_render_plan("list_content", tmp_path)

        assert "Render plan must be a dict" in str(exc_info.value)

    def test_load_invalid_schema(self, tmp_path: Path) -> None:
        """Test loading a plan with schema validation errors (lines 200-202)."""
        from scripts.knowledge.render_plan_manager import load_render_plan

        # Create a file with missing required fields
        plan_path = tmp_path / "missing_fields.yml"
        plan_path.write_text("render_plan_id: test\n")

        with pytest.raises(ValueError) as exc_info:
            load_render_plan("missing_fields", tmp_path)

        assert "Invalid render plan" in str(exc_info.value)


class TestListRenderPlans:
    """Tests for list_render_plans function."""

    def test_list_empty_when_directory_not_exists(self, tmp_path: Path) -> None:
        """Test listing plans when directory doesn't exist (line 217-218)."""
        from scripts.knowledge.render_plan_manager import list_render_plans

        nonexistent_dir = tmp_path / "nonexistent"
        result = list_render_plans(nonexistent_dir)

        assert result == []

    def test_list_render_plans_returns_valid_plans(self, tmp_path: Path) -> None:
        """Test listing valid render plans (lines 220-232)."""
        from scripts.knowledge.render_plan_manager import list_render_plans

        # Create valid plan files
        plan1_content = """
render_plan_id: plan1.v1
render_engine: text_llm
artifact_kind: type1
inputs:
  use_structural_fieldfacts: true
  use_semantic_facts: false
determinism:
  ordering: []
steps:
  - id: step1
    instruction: Do something
"""
        plan2_content = """
render_plan_id: plan2.v1
render_engine: none
artifact_kind: type2
inputs:
  use_structural_fieldfacts: false
  use_semantic_facts: true
determinism:
  ordering: []
steps:
  - id: step1
    instruction: Do something else
"""
        (tmp_path / "plan1.v1.yml").write_text(plan1_content)
        (tmp_path / "plan2.v1.yml").write_text(plan2_content)

        result = list_render_plans(tmp_path)

        assert len(result) == 2
        plan_ids = [p["render_plan_id"] for p in result]
        assert "plan1.v1" in plan_ids
        assert "plan2.v1" in plan_ids

    def test_list_render_plans_skips_invalid_files(self, tmp_path: Path) -> None:
        """Test that invalid plans are skipped with warning (lines 227-229)."""
        from scripts.knowledge.render_plan_manager import list_render_plans

        # Create one valid plan
        valid_plan_content = """
render_plan_id: valid.v1
render_engine: text_llm
artifact_kind: type1
inputs:
  use_structural_fieldfacts: true
  use_semantic_facts: false
determinism:
  ordering: []
steps:
  - id: step1
    instruction: Do something
"""
        (tmp_path / "valid.v1.yml").write_text(valid_plan_content)

        # Create one invalid plan (bad YAML)
        (tmp_path / "invalid.yml").write_text("invalid: yaml: [")

        result = list_render_plans(tmp_path)

        # Should only return the valid plan
        assert len(result) == 1
        assert result[0]["render_plan_id"] == "valid.v1"


class TestGetRenderPlanForArtifactKind:
    """Tests for get_render_plan_for_artifact_kind function."""

    def test_finds_matching_plan(self, tmp_path: Path) -> None:
        """Test finding a plan that matches artifact kind (lines 248-257)."""
        from scripts.knowledge.render_plan_manager import get_render_plan_for_artifact_kind

        # Create a plan with specific artifact_kind
        plan_content = """
render_plan_id: prose.paragraph.v1
render_engine: text_llm
artifact_kind: prose/paragraph
inputs:
  use_structural_fieldfacts: true
  use_semantic_facts: false
determinism:
  ordering: []
steps:
  - id: step1
    instruction: Render the prose
"""
        (tmp_path / "prose.paragraph.v1.yml").write_text(plan_content)

        result = get_render_plan_for_artifact_kind("prose/paragraph", tmp_path)

        assert result is not None
        assert result["artifact_kind"] == "prose/paragraph"
        assert result["render_plan_id"] == "prose.paragraph.v1"

    def test_returns_none_when_no_match(self, tmp_path: Path) -> None:
        """Test returning None when no matching plan (lines 259-260)."""
        from scripts.knowledge.render_plan_manager import get_render_plan_for_artifact_kind

        # Create a plan with different artifact_kind
        plan_content = """
render_plan_id: other.v1
render_engine: text_llm
artifact_kind: other/type
inputs:
  use_structural_fieldfacts: true
  use_semantic_facts: false
determinism:
  ordering: []
steps:
  - id: step1
    instruction: Something
"""
        (tmp_path / "other.v1.yml").write_text(plan_content)

        result = get_render_plan_for_artifact_kind("nonexistent/kind", tmp_path)

        assert result is None


class TestGetRenderPlanById:
    """Tests for get_render_plan_by_id function."""

    def test_returns_plan_when_found(self, tmp_path: Path) -> None:
        """Test returning plan when found (lines 279-280)."""
        from scripts.knowledge.render_plan_manager import get_render_plan_by_id

        # Create a valid plan
        plan_content = """
render_plan_id: test.plan.v1
render_engine: text_llm
artifact_kind: test/type
inputs:
  use_structural_fieldfacts: true
  use_semantic_facts: false
determinism:
  ordering: []
steps:
  - id: step1
    instruction: Test step
"""
        (tmp_path / "test.plan.v1.yml").write_text(plan_content)

        result = get_render_plan_by_id("test.plan.v1", tmp_path)

        assert result is not None
        assert result["render_plan_id"] == "test.plan.v1"

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """Test returning None when plan doesn't exist (lines 281-282)."""
        from scripts.knowledge.render_plan_manager import get_render_plan_by_id

        result = get_render_plan_by_id("nonexistent.plan", tmp_path)

        assert result is None

    def test_returns_none_for_invalid_plan(self, tmp_path: Path) -> None:
        """Test returning None for invalid plan (lines 283-285)."""
        from scripts.knowledge.render_plan_manager import get_render_plan_by_id

        # Create an invalid plan (missing required fields)
        plan_path = tmp_path / "invalid.yml"
        plan_path.write_text("render_plan_id: invalid\n")

        result = get_render_plan_by_id("invalid", tmp_path)

        assert result is None

    def test_returns_none_for_bad_yaml(self, tmp_path: Path) -> None:
        """Test returning None for bad YAML (lines 283-285)."""
        from scripts.knowledge.render_plan_manager import get_render_plan_by_id

        # Create a file with invalid YAML
        plan_path = tmp_path / "bad_yaml.yml"
        plan_path.write_text("invalid: yaml: [")

        result = get_render_plan_by_id("bad_yaml", tmp_path)

        assert result is None
