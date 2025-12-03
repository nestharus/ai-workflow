"""Unit tests for artifact_renderer module."""

from pathlib import Path

import pytest
import yaml
from pyfakefs.fake_filesystem import FakeFilesystem

from scripts.knowledge.artifact_renderer import (
    MIME_TO_EXTENSION,
    ROLE_PRIORITY_MAP,
    _derive_role_priority,
    _gather_contributor_facts,
    _get_output_extension,
    _get_step_handler,
    _normalize_terminology,
    _order_facts,
    _render_none,
    _render_with_llm,
    _self_check,
    _step_gather,
    _step_normalize,
    _step_order,
    _step_render,
    _step_self_check,
    get_output_extension,
    render_artifact,
)


@pytest.fixture
def sample_manifest() -> dict:
    """Create a sample artifact manifest for testing."""
    return {
        "artifact_id": "abc123def456789012345678901234567890123456789012345678901234",
        "artifact_kind": "prose/paragraph",
        "artifact_format": "text/markdown",
        "source": {
            "source_file": "docs/test.yml",
            "source_element_id": "test-element-1",
            "field_path": "description",
            "source_locator": "inline",
            "source_uri": None,
        },
        "render_plan_id": "prose.paragraph.v1",
        "projection_version": "fieldfacts.v2",
        "modality": "text",
        "extraction_mode": "full",
        "contributors": {
            "structural": [
                {
                    "element_id": "elem-1",
                    "field_path": "field.one",
                    "fact_id": "fact-1",
                    "role": "constraint",
                    "group_key": "grp-a",
                    "group_id": "g1",
                },
                {
                    "element_id": "elem-2",
                    "field_path": "field.two",
                    "fact_id": "fact-2",
                    "role": "metadata",
                    "role_priority": 2,
                },
            ],
            "semantic": [
                {
                    "element_id": "elem-3",
                    "field_path": "field.three",
                    "fact_id": "fact-3",
                    "role": "entity_ref",
                },
            ],
        },
        "entities": [],
        "rendered": {"path": "", "validation": {}},
    }


@pytest.fixture
def sample_render_plan() -> dict:
    """Create a sample render plan for testing."""
    return {
        "render_plan_id": "prose.paragraph.v1",
        "render_engine": "text_llm",
        "artifact_kind": "prose/paragraph",
        "inputs": {
            "use_structural_fieldfacts": True,
            "use_semantic_facts": True,
        },
        "determinism": {
            "ordering": ["field_path"],
        },
        "steps": [
            {"id": "gather", "instruction": "Collect contributor facts."},
            {"id": "render", "instruction": "Render paragraph."},
        ],
        "notes": "Test render plan",
    }


@pytest.fixture
def artifacts_dir(fs: FakeFilesystem) -> Path:
    """Create a fake artifacts directory."""
    artifacts_path = Path("/fake/.knowledge/artifacts")
    fs.create_dir(artifacts_path)
    return artifacts_path


@pytest.fixture
def rendered_dir(fs: FakeFilesystem) -> Path:
    """Create a fake rendered directory."""
    rendered_path = Path("/fake/.knowledge/artifacts/rendered")
    fs.create_dir(rendered_path)
    return rendered_path


class TestGetOutputExtension:
    """Tests for _get_output_extension function."""

    def test_markdown_extension(self) -> None:
        """Verify markdown MIME type maps to .md."""
        assert _get_output_extension("text/markdown") == ".md"

    def test_yaml_extension(self) -> None:
        """Verify YAML MIME types map to .yml."""
        assert _get_output_extension("text/yaml") == ".yml"
        assert _get_output_extension("text/x-yaml") == ".yml"
        assert _get_output_extension("application/x-yaml") == ".yml"

    def test_json_extension(self) -> None:
        """Verify JSON MIME type maps to .json."""
        assert _get_output_extension("application/json") == ".json"

    def test_mermaid_extension(self) -> None:
        """Verify Mermaid MIME type maps to .mmd."""
        assert _get_output_extension("text/x-mermaid") == ".mmd"

    def test_plain_extension(self) -> None:
        """Verify plain text MIME type maps to .txt."""
        assert _get_output_extension("text/plain") == ".txt"

    def test_unknown_extension(self) -> None:
        """Verify unknown MIME type defaults to .txt."""
        assert _get_output_extension("unknown/type") == ".txt"

    def test_public_wrapper(self) -> None:
        """Verify public get_output_extension function works."""
        assert get_output_extension("text/markdown") == ".md"


class TestGatherContributorFacts:
    """Tests for _gather_contributor_facts function."""

    def test_gathers_structural_facts(
        self, sample_manifest: dict, sample_render_plan: dict
    ) -> None:
        """Verify structural facts are gathered."""
        facts = _gather_contributor_facts(sample_manifest, sample_render_plan)

        structural_facts = [f for f in facts if f["type"] == "structural"]
        assert len(structural_facts) == 2

    def test_gathers_semantic_facts(
        self, sample_manifest: dict, sample_render_plan: dict
    ) -> None:
        """Verify semantic facts are gathered."""
        facts = _gather_contributor_facts(sample_manifest, sample_render_plan)

        semantic_facts = [f for f in facts if f["type"] == "semantic"]
        assert len(semantic_facts) == 1

    def test_respects_input_flags(
        self, sample_manifest: dict, sample_render_plan: dict
    ) -> None:
        """Verify input flags control which facts are gathered."""
        # Disable semantic facts
        sample_render_plan["inputs"]["use_semantic_facts"] = False

        facts = _gather_contributor_facts(sample_manifest, sample_render_plan)

        assert all(f["type"] == "structural" for f in facts)

    def test_handles_empty_contributors(self, sample_render_plan: dict) -> None:
        """Verify empty contributors is handled."""
        manifest = {
            "artifact_id": "test",
            "contributors": {"structural": [], "semantic": []},
        }

        facts = _gather_contributor_facts(manifest, sample_render_plan)

        assert facts == []

    def test_includes_ordering_fields(
        self, sample_manifest: dict, sample_render_plan: dict
    ) -> None:
        """Verify facts include role, role_priority, group_key, group_id fields."""
        facts = _gather_contributor_facts(sample_manifest, sample_render_plan)

        # Check structural fact with explicit fields
        structural_fact = next(f for f in facts if f["element_id"] == "elem-1")
        assert structural_fact["role"] == "constraint"
        assert structural_fact["role_priority"] == 1  # Derived from role
        assert structural_fact["group_key"] == "grp-a"
        assert structural_fact["group_id"] == "g1"

        # Check structural fact with explicit role_priority
        meta_fact = next(f for f in facts if f["element_id"] == "elem-2")
        assert meta_fact["role"] == "metadata"
        assert meta_fact["role_priority"] == 2  # Explicit from contributor

        # Check semantic fact derives role_priority
        semantic_fact = next(f for f in facts if f["element_id"] == "elem-3")
        assert semantic_fact["role"] == "entity_ref"
        assert semantic_fact["role_priority"] == 3  # Derived from entity_ref role

    def test_defaults_missing_ordering_fields(
        self, sample_render_plan: dict
    ) -> None:
        """Verify missing ordering fields get default values."""
        manifest = {
            "artifact_id": "test",
            "contributors": {
                "structural": [
                    {"element_id": "elem-1", "field_path": "test"},
                ],
                "semantic": [],
            },
        }

        facts = _gather_contributor_facts(manifest, sample_render_plan)

        fact = facts[0]
        assert fact["role"] == "constraint"  # Default role
        assert fact["role_priority"] == 1  # Derived from constraint
        assert fact["group_key"] == ""  # Default empty
        assert fact["group_id"] == ""  # Default empty


class TestNormalizeTerminology:
    """Tests for _normalize_terminology function."""

    def test_returns_facts_unchanged_stub(self) -> None:
        """Verify stub returns facts unchanged."""
        facts = [
            {"type": "structural", "field_path": "test"},
            {"type": "semantic", "field_path": "another"},
        ]

        result = _normalize_terminology(facts)

        assert result == facts

    def test_handles_empty_list(self) -> None:
        """Verify empty list is handled."""
        result = _normalize_terminology([])
        assert result == []


class TestOrderFacts:
    """Tests for _order_facts function."""

    def test_orders_by_field_path(self) -> None:
        """Verify facts are ordered by field_path."""
        facts = [
            {"field_path": "z.field"},
            {"field_path": "a.field"},
            {"field_path": "m.field"},
        ]

        result = _order_facts(facts, ["field_path"])

        assert result[0]["field_path"] == "a.field"
        assert result[1]["field_path"] == "m.field"
        assert result[2]["field_path"] == "z.field"

    def test_orders_by_multiple_keys(self) -> None:
        """Verify facts are ordered by multiple keys."""
        facts = [
            {"group_id": "b", "field_path": "z"},
            {"group_id": "a", "field_path": "y"},
            {"group_id": "a", "field_path": "x"},
        ]

        result = _order_facts(facts, ["group_id", "field_path"])

        assert result[0]["group_id"] == "a"
        assert result[0]["field_path"] == "x"
        assert result[1]["group_id"] == "a"
        assert result[1]["field_path"] == "y"
        assert result[2]["group_id"] == "b"

    def test_handles_empty_ordering(self) -> None:
        """Verify empty ordering returns facts unchanged."""
        facts = [{"a": 1}, {"b": 2}]

        result = _order_facts(facts, [])

        assert result == facts

    def test_handles_missing_keys(self) -> None:
        """Verify missing keys are treated as empty string."""
        facts = [
            {"field_path": "b"},
            {},  # Missing field_path
            {"field_path": "a"},
        ]

        result = _order_facts(facts, ["field_path"])

        # Empty string sorts before 'a'
        assert result[0] == {}
        assert result[1]["field_path"] == "a"
        assert result[2]["field_path"] == "b"

    def test_orders_by_role_priority(self) -> None:
        """Verify facts are ordered by role_priority."""
        facts = [
            {"role_priority": 4, "field_path": "a"},  # artifact_root
            {"role_priority": 1, "field_path": "b"},  # constraint
            {"role_priority": 2, "field_path": "c"},  # metadata
        ]

        result = _order_facts(facts, ["role_priority", "field_path"])

        assert result[0]["role_priority"] == 1
        assert result[1]["role_priority"] == 2
        assert result[2]["role_priority"] == 4

    def test_orders_by_role_priority_then_group_id(self) -> None:
        """Verify facts are ordered by role_priority then group_id."""
        facts = [
            {"role_priority": 1, "group_id": "z", "field_path": "a"},
            {"role_priority": 1, "group_id": "a", "field_path": "b"},
            {"role_priority": 2, "group_id": "a", "field_path": "c"},
        ]

        result = _order_facts(facts, ["role_priority", "group_id", "field_path"])

        # Same role_priority, sorted by group_id
        assert result[0]["role_priority"] == 1
        assert result[0]["group_id"] == "a"
        assert result[1]["role_priority"] == 1
        assert result[1]["group_id"] == "z"
        assert result[2]["role_priority"] == 2


class TestDeriveRolePriority:
    """Tests for _derive_role_priority function."""

    def test_constraint_role(self) -> None:
        """Verify constraint role has priority 1."""
        assert _derive_role_priority("constraint") == 1

    def test_metadata_role(self) -> None:
        """Verify metadata role has priority 2."""
        assert _derive_role_priority("metadata") == 2

    def test_entity_ref_role(self) -> None:
        """Verify entity_ref role has priority 3."""
        assert _derive_role_priority("entity_ref") == 3

    def test_artifact_root_role(self) -> None:
        """Verify artifact_root role has priority 4."""
        assert _derive_role_priority("artifact_root") == 4

    def test_unknown_role_defaults_to_99(self) -> None:
        """Verify unknown role defaults to 99."""
        assert _derive_role_priority("unknown") == 99
        assert _derive_role_priority("") == 99


class TestRolePriorityMap:
    """Tests for ROLE_PRIORITY_MAP constant."""

    def test_contains_expected_roles(self) -> None:
        """Verify map contains expected roles."""
        assert "constraint" in ROLE_PRIORITY_MAP
        assert "metadata" in ROLE_PRIORITY_MAP
        assert "entity_ref" in ROLE_PRIORITY_MAP
        assert "artifact_root" in ROLE_PRIORITY_MAP

    def test_constraint_first(self) -> None:
        """Verify constraint has lowest (first) priority value."""
        assert ROLE_PRIORITY_MAP["constraint"] == min(ROLE_PRIORITY_MAP.values())


class TestRenderWithLlm:
    """Tests for _render_with_llm function."""

    def test_returns_placeholder_text(self, sample_render_plan: dict) -> None:
        """Verify stub returns placeholder text."""
        facts = [
            {"type": "structural", "field_path": "test.field"},
        ]

        result = _render_with_llm(facts, sample_render_plan, "prose/paragraph")

        assert "Rendered Artifact: prose/paragraph" in result
        assert "Facts count: 1" in result
        assert "placeholder output" in result.lower()


class TestRenderNone:
    """Tests for _render_none function."""

    def test_returns_source_text(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        sample_manifest: dict,
    ) -> None:
        """Verify source text is returned."""
        # Create source file
        repo_root = artifacts_dir.parent.parent
        source_path = repo_root / "docs" / "test.yml"
        fs.create_file(source_path, contents="description: Test content\nother: value")

        result = _render_none(sample_manifest, artifacts_dir)

        # The field_path is "description", so only the value is extracted
        assert "Test content" in result

    def test_returns_empty_for_missing_source(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        sample_manifest: dict,
    ) -> None:
        """Verify empty string returned for missing source file."""
        result = _render_none(sample_manifest, artifacts_dir)

        assert result == ""

    def test_returns_empty_for_no_source_file(
        self, fs: FakeFilesystem, artifacts_dir: Path
    ) -> None:
        """Verify empty string returned when no source_file."""
        manifest = {
            "artifact_id": "test",
            "source": {"source_file": ""},
        }

        result = _render_none(manifest, artifacts_dir)

        assert result == ""


class TestSelfCheck:
    """Tests for _self_check function."""

    def test_stub_returns_true(self) -> None:
        """Verify stub always returns True."""
        result = _self_check("some rendered text", [{"fact": "value"}])
        assert result is True

    def test_handles_empty_inputs(self) -> None:
        """Verify empty inputs are handled."""
        assert _self_check("", []) is True


class TestGetStepHandler:
    """Tests for _get_step_handler function."""

    def test_returns_handler_for_known_steps(self) -> None:
        """Verify handlers returned for known step IDs."""
        assert _get_step_handler("gather") is _step_gather
        assert _get_step_handler("normalize") is _step_normalize
        assert _get_step_handler("order") is _step_order
        assert _get_step_handler("render") is _step_render
        assert _get_step_handler("self_check") is _step_self_check

    def test_returns_none_for_unknown_step(self) -> None:
        """Verify None returned for unknown step ID."""
        assert _get_step_handler("unknown") is None
        assert _get_step_handler("") is None


class TestStepHandlers:
    """Tests for individual step handler functions."""

    def test_step_gather_collects_facts(
        self, sample_manifest: dict, sample_render_plan: dict
    ) -> None:
        """Verify _step_gather collects contributor facts."""
        ctx = {"manifest": sample_manifest, "render_plan": sample_render_plan}

        result = _step_gather(ctx)

        assert "facts" in result
        assert len(result["facts"]) == 3  # 2 structural + 1 semantic

    def test_step_normalize_normalizes_facts(self) -> None:
        """Verify _step_normalize normalizes facts."""
        ctx = {"facts": [{"field_path": "test"}]}

        result = _step_normalize(ctx)

        assert "normalized_facts" in result
        assert result["normalized_facts"] == ctx["facts"]

    def test_step_order_orders_facts(self, sample_render_plan: dict) -> None:
        """Verify _step_order orders facts by determinism rules."""
        ctx = {
            "render_plan": sample_render_plan,
            "normalized_facts": [
                {"field_path": "z"},
                {"field_path": "a"},
            ],
        }

        result = _step_order(ctx)

        assert "ordered_facts" in result
        assert result["ordered_facts"][0]["field_path"] == "a"
        assert result["ordered_facts"][1]["field_path"] == "z"

    def test_step_render_renders_with_llm(
        self, sample_render_plan: dict
    ) -> None:
        """Verify _step_render renders with text_llm engine."""
        ctx = {
            "render_plan": sample_render_plan,
            "artifact_kind": "prose/paragraph",
            "ordered_facts": [{"field_path": "test"}],
            "manifest": {},
            "artifacts_dir": Path("/fake"),
        }

        result = _step_render(ctx)

        assert "rendered_text" in result
        assert "Rendered Artifact" in result["rendered_text"]

    def test_step_self_check_validates(self) -> None:
        """Verify _step_self_check validates rendered output."""
        ctx = {
            "artifact_id": "test-123",
            "rendered_text": "test content",
            "ordered_facts": [{"fact": "value"}],
        }

        result = _step_self_check(ctx)

        # Stub always passes, should not raise
        assert result is ctx


class TestRenderArtifact:
    """Tests for render_artifact function."""

    def test_renders_text_llm_artifact(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: dict,
        sample_render_plan: dict,
    ) -> None:
        """Verify artifact is rendered with text_llm engine."""
        result = render_artifact(
            sample_manifest,
            sample_render_plan,
            artifacts_dir,
            rendered_dir,
        )

        assert result.exists()
        assert result.suffix == ".md"
        content = result.read_text()
        assert "Rendered Artifact" in content

    def test_renders_none_engine_artifact(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: dict,
        sample_render_plan: dict,
    ) -> None:
        """Verify artifact is rendered with none engine."""
        # Create source file
        repo_root = artifacts_dir.parent.parent
        source_path = repo_root / "docs" / "test.yml"
        fs.create_file(source_path, contents="description: Source content")

        sample_render_plan["render_engine"] = "none"

        result = render_artifact(
            sample_manifest,
            sample_render_plan,
            artifacts_dir,
            rendered_dir,
        )

        assert result.exists()

    def test_creates_output_directory(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        sample_manifest: dict,
        sample_render_plan: dict,
    ) -> None:
        """Verify output directory is created if not exists."""
        rendered_dir = Path("/fake/new/rendered")
        # Don't create dir - let function create it

        result = render_artifact(
            sample_manifest,
            sample_render_plan,
            artifacts_dir,
            rendered_dir,
        )

        assert result.exists()
        assert rendered_dir.exists()

    def test_raises_for_unsupported_engine(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: dict,
        sample_render_plan: dict,
    ) -> None:
        """Verify ValueError raised for unsupported engine."""
        sample_render_plan["render_engine"] = "unsupported"

        with pytest.raises(ValueError, match="Unsupported render_engine"):
            render_artifact(
                sample_manifest,
                sample_render_plan,
                artifacts_dir,
                rendered_dir,
            )

    def test_uses_correct_extension(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: dict,
        sample_render_plan: dict,
    ) -> None:
        """Verify correct file extension is used based on format."""
        sample_manifest["artifact_format"] = "text/x-mermaid"

        result = render_artifact(
            sample_manifest,
            sample_render_plan,
            artifacts_dir,
            rendered_dir,
        )

        assert result.suffix == ".mmd"

    def test_uses_custom_steps_from_render_plan(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: dict,
        sample_render_plan: dict,
    ) -> None:
        """Verify render_artifact interprets custom steps from render plan."""
        # Define custom steps (skip normalize step)
        sample_render_plan["steps"] = [
            {"id": "gather", "instruction": "Collect facts"},
            {"id": "order", "instruction": "Order facts"},
            {"id": "render", "instruction": "Render artifact"},
        ]

        result = render_artifact(
            sample_manifest,
            sample_render_plan,
            artifacts_dir,
            rendered_dir,
        )

        assert result.exists()
        content = result.read_text()
        assert "Rendered Artifact" in content

    def test_uses_default_steps_when_none_specified(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: dict,
        sample_render_plan: dict,
    ) -> None:
        """Verify default steps used when render plan has no steps."""
        # Remove steps from render plan
        del sample_render_plan["steps"]

        result = render_artifact(
            sample_manifest,
            sample_render_plan,
            artifacts_dir,
            rendered_dir,
        )

        assert result.exists()
        content = result.read_text()
        assert "Rendered Artifact" in content

    def test_skips_unrecognized_steps(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: dict,
        sample_render_plan: dict,
    ) -> None:
        """Verify unrecognized steps are skipped gracefully."""
        sample_render_plan["steps"] = [
            {"id": "gather"},
            {"id": "unknown_step"},  # Should be skipped
            {"id": "render"},
        ]

        result = render_artifact(
            sample_manifest,
            sample_render_plan,
            artifacts_dir,
            rendered_dir,
        )

        assert result.exists()
