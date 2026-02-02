"""Core gap primitives for spec refinement."""

from spec_manager.refinement.core.gap import (
    Gap,
    GapEvidence,
    GapSynthesizer,
    GapType,
    compute_evidence_signature,
    format_gap_markdown,
    format_gap_table,
    parse_gaps_markdown,
)
from spec_manager.refinement.core.gap_queue import GapQueue

__all__ = [
    "Gap",
    "GapEvidence",
    "GapSynthesizer",
    "GapType",
    "GapQueue",
    "compute_evidence_signature",
    "format_gap_markdown",
    "format_gap_table",
    "parse_gaps_markdown",
]
