from __future__ import annotations

from pathlib import Path

from spec_manager.refinement.qa.contract_lint import (
    lint_agent_prompts,
    lint_pointer_conventions,
    lint_workflow_agent_references,
    run_contract_lint,
)


def _write_prompt(agents_dir: Path, filename: str, content: str) -> Path:
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = agents_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def _write_workflow(workflows_dir: Path, filename: str, content: str) -> Path:
    workflows_dir.mkdir(parents=True, exist_ok=True)
    path = workflows_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def test_linter_flags_legacy_file_id_pattern(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_prompt(agents_dir, "sample.md", "Legacy reference file_001 should be flagged.")

    issues = lint_agent_prompts(agents_dir)

    assert any(
        issue.severity == "error" and issue.message == "Legacy ID pattern found: file_001"
        for issue in issues
    )


def test_linter_flags_legacy_lib_id_pattern(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_prompt(agents_dir, "sample.md", "Legacy reference lib_001 should be flagged.")

    issues = lint_agent_prompts(agents_dir)

    assert any(
        issue.severity == "error" and issue.message == "Legacy ID pattern found: lib_001"
        for issue in issues
    )


def test_linter_detects_missing_required_formats(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_prompt(agents_dir, "sample.md", "No format examples included here.")

    issues = lint_agent_prompts(agents_dir)

    assert any(
        issue.severity == "error" and issue.message == "Prompt missing required ID format examples."
        for issue in issues
    )


def test_linter_passes_after_fixing_prompt(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    content = (
        "Use F0001 for files and LIB-0001 for libraries.\n"
        "Section IDs look like SEC-F0001-0001.\n"
        "Example pointer: [spec_snapshot/requirements.md::SEC-F0001-0001].\n"
    )
    _write_prompt(agents_dir, "sample.md", content)

    issues = lint_agent_prompts(agents_dir)

    assert issues == []


def test_linter_detects_legacy_pointer_only(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_prompt(agents_dir, "sample.md", "Evidence example: [F0001::INTRO].")

    issues = lint_pointer_conventions(agents_dir)

    assert any(
        issue.severity == "warning"
        and issue.message == "Legacy pointer examples without new-format examples."
        for issue in issues
    )


def test_workflow_agent_reference_validation(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    workflows_dir = tmp_path / "workflows"
    _write_workflow(workflows_dir, "workflow.py", 'agent_name = "test-agent"\n')

    issues = lint_workflow_agent_references(workflows_dir, agents_dir)

    assert any(
        issue.severity == "error" and issue.message == "Agent prompt file not found: test-agent.md"
        for issue in issues
    )


def test_run_contract_lint_returns_exit_code_one_on_errors(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    workflows_dir = tmp_path / "workflows"
    _write_prompt(agents_dir, "sample.md", "Legacy reference file_001 should fail.")
    workflows_dir.mkdir(parents=True, exist_ok=True)

    _, exit_code = run_contract_lint(agents_dir, workflows_dir)

    assert exit_code == 1


def test_run_contract_lint_returns_exit_code_zero_when_clean(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    workflows_dir = tmp_path / "workflows"
    prompt_content = (
        "Use F0001 and LIB-0001 identifiers.\n"
        "Section IDs follow SEC-F0001-0001.\n"
        "Evidence pointer: [spec_snapshot/requirements.md::SEC-F0001-0001].\n"
    )
    _write_prompt(agents_dir, "test-agent.md", prompt_content)
    _write_workflow(workflows_dir, "workflow.py", 'agent_name = "test-agent"\n')

    _, exit_code = run_contract_lint(agents_dir, workflows_dir)

    assert exit_code == 0
