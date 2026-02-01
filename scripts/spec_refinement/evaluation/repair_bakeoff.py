"""Repair model evaluation harness for spec refinement artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import tempfile
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.spec_refinement.evaluation.fixtures import FixtureCategory, RepairFixture
from scripts.spec_refinement.workflows.architecture import _validate_architecture_citations
from scripts.spec_refinement.workflows.evidence_expansion import _validate_evidence_entry
from scripts.spec_refinement.workflows.formats import parse_library_synthesis
from scripts.spec_refinement.workflows.library_synthesis import (
    _validate_evidence_sources,
    _validate_library_ids,
    _validate_overlap_resolutions,
)
from scripts.spec_refinement.workflows.repair import (
    ArtifactType,
    _build_repair_prompt,
    repair_artifact,
)
from scripts.spec_refinement.workflows.spec_building import _validate_spec_citations
from scripts.spec_refinement.workflows.summarization import _validate_evidence_pointers
from scripts.spec_refinement.workspace import RunFolderStructure, WorkspaceManager, WorkspaceState

_PRELUDE_PREFIXES = (
    "here is",
    "here's",
    "below is",
    "note:",
    "corrected",
    "the corrected",
)

_ERROR_CATEGORY_MAP: dict[str, FixtureCategory] = {
    "unknown_file_reference": FixtureCategory.INVALID_FILE_ID,
    "invalid_file_id": FixtureCategory.INVALID_FILE_ID,
    "unknown_library": FixtureCategory.INVALID_FILE_ID,
    "unknown_section_reference": FixtureCategory.INVENTED_SECTION,
    "missing_citation": FixtureCategory.MISSING_CITATION,
    "missing_citations": FixtureCategory.MISSING_CITATION,
    "missing_evidence_pointers": FixtureCategory.MISSING_CITATION,
    "malformed_evidence_pointer": FixtureCategory.MISSING_CITATION,
    "stray_preamble": FixtureCategory.STRAY_PREAMBLE,
    "trailing_fence": FixtureCategory.TRAILING_FENCE,
    "compound_pointer": FixtureCategory.COMPOUND_POINTER,
}

_FIXTURE_ID_BY_OBJECT: dict[int, str] = {}
_FIXTURE_CATEGORY_BY_ID: dict[str, set[FixtureCategory]] = {}


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for an AI model used in repair evaluation.

    Attributes:
        name: Human-readable model name.
        provider: Name of the model provider (e.g., "openai", "anthropic").
        model_id: Model identifier for API calls.
        cost_per_1k_tokens: Tuple of (input_cost, output_cost) per 1000 tokens.
    """

    name: str
    provider: str
    model_id: str
    cost_per_1k_tokens: tuple[float, float]


@dataclass(frozen=True)
class RepairResult:
    """Result of running repair on a single fixture with a model.

    Attributes:
        fixture_id: Identifier of the fixture that was repaired.
        model_name: Name of the model used for repair.
        success: Whether the repair produced valid output.
        validation_errors: List of validation errors found in repaired output.
        edit_distance: Levenshtein distance between original and repaired output.
        latency_ms: Repair execution time in milliseconds.
        input_tokens: Estimated input tokens for the repair request.
        output_tokens: Estimated output tokens in the repair response.
        cost_usd: Estimated cost in USD for this repair attempt.
    """

    fixture_id: str
    model_name: str
    success: bool
    validation_errors: list[dict[str, Any]]
    edit_distance: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float


CANDIDATE_MODELS: list[ModelConfig] = [
    ModelConfig(
        name="gpt-5.2-none",
        provider="openai",
        model_id="gpt-5.2-none",
        cost_per_1k_tokens=(0.00175, 0.014),
    ),
    ModelConfig(
        name="gpt-5.2-low",
        provider="openai",
        model_id="gpt-5.2-low",
        cost_per_1k_tokens=(0.00175, 0.014),
    ),
    ModelConfig(
        name="claude-haiku",
        provider="anthropic",
        model_id="claude-haiku",
        cost_per_1k_tokens=(0.001, 0.005),
    ),
    ModelConfig(
        name="gemini-3-flash",
        provider="gemini",
        model_id="gemini-3-flash-low",
        cost_per_1k_tokens=(0.0005, 0.003),
    ),
]


def _load_fixtures() -> list[RepairFixture]:
    from scripts.spec_refinement.evaluation.fixtures import (
        architecture_fixtures,
        charter_fixtures,
        evidence_json_fixtures,
        spec_fixtures,
        summary_fixtures,
    )

    fixtures: list[RepairFixture] = []
    for module in (
        summary_fixtures,
        charter_fixtures,
        spec_fixtures,
        evidence_json_fixtures,
        architecture_fixtures,
    ):
        fixtures.extend(module.FIXTURES)
    return fixtures


def _index_fixtures(fixtures: list[RepairFixture]) -> None:
    _FIXTURE_ID_BY_OBJECT.clear()
    _FIXTURE_CATEGORY_BY_ID.clear()

    per_type: dict[ArtifactType, int] = {}
    for fixture in fixtures:
        count = per_type.get(fixture.artifact_type, 0) + 1
        per_type[fixture.artifact_type] = count
        fixture_id = f"{fixture.artifact_type.value}_{count:03d}"
        _FIXTURE_ID_BY_OBJECT[id(fixture)] = fixture_id
        _FIXTURE_CATEGORY_BY_ID[fixture_id] = _infer_fixture_categories(fixture)


def _infer_fixture_categories(fixture: RepairFixture) -> set[FixtureCategory]:
    categories: set[FixtureCategory] = set()
    for error in fixture.expected_errors:
        category = _ERROR_CATEGORY_MAP.get(str(error.get("type", "")))
        if category:
            categories.add(category)
    if not categories:
        description = fixture.description.lower()
        for keyword, category in (
            ("preamble", FixtureCategory.STRAY_PREAMBLE),
            ("fence", FixtureCategory.TRAILING_FENCE),
            ("compound", FixtureCategory.COMPOUND_POINTER),
            ("section", FixtureCategory.INVENTED_SECTION),
            ("file", FixtureCategory.INVALID_FILE_ID),
            ("citation", FixtureCategory.MISSING_CITATION),
        ):
            if keyword in description:
                categories.add(category)
    return categories or {FixtureCategory.MISSING_CITATION}


def _filter_fixtures(
    fixtures: list[RepairFixture],
    categories: set[FixtureCategory] | None,
) -> list[RepairFixture]:
    if not categories:
        return fixtures
    filtered: list[RepairFixture] = []
    for fixture in fixtures:
        if _infer_fixture_categories(fixture) & categories:
            filtered.append(fixture)
    return filtered


def _is_gemini_available() -> bool:
    env = os.environ
    if env.get("GEMINI_API_KEY") or env.get("GEMINI_BASE_URL"):
        return True
    base_url = env.get("OPENAI_BASE_URL", "") or env.get("OPENAI_API_BASE", "")
    return "gemini" in base_url.lower()


def _select_models(names: Iterable[str] | None) -> list[ModelConfig]:
    models = CANDIDATE_MODELS
    if names:
        selected = {name.strip() for name in names if name.strip()}
        models = [model for model in models if model.name in selected]
    if not _is_gemini_available():
        models = [model for model in models if model.name != "gemini-3-flash"]
    return models


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def compute_edit_distance(original: str, repaired: str) -> int:
    """Calculate Levenshtein edit distance between two strings.

    Args:
        original: The original string.
        repaired: The repaired string.

    Returns:
        int: The minimum number of insertions, deletions, or substitutions
            required to transform original into repaired.
    """
    if original == repaired:
        return 0
    if not original:
        return len(repaired)
    if not repaired:
        return len(original)

    prev = list(range(len(repaired) + 1))
    for i, ch in enumerate(original, start=1):
        curr = [i]
        for j, other in enumerate(repaired, start=1):
            insert_cost = curr[j - 1] + 1
            delete_cost = prev[j] + 1
            replace_cost = prev[j - 1] + (ch != other)
            curr.append(min(insert_cost, delete_cost, replace_cost))
        prev = curr
    return prev[-1]


def is_repair_minimal(original: str, repaired: str, errors: list[dict[str, Any]]) -> bool:
    """Check if repair is minimal given the expected errors.

    A minimal repair should only modify lines directly related to the error
    types expected. Changes outside those scopes are considered non-minimal.

    Args:
        original: The original output text.
        repaired: The repaired output text.
        errors: List of error dictionaries with type information.

    Returns:
        bool: True if repair is minimal, False otherwise.
    """
    if original == repaired:
        return True

    allowed_snippets: set[str] = set()
    error_types = {str(error.get("type", "")) for error in errors}
    for error in errors:
        for key in ("pointer", "line"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                allowed_snippets.add(value.strip())

    original_lines = original.splitlines()
    repaired_lines = repaired.splitlines()

    from difflib import SequenceMatcher

    matcher = SequenceMatcher(a=original_lines, b=repaired_lines)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed_lines = repaired_lines[j1:j2]
        if "stray_preamble" in error_types and j1 <= 2:
            continue
        if "trailing_fence" in error_types and j2 >= max(len(repaired_lines) - 2, 0):
            continue
        if (
            "compound_pointer" in error_types
            and allowed_snippets
            and any(snippet in line for snippet in allowed_snippets for line in changed_lines)
        ):
            continue
        if allowed_snippets and any(
            snippet in line for snippet in allowed_snippets for line in changed_lines
        ):
            continue
        return False
    return True


def _detect_trailing_fence(output: str) -> list[dict[str, Any]]:
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    last = lines[-1].strip()
    if last.startswith("```"):
        return [
            {
                "type": "trailing_fence",
                "message": "Output ends with a code fence.",
            }
        ]
    return []


def _detect_compound_pointers(output: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for match in re.finditer(r"\[[^\[\]]*?::[^\[\]]*?,[^\[\]]*?\]", output):
        issues.append(
            {
                "type": "compound_pointer",
                "pointer": match.group(0),
                "message": "Compound pointer detected.",
            }
        )
    return issues


def _detect_stray_preamble(output: str, anchors: tuple[str, ...]) -> list[dict[str, Any]]:
    lines = output.splitlines()
    first_non_empty_index = None
    first_non_empty_line = ""
    for idx, line in enumerate(lines):
        if line.strip():
            first_non_empty_index = idx
            first_non_empty_line = line.strip()
            break

    if first_non_empty_index is None:
        return []

    lowered = first_non_empty_line.lower()
    if lowered.startswith(_PRELUDE_PREFIXES):
        return [
            {
                "type": "stray_preamble",
                "line": first_non_empty_line,
                "message": "Leading preamble detected.",
            }
        ]

    if anchors:
        anchor_index = None
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if any(stripped.startswith(anchor) for anchor in anchors):
                anchor_index = idx
                break
        if anchor_index is not None and anchor_index > first_non_empty_index:
            return [
                {
                    "type": "stray_preamble",
                    "line": first_non_empty_line,
                    "message": "Leading preamble detected before expected heading.",
                }
            ]

    return []


def _infer_file_id(output: str, allowlists: dict[str, Any]) -> str:
    file_id = allowlists.get("file_id")
    if isinstance(file_id, str) and file_id:
        return file_id
    for line in output.splitlines():
        if line.lower().startswith("file id:"):
            return line.split(":", 1)[1].strip()
    match = re.search(r"File Summary:\s*([\w\-\.]+)", output, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "unknown"


def _infer_lib_id(output: str, allowlists: dict[str, Any]) -> str:
    lib_id = allowlists.get("lib_id")
    if isinstance(lib_id, str) and lib_id:
        return lib_id
    match = re.search(r"Library Spec:\s*([\w\-\.]+)", output, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "lib_000"


def _build_validation_manager(allowlists: dict[str, Any], root: Path) -> WorkspaceManager:
    root.mkdir(parents=True, exist_ok=True)
    structure = RunFolderStructure(run_id=root.name, root=root)
    for directory in (
        structure.manifest_dir,
        structure.summaries_dir,
        structure.libraries_dir,
        structure.architecture_dir,
        structure.tasks_dir,
        structure.audits_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    manager = WorkspaceManager(run_id=root.name, input_folder=root)
    manager.structure = structure
    manager.state = WorkspaceState(run_id=root.name, input_folder=str(root))

    file_ids: list[str] = []
    raw_file_ids = allowlists.get("file_ids")
    if isinstance(raw_file_ids, list):
        file_ids = [str(item) for item in raw_file_ids if item]
    if not file_ids:
        sections_for_file_ids = allowlists.get("sections", {})
        if isinstance(sections_for_file_ids, dict):
            file_ids = list(sections_for_file_ids.keys())

    file_manifest = {
        file_id: {"relpath": f"inputs/{file_id}.md", "sha256": "0" * 64} for file_id in file_ids
    }
    manager.state.file_manifest = file_manifest

    section_manifest: dict[str, list[str]] = {}
    raw_sections: dict[str, list[str] | str] = allowlists.get("sections", {})
    if isinstance(raw_sections, dict):
        for file_id, sections in raw_sections.items():
            if isinstance(sections, list):
                section_manifest[file_id] = [str(item) for item in sections if item]
    for file_id in file_manifest:
        section_manifest.setdefault(file_id, [])
    manager.state.section_manifest = section_manifest

    library_files = allowlists.get("library_files", {})
    if isinstance(library_files, dict):
        for lib_id, files in library_files.items():
            lib_dir = manager.structure.libraries_dir / str(lib_id)
            lib_dir.mkdir(parents=True, exist_ok=True)
            if isinstance(files, dict):
                for filename, sections in files.items():
                    content = _render_library_file(filename, sections)
                    (lib_dir / str(filename)).write_text(content, encoding="utf-8")

    return manager


def _render_library_file(filename: str, sections: list[str] | object) -> str:
    title = filename.replace(".md", "").replace("_", " ").title()
    lines = [f"# {title}", ""]
    if isinstance(sections, list) and sections:
        for section in sections:
            heading = str(section).replace("_", " ").title()
            lines.append(f"## {heading}")
            lines.append(f"- Placeholder for {section}")
            lines.append("")
    else:
        lines.append("## Overview")
        lines.append("- Placeholder")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def validate_repaired_output(
    output: str, artifact_type: ArtifactType, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    """Validate repaired output against artifact-specific rules.

    Args:
        output: The repaired text output to validate.
        artifact_type: Type of artifact being validated.
        allowlists: Validation allowlists containing valid file IDs, sections, etc.

    Returns:
        List of validation error dictionaries.
    """
    issues: list[dict[str, Any]] = []

    anchors: tuple[str, ...]
    if artifact_type == ArtifactType.SUMMARY:
        anchors = ("# File Summary",)
    elif artifact_type == ArtifactType.CHARTER:
        anchors = ("## Library Index", "### lib_")
    elif artifact_type == ArtifactType.SPEC:
        anchors = ("# Library Spec",)
    elif artifact_type == ArtifactType.EVIDENCE_JSON:
        anchors = ("{", "[")
    else:
        anchors = ()

    issues.extend(_detect_stray_preamble(output, anchors))
    issues.extend(_detect_trailing_fence(output))
    issues.extend(_detect_compound_pointers(output))

    with tempfile.TemporaryDirectory(prefix="repair-bakeoff-validate-") as temp_dir:
        manager = _build_validation_manager(allowlists, Path(temp_dir))

        if artifact_type == ArtifactType.SUMMARY:
            file_id = _infer_file_id(output, allowlists)
            issues.extend(_validate_evidence_pointers(output, manager, file_id))
        elif artifact_type == ArtifactType.CHARTER:
            charters, _ = parse_library_synthesis(output)
            issues.extend(_validate_library_ids(charters))
            issues.extend(_validate_evidence_sources(charters, manager))
            issues.extend(_validate_overlap_resolutions(charters))
            issues.extend(_validate_charter_evidence_lines(output))
        elif artifact_type == ArtifactType.SPEC:
            lib_id = _infer_lib_id(output, allowlists)
            issues.extend(_validate_spec_citations(output, manager, lib_id))
        elif artifact_type == ArtifactType.EVIDENCE_JSON:
            issues.extend(_validate_evidence_json(output, manager, allowlists))
        elif artifact_type in {
            ArtifactType.ARCHITECTURE_SELECTION,
            ArtifactType.ARCHITECTURE_MAPPING,
        }:
            issues.extend(_validate_architecture_citations(output, manager))

    return issues


def _validate_charter_evidence_lines(content: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    in_evidence = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#### Evidence") or stripped.startswith("## Evidence"):
            in_evidence = True
            continue
        if in_evidence and stripped.startswith("#"):
            in_evidence = False
        if not in_evidence:
            continue
        if stripped.startswith("-") and "[" not in stripped:
            issues.append(
                {
                    "type": "missing_citation",
                    "line": stripped,
                    "message": "Evidence bullet missing pointer.",
                }
            )
    return issues


def _validate_evidence_json(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    """Validate evidence JSON output structure and citations.

    Args:
        output: JSON string to validate.
        manager: Workspace manager for file lookups.
        allowlists: Validation allowlists.

    Returns:
        List of validation error dictionaries.
    """
    issues: list[dict[str, Any]] = []
    lib_id = str(allowlists.get("lib_id") or "lib_000")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        return [
            {
                "type": "invalid_json",
                "message": f"Invalid JSON payload: {exc}",
            }
        ]

    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list):
        return [
            {
                "type": "invalid_sources",
                "message": "Evidence JSON sources must be a list.",
            }
        ]

    for entry in sources:
        if not isinstance(entry, dict):
            issues.append(
                {
                    "type": "invalid_entry",
                    "message": "Evidence entry must be an object.",
                }
            )
            continue
        entry_issues, _ = _validate_evidence_entry(entry, manager, lib_id)
        issues.extend(entry_issues)
        sections = entry.get("sections")
        if isinstance(sections, list) and not sections:
            issues.append(
                {
                    "type": "missing_citation",
                    "file_id": entry.get("file_id"),
                    "message": "Evidence entry missing section citations.",
                }
            )
        if isinstance(sections, list):
            for section in sections:
                if isinstance(section, str) and "," in section:
                    issues.append(
                        {
                            "type": "compound_pointer",
                            "section": section,
                            "message": "Compound pointer detected in section string.",
                        }
                    )
    return issues


def run_repair_with_model(
    fixture: RepairFixture, model: ModelConfig, workspace: Path
) -> RepairResult:
    """Run repair on a single fixture using the specified model.

    Args:
        fixture: The fixture containing invalid output and expected errors.
        model: The model configuration to use for repair.
        workspace: Path to the workspace directory for temporary files.

    Returns:
        RepairResult containing success status and metrics.
    """
    fixture_id = _FIXTURE_ID_BY_OBJECT.get(id(fixture), "unknown")

    errors = validate_repaired_output(
        fixture.invalid_output, fixture.artifact_type, fixture.allowlists
    )
    if not errors:
        return RepairResult(
            fixture_id=fixture_id,
            model_name=model.name,
            success=False,
            validation_errors=[
                {
                    "type": "fixture_validation_missed",
                    "message": "Fixture did not trigger validation errors.",
                }
            ],
            edit_distance=0,
            latency_ms=0.0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )

    model_workspace = workspace / f"{fixture_id}_{model.name}"
    manager = _build_validation_manager(fixture.allowlists, model_workspace)

    prompt = _build_repair_prompt(
        output=fixture.invalid_output,
        errors=errors,
        allowlists=fixture.allowlists,
        artifact_type=fixture.artifact_type,
    )
    input_tokens = _estimate_tokens(prompt)

    start = time.perf_counter()
    try:
        repaired_output, _ = repair_artifact(
            output=fixture.invalid_output,
            errors=errors,
            allowlists=fixture.allowlists,
            artifact_type=fixture.artifact_type,
            model_override=model.model_id,
            manager=manager,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RepairResult(
            fixture_id=fixture_id,
            model_name=model.name,
            success=False,
            validation_errors=[
                {
                    "type": "repair_exception",
                    "message": str(exc),
                }
            ],
            edit_distance=0,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=0,
            cost_usd=0.0,
        )

    latency_ms = (time.perf_counter() - start) * 1000
    output_tokens = _estimate_tokens(repaired_output)
    edit_distance = compute_edit_distance(fixture.invalid_output, repaired_output)
    validation_errors = validate_repaired_output(
        repaired_output, fixture.artifact_type, fixture.allowlists
    )

    input_cost, output_cost = model.cost_per_1k_tokens
    cost_usd = (input_tokens / 1000) * input_cost + (output_tokens / 1000) * output_cost

    return RepairResult(
        fixture_id=fixture_id,
        model_name=model.name,
        success=not validation_errors,
        validation_errors=validation_errors,
        edit_distance=edit_distance,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


def run_bakeoff(
    fixtures: list[RepairFixture],
    models: list[ModelConfig],
    workspace: Path,
) -> list[RepairResult]:
    """Run repair bakeoff across all fixtures and models concurrently.

    Args:
        fixtures: List of fixtures to repair.
        models: List of model configurations to evaluate.
        workspace: Path to workspace for temporary files.

    Returns:
        List of repair results for all fixture/model combinations.
    """
    results: list[RepairResult] = []
    tasks = [(fixture, model) for fixture in fixtures for model in models]

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(run_repair_with_model, fixture, model, workspace): (fixture, model)
            for fixture, model in tasks
        }
        for future in as_completed(future_map):
            results.append(future.result())
    return results


def aggregate_results(results: list[RepairResult]) -> dict[str, Any]:
    """Aggregate repair results into statistics by model.

    Args:
        results: List of repair results to aggregate.

    Returns:
        Dictionary mapping model names to their computed statistics including
        pass rate, average edit distance, latency, cost, and failure breakdown.
    """
    """Aggregate repair results into statistics by model.

    Args:
        results: List of repair results to aggregate.

    Returns:
        Dictionary mapping model names to their computed statistics including
        pass rate, average edit distance, latency, cost, and failure breakdown.
    """
    stats: dict[str, Any] = {}
    by_model: dict[str, list[RepairResult]] = {}

    for result in results:
        by_model.setdefault(result.model_name, []).append(result)

    for model_name, model_results in by_model.items():
        total = len(model_results)
        successes = sum(1 for result in model_results if result.success)
        pass_rate = successes / total if total else 0.0
        avg_edit_distance = (
            statistics.mean(result.edit_distance for result in model_results) if total else 0.0
        )
        avg_latency = (
            statistics.mean(result.latency_ms for result in model_results) if total else 0.0
        )
        total_cost = sum(result.cost_usd for result in model_results)

        failure_breakdown: dict[str, int] = {}
        for result in model_results:
            if result.success:
                continue
            for error in result.validation_errors:
                error_type = str(error.get("type", "unknown"))
                failure_breakdown[error_type] = failure_breakdown.get(error_type, 0) + 1

        stats[model_name] = {
            "total": total,
            "successes": successes,
            "pass_rate": pass_rate,
            "avg_edit_distance": avg_edit_distance,
            "avg_latency": avg_latency,
            "total_cost": total_cost,
            "failure_breakdown": failure_breakdown,
        }

    return stats


def _category_breakdown(results: list[RepairResult]) -> dict[str, dict[FixtureCategory, float]]:
    by_model: dict[str, dict[FixtureCategory, list[RepairResult]]] = {}

    for result in results:
        categories = _FIXTURE_CATEGORY_BY_ID.get(result.fixture_id, set())
        for category in categories:
            by_model.setdefault(result.model_name, {}).setdefault(category, []).append(result)

    breakdown: dict[str, dict[FixtureCategory, float]] = {}
    for model_name, category_results in by_model.items():
        model_breakdown: dict[FixtureCategory, float] = {}
        for category, items in category_results.items():
            if not items:
                model_breakdown[category] = 0.0
            else:
                model_breakdown[category] = sum(1 for item in items if item.success) / len(items)
        breakdown[model_name] = model_breakdown
    return breakdown


def _format_percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def generate_report(results: list[RepairResult], output_path: Path) -> None:
    """Generate a markdown report for repair bakeoff results.

    Args:
        results: List of repair results to report on.
        output_path: Path where the report should be written.
    """
    stats = aggregate_results(results)
    breakdown = _category_breakdown(results)
    timestamp = time.strftime("%Y-%m-%d")

    models = sorted(stats.keys())
    lines: list[str] = [
        "# Repair Model Selection Report",
        "",
        f"Generated: {timestamp}",
        "",
        "## Executive Summary",
        "",
        "| Model | Pass Rate | Avg Edit Distance | Avg Latency (ms) | Total Cost (USD) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for model in models:
        metrics = stats[model]
        lines.append(
            "| {model} | {pass_rate} | {edit:.1f} | {latency:.1f} | {cost:.4f} |".format(
                model=model,
                pass_rate=_format_percentage(metrics["pass_rate"]),
                edit=metrics["avg_edit_distance"],
                latency=metrics["avg_latency"],
                cost=metrics["total_cost"],
            )
        )

    lines.extend(["", "## Per-Category Breakdown", ""])

    category_headers = [category.value for category in FixtureCategory]
    header_row = "| Model | " + " | ".join(category_headers) + " |"
    sep_row = "| --- | " + " | ".join("---" for _ in category_headers) + " |"
    lines.extend([header_row, sep_row])
    for model in models:
        model_breakdown = breakdown.get(model, {})
        values = [
            _format_percentage(model_breakdown.get(category, 0.0)) for category in FixtureCategory
        ]
        lines.append("| {model} | {values} |".format(model=model, values=" | ".join(values)))

    lines.extend(["", "## Failure Analysis", ""])
    for model in models:
        lines.append(f"### {model}")
        failures = [
            result for result in results if result.model_name == model and not result.success
        ]
        if not failures:
            lines.append("- No failures")
            lines.append("")
            continue
        for result in failures:
            error_types = ", ".join(
                sorted({str(error.get("type", "unknown")) for error in result.validation_errors})
            )
            lines.append(f"- {result.fixture_id}: {error_types}")
        lines.append("")

    recommendation = _recommend_model(stats)
    lines.extend(
        [
            "## Recommendation",
            "",
            recommendation,
            "",
            "## Pass Rate Chart",
            "",
            "```mermaid",
            "xychart-beta",
            '  title "Pass Rate by Model"',
            "  x-axis [" + ", ".join(f'"{model}"' for model in models) + "]",
            '  y-axis "Pass Rate" 0 --> 1',
            "  bar [" + ", ".join(f"{stats[model]['pass_rate']:.2f}" for model in models) + "]",
            "```",
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _recommend_model(stats: dict[str, Any]) -> str:
    if not stats:
        return "No results available to recommend a model."

    ranked = sorted(
        stats.items(),
        key=lambda item: (
            -item[1]["pass_rate"],
            item[1]["total_cost"],
            item[1]["avg_latency"],
            item[1]["avg_edit_distance"],
        ),
    )
    top_model, metrics = ranked[0]
    return (
        "Based on a {pass_rate} pass rate and ${cost:.4f} total cost, "
        "we recommend **{model}** for repair tasks.".format(
            pass_rate=_format_percentage(metrics["pass_rate"]),
            cost=metrics["total_cost"],
            model=top_model,
        )
    )


def main() -> None:
    """Run the repair model bakeoff evaluation.

    Parses command-line arguments to select models and fixture categories,
    runs repair tasks, generates a markdown report, and prints a recommendation.
    """
    parser = argparse.ArgumentParser(description="Run repair model bakeoff")
    parser.add_argument(
        "--models",
        help="Comma-separated model names to evaluate (default: all)",
    )
    parser.add_argument(
        "--fixtures",
        help="Comma-separated fixture categories to include (default: all)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scripts/spec_refinement/evaluation/results/REPAIR_MODEL_SELECTION.md"),
        help="Path for the markdown report",
    )

    args = parser.parse_args()

    fixtures = _load_fixtures()
    category_filter: set[FixtureCategory] | None = None
    if args.fixtures:
        category_filter = {
            FixtureCategory(name.strip().lower())
            for name in args.fixtures.split(",")
            if name.strip()
        }
    fixtures = _filter_fixtures(fixtures, category_filter)
    if not fixtures:
        raise SystemExit("No fixtures selected for bakeoff.")

    _index_fixtures(fixtures)

    model_names = [name.strip() for name in args.models.split(",")] if args.models else None
    models = _select_models(model_names)
    if not models:
        raise SystemExit("No models selected for bakeoff.")

    with tempfile.TemporaryDirectory(prefix="repair-bakeoff-workspace-") as temp_dir:
        workspace = Path(temp_dir)
        results = run_bakeoff(fixtures, models, workspace)

    generate_report(results, args.output)

    stats = aggregate_results(results)
    recommendation = _recommend_model(stats)
    print(f"Bakeoff complete. Report: {args.output}")
    print(recommendation)


if __name__ == "__main__":
    main()
