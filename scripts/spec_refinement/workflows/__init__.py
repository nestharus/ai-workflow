"""Workflow orchestration for spec refinement phases.

Workflows coordinate agent execution, structured output parsing, and workspace
state transitions while keeping each phase resumable and auditable.
"""

from scripts.spec_refinement.workspace import Phase

from .evidence_expansion import expand_evidence, spotcheck_evidence
from .library_synthesis import synthesize_libraries
from .spec_building import build_specs
from .sublibrary_detection import detect_sublibraries
from .summarization import summarize_all

__all__ = [
    "Phase",
    "build_specs",
    "detect_sublibraries",
    "expand_evidence",
    "spotcheck_evidence",
    "summarize_all",
    "synthesize_libraries",
]
