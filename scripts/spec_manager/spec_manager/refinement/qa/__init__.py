"""Manual QA harness for spec-refinement agent steps.

These QA cases are intentionally NOT part of the automated pytest suite because they can
invoke external LLMs and are meant to be run on-demand.
"""

from spec_manager.refinement.qa.cases import QA_CASES
from spec_manager.refinement.qa.runner import run_qa_case, run_qa_suite

__all__ = ["QA_CASES", "run_qa_case", "run_qa_suite"]
