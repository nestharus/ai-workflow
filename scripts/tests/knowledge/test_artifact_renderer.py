"""Unit tests for artifact_renderer module."""

from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from scripts.knowledge.artifact_manager import ArtifactManifest
from scripts.knowledge.artifact_renderer import (
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
from scripts.knowledge.render_plan_manager import RenderPlan


@pytest.fixture
def sample_manifest() -> ArtifactManifest:
    """Create a sample artifact manifest for testing."""
    return cast(
        "ArtifactManifest",
        {
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
        },
    )


@pytest.fixture
def sample_render_plan() -> RenderPlan:
    """Create a sample render plan for testing."""
    return cast(
        "RenderPlan",
        {
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
        },
    )


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


@pytest.fixture
def mock_claude_cli() -> Iterator[MagicMock]:
    """Set up mocks for successful Claude CLI invocation.

    Yields a mock_run object that can be used for assertions.
    """
    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "Rendered content from LLM"
    mock_run.return_value.stderr = ""

    with (
        patch("scripts.knowledge.artifact_renderer.shutil.which", return_value="/usr/bin/claude"),
        patch("scripts.knowledge.artifact_renderer.subprocess.run", mock_run),
    ):
        yield mock_run


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
        self, sample_manifest: ArtifactManifest, sample_render_plan: RenderPlan
    ) -> None:
        """Verify structural facts are gathered."""
        facts = _gather_contributor_facts(sample_manifest, sample_render_plan)

        structural_facts = [f for f in facts if f["type"] == "structural"]
        assert len(structural_facts) == 2

    def test_gathers_semantic_facts(
        self, sample_manifest: ArtifactManifest, sample_render_plan: RenderPlan
    ) -> None:
        """Verify semantic facts are gathered."""
        facts = _gather_contributor_facts(sample_manifest, sample_render_plan)

        semantic_facts = [f for f in facts if f["type"] == "semantic"]
        assert len(semantic_facts) == 1

    def test_respects_input_flags(
        self, sample_manifest: ArtifactManifest, sample_render_plan: RenderPlan
    ) -> None:
        """Verify input flags control which facts are gathered."""
        # Disable semantic facts
        sample_render_plan["inputs"]["use_semantic_facts"] = False

        facts = _gather_contributor_facts(sample_manifest, sample_render_plan)

        assert all(f["type"] == "structural" for f in facts)

    def test_handles_empty_contributors(self, sample_render_plan: RenderPlan) -> None:
        """Verify empty contributors is handled."""
        manifest = cast(
            "ArtifactManifest",
            {
                "artifact_id": "test",
                "contributors": {"structural": [], "semantic": []},
            },
        )

        facts = _gather_contributor_facts(manifest, sample_render_plan)

        assert facts == []

    def test_includes_ordering_fields(
        self, sample_manifest: ArtifactManifest, sample_render_plan: RenderPlan
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

    def test_defaults_missing_ordering_fields(self, sample_render_plan: RenderPlan) -> None:
        """Verify missing ordering fields get default values."""
        manifest = cast(
            "ArtifactManifest",
            {
                "artifact_id": "test",
                "contributors": {
                    "structural": [
                        {"element_id": "elem-1", "field_path": "test"},
                    ],
                    "semantic": [],
                },
            },
        )

        facts = _gather_contributor_facts(manifest, sample_render_plan)

        fact = facts[0]
        assert fact["role"] == "constraint"  # Default role
        assert fact["role_priority"] == 1  # Derived from constraint
        assert fact["group_key"] == ""  # Default empty
        assert fact["group_id"] == ""  # Default empty


class TestNormalizeTerminology:
    """Tests for _normalize_terminology function."""

    def test_returns_facts_unchanged_without_mapping(self) -> None:
        """Verify facts are returned unchanged when no variant mapping is provided."""
        facts = [
            {"type": "structural", "field_path": "test", "value": "some content"},
            {"type": "semantic", "field_path": "another", "value": "other content"},
        ]

        # With empty mapping, facts should be unchanged
        result = _normalize_terminology(facts, keyword_variant_mapping={})

        assert result == facts

    def test_handles_empty_list(self) -> None:
        """Verify empty list is handled."""
        from unittest.mock import patch

        # Mock apply_variant_decisions to avoid needing the CSV file
        with patch("scripts.knowledge.variant_resolver.apply_variant_decisions", return_value={}):
            result = _normalize_terminology([])

            assert result == []

    def test_replaces_variant_terms(self) -> None:
        """Verify variant terms are replaced with canonical forms."""
        facts = [
            {"type": "structural", "value": "Use FastAPI for REST APIs"},
        ]
        mapping = {"REST": "RESTful", "FastAPI": "FastAPI"}

        result = _normalize_terminology(facts, keyword_variant_mapping=mapping)

        assert result[0]["value"] == "Use FastAPI for RESTful APIs"

    def test_handles_multiple_fields(self) -> None:
        """Verify normalization applies to multiple text fields."""
        facts = [
            {"fact_text": "REST API", "value": "REST endpoint", "text": "REST service"},
        ]
        mapping = {"REST": "RESTful"}

        result = _normalize_terminology(facts, keyword_variant_mapping=mapping)

        assert "RESTful API" in result[0]["fact_text"]
        assert "RESTful endpoint" in result[0]["value"]
        assert "RESTful service" in result[0]["text"]


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

    def test_calls_claude_cli(self, sample_render_plan: RenderPlan) -> None:
        """Verify Claude CLI is invoked with correct arguments."""
        from unittest.mock import patch

        facts = [
            {"type": "structural", "field_path": "test.field"},
        ]

        with (
            patch(
                "scripts.knowledge.artifact_renderer.shutil.which", return_value="/usr/bin/claude"
            ),
            patch("scripts.knowledge.artifact_renderer.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Rendered content from LLM"
            mock_run.return_value.stderr = ""

            result = _render_with_llm(facts, sample_render_plan, "prose/paragraph")

            assert result == "Rendered content from LLM"
            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            assert "claude" in call_args[0]
            assert "--model" in call_args
            assert "haiku" in call_args

    def test_falls_back_to_source_text_on_failure(self, sample_render_plan: RenderPlan) -> None:
        """Verify fallback to source text when CLI fails."""
        from unittest.mock import patch

        facts = [{"type": "structural", "field_path": "test"}]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "Error"

            result = _render_with_llm(
                facts, sample_render_plan, "prose/paragraph", source_text="Original source text"
            )

            assert result == "Original source text"

    def test_falls_back_on_timeout(self, sample_render_plan: RenderPlan) -> None:
        """Verify fallback to source text on timeout."""
        import subprocess
        from unittest.mock import patch

        facts = [{"type": "structural", "field_path": "test"}]

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)

            result = _render_with_llm(
                facts, sample_render_plan, "prose/paragraph", source_text="Fallback text"
            )

            assert result == "Fallback text"

    def test_minimal_placeholder_when_no_source(self, sample_render_plan: RenderPlan) -> None:
        """Verify minimal placeholder when CLI fails and no source text."""
        from unittest.mock import patch

        facts = [{"type": "structural", "field_path": "test"}]

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("claude not found")

            result = _render_with_llm(facts, sample_render_plan, "prose/paragraph")

            assert "prose/paragraph" in result


class TestRenderNone:
    """Tests for _render_none function."""

    def test_returns_source_text(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        sample_manifest: ArtifactManifest,
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
        sample_manifest: ArtifactManifest,
    ) -> None:
        """Verify empty string returned for missing source file."""
        result = _render_none(sample_manifest, artifacts_dir)

        assert result == ""

    def test_returns_empty_for_no_source_file(
        self, fs: FakeFilesystem, artifacts_dir: Path
    ) -> None:
        """Verify empty string returned when no source_file."""
        manifest = cast(
            "ArtifactManifest",
            {
                "artifact_id": "test",
                "source": {"source_file": ""},
            },
        )

        result = _render_none(manifest, artifacts_dir)

        assert result == ""


class TestSelfCheck:
    """Tests for _self_check function."""

    def test_handles_empty_inputs(self) -> None:
        """Verify empty inputs return True (vacuous pass)."""
        assert _self_check("", []) is True
        assert _self_check("some text", []) is True
        assert _self_check("", [{"value": "fact"}]) is True

    def test_returns_true_without_embeddings(self) -> None:
        """Verify falls back to True when embeddings unavailable."""
        from unittest.mock import patch

        # When variant_resolver import fails, should return True
        with patch.dict("sys.modules", {"scripts.knowledge.variant_resolver": None}):
            result = _self_check("some rendered text", [{"value": "fact content"}])
            assert result is True

    def test_uses_embeddings_when_available(self) -> None:
        """Verify embedding-based verification is attempted when available."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        rendered_text = "This is a test sentence. Another statement here."
        facts = [{"value": "test sentence"}, {"value": "another statement"}]

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Create mock embeddings with high similarity
        mock_embeddings = np.array([[0.9, 0.1], [0.1, 0.9], [0.85, 0.15], [0.15, 0.85]])

        # Patch at the source module (variant_resolver) where the functions are defined
        with (
            patch(
                "scripts.knowledge.variant_resolver.load_qwen_embedding_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.knowledge.variant_resolver.embed_keywords", return_value=mock_embeddings
            ),
            patch(
                "scripts.knowledge.variant_resolver.compute_cosine_similarity",
                return_value=np.array([[0.9, 0.2], [0.2, 0.85]]),
            ),
        ):
            result = _self_check(rendered_text, facts)
            # Should pass with high similarity
            assert result is True

    def test_extracts_statements_correctly(self) -> None:
        """Verify statements are extracted from rendered text."""
        # Test with ImportError to see that the function handles the path without embeddings
        result = _self_check("Short.", [{"value": "Short"}])
        # Without embeddings available, should return True
        assert result is True


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
        self, sample_manifest: ArtifactManifest, sample_render_plan: RenderPlan
    ) -> None:
        """Verify _step_gather collects contributor facts."""
        ctx = {"manifest": sample_manifest, "render_plan": sample_render_plan}

        result = _step_gather(ctx)

        assert "facts" in result
        assert len(result["facts"]) == 3  # 2 structural + 1 semantic

    def test_step_normalize_normalizes_facts(self) -> None:
        """Verify _step_normalize normalizes facts."""
        from unittest.mock import patch

        ctx = {"facts": [{"field_path": "test"}]}

        # Mock apply_variant_decisions to avoid needing the CSV file
        with patch("scripts.knowledge.variant_resolver.apply_variant_decisions", return_value={}):
            result = _step_normalize(ctx)

            assert "normalized_facts" in result
            assert result["normalized_facts"] == ctx["facts"]

    def test_step_order_orders_facts(self, sample_render_plan: RenderPlan) -> None:
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

    def test_step_render_renders_with_llm(self, sample_render_plan: RenderPlan) -> None:
        """Verify _step_render renders with text_llm engine."""
        from unittest.mock import patch

        ctx = {
            "render_plan": sample_render_plan,
            "artifact_kind": "prose/paragraph",
            "ordered_facts": [{"field_path": "test"}],
            "manifest": {},
            "artifacts_dir": Path("/fake"),
        }

        with patch("scripts.knowledge.artifact_renderer.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Rendered content from LLM"
            mock_run.return_value.stderr = ""

            result = _step_render(ctx)

            assert "rendered_text" in result
            assert result["rendered_text"] == "Rendered content from LLM"

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
        sample_manifest: ArtifactManifest,
        sample_render_plan: RenderPlan,
        mock_claude_cli: MagicMock,
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
        assert content == "Rendered content from LLM"

    def test_renders_none_engine_artifact(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: ArtifactManifest,
        sample_render_plan: RenderPlan,
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
        sample_manifest: ArtifactManifest,
        sample_render_plan: RenderPlan,
    ) -> None:
        """Verify output directory is created if not exists."""
        from unittest.mock import patch

        rendered_dir = Path("/fake/new/rendered")
        # Don't create dir - let function create it

        with patch("scripts.knowledge.artifact_renderer.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Rendered content from LLM"
            mock_run.return_value.stderr = ""

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
        sample_manifest: ArtifactManifest,
        sample_render_plan: RenderPlan,
    ) -> None:
        """Verify ValueError raised for unsupported engine."""
        sample_render_plan["render_engine"] = "unsupported"  # type: ignore[typeddict-item]

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
        sample_manifest: ArtifactManifest,
        sample_render_plan: RenderPlan,
    ) -> None:
        """Verify correct file extension is used based on format."""
        from unittest.mock import patch

        sample_manifest["artifact_format"] = "text/x-mermaid"

        with patch("scripts.knowledge.artifact_renderer.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "sequenceDiagram\n    A->>B: Hello"
            mock_run.return_value.stderr = ""

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
        sample_manifest: ArtifactManifest,
        sample_render_plan: RenderPlan,
        mock_claude_cli: MagicMock,
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
        assert content == "Rendered content from LLM"

    def test_uses_default_steps_when_none_specified(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: ArtifactManifest,
        sample_render_plan: RenderPlan,
        mock_claude_cli: MagicMock,
    ) -> None:
        """Verify default steps used when render plan has no steps."""
        from unittest.mock import MagicMock, patch

        # Remove steps from render plan
        del sample_render_plan["steps"]  # type: ignore[misc]

        # Create a mock for the normalize function that needs variant_resolver
        # _normalize_terminology(facts, keyword_variant_mapping=None, knowledge_path=None)
        mock_normalize = MagicMock(side_effect=lambda facts, *args, **kwargs: facts)

        # Mock _normalize_terminology to avoid importing variant_resolver during test
        with patch("scripts.knowledge.artifact_renderer._normalize_terminology", mock_normalize):
            result = render_artifact(
                sample_manifest,
                sample_render_plan,
                artifacts_dir,
                rendered_dir,
            )

            assert result.exists()
            content = result.read_text()
            assert content == "Rendered content from LLM"
            # Verify that the default pipeline runs the normalize step
            mock_normalize.assert_called_once()

    def test_skips_unrecognized_steps(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: ArtifactManifest,
        sample_render_plan: RenderPlan,
    ) -> None:
        """Verify unrecognized steps are skipped gracefully."""
        from unittest.mock import patch

        sample_render_plan["steps"] = [
            {"id": "gather", "instruction": "Gather facts"},
            {"id": "unknown_step", "instruction": "Unknown"},  # Should be skipped
            {"id": "render", "instruction": "Render"},
        ]

        with patch("scripts.knowledge.artifact_renderer.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Rendered content from LLM"
            mock_run.return_value.stderr = ""

            result = render_artifact(
                sample_manifest,
                sample_render_plan,
                artifacts_dir,
                rendered_dir,
            )

            assert result.exists()
