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


class TestNormalizeTerminology:
    def test_handles_empty_list(self) -> None:
        """Verify empty list is handled."""
        from unittest.mock import patch

        # Mock apply_variant_decisions to avoid needing the CSV file
        with patch("scripts.knowledge.variant_resolver.apply_variant_decisions", return_value={}):
            result = _normalize_terminology([])

            assert result == []


class TestRenderWithLlm:
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


class TestSelfCheck:
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


class TestStepHandlers:
    def test_step_normalize_normalizes_facts(self) -> None:
        """Verify _step_normalize normalizes facts."""
        from unittest.mock import patch

        ctx = {"facts": [{"field_path": "test"}]}

        # Mock apply_variant_decisions to avoid needing the CSV file
        with patch("scripts.knowledge.variant_resolver.apply_variant_decisions", return_value={}):
            result = _step_normalize(ctx)

            assert "normalized_facts" in result
            assert result["normalized_facts"] == ctx["facts"]

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


class TestRenderArtifact:
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
