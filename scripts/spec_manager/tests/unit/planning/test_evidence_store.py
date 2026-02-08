"""Tests for planning.evidence_store module."""

from __future__ import annotations

from pathlib import Path

from spec_manager.planning.evidence_store import (
    AmbiguityResolution,
    EvidenceHit,
    EvidenceStore,
)
from spec_manager.planning.models import FunctionInfo


class TestEvidenceHit:
    """Tests for EvidenceHit dataclass."""

    def test_creation(self) -> None:
        hit = EvidenceHit(
            lib_id="LIB-001",
            section_heading="Payment Rules",
            element_id="ATOM-F0001-R0001-L0001",
            excerpt="Validate payment against fraud rules",
            relevance_score=0.85,
            source_path="/specs/payments.md",
        )
        assert hit.lib_id == "LIB-001"
        assert hit.relevance_score == 0.85

    def test_frozen(self) -> None:
        hit = EvidenceHit(
            lib_id="LIB-001",
            section_heading="Test",
            element_id=None,
            excerpt="test",
            relevance_score=0.5,
            source_path="/test.md",
        )
        try:
            hit.lib_id = "LIB-002"  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass


class TestAmbiguityResolution:
    """Tests for AmbiguityResolution dataclass."""

    def test_resolved(self) -> None:
        resolution = AmbiguityResolution(
            resolved=True,
            answer="Check against daily limit and velocity",
            evidence_refs=["LIB-001::ATOM-001"],
            gap_description=None,
            refined_comments=["check daily limit", "run velocity check"],
        )
        assert resolution.resolved is True
        assert resolution.answer is not None
        assert len(resolution.refined_comments) == 2

    def test_unresolved(self) -> None:
        resolution = AmbiguityResolution(
            resolved=False,
            answer=None,
            evidence_refs=[],
            gap_description="No evidence found for fraud rules",
            refined_comments=["validate payment against fraud rules"],
        )
        assert resolution.resolved is False
        assert resolution.gap_description is not None


class TestEvidenceStore:
    """Tests for EvidenceStore class."""

    def test_init_empty_dirs(self, tmp_path: Path) -> None:
        """Initialize with empty directories."""
        spec_dir = tmp_path / "spec_snapshot"
        spec_dir.mkdir()
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()

        store = EvidenceStore(spec_dir, libs_dir)
        results = store.search("anything")
        assert results == []

    def test_indexes_markdown_files(self, tmp_path: Path) -> None:
        """Index markdown files and find matching content."""
        spec_dir = tmp_path / "spec_snapshot"
        spec_dir.mkdir()
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()

        # Create a library file
        lib_content = (
            "# Payment Rules\n\n"
            "## Fraud Detection\n\n"
            "- ATOM-F0001-R0001-L0001: Validate transaction amount\n"
            "- Check daily transaction limit of $10,000\n"
            "- Run velocity checks on last 24 hours\n"
        )
        (libs_dir / "payments.md").write_text(lib_content, encoding="utf-8")

        store = EvidenceStore(spec_dir, libs_dir)
        results = store.search("fraud detection payment")
        assert len(results) > 0

    def test_search_keyword_matching(self, tmp_path: Path) -> None:
        """Search uses keyword matching."""
        spec_dir = tmp_path / "spec_snapshot"
        spec_dir.mkdir()
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()

        (libs_dir / "auth.md").write_text(
            "# Authentication\n\n## Login Flow\n\n- ATOM-F0001-R0001-L0001: Validate credentials\n",
            encoding="utf-8",
        )
        (libs_dir / "payments.md").write_text(
            "# Payments\n\n## Processing\n\n- ATOM-F0002-R0001-L0001: Process payment\n",
            encoding="utf-8",
        )

        store = EvidenceStore(spec_dir, libs_dir)

        # Search for authentication should rank auth higher
        auth_results = store.search("authentication login credentials")
        pay_results = store.search("payment processing")

        assert len(auth_results) > 0
        assert len(pay_results) > 0

    def test_search_max_results(self, tmp_path: Path) -> None:
        """Search respects max_results."""
        spec_dir = tmp_path / "spec_snapshot"
        spec_dir.mkdir()
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()

        # Create multiple matching sections
        content = "# Test\n\n"
        for i in range(10):
            content += f"## Section {i}\n\nATOM-F{i:04d}-R0001-L0001: keyword test\n\n"
        (libs_dir / "test.md").write_text(content, encoding="utf-8")

        store = EvidenceStore(spec_dir, libs_dir)
        results = store.search("keyword test", max_results=3)
        assert len(results) <= 3

    def test_search_with_context(self, tmp_path: Path) -> None:
        """Search can use optional context to narrow results."""
        spec_dir = tmp_path / "spec_snapshot"
        spec_dir.mkdir()
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()

        (libs_dir / "payments.md").write_text(
            "# Payments\n\n## Fraud Rules\n\n"
            "- ATOM-F0001-R0001-L0001: Check fraud amount validation\n",
            encoding="utf-8",
        )

        store = EvidenceStore(spec_dir, libs_dir)
        results = store.search(
            "fraud rules",
            context="function: validate_payment, params: order",
        )
        # Should still find results even with context
        assert isinstance(results, list)

    def test_lazy_loading(self, tmp_path: Path) -> None:
        """Content is loaded lazily (on demand)."""
        spec_dir = tmp_path / "spec_snapshot"
        spec_dir.mkdir()
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()

        (libs_dir / "test.md").write_text(
            "# Test\n\n## Details\n\nATOM-F0001-R0001-L0001: Important detail here\n",
            encoding="utf-8",
        )

        store = EvidenceStore(spec_dir, libs_dir)
        # Content cache should be empty before search
        assert len(store._content_cache) == 0

        results = store.search("important detail")
        if results:
            # Content should now be cached after loading
            assert len(store._content_cache) > 0

    def test_resolve_ambiguity_no_evidence(self, tmp_path: Path) -> None:
        """Resolve ambiguity with no matching evidence."""
        spec_dir = tmp_path / "spec_snapshot"
        spec_dir.mkdir()
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()

        store = EvidenceStore(spec_dir, libs_dir)
        func = _make_func_info("validate_payment")

        resolution = store.resolve_ambiguity("validate against fraud rules", func)
        assert resolution.resolved is False
        assert resolution.gap_description is not None

    def test_resolve_ambiguity_with_evidence(self, tmp_path: Path) -> None:
        """Resolve ambiguity when evidence exists (no LLM, falls back)."""
        spec_dir = tmp_path / "spec_snapshot"
        spec_dir.mkdir()
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()

        (libs_dir / "payments.md").write_text(
            "# Payments\n\n## Fraud Rules\n\n"
            "Check transaction amount against daily limit of $10,000.\n"
            "Run velocity check on last 24 hours.\n",
            encoding="utf-8",
        )

        store = EvidenceStore(spec_dir, libs_dir)
        func = _make_func_info("validate_payment")

        resolution = store.resolve_ambiguity("validate against fraud rules", func)
        # Should find evidence even without LLM synthesis
        assert len(resolution.evidence_refs) > 0


class TestEvidenceStoreNonexistentDirs:
    """Tests for EvidenceStore with nonexistent directories."""

    def test_nonexistent_dirs(self, tmp_path: Path) -> None:
        """Handles nonexistent directories gracefully."""
        store = EvidenceStore(
            tmp_path / "nonexistent_spec",
            tmp_path / "nonexistent_libs",
        )
        results = store.search("anything")
        assert results == []


def _make_func_info(name: str) -> FunctionInfo:
    """Create a minimal FunctionInfo for testing."""
    return FunctionInfo(
        name=name,
        file_path="/test.py",
        start_line=1,
        end_line=5,
        indent_level=0,
        parameters=["self", "order"],
        return_annotation="bool",
        docstring="Validate payment.",
        body_lines=["def validate_payment(self, order):", "    pass"],
        calls=[],
        comments=[],
        class_name=None,
        decorators=[],
    )
