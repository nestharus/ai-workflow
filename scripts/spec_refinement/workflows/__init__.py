"""Workflow orchestration for spec refinement phases.

Workflows coordinate agent execution, structured output parsing, and workspace
state transitions while keeping each phase resumable and auditable.
"""

from spec_manager.refinement.workspace import Phase

from .architecture import (
    map_libraries_to_architecture,
    propose_architectures,
    select_architecture,
)
from .evidence_expansion import expand_evidence, spotcheck_evidence
from .library_synthesis import synthesize_libraries
from .phase_01_sectionization import sectionize_all
from .spec_building import build_specs
from .sublibrary_detection import detect_sublibraries
from .summarization import summarize_all

__all__ = [
    "Phase",
    "build_specs",
    "detect_sublibraries",
    "expand_evidence",
    "map_libraries_to_architecture",
    "propose_architectures",
    "sectionize_all",
    "select_architecture",
    "spotcheck_evidence",
    "summarize_all",
    "synthesize_libraries",
]
