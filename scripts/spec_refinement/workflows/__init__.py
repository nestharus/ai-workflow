"""Workflow orchestration for spec refinement phases.

Workflows coordinate agent execution, structured output parsing, and workspace
state transitions while keeping each phase resumable and auditable.
"""

from scripts.spec_refinement.workspace import Phase

from .library_synthesis import synthesize_libraries
from .summarization import summarize_all

__all__ = ["Phase", "summarize_all", "synthesize_libraries"]
