"""Task implementation workflow utilities.

This module provides utilities for executing tasks in the implementation phase,
including building context bundles, generating patches, applying patches, and
auditing results.
"""

import json
import logging
import re
import shlex
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.repair import ArtifactType, get_repair_model, repair_artifact
from spec_manager.refinement.workflows.patch_utils import (
    IMMUTABLE_PATH_PATTERNS,
    apply_patch,
    validate_patch,
)
from spec_manager.refinement.workspace import Phase, WorkspaceManager
from spec_manager.schemas import (
    DecisionsIndex,
    PatchGraphSchema,
    PatchOutputSchema,
    SpecIndex,
    TaskImplementationStatusSchema,
    TaskSchema,
    TestResultSchema,
    read_patch_graph_json,
    write_task_implementation_status_json,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImplementationConfig:
    """Configuration for task implementation execution."""

    run_tests: bool = True
    test_command: str | None = None
    run_lint: bool = False
    lint_command: str | None = None
    allow_test_repair: bool = True


def _read_test_command_from_pyproject(repo_root: Path) -> str | None:
    # NOTE: This function is Python-specific — reads pyproject.toml for a
    # custom test command.  See core.language.DEFAULT_TEST_COMMAND for the
    # language-agnostic default.
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Failed to read pyproject.toml for test command: %s", exc)
        return None
    except tomllib.TOMLDecodeError as exc:  # type: ignore[attr-defined]
        logger.warning("Failed to parse pyproject.toml for test command: %s", exc)
        return None

    tool_config = payload.get("tool")
    if not isinstance(tool_config, dict):
        return None
    spec_config = tool_config.get("spec_manager")
    if not isinstance(spec_config, dict):
        return None
    command = spec_config.get("test_command")
    if isinstance(command, str) and command.strip():
        return command.strip()
    return None


def _format_command_output(
    *,
    started_at: datetime,
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int | None = None,
    duration_s: float | None = None,
) -> str:
    lines = [
        f"timestamp: {started_at.isoformat()}",
        f"command: {command}",
    ]
    if exit_code is not None:
        lines.append(f"exit_code: {exit_code}")
    if duration_s is not None:
        lines.append(f"duration_s: {duration_s:.3f}")
    lines.append("")
    lines.append("stdout:")
    lines.append(stdout)
    lines.append("")
    lines.append("stderr:")
    lines.append(stderr)
    lines.append("")
    return "\n".join(lines)


def run_tests(
    task_dir: Path,
    repo_root: Path,
    test_command: str | None = None,
    run_tests_flag: bool = True,
) -> TestResultSchema | None:
    if not run_tests_flag:
        return None

    # NOTE: The "uv run" prefix is Python-specific (uv package manager).
    # The fallback test command is derived from core.language.DEFAULT_TEST_COMMAND.
    from spec_manager.core.language import DEFAULT_TEST_COMMAND

    _default_cmd = "uv run " + " ".join(DEFAULT_TEST_COMMAND)
    effective_command = test_command or _read_test_command_from_pyproject(repo_root) or _default_cmd
    cmd = shlex.split(effective_command)
    output_path = task_dir / "test_output.txt"
    started_at = datetime.now()

    logger.info("Running tests (command=%s).", effective_command)
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        duration_s = time.perf_counter() - start
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        output_path.write_text(
            _format_command_output(
                started_at=started_at,
                command=effective_command,
                stdout=stdout,
                stderr=stderr,
                exit_code=result.returncode,
                duration_s=duration_s,
            ),
            encoding="utf-8",
        )
        finished_at = datetime.now()
        logger.info(
            "Tests completed (exit_code=%d, duration_s=%.2f).",
            result.returncode,
            duration_s,
        )
        return TestResultSchema(
            ran=True,
            command=effective_command,
            exit_code=result.returncode,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_s=round(duration_s, 3),
        )
    except OSError as exc:
        duration_s = time.perf_counter() - start
        error_text = f"Test command failed to execute: {exc}"
        output_path.write_text(
            _format_command_output(
                started_at=started_at,
                command=effective_command,
                stdout="",
                stderr=error_text,
                exit_code=-1,
                duration_s=duration_s,
            ),
            encoding="utf-8",
        )
        finished_at = datetime.now()
        logger.exception("Test execution failed (command=%s).", effective_command)
        return TestResultSchema(
            ran=True,
            command=f"{effective_command} (error: {exc})",
            exit_code=-1,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_s=round(duration_s, 3),
        )


def run_lint(
    task_dir: Path,
    repo_root: Path,
    lint_command: str | None = None,
    run_lint_flag: bool = False,
) -> dict[str, Any] | None:
    if not run_lint_flag:
        return None

    effective_command = lint_command or "uv run lint"
    cmd = shlex.split(effective_command)
    output_path = task_dir / "lint_output.txt"
    started_at = datetime.now()

    logger.info("Running lint (command=%s).", effective_command)
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        duration_s = time.perf_counter() - start
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        output_path.write_text(
            _format_command_output(
                started_at=started_at,
                command=effective_command,
                stdout=stdout,
                stderr=stderr,
                exit_code=result.returncode,
                duration_s=duration_s,
            ),
            encoding="utf-8",
        )
        logger.info(
            "Lint completed (exit_code=%d, duration_s=%.2f).",
            result.returncode,
            duration_s,
        )
        return {
            "ran": True,
            "command": effective_command,
            "exit_code": result.returncode,
            "passed": result.returncode == 0,
        }
    except OSError as exc:
        duration_s = time.perf_counter() - start
        error_text = f"Lint command failed to execute: {exc}"
        output_path.write_text(
            _format_command_output(
                started_at=started_at,
                command=effective_command,
                stdout="",
                stderr=error_text,
                exit_code=-1,
                duration_s=duration_s,
            ),
            encoding="utf-8",
        )
        logger.exception("Lint execution failed (command=%s).", effective_command)
        return {
            "ran": True,
            "command": f"{effective_command} (error: {exc})",
            "exit_code": -1,
            "passed": False,
        }


def _load_spec_index_for_lib(run_root: Path, lib_id: str) -> SpecIndex | None:
    spec_index_path = run_root / "spec_snapshot" / "libraries" / lib_id / "spec_index.json"
    if not spec_index_path.exists():
        logger.warning("spec_index.json not found for %s", lib_id)
        return None
    try:
        payload = json.loads(spec_index_path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Failed to read spec_index.json for %s: %s", lib_id, exc)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Invalid spec_index.json for %s: %s", lib_id, exc)
        return None
    try:
        return SpecIndex.model_validate(payload)
    except Exception as exc:
        logger.warning("Spec index validation failed for %s: %s", lib_id, exc)
        return None


def _load_decisions_index_for_lib(run_root: Path, lib_id: str) -> DecisionsIndex | None:
    decisions_index_path = (
        run_root / "spec_snapshot" / "libraries" / lib_id / "decisions_index.json"
    )
    if not decisions_index_path.exists():
        return None
    try:
        payload = json.loads(decisions_index_path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Failed to read decisions_index.json for %s: %s", lib_id, exc)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Invalid decisions_index.json for %s: %s", lib_id, exc)
        return None
    try:
        return DecisionsIndex.model_validate(payload)
    except Exception as exc:
        logger.warning("Decisions index validation failed for %s: %s", lib_id, exc)
        return None


def _extract_lib_id_from_element(element_id: str) -> str:
    match = re.search(r"LIB-\d{4}", element_id)
    return match.group(0) if match else "unknown"


def _extract_lib_ids_from_edge(edge_id: str) -> tuple[str, str]:
    parts = edge_id.split("-")
    if len(parts) < 5:
        return ("unknown", "unknown")
    return (f"{parts[1]}-{parts[2]}", f"{parts[3]}-{parts[4]}")


def _read_spec_md_for_lib(run_root: Path, lib_id: str) -> str | None:
    spec_md_path = run_root / "spec_snapshot" / "libraries" / lib_id / "spec.md"
    if not spec_md_path.exists():
        return None
    try:
        return spec_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read spec.md for %s: %s", lib_id, exc)
        return None


def _extract_snippet_from_spec_md(spec_content: str, element_id: str) -> str | None:
    lines = spec_content.splitlines()
    current_section = ""
    anchor_re = re.compile(rf"^\s*[-*]\s*{re.escape(element_id)}\s*:")

    for i, line in enumerate(lines):
        section_match = re.match(r"^##\s+(.+)$", line)
        if section_match:
            current_section = section_match.group(1).strip()
            continue

        if not anchor_re.match(line):
            continue

        text = re.sub(r"^\s*[-*]\s*(?:REQ|FLOW|INV)-LIB-\d{4}-\d+:\s*", "", line).strip()

        sub_lines: list[str] = []
        for j in range(i + 1, len(lines)):
            next_line = lines[j]
            if not next_line.strip():
                break
            if re.match(r"^\s{2,}[-*]\s+", next_line):
                sub_lines.append(next_line.strip())
            else:
                break

        section_label = current_section if current_section else "Unknown"
        snippet = f"**{element_id}** ({section_label}): {text}"
        if sub_lines:
            snippet += "\n" + "\n".join(f"  {sl}" for sl in sub_lines)
        return snippet

    return None


def _gather_element_snippets(run_root: Path, element_ids: list[str]) -> dict[str, str]:
    snippets: dict[str, str] = {}
    grouped: dict[str, list[str]] = {}
    for element_id in element_ids:
        lib_id = _extract_lib_id_from_element(element_id)
        grouped.setdefault(lib_id, []).append(element_id)

    for lib_id, ids in grouped.items():
        if lib_id == "unknown":
            for element_id in ids:
                logger.warning("Unable to parse library ID from element %s", element_id)
                snippets[element_id] = f"**{element_id}**: [Element not found]"
            continue

        spec_content = _read_spec_md_for_lib(run_root, lib_id)
        remaining_ids: list[str] = []

        if spec_content is not None:
            for element_id in ids:
                snippet = _extract_snippet_from_spec_md(spec_content, element_id)
                if snippet is not None:
                    snippets[element_id] = snippet
                else:
                    remaining_ids.append(element_id)
        else:
            remaining_ids = list(ids)

        if not remaining_ids:
            continue

        spec_index = _load_spec_index_for_lib(run_root, lib_id)
        if spec_index is None:
            for element_id in remaining_ids:
                logger.warning("Spec index missing for %s when looking up %s", lib_id, element_id)
                snippets[element_id] = f"**{element_id}**: [Element not found]"
            continue
        lookup = {element.element_id: element for element in spec_index.elements}
        for element_id in remaining_ids:
            element = lookup.get(element_id)
            if element is None:
                logger.warning("Element %s not found in spec index for %s", element_id, lib_id)
                snippets[element_id] = f"**{element_id}**: [Element not found]"
                continue
            snippets[element_id] = f"**{element.element_id}** ({element.kind}): {element.text}"

    return snippets


def _gather_decision_snippets(run_root: Path, decision_ids: list[str]) -> dict[str, str]:
    snippets: dict[str, str] = {}
    grouped: dict[str, list[str]] = {}
    for decision_id in decision_ids:
        lib_id = _extract_lib_id_from_element(decision_id)
        grouped.setdefault(lib_id, []).append(decision_id)

    for lib_id, ids in grouped.items():
        if lib_id == "unknown":
            for decision_id in ids:
                logger.warning("Unable to parse library ID from decision %s", decision_id)
                snippets[decision_id] = f"**{decision_id}**: [Decision not found]"
            continue
        decisions_index = _load_decisions_index_for_lib(run_root, lib_id)
        if decisions_index is None:
            for decision_id in ids:
                logger.warning(
                    "Decisions index missing for %s when looking up %s", lib_id, decision_id
                )
                snippets[decision_id] = f"**{decision_id}**: [Decision not found]"
            continue
        lookup = {decision.decision_id: decision for decision in decisions_index.decisions}
        for decision_id in ids:
            decision = lookup.get(decision_id)
            if decision is None:
                logger.warning(
                    "Decision %s not found in decisions index for %s", decision_id, lib_id
                )
                snippets[decision_id] = f"**{decision_id}**: [Decision not found]"
                continue
            context = decision.context or "N/A"
            snippets[decision_id] = (
                f"**{decision.decision_id}** ({decision.status}): {decision.question}\n"
                f"Context: {context}"
            )

    return snippets


def _format_interface_contract_json(edge_id: str, payload: object) -> str:
    summary_lines = [f"**{edge_id}** (json)"]
    if isinstance(payload, dict):
        for key in sorted(payload.keys()):
            value = payload[key]
            rendered = json.dumps(value, ensure_ascii=True)
            summary_lines.append(f"- {key}: {rendered}")
    else:
        summary_lines.append(f"- content: {json.dumps(payload, ensure_ascii=True)}")
    return "\n".join(summary_lines)


def _gather_interface_contracts(run_root: Path, edge_ids: list[str]) -> dict[str, str]:
    contracts: dict[str, str] = {}
    for edge_id in edge_ids:
        consumer_lib, _provider_lib = _extract_lib_ids_from_edge(edge_id)
        if consumer_lib == "unknown":
            logger.warning("Unable to parse library IDs from edge %s", edge_id)
            contracts[edge_id] = f"**{edge_id}**: [Interface contract not found]"
            continue
        interface_dir = run_root / "spec_snapshot" / "libraries" / consumer_lib / "interfaces"
        markdown_path = interface_dir / f"{edge_id}.md"
        content: str | None = None
        if markdown_path.exists():
            try:
                content = markdown_path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("Failed to read interface contract %s: %s", markdown_path, exc)
                content = f"**{edge_id}**: [Error reading interface contract]"
        else:
            json_path = interface_dir / f"{edge_id}.json"
            if json_path.exists():
                try:
                    payload = json.loads(json_path.read_text(encoding="utf-8"))
                except OSError as exc:
                    logger.warning("Failed to read interface contract %s: %s", json_path, exc)
                    content = f"**{edge_id}**: [Error reading interface contract]"
                except json.JSONDecodeError as exc:
                    logger.warning("Invalid interface contract %s: %s", json_path, exc)
                    content = f"**{edge_id}**: [Error reading interface contract]"
                else:
                    content = _format_interface_contract_json(edge_id, payload)
            else:
                logger.warning("Interface contract not found for edge %s", edge_id)
                content = f"**{edge_id}**: [Interface contract not found]"

        if content is None:
            content = f"**{edge_id}**: [Interface contract not found]"
        if len(content) > 2000:
            content = f"{content[:2000]}...[truncated]"
        contracts[edge_id] = content

    return contracts


def _read_file_with_limit(file_path: Path, max_chars: int = 5000) -> str:
    if not file_path.exists():
        return f"[Missing file: {file_path}]"
    try:
        total_size = file_path.stat().st_size
    except OSError as exc:
        return f"[Error reading file: {exc}]"
    try:
        with file_path.open("rb") as handle:
            probe = handle.read(min(total_size, 8192))
    except OSError as exc:
        return f"[Error reading file: {exc}]"
    if b"\x00" in probe:
        return f"[Binary file: {file_path.name}]"
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"[Binary file: {file_path.name}]"
    except OSError as exc:
        return f"[Error reading file: {exc}]"
    if len(text) <= max_chars:
        return text
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    head_budget = max_chars // 2
    tail_budget = max_chars - head_budget
    head_chars = 0
    head_end = 0
    for i, line in enumerate(lines):
        if head_chars + len(line) > head_budget and head_end > 0:
            break
        head_chars += len(line)
        head_end = i + 1
    tail_chars = 0
    tail_start = total_lines
    for i in range(total_lines - 1, head_end - 1, -1):
        if tail_chars + len(lines[i]) > tail_budget and tail_start < total_lines:
            break
        tail_chars += len(lines[i])
        tail_start = i
    if tail_start <= head_end:
        head_text = "".join(lines[:head_end]).rstrip("\n")
        return (
            f"{head_text}\n\n"
            f"...[File truncated: showing lines 1\u2013{head_end} of {total_lines} "
            f"total lines ({len(text)} characters)]"
        )
    head_text = "".join(lines[:head_end]).rstrip("\n")
    tail_text = "".join(lines[tail_start:]).rstrip("\n")
    omitted_count = tail_start - head_end
    return (
        f"{head_text}\n\n"
        f"...[Lines {head_end + 1}\u2013{tail_start} omitted ({omitted_count} lines)]\n\n"
        f"{tail_text}\n\n"
        f"...[File truncated: showing lines 1\u2013{head_end} and "
        f"{tail_start + 1}\u2013{total_lines} of {total_lines} total lines "
        f"({len(text)} characters)]"
    )


def _gather_suggested_files_content(repo_root: Path, suggested_files: list[str]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for file_path in suggested_files:
        resolved_path = repo_root / file_path
        contents[file_path] = _read_file_with_limit(resolved_path, max_chars=5000)
    return contents


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _truncate_section(content: str, max_chars: int, section_name: str) -> str:
    if len(content) <= max_chars:
        return content
    estimated_tokens = _estimate_tokens(content)
    truncated = content[:max_chars]
    return (
        f"{truncated}\n\n...[{section_name} truncated: showing {max_chars} of {len(content)} "
        f"characters (~{estimated_tokens} tokens)]"
    )


def build_context_bundle(run_root: Path, task_id: str, repo_root: Path) -> str:
    """Build context bundle for a task.

    Args:
        run_root: Root directory for the run.
        task_id: Task identifier.
        repo_root: Repository root directory.

    Returns:
        Context bundle content as a string.
    """
    task_path = run_root / "tasks" / task_id / "task.json"
    task = TaskSchema.model_validate_json(task_path.read_text(encoding="utf-8"))

    element_snippets = _gather_element_snippets(run_root, task.covers.elements)
    decision_snippets = _gather_decision_snippets(run_root, task.covers.decisions)
    interface_contracts = _gather_interface_contracts(run_root, task.covers.edges)
    file_contents = _gather_suggested_files_content(repo_root, task.suggested_files)

    acceptance_criteria = (
        "\n".join(
            f"{index + 1}. {criterion}" for index, criterion in enumerate(task.acceptance_criteria)
        )
        if task.acceptance_criteria
        else "None"
    )

    section_1_lines = [
        "# Task Requirements",
        "",
        "## Task ID",
        task.task_id,
        "",
        "## Title",
        task.title,
        "",
        "## Description",
        task.description,
        "",
        "## Priority",
        task.priority,
        "",
        "## Component",
        task.component,
        "",
        "## Libraries",
        ", ".join(task.libraries) if task.libraries else "None",
        "",
        "## Acceptance Criteria",
        acceptance_criteria,
        "",
        "## Risk Notes",
        task.risk_notes or "None",
        "",
        "## Validation Notes",
        task.validation_notes or "None",
    ]
    section_1 = "\n".join(section_1_lines)

    section_2_lines = ["# Relevant Specs / Interfaces", "", "## Covered Elements"]
    if task.covers.elements:
        for element_id in task.covers.elements:
            section_2_lines.append(
                element_snippets.get(element_id, f"**{element_id}**: [Element not found]")
            )
    else:
        section_2_lines.append("None")

    section_2_lines.extend(["", "## Covered Decisions"])
    if task.covers.decisions:
        for decision_id in task.covers.decisions:
            section_2_lines.append(
                decision_snippets.get(decision_id, f"**{decision_id}**: [Decision not found]")
            )
    else:
        section_2_lines.append("None")

    section_2_lines.extend(["", "## Interface Contracts"])
    if task.covers.edges:
        for edge_id in task.covers.edges:
            section_2_lines.append(
                interface_contracts.get(edge_id, f"**{edge_id}**: [Interface contract not found]")
            )
    else:
        section_2_lines.append("None")

    section_2_lines.extend(["", "## Citations"])
    if task.citations:
        section_2_lines.extend(f"- {citation}" for citation in task.citations)
    else:
        section_2_lines.append("None")

    section_2 = "\n".join(section_2_lines)

    section_3_lines = ["# Relevant Code Context", "", "## Suggested Files"]
    if file_contents:
        for file_path, content in file_contents.items():
            section_3_lines.extend(
                [
                    "",
                    f"### File: {file_path}",
                    "",
                    "```",
                    content,
                    "```",
                ]
            )
    else:
        section_3_lines.append("None")

    section_3 = "\n".join(section_3_lines)

    section_1 = _truncate_section(section_1, 10000, "Task Requirements")
    section_2 = _truncate_section(section_2, 20000, "Relevant Specs / Interfaces")
    section_3 = _truncate_section(section_3, 20000, "Relevant Code Context")

    total_limit = 50000
    sections = [section_1, section_2, section_3]
    total_length = sum(len(section) for section in sections)
    attempts = 0
    while total_length > total_limit and attempts < 3:
        scale = total_limit / total_length
        section_1 = _truncate_section(
            section_1, max(1, int(len(section_1) * scale)), "Task Requirements"
        )
        section_2 = _truncate_section(
            section_2,
            max(1, int(len(section_2) * scale)),
            "Relevant Specs / Interfaces",
        )
        section_3 = _truncate_section(
            section_3,
            max(1, int(len(section_3) * scale)),
            "Relevant Code Context",
        )
        sections = [section_1, section_2, section_3]
        total_length = sum(len(section) for section in sections)
        attempts += 1

    return "\n\n".join([section_1, section_2, section_3])


def write_context_bundle(run_root: Path, task_id: str, content: str) -> Path:
    """Write context bundle content to file.

    Args:
        run_root: Root directory for the run.
        task_id: Task identifier.
        content: Context bundle content to write.

    Returns:
        Path to the written context bundle file.
    """
    output_path = run_root / "tasks" / task_id / "context_bundle.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    logger.info("Wrote context bundle for %s: %s", task_id, output_path)
    return output_path


def _topological_sort_tasks(graph: PatchGraphSchema) -> list[str]:
    nodes = list(graph.nodes)
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    in_degree: dict[str, int] = {node: 0 for node in nodes}

    for source, target in graph.edges:
        adjacency.setdefault(source, []).append(target)
        in_degree.setdefault(source, 0)
        in_degree[target] = in_degree.get(target, 0) + 1

    queue = deque([node for node in nodes if in_degree.get(node, 0) == 0])
    ordered: list[str] = []

    while queue:
        node = queue.popleft()
        ordered.append(node)
        for target in adjacency.get(node, []):
            in_degree[target] -= 1
            if in_degree[target] == 0:
                queue.append(target)

    if len(ordered) != len(in_degree):
        raise RuntimeError("cycle detected in patch graph")

    return ordered


def _filter_tasks_with_prerequisites(
    task_ids: list[str],
    graph: PatchGraphSchema,
) -> list[str]:
    prerequisites: dict[str, set[str]] = {node: set() for node in graph.nodes}
    for source, target in graph.edges:
        prerequisites.setdefault(target, set()).add(source)
        prerequisites.setdefault(source, set())

    required: set[str] = set()

    def _visit(task_id: str) -> None:
        if task_id in required:
            return
        if task_id not in prerequisites:
            logger.warning("Task %s not found in patch graph nodes.", task_id)
            return
        required.add(task_id)
        for dep in prerequisites.get(task_id, set()):
            _visit(dep)

    for task_id in task_ids:
        _visit(task_id)

    ordered = _topological_sort_tasks(graph)
    return [task_id for task_id in ordered if task_id in required]


def _generate_patch(
    run_root: Path,
    task_id: str,
    context_bundle: str,
    max_iterations: int,
    manager: WorkspaceManager,
) -> tuple[str, list[dict[str, Any]]]:
    logger.info("Generating patch for %s.", task_id)
    logger.debug("Run root for %s: %s", task_id, run_root)
    start = time.perf_counter()
    output = run_agent(
        agent_name="glm-task-implementer",
        prompt=context_bundle,
        workspace=manager.workspace_path,
    )
    logger.debug("Received patch output for %s (chars=%d).", task_id, len(output))
    try:
        parsed = PatchOutputSchema.model_validate_json(output)
    except Exception:
        logger.exception("Failed to parse patch output for %s", task_id)
        raise

    patch_text = parsed.patch
    evidence_records: list[dict[str, Any]] = []
    attempts = 0
    repo_root = manager.input_folder

    while True:
        is_valid, errors = validate_patch(
            patch_text,
            repo_root,
            immutable_paths=IMMUTABLE_PATH_PATTERNS,
        )
        if is_valid:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Patch validation succeeded for %s (latency_ms=%.2f).",
                task_id,
                elapsed_ms,
            )
            return patch_text, evidence_records

        logger.warning(
            "Patch validation failed for %s (errors=%d).",
            task_id,
            len(errors),
        )
        if attempts >= max_iterations:
            error_payload = json.dumps(errors, indent=2, sort_keys=True)
            raise RuntimeError(
                f"Patch validation failed for {task_id} after {max_iterations} repair attempts: "
                f"{error_payload}"
            )

        attempts += 1
        patch_text, repair_evidence = repair_artifact(
            output=patch_text,
            errors=errors,
            allowlists={},
            artifact_type=ArtifactType.PATCH_OUTPUT,
            model_override=get_repair_model(),
            manager=manager,
        )
        evidence_records.extend(repair_evidence)
        logger.info(
            "Repair iteration %d/%d completed for %s.",
            attempts,
            max_iterations,
            task_id,
        )


def _build_audit_prompt(task: TaskSchema, patch_text: str) -> str:
    acceptance_criteria = (
        "\n".join(
            f"{index + 1}. {criterion}" for index, criterion in enumerate(task.acceptance_criteria)
        )
        if task.acceptance_criteria
        else "None"
    )

    lines = [
        "Task Requirements",
        f"- Task ID: {task.task_id}",
        f"- Title: {task.title}",
        "",
        "Description:",
        task.description,
        "",
        "Acceptance Criteria:",
        acceptance_criteria,
        "",
        "Patch Content:",
        "```diff",
        patch_text,
        "```",
        "",
        "Instructions:",
        "1. Verify each acceptance criterion against the patch content.",
        "2. Identify any spec/interface violations using pointer format",
        "   [LIB-####::spec.md::ELEMENT_ID].",
        "3. Output a verdict of pass or fail and a list of issues.",
        "",
        "Output Format (JSON):",
        "{",
        '  "verdict": "pass" | "fail",',
        '  "issues": ["issue 1", "issue 2"]',
        "}",
    ]
    return "\n".join(lines)


def _format_audit_md_content(
    verdict: str,
    issues: list[str],
    acceptance_criteria: list[str],
) -> str:
    normalized_verdict = verdict.lower()
    status_symbol = "✓" if normalized_verdict == "pass" else "✗"
    notes = "Meets criterion." if normalized_verdict == "pass" else "See issues list."

    table_lines = [
        "| Criterion | Status | Notes |",
        "| --- | --- | --- |",
    ]
    if acceptance_criteria:
        for criterion in acceptance_criteria:
            escaped = criterion.replace("|", "\\|")
            table_lines.append(f"| {escaped} | {status_symbol} | {notes} |")
    else:
        table_lines.append("| None | - | No acceptance criteria provided. |")

    issue_lines = [f"{index + 1}. {issue}" for index, issue in enumerate(issues)]
    if not issue_lines:
        issue_lines = ["None"]

    summary = f"Verdict: {normalized_verdict}. Issues reported: {len(issues)}."

    return "\n".join(
        [
            "# Patch Audit Report",
            "",
            "## Verdict",
            normalized_verdict,
            "",
            "## Acceptance Criteria Assessment",
            "\n".join(table_lines),
            "",
            "## Issues",
            "\n".join(issue_lines),
            "",
            "## Summary",
            summary,
            "",
        ]
    )


def _write_audit_md(
    task_dir: Path,
    verdict: str,
    issues: list[str],
    acceptance_criteria: list[str],
) -> None:
    content = _format_audit_md_content(verdict, issues, acceptance_criteria)
    task_dir.mkdir(parents=True, exist_ok=True)
    output_path = task_dir / "audit.md"
    output_path.write_text(content, encoding="utf-8")
    logger.info("Wrote audit report: %s", output_path)


def _parse_audit_output(output: str) -> tuple[str, list[str]]:
    content = output.strip()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        verdict_raw = str(payload.get("verdict", "")).strip().lower()
        issues_raw = payload.get("issues", [])
        if verdict_raw in {"pass", "fail"}:
            issues: list[str] = []
            if isinstance(issues_raw, list):
                issues = [str(issue).strip() for issue in issues_raw if str(issue).strip()]
            elif isinstance(issues_raw, str):
                issues = [line.strip() for line in issues_raw.splitlines() if line.strip()]
            return verdict_raw, issues

    verdict: str | None = None
    issues: list[str] = []
    for line in content.splitlines():
        lower = line.strip().lower()
        if verdict is None and "verdict" in lower:
            parts = re.split(r"[:\-]\s*", line, maxsplit=1)
            if len(parts) > 1:
                candidate = parts[1].strip().lower()
                if candidate in {"pass", "fail"}:
                    verdict = candidate
        if re.match(r"^\s*[-*]\s+", line) or re.match(r"^\s*\d+[\).]\s+", line):
            issue = re.sub(r"^\s*([-*]|\d+[\).])\s*", "", line).strip()
            if issue:
                issues.append(issue)

    if verdict is None:
        raise ValueError("Unable to parse audit verdict.")

    return verdict, issues


def _read_test_output(task_dir: Path) -> str:
    output_path = task_dir / "test_output.txt"
    if not output_path.exists():
        return ""
    try:
        return output_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read test output: %s", exc)
        return ""


def _extract_pytest_failures(test_output: str) -> list[str]:
    failures: list[str] = []
    for line in test_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("FAILED ") or stripped.startswith("ERROR "):
            failures.append(stripped)
    return failures


def _build_test_repair_prompt(
    task: TaskSchema,
    patch_text: str,
    test_result: TestResultSchema,
    test_output: str,
    failures: list[str],
    validation_errors: list[dict[str, Any]] | None = None,
    apply_error: str | None = None,
) -> str:
    acceptance_criteria = (
        "\n".join(
            f"{index + 1}. {criterion}" for index, criterion in enumerate(task.acceptance_criteria)
        )
        if task.acceptance_criteria
        else "None"
    )
    failure_lines = "\n".join(f"- {item}" for item in failures) if failures else "None"
    validation_block = (
        json.dumps(validation_errors, indent=2, sort_keys=True) if validation_errors else "None"
    )
    apply_error_text = apply_error or "None"

    lines = [
        "Task Requirements",
        f"- Task ID: {task.task_id}",
        f"- Title: {task.title}",
        "",
        "Description:",
        task.description,
        "",
        "Acceptance Criteria:",
        acceptance_criteria,
        "",
        "Test Command:",
        test_result.command,
        f"Exit Code: {test_result.exit_code}",
        "",
        "Parsed Test Failures:",
        failure_lines,
        "",
        "Patch Validation Errors:",
        validation_block,
        "",
        "Patch Apply Error:",
        apply_error_text,
        "",
        "Test Output (verbatim):",
        "<BEGIN_TEST_OUTPUT>",
        test_output.strip(),
        "<END_TEST_OUTPUT>",
        "",
        "Current Patch:",
        "```diff",
        patch_text,
        "```",
        "",
        "Instructions:",
        "Fix the patch so tests pass and requirements remain satisfied.",
        "Return ONLY a unified diff patch. No explanations or code fences.",
    ]
    return "\n".join(lines)


def _restore_from_backup(backup_dir: Path, repo_root: Path) -> None:
    """Restore repository files from backup before re-applying a repaired patch.

    Reads the apply_log.json from the backup directory, copies backed-up files
    to their original locations, and removes new files that were created by the
    previous patch application.

    Args:
        backup_dir: Directory containing backup files and apply_log.json.
        repo_root: Repository root directory.
    """
    log_path = backup_dir / "apply_log.json"
    if not log_path.exists():
        logger.warning("No apply_log.json found in %s, skipping restore.", backup_dir)
        return

    try:
        apply_log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read apply_log.json for restore: %s", exc)
        return

    restored_paths: set[str] = set()
    for record in apply_log.get("backup_records", []):
        backup_path = Path(record["backup_path"])
        original_path = Path(record["path"])
        if backup_path.exists():
            original_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, original_path)
            restored_paths.add(str(original_path))

    removed = 0
    for rel_path in apply_log.get("applied_files", []):
        abs_path = repo_root / rel_path
        if str(abs_path) not in restored_paths and abs_path.exists():
            abs_path.unlink()
            removed += 1

    logger.info(
        "Backup restore completed (restored=%d, removed=%d).",
        len(restored_paths),
        removed,
    )


def _repair_patch_for_tests(
    *,
    run_root: Path,
    task_id: str,
    task_dir: Path,
    repo_root: Path,
    patch_text: str,
    apply_log: dict[str, Any],
    test_result: TestResultSchema,
    max_iterations: int,
    manager: WorkspaceManager,
    test_command: str | None,
) -> tuple[str, dict[str, Any], TestResultSchema]:
    task_path = run_root / "tasks" / task_id / "task.json"
    task = TaskSchema.model_validate_json(task_path.read_text(encoding="utf-8"))

    attempts = 0
    current_patch = patch_text
    current_test_result = test_result
    current_apply_log = dict(apply_log)
    validation_errors: list[dict[str, Any]] | None = None
    apply_error: str | None = None

    while current_test_result.exit_code != 0 and attempts < max_iterations:
        attempts += 1
        test_output = _read_test_output(task_dir)
        failures = _extract_pytest_failures(test_output)
        prompt = _build_test_repair_prompt(
            task,
            current_patch,
            current_test_result,
            test_output,
            failures,
            validation_errors=validation_errors,
            apply_error=apply_error,
        )
        logger.info(
            "Running test repair iteration %d/%d for %s.",
            attempts,
            max_iterations,
            task_id,
        )
        repaired_patch = run_agent(
            agent_name="chatgpt-patch-repairer",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
        if not isinstance(repaired_patch, str):
            raise TypeError(
                f"Expected patch repair output to be str, got {type(repaired_patch).__name__}"
            )
        current_patch = repaired_patch
        validation_errors = None
        apply_error = None

        is_valid, errors = validate_patch(
            current_patch,
            repo_root,
            immutable_paths=IMMUTABLE_PATH_PATTERNS,
        )
        if not is_valid:
            validation_errors = errors
            logger.warning(
                "Repaired patch validation failed for %s (errors=%d).",
                task_id,
                len(errors),
            )
            continue

        _restore_from_backup(task_dir / "backup", repo_root)
        current_apply_log = apply_patch(
            patch_text=current_patch,
            repo_root=repo_root,
            backup_dir=task_dir / "backup",
            immutable_paths=IMMUTABLE_PATH_PATTERNS,
        )
        if not current_apply_log.get("success"):
            apply_error = str(current_apply_log.get("error") or "Patch apply failed")
            logger.warning(
                "Repaired patch apply failed for %s (error=%s).",
                task_id,
                apply_error,
            )
            continue

        current_test_result = (
            run_tests(
                task_dir=task_dir,
                repo_root=repo_root,
                test_command=test_command,
                run_tests_flag=True,
            )
            or current_test_result
        )
        logger.info(
            "Test repair iteration %d/%d completed for %s (exit_code=%d).",
            attempts,
            max_iterations,
            task_id,
            current_test_result.exit_code,
        )

    return current_patch, current_apply_log, current_test_result


def _audit_patch(
    run_root: Path,
    task_id: str,
    patch_text: str,
    max_iterations: int,
    manager: WorkspaceManager,
) -> tuple[str, str, int, str]:
    task_path = run_root / "tasks" / task_id / "task.json"
    task = TaskSchema.model_validate_json(task_path.read_text(encoding="utf-8"))
    task_dir = run_root / "tasks" / task_id

    attempts = 0
    current_patch = patch_text

    while True:
        prompt = _build_audit_prompt(task, current_patch)
        logger.info(
            "Running patch audit for %s (attempt %d/%d).", task_id, attempts + 1, max_iterations + 1
        )
        output = run_agent(
            agent_name="chatgpt-patch-audit-judge",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
        try:
            verdict, issues = _parse_audit_output(output)
        except Exception:
            logger.exception("Failed to parse audit output for %s", task_id)
            raise

        logger.info(
            "Audit completed for %s (verdict=%s, issues=%d).",
            task_id,
            verdict,
            len(issues),
        )

        if verdict == "pass":
            audit_md_content = _format_audit_md_content(
                verdict,
                issues,
                task.acceptance_criteria,
            )
            _write_audit_md(task_dir, verdict, issues, task.acceptance_criteria)
            return audit_md_content, verdict, len(issues), current_patch

        if attempts >= max_iterations:
            audit_md_content = _format_audit_md_content(
                verdict,
                issues,
                task.acceptance_criteria,
            )
            _write_audit_md(task_dir, verdict, issues, task.acceptance_criteria)
            return audit_md_content, verdict, len(issues), current_patch

        attempts += 1
        audit_errors = [
            {
                "type": "audit_issue",
                "message": issue,
                "task_id": task_id,
            }
            for issue in issues
        ]
        if not audit_errors:
            audit_errors = [
                {
                    "type": "audit_failure",
                    "message": "Audit failed without issue details.",
                    "task_id": task_id,
                }
            ]

        current_patch, _ = repair_artifact(
            output=current_patch,
            errors=audit_errors,
            allowlists={},
            artifact_type=ArtifactType.PATCH_OUTPUT,
            model_override=get_repair_model(),
            manager=manager,
        )

        repo_root = manager.input_folder
        is_valid, validation_errors = validate_patch(
            current_patch,
            repo_root,
            immutable_paths=IMMUTABLE_PATH_PATTERNS,
        )
        if is_valid:
            _restore_from_backup(task_dir / "backup", repo_root)
            repair_apply_log = apply_patch(
                patch_text=current_patch,
                repo_root=repo_root,
                backup_dir=task_dir / "backup",
                immutable_paths=IMMUTABLE_PATH_PATTERNS,
            )
            logger.info(
                "Repaired patch re-applied for %s (success=%s, files=%d).",
                task_id,
                repair_apply_log.get("success"),
                len(repair_apply_log.get("applied_files", [])),
            )
        else:
            logger.warning(
                "Repaired patch validation failed for %s (errors=%d), skipping re-apply.",
                task_id,
                len(validation_errors),
            )

        logger.info(
            "Audit repair iteration %d/%d completed for %s.",
            attempts,
            max_iterations,
            task_id,
        )


def execute_task(
    run_root: Path,
    task_id: str,
    repo_root: Path,
    max_iterations: int,
    manager: WorkspaceManager,
    config: ImplementationConfig,
) -> dict[str, Any]:
    """Execute a single implementation task.

    Args:
        run_root: Root directory for the run.
        task_id: Task identifier.
        repo_root: Repository root directory.
        max_iterations: Maximum number of repair iterations.
        manager: Workspace manager instance.
        config: Implementation execution configuration.

    Returns:
        Task execution summary dictionary.
    """
    task_dir = run_root / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    status_path = task_dir / "status.json"

    started_at = datetime.now().isoformat()
    status = TaskImplementationStatusSchema(
        task_id=task_id,
        status="in_progress",
        started_at=started_at,
        repo_root=str(repo_root),
    )
    write_task_implementation_status_json(status, status_path)
    logger.info("Started task %s.", task_id)

    patch_sha256 = ""
    applied_files: list[str] = []
    audit_verdict: str | None = None
    issue_count = 0
    test_result: TestResultSchema | None = None
    lint_result: dict[str, Any] | None = None

    start = time.perf_counter()
    try:
        context_bundle = build_context_bundle(run_root, task_id, repo_root)
        write_context_bundle(run_root, task_id, context_bundle)

        patch_text, _ = _generate_patch(
            run_root,
            task_id,
            context_bundle,
            max_iterations,
            manager,
        )

        apply_log = apply_patch(
            patch_text=patch_text,
            repo_root=repo_root,
            backup_dir=task_dir / "backup",
            immutable_paths=IMMUTABLE_PATH_PATTERNS,
        )

        patch_sha256 = str(apply_log.get("patch_sha256", ""))
        applied_files = list(apply_log.get("applied_files", []))
        logger.info(
            "Patch applied for %s (success=%s, files=%d).",
            task_id,
            apply_log.get("success"),
            len(applied_files),
        )

        test_result = run_tests(
            task_dir=task_dir,
            repo_root=repo_root,
            test_command=config.test_command,
            run_tests_flag=config.run_tests,
        )
        if test_result is not None:
            status = TaskImplementationStatusSchema(
                task_id=task_id,
                status="in_progress",
                started_at=started_at,
                repo_root=str(repo_root),
                patch_sha256=patch_sha256,
                applied_files=applied_files,
                tests=test_result,
            )
            write_task_implementation_status_json(status, status_path)

            if test_result.exit_code != 0:
                if config.allow_test_repair:
                    logger.info(
                        "Tests failed for %s (exit_code=%d). Starting repair loop.",
                        task_id,
                        test_result.exit_code,
                    )
                    patch_text, apply_log, test_result = _repair_patch_for_tests(
                        run_root=run_root,
                        task_id=task_id,
                        task_dir=task_dir,
                        repo_root=repo_root,
                        patch_text=patch_text,
                        apply_log=apply_log,
                        test_result=test_result,
                        max_iterations=max_iterations,
                        manager=manager,
                        test_command=config.test_command,
                    )
                    patch_sha256 = str(apply_log.get("patch_sha256", ""))
                    applied_files = list(apply_log.get("applied_files", []))
                    status = TaskImplementationStatusSchema(
                        task_id=task_id,
                        status="in_progress",
                        started_at=started_at,
                        repo_root=str(repo_root),
                        patch_sha256=patch_sha256,
                        applied_files=applied_files,
                        tests=test_result,
                    )
                    write_task_implementation_status_json(status, status_path)

                if test_result.exit_code != 0:
                    logger.info(
                        "Tests still failing for %s after repair attempts.",
                        task_id,
                    )
                    finished_at = datetime.now().isoformat()
                    status = TaskImplementationStatusSchema(
                        task_id=task_id,
                        status="failed",
                        started_at=started_at,
                        finished_at=finished_at,
                        repo_root=str(repo_root),
                        patch_sha256=patch_sha256,
                        applied_files=applied_files,
                        tests=test_result,
                    )
                    write_task_implementation_status_json(status, status_path)
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    logger.info(
                        "Completed task %s (status=failed, latency_ms=%.2f).",
                        task_id,
                        elapsed_ms,
                    )
                    return {
                        "task_id": task_id,
                        "status": "failed",
                        "patch_sha256": patch_sha256,
                        "applied_files": len(applied_files),
                        "audit_verdict": None,
                        "tests": test_result.model_dump(),
                        "lint": lint_result,
                    }

        lint_result = run_lint(
            task_dir=task_dir,
            repo_root=repo_root,
            lint_command=config.lint_command,
            run_lint_flag=config.run_lint,
        )

        audit_md_content, audit_verdict, issue_count, final_patch_text = _audit_patch(
            run_root,
            task_id,
            patch_text,
            max_iterations,
            manager,
        )
        logger.debug("Audit content size for %s: %d chars.", task_id, len(audit_md_content))

        if final_patch_text != patch_text:
            patch_text = final_patch_text
            backup_log_path = task_dir / "backup" / "apply_log.json"
            apply_log = json.loads(backup_log_path.read_text(encoding="utf-8"))
            patch_sha256 = str(apply_log.get("patch_sha256", ""))
            applied_files = list(apply_log.get("applied_files", []))
            logger.info(
                "Updated artifacts from repaired patch for %s (files=%d).",
                task_id,
                len(applied_files),
            )

        patch_path = task_dir / "patch.diff"
        patch_path.write_text(patch_text, encoding="utf-8")
        logger.info("Wrote patch diff for %s: %s", task_id, patch_path)

        apply_log_path = task_dir / "apply_log.json"
        apply_log_path.write_text(
            json.dumps(apply_log, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        logger.info("Wrote apply log for %s: %s", task_id, apply_log_path)

        apply_success = bool(apply_log.get("success"))
        tests_passed = test_result is None or test_result.exit_code == 0
        final_status = (
            "done" if apply_success and audit_verdict == "pass" and tests_passed else "failed"
        )
        finished_at = datetime.now().isoformat()
        audit_result = {"verdict": audit_verdict, "issues": issue_count} if audit_verdict else None
        status = TaskImplementationStatusSchema(
            task_id=task_id,
            status=final_status,
            started_at=started_at,
            finished_at=finished_at,
            repo_root=str(repo_root),
            patch_sha256=patch_sha256,
            applied_files=applied_files,
            tests=test_result,
            audit=audit_result,
        )
        write_task_implementation_status_json(status, status_path)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Completed task %s (status=%s, latency_ms=%.2f).",
            task_id,
            final_status,
            elapsed_ms,
        )

        return {
            "task_id": task_id,
            "status": final_status,
            "patch_sha256": patch_sha256,
            "applied_files": len(applied_files),
            "audit_verdict": audit_verdict,
            "tests": test_result.model_dump() if test_result else None,
            "lint": lint_result,
        }
    except Exception as exc:
        finished_at = datetime.now().isoformat()
        logger.exception("Task %s failed", task_id)
        status = TaskImplementationStatusSchema(
            task_id=task_id,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            repo_root=str(repo_root),
            patch_sha256=patch_sha256,
            applied_files=applied_files,
            tests=test_result,
            audit={"verdict": audit_verdict or "fail", "issues": issue_count}
            if audit_verdict is not None
            else None,
        )
        write_task_implementation_status_json(status, status_path)
        return {
            "task_id": task_id,
            "status": "failed",
            "patch_sha256": patch_sha256,
            "applied_files": len(applied_files),
            "audit_verdict": audit_verdict,
            "error": str(exc),
            "tests": test_result.model_dump() if test_result else None,
            "lint": lint_result,
        }


def run_implementation_phase(
    run_root: Path,
    repo_root: Path,
    task_filter: list[str] | None,
    max_iterations: int,
    config: ImplementationConfig,
) -> dict[str, Any]:
    """Run the implementation phase for tasks.

    Args:
        run_root: Root directory for the run.
        repo_root: Repository root directory.
        task_filter: Optional list of task IDs to filter.
        max_iterations: Maximum number of repair iterations.
        config: Implementation execution configuration.

    Returns:
        Summary dictionary of implementation phase results.
    """
    manager = WorkspaceManager(run_id=run_root.name, input_folder=repo_root)
    manager.start_phase(Phase.IMPLEMENTATION)

    patch_graph_path = run_root / "tasks" / "patch_graph.json"
    graph = read_patch_graph_json(patch_graph_path)
    ordered_tasks = _topological_sort_tasks(graph)

    if task_filter:
        selected_with_prereqs = _filter_tasks_with_prerequisites(task_filter, graph)
        selected_set = set(selected_with_prereqs)
        selected_tasks = [task_id for task_id in ordered_tasks if task_id in selected_set]
    else:
        selected_tasks = ordered_tasks

    total = len(selected_tasks)
    logger.info("Executing %d task(s) for implementation phase.", total)

    summaries: list[dict[str, Any]] = []
    for index, task_id in enumerate(selected_tasks):
        logger.info("Executing task %s (%d/%d).", task_id, index + 1, total)
        try:
            summary = execute_task(run_root, task_id, repo_root, max_iterations, manager, config)
        except Exception as exc:
            logger.exception("Unhandled exception while executing %s", task_id)
            task_dir = run_root / "tasks" / task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            now = datetime.now().isoformat()
            fallback_status = TaskImplementationStatusSchema(
                task_id=task_id,
                status="failed",
                started_at=now,
                finished_at=now,
                repo_root=str(repo_root),
            )
            write_task_implementation_status_json(fallback_status, task_dir / "status.json")
            summary = {
                "task_id": task_id,
                "status": "failed",
                "patch_sha256": "",
                "applied_files": 0,
                "audit_verdict": None,
                "error": str(exc),
            }
        summaries.append(summary)

    done_count = sum(1 for summary in summaries if summary.get("status") == "done")
    failed_count = sum(1 for summary in summaries if summary.get("status") == "failed")
    blocked_count = sum(1 for summary in summaries if summary.get("status") == "blocked")
    patches_applied = sum(summary.get("applied_files", 0) for summary in summaries)
    tests_passed = 0
    tests_failed = 0
    for summary in summaries:
        tests = summary.get("tests")
        if tests and tests.get("ran"):
            if tests.get("exit_code", -1) == 0:
                tests_passed += 1
            else:
                tests_failed += 1

    manager.complete_phase(
        Phase.IMPLEMENTATION,
        outputs={
            "tasks_executed": len(selected_tasks),
            "tasks_done": done_count,
            "tasks_failed": failed_count,
            "patches_applied": patches_applied,
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
        },
    )

    return {
        "tasks_executed": len(selected_tasks),
        "tasks_done": done_count,
        "tasks_failed": failed_count,
        "tasks_blocked": blocked_count,
        "patches_applied": patches_applied,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "task_summaries": summaries,
    }


__all__ = [
    "build_context_bundle",
    "execute_task",
    "run_implementation_phase",
    "write_context_bundle",
]
