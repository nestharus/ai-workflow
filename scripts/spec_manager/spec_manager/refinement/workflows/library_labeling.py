"""Library labeling and charter generation workflow helpers for Phase 2."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.formats import (
    EVIDENCE_POINTER_RE,
    FileSummary,
    LibraryCharter,
    LibraryEvent,
    LibraryEventType,
    _strip_code_fences,
    build_evidence_pointer,
    migrate_pointers_to_new_format,
    normalize_compound_pointers,
    parse_concern_assignment_judge,
    parse_file_summary,
    parse_library_labeler_output,
    parse_library_synthesis,
)
from spec_manager.refinement.progress import ProgressTracker
from spec_manager.refinement.repair import ArtifactType, get_repair_model, repair_artifact
from spec_manager.refinement.validation_utils import build_file_id_lookup, build_section_id_lookup
from spec_manager.refinement.workspace import WorkspaceManager

MAX_WORKERS = 4
LIB_ID_PATTERN = re.compile(r"^LIB-(\d{4})$")
logger = logging.getLogger(__name__)


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
        # Strip code fences before parsing - LLMs often wrap JSON in markdown
        cleaned = _strip_code_fences(payload)
        data = json.loads(cleaned)
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
        "candidate_labels": [
            {
                "label": label.get("label"),
                "sections": label.get("sections", []),
                "confidence": label.get("confidence", 0.0),
                "rationale": label.get("rationale", ""),
            }
            for label in candidate_labels
        ],
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


def build_library_shapes(file_labels: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build multi-label shape distributions from file labels.

    Confidence values per file are normalized to sum to at most 1.0.

    Returns:
        {file_id: {lib_id: {confidence, sections, rationale}}}
    """
    shapes: dict[str, dict[str, Any]] = {}

    for file_id, data in file_labels.items():
        file_shape: dict[str, Any] = {}

        for label_entry in data.get("candidate_labels", []):
            label = str(label_entry.get("label", "")).strip()
            if not label:
                continue

            confidence = label_entry.get("confidence", 0.0)
            if not isinstance(confidence, (int, float)):
                confidence = 0.0

            file_shape[label] = {
                "confidence": confidence,
                "sections": label_entry.get("sections", []),
                "rationale": label_entry.get("rationale", ""),
            }

        if file_shape:
            total = sum(
                entry["confidence"]
                for entry in file_shape.values()
                if isinstance(entry.get("confidence"), (int, float))
            )
            if total > 1.0:
                for entry in file_shape.values():
                    if isinstance(entry.get("confidence"), (int, float)):
                        entry["confidence"] = round(entry["confidence"] / total, 4)
            shapes[file_id] = file_shape

    return shapes


def validate_library_shapes(shapes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate library shape distributions.

    Ensures:
    - Confidence values are between 0.0 and 1.0
    - Sum of confidences per file <= 1.0
    - All required fields are present
    """
    issues: list[dict[str, Any]] = []

    for file_id, file_shape in shapes.items():
        total_confidence = 0.0

        for lib_label, shape_data in file_shape.items():
            confidence = shape_data.get("confidence", 0.0)

            if not isinstance(confidence, (int, float)):
                issues.append(
                    {
                        "type": "invalid_confidence_type",
                        "file_id": file_id,
                        "lib_label": lib_label,
                        "message": f"Confidence must be numeric, got {type(confidence).__name__}",
                    }
                )
                continue

            if confidence < 0.0 or confidence > 1.0:
                issues.append(
                    {
                        "type": "confidence_out_of_range",
                        "file_id": file_id,
                        "lib_label": lib_label,
                        "confidence": confidence,
                        "message": "Confidence must be between 0.0 and 1.0",
                    }
                )

            if "sections" not in shape_data:
                issues.append(
                    {
                        "type": "missing_sections",
                        "file_id": file_id,
                        "lib_label": lib_label,
                        "message": "Shape entry missing sections field",
                    }
                )

            if "rationale" not in shape_data:
                issues.append(
                    {
                        "type": "missing_rationale",
                        "file_id": file_id,
                        "lib_label": lib_label,
                        "message": "Shape entry missing rationale field",
                    }
                )

            total_confidence += confidence

        if total_confidence > 1.0:
            issues.append(
                {
                    "type": "confidence_sum_exceeds_one",
                    "file_id": file_id,
                    "total_confidence": round(total_confidence, 3),
                    "message": f"Sum of confidences ({total_confidence:.3f}) exceeds 1.0",
                }
            )

    return issues


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
        "Use LIB-0001, LIB-0002, etc. for stable_internal_id and lib_id.",
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
        # Strip code fences before parsing JSON
        cleaned_output = _strip_code_fences(output)
        data = json.loads(cleaned_output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse refined labels: {exc}") from exc

    if not isinstance(data, list):
        raise TypeError("Refined labels output must be a JSON array.")

    from .library_synthesis import LIB_ID_RE

    allocated_ids = set(manager.state.allocated_library_ids)
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise TypeError(f"Refined label entry {index} is not an object.")
        for field in ("lib_id", "final_label", "stable_internal_id"):
            if field not in item:
                raise TypeError(f"Refined label missing required field: {field}")
        lib_id = str(item.get("lib_id", "")).strip()
        if not LIB_ID_RE.match(lib_id):
            raise ValueError(f"Invalid library id format: {lib_id}")
        if lib_id in allocated_ids:
            raise ValueError(f"Library id already allocated: {lib_id}")
        allocated_ids.add(lib_id)
        manager.state.register_library_id(lib_id)

    manager.save_state()

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
    manager: WorkspaceManager,
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
        "Evidence pointers must use [spec_snapshot/<relpath>::SEC-...] format.",
        "",
    ]

    if file_sections:
        lines.append("Evidence pointers to consider:")
        section_lookup_cache: dict[str, dict[str, str]] = {}
        for file_id, section in file_sections:
            if not section:
                continue
            if file_id not in section_lookup_cache:
                sections_data = manager.read_file_sections(file_id) or {}
                section_lookup_cache[file_id] = build_section_id_lookup(file_id, sections_data)
            resolved_section = section_lookup_cache[file_id].get(section, section)
            try:
                pointer = build_evidence_pointer(
                    file_id, resolved_section, manager.state.file_manifest
                )
            except KeyError as exc:
                logger.warning(
                    "Skipping evidence pointer for %s::%s (missing relpath): %s",
                    file_id,
                    resolved_section,
                    exc,
                )
                continue
            lines.append(f"- {pointer}")
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
            "- [spec_snapshot/<relpath>::SEC-...]",
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

    prompt = _build_charter_prompt(lib_def, file_ids, file_sections, summaries, manager)
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
    # Force the charter to use the requested lib_id. The LLM may return a
    # different ID (or multiple libraries), which causes duplicate lib_id
    # validation failures when multiple charters are collected.
    if charter.lib_id != lib_id:
        charter = LibraryCharter(
            lib_id=lib_id,
            intent=charter.intent,
            boundaries=charter.boundaries,
            responsibilities=charter.responsibilities,
            evidence_sources=charter.evidence_sources,
            overlap_resolutions=charter.overlap_resolutions,
        )
    file_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )
    normalized_sources: list[dict[str, Any]] = []
    for source in charter.evidence_sources:
        if not isinstance(source, dict):
            continue
        file_ref = source.get("file_id")
        resolved_file_id = (
            file_lookup.get(file_ref) if isinstance(file_ref, str) and file_ref else file_ref
        )
        sections = source.get("sections", [])
        if not isinstance(sections, list):
            sections = []
        normalized_sources.append(
            {
                "file_id": resolved_file_id,
                "sections": [str(section).strip() for section in sections if str(section).strip()],
            }
        )
    if normalized_sources:
        charter = LibraryCharter(
            lib_id=charter.lib_id,
            intent=charter.intent,
            boundaries=charter.boundaries,
            responsibilities=charter.responsibilities,
            evidence_sources=normalized_sources,
            overlap_resolutions=charter.overlap_resolutions,
        )

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
        # Strip code fences before parsing JSON
        cleaned_output = _strip_code_fences(output)
        data = json.loads(cleaned_output)
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
            new_lib_id = manager.state.allocate_library_id()
            if new_lib_id in charter_map:
                raise ValueError(f"Allocated library id already in use: {new_lib_id}")
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

            from .library_synthesis import _write_library_event

            created_event = LibraryEvent(
                event_type=LibraryEventType.LIBRARY_CREATED,
                timestamp=datetime.now().isoformat(),
                lib_id=new_lib_id,
                metadata={
                    "created_from": [lib_id_a, lib_id_b],
                    "initial_intent": new_charter.intent,
                    "initial_files": sorted(
                        {
                            str(source.get("file_id"))
                            for source in overlap_sources
                            if source.get("file_id")
                        }
                    ),
                },
                previous_state=None,
            )
            _write_library_event(manager.structure.libraries_dir / new_lib_id, created_event)

            split_rationale = rationale or "Overlap resolution created cross-cutting library."
            for source_lib_id in (lib_id_a, lib_id_b):
                split_event = LibraryEvent(
                    event_type=LibraryEventType.LIBRARY_SPLIT,
                    timestamp=datetime.now().isoformat(),
                    lib_id=source_lib_id,
                    metadata={
                        "source_lib_id": source_lib_id,
                        "target_lib_ids": [new_lib_id],
                        "rationale": split_rationale,
                    },
                    previous_state=None,
                )
                _write_library_event(manager.structure.libraries_dir / source_lib_id, split_event)
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


def _extract_concerns_from_summary(summary: FileSummary, file_id: str) -> list[dict[str, Any]]:
    concerns: list[dict[str, Any]] = []

    def _build_text(item: dict[str, Any]) -> str:
        name = str(item.get("name", "")).strip()
        intent = str(item.get("intent", "")).strip()
        if name and intent:
            return f"{name} | {intent}"
        if name:
            return name
        if intent:
            return intent
        return ""

    def _append(items: list[dict[str, Any]], concern_type: str) -> None:
        for index, item in enumerate(items, start=1):
            text = (
                _build_text(item)
                if concern_type != "responsibility"
                else str(item.get("description", "")).strip()
            )
            if not text:
                text = "Unspecified concern"
            concern_id = f"{file_id}:{concern_type}:{index:03d}"
            evidence = item.get("evidence", [])
            if not isinstance(evidence, list):
                evidence = []
            evidence = [str(pointer).strip() for pointer in evidence if str(pointer).strip()]
            concerns.append(
                {
                    "concern_id": concern_id,
                    "file_id": file_id,
                    "concern_type": concern_type,
                    "concern_text": text,
                    "evidence": evidence,
                }
            )

    _append(summary.algorithms, "algorithm")
    _append(summary.components, "component")
    _append(summary.workflows, "workflow")
    _append(summary.candidate_responsibilities, "responsibility")

    return concerns


def _load_summary_concerns(manager: WorkspaceManager) -> list[dict[str, Any]]:
    concerns: list[dict[str, Any]] = []
    summary_files = sorted(manager.structure.summaries_dir.glob("*.what.md"))
    for summary_path in summary_files:
        file_id = summary_path.stem.replace(".what", "")
        content = summary_path.read_text(encoding="utf-8")
        normalized = migrate_pointers_to_new_format(content, manager)
        parsed = parse_file_summary(normalized)
        if parsed.file_id and parsed.file_id != "unknown":
            file_id = parsed.file_id
        concerns.extend(_extract_concerns_from_summary(parsed, file_id))
    return concerns


def _build_library_index_fallback(charters: list[LibraryCharter]) -> str:
    lines = ["# Library Index", ""]
    for charter in charters:
        intent = charter.intent or "Intent not provided"
        lines.append(f"- {charter.lib_id}: {intent}")
    return "\n".join(lines).strip() + "\n"


def _format_charter_fallback(charter: LibraryCharter) -> str:
    lines = [f"### {charter.lib_id}", "#### Intent", charter.intent or "", ""]
    lines.extend(["#### Boundaries", charter.boundaries or "", ""])
    lines.append("#### Responsibilities")
    if charter.responsibilities:
        for item in charter.responsibilities:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("#### Evidence")
    if charter.evidence_sources:
        for source in charter.evidence_sources:
            file_id = source.get("file_id", "")
            sections = source.get("sections", [])
            if isinstance(sections, list) and sections:
                for section in sections:
                    lines.append(f"- [{file_id}::{section}]")
            elif file_id:
                lines.append(f"- [{file_id}::]")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def judge_concern_assignments(
    charters: list[LibraryCharter], manager: WorkspaceManager
) -> dict[str, Any]:
    """Run concern assignment judge across all .what.md summaries."""
    issues: list[dict[str, Any]] = []

    concerns = _load_summary_concerns(manager)

    index_path = manager.structure.libraries_dir / "library_index.md"
    if index_path.exists():
        library_index = index_path.read_text(encoding="utf-8")
    else:
        library_index = _build_library_index_fallback(charters)

    charter_texts: list[str] = []
    library_ids = set(re.findall(r"\bLIB-\d{4}\b", library_index))
    for charter in charters:
        charter_path = manager.structure.libraries_dir / charter.lib_id / "charter.md"
        if charter_path.exists():
            charter_text = charter_path.read_text(encoding="utf-8")
        else:
            charter_text = _format_charter_fallback(charter)
        charter_texts.append(migrate_pointers_to_new_format(charter_text, manager))

    if not library_ids:
        library_ids = {charter.lib_id for charter in charters}

    library_shapes = manager.read_library_shapes()

    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "Return ONLY valid JSON. No preamble, no code fences.",
        "",
        "SCHEMA:",
        "{",
        '  "assignments": [',
        "    {",
        '      "concern_id": "string",',
        '      "file_id": "string",',
        '      "concern_type": "algorithm|component|workflow|responsibility",',
        '      "concern_text": "string",',
        '      "assigned_to": ["LIB-0001", "LIB-0002"],',
        '      "confidence": 0.85,',
        '      "rationale": "string"',
        "    }",
        "  ],",
        '  "gaps": [',
        "    {",
        '      "concern_id": "string",',
        '      "file_id": "string",',
        '      "concern_type": "string",',
        '      "concern_text": "string",',
        '      "gap_type": "out_of_scope|ambiguous",',
        '      "rationale": "string"',
        "    }",
        "  ],",
        '  "decisions": [',
        "    {",
        '      "concern_id": "string",',
        '      "file_id": "string",',
        '      "concern_type": "string",',
        '      "concern_text": "string",',
        '      "decision": "deferred|needs_clarification",',
        '      "rationale": "string"',
        "    }",
        "  ]",
        "}",
        "",
        "RULES:",
        "- Every concern must appear in exactly one of: assignments, gaps, decisions.",
        "- assigned_to must reference valid lib_id values from the library index.",
        "- Confidence must be between 0.0 and 1.0.",
        "- Rationale must include evidence pointers using [spec_snapshot/<relpath>::SEC-...]",
        "- No concerns can be silently dropped.",
        "",
        "## LIBRARY INDEX",
        library_index.strip(),
        "",
        "## LIBRARY CHARTERS",
    ]
    lines.extend(charter_texts or ["(No charters provided)"])
    lines.extend(
        [
            "",
            "## MULTI-LABEL SHAPES",
            json.dumps(library_shapes, indent=2),
            "",
            "## CONCERNS TO JUDGE",
        ]
    )

    for concern in concerns:
        evidence = concern.get("evidence", [])
        if isinstance(evidence, list) and evidence:
            evidence_text = " ".join(evidence)
        else:
            evidence_text = "[no_evidence]"
        lines.append(
            f"- {concern['file_id']}::{concern['concern_type']}::{concern['concern_id']} - "
            f"{concern['concern_text']} {evidence_text}"
        )

    prompt = "\n".join(lines)

    try:
        output = run_agent(
            agent_name="chatgpt-concern-assignment-judge",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        return {
            "assignments": [],
            "gaps": [],
            "decisions": [],
            "issues": [
                {
                    "type": "agent_error",
                    "message": f"Concern assignment judge failed: {exc}",
                },
                *issues,
            ],
        }

    if isinstance(output, BaseModel):
        output = output.model_dump_json()

    try:
        parsed = parse_concern_assignment_judge(output)
    except Exception as exc:
        return {
            "assignments": [],
            "gaps": [],
            "decisions": [],
            "issues": [
                {
                    "type": "parse_error",
                    "message": f"Failed to parse concern assignment output: {exc}",
                },
                *issues,
            ],
        }

    issues.extend(parsed.get("issues", []))

    for index, item in enumerate(parsed.get("assignments", [])):
        if not isinstance(item, dict):
            continue
        assigned_to = item.get("assigned_to", [])
        invalid_targets = [lib_id for lib_id in assigned_to if lib_id and lib_id not in library_ids]
        if invalid_targets:
            issues.append(
                {
                    "type": "invalid_assignment_target",
                    "index": index,
                    "lib_ids": invalid_targets,
                    "message": "Assignment references unknown library ids.",
                }
            )

    return {
        "assignments": parsed.get("assignments", []),
        "gaps": parsed.get("gaps", []),
        "decisions": parsed.get("decisions", []),
        "issues": issues,
    }


def _write_concern_evidence(judge_result: dict[str, Any], manager: WorkspaceManager) -> Path:
    pass_04_dir = manager.structure.intermediates_dir / "pass_04"
    pass_04_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = pass_04_dir / "evidence.jsonl"

    records: list[dict[str, Any]] = []
    timestamp = datetime.now().isoformat()

    for gap in judge_result.get("gaps", []):
        records.append(
            {
                "type": "GAP",
                "gap_type": gap.get("gap_type"),
                "concern_id": gap.get("concern_id"),
                "file_id": gap.get("file_id"),
                "concern_type": gap.get("concern_type"),
                "concern_text": gap.get("concern_text"),
                "rationale": gap.get("rationale"),
                "timestamp": timestamp,
            }
        )

    for decision in judge_result.get("decisions", []):
        records.append(
            {
                "type": "DEC",
                "decision": decision.get("decision"),
                "concern_id": decision.get("concern_id"),
                "file_id": decision.get("file_id"),
                "concern_type": decision.get("concern_type"),
                "concern_text": decision.get("concern_text"),
                "rationale": decision.get("rationale"),
                "timestamp": timestamp,
            }
        )

    if records:
        with evidence_path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record))
                handle.write("\n")

    return evidence_path


def _validate_concern_coverage(
    judge_result: dict[str, Any], manager: WorkspaceManager
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    file_concerns = {item["concern_id"] for item in _load_summary_concerns(manager)}
    judged_concerns: set[str] = set()
    for bucket in ("assignments", "gaps", "decisions"):
        for item in judge_result.get(bucket, []):
            if isinstance(item, dict) and item.get("concern_id"):
                judged_concerns.add(str(item.get("concern_id")))

    missing = sorted(file_concerns - judged_concerns)
    extra = sorted(judged_concerns - file_concerns)

    if missing:
        issues.append(
            {
                "type": "concern_assignment_missing",
                "missing": missing,
                "message": "Concerns from summaries missing in judge output.",
            }
        )
    if extra:
        issues.append(
            {
                "type": "concern_assignment_extra",
                "extra": extra,
                "message": "Judge output contains unknown concerns.",
            }
        )

    return issues
