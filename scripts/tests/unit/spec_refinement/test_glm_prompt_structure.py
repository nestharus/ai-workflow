"""Tests for GLM prompt structure compliance with Cerebras best practices."""

from pathlib import Path

import pytest

from scripts.spec_refinement.workflows.architecture import (
    _build_architecture_proposal_prompt,
    _build_brief_extraction_prompt,
)
from scripts.spec_refinement.workflows.evidence_expansion import _build_evidence_prompt
from scripts.spec_refinement.workflows.library_labeling import _build_label_prompt
from scripts.spec_refinement.workflows.spec_building import _build_gap_prompt, _build_patch_prompt
from scripts.spec_refinement.workflows.summarization import _build_summary_prompt


def _assert_contract_first(prompt: str, agent_name: str) -> None:
    """Assert that contract section appears in first 20 lines."""
    lines = prompt.splitlines()
    contract_keywords = ["OUTPUT CONTRACT", "REQUIRED", "FORBIDDEN", "MUST"]

    first_20 = "\n".join(lines[:20]).upper()
    assert any(kw in first_20 for kw in contract_keywords), (
        f"{agent_name}: Contract section not found in first 20 lines"
    )

    content_keywords = ["INPUT DATA", "CONTENT", "Charter:", "Spec:", "File Content:"]
    contract_end_line = None
    content_start_line = None

    for idx, line in enumerate(lines):
        if any(kw in line.upper() for kw in contract_keywords):
            if contract_end_line is None or idx > contract_end_line:
                contract_end_line = idx
        if any(kw in line for kw in content_keywords):
            if content_start_line is None:
                content_start_line = idx

    if content_start_line is not None and contract_end_line is not None:
        assert contract_end_line < content_start_line, (
            f"{agent_name}: Content section appears before contract section ends"
        )


class TestSummarizationPromptStructure:
    def test_summary_prompt_contract_first(self):
        prompt = _build_summary_prompt("file_001", Path("test.md"), ["INTRO", "REQS"], "content")
        _assert_contract_first(prompt, "glm-file-what-summarizer")


class TestEvidenceExpansionPromptStructure:
    def test_evidence_prompt_contract_first(self):
        prompt = _build_evidence_prompt("lib_001", "charter", "file_001", "summary", ["INTRO"])
        _assert_contract_first(prompt, "glm-library-evidence-mapper")


class TestSpecBuildingPromptStructure:
    def test_patch_prompt_contract_first(self):
        prompt = _build_patch_prompt(
            "lib_001",
            "charter",
            "spec",
            "file_001",
            "content",
            ["INTRO"],
            ["INTRO"],
            ["file_001"],
            None,
        )
        _assert_contract_first(prompt, "glm-library-spec-integrator")

    def test_gap_prompt_contract_first(self):
        prompt = _build_gap_prompt("spec", "file_001", "content", ["INTRO"], ["INTRO"])
        _assert_contract_first(prompt, "chatgpt-evidence-gap-judge")


class TestArchitecturePromptStructure:
    def test_brief_extraction_prompt_contract_first(self):
        prompt = _build_brief_extraction_prompt("lib_001", "charter", "spec")
        _assert_contract_first(prompt, "glm-architecture-brief-extractor")

    def test_architecture_proposal_prompt_contract_first(self):
        prompt = _build_architecture_proposal_prompt({"lib_001": "charter"}, {"lib_001": "spec"}, {})
        _assert_contract_first(prompt, "opus-architecture-proposer")


class TestLibraryLabelingPromptStructure:
    def test_label_prompt_contract_first(self):
        prompt = _build_label_prompt("file_001", "summary")
        _assert_contract_first(prompt, "glm-file-library-labeler")
