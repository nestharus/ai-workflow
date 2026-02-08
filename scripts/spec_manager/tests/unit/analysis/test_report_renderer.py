"""Tests for analysis Markdown report rendering."""

from __future__ import annotations

from spec_manager.analysis.report_renderer import (
    render_analysis_markdown,
    render_summary_table,
)
from spec_manager.schemas.lineage import (
    AnalysisFileSchema,
    AtomAdjacency,
    AtomAnalysisEntry,
    DataFlowSummary,
    LineageEdge,
    OrphanedArchEntry,
)


class TestRenderAnalysisMarkdown:
    """Test the full Markdown rendering."""

    def test_produces_valid_markdown(self) -> None:
        analysis = AnalysisFileSchema(
            run_id="test-render",
            generated_at="2025-01-01T00:00:00Z",
            atoms=[
                AtomAnalysisEntry(
                    atom_id="validate_payment",
                    atom_file="atoms/payment.py",
                    forward_traces=[
                        LineageEdge(
                            from_atom="validate_payment",
                            to_location="src/handler.py:process",
                            transformation="pass_through",
                            confidence=1.0,
                        )
                    ],
                    adjacency=AtomAdjacency(
                        atom_id="validate_payment",
                        co_occurrence_edges=["compute_tax"],
                    ),
                    data_flow=DataFlowSummary(
                        atom_id="validate_payment",
                        signals_in=["amount: float"],
                        signals_out=["bool"],
                    ),
                    is_unimplemented=False,
                ),
            ],
            orphaned_architecture=[
                OrphanedArchEntry(
                    location="src/orphan.py",
                    description="Orphaned file",
                    suggested_action="investigate",
                )
            ],
            summary={
                "total_atoms": 1,
                "implemented_atoms": 1,
                "unimplemented_atoms": 0,
                "orphaned_architecture": 1,
                "pass_through_imports": 1,
                "wrap_imports": 0,
                "smear_imports": 0,
                "total_lineage_edges": 1,
            },
        )
        md = render_analysis_markdown(analysis)

        assert "# Analysis Report" in md
        assert "## Summary" in md
        assert "## Per-Atom Analysis" in md
        assert "validate_payment" in md
        assert "## Unimplemented Atoms" in md
        assert "## Orphaned Architecture" in md
        assert "src/orphan.py" in md

    def test_empty_analysis_renders_gracefully(self) -> None:
        analysis = AnalysisFileSchema(
            run_id="test-empty",
            generated_at="2025-01-01T00:00:00Z",
            summary={
                "total_atoms": 0,
                "implemented_atoms": 0,
                "unimplemented_atoms": 0,
                "orphaned_architecture": 0,
            },
        )
        md = render_analysis_markdown(analysis)

        assert "# Analysis Report" in md
        assert "No implemented atoms found." in md
        assert "No unimplemented atoms." in md
        assert "No orphaned architecture detected." in md

    def test_per_atom_section_includes_forward_traces_table(self) -> None:
        analysis = AnalysisFileSchema(
            run_id="test-traces",
            generated_at="2025-01-01T00:00:00Z",
            atoms=[
                AtomAnalysisEntry(
                    atom_id="compute_tax",
                    atom_file="atoms/tax.py",
                    forward_traces=[
                        LineageEdge(
                            from_atom="compute_tax",
                            to_location="src/billing.py:calc",
                            transformation="middleware_wrap",
                            confidence=0.85,
                        )
                    ],
                ),
            ],
            summary={"total_atoms": 1, "implemented_atoms": 1},
        )
        md = render_analysis_markdown(analysis)

        assert "| Architectural Location | Projection Type | Confidence |" in md
        assert "src/billing.py:calc" in md
        assert "middleware_wrap" in md
        assert "0.85" in md

    def test_unimplemented_atoms_populated(self) -> None:
        analysis = AnalysisFileSchema(
            run_id="test-unimpl",
            generated_at="2025-01-01T00:00:00Z",
            atoms=[
                AtomAnalysisEntry(
                    atom_id="lonely_atom",
                    atom_file="atoms/lonely.py",
                    is_unimplemented=True,
                ),
            ],
            summary={"total_atoms": 1, "unimplemented_atoms": 1},
        )
        md = render_analysis_markdown(analysis)

        assert "| lonely_atom |" in md
        assert "atoms/lonely.py" in md
        assert "No architectural imports found" in md

    def test_orphaned_architecture_populated(self) -> None:
        analysis = AnalysisFileSchema(
            run_id="test-orphan",
            generated_at="2025-01-01T00:00:00Z",
            orphaned_architecture=[
                OrphanedArchEntry(
                    location="src/orphan.py",
                    description="Legacy helper",
                    suggested_action="create_atom",
                ),
            ],
            summary={"orphaned_architecture": 1},
        )
        md = render_analysis_markdown(analysis)

        assert "src/orphan.py" in md
        assert "Legacy helper" in md
        assert "create_atom" in md


class TestRenderSummaryTable:
    """Test standalone summary table rendering."""

    def test_standalone_usage(self) -> None:
        analysis = AnalysisFileSchema(
            run_id="test-summary",
            generated_at="2025-01-01T00:00:00Z",
            summary={
                "total_atoms": 10,
                "implemented_atoms": 8,
                "unimplemented_atoms": 2,
                "orphaned_architecture": 3,
                "pass_through_imports": 5,
                "wrap_imports": 2,
                "smear_imports": 1,
                "total_lineage_edges": 8,
            },
        )
        table = render_summary_table(analysis)

        assert "| Metric | Value |" in table
        assert "| Total atoms | 10 |" in table
        assert "| Implemented atoms | 8 |" in table
        assert "| Unimplemented atoms | 2 |" in table
        assert "| Orphaned architecture | 3 |" in table

    def test_empty_summary(self) -> None:
        analysis = AnalysisFileSchema(
            run_id="test-empty-summary",
            generated_at="2025-01-01T00:00:00Z",
        )
        table = render_summary_table(analysis)

        assert "| Metric | Value |" in table
        assert "| Total atoms | 0 |" in table
