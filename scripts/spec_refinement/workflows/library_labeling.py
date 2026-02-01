"""Library labeling and charter generation workflow helpers for Phase 2."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from scripts.spec_refinement.workspace import WorkspaceManager

from .agent_utils import run_agent
from .formats import (
    EVIDENCE_POINTER_RE,
    LibraryCharter,
    normalize_compound_pointers,
    parse_library_labeler_output,
    parse_library_synthesis,
)
from .progress import ProgressTracker
from .repair import ArtifactType, get_repair_model, repair_artifact

MAX_WORKERS = 4
LIB_ID_PATTERN = re.compile(r"^lib_(\d{3})$")


def _build_label_prompt(file_id: str, summary: str) -> str:
    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return ONLY valid JSON. No preamble, no code fences.",
        "",
        "REQUIRED SCHEMA:",
        "{"
        '  "file_id": "F####",'
        '  "candidate_labels": ['
        '    {"label": "string", "sections": ["string"], "confidence": 0.0, "rationale": "string"}'
        "  ],"
        '  "uncertain_labels": ['
        '    {"label": "string", "rationale": "string"}'
        "  ]"
        "}",
        "",
        "REQUIRED RULES:",
        "- Classify file into 0-N candidate library labels",
        "- file_id MUST match the input file ID",
        "- Labels MUST be capability-based (what the system does), not type-based",
        "- Each label MUST include sections that justify it",
        "- Sections MUST use [F####::SECTION] format",
        "- Confidence MUST be between 0.0 and 1.0",
        "- Each candidate label MUST include a rationale",
        "- Uncertain labels MUST include label and rationale",
        "- Place labels with confidence < 0.5 in uncertain_labels",
        "",
        "FORBIDDEN:",
        "- Labels without justifying sections",
        "- Invalid confidence values",
        "",
        "## INPUT DATA",
        "",
        f"File ID: {file_id}",
        "",
        "File Summary:",
        summary,
        "",
        "## OUTPUT FORMAT",
        "",
        "Example payload:",
        "{",
        '  "file_id": "F0001",',
        '  "candidate_labels": [',
        "    {",
        '      "label": "Request Intake",',
        '      "sections": ["[F0001::INTRO]"],',
        '      "confidence": 0.82,',
        '      "rationale": "Summary describes request ingestion responsibilities."',
        "    }",
        "  ],",
        '  "uncertain_labels": [',
        "    {",
        '      "label": "Rate Limiting",',
        '      "rationale": "Only indirect references; unclear ownership."',
        "    }",
        "  ]",
        "}",
    ]
    return "\n".join(lines)


def _parse_label_output(payload: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return {}, [
            {
                "type": "invalid_json",
                "message": f"JSON decode error: {exc}",
            }
        ]

    if not isinstance(data, dict):
        return {}, [
            {
                "type": "invalid_payload",
                "message": "Expected JSON object at top level.",
            }
        ]

    required_fields = ("file_id", "candidate_labels", "uncertain_labels")
    for field in required_fields:
        if field not in data:
            issues.append(
                {
                    "type": "missing_field",
                    "field": field,
                    "message": f"Missing required field: {field}",
                }
            )
            continue
        if field == "file_id":
            if not isinstance(data.get(field), str):
                issues.append(
                    {
                        "type": "invalid_field_type",
                        "field": field,
                        "message": "Field file_id must be a string.",
                    }
                )
            continue
        if not isinstance(data.get(field), list):
            issues.append(
                {
                    "type": "invalid_field_type",
                    "field": field,
                    "message": f"Field {field} must be a list.",
                }
            )

    return data, issues


def label_file_to_libraries(
    file_id: str, summary_path: Path, manager: WorkspaceManager
) -> dict[str, Any]:
    """Label a single file summary into candidate libraries."""
    summary = summary_path.read_text(encoding="utf-8")
    prompt = _build_label_prompt(file_id, summary)
    format_evidence: list[dict[str, Any]] = []

    try:
        output = run_agent(
            agent_name="glm-file-library-labeler",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        return {
            "file_id": file_id,
            "candidate_labels": [],
            "uncertain_labels": [],
            "raw_output": "",
            "issues": [
                {
                    "type": "agent_error",
                    "message": f"Agent execution failed: {exc}",
                }
            ],
        }

    data, issues = _parse_label_output(output)
    output_text = output

    if issues:
        try:
            repaired, repair_evidence = repair_artifact(
                output=output_text,
                errors=issues,
                allowlists={
                    "file_ids": list(manager.state.file_manifest.keys()),
                    "sections": manager.state.section_manifest,
                },
                artifact_type=ArtifactType.LIBRARY_LABELS,
                model_override=get_repair_model(),
                manager=manager,
            )
            format_evidence.extend(repair_evidence)
            repaired_data = parse_library_labeler_output(repaired, format_evidence)
            output_text = repaired
            data = repaired_data
            issues = []
        except Exception as exc:
            issues.append(
                {
                    "type": "repair_failed",
                    "message": f"Library label repair failed: {exc}",
                }
            )

    candidate_labels = data.get("candidate_labels") if isinstance(data, dict) else None
    uncertain_labels = data.get("uncertain_labels") if isinstance(data, dict) else None

    if not isinstance(candidate_labels, list):
        candidate_labels = []
    if not isinstance(uncertain_labels, list):
        uncertain_labels = []

    return {
        "file_id": file_id,
        "candidate_labels": candidate_labels,
        "uncertain_labels": uncertain_labels,
        "raw_output": output_text,
        "issues": issues,
        "format_evidence": format_evidence,
    }


def label_all_files(manager: WorkspaceManager) -> dict[str, Any]:
    """Label all summaries with candidate library labels."""
    summary_files = sorted(manager.structure.summaries_dir.glob("*.what.md"))
    tracker = ProgressTracker(
        total=len(summary_files),
        description="Labeling files",
        manager=manager,
    )

    file_labels: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    format_evidence: list[dict[str, Any]] = []

    if summary_files:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    label_file_to_libraries,
                    summary_path.stem.replace(".what", ""),
                    summary_path,
                    manager,
                ): summary_path
                for summary_path in summary_files
            }
            for future in as_completed(futures):
                result = future.result()
                format_evidence.extend(result.get("format_evidence", []))
                file_id = result.get("file_id")
                if not file_id:
                    continue
                file_labels[file_id] = {
                    "candidate_labels": result.get("candidate_labels", []),
                    "uncertain_labels": result.get("uncertain_labels", []),
                }
                if result.get("issues"):
                    issues.extend(result["issues"])
                tracker.update(status=file_id)
    else:
        tracker.finish()

    if summary_files:
        tracker.finish()

    total_labels = sum(len(data.get("candidate_labels", [])) for data in file_labels.values())
    uncertain_count = sum(len(data.get("uncertain_labels", [])) for data in file_labels.values())

    manager.structure.libraries_dir.mkdir(parents=True, exist_ok=True)
    labels_path = manager.structure.libraries_dir / "file_labels.json"
    labels_path.write_text(json.dumps(file_labels, indent=2), encoding="utf-8")

    return {
        "file_labels": file_labels,
        "files_labeled": len(file_labels),
        "total_labels": total_labels,
        "uncertain_count": uncertain_count,
        "issues": issues,
        "format_evidence": format_evidence,
    }


def _parse_section_pointer(value: str, default_file_id: str | None = None) -> list[tuple[str, str]]:
    matches = EVIDENCE_POINTER_RE.findall(value)
    if matches:
        return [(file_id.strip(), section.strip()) for file_id, section in matches]
    if "::" in value:
        file_part, section_part = value.split("::", 1)
        file_part = file_part.strip()
        section_part = section_part.strip()
        if file_part and section_part:
            return [(file_part, section_part)]
    if default_file_id and value.strip():
        return [(default_file_id, value.strip())]
    return []


def _collect_label_graph(file_labels: dict[str, Any]) -> dict[str, dict[str, Any]]:
    label_graph: dict[str, dict[str, Any]] = {}
    for file_id, data in file_labels.items():
        for entry in data.get("candidate_labels", []):
            label = str(entry.get("label", "")).strip()
            if not label:
                continue
            node = label_graph.setdefault(
                label,
                {
                    "file_sections": [],
                    "files": set(),
                },
            )
            sections = entry.get("sections", [])
            if isinstance(sections, list) and sections:
                for section in sections:
                    for file_ref, section_ref in _parse_section_pointer(
                        str(section), default_file_id=file_id
                    ):
                        node["file_sections"].append((file_ref, section_ref))
                        node["files"].add(file_ref)
            else:
                node["files"].add(file_id)

    for _, node in label_graph.items():
        node["count"] = len(node["files"])
    return label_graph


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = left & right
    union = left | right
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _dedupe_pairs(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    output: list[tuple[str, str]] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def aggregate_labels(file_labels: dict[str, Any]) -> dict[str, Any]:
    """Aggregate file labels into candidate library clusters."""
    label_graph = _collect_label_graph(file_labels)
    labels = sorted(label_graph.keys())

    similarities: dict[tuple[str, str], float] = {}
    adjacency: dict[str, set[str]] = {label: set() for label in labels}

    for left, right in combinations(labels, 2):
        left_files = label_graph[left]["files"]
        right_files = label_graph[right]["files"]
        similarity = _jaccard_similarity(left_files, right_files)
        if similarity > 0.0:
            similarities[(left, right)] = similarity
        if similarity > 0.3:
            adjacency[left].add(right)
            adjacency[right].add(left)

    visited: set[str] = set()
    label_clusters: list[dict[str, Any]] = []
    singleton_labels: list[dict[str, Any]] = []

    for label in labels:
        if label in visited:
            continue
        stack = [label]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)

        if len(component) == 1:
            singleton_labels.append(
                {
                    "label": component[0],
                    "files": sorted(label_graph[component[0]]["files"]),
                }
            )
            continue

        component_files: set[str] = set()
        component_sections: list[tuple[str, str]] = []
        pair_scores: list[float] = []
        for item in component:
            component_files.update(label_graph[item]["files"])
            component_sections.extend(label_graph[item]["file_sections"])
        for left, right in combinations(sorted(component), 2):
            score = similarities.get((left, right)) or similarities.get((right, left))
            if score is not None:
                pair_scores.append(score)
        similarity_score = sum(pair_scores) / len(pair_scores) if pair_scores else 0.0

        label_clusters.append(
            {
                "labels": sorted(component),
                "files": sorted(component_files),
                "file_sections": _dedupe_pairs(component_sections),
                "similarity_score": round(similarity_score, 3),
            }
        )

    average_cluster_size = (
        sum(len(cluster["labels"]) for cluster in label_clusters) / len(label_clusters)
        if label_clusters
        else 0.0
    )

    return {
        "label_clusters": label_clusters,
        "singleton_labels": singleton_labels,
        "metadata": {
            "total_clusters": len(label_clusters),
            "singleton_count": len(singleton_labels),
            "average_cluster_size": round(average_cluster_size, 2),
        },
    }


def refine_library_labels(
    label_clusters: dict[str, Any], manager: WorkspaceManager
) -> list[dict[str, Any]]:
    """Refine label clusters into stable library definitions."""
    clusters = label_clusters.get("label_clusters", [])
    singletons = label_clusters.get("singleton_labels", [])

    lines = [
        "Refine aggregated label clusters into stable libraries.",
        "Return ONLY valid JSON array. No preamble, no code fences.",
        "Each item must include: lib_id, final_label, merged_from, split_notes, "
        "stable_internal_id.",
        "Use lib_001, lib_002, etc. for stable_internal_id and lib_id.",
        "",
        "Clusters:",
    ]

    if clusters:
        for index, cluster in enumerate(clusters, start=1):
            labels = ", ".join(cluster.get("labels", []))
            file_count = len(cluster.get("files", []))
            similarity = cluster.get("similarity_score", 0.0)
            lines.append(
                f"- Cluster {index}: labels=[{labels}] files={file_count} similarity={similarity}"
            )
    else:
        lines.append("- None")

    lines.append("")
    lines.append("Singleton Labels:")
    if singletons:
        for singleton in singletons:
            label = singleton.get("label", "")
            file_count = len(singleton.get("files", []))
            lines.append(f"- {label} (files={file_count})")
    else:
        lines.append("- None")

    prompt = "\n".join(lines)

    output = run_agent(
        agent_name="opus-library-label-refiner",
        prompt=prompt,
        workspace=manager.workspace_path,
    )

    if isinstance(output, BaseModel):
        output = output.model_dump_json()

    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse refined labels: {exc}") from exc

    if not isinstance(data, list):
        raise TypeError("Refined labels output must be a JSON array.")

    from .library_synthesis import LIB_ID_RE

    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise TypeError(f"Refined label entry {index} is not an object.")
        for field in ("lib_id", "final_label", "stable_internal_id"):
            if field not in item:
                raise TypeError(f"Refined label missing required field: {field}")
        lib_id = str(item.get("lib_id", "")).strip()
        if not LIB_ID_RE.match(lib_id):
            raise ValueError(f"Invalid library id format: {lib_id}")

    manager.structure.libraries_dir.mkdir(parents=True, exist_ok=True)
    refined_path = manager.structure.libraries_dir / "refined_labels.json"
    refined_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return data


def _resolve_library_files(
    lib_def: dict[str, Any], file_labels: dict[str, Any]
) -> tuple[list[str], list[tuple[str, str]]]:
    merged_from = lib_def.get("merged_from")
    if isinstance(merged_from, list) and merged_from:
        target_labels = [str(label).strip() for label in merged_from if str(label).strip()]
    else:
        final_label = str(lib_def.get("final_label", "")).strip()
        target_labels = [final_label] if final_label else []

    file_ids: set[str] = set()
    file_sections: list[tuple[str, str]] = []

    for file_id, data in file_labels.items():
        for entry in data.get("candidate_labels", []):
            label = str(entry.get("label", "")).strip()
            if label not in target_labels:
                continue
            file_ids.add(file_id)
            sections = entry.get("sections", [])
            if isinstance(sections, list) and sections:
                for section in sections:
                    for file_ref, section_ref in _parse_section_pointer(
                        str(section), default_file_id=file_id
                    ):
                        file_sections.append((file_ref, section_ref))
            else:
                file_sections.append((file_id, ""))

    return sorted(file_ids), _dedupe_pairs(file_sections)


def _build_charter_prompt(
    lib_def: dict[str, Any],
    file_ids: list[str],
    file_sections: list[tuple[str, str]],
    summaries: dict[str, str],
) -> str:
    lib_id = lib_def.get("lib_id", "")
    final_label = lib_def.get("final_label", "")
    merged_from = lib_def.get("merged_from", [])
    merged_text = ", ".join(str(label) for label in merged_from) if merged_from else "None"

    lines = [
        "Synthesize a single library charter for Phase 2 using the summaries below.",
        f"Target Library ID: {lib_id}",
        f"Target Label: {final_label}",
        f"Merged From: {merged_text}",
        "Use the exact markdown structure below with headings and bullet lists.",
        "Library IDs must match the target library ID.",
        "Evidence pointers must use [FILE_ID::SECTION].",
        "",
    ]

    if file_sections:
        lines.append("Evidence pointers to consider:")
        for file_id, section in file_sections:
            if section:
                lines.append(f"- [{file_id}::{section}]")
        lines.append("")

    lines.extend(
        [
            "## Library Index",
            f"- {lib_id}: <intent>",
            "",
            "## Library Charters",
            f"### {lib_id}",
            "#### Intent",
            "<intent text>",
            "",
            "#### Boundaries",
            "<boundaries text>",
            "",
            "#### Responsibilities",
            "- <responsibility>",
            "",
            "#### Evidence",
            "- [FILE_ID::SECTION]",
            "",
            "#### Overlap Resolutions",
            "- <overlap description> -> <decision>",
            "",
            "---",
            "",
            "# Summaries",
        ]
    )

    for file_id in file_ids:
        summary = summaries.get(file_id)
        if not summary:
            continue
        lines.append(f"## {file_id}")
        lines.append(summary)
        lines.append("")

    return "\n".join(lines)


def generate_library_charter(
    lib_def: dict[str, Any],
    file_labels: dict[str, Any],
    summaries: dict[str, str],
    manager: WorkspaceManager,
) -> dict[str, Any]:
    """Generate a charter for a single library definition."""
    lib_id = str(lib_def.get("lib_id", "")).strip()
    file_ids, file_sections = _resolve_library_files(lib_def, file_labels)

    prompt = _build_charter_prompt(lib_def, file_ids, file_sections, summaries)
    try:
        output = run_agent(
            agent_name="opus-library-synthesizer",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        return {
            "lib_id": lib_id,
            "charter": None,
            "issues": [
                {
                    "type": "agent_error",
                    "message": f"Agent execution failed: {exc}",
                }
            ],
        }

    if isinstance(output, BaseModel):
        output = output.model_dump_json()

    output = normalize_compound_pointers(output)

    try:
        charters, _ = parse_library_synthesis(output)
    except Exception as exc:
        return {
            "lib_id": lib_id,
            "charter": None,
            "issues": [
                {
                    "type": "parse_error",
                    "message": f"Failed to parse charter output: {exc}",
                }
            ],
        }

    if not charters:
        return {
            "lib_id": lib_id,
            "charter": None,
            "issues": [
                {
                    "type": "no_charter",
                    "message": "No charter returned from synthesizer.",
                }
            ],
        }

    charter = next((item for item in charters if item.lib_id == lib_id), charters[0])

    from .library_synthesis import (
        _validate_evidence_sources,
        _validate_library_ids,
        _validate_overlap_resolutions,
    )

    issues: list[dict[str, Any]] = []
    format_evidence: list[dict[str, Any]] = []
    issues.extend(_validate_library_ids([charter]))
    issues.extend(_validate_evidence_sources([charter], manager))
    issues.extend(_validate_overlap_resolutions([charter]))

    if issues:
        try:
            repaired_output, repair_evidence = repair_artifact(
                output=output,
                errors=issues,
                allowlists={
                    "file_ids": list(manager.state.file_manifest.keys()),
                    "library_ids": [lib_id],
                },
                artifact_type=ArtifactType.CHARTER,
                model_override=get_repair_model(),
                manager=manager,
            )
            format_evidence.extend(repair_evidence)
            repaired_charters, _ = parse_library_synthesis(repaired_output)
            if repaired_charters:
                repaired_charter = next(
                    (item for item in repaired_charters if item.lib_id == lib_id),
                    repaired_charters[0],
                )
                repaired_issues: list[dict[str, Any]] = []
                repaired_issues.extend(_validate_library_ids([repaired_charter]))
                repaired_issues.extend(_validate_evidence_sources([repaired_charter], manager))
                repaired_issues.extend(_validate_overlap_resolutions([repaired_charter]))
                if not repaired_issues:
                    charter = repaired_charter
                    issues = []
        except Exception as exc:
            issues.append(
                {
                    "type": "repair_failed",
                    "message": f"Charter repair failed: {exc}",
                }
            )

    return {
        "lib_id": lib_id,
        "charter": charter,
        "issues": issues,
        "format_evidence": format_evidence,
    }


class CharterResults(list[LibraryCharter]):
    """List of generated charters with associated issues."""

    def __init__(
        self,
        charters: list[LibraryCharter],
        issues: list[dict[str, Any]],
        format_evidence: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize charters list and attach issues.

        Args:
            charters: List of library charters.
            issues: List of issues from charter generation.
            format_evidence: Evidence records from format repair/extraction.
        """
        super().__init__(charters)
        self.issues = issues
        self.format_evidence = format_evidence or []


def generate_all_charters(
    refined_labels: list[dict[str, Any]],
    file_labels: dict[str, Any],
    manager: WorkspaceManager,
) -> list[LibraryCharter]:
    """Generate charters in parallel for all refined libraries."""
    summaries: dict[str, str] = {}
    for summary_path in manager.structure.summaries_dir.glob("*.what.md"):
        file_id = summary_path.stem.replace(".what", "")
        summaries[file_id] = summary_path.read_text(encoding="utf-8")

    tracker = ProgressTracker(
        total=len(refined_labels),
        description="Generating charters",
        manager=manager,
    )

    issues: list[dict[str, Any]] = []
    format_evidence: list[dict[str, Any]] = []
    charters: list[LibraryCharter] = []

    if refined_labels:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    generate_library_charter,
                    lib_def,
                    file_labels,
                    summaries,
                    manager,
                ): lib_def
                for lib_def in refined_labels
            }
            for future in as_completed(futures):
                result = future.result()
                lib_id = result.get("lib_id", "")
                if result.get("issues"):
                    issues.extend(result["issues"])
                format_evidence.extend(result.get("format_evidence", []))
                charter = result.get("charter")
                if isinstance(charter, LibraryCharter):
                    charters.append(charter)
                tracker.update(status=lib_id)
    else:
        tracker.finish()

    if refined_labels:
        tracker.finish()

    return CharterResults(charters, issues, format_evidence)


def detect_overlaps(charters: list[LibraryCharter]) -> list[tuple[str, str, float]]:
    """Detect pairwise overlaps based on shared evidence sources."""
    overlaps: list[tuple[str, str, float]] = []
    if len(charters) < 2:
        return overlaps

    evidence_map: dict[str, set[str]] = {}
    for charter in charters:
        files = {source.get("file_id") for source in charter.evidence_sources}
        evidence_map[charter.lib_id] = {file_id for file_id in files if file_id}

    for left, right in combinations(charters, 2):
        files_left = evidence_map.get(left.lib_id, set())
        files_right = evidence_map.get(right.lib_id, set())
        if not files_left or not files_right:
            continue
        shared = files_left & files_right
        if not shared:
            continue
        overlap_score = len(shared) / min(len(files_left), len(files_right))
        if overlap_score > 0.3:
            overlaps.append((left.lib_id, right.lib_id, round(overlap_score, 3)))

    return overlaps


def resolve_overlap(
    lib_id_a: str,
    lib_id_b: str,
    charters: dict[str, LibraryCharter],
    manager: WorkspaceManager,
    overlap_score: float,
) -> dict[str, Any]:
    """Resolve overlap between two libraries."""
    charter_a = charters[lib_id_a]
    charter_b = charters[lib_id_b]

    prompt = "\n".join(
        [
            "Resolve the overlap between the following two libraries.",
            f"Overlap score: {overlap_score}",
            "Return ONLY valid JSON. No preamble, no code fences.",
            "",
            "Library A:",
            f"ID: {charter_a.lib_id}",
            f"Intent: {charter_a.intent}",
            f"Boundaries: {charter_a.boundaries}",
            "Evidence:",
            *[
                f"- [{src.get('file_id')}::{section}]"
                for src in charter_a.evidence_sources
                for section in src.get("sections", [])
            ],
            "",
            "Library B:",
            f"ID: {charter_b.lib_id}",
            f"Intent: {charter_b.intent}",
            f"Boundaries: {charter_b.boundaries}",
            "Evidence:",
            *[
                f"- [{src.get('file_id')}::{section}]"
                for src in charter_b.evidence_sources
                for section in src.get("sections", [])
            ],
        ]
    )

    output = run_agent(
        agent_name="glm-library-overlap-resolver",
        prompt=prompt,
        workspace=manager.workspace_path,
    )

    if isinstance(output, BaseModel):
        output = output.model_dump_json()

    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse overlap resolution: {exc}") from exc

    if not isinstance(data, dict):
        raise TypeError("Overlap resolution output must be a JSON object.")

    decision = data.get("decision")
    if decision not in {
        "assign_to_lib_A",
        "assign_to_lib_B",
        "create_cross_cutting",
        "mark_shared_boundary",
    }:
        raise ValueError(f"Invalid overlap decision: {decision}")

    return data


def _collect_evidence_file_ids(charter: LibraryCharter) -> set[str]:
    return {
        str(file_id) for source in charter.evidence_sources if (file_id := source.get("file_id"))
    }


def _collect_sections_by_file(charter: LibraryCharter) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for source in charter.evidence_sources:
        file_id = source.get("file_id")
        if not file_id:
            continue
        sections = source.get("sections", [])
        if not isinstance(sections, list):
            continue
        cleaned_sections = {str(section).strip() for section in sections if str(section).strip()}
        if not cleaned_sections:
            continue
        grouped.setdefault(file_id, set()).update(cleaned_sections)
    return grouped


def _resolve_overlap_files(
    resolution: dict[str, Any], charter_a: LibraryCharter, charter_b: LibraryCharter
) -> list[str]:
    files_a = _collect_evidence_file_ids(charter_a)
    files_b = _collect_evidence_file_ids(charter_b)
    shared_files = files_a & files_b

    affected_files = resolution.get("affected_files")
    if isinstance(affected_files, list):
        normalized = [str(item).strip() for item in affected_files if str(item).strip()]
        if normalized:
            return sorted(set(normalized))

    return sorted(shared_files)


def _build_overlap_evidence_sources(
    charter_a: LibraryCharter,
    charter_b: LibraryCharter,
    overlap_files: list[str],
) -> list[dict[str, Any]]:
    if not overlap_files:
        return []

    sections_a = _collect_sections_by_file(charter_a)
    sections_b = _collect_sections_by_file(charter_b)
    sources: list[dict[str, Any]] = []
    for file_id in overlap_files:
        sections = sorted(sections_a.get(file_id, set()) | sections_b.get(file_id, set()))
        if sections:
            sources.append({"file_id": file_id, "sections": sections})
    return sources


def _remove_overlap_evidence_sources(
    charter: LibraryCharter, overlap_files: list[str]
) -> list[dict[str, Any]]:
    if not overlap_files:
        return list(charter.evidence_sources)
    overlap_set = {file_id for file_id in overlap_files if file_id}
    if not overlap_set:
        return list(charter.evidence_sources)
    return [
        source for source in charter.evidence_sources if source.get("file_id") not in overlap_set
    ]


def _append_overlap_resolution(
    charter: LibraryCharter,
    description: str,
    decision: str,
    *,
    evidence_sources: list[dict[str, Any]] | None = None,
) -> LibraryCharter:
    updated_resolutions = list(charter.overlap_resolutions)
    updated_resolutions.append({"description": description, "decision": decision})
    return LibraryCharter(
        lib_id=charter.lib_id,
        intent=charter.intent,
        boundaries=charter.boundaries,
        responsibilities=charter.responsibilities,
        evidence_sources=evidence_sources
        if evidence_sources is not None
        else charter.evidence_sources,
        overlap_resolutions=updated_resolutions,
    )


def resolve_all_overlaps(
    charters: list[LibraryCharter], manager: WorkspaceManager
) -> list[dict[str, Any]]:
    """Resolve overlaps sequentially and update charter overlap resolutions."""
    overlap_pairs = detect_overlaps(charters)
    if not overlap_pairs:
        return []

    tracker = ProgressTracker(
        total=len(overlap_pairs),
        description="Resolving overlaps",
        manager=manager,
    )

    charter_map = {charter.lib_id: charter for charter in charters}
    original_ids = [charter.lib_id for charter in charters]
    max_lib_number = 0
    for lib_id in charter_map:
        match = LIB_ID_PATTERN.match(lib_id)
        if match:
            max_lib_number = max(max_lib_number, int(match.group(1)))
    next_lib_number = max_lib_number + 1
    new_charters: list[LibraryCharter] = []
    decisions: list[dict[str, Any]] = []

    for lib_id_a, lib_id_b, score in overlap_pairs:
        resolution = resolve_overlap(lib_id_a, lib_id_b, charter_map, manager, score)
        decision = str(resolution.get("decision", "")).strip()
        rationale = str(resolution.get("rationale", "")).strip()
        charter_a = charter_map[lib_id_a]
        charter_b = charter_map[lib_id_b]
        overlap_files = _resolve_overlap_files(resolution, charter_a, charter_b)

        decision_entry = {
            "lib_id_a": lib_id_a,
            "lib_id_b": lib_id_b,
            "decision": decision,
            "rationale": rationale,
            "affected_files": overlap_files,
            "overlap_score": score,
        }

        updated_evidence_a = charter_a.evidence_sources
        updated_evidence_b = charter_b.evidence_sources

        if decision == "assign_to_lib_A":
            updated_evidence_b = _remove_overlap_evidence_sources(charter_b, overlap_files)
        elif decision == "assign_to_lib_B":
            updated_evidence_a = _remove_overlap_evidence_sources(charter_a, overlap_files)
        elif decision == "create_cross_cutting":
            overlap_sources = _build_overlap_evidence_sources(charter_a, charter_b, overlap_files)
            while True:
                if next_lib_number > 999:
                    raise ValueError("Unable to allocate lib_### id for cross-cutting overlap.")
                new_lib_id = f"lib_{next_lib_number:03d}"
                next_lib_number += 1
                if new_lib_id not in charter_map:
                    break
            cross_cutting_description = f"Created from overlap between {lib_id_a} and {lib_id_b}"
            if rationale:
                cross_cutting_description = f"{cross_cutting_description}: {rationale}"
            new_charter = LibraryCharter(
                lib_id=new_lib_id,
                intent=f"TBD: cross-cutting concern between {lib_id_a} and {lib_id_b}.",
                boundaries=f"TBD: shared boundary across {lib_id_a} and {lib_id_b}.",
                responsibilities=[],
                evidence_sources=overlap_sources,
                overlap_resolutions=[
                    {
                        "description": cross_cutting_description,
                        "decision": decision,
                    }
                ],
            )
            charter_map[new_lib_id] = new_charter
            new_charters.append(new_charter)
            decision_entry["created_lib_id"] = new_lib_id
        elif decision == "mark_shared_boundary":
            pass
        else:
            raise ValueError(f"Unsupported overlap decision: {decision}")

        decisions.append(decision_entry)

        for lib_id, updated_evidence in (
            (lib_id_a, updated_evidence_a),
            (lib_id_b, updated_evidence_b),
        ):
            charter = charter_map[lib_id]
            other_id = lib_id_b if lib_id == lib_id_a else lib_id_a
            description = f"Overlap with {other_id}"
            if rationale:
                description = f"{description}: {rationale}"
            charter_map[lib_id] = _append_overlap_resolution(
                charter,
                description,
                decision,
                evidence_sources=updated_evidence,
            )

        tracker.update(status=f"{lib_id_a} vs {lib_id_b}")

    tracker.finish()

    charters[:] = [charter_map[lib_id] for lib_id in original_ids] + new_charters
    return decisions
