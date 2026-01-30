"""Library labeling and charter generation workflow helpers for Phase 2."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from scripts.spec_refinement.workspace import WorkspaceManager

from .agent_utils import run_agent
from .formats import EVIDENCE_POINTER_RE, LibraryCharter, normalize_compound_pointers, parse_library_synthesis
from .progress import ProgressTracker
from .repair import ArtifactType, repair_artifact

MAX_WORKERS = 4


def _build_label_prompt(file_id: str, summary: str) -> str:
    lines = [
        "Classify the following file summary into candidate library labels.",
        "Return ONLY valid JSON matching the schema. No preamble, no code fences.",
        "Labels must be capability-based (what the system does).",
        "Use evidence pointers from the summary in [FILE_ID::SECTION] format.",
        "Confidence scoring: 1.0 direct match, 0.8 strong inference, 0.6 possible, <0.5 uncertain.",
        "",
        "JSON Schema:",
        "{",
        "  \"candidate_labels\": [",
        "    {",
        "      \"label\": \"string\",",
        "      \"sections\": [\"[FILE_ID::SECTION]\"],",
        "      \"confidence\": 0.8,",
        "      \"rationale\": \"string\"",
        "    }",
        "  ],",
        "  \"uncertain_labels\": [",
        "    {",
        "      \"label\": \"string\",",
        "      \"rationale\": \"string\"",
        "    }",
        "  ]",
        "}",
        "",
        f"# File Summary: {file_id}",
        summary,
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

    for field in ("candidate_labels", "uncertain_labels"):
        if field not in data:
            issues.append(
                {
                    "type": "missing_field",
                    "field": field,
                    "message": f"Missing required field: {field}",
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

    if issues:
        try:
            repaired = repair_artifact(
                output=output,
                errors=issues,
                allowlists={
                    "file_ids": list(manager.state.file_manifest.keys()),
                    "sections": manager.state.section_manifest,
                },
                artifact_type=ArtifactType.LIBRARY_LABELS,
                manager=manager,
            )
            repaired_data, repaired_issues = _parse_label_output(repaired)
            if not repaired_issues:
                output = repaired
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
        "raw_output": output,
        "issues": issues,
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

    for label, node in label_graph.items():
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
        "Each item must include: lib_id, final_label, merged_from, split_notes, stable_internal_id.",
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

    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse refined labels: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("Refined labels output must be a JSON array.")

    from .library_synthesis import LIB_ID_RE

    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Refined label entry {index} is not an object.")
        for field in ("lib_id", "final_label", "stable_internal_id"):
            if field not in item:
                raise ValueError(f"Refined label missing required field: {field}")
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
    issues.extend(_validate_library_ids([charter]))
    issues.extend(_validate_evidence_sources([charter], manager))
    issues.extend(_validate_overlap_resolutions([charter]))

    if issues:
        try:
            repaired_output = repair_artifact(
                output=output,
                errors=issues,
                allowlists={
                    "file_ids": list(manager.state.file_manifest.keys()),
                    "library_ids": [lib_id],
                },
                artifact_type=ArtifactType.CHARTER,
                manager=manager,
            )
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
    }


class CharterResults(list):
    """List of generated charters with associated issues."""

    def __init__(self, charters: list[LibraryCharter], issues: list[dict[str, Any]]) -> None:
        super().__init__(charters)
        self.issues = issues


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
                charter = result.get("charter")
                if isinstance(charter, LibraryCharter):
                    charters.append(charter)
                tracker.update(status=lib_id)
    else:
        tracker.finish()

    if refined_labels:
        tracker.finish()

    return CharterResults(charters, issues)


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
            *[f"- [{src.get('file_id')}::{section}]" for src in charter_a.evidence_sources for section in src.get("sections", [])],
            "",
            "Library B:",
            f"ID: {charter_b.lib_id}",
            f"Intent: {charter_b.intent}",
            f"Boundaries: {charter_b.boundaries}",
            "Evidence:",
            *[f"- [{src.get('file_id')}::{section}]" for src in charter_b.evidence_sources for section in src.get("sections", [])],
        ]
    )

    output = run_agent(
        agent_name="glm-library-overlap-resolver",
        prompt=prompt,
        workspace=manager.workspace_path,
    )

    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse overlap resolution: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Overlap resolution output must be a JSON object.")

    decision = data.get("decision")
    if decision not in {
        "assign_to_lib_A",
        "assign_to_lib_B",
        "create_cross_cutting",
        "mark_shared_boundary",
    }:
        raise ValueError(f"Invalid overlap decision: {decision}")

    return data


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
    decisions: list[dict[str, Any]] = []

    for lib_id_a, lib_id_b, score in overlap_pairs:
        resolution = resolve_overlap(lib_id_a, lib_id_b, charter_map, manager, score)
        decisions.append(
            {
                "lib_id_a": lib_id_a,
                "lib_id_b": lib_id_b,
                "decision": resolution.get("decision"),
                "rationale": resolution.get("rationale", ""),
                "affected_files": resolution.get("affected_files", []),
                "overlap_score": score,
            }
        )

        for lib_id in (lib_id_a, lib_id_b):
            charter = charter_map[lib_id]
            description = (
                f"Overlap with {lib_id_b if lib_id == lib_id_a else lib_id_a}: "
                f"{resolution.get('rationale', '').strip()}"
            ).strip()
            updated_resolutions = list(charter.overlap_resolutions)
            updated_resolutions.append(
                {
                    "description": description,
                    "decision": resolution.get("decision", ""),
                }
            )
            charter_map[lib_id] = LibraryCharter(
                lib_id=charter.lib_id,
                intent=charter.intent,
                boundaries=charter.boundaries,
                responsibilities=charter.responsibilities,
                evidence_sources=charter.evidence_sources,
                overlap_resolutions=updated_resolutions,
            )

        tracker.update(status=f"{lib_id_a} vs {lib_id_b}")

    tracker.finish()

    charters[:] = [charter_map[charter.lib_id] for charter in charters]
    return decisions
