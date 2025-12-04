"""Unit tests for render_plan_manager module."""

from pathlib import Path

import pytest
import yaml
from pyfakefs.fake_filesystem import FakeFilesystem

from scripts.knowledge.render_plan_manager import (
    get_render_plan_by_id,
    get_render_plan_for_artifact_kind,
    list_render_plans,
    load_render_plan,
    validate_render_plan_schema,
)


@pytest.fixture
def sample_render_plan_dict() -> dict:
    """Create a sample valid render plan dictionary."""
    return {
        "render_plan_id": "prose.paragraph.v1",
        "render_engine": "text_llm",
        "artifact_kind": "prose/paragraph",
        "inputs": {
            "use_structural_fieldfacts": True,
            "use_semantic_facts": True,
        },
        "determinism": {
            "ordering": ["role_priority", "group_id", "field_path"],
        },
        "steps": [
            {"id": "gather", "instruction": "Collect contributor facts."},
            {"id": "normalize", "instruction": "Normalize terminology."},
            {"id": "order", "instruction": "Order facts by determinism rules."},
            {"id": "render", "instruction": "Render paragraph from facts."},
            {"id": "self_check", "instruction": "Verify output maps to facts."},
        ],
        "notes": "Test render plan",
    }


@pytest.fixture
def render_plans_dir(fs: FakeFilesystem) -> Path:
    """Create a fake render plans directory."""
    plans_path = Path("/fake/.knowledge/artifacts/render_plans")
    fs.create_dir(plans_path)
    return plans_path


class TestValidateRenderPlanSchema:
    """Tests for validate_render_plan_schema function."""

    def test_valid_plan_returns_empty_list(self, sample_render_plan_dict: dict) -> None:
        """Verify valid plan passes validation."""
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert errors == []

    def test_missing_required_fields(self) -> None:
        """Verify missing required fields are reported."""
        errors = validate_render_plan_schema({})
        assert len(errors) == 1
        assert "Missing required fields" in errors[0]

    def test_invalid_render_engine(self, sample_render_plan_dict: dict) -> None:
        """Verify invalid render_engine is reported."""
        sample_render_plan_dict["render_engine"] = "invalid_engine"
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert len(errors) == 1
        assert "Invalid render_engine" in errors[0]

    def test_inputs_not_dict(self, sample_render_plan_dict: dict) -> None:
        """Verify non-dict inputs is reported."""
        sample_render_plan_dict["inputs"] = "not a dict"
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert any("'inputs' must be a dict" in e for e in errors)

    def test_inputs_missing_fields(self, sample_render_plan_dict: dict) -> None:
        """Verify missing input fields are reported."""
        sample_render_plan_dict["inputs"] = {}
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert any("use_structural_fieldfacts" in e for e in errors)
        assert any("use_semantic_facts" in e for e in errors)

    def test_inputs_wrong_type(self, sample_render_plan_dict: dict) -> None:
        """Verify non-boolean input fields are reported."""
        sample_render_plan_dict["inputs"]["use_structural_fieldfacts"] = "true"
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert any("must be a boolean" in e for e in errors)

    def test_determinism_not_dict(self, sample_render_plan_dict: dict) -> None:
        """Verify non-dict determinism is reported."""
        sample_render_plan_dict["determinism"] = "not a dict"
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert any("'determinism' must be a dict" in e for e in errors)

    def test_determinism_missing_ordering(self, sample_render_plan_dict: dict) -> None:
        """Verify missing ordering field is reported."""
        sample_render_plan_dict["determinism"] = {}
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert any("must contain 'ordering'" in e for e in errors)

    def test_steps_not_list(self, sample_render_plan_dict: dict) -> None:
        """Verify non-list steps is reported."""
        sample_render_plan_dict["steps"] = "not a list"
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert any("'steps' must be a list" in e for e in errors)

    def test_step_missing_id(self, sample_render_plan_dict: dict) -> None:
        """Verify step missing id is reported."""
        sample_render_plan_dict["steps"] = [{"instruction": "Do something"}]
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert any("missing required field 'id'" in e for e in errors)

    def test_step_missing_instruction(self, sample_render_plan_dict: dict) -> None:
        """Verify step missing instruction is reported."""
        sample_render_plan_dict["steps"] = [{"id": "gather"}]
        errors = validate_render_plan_schema(sample_render_plan_dict)
        assert any("missing required field 'instruction'" in e for e in errors)


class TestLoadRenderPlan:
    """Tests for load_render_plan function."""

    def test_loads_existing_plan(
        self,
        fs: FakeFilesystem,
        render_plans_dir: Path,
        sample_render_plan_dict: dict,
    ) -> None:
        """Verify render plan is correctly loaded from file."""
        plan_path = render_plans_dir / "prose.paragraph.v1.yml"
        fs.create_file(
            plan_path,
            contents=yaml.safe_dump(sample_render_plan_dict),
        )

        plan = load_render_plan("prose.paragraph.v1", render_plans_dir)

        assert plan["render_plan_id"] == "prose.paragraph.v1"
        assert plan["render_engine"] == "text_llm"
        assert plan["artifact_kind"] == "prose/paragraph"

    def test_raises_for_missing_plan(self, fs: FakeFilesystem, render_plans_dir: Path) -> None:
        """Verify FileNotFoundError raised for missing plan."""
        with pytest.raises(FileNotFoundError, match="Render plan not found"):
            load_render_plan("nonexistent", render_plans_dir)

    def test_raises_for_invalid_yaml(self, fs: FakeFilesystem, render_plans_dir: Path) -> None:
        """Verify ValueError raised for invalid YAML."""
        plan_path = render_plans_dir / "bad-plan.yml"
        fs.create_file(plan_path, contents="invalid: yaml: syntax: {{")

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_render_plan("bad-plan", render_plans_dir)

    def test_raises_for_non_dict(self, fs: FakeFilesystem, render_plans_dir: Path) -> None:
        """Verify ValueError raised for non-dict content."""
        plan_path = render_plans_dir / "array-plan.yml"
        fs.create_file(plan_path, contents="- item1\n- item2")

        with pytest.raises(ValueError, match="must be a dict"):
            load_render_plan("array-plan", render_plans_dir)

    def test_raises_for_invalid_schema(self, fs: FakeFilesystem, render_plans_dir: Path) -> None:
        """Verify ValueError raised for invalid schema."""
        plan_path = render_plans_dir / "invalid-schema.yml"
        fs.create_file(plan_path, contents="render_plan_id: test")

        with pytest.raises(ValueError, match="Invalid render plan"):
            load_render_plan("invalid-schema", render_plans_dir)


class TestListRenderPlans:
    """Tests for list_render_plans function."""

    def test_lists_all_plans(
        self,
        fs: FakeFilesystem,
        render_plans_dir: Path,
        sample_render_plan_dict: dict,
    ) -> None:
        """Verify all render plans are listed."""
        # Create multiple plans
        for plan_id in ["prose.paragraph.v1", "table.discriminator-grouped.v1"]:
            sample_render_plan_dict["render_plan_id"] = plan_id
            sample_render_plan_dict["artifact_kind"] = f"test/{plan_id}"
            plan_path = render_plans_dir / f"{plan_id}.yml"
            fs.create_file(
                plan_path,
                contents=yaml.safe_dump(sample_render_plan_dict),
            )

        plans = list_render_plans(render_plans_dir)

        assert len(plans) == 2
        plan_ids = {p["render_plan_id"] for p in plans}
        assert "prose.paragraph.v1" in plan_ids
        assert "table.discriminator-grouped.v1" in plan_ids

    def test_returns_empty_for_missing_dir(self, fs: FakeFilesystem) -> None:
        """Verify empty list returned for non-existent directory."""
        plans = list_render_plans(Path("/nonexistent"))
        assert plans == []

    def test_skips_invalid_plans(
        self,
        fs: FakeFilesystem,
        render_plans_dir: Path,
        sample_render_plan_dict: dict,
    ) -> None:
        """Verify invalid plans are skipped."""
        # Create valid plan
        valid_path = render_plans_dir / "valid.yml"
        fs.create_file(
            valid_path,
            contents=yaml.safe_dump(sample_render_plan_dict),
        )

        # Create invalid plan
        invalid_path = render_plans_dir / "invalid.yml"
        fs.create_file(invalid_path, contents="render_plan_id: test")

        plans = list_render_plans(render_plans_dir)

        assert len(plans) == 1
        assert plans[0]["render_plan_id"] == "prose.paragraph.v1"


class TestGetRenderPlanForArtifactKind:
    """Tests for get_render_plan_for_artifact_kind function."""

    def test_finds_matching_plan(
        self,
        fs: FakeFilesystem,
        render_plans_dir: Path,
        sample_render_plan_dict: dict,
    ) -> None:
        """Verify matching plan is found."""
        plan_path = render_plans_dir / "prose.paragraph.v1.yml"
        fs.create_file(
            plan_path,
            contents=yaml.safe_dump(sample_render_plan_dict),
        )

        plan = get_render_plan_for_artifact_kind("prose/paragraph", render_plans_dir)

        assert plan is not None
        assert plan["render_plan_id"] == "prose.paragraph.v1"

    def test_returns_none_for_no_match(
        self,
        fs: FakeFilesystem,
        render_plans_dir: Path,
        sample_render_plan_dict: dict,
    ) -> None:
        """Verify None returned when no matching plan."""
        plan_path = render_plans_dir / "prose.paragraph.v1.yml"
        fs.create_file(
            plan_path,
            contents=yaml.safe_dump(sample_render_plan_dict),
        )

        plan = get_render_plan_for_artifact_kind("diagram/mermaid", render_plans_dir)

        assert plan is None


class TestGetRenderPlanById:
    """Tests for get_render_plan_by_id function."""

    def test_finds_existing_plan(
        self,
        fs: FakeFilesystem,
        render_plans_dir: Path,
        sample_render_plan_dict: dict,
    ) -> None:
        """Verify existing plan is found by ID."""
        plan_path = render_plans_dir / "prose.paragraph.v1.yml"
        fs.create_file(
            plan_path,
            contents=yaml.safe_dump(sample_render_plan_dict),
        )

        plan = get_render_plan_by_id("prose.paragraph.v1", render_plans_dir)

        assert plan is not None
        assert plan["render_plan_id"] == "prose.paragraph.v1"

    def test_returns_none_for_missing(self, fs: FakeFilesystem, render_plans_dir: Path) -> None:
        """Verify None returned for missing plan."""
        plan = get_render_plan_by_id("nonexistent", render_plans_dir)
        assert plan is None
