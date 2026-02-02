"""Manual QA runner for spec-refinement agent steps."""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.refinement.qa.bad_signatures import scan_known_bad_signatures
from spec_manager.refinement.qa.cases import QA_CASES, PreparedQaCase, qa_fixture_dir
from spec_manager.refinement.workspace import WorkspaceManager

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_FILE_OUTPUT_RE = re.compile(r"see `([^`]+)` for details\\.?$", re.IGNORECASE)


@dataclass(frozen=True)
class AgentExecResult:
    """Result of executing an agent."""

    agent_name: str
    prompt_path: Path
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float


def _read_git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    sha = (result.stdout or "").strip()
    return sha or None


def _run_agent_capture(*, agent_name: str, prompt: str, prompt_path: Path) -> AgentExecResult:
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    cmd = [
        "uv",
        "run",
        "agents",
        agent_name,
        "--file",
        str(prompt_path),
        "--project",
        str(PROJECT_ROOT),
    ]

    started = time.time()
    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    duration_s = time.time() - started

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    return AgentExecResult(
        agent_name=agent_name,
        prompt_path=prompt_path,
        stdout=stdout,
        stderr=stderr,
        exit_code=result.returncode,
        duration_s=duration_s,
    )


def _maybe_read_file_output(stdout: str) -> str | None:
    """Handle runners that write long outputs to a file and print a pointer message."""
    match = _FILE_OUTPUT_RE.search(stdout.strip())
    if not match:
        return None
    rel_path = match.group(1).strip()
    if not rel_path:
        return None

    path = (PROJECT_ROOT / rel_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None

    if not path.exists() or not path.is_file():
        return None

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None

    # Cleanup the known temporary artifact to avoid polluting the repo root.
    if path.name.upper() == "ARCHITECTURE-MAPPING.MD":
        with contextlib.suppress(OSError):
            path.unlink()

    return content


def _qa_session_dir(manager: WorkspaceManager, session_id: str) -> Path:
    return manager.structure.audits_dir / "qa" / session_id


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def _truncate_for_judge(text: str, *, max_chars: int = 12000) -> str:
    if not text:
        return text
    if len(text) <= max_chars:
        return text
    head = text[:9000]
    tail = text[-2000:] if len(text) > 11000 else ""
    return f"{head}\n\n...[truncated]...\n\n{tail}".strip() + "\n"


def _build_judge_prompt(
    *,
    prepared: PreparedQaCase,
    agent_exec: AgentExecResult,
    raw_output: str,
    processed_output: str,
    deterministic_issues: list[dict[str, Any]],
) -> str:
    criteria_lines = "\n".join(f"- {item}" for item in prepared.acceptance_criteria)
    issues_lines = (
        json.dumps(deterministic_issues, indent=2, sort_keys=True) if deterministic_issues else "[]"
    )
    allowlists_text = (
        json.dumps(prepared.allowlists, indent=2, sort_keys=True) if prepared.allowlists else "{}"
    )

    lines = [
        "Evaluate this agent-step QA case against the acceptance criteria.",
        "",
        f"case_id: {prepared.case_id}",
        f"agent_name: {prepared.agent_name}",
        "",
        "## Allowlists / Constraints (JSON)",
        allowlists_text,
        "",
        "## Acceptance Criteria",
        criteria_lines or "- (none)",
        "",
        "## Harness Deterministic Findings (JSON)",
        issues_lines,
        "",
        "## Prompt Sent To Agent Under Test",
        _truncate_for_judge(prepared.prompt.strip()),
        "",
        "## Agent Trace (stderr)",
        _truncate_for_judge(agent_exec.stderr) or "(empty)",
        "",
        "## Agent Output (raw stdout)",
        _truncate_for_judge(raw_output) or "(empty)",
        "",
        "## Agent Output (post-processed, what the workflow would consume)",
        _truncate_for_judge(processed_output) or "(empty)",
        "",
        "Return JSON only.",
    ]

    return "\n".join(str(line) for line in lines if line is not None).strip() + "\n"


def _render_case_report(
    *,
    prepared: PreparedQaCase,
    agent_exec: AgentExecResult,
    processed_output: str,
    deterministic_issues: list[dict[str, Any]],
    judge: dict[str, Any] | None,
) -> str:
    judge_summary = (judge or {}).get("summary", "")
    score = (judge or {}).get("score")
    passed = (judge or {}).get("passed")

    lines: list[str] = []
    lines.extend([f"# QA Case Report: {prepared.case_id}", ""])
    lines.extend([f"Agent: `{prepared.agent_name}`", f"Description: {prepared.description}", ""])
    lines.append("## Result")
    lines.append(f"- exit_code: {agent_exec.exit_code}")
    lines.append(f"- duration_s: {agent_exec.duration_s:.2f}")
    if passed is not None:
        lines.append(f"- judge_passed: {passed}")
    if score is not None:
        lines.append(f"- judge_score: {score}")
    if judge_summary:
        lines.append(f"- judge_summary: {judge_summary}")
    lines.append("")

    lines.append("## Acceptance Criteria")
    for item in prepared.acceptance_criteria:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Deterministic Issues")
    if deterministic_issues:
        for issue in deterministic_issues:
            lines.append(f"- {issue.get('type')}: {issue.get('message')}")
    else:
        lines.append("- None")
    lines.append("")

    if judge:
        lines.append("## Criteria Results")
        criteria = judge.get("criteria") or []
        if isinstance(criteria, list) and criteria:
            for item in criteria:
                if not isinstance(item, dict):
                    continue
                label = item.get("criterion", "")
                passed_flag = item.get("passed")
                evidence = item.get("evidence")
                status = "PASS" if passed_flag else "FAIL"
                if evidence:
                    lines.append(f"- {status}: {label} (evidence: {evidence})")
                else:
                    lines.append(f"- {status}: {label}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Judge Failures")
        failures = judge.get("failures") or []
        if failures:
            for item in failures:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Trace Findings")
        trace = judge.get("trace_findings") or []
        if trace:
            for item in trace:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Likely Root Causes")
        roots = judge.get("likely_root_causes") or []
        if roots:
            for item in roots:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Suggested Fixes")
        fixes = judge.get("suggested_fixes") or []
        if fixes:
            for item in fixes:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines.append("")

    lines.append("## Post-Processed Output (excerpt)")
    excerpt = processed_output.strip().splitlines()
    excerpt_text = "\n".join(excerpt[:80])
    lines.append("```markdown")
    lines.append(excerpt_text)
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def run_qa_case(
    run_id: str,
    case_id: str,
    *,
    force_init: bool = False,
    judge_agent: str = "chatgpt-qa-judge",
) -> dict[str, Any]:
    """Run a single QA case and return the result."""
    case = QA_CASES.get(case_id)
    if case is None:
        raise RuntimeError(f"Unknown QA case: {case_id}")

    manager = WorkspaceManager(run_id=run_id, input_folder=qa_fixture_dir())
    if not manager.is_initialized or force_init:
        issues = manager.initialize(force=force_init)
        if issues:
            raise RuntimeError(f"QA workspace init failed: {issues}")

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = _qa_session_dir(manager, session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    session_meta = {
        "run_id": run_id,
        "session_id": session_id,
        "started_at": datetime.now().isoformat(),
        "git_sha": _read_git_sha(),
        "fixture_dir": str(qa_fixture_dir()),
        "cases": [case_id],
    }
    _write_json(session_dir / "session_meta.json", session_meta)

    manager.cleanup(keep_audits=True)
    prepared = case.prepare(manager)

    result = _run_prepared_case(
        manager=manager,
        session_dir=session_dir,
        prepared=prepared,
        judge_agent=judge_agent,
    )
    _write_json(session_dir / "session_result.json", result)
    return result


def run_qa_suite(
    run_id: str,
    *,
    case_ids: list[str] | None = None,
    force_init: bool = False,
    judge_agent: str = "chatgpt-qa-judge",
) -> dict[str, Any]:
    """Run a suite of QA cases and return the summary."""
    selected_ids = case_ids or list(QA_CASES.keys())

    manager = WorkspaceManager(run_id=run_id, input_folder=qa_fixture_dir())
    if not manager.is_initialized or force_init:
        issues = manager.initialize(force=force_init)
        if issues:
            raise RuntimeError(f"QA workspace init failed: {issues}")

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = _qa_session_dir(manager, session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    session_meta = {
        "run_id": run_id,
        "session_id": session_id,
        "started_at": datetime.now().isoformat(),
        "git_sha": _read_git_sha(),
        "fixture_dir": str(qa_fixture_dir()),
        "cases": selected_ids,
    }
    _write_json(session_dir / "session_meta.json", session_meta)

    case_results: list[dict[str, Any]] = []
    for cid in selected_ids:
        case = QA_CASES.get(cid)
        if case is None:
            case_results.append({"case_id": cid, "error": "unknown_case"})
            continue
        manager.cleanup(keep_audits=True)
        prepared = case.prepare(manager)
        case_results.append(
            _run_prepared_case(
                manager=manager,
                session_dir=session_dir,
                prepared=prepared,
                judge_agent=judge_agent,
            )
        )

    passed = [item for item in case_results if item.get("passed") is True]
    failed = [item for item in case_results if item.get("passed") is False]

    summary = {
        "run_id": run_id,
        "session_id": session_id,
        "cases_total": len(case_results),
        "cases_passed": len(passed),
        "cases_failed": len(failed),
        "results": case_results,
    }
    _write_json(session_dir / "suite_summary.json", summary)
    return summary


def _run_prepared_case(
    *,
    manager: WorkspaceManager,
    session_dir: Path,
    prepared: PreparedQaCase,
    judge_agent: str,
) -> dict[str, Any]:
    case_dir = session_dir / "cases" / prepared.case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = case_dir / "agent_prompt.txt"
    if prepared.agent_name == "none":
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prepared.prompt, encoding="utf-8")
        agent_exec = AgentExecResult(
            agent_name=prepared.agent_name,
            prompt_path=prompt_path,
            stdout=prepared.prompt,
            stderr="",
            exit_code=0,
            duration_s=0.0,
        )
    else:
        agent_exec = _run_agent_capture(
            agent_name=prepared.agent_name,
            prompt=prepared.prompt,
            prompt_path=prompt_path,
        )

    _write_json(case_dir / "agent_exec.json", asdict(agent_exec))
    (case_dir / "agent_stdout.txt").write_text(agent_exec.stdout + "\n", encoding="utf-8")
    (case_dir / "agent_stderr.txt").write_text(agent_exec.stderr + "\n", encoding="utf-8")

    raw_output = agent_exec.stdout
    effective_output = _maybe_read_file_output(raw_output) or raw_output
    (case_dir / "agent_stdout_effective.txt").write_text(effective_output + "\n", encoding="utf-8")

    processed_output = prepared.postprocess(effective_output)
    (case_dir / "agent_output_postprocessed.txt").write_text(
        processed_output + "\n", encoding="utf-8"
    )

    deterministic_issues = prepared.validator(processed_output, manager, prepared.allowlists)
    signature_issues: list[dict[str, Any]] = []
    for kind, text in (
        ("raw", raw_output),
        ("effective", effective_output),
        ("postprocessed", processed_output),
    ):
        for issue in scan_known_bad_signatures(text):
            issue["output_kind"] = kind
            signature_issues.append(issue)
    if signature_issues:
        deterministic_issues.extend(signature_issues)
    _write_json(case_dir / "deterministic_issues.json", deterministic_issues)

    if prepared.agent_name == "none":
        judge_data = None
        _write_json(case_dir / "judge.json", {"skipped": "non_agent_case"})
        passed = len(deterministic_issues) == 0
        score = None
    else:
        judge_prompt = _build_judge_prompt(
            prepared=prepared,
            agent_exec=agent_exec,
            raw_output=raw_output,
            processed_output=processed_output,
            deterministic_issues=deterministic_issues,
        )

        judge_exec = _run_agent_capture(
            agent_name=judge_agent,
            prompt=judge_prompt,
            prompt_path=case_dir / "judge_prompt.txt",
        )
        (case_dir / "judge_stdout.txt").write_text(judge_exec.stdout + "\n", encoding="utf-8")
        (case_dir / "judge_stderr.txt").write_text(judge_exec.stderr + "\n", encoding="utf-8")

        if judge_exec.exit_code == 0 and judge_exec.stdout.strip():
            try:
                judge_data = json.loads(judge_exec.stdout)
            except json.JSONDecodeError:
                judge_data = None
        else:
            judge_data = None

        _write_json(case_dir / "judge.json", judge_data or {"error": "judge_parse_failed"})

        passed = bool(judge_data.get("passed")) if judge_data else False
        score = judge_data.get("score") if judge_data else None

    report = _render_case_report(
        prepared=prepared,
        agent_exec=agent_exec,
        processed_output=processed_output,
        deterministic_issues=deterministic_issues,
        judge=judge_data,
    )
    (case_dir / "report.md").write_text(report, encoding="utf-8")

    record = {
        "run_id": manager.run_id,
        "session_id": session_dir.name,
        "timestamp": datetime.now().isoformat(),
        "git_sha": _read_git_sha(),
        "case_id": prepared.case_id,
        "agent_name": prepared.agent_name,
        "judge_agent": None if prepared.agent_name == "none" else judge_agent,
        "passed": passed,
        "score": score,
        "exit_code": agent_exec.exit_code,
        "duration_s": agent_exec.duration_s,
        "deterministic_issues_count": len(deterministic_issues),
        "report_path": str(case_dir / "report.md"),
    }

    # Append to a global scoreboard (ignored by git).
    _append_jsonl(PROJECT_ROOT / "runs" / "_qa_scoreboard.jsonl", record)

    return record
