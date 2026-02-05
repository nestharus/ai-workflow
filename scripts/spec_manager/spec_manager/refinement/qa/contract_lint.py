"""Contract linting for spec-refinement agent prompts and workflows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec_manager.compliance.evidence_field_lint import (
    scan_for_forbidden_output_signatures,
)
from spec_manager.compliance.hardcoding_scanner import scan_for_hardcoding_violations
from spec_manager.refinement.formats import EVIDENCE_POINTER_RE, parse_evidence_pointer
from spec_manager.refinement.validation_utils import SECTION_ID_RE
from spec_manager.schemas.evidence_ranges import EVID_CITATION_PATTERN

PROJECT_ROOT = Path(__file__).resolve().parents[5]

# Per CON-0021: EVID citation pattern for evidence fields
EVID_FIELD_PATTERN = re.compile(r"^EVID-F\d{4}-R\d{4}-L\d+-L\d+$")

LEGACY_FILE_ID_RE = re.compile(r"\bfile_\d+\b")
LEGACY_LIB_ID_RE = re.compile(r"\blib_\d+\b")
FILE_ID_RE = re.compile(r"F\d{4}")
LIB_ID_RE = re.compile(r"LIB-\d{4}")
SECTION_ID_REQUIRED_RE = re.compile(r"SEC-F\d{4}-\d{4}")
PREFERRED_POINTER_RE = re.compile(r"\[spec_snapshot/[^]]+::SEC-F\d{4}-\d{4}\]")

JSON_ONLY_RE = re.compile(r"\bjson only\b", re.IGNORECASE)
PROSE_REQUIREMENT_RE = re.compile(
    r"\b(explain|explanation|analysis|reasoning|summary|summarize|markdown|bullet|bulleted|prose|"
    r"narrative|paragraph)\b",
    re.IGNORECASE,
)
PROSE_TRIGGER_RE = re.compile(r"\b(include|provide|add|give|write|return|output)\b", re.IGNORECASE)

DERIVED_POINTER_PROHIBITION_RE = re.compile(
    r"(do not|don't|never|avoid|forbid|forbidden)[^\n]{0,120}"
    r"(\[?LIB-\d{4}|library pointer|derived pointer)",
    re.IGNORECASE,
)

MULTI_HOP_CONTEXT_RE = re.compile(r"\b(library|derived|charter)\b", re.IGNORECASE)
MULTI_HOP_FORBID_RE = re.compile(
    r"(do not|don't|never|avoid|forbid|forbidden)[^\n]{0,120}"
    r"(multi[- ]?hop|library pointer|lib pointer|\[?LIB-\d{4})",
    re.IGNORECASE,
)

_REPORT_TIMESTAMP: str | None = None


@dataclass(frozen=True)
class LintIssue:
    """Represents a contract lint finding."""

    severity: str
    file: str
    line: int | None
    message: str
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the issue for JSON reports."""
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "hint": self.hint,
        }


def lint_agent_prompts(agents_dir: Path) -> list[LintIssue]:
    """Lint agent prompt files for legacy patterns and contract compliance."""
    issues: list[LintIssue] = []
    for prompt_path in _iter_files(agents_dir, "*.md"):
        rel_path = _relative_path(prompt_path)
        try:
            content = prompt_path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(
                LintIssue(
                    severity="error",
                    file=rel_path,
                    line=None,
                    message=f"Failed to read prompt: {exc}",
                    hint="Check file permissions or encoding.",
                )
            )
            continue

        lines = content.splitlines()
        for line_no, line in enumerate(lines, start=1):
            for match in LEGACY_FILE_ID_RE.finditer(line):
                issues.append(
                    LintIssue(
                        severity="error",
                        file=rel_path,
                        line=line_no,
                        message=f"Legacy ID pattern found: {match.group(0)}",
                        hint="Replace with current format (F#### or LIB-####).",
                    )
                )
            for match in LEGACY_LIB_ID_RE.finditer(line):
                issues.append(
                    LintIssue(
                        severity="error",
                        file=rel_path,
                        line=line_no,
                        message=f"Legacy ID pattern found: {match.group(0)}",
                        hint="Replace with current format (F#### or LIB-####).",
                    )
                )
            if DERIVED_POINTER_PROHIBITION_RE.search(line):
                issues.append(
                    LintIssue(
                        severity="error",
                        file=rel_path,
                        line=line_no,
                        message="Prompt forbids derived pointers like [LIB-####::...].",
                        hint="Allow derived/library pointers when they are needed.",
                    )
                )

        missing_required = _required_format_missing(content)
        if missing_required:
            section_hint = _section_id_hint(content)
            hint = (
                "Add examples showing F####, LIB-####, SEC-F####-####, and "
                "[spec_snapshot/<relpath>::SEC-F####-####]."
            )
            if section_hint:
                hint = f"{hint} {section_hint}"
            issues.append(
                LintIssue(
                    severity="error",
                    file=rel_path,
                    line=None,
                    message="Prompt missing required ID format examples.",
                    hint=hint,
                )
            )

        if _has_json_only_contract(lines):
            issues.extend(_lint_json_only_prose(rel_path, lines))

    return issues


def lint_workflow_agent_references(workflows_dir: Path, agents_dir: Path) -> list[LintIssue]:
    """Ensure workflow agent references have matching prompt files."""
    issues: list[LintIssue] = []
    for workflow_path in _iter_files(workflows_dir, "*.py"):
        rel_path = _relative_path(workflow_path)
        try:
            lines = workflow_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            issues.append(
                LintIssue(
                    severity="error",
                    file=rel_path,
                    line=None,
                    message=f"Failed to read workflow: {exc}",
                    hint="Check file permissions or encoding.",
                )
            )
            continue

        for line_no, line in enumerate(lines, start=1):
            for match in re.finditer(r'agent_name\s*=\s*["\']([^"\']+)["\']', line):
                agent_name = match.group(1)
                prompt_path = agents_dir / f"{agent_name}.md"
                if not prompt_path.exists():
                    issues.append(
                        LintIssue(
                            severity="error",
                            file=rel_path,
                            line=line_no,
                            message=f"Agent prompt file not found: {agent_name}.md",
                            hint=(
                                f"Create .agents/agents/{agent_name}.md "
                                f"or fix agent name reference."
                            ),
                        )
                    )

    return issues


def lint_pointer_conventions(agents_dir: Path) -> list[LintIssue]:
    """Lint pointer format conventions inside agent prompts."""
    issues: list[LintIssue] = []
    for prompt_path in _iter_files(agents_dir, "*.md"):
        rel_path = _relative_path(prompt_path)
        try:
            content = prompt_path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(
                LintIssue(
                    severity="error",
                    file=rel_path,
                    line=None,
                    message=f"Failed to read prompt: {exc}",
                    hint="Check file permissions or encoding.",
                )
            )
            continue

        missing_required = _required_format_missing(content)
        if missing_required:
            section_hint = _section_id_hint(content)
            hint = (
                "Add examples showing F####, LIB-####, SEC-F####-####, and "
                "[spec_snapshot/<relpath>::SEC-F####-####]."
            )
            if section_hint:
                hint = f"{hint} {section_hint}"
            issues.append(
                LintIssue(
                    severity="error",
                    file=rel_path,
                    line=None,
                    message="Prompt missing required ID/pointer format examples.",
                    hint=hint,
                )
            )

        lines = content.splitlines()
        has_new = False
        has_legacy = False
        legacy_line: int | None = None
        for line_no, line in enumerate(lines, start=1):
            for match in EVIDENCE_POINTER_RE.finditer(line):
                parsed = parse_evidence_pointer(match.group(0))
                if not parsed:
                    continue
                if parsed["format"] == "new":
                    has_new = True
                elif parsed["format"] == "legacy":
                    has_legacy = True
                    if legacy_line is None:
                        legacy_line = line_no

        if has_legacy and not has_new:
            issues.append(
                LintIssue(
                    severity="warning",
                    file=rel_path,
                    line=legacy_line,
                    message="Legacy pointer examples without new-format examples.",
                    hint="Add [spec_snapshot/<relpath>::SEC-F####-####] examples.",
                )
            )

        if MULTI_HOP_CONTEXT_RE.search(content):
            for line_no, line in enumerate(lines, start=1):
                if MULTI_HOP_FORBID_RE.search(line):
                    issues.append(
                        LintIssue(
                            severity="error",
                            file=rel_path,
                            line=line_no,
                            message="Prompt forbids multi-hop pointers but likely requires them.",
                            hint="Allow [LIB-####::...] or derived pointers when needed.",
                        )
                    )
                    break

    return issues


def lint_evid_compliance(agents_dir: Path) -> list[LintIssue]:
    """Lint agent prompts for EVID-only compliance (CON-0021).

    Evidence-producing agent prompts should:
    1. Document the EVID citation format
    2. Show examples of valid EVID citations
    3. Not include legacy citation examples in evidence contexts

    Args:
        agents_dir: Directory containing agent prompt files

    Returns:
        List of lint issues
    """
    issues: list[LintIssue] = []

    # Evidence-producing agent prompts that should document EVID format
    evidence_producing_agents = {
        "glm-library-evidence-mapper",
        "glm-library-spec-integrator",
        "chatgpt-evidence-gap-judge",
        "chatgpt-concern-assignment-judge",
        "chatgpt-patch-repairer",
        "chatgpt-task-plan-judge",
        "opus-task-planner",
    }

    for prompt_path in _iter_files(agents_dir, "*.md"):
        rel_path = _relative_path(prompt_path)
        agent_name = prompt_path.stem

        try:
            content = prompt_path.read_text(encoding="utf-8")
        except OSError:
            continue

        # Check evidence-producing agents for EVID documentation
        if agent_name in evidence_producing_agents:
            has_evid_example = bool(EVID_CITATION_PATTERN.search(content))
            has_evid_format_doc = "EVID-F" in content and "L#-L#" in content

            if not has_evid_example and not has_evid_format_doc:
                issues.append(
                    LintIssue(
                        severity="warning",
                        file=rel_path,
                        line=None,
                        message="Evidence-producing prompt missing EVID format examples.",
                        hint="Add EVID citation format: [EVID-F####-R####-L#-L#]",
                    )
                )

        # Scan for forbidden output signatures in all prompts
        errors, _warnings = scan_for_forbidden_output_signatures(content, rel_path)
        for error in errors:
            issues.append(
                LintIssue(
                    severity="warning",  # Downgrade to warning for prompts
                    file=rel_path,
                    line=None,
                    message=f"[CON-0021] {error}",
                    hint="Use EVID format for evidence citations.",
                )
            )

    return issues


def generate_json_report(issues: list[LintIssue]) -> dict[str, Any]:
    """Generate a JSON-friendly report payload."""
    summary = _summarize_issues(issues)
    return {
        "timestamp": _report_timestamp(),
        "summary": summary,
        "issues": [issue.to_dict() for issue in issues],
    }


def generate_markdown_report(issues: list[LintIssue]) -> str:
    """Generate a Markdown report for contract lint issues."""
    summary = _summarize_issues(issues)
    lines: list[str] = []
    lines.append("# Contract Lint Report")
    lines.append("")
    lines.append(f"Generated: {_report_timestamp()}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total Issues: {summary['total']}")
    lines.append(f"- Errors: {summary['error']}")
    lines.append(f"- Warnings: {summary['warning']}")
    lines.append(f"- Info: {summary['info']}")
    lines.append("")
    lines.append("## Issues by File")

    if not issues:
        lines.append("")
        lines.append("- None")
        lines.append("")
        return "\n".join(lines)

    grouped = _group_by_file(issues)
    for file_path in sorted(grouped.keys()):
        lines.append("")
        lines.append(f"### {file_path}")
        lines.append("")
        for issue in _sort_issues(grouped[file_path]):
            line_label = f"Line {issue.line}" if issue.line is not None else "Line N/A"
            severity = issue.severity.upper()
            lines.append(f"**{line_label}** [{severity}]: {issue.message}")
            if issue.hint:
                lines.append(f"> Hint: {issue.hint}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run_contract_lint(
    agents_dir: Path,
    workflows_dir: Path,
    output_dir: Path | None = None,
    *,
    scan_source_dirs: list[Path] | None = None,
) -> tuple[list[LintIssue], int]:
    """Run all contract lint checks and optionally write reports.

    Args:
        agents_dir: Directory containing agent prompt files.
        workflows_dir: Directory containing workflow Python files.
        output_dir: Optional directory to write reports to.
        scan_source_dirs: Optional list of directories to scan for hardcoding violations.
            If not provided, scans the spec_manager source directory.

    Returns:
        Tuple of (list of issues, exit code).
        Exit code is 1 if any errors found, 0 otherwise.
        Note: hardcoding scanner findings are warnings only (report-only mode).
    """
    issues: list[LintIssue] = []
    issues.extend(lint_agent_prompts(agents_dir))
    issues.extend(lint_workflow_agent_references(workflows_dir, agents_dir))
    issues.extend(lint_pointer_conventions(agents_dir))
    issues.extend(lint_evid_compliance(agents_dir))  # CON-0021 enforcement

    # Add hardcoding scanner (report-only mode - warnings only)
    if scan_source_dirs is None:
        # Default: scan spec_manager source directory
        spec_manager_src = PROJECT_ROOT / "scripts" / "spec_manager" / "spec_manager"
        scan_source_dirs = [spec_manager_src] if spec_manager_src.exists() else []

    for source_dir in scan_source_dirs:
        if source_dir.exists() and source_dir.is_dir():
            source_files = list(source_dir.rglob("*.py"))
            hardcoding_findings = scan_for_hardcoding_violations(source_files)
            for finding in hardcoding_findings:
                # Make path relative for cleaner output
                try:
                    rel_path = str(Path(finding.file).relative_to(PROJECT_ROOT))
                except ValueError:
                    rel_path = finding.file
                issues.append(
                    LintIssue(
                        severity="warning",  # Report-only: warnings not errors
                        file=rel_path,
                        line=finding.line,
                        message=f"[CON-0003] {finding.message}",
                        hint="Consider using LLM-driven semantics instead of hardcoded patterns.",
                    )
                )

    issues = _sort_issues(issues)
    exit_code = 1 if any(issue.severity == "error" for issue in issues) else 0

    global _REPORT_TIMESTAMP
    _REPORT_TIMESTAMP = _iso_timestamp()
    try:
        json_report = generate_json_report(issues)
        markdown_report = generate_markdown_report(issues)
    finally:
        _REPORT_TIMESTAMP = None

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "contract_lint.json").write_text(
            json.dumps(json_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output_dir / "contract_lint.md").write_text(markdown_report, encoding="utf-8")

    return issues, exit_code


def _iter_files(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob(pattern) if path.is_file())


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _required_format_missing(content: str) -> bool:
    return bool(
        not FILE_ID_RE.search(content)
        or not LIB_ID_RE.search(content)
        or not SECTION_ID_REQUIRED_RE.search(content)
        or not PREFERRED_POINTER_RE.search(content)
    )


def _has_json_only_contract(lines: list[str]) -> bool:
    return any(JSON_ONLY_RE.search(line) for line in lines)


def _lint_json_only_prose(file_path: str, lines: list[str]) -> list[LintIssue]:
    issues: list[LintIssue] = []
    in_code_block = False
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if "json" in stripped.lower():
            continue
        if PROSE_REQUIREMENT_RE.search(line) and PROSE_TRIGGER_RE.search(line):
            issues.append(
                LintIssue(
                    severity="error",
                    file=file_path,
                    line=line_no,
                    message="JSON-only contract includes additional prose requirements.",
                    hint="Remove the prose requirement or relax the JSON-only rule.",
                )
            )
    return issues


def _summarize_issues(issues: list[LintIssue]) -> dict[str, int]:
    summary = {"total": len(issues), "error": 0, "warning": 0, "info": 0}
    for issue in issues:
        if issue.severity in summary:
            summary[issue.severity] += 1
    return summary


def _group_by_file(issues: list[LintIssue]) -> dict[str, list[LintIssue]]:
    grouped: dict[str, list[LintIssue]] = {}
    for issue in issues:
        grouped.setdefault(issue.file, []).append(issue)
    return grouped


def _sort_issues(issues: list[LintIssue]) -> list[LintIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            issue.file,
            issue.line is None,
            issue.line or 0,
            issue.severity,
            issue.message,
        ),
    )


def _iso_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _report_timestamp() -> str:
    return _REPORT_TIMESTAMP or _iso_timestamp()


def _section_id_hint(content: str) -> str | None:
    if SECTION_ID_RE.search(content) and not SECTION_ID_REQUIRED_RE.search(content):
        return "Use SEC-F####-#### section IDs for examples."
    return None
