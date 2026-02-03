"""Phase 7 library structure review workflow for overlap and split detection.

This module scans stabilized spec indexes, builds TF-IDF similarity signals, and
returns in-memory overlap/split candidates for downstream review agents.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_similarity

from spec_manager.refinement.agent_utils import run_agent
from spec_manager.refinement.formats import LibraryEvent, LibraryEventType, parse_evidence_pointer
from spec_manager.refinement.progress import ProgressTracker
from spec_manager.refinement.repair import ArtifactType, get_repair_model, repair_artifact
from spec_manager.refinement.validation_utils import build_file_id_lookup
from spec_manager.refinement.workflows.library_synthesis import (
    _read_library_events,
    _rewrite_library_events,
    _write_library_event,
)
from spec_manager.refinement.workflows.spec_stabilization import (
    _extract_sections_with_positions,
    build_spec_index,
    extract_existing_id,
)
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager
from spec_manager.schemas.review_actions import (
    ReviewAction,
    ReviewActionsReport,
    generate_stable_action_ids,
    read_review_actions_json,
    validate_pointer_references,
    write_review_actions_json,
    write_review_actions_markdown,
)
from spec_manager.schemas.spec_indexes import SpecIndex

logger = logging.getLogger(__name__)

_REVIEW_ACTIONS_REPORT_TYPE = ReviewActionsReport
_TEXT_KINDS = {"requirement", "invariant"}
_DEFAULT_THRESHOLDS = {
    "overlap_similarity": 0.35,
    "min_shared_elements": 5,
    "split_silhouette": 0.3,
    "split_min_elements": 10,
}
_ELEMENT_ID_RE = re.compile(
    r"^(?:REQ-LIB-\d{4}-\d{4}|INV-LIB-\d{4}-\d{4}|FLOW-LIB-\d{4}-\d{2}|DEC-LIB-\d{4}-\d{4})$"
)
_CITATION_RE = re.compile(
    r"\[LIB-\d{4}::spec\.md::(REQ|INV|FLOW|DEC)-LIB-\d{4}-\d{2,4}\]"
    r"|\[LIB-\d{4}::charter\.md\]"
)


def _truncate_text(value: str, limit: int) -> str:
    trimmed = value.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[:limit]


def _is_library_id(value: str) -> bool:
    """Return True if the value matches the LIB-#### format.

    Args:
        value: Candidate library ID.

    Returns:
        True if the value is a LIB-#### identifier.
    """
    return value.startswith("LIB-") and len(value) == 8 and value[4:].isdigit()


def _load_all_spec_indexes(manager: WorkspaceManager) -> dict[str, SpecIndex]:
    """Load spec_index.json files for all libraries in the workspace.

    Args:
        manager: Workspace manager for the active refinement run.

    Returns:
        Mapping of library IDs to validated SpecIndex objects.
    """
    indexes: dict[str, SpecIndex] = {}
    libraries_dir: Path = manager.structure.libraries_dir
    if not libraries_dir.exists():
        logger.warning("Libraries directory missing: %s", libraries_dir)
        return indexes

    for lib_dir in sorted(libraries_dir.iterdir()):
        if not lib_dir.is_dir():
            continue
        lib_id = lib_dir.name
        if not _is_library_id(lib_id):
            continue
        index_path = lib_dir / "spec_index.json"
        if not index_path.exists():
            logger.warning("spec_index.json missing for library %s", lib_id)
            continue
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            index = SpecIndex.model_validate(payload)
        except (FileNotFoundError, OSError) as exc:
            logger.warning("Failed to read spec_index.json for %s: %s", lib_id, exc)
            continue
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON in spec_index.json for %s: %s", lib_id, exc)
            continue
        except ValidationError as exc:
            logger.warning("Invalid spec index schema for %s: %s", lib_id, exc)
            continue
        indexes[lib_id] = index

    return indexes


def _load_architecture_context(manager: WorkspaceManager) -> str | None:
    r"""Load optional architecture context for boundary review prompts.

    Args:
        manager: Workspace manager for the active refinement run.

    Returns:
        Combined architecture text with section headers, or None when no
        architecture context is available.

    Examples:
        >>> _load_architecture_context(manager)
        "## selected.md\n...\n\n## mapping.md\n..."

    Error handling:
        Missing files return None. Read failures are logged and return None.
    """
    selected_path = manager.structure.architecture_dir / "selected.md"
    if not selected_path.exists():
        return None

    sections: list[str] = []
    try:
        selected_content = selected_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read architecture selected.md: %s", exc)
        return None

    if selected_content:
        sections.append("## selected.md")
        sections.append(selected_content)

    mapping_path = manager.structure.architecture_dir / "mapping.md"
    if mapping_path.exists():
        try:
            mapping_content = mapping_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Failed to read architecture mapping.md: %s", exc)
            mapping_content = ""
        if mapping_content:
            sections.append("")
            sections.append("## mapping.md")
            sections.append(mapping_content)

    combined = "\n".join(sections).strip()
    if not combined:
        return None
    return _truncate_text(combined, 2000)


def _extract_evidence_pointers(text: str) -> list[str]:
    """Extract evidence pointers from agent rationale text.

    Args:
        text: Rationale or justification text that may include evidence pointers.

    Returns:
        List of evidence pointers in multi-hop or spec snapshot formats.

    Examples:
        >>> _extract_evidence_pointers(
        ...     "See [LIB-0001::spec.md::REQ-LIB-0001-0001] and "
        ...     "[spec_snapshot/foo.md::SEC-ARCH-0001]."
        ... )
        ["[LIB-0001::spec.md::REQ-LIB-0001-0001]", "[spec_snapshot/foo.md::SEC-ARCH-0001]"]

    Error handling:
        Returns an empty list when text is empty or contains no matches.
    """
    if not text:
        return []
    return re.findall(
        r"\[(?:LIB-\d{4}::[^\]]+|spec_snapshot/[^\]]+::SEC-[A-Za-z0-9]+-\d{4})\]",
        text,
    )


def _build_tfidf_vectors(
    spec_indexes: dict[str, SpecIndex],
) -> tuple[dict[str, np.ndarray], TfidfVectorizer]:
    """Build TF-IDF vectors for each library spec index.

    Args:
        spec_indexes: Mapping of library IDs to SpecIndex objects.

    Returns:
        Tuple of (library vectors mapping, fitted vectorizer).
    """
    lib_ids = sorted(spec_indexes)
    documents: list[str] = []
    empty_libs: set[str] = set()

    for lib_id in lib_ids:
        elements = sorted(
            [
                element
                for element in spec_indexes[lib_id].elements
                if element.kind in _TEXT_KINDS and element.text.strip()
            ],
            key=lambda element: element.element_id,
        )
        if elements:
            documents.append(" ".join(element.text.strip() for element in elements))
        else:
            documents.append("")
            empty_libs.add(lib_id)

    vectorizer = TfidfVectorizer(
        max_features=1000,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
    )

    if not lib_ids:
        vectorizer.fit(["placeholder"])
        return {}, vectorizer

    try:
        if any(doc.strip() for doc in documents):
            matrix = vectorizer.fit_transform(documents)
        else:
            raise ValueError("empty vocabulary")
    except ValueError as exc:
        logger.warning("TF-IDF vectorization failed (%s); using placeholder vocab", exc)
        vectorizer.fit(["placeholder"])
        matrix = vectorizer.transform(documents)

    vectors: dict[str, np.ndarray] = {}
    for index, lib_id in enumerate(lib_ids):
        vector = matrix[index].toarray().ravel()
        if lib_id in empty_libs:
            vector = np.zeros(matrix.shape[1], dtype=float)
        vectors[lib_id] = vector

    return vectors, vectorizer


def _is_zero_vector(vector: np.ndarray) -> bool:
    """Return True if the vector is empty or all zeros.

    Args:
        vector: Vector to inspect.

    Returns:
        True when the vector is empty or contains only zeros.
    """
    return vector.size == 0 or not np.any(vector)


def _compute_pairwise_similarity(
    vectors: dict[str, np.ndarray],
) -> dict[tuple[str, str], float]:
    """Compute pairwise cosine similarity across library vectors.

    Args:
        vectors: Mapping of library IDs to TF-IDF vectors.

    Returns:
        Mapping of library ID pairs to cosine similarity scores.
    """
    similarities: dict[tuple[str, str], float] = {}
    lib_ids = sorted(vectors)
    for idx, lib_a in enumerate(lib_ids):
        vec_a = vectors[lib_a]
        for lib_b in lib_ids[idx + 1 :]:
            vec_b = vectors[lib_b]
            if _is_zero_vector(vec_a) or _is_zero_vector(vec_b):
                similarities[(lib_a, lib_b)] = 0.0
                continue
            score = cosine_similarity(vec_a.reshape(1, -1), vec_b.reshape(1, -1))[0][0]
            similarities[(lib_a, lib_b)] = float(score)

    return similarities


def _find_shared_elements(
    spec_a: SpecIndex,
    spec_b: SpecIndex,
    vectorizer: TfidfVectorizer,
    threshold: float = 0.70,
) -> list[dict[str, Any]]:
    """Find similar requirement/invariant elements across two libraries.

    Args:
        spec_a: Spec index for the first library.
        spec_b: Spec index for the second library.
        vectorizer: Fitted TF-IDF vectorizer.
        threshold: Cosine similarity threshold for element matches.

    Returns:
        List of matched element pairs with similarity scores.
    """
    elements_a = sorted(
        [element for element in spec_a.elements if element.kind in _TEXT_KINDS],
        key=lambda element: element.element_id,
    )
    elements_b = sorted(
        [element for element in spec_b.elements if element.kind in _TEXT_KINDS],
        key=lambda element: element.element_id,
    )
    if not elements_a or not elements_b:
        return []

    if not hasattr(vectorizer, "vocabulary_"):
        logger.warning(
            "TF-IDF vectorizer not fitted; skipping element matching for %s/%s",
            spec_a.lib_id,
            spec_b.lib_id,
        )
        return []

    try:
        matrix_a = vectorizer.transform([element.text for element in elements_a])
        matrix_b = vectorizer.transform([element.text for element in elements_b])
    except ValueError as exc:
        logger.warning(
            "Failed to vectorize elements for %s/%s: %s",
            spec_a.lib_id,
            spec_b.lib_id,
            exc,
        )
        return []

    similarities = cosine_similarity(matrix_a, matrix_b)
    all_matches: list[dict[str, Any]] = []
    for idx_a, row in enumerate(similarities):
        for idx_b, score in enumerate(row):
            if score < threshold:
                continue
            all_matches.append(
                {
                    "element_a_id": elements_a[idx_a].element_id,
                    "element_a_text": elements_a[idx_a].text,
                    "element_b_id": elements_b[idx_b].element_id,
                    "element_b_text": elements_b[idx_b].text,
                    "similarity": float(score),
                }
            )

    all_matches.sort(
        key=lambda item: (-item["similarity"], item["element_a_id"], item["element_b_id"])
    )

    claimed_a: set[str] = set()
    claimed_b: set[str] = set()
    matches: list[dict[str, Any]] = []
    for match in all_matches:
        a_id = match["element_a_id"]
        b_id = match["element_b_id"]
        if a_id in claimed_a or b_id in claimed_b:
            continue
        matches.append(match)
        claimed_a.add(a_id)
        claimed_b.add(b_id)

    return matches


def detect_overlap_candidates(
    manager: WorkspaceManager,
    overlap_threshold: float = 0.35,
    min_shared_elements: int = 5,
) -> list[dict[str, Any]]:
    """Detect library pairs with likely overlapping requirements/invariants.

    Args:
        manager: Workspace manager for the active refinement run.
        overlap_threshold: Library-level cosine similarity threshold.
        min_shared_elements: Minimum number of element-level matches required.

    Returns:
        List of overlap candidate dictionaries.
    """
    spec_indexes = _load_all_spec_indexes(manager)
    if not spec_indexes:
        logger.warning("No spec indexes available for overlap detection.")
        return []

    vectors, vectorizer = _build_tfidf_vectors(spec_indexes)
    similarities = _compute_pairwise_similarity(vectors)

    candidates: list[dict[str, Any]] = []
    for (lib_a, lib_b), score in sorted(similarities.items()):
        if score < overlap_threshold:
            continue
        all_shared = _find_shared_elements(
            spec_indexes[lib_a],
            spec_indexes[lib_b],
            vectorizer,
        )
        shared_count = len(all_shared)
        if shared_count < min_shared_elements:
            continue
        evidence = all_shared[:10]
        candidates.append(
            {
                "lib_a": lib_a,
                "lib_b": lib_b,
                "similarity": float(score),
                "shared_element_count": shared_count,
                "matched_elements": evidence,
            }
        )

    candidates.sort(key=lambda item: (item["lib_a"], item["lib_b"]))
    logger.info("Found %s overlap candidates", len(candidates))
    return candidates


def _cluster_library_elements(
    spec_index: SpecIndex,
    vectorizer: TfidfVectorizer,
    k: int,
) -> tuple[np.ndarray, float]:
    """Cluster requirement/invariant elements within a library.

    Args:
        spec_index: Spec index to cluster.
        vectorizer: Fitted TF-IDF vectorizer.
        k: Number of clusters.

    Returns:
        Tuple of (labels array, silhouette score).
    """
    elements = sorted(
        [element for element in spec_index.elements if element.kind in _TEXT_KINDS],
        key=lambda element: element.element_id,
    )
    if len(elements) < k:
        return np.array([]), -1.0

    if not hasattr(vectorizer, "vocabulary_"):
        logger.warning(
            "TF-IDF vectorizer not fitted; skipping clustering for %s",
            spec_index.lib_id,
        )
        return np.array([]), -1.0

    try:
        vectors = vectorizer.transform([element.text for element in elements]).toarray()
    except ValueError as exc:
        logger.warning("Failed to vectorize elements for %s: %s", spec_index.lib_id, exc)
        return np.array([]), -1.0

    if vectors.shape[1] == 0:
        return np.array([]), -1.0

    model = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = model.fit_predict(vectors)
    try:
        score = float(silhouette_score(vectors, labels))
    except ValueError as exc:
        logger.warning(
            "Failed to compute silhouette score for %s (k=%s): %s",
            spec_index.lib_id,
            k,
            exc,
        )
        return np.array([]), -1.0

    return labels, score


def detect_split_candidates(
    manager: WorkspaceManager,
    min_silhouette: float = 0.3,
    min_elements: int = 10,
) -> list[dict[str, Any]]:
    """Detect libraries that may benefit from splitting via clustering.

    Args:
        manager: Workspace manager for the active refinement run.
        min_silhouette: Minimum silhouette score to accept a split candidate.
        min_elements: Minimum number of elements required to attempt clustering.

    Returns:
        List of split candidate dictionaries.
    """
    spec_indexes = _load_all_spec_indexes(manager)
    if not spec_indexes:
        logger.warning("No spec indexes available for split detection.")
        return []

    _vectors, vectorizer = _build_tfidf_vectors(spec_indexes)

    candidates: list[dict[str, Any]] = []
    for lib_id in sorted(spec_indexes):
        spec_index = spec_indexes[lib_id]
        elements = sorted(
            [element for element in spec_index.elements if element.kind in _TEXT_KINDS],
            key=lambda element: element.element_id,
        )
        if len(elements) < min_elements:
            continue

        best_score = -1.0
        best_labels: np.ndarray = np.array([])
        best_k = 0
        for k in range(2, 6):
            labels, score = _cluster_library_elements(spec_index, vectorizer, k)
            if score > best_score or (score == best_score and score >= 0 and k < best_k):
                best_score = score
                best_labels = labels
                best_k = k

        if best_score < min_silhouette or best_labels.size == 0:
            continue

        cluster_assignments = {
            element.element_id: int(label)
            for element, label in zip(elements, best_labels, strict=True)
        }
        candidates.append(
            {
                "lib_id": lib_id,
                "num_clusters": int(best_k),
                "silhouette_score": float(best_score),
                "cluster_assignments": cluster_assignments,
            }
        )

    candidates.sort(key=lambda item: item["lib_id"])
    logger.info("Found %s split candidates", len(candidates))
    return candidates


def detect_structure_issues(
    manager: WorkspaceManager,
    thresholds: dict[str, float] | None = None,
    consolidate: bool = False,
) -> dict[str, Any]:
    """Run overlap and split detection with configurable thresholds.

    Args:
        manager: Workspace manager for the active refinement run.
        thresholds: Optional overrides for detection thresholds.
        consolidate: When True, run review agents and write review action reports.

    Returns:
        Dictionary containing overlap/split candidates, applied thresholds, and any errors.
        When consolidation is enabled, report_paths is included with output locations.
    """
    start_time = datetime.now()
    effective_thresholds = dict(_DEFAULT_THRESHOLDS)
    if thresholds:
        effective_thresholds.update(thresholds)

    results: dict[str, Any] = {
        "thresholds": effective_thresholds,
        "overlap_candidates": [],
        "split_candidates": [],
    }
    errors: list[dict[str, str]] = []

    try:
        results["overlap_candidates"] = detect_overlap_candidates(
            manager,
            overlap_threshold=effective_thresholds["overlap_similarity"],
            min_shared_elements=int(effective_thresholds["min_shared_elements"]),
        )
    except Exception as exc:
        logger.exception("Overlap detection failed")
        errors.append({"type": "overlap_detection_failed", "error": str(exc)})

    try:
        results["split_candidates"] = detect_split_candidates(
            manager,
            min_silhouette=effective_thresholds["split_silhouette"],
            min_elements=int(effective_thresholds["split_min_elements"]),
        )
    except Exception as exc:
        logger.exception("Split detection failed")
        errors.append({"type": "split_detection_failed", "error": str(exc)})

    if errors:
        results["errors"] = errors

    if consolidate:
        report = consolidate_proposals(
            manager,
            results["overlap_candidates"],
            results["split_candidates"],
            effective_thresholds,
        )
        json_path, md_path = write_review_reports(manager, report)
        results["report_paths"] = {"json": str(json_path), "markdown": str(md_path)}

    duration = (datetime.now() - start_time).total_seconds()
    logger.info(
        "Structure review completed in %.2fs (overlaps=%s, splits=%s)",
        duration,
        len(results["overlap_candidates"]),
        len(results["split_candidates"]),
    )
    return results


def _build_boundary_judge_prompt(
    lib_a_id: str,
    lib_b_id: str,
    charter_a: str,
    charter_b: str,
    matched_elements: list[dict[str, Any]],
    architecture_context: str | None,
) -> str:
    """Build prompt for boundary overlap judge agent."""
    charter_a_excerpt = _truncate_text(charter_a, 500)
    charter_b_excerpt = _truncate_text(charter_b, 500)

    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "Return a JSON object with this schema:",
        "{",
        '  "action": "merge|keep_separate|move_elements",',
        '  "rationale": "string with [LIB-####::spec.md::ELEMENT_ID] citations",',
        '  "elements_to_move": ["REQ-LIB-####-####", "..."],',
        '  "target_lib": "LIB-####",',
        '  "confidence": 0.0',
        "}",
        "",
        "Validation rules:",
        "- action must be merge, keep_separate, or move_elements",
        (
            "- element IDs must match REQ-LIB-####-####, INV-LIB-####-####, "
            "FLOW-LIB-####-##, DEC-LIB-####-####"
        ),
        "- citations must use [LIB-####::spec.md::ELEMENT_ID] or [LIB-####::charter.md]",
        f"- target_lib must be {lib_a_id} or {lib_b_id}",
        "- confidence must be between 0.0 and 1.0",
        "",
        "## INPUT DATA",
        f"Library A ID: {lib_a_id}",
        "Library A Charter (excerpt, first 500 chars):",
        charter_a_excerpt or "(empty)",
        "",
        f"Library B ID: {lib_b_id}",
        "Library B Charter (excerpt, first 500 chars):",
        charter_b_excerpt or "(empty)",
        "",
        "Matched Elements (top 10):",
    ]

    if matched_elements:
        for idx, match in enumerate(matched_elements[:10], start=1):
            a_id = str(match.get("element_a_id", "")).strip()
            b_id = str(match.get("element_b_id", "")).strip()
            a_text = _truncate_text(str(match.get("element_a_text", "")), 200)
            b_text = _truncate_text(str(match.get("element_b_text", "")), 200)
            similarity = match.get("similarity", 0.0)
            try:
                similarity_value = float(similarity)
            except (TypeError, ValueError):
                similarity_value = 0.0
            lines.append(
                f"- Pair {idx}: A {a_id}: {a_text} | B {b_id}: {b_text} | "
                f"similarity={similarity_value:.2f}"
            )
    else:
        lines.append("- (none)")

    if architecture_context:
        lines.extend(
            [
                "",
                "Architecture Mapping Context:",
                _truncate_text(architecture_context, 1000) or "(empty)",
            ]
        )

    lines.extend(
        [
            "",
            "## OUTPUT FORMAT",
            "{",
            '  "action": "keep_separate",',
            '  "rationale": "Reasons with citations [LIB-0001::spec.md::REQ-LIB-0001-0001].",',
            '  "elements_to_move": [],',
            '  "target_lib": "LIB-0001",',
            '  "confidence": 0.62',
            "}",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def _build_split_planner_prompt(
    lib_id: str,
    charter: str,
    spec_excerpt: str,
    cluster_assignments: dict[str, int],
    silhouette_score: float,
    num_clusters: int,
) -> str:
    """Build prompt for split planner agent."""
    charter_excerpt = _truncate_text(charter, 500)
    spec_excerpt_trimmed = _truncate_text(spec_excerpt, 1000)

    clusters: dict[int, list[str]] = {}
    for element_id, cluster_id in cluster_assignments.items():
        clusters.setdefault(int(cluster_id), []).append(element_id)

    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "Return a JSON object with this schema:",
        "{",
        '  "split_groups": [',
        "    {",
        '      "group_id": 0,',
        '      "proposed_name": "string",',
        '      "charter_summary": "string",',
        '      "element_ids": ["REQ-LIB-####-####", "..."],',
        '      "justification": "string with citations"',
        "    }",
        "  ],",
        '  "interface_notes": "string",',
        '  "confidence": 0.0',
        "}",
        "",
        "Termination criteria: return an empty split_groups list if clusters reflect",
        "implementation details, boundaries are unclear, cross-cluster dependencies exceed 30%,",
        "or silhouette score is below 0.3.",
        "",
        "Validation rules:",
        "- each split group must include at least 3 element IDs",
        (
            "- element IDs must match REQ-LIB-####-####, INV-LIB-####-####, "
            "FLOW-LIB-####-##, DEC-LIB-####-####"
        ),
        "- citations must use [LIB-####::spec.md::ELEMENT_ID]",
        "- proposed_name must describe capability, not technical layer",
        "",
        "## INPUT DATA",
        f"Library ID: {lib_id}",
        "Library Charter (excerpt, first 500 chars):",
        charter_excerpt or "(empty)",
        "",
        "Spec Excerpt (requirements/invariants, first 1000 chars):",
        spec_excerpt_trimmed or "(empty)",
        "",
        f"Silhouette score: {silhouette_score:.3f}",
        f"Number of clusters: {num_clusters}",
        "",
        "Cluster assignments:",
    ]

    if clusters:
        for cluster_id in sorted(clusters):
            element_ids = sorted(clusters[cluster_id])
            lines.append(f"- Cluster {cluster_id} ({len(element_ids)} elements):")
            for element_id in element_ids:
                lines.append(f"  - {element_id}")
    else:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "## OUTPUT FORMAT",
            "{",
            '  "split_groups": [',
            "    {",
            '      "group_id": 0,',
            '      "proposed_name": "Input Routing",',
            '      "charter_summary": "Own intake and routing capabilities.",',
            '      "element_ids": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002", "INV-LIB-0001-0003"],',
            '      "justification": "Evidence [LIB-0001::spec.md::REQ-LIB-0001-0001]."',
            "    }",
            "  ],",
            '  "interface_notes": "Describe how groups interact.",',
            '  "confidence": 0.58',
            "}",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def _parse_agent_json(output: str) -> dict[str, Any]:
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", output, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    return json.loads(output)


def _extract_spec_excerpt(spec_content: str, limit: int = 1000) -> str:
    lines = spec_content.splitlines()
    capture = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            capture = heading in {"requirements", "invariants"}
        if capture:
            collected.append(line)
    excerpt = "\n".join(collected).strip()
    if not excerpt:
        excerpt = spec_content.strip()
    return _truncate_text(excerpt, limit)


def _judge_boundary_overlap(
    candidate: dict[str, Any],
    manager: WorkspaceManager,
    architecture_context: str | None,
) -> dict[str, Any]:
    lib_a = candidate["lib_a"]
    lib_b = candidate["lib_b"]
    matched_elements = candidate.get("matched_elements", [])

    lib_a_dir = manager.structure.libraries_dir / lib_a
    lib_b_dir = manager.structure.libraries_dir / lib_b
    charter_a = (lib_a_dir / "charter.md").read_text(encoding="utf-8")
    charter_b = (lib_b_dir / "charter.md").read_text(encoding="utf-8")

    prompt = _build_boundary_judge_prompt(
        lib_a_id=lib_a,
        lib_b_id=lib_b,
        charter_a=charter_a,
        charter_b=charter_b,
        matched_elements=matched_elements,
        architecture_context=architecture_context,
    )

    output = run_agent(
        agent_name="chatgpt-library-boundary-judge",
        prompt=prompt,
        workspace=manager.workspace_path,
    )

    data = _parse_agent_json(str(output))
    errors = _validate_boundary_judge_output(data, lib_a, lib_b)
    if errors:
        raise ValueError(f"Boundary judge output failed validation: {errors}")
    return data


def _plan_library_split(
    candidate: dict[str, Any],
    manager: WorkspaceManager,
) -> dict[str, Any]:
    lib_id = candidate["lib_id"]
    cluster_assignments = candidate["cluster_assignments"]
    silhouette_score = float(candidate["silhouette_score"])
    num_clusters = int(candidate["num_clusters"])

    lib_dir = manager.structure.libraries_dir / lib_id
    charter = (lib_dir / "charter.md").read_text(encoding="utf-8")
    spec_content = (lib_dir / "spec.md").read_text(encoding="utf-8")
    spec_excerpt = _extract_spec_excerpt(spec_content, limit=1000)

    prompt = _build_split_planner_prompt(
        lib_id=lib_id,
        charter=charter,
        spec_excerpt=spec_excerpt,
        cluster_assignments=cluster_assignments,
        silhouette_score=silhouette_score,
        num_clusters=num_clusters,
    )

    output = run_agent(
        agent_name="opus-library-split-planner",
        prompt=prompt,
        workspace=manager.workspace_path,
    )

    data = _parse_agent_json(str(output))
    errors = _validate_split_planner_output(data, lib_id)
    if errors:
        raise ValueError(f"Split planner output failed validation: {errors}")
    return data


def _validate_boundary_judge_output(
    output: dict[str, Any],
    lib_a: str,
    lib_b: str,
) -> list[str]:
    errors: list[str] = []

    action = output.get("action")
    if action not in {"merge", "keep_separate", "move_elements"}:
        errors.append("action must be merge, keep_separate, or move_elements")

    rationale = output.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append("rationale must be a non-empty string")
    elif not _CITATION_RE.search(rationale):
        errors.append(
            "rationale must contain at least one citation matching "
            "[LIB-####::spec.md::ELEMENT_ID] or [LIB-####::charter.md]"
        )

    if action == "move_elements":
        elements_to_move = output.get("elements_to_move")
        if not isinstance(elements_to_move, list) or not elements_to_move:
            errors.append("elements_to_move must be a non-empty list for move_elements")
        else:
            for element_id in elements_to_move:
                if not isinstance(element_id, str) or not _ELEMENT_ID_RE.fullmatch(element_id):
                    errors.append(f"invalid element id: {element_id}")

        target_lib = output.get("target_lib")
        if target_lib not in {lib_a, lib_b}:
            errors.append("target_lib must be one of the input libraries")

    confidence = output.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        errors.append("confidence must be a number between 0.0 and 1.0")
    elif not 0.0 <= float(confidence) <= 1.0:
        errors.append("confidence must be between 0.0 and 1.0")

    return errors


def _validate_split_planner_output(output: dict[str, Any], lib_id: str) -> list[str]:
    errors: list[str] = []

    split_groups = output.get("split_groups")
    if not isinstance(split_groups, list):
        errors.append("split_groups must be a list")
        split_groups = []

    for group in split_groups:
        if not isinstance(group, dict):
            errors.append("split group must be an object")
            continue

        group_id = group.get("group_id")
        if not isinstance(group_id, int) or isinstance(group_id, bool):
            errors.append("group_id must be an integer")

        proposed_name = group.get("proposed_name")
        if not isinstance(proposed_name, str) or not proposed_name.strip():
            errors.append("proposed_name must be a non-empty string")

        charter_summary = group.get("charter_summary")
        if not isinstance(charter_summary, str) or not charter_summary.strip():
            errors.append("charter_summary must be a non-empty string")

        element_ids = group.get("element_ids")
        if not isinstance(element_ids, list):
            errors.append("element_ids must be a list")
            element_ids = []
        if isinstance(element_ids, list) and len(element_ids) < 3:
            errors.append("each split group must include at least 3 element IDs")
        for element_id in element_ids:
            if not isinstance(element_id, str) or not _ELEMENT_ID_RE.fullmatch(element_id):
                errors.append(f"invalid element id: {element_id}")

        justification = group.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            errors.append("justification must be a non-empty string")
        elif not _CITATION_RE.search(justification):
            errors.append(
                "justification must contain at least one citation matching "
                "[LIB-####::spec.md::ELEMENT_ID] or [LIB-####::charter.md]"
            )

    confidence = output.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        errors.append("confidence must be a number between 0.0 and 1.0")
    elif not 0.0 <= float(confidence) <= 1.0:
        errors.append("confidence must be between 0.0 and 1.0")

    return errors


def _convert_boundary_judge_to_action(
    judge_output: dict[str, Any],
    lib_a: str,
    lib_b: str,
    matched_elements: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Convert boundary judge output into a review action payload.

    Args:
        judge_output: Parsed JSON output from the boundary judge agent.
        lib_a: First library ID in the overlap candidate.
        lib_b: Second library ID in the overlap candidate.
        matched_elements: Shared element evidence from overlap detection.

    Returns:
        Action dictionary ready for ReviewAction validation, or None when the
        judge recommends keeping libraries separate.

    Examples:
        >>> _convert_boundary_judge_to_action(
        ...     {"action": "merge", "rationale": "Overlap [LIB-0001::spec.md::REQ-LIB-0001-0001]"},
        ...     "LIB-0001",
        ...     "LIB-0002",
        ...     [],
        ... )
        {'type': 'merge', 'status': 'proposed', 'source_libs': ['LIB-0001', 'LIB-0002'], ...}

    Error handling:
        Expects pre-validated agent output. Invalid action values return None.
    """
    _ = matched_elements
    action = judge_output.get("action")
    if action == "keep_separate":
        return None
    if action not in {"merge", "move_elements"}:
        return None

    rationale = str(judge_output.get("rationale", "")).strip()
    evidence = _extract_evidence_pointers(rationale)
    summary = _truncate_text(rationale, 100) or "Boundary review proposal"

    if action == "merge":
        return {
            "type": "merge",
            "status": "proposed",
            "source_libs": [lib_a, lib_b],
            "target_libs": [],
            "elements": [],
            "summary": summary,
            "rationale": rationale,
            "evidence": evidence,
        }

    elements_to_move = judge_output.get("elements_to_move", [])
    target_lib = judge_output.get("target_lib")
    return {
        "type": "move_elements",
        "status": "proposed",
        "source_libs": [lib_a, lib_b],
        "target_libs": [target_lib] if isinstance(target_lib, str) else [],
        "elements": list(elements_to_move) if isinstance(elements_to_move, list) else [],
        "summary": summary,
        "rationale": rationale,
        "evidence": evidence,
    }


def _convert_split_planner_to_actions(
    split_output: dict[str, Any],
    lib_id: str,
) -> list[dict[str, Any]]:
    """Convert split planner output into review action payloads.

    Args:
        split_output: Parsed JSON output from the split planner agent.
        lib_id: Library ID targeted for splitting.

    Returns:
        List of action dictionaries ready for ReviewAction validation.

    Examples:
        >>> _convert_split_planner_to_actions(
        ...     {"split_groups": [
        ...         {"proposed_name": "Routing", "charter_summary": "Own intake.",
        ...          "element_ids": ["REQ-LIB-0001-0001"],
        ...          "justification": "Evidence [LIB-0001::spec.md::REQ-LIB-0001-0001]"}
        ...     ]},
        ...     "LIB-0001",
        ... )
        [{'type': 'split', 'source_libs': ['LIB-0001'], ...}]

    Error handling:
        Returns an empty list when split_groups is empty or missing.
    """
    split_groups = split_output.get("split_groups", [])
    if not split_groups:
        return []

    actions: list[dict[str, Any]] = []
    for group in split_groups:
        if not isinstance(group, dict):
            continue
        proposed_name = str(group.get("proposed_name", "")).strip()
        charter_summary = str(group.get("charter_summary", "")).strip()
        justification = str(group.get("justification", "")).strip()
        evidence = _extract_evidence_pointers(justification)
        summary = f"{proposed_name} - {charter_summary}".strip(" -")
        actions.append(
            {
                "type": "split",
                "status": "proposed",
                "source_libs": [lib_id],
                "target_libs": [],
                "elements": list(group.get("element_ids", [])),
                "summary": summary,
                "rationale": justification,
                "evidence": evidence,
            }
        )

    return actions


def consolidate_proposals(
    manager: WorkspaceManager,
    overlap_candidates: list[dict[str, Any]],
    split_candidates: list[dict[str, Any]],
    thresholds: dict[str, float],
) -> ReviewActionsReport:
    """Run overlap and split review agents and build a consolidated report.

    Args:
        manager: Workspace manager for the active refinement run.
        overlap_candidates: Overlap candidate payloads from detection.
        split_candidates: Split candidate payloads from detection.
        thresholds: Effective thresholds used for detection.

    Returns:
        ReviewActionsReport with stable action IDs and validated pointers.

    Examples:
        >>> report = consolidate_proposals(manager, [], [], {"overlap_similarity": 0.35})
        >>> report.actions
        []

    Error handling:
        Agent failures are logged and skipped. Pointer validation failures
        mark actions as rejected with explanatory notes.
    """
    architecture_context = _load_architecture_context(manager)
    actions: list[dict[str, Any]] = []

    for candidate in overlap_candidates:
        try:
            judge_output = _judge_boundary_overlap(candidate, manager, architecture_context)
        except Exception as exc:
            logger.warning(
                "Boundary judge failed for %s/%s: %s",
                candidate.get("lib_a"),
                candidate.get("lib_b"),
                exc,
            )
            continue
        action = _convert_boundary_judge_to_action(
            judge_output,
            candidate.get("lib_a", ""),
            candidate.get("lib_b", ""),
            candidate.get("matched_elements", []),
        )
        if action is not None:
            actions.append(action)

    for candidate in split_candidates:
        try:
            split_output = _plan_library_split(candidate, manager)
        except Exception as exc:
            logger.warning("Split planner failed for %s: %s", candidate.get("lib_id"), exc)
            continue
        actions.extend(
            _convert_split_planner_to_actions(
                split_output,
                candidate.get("lib_id", ""),
            )
        )

    actions = generate_stable_action_ids(actions)

    for action in actions:
        for pointer in action.get("evidence", []):
            valid, error_msg = validate_pointer_references(
                pointer,
                manager.state.file_manifest,
                manager.allocated_library_ids,
            )
            if not valid and action.get("status") != "rejected":
                action["status"] = "rejected"
                action["notes"] = f"Pointer validation failed: {error_msg}"
                logger.warning(
                    "Pointer validation failed for action %s: %s",
                    action.get("summary", "unknown"),
                    error_msg,
                )

    report = ReviewActionsReport(
        run_id=manager.run_id,
        generated_at=datetime.now().isoformat(),
        thresholds=thresholds,
        actions=[ReviewAction.model_validate(action) for action in actions],
    )
    return report


def write_review_reports(
    manager: WorkspaceManager,
    report: ReviewActionsReport,
) -> tuple[Path, Path]:
    """Write review action reports as JSON and Markdown.

    Args:
        manager: Workspace manager for the active refinement run.
        report: Consolidated review actions report.

    Returns:
        Tuple of (json_path, markdown_path).

    Examples:
        >>> json_path, md_path = write_review_reports(manager, report)
        >>> json_path.name
        'review_actions.json'

    Error handling:
        Raises if writing fails; callers should handle file IO errors if needed.
    """
    json_path = manager.structure.reports_dir / "review_actions.json"
    md_path = manager.structure.reports_dir / "review_actions.md"
    write_review_actions_json(report, json_path)
    write_review_actions_markdown(report, md_path)
    logger.info("Wrote review actions JSON report to %s", json_path)
    logger.info("Wrote review actions Markdown report to %s", md_path)
    return json_path, md_path


def _derive_split_group_from_action(action: ReviewAction) -> dict[str, Any]:
    summary = (action.summary or "").strip()
    proposed_name = ""
    charter_summary = ""
    if " - " in summary:
        proposed_name, charter_summary = [part.strip() for part in summary.split(" - ", 1)]
    else:
        proposed_name = summary

    if not charter_summary:
        charter_summary = summary or (action.rationale or "").strip()

    group_id = 0
    if action.action_id:
        try:
            group_id = int(action.action_id.split("-", 1)[1])
        except (IndexError, ValueError):
            group_id = 0

    if not proposed_name:
        proposed_name = f"Split Group {group_id or 1}"
    if not charter_summary:
        charter_summary = proposed_name

    return {
        "group_id": group_id,
        "proposed_name": proposed_name,
        "charter_summary": charter_summary,
        "element_ids": list(action.elements),
    }


def _format_split_charter(
    lib_id: str,
    group_proposal: dict[str, Any],
    source_lib_id: str,
) -> str:
    proposed_name = str(group_proposal.get("proposed_name", "")).strip()
    charter_summary = str(group_proposal.get("charter_summary", "")).strip()
    intent = charter_summary or proposed_name or f"Split from {source_lib_id}."
    boundaries = proposed_name or f"Derived from {source_lib_id}."

    lines = [
        f"# Library Charter: {lib_id}",
        "",
        "## Intent",
        intent,
        "",
        "## Boundaries",
        boundaries,
        "",
        "## Responsibilities",
        "- None",
        "",
        "## Evidence",
        "- None",
        "",
        "## Overlap Resolutions",
        "- None",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _partition_spec_elements(
    source_spec_content: str,
    element_ids: list[str],
    new_lib_id: str,
) -> str:
    selected_ids = {element_id.strip() for element_id in element_ids if element_id}
    sections = _extract_sections_with_positions(source_spec_content, level=2)
    section_map = {title: source_spec_content[start:end] for title, start, end in sections}

    def _next_element_id(
        element_id: str,
        counters: dict[str, int],
        lib_id: str,
    ) -> str:
        prefix = element_id.split("-", 1)[0]
        counters.setdefault(prefix, 0)
        counters[prefix] += 1
        width = 2 if prefix == "FLOW" else 4
        lib_suffix = lib_id.split("-", 1)[1]
        return f"{prefix}-LIB-{lib_suffix}-{counters[prefix]:0{width}d}"

    def _filter_section(section_content: str, counters: dict[str, int]) -> list[str]:
        filtered: list[str] = []
        include_continuation = False
        for line in section_content.splitlines():
            element_id = extract_existing_id(line)
            bullet_match = re.match(r"^([ \t]*[-*])\s+", line)
            if bullet_match and element_id:
                if element_id in selected_ids:
                    include_continuation = True
                    new_id = _next_element_id(element_id, counters, new_lib_id)
                    filtered.append(line.replace(element_id, new_id, 1))
                else:
                    include_continuation = False
                continue
            if include_continuation:
                filtered.append(line)
        return filtered

    counters: dict[str, int] = {}
    ordered_sections = ["Requirements", "Flows", "Constraints", "Dependencies"]
    lines: list[str] = [f"# Library Spec: {new_lib_id}", ""]

    for section_title in ordered_sections:
        lines.append(f"## {section_title}")
        section_content = section_map.get(section_title, "")
        filtered_lines = _filter_section(section_content, counters)
        if filtered_lines:
            lines.extend(filtered_lines)
        else:
            lines.append("<!-- No elements assigned -->")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _partition_evidence(
    source_evidence: dict[str, Any],
    element_ids: list[str],
    source_spec_index: dict[str, Any],
) -> dict[str, Any]:
    sources = source_evidence.get("sources", [])
    if not isinstance(sources, list):
        return {"sources": []}

    file_manifest = source_spec_index.get("file_manifest")
    file_id_lookup: dict[str, str] = {}
    if isinstance(file_manifest, dict) and file_manifest:
        file_id_lookup = build_file_id_lookup(file_manifest)

    target_ids = {element_id for element_id in element_ids if element_id}
    citations_by_file: dict[str, set[str]] = {}
    for element in source_spec_index.get("elements", []) or []:
        element_id = element.get("element_id")
        if element_id not in target_ids:
            continue
        for citation in element.get("citations", []) or []:
            parsed = parse_evidence_pointer(citation, allow_multi_hop=True)
            if not parsed or "intermediate" in parsed:
                continue
            file_ref = parsed["file_ref"]
            section_ref = parsed["section_ref"]
            resolved_file_id = file_id_lookup.get(file_ref, file_ref)
            if not resolved_file_id:
                continue
            citations_by_file.setdefault(resolved_file_id, set()).add(section_ref)

    filtered_sources: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        file_id = source.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            continue
        sections = source.get("sections", [])
        if not isinstance(sections, list):
            sections = []
        section_set = {section for section in sections if isinstance(section, str)}
        cited_sections = citations_by_file.get(file_id, set())
        if not cited_sections:
            continue
        if not section_set or cited_sections.intersection(section_set):
            filtered_sources.append(source)
            continue
        # Fallback: include if the file is cited but section labels don't match.
        filtered_sources.append(source)

    return {"sources": filtered_sources}


def _add_spec_tombstones(
    source_spec_content: str,
    element_ids: list[str],
    target_lib_id: str,
) -> str:
    selected_ids = {element_id for element_id in element_ids if element_id}
    lines = source_spec_content.splitlines(keepends=True)
    updated_lines: list[str] = []
    skip_indent: int | None = None
    pending_blanks: list[str] = []

    for line in lines:
        line_text = line.rstrip("\r\n")
        line_ending = line[len(line_text) :]
        element_id = extract_existing_id(line_text)
        bullet_match = re.match(r"^([ \t]*)([-*])\s+", line_text)

        if bullet_match and element_id:
            if element_id in selected_ids:
                indent = bullet_match.group(1)
                indent_width = len(indent.expandtabs(4))
                updated_lines.extend(pending_blanks)
                pending_blanks = []
                updated_lines.append(
                    f"{indent}<!-- {element_id} moved to {target_lib_id} -->{line_ending}"
                )
                skip_indent = indent_width
                continue
            else:
                updated_lines.extend(pending_blanks)
                pending_blanks = []
                skip_indent = None

        elif skip_indent is not None:
            if line_text.strip() == "":
                pending_blanks.append(line)
                continue
            current_indent_match = re.match(r"^([ \t]*)", line_text)
            current_indent = (
                len(current_indent_match.group(1).expandtabs(4)) if current_indent_match else 0
            )
            if current_indent > skip_indent:
                pending_blanks = []
                continue
            else:
                updated_lines.extend(pending_blanks)
                pending_blanks = []
                skip_indent = None

        updated_lines.append(line)

    updated_lines.extend(pending_blanks)
    return "".join(updated_lines)


def _extract_elements_from_spec(
    spec_content: str,
    element_ids: list[str],
) -> dict[str, str]:
    selected_ids = {element_id.strip() for element_id in element_ids if element_id}
    if not selected_ids:
        return {}

    sections = _extract_sections_with_positions(spec_content, level=2)
    section_map = {title: spec_content[start:end] for title, start, end in sections}

    extracted: dict[str, str] = {}
    ordered_sections = ["Requirements", "Flows", "Constraints", "Dependencies"]
    for section_title in ordered_sections:
        section_content = section_map.get(section_title, "")
        if not section_content:
            continue
        current_id: str | None = None
        current_lines: list[str] = []
        current_indent = 0
        capturing = False
        for line in section_content.splitlines():
            element_id = extract_existing_id(line)
            bullet_match = re.match(r"^([ \t]*)([-*])\s+", line)
            if bullet_match and element_id:
                if capturing and current_id and current_lines:
                    extracted[current_id] = "\n".join(current_lines).rstrip()
                if element_id in selected_ids:
                    capturing = True
                    current_id = element_id
                    current_lines = [line]
                    current_indent = len(bullet_match.group(1).expandtabs(4))
                else:
                    capturing = False
                    current_id = None
                    current_lines = []
                continue
            if capturing:
                if bullet_match:
                    indent_width = len(bullet_match.group(1).expandtabs(4))
                    if indent_width > current_indent:
                        current_lines.append(line)
                        continue
                    extracted[current_id] = "\n".join(current_lines).rstrip()
                    capturing = False
                    current_id = None
                    current_lines = []
                    continue
                if line.strip() == "":
                    current_lines.append(line)
                    continue
                indent_width = len(re.match(r"^([ \t]*)", line).group(1).expandtabs(4))
                if indent_width > current_indent:
                    current_lines.append(line)
                    continue
                extracted[current_id] = "\n".join(current_lines).rstrip()
                capturing = False
                current_id = None
                current_lines = []
        if capturing and current_id and current_lines:
            extracted[current_id] = "\n".join(current_lines).rstrip()

    return extracted


def _rewrite_element_id(
    element_text: str,
    old_id: str,
    target_lib_id: str,
    counters: dict[str, int],
) -> str:
    prefix = old_id.split("-", 1)[0]
    counters.setdefault(prefix, 0)
    counters[prefix] += 1
    width = 2 if prefix == "FLOW" else 4
    lib_suffix = target_lib_id.split("-", 1)[1]
    new_id = f"{prefix}-LIB-{lib_suffix}-{counters[prefix]:0{width}d}"
    return element_text.replace(old_id, new_id, 1)


def _append_elements_to_spec(
    target_spec_content: str,
    elements: dict[str, str],
    target_lib_id: str,
    source_lib_id: str,
) -> str:
    if not elements:
        return target_spec_content

    header_pattern = re.compile(r"^(##\s+(.+))$", re.MULTILINE)
    matches = list(header_pattern.finditer(target_spec_content))
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        title = match.group(2).strip()
        header_start = match.start()
        content_start = match.end()
        content_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(target_spec_content)
        )
        sections.append(
            {
                "title": title,
                "header_start": header_start,
                "content_start": content_start,
                "content_end": content_end,
            }
        )
    section_by_title = {section["title"]: section for section in sections}

    counters: dict[str, int] = {}
    for line in target_spec_content.splitlines():
        element_id = extract_existing_id(line)
        if not element_id:
            continue
        if f"-{target_lib_id}-" not in element_id:
            continue
        prefix = element_id.split("-", 1)[0]
        suffix = element_id.split("-")[-1]
        if not suffix.isdigit():
            continue
        counters[prefix] = max(counters.get(prefix, 0), int(suffix))

    elements_by_section: dict[str, list[list[str]]] = {}
    for old_id, element_text in elements.items():
        prefix = old_id.split("-", 1)[0]
        if prefix == "REQ":
            section_title = "Requirements"
        elif prefix == "FLOW":
            section_title = "Flows"
        elif prefix == "INV":
            if "Constraints" in section_by_title:
                section_title = "Constraints"
            elif "Dependencies" in section_by_title:
                section_title = "Dependencies"
            else:
                section_title = "Constraints"
        elif prefix == "DEC":
            section_title = "Dependencies"
        else:
            logger.warning("Unknown element prefix %s for %s", prefix, old_id)
            continue

        updated_text = _rewrite_element_id(element_text, old_id, target_lib_id, counters)
        first_line = updated_text.splitlines()[0] if updated_text.splitlines() else ""
        indent_match = re.match(r"^(\s*)", first_line)
        indent = indent_match.group(1) if indent_match else ""
        comment_line = f"{indent}<!-- Moved from {source_lib_id} -->"
        entry_lines = [comment_line, *updated_text.splitlines()]
        elements_by_section.setdefault(section_title, []).append(entry_lines)

    if not elements_by_section:
        return target_spec_content

    def _append_entries(section_content: str, entry_sets: list[list[str]]) -> str:
        lines = [
            line
            for line in section_content.splitlines()
            if line.strip() != "<!-- No elements assigned -->"
        ]
        cleaned = "\n".join(lines).rstrip("\n")
        additions: list[str] = []
        for entry in entry_sets:
            additions.extend(entry)
        if not additions:
            return section_content
        if cleaned:
            cleaned += "\n"
        cleaned += "\n".join(additions) + "\n"
        return cleaned

    operations: list[tuple[int, int, int, str]] = []
    op_index = 0
    missing_sections: dict[str, list[list[str]]] = {}
    for section_title, entry_sets in elements_by_section.items():
        section_info = section_by_title.get(section_title)
        if section_info:
            updated_section = _append_entries(
                target_spec_content[section_info["content_start"] : section_info["content_end"]],
                entry_sets,
            )
            operations.append(
                (
                    section_info["content_start"],
                    op_index,
                    section_info["content_end"],
                    updated_section,
                )
            )
            op_index += 1
        else:
            missing_sections[section_title] = entry_sets

    ordered_sections = ["Requirements", "Flows", "Constraints", "Dependencies"]
    for section_title in ordered_sections:
        if section_title not in missing_sections:
            continue
        entry_sets = missing_sections[section_title]
        if not entry_sets:
            continue
        insert_pos = len(target_spec_content)
        for next_section in ordered_sections[ordered_sections.index(section_title) + 1 :]:
            next_info = section_by_title.get(next_section)
            if next_info:
                insert_pos = next_info["header_start"]
                break
        additions: list[str] = []
        for entry in entry_sets:
            additions.extend(entry)
        section_lines = [f"## {section_title}", *additions, ""]
        insert_text = "\n".join(section_lines) + "\n"
        if insert_pos > 0 and not target_spec_content[:insert_pos].endswith("\n"):
            insert_text = "\n" + insert_text
        operations.append((insert_pos, op_index, insert_pos, insert_text))
        op_index += 1

    updated_content = target_spec_content
    for start, _, end, replacement in sorted(
        operations, key=lambda item: (item[0], item[1]), reverse=True
    ):
        updated_content = updated_content[:start] + replacement + updated_content[end:]
    return updated_content


def _update_evidence_for_move(
    source_evidence: dict[str, Any],
    target_evidence: dict[str, Any],
    element_ids: list[str],
    source_spec_index: dict[str, Any],
    target_spec_index: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    moved_evidence = _partition_evidence(source_evidence, element_ids, source_spec_index)
    moved_sources = moved_evidence.get("sources", [])
    if not isinstance(moved_sources, list):
        moved_sources = []

    file_manifest: dict[str, dict[str, str]] = {}
    if isinstance(source_spec_index.get("file_manifest"), dict):
        file_manifest.update(source_spec_index["file_manifest"])
    if isinstance(target_spec_index.get("file_manifest"), dict):
        file_manifest.update(target_spec_index["file_manifest"])
    file_id_lookup = build_file_id_lookup(file_manifest) if file_manifest else {}

    def _normalize_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            entry = dict(source)
            file_id = entry.get("file_id")
            if isinstance(file_id, str) and file_id:
                entry["file_id"] = file_id_lookup.get(file_id, file_id)
            sections = entry.get("sections", [])
            if isinstance(sections, list):
                seen: set[str] = set()
                unique_sections: list[str] = []
                for section in sections:
                    if not isinstance(section, str) or not section:
                        continue
                    if section in seen:
                        continue
                    seen.add(section)
                    unique_sections.append(section)
                entry["sections"] = unique_sections
            normalized.append(entry)
        return normalized

    moved_sources = _normalize_sources(moved_sources)
    source_sources = _normalize_sources(
        list(source_evidence.get("sources", [])) if isinstance(source_evidence, dict) else []
    )
    target_sources = _normalize_sources(
        list(target_evidence.get("sources", [])) if isinstance(target_evidence, dict) else []
    )

    moved_file_ids = {
        source.get("file_id") for source in moved_sources if isinstance(source.get("file_id"), str)
    }

    # Compute remaining citations from elements NOT being moved.
    moved_element_ids = set(element_ids)
    remaining_cited_files: dict[str, set[str]] = {}
    for element in source_spec_index.get("elements", []) or []:
        eid = element.get("element_id")
        if eid in moved_element_ids:
            continue
        for citation in element.get("citations", []) or []:
            parsed = parse_evidence_pointer(citation, allow_multi_hop=True)
            if not parsed or "intermediate" in parsed:
                continue
            file_ref = parsed["file_ref"]
            section_ref = parsed["section_ref"]
            resolved = file_id_lookup.get(file_ref, file_ref)
            if resolved:
                remaining_cited_files.setdefault(resolved, set()).add(section_ref)

    # Build moved sections per file_id so we can prune at section level.
    moved_sections_by_file: dict[str, set[str]] = {}
    for ms in moved_sources:
        fid = ms.get("file_id")
        if isinstance(fid, str) and fid:
            sects = ms.get("sections", [])
            if isinstance(sects, list):
                moved_sections_by_file.setdefault(fid, set()).update(
                    s for s in sects if isinstance(s, str)
                )

    # Prune source_sources: keep entries still cited by remaining elements,
    # removing only sections that moved and are no longer needed.
    pruned_sources: list[dict[str, Any]] = []
    for source in source_sources:
        fid = source.get("file_id")
        if fid not in moved_file_ids:
            pruned_sources.append(source)
            continue
        if fid not in remaining_cited_files:
            continue
        sections = source.get("sections", [])
        if isinstance(sections, list) and sections:
            still_cited = remaining_cited_files.get(fid, set())
            moved_sects = moved_sections_by_file.get(fid, set())
            kept = [s for s in sections if s not in moved_sects or s in still_cited]
            if not kept:
                continue
            source = dict(source)
            source["sections"] = kept
        pruned_sources.append(source)
    source_sources = pruned_sources

    target_by_id: dict[str, dict[str, Any]] = {}
    for source in target_sources:
        file_id = source.get("file_id")
        if isinstance(file_id, str) and file_id:
            target_by_id[file_id] = source

    for moved_source in moved_sources:
        file_id = moved_source.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            continue
        if file_id in target_by_id:
            existing = target_by_id[file_id]
            existing_sections = (
                existing.get("sections", []) if isinstance(existing.get("sections"), list) else []
            )
            moved_sections = (
                moved_source.get("sections", [])
                if isinstance(moved_source.get("sections"), list)
                else []
            )
            seen_sections = set(existing_sections)
            merged_sections = list(existing_sections)
            for section in moved_sections:
                if section in seen_sections:
                    continue
                seen_sections.add(section)
                merged_sections.append(section)
            existing["sections"] = merged_sections
        else:
            target_sources.append(moved_source)
            target_by_id[file_id] = moved_source

    updated_source = dict(source_evidence) if isinstance(source_evidence, dict) else {}
    updated_target = dict(target_evidence) if isinstance(target_evidence, dict) else {}
    updated_source["sources"] = source_sources
    updated_target["sources"] = target_sources
    return updated_source, updated_target


def _validate_moved_elements(
    source_spec: str,
    target_spec: str,
    element_ids: list[str],
    target_lib_id: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not element_ids:
        return issues

    for element_id in element_ids:
        tombstone = f"<!-- {element_id} moved to {target_lib_id} -->"
        if tombstone not in source_spec:
            issues.append(
                {
                    "type": "missing_tombstone",
                    "element_id": element_id,
                    "message": "Missing tombstone in source spec.",
                }
            )

    source_elements = {
        extract_existing_id(line) for line in source_spec.splitlines() if extract_existing_id(line)
    }
    for element_id in element_ids:
        if element_id in source_elements:
            issues.append(
                {
                    "type": "element_still_in_source",
                    "element_id": element_id,
                    "message": "Element still present in source spec.",
                }
            )

    target_elements = {
        extract_existing_id(line) for line in target_spec.splitlines() if extract_existing_id(line)
    }
    for element_id in element_ids:
        if element_id in target_elements:
            issues.append(
                {
                    "type": "element_id_not_rewritten",
                    "element_id": element_id,
                    "message": "Element ID not rewritten in target spec.",
                }
            )

    moved_entries: list[tuple[str, str]] = []
    lines = target_spec.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith("<!-- Moved from"):
            continue
        element_id = None
        element_lines: list[str] = []
        for next_line in lines[index + 1 :]:
            if element_id is None:
                element_id = extract_existing_id(next_line)
                if element_id:
                    element_lines.append(next_line)
                    continue
                if next_line.strip():
                    break
                continue
            indent_match = re.match(r"^([ \t]*)", next_line)
            indent_width = len(indent_match.group(1).expandtabs(4)) if indent_match else 0
            if indent_width > 0 and next_line.strip():
                element_lines.append(next_line)
                continue
            if next_line.strip() == "":
                element_lines.append(next_line)
                continue
            break
        if element_id:
            moved_entries.append((element_id, "\n".join(element_lines).strip()))

    moved_target_ids = [
        element_id
        for element_id, _ in moved_entries
        if element_id and f"-{target_lib_id}-" in element_id
    ]
    if len(moved_target_ids) < len(element_ids):
        issues.append(
            {
                "type": "missing_target_elements",
                "message": "Moved elements missing from target spec.",
            }
        )

    for element_id, element_text in moved_entries:
        if f"-{target_lib_id}-" not in element_id:
            issues.append(
                {
                    "type": "element_id_mismatch",
                    "element_id": element_id,
                    "message": "Moved element ID does not match target library format.",
                }
            )
        if element_text and not _CITATION_RE.search(element_text):
            issues.append(
                {
                    "type": "missing_citations",
                    "element_id": element_id,
                    "message": "Moved element missing citations.",
                }
            )

    return issues


def _validate_split_artifacts(
    manager: WorkspaceManager,
    lib_id: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    lib_dir = manager.structure.libraries_dir / lib_id
    spec_path = lib_dir / "spec.md"
    charter_path = lib_dir / "charter.md"
    evidence_path = lib_dir / "evidence.json"

    if not spec_path.exists():
        issues.append(
            {
                "type": "missing_artifact",
                "artifact": "spec",
                "lib_id": lib_id,
                "message": "Missing spec.md for split library.",
            }
        )
        return issues

    if not charter_path.exists():
        issues.append(
            {
                "type": "missing_artifact",
                "artifact": "charter",
                "lib_id": lib_id,
                "message": "Missing charter.md for split library.",
            }
        )

    if not evidence_path.exists():
        issues.append(
            {
                "type": "missing_artifact",
                "artifact": "evidence",
                "lib_id": lib_id,
                "message": "Missing evidence.json for split library.",
            }
        )

    spec_content = spec_path.read_text(encoding="utf-8")
    charter_content = charter_path.read_text(encoding="utf-8") if charter_path.exists() else ""

    spec_index = build_spec_index(spec_content, lib_id)
    for element in spec_index.get("elements", []) or []:
        element_id = str(element.get("element_id", "")).strip()
        if not element_id:
            continue
        if not _ELEMENT_ID_RE.fullmatch(element_id):
            issues.append(
                {
                    "type": "invalid_element_id",
                    "artifact": "spec",
                    "lib_id": lib_id,
                    "element_id": element_id,
                    "message": "Element ID does not match expected pattern.",
                }
            )
            continue
        if f"-{lib_id}-" not in element_id:
            issues.append(
                {
                    "type": "element_id_mismatch",
                    "artifact": "spec",
                    "lib_id": lib_id,
                    "element_id": element_id,
                    "message": "Element ID does not match new library ID.",
                }
            )

    def _extract_pointers(text: str) -> list[str]:
        if not text:
            return []
        return re.findall(r"\[[^\[\]]+::[^\[\]]+\]", text)

    for pointer in _extract_pointers(spec_content):
        valid, error_msg = validate_pointer_references(
            pointer,
            manager.state.file_manifest,
            manager.allocated_library_ids,
        )
        if not valid:
            issues.append(
                {
                    "type": "invalid_pointer",
                    "artifact": "spec",
                    "lib_id": lib_id,
                    "pointer": pointer,
                    "message": error_msg or "Invalid pointer reference.",
                }
            )

    for pointer in _extract_pointers(charter_content):
        valid, error_msg = validate_pointer_references(
            pointer,
            manager.state.file_manifest,
            manager.allocated_library_ids,
        )
        if not valid:
            issues.append(
                {
                    "type": "invalid_pointer",
                    "artifact": "charter",
                    "lib_id": lib_id,
                    "pointer": pointer,
                    "message": error_msg or "Invalid pointer reference.",
                }
            )

    return issues


def _repair_split_artifacts(
    manager: WorkspaceManager,
    lib_id: str,
    issues: list[dict[str, Any]],
) -> bool:
    if not issues:
        return True

    lib_dir = manager.structure.libraries_dir / lib_id
    spec_path = lib_dir / "spec.md"
    charter_path = lib_dir / "charter.md"
    allowlists = {"file_refs": sorted(manager.state.file_manifest), "sections": {}}
    issues_by_artifact: dict[str, list[dict[str, Any]]] = {"spec": [], "charter": []}
    for issue in issues:
        artifact = issue.get("artifact", "spec")
        issues_by_artifact.setdefault(artifact, []).append(issue)

    if issues_by_artifact.get("spec"):
        if not spec_path.exists():
            return False
        try:
            repaired_spec, _ = repair_artifact(
                output=spec_path.read_text(encoding="utf-8"),
                errors=issues_by_artifact["spec"],
                allowlists=allowlists,
                artifact_type=ArtifactType.SPEC,
                model_override=get_repair_model(),
                manager=manager,
            )
            spec_path.write_text(repaired_spec, encoding="utf-8")
        except Exception:
            logger.exception("Spec repair failed for split library %s", lib_id)
            return False

    if issues_by_artifact.get("charter"):
        if not charter_path.exists():
            return False
        try:
            repaired_charter, _ = repair_artifact(
                output=charter_path.read_text(encoding="utf-8"),
                errors=issues_by_artifact["charter"],
                allowlists=allowlists,
                artifact_type=ArtifactType.CHARTER,
                model_override=get_repair_model(),
                manager=manager,
            )
            charter_path.write_text(repaired_charter, encoding="utf-8")
        except Exception:
            logger.exception("Charter repair failed for split library %s", lib_id)
            return False

    return True


def _create_split_library(
    manager: WorkspaceManager,
    source_lib_id: str,
    group_proposal: dict[str, Any],
    source_spec_index: dict[str, Any],
    source_evidence: dict[str, Any],
) -> str:
    new_lib_id = manager.allocate_library_id()
    lib_dir = manager.structure.libraries_dir / new_lib_id
    if lib_dir.exists():
        raise RuntimeError(f"Split library directory already exists: {lib_dir}")

    lib_dir.mkdir(parents=True, exist_ok=True)
    source_spec_path = manager.structure.libraries_dir / source_lib_id / "spec.md"
    source_spec_content = source_spec_path.read_text(encoding="utf-8")
    element_ids = list(group_proposal.get("element_ids", []))

    spec_content = _partition_spec_elements(source_spec_content, element_ids, new_lib_id)
    (lib_dir / "spec.md").write_text(spec_content, encoding="utf-8")

    charter_content = _format_split_charter(new_lib_id, group_proposal, source_lib_id)
    (lib_dir / "charter.md").write_text(charter_content, encoding="utf-8")

    evidence_payload = _partition_evidence(source_evidence, element_ids, source_spec_index)
    (lib_dir / "evidence.json").write_text(
        json.dumps(evidence_payload, indent=2),
        encoding="utf-8",
    )

    (lib_dir / "gaps.md").write_text("", encoding="utf-8")
    (lib_dir / "decisions.md").write_text("", encoding="utf-8")

    spec_index = build_spec_index(spec_content, new_lib_id)
    initial_elements = [element.get("element_id") for element in spec_index.get("elements", [])]
    if element_ids and len(initial_elements) < len(
        {element_id for element_id in element_ids if element_id}
    ):
        raise RuntimeError("Element ID rewrite failed for split spec.")
    (lib_dir / "spec_index.json").write_text(
        json.dumps(spec_index, indent=2),
        encoding="utf-8",
    )
    metadata = {
        "derived_from": source_lib_id,
        "split_group": group_proposal.get("group_id"),
        "initial_intent": group_proposal.get("charter_summary", ""),
        "initial_elements": [element_id for element_id in initial_elements if element_id],
    }
    event = LibraryEvent(
        event_type=LibraryEventType.LIBRARY_CREATED,
        timestamp=datetime.now().isoformat(),
        lib_id=new_lib_id,
        metadata=metadata,
        previous_state=None,
    )
    try:
        _write_library_event(lib_dir, event)
    except Exception:
        shutil.rmtree(lib_dir, ignore_errors=True)
        raise

    return new_lib_id


def _apply_single_split(
    manager: WorkspaceManager,
    action: ReviewAction,
    split_proposal: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "action_id": action.action_id,
        "new_lib_ids": [],
        "errors": [],
        "validation_issues": [],
    }

    if not action.source_libs:
        result["errors"].append(
            {"type": "missing_source_lib", "error": "Split action missing source library."}
        )
        return result

    source_lib_id = action.source_libs[0]
    lib_dir = manager.structure.libraries_dir / source_lib_id
    if not lib_dir.exists():
        result["errors"].append(
            {
                "type": "missing_source_library",
                "lib_id": source_lib_id,
                "error": "Source library directory not found.",
            }
        )
        return result

    spec_path = lib_dir / "spec.md"
    charter_path = lib_dir / "charter.md"
    evidence_path = lib_dir / "evidence.json"
    spec_index_path = lib_dir / "spec_index.json"

    if not spec_path.exists() or not charter_path.exists() or not evidence_path.exists():
        result["errors"].append(
            {
                "type": "missing_source_artifacts",
                "lib_id": source_lib_id,
                "error": "Source library missing required artifacts.",
            }
        )
        return result

    if not spec_index_path.exists():
        result["errors"].append(
            {
                "type": "missing_spec_index",
                "lib_id": source_lib_id,
                "error": "Source library spec_index.json missing.",
            }
        )
        return result

    source_spec_content = spec_path.read_text(encoding="utf-8")
    try:
        source_spec_index_content = spec_index_path.read_text(encoding="utf-8")
        source_spec_index = json.loads(source_spec_index_content)
    except json.JSONDecodeError:
        result["errors"].append(
            {
                "type": "invalid_spec_index",
                "lib_id": source_lib_id,
                "error": "Source library spec_index.json is invalid JSON.",
            }
        )
        return result
    if not isinstance(source_spec_index, dict):
        result["errors"].append(
            {
                "type": "invalid_spec_index",
                "lib_id": source_lib_id,
                "error": "Source library spec_index.json must be an object.",
            }
        )
        return result
    source_spec_index.setdefault("file_manifest", manager.state.file_manifest)

    try:
        source_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        source_evidence = {"sources": []}

    split_groups = split_proposal.get("split_groups")
    if not isinstance(split_groups, list):
        split_groups = [split_proposal]
    split_groups = [group for group in split_groups if isinstance(group, dict)]
    if not split_groups:
        result["errors"].append(
            {
                "type": "invalid_split_proposal",
                "lib_id": source_lib_id,
                "error": "Split proposal missing groups.",
            }
        )
        return result

    new_lib_ids: list[str] = []
    created_dirs: list[Path] = []
    pre_split_allocated_ids = set(manager.state.allocated_library_ids)
    pre_split_next_number = manager.state.next_library_number
    try:
        for group in split_groups:
            new_lib_id = _create_split_library(
                manager,
                source_lib_id,
                group,
                source_spec_index,
                source_evidence,
            )
            new_lib_ids.append(new_lib_id)
            created_dirs.append(manager.structure.libraries_dir / new_lib_id)

            issues = _validate_split_artifacts(manager, new_lib_id)
            if issues:
                repaired = _repair_split_artifacts(manager, new_lib_id, issues)
                if repaired:
                    issues = _validate_split_artifacts(manager, new_lib_id)
            if issues:
                result["validation_issues"].extend(issues)
                raise RuntimeError("Split library validation failed.")
    except Exception as exc:
        for lib_dir in created_dirs:
            shutil.rmtree(lib_dir, ignore_errors=True)
        manager.state.allocated_library_ids = pre_split_allocated_ids
        manager.state.next_library_number = pre_split_next_number
        manager.save_state()
        result["errors"].append(
            {
                "type": "split_failed",
                "lib_id": source_lib_id,
                "error": str(exc),
            }
        )
        return result

    updated_spec_content = source_spec_content
    for group, new_lib_id in zip(split_groups, new_lib_ids, strict=False):
        updated_spec_content = _add_spec_tombstones(
            updated_spec_content,
            list(group.get("element_ids", [])),
            new_lib_id,
        )

    try:
        spec_path.write_text(updated_spec_content, encoding="utf-8")
        updated_index = build_spec_index(updated_spec_content, source_lib_id)
        for key, value in source_spec_index.items():
            if key not in updated_index:
                updated_index[key] = value
        (lib_dir / "spec_index.json").write_text(
            json.dumps(updated_index, indent=2),
            encoding="utf-8",
        )
        existing_events = _read_library_events(lib_dir)
        split_event = LibraryEvent(
            event_type=LibraryEventType.LIBRARY_SPLIT,
            timestamp=datetime.now().isoformat(),
            lib_id=source_lib_id,
            metadata={
                "target_libs": new_lib_ids,
                "split_groups": len(split_groups),
                "reason": action.summary,
                "element_count": sum(
                    len(group.get("element_ids", []))
                    for group in split_groups
                    if isinstance(group, dict)
                ),
            },
            previous_state=None,
        )
        _rewrite_library_events(lib_dir, [*existing_events, split_event])
    except Exception as exc:
        spec_path.write_text(source_spec_content, encoding="utf-8")
        spec_index_path.write_text(source_spec_index_content, encoding="utf-8")
        for lib_dir in created_dirs:
            shutil.rmtree(lib_dir, ignore_errors=True)
        manager.state.allocated_library_ids = pre_split_allocated_ids
        manager.state.next_library_number = pre_split_next_number
        manager.save_state()
        result["errors"].append(
            {
                "type": "split_event_failed",
                "lib_id": source_lib_id,
                "error": str(exc),
            }
        )
        return result

    manager.save_state()
    result["new_lib_ids"] = new_lib_ids
    return result


def _apply_single_move(
    manager: WorkspaceManager,
    action: ReviewAction,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "action_id": action.action_id,
        "source_lib": None,
        "target_lib": None,
        "elements_moved": 0,
        "errors": [],
    }

    if len(action.source_libs) != 1 or len(action.target_libs) != 1:
        result["errors"].append(
            {
                "type": "invalid_move_action",
                "error": "Move action must include exactly one source and one target library.",
            }
        )
        return result

    source_lib_id = action.source_libs[0]
    target_lib_id = action.target_libs[0]
    result["source_lib"] = source_lib_id
    result["target_lib"] = target_lib_id

    if source_lib_id == target_lib_id:
        result["errors"].append(
            {
                "type": "invalid_move_action",
                "error": "Move action cannot target the same library as the source.",
            }
        )
        return result

    source_dir = manager.structure.libraries_dir / source_lib_id
    target_dir = manager.structure.libraries_dir / target_lib_id
    if not source_dir.exists() or not target_dir.exists():
        result["errors"].append(
            {
                "type": "missing_library",
                "error": "Source or target library directory not found.",
            }
        )
        return result

    source_spec_path = source_dir / "spec.md"
    source_evidence_path = source_dir / "evidence.json"
    source_spec_index_path = source_dir / "spec_index.json"
    target_spec_path = target_dir / "spec.md"
    target_evidence_path = target_dir / "evidence.json"
    target_spec_index_path = target_dir / "spec_index.json"

    if not source_spec_path.exists() or not target_spec_path.exists():
        result["errors"].append(
            {
                "type": "missing_spec",
                "error": "Source or target spec.md missing.",
            }
        )
        return result

    if not source_spec_index_path.exists() or not target_spec_index_path.exists():
        result["errors"].append(
            {
                "type": "missing_spec_index",
                "error": "Source or target spec_index.json missing.",
            }
        )
        return result

    if not source_evidence_path.exists() or not target_evidence_path.exists():
        result["errors"].append(
            {
                "type": "missing_evidence",
                "error": "Source or target evidence.json missing.",
            }
        )
        return result

    source_spec_content = source_spec_path.read_text(encoding="utf-8")
    target_spec_content = target_spec_path.read_text(encoding="utf-8")

    try:
        source_spec_index_content = source_spec_index_path.read_text(encoding="utf-8")
        source_spec_index = json.loads(source_spec_index_content)
    except json.JSONDecodeError:
        result["errors"].append(
            {
                "type": "invalid_spec_index",
                "lib_id": source_lib_id,
                "error": "Source library spec_index.json is invalid JSON.",
            }
        )
        return result
    if not isinstance(source_spec_index, dict):
        result["errors"].append(
            {
                "type": "invalid_spec_index",
                "lib_id": source_lib_id,
                "error": "Source library spec_index.json must be an object.",
            }
        )
        return result
    source_spec_index.setdefault("file_manifest", manager.state.file_manifest)

    try:
        target_spec_index_content = target_spec_index_path.read_text(encoding="utf-8")
        target_spec_index = json.loads(target_spec_index_content)
    except json.JSONDecodeError:
        result["errors"].append(
            {
                "type": "invalid_spec_index",
                "lib_id": target_lib_id,
                "error": "Target library spec_index.json is invalid JSON.",
            }
        )
        return result
    if not isinstance(target_spec_index, dict):
        result["errors"].append(
            {
                "type": "invalid_spec_index",
                "lib_id": target_lib_id,
                "error": "Target library spec_index.json must be an object.",
            }
        )
        return result
    target_spec_index.setdefault("file_manifest", manager.state.file_manifest)

    try:
        source_evidence = json.loads(source_evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        source_evidence = {"sources": []}

    try:
        target_evidence = json.loads(target_evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        target_evidence = {"sources": []}

    element_ids = [element_id for element_id in action.elements if element_id]
    if not element_ids:
        logger.warning("Move action %s has no elements.", action.action_id)
        result["errors"].append(
            {
                "type": "empty_elements",
                "error": "Move action has no elements to move.",
            }
        )
        return result

    target_existing_ids = {
        extract_existing_id(line)
        for line in target_spec_content.splitlines()
        if extract_existing_id(line)
    }

    filtered_ids: list[str] = []
    for element_id in element_ids:
        if f"-{target_lib_id}-" in element_id:
            logger.warning(
                "Skipping element %s already scoped to target library %s.",
                element_id,
                target_lib_id,
            )
            continue
        if f"-{source_lib_id}-" not in element_id:
            logger.warning(
                "Skipping element %s not scoped to source library %s.",
                element_id,
                source_lib_id,
            )
            continue
        if element_id in target_existing_ids:
            logger.warning("Skipping element %s already present in target spec.", element_id)
            continue
        filtered_ids.append(element_id)

    unique_filtered: list[str] = []
    seen_ids: set[str] = set()
    for element_id in filtered_ids:
        if element_id in seen_ids:
            continue
        seen_ids.add(element_id)
        unique_filtered.append(element_id)
    filtered_ids = unique_filtered

    if not filtered_ids:
        result["errors"].append(
            {
                "type": "no_elements_to_move",
                "error": "No eligible elements remained after filtering.",
            }
        )
        return result

    elements = _extract_elements_from_spec(source_spec_content, filtered_ids)
    missing_ids = [element_id for element_id in filtered_ids if element_id not in elements]
    for missing_id in missing_ids:
        logger.warning(
            "Move action %s missing element %s in source spec.",
            action.action_id,
            missing_id,
        )
    filtered_ids = [element_id for element_id in filtered_ids if element_id in elements]
    if not filtered_ids:
        result["errors"].append(
            {
                "type": "no_elements_found",
                "error": "No matching elements found in source spec.",
            }
        )
        return result

    source_spec_backup = source_spec_content
    target_spec_backup = target_spec_content
    source_evidence_backup = copy.deepcopy(source_evidence)
    target_evidence_backup = copy.deepcopy(target_evidence)
    source_events_backup = copy.deepcopy(_read_library_events(source_dir))
    target_events_backup = copy.deepcopy(_read_library_events(target_dir))
    source_spec_index_backup = source_spec_index_content
    target_spec_index_backup = target_spec_index_content

    def _validate_spec_content(
        lib_id: str,
        spec_content: str,
        spec_index_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for element in spec_index_payload.get("elements", []) or []:
            element_id = str(element.get("element_id", "")).strip()
            if not element_id:
                continue
            if not _ELEMENT_ID_RE.fullmatch(element_id):
                issues.append(
                    {
                        "type": "invalid_element_id",
                        "artifact": "spec",
                        "lib_id": lib_id,
                        "element_id": element_id,
                        "message": "Element ID does not match expected pattern.",
                    }
                )
                continue
            if f"-{lib_id}-" not in element_id:
                issues.append(
                    {
                        "type": "element_id_mismatch",
                        "artifact": "spec",
                        "lib_id": lib_id,
                        "element_id": element_id,
                        "message": "Element ID does not match library ID.",
                    }
                )

        for pointer in re.findall(r"\[[^\[\]]+::[^\[\]]+\]", spec_content or ""):
            valid, error_msg = validate_pointer_references(
                pointer,
                manager.state.file_manifest,
                manager.allocated_library_ids,
            )
            if not valid:
                issues.append(
                    {
                        "type": "invalid_pointer",
                        "artifact": "spec",
                        "lib_id": lib_id,
                        "pointer": pointer,
                        "message": error_msg or "Invalid pointer reference.",
                    }
                )
        return issues

    try:
        updated_source_spec = _add_spec_tombstones(source_spec_content, filtered_ids, target_lib_id)
        updated_target_spec = _append_elements_to_spec(
            target_spec_content, elements, target_lib_id, source_lib_id
        )

        updated_source_evidence, updated_target_evidence = _update_evidence_for_move(
            source_evidence,
            target_evidence,
            filtered_ids,
            source_spec_index,
            target_spec_index,
        )

        source_spec_path.write_text(updated_source_spec, encoding="utf-8")
        target_spec_path.write_text(updated_target_spec, encoding="utf-8")
        source_evidence_path.write_text(
            json.dumps(updated_source_evidence, indent=2), encoding="utf-8"
        )
        target_evidence_path.write_text(
            json.dumps(updated_target_evidence, indent=2), encoding="utf-8"
        )

        updated_source_index = build_spec_index(updated_source_spec, source_lib_id)
        for key, value in source_spec_index.items():
            if key not in updated_source_index:
                updated_source_index[key] = value
        updated_target_index = build_spec_index(updated_target_spec, target_lib_id)
        for key, value in target_spec_index.items():
            if key not in updated_target_index:
                updated_target_index[key] = value
        source_spec_index_path.write_text(
            json.dumps(updated_source_index, indent=2), encoding="utf-8"
        )
        target_spec_index_path.write_text(
            json.dumps(updated_target_index, indent=2), encoding="utf-8"
        )

        validation_issues = _validate_spec_content(
            source_lib_id, updated_source_spec, updated_source_index
        ) + _validate_spec_content(target_lib_id, updated_target_spec, updated_target_index)

        if validation_issues:
            issues_by_lib: dict[str, list[dict[str, Any]]] = {
                source_lib_id: [],
                target_lib_id: [],
            }
            for issue in validation_issues:
                issues_by_lib.setdefault(issue.get("lib_id", ""), []).append(issue)

            for lib_id, issues in issues_by_lib.items():
                if issues:
                    _repair_split_artifacts(manager, lib_id, issues)

            updated_source_spec = source_spec_path.read_text(encoding="utf-8")
            updated_target_spec = target_spec_path.read_text(encoding="utf-8")
            updated_source_index = build_spec_index(updated_source_spec, source_lib_id)
            for key, value in source_spec_index.items():
                if key not in updated_source_index:
                    updated_source_index[key] = value
            updated_target_index = build_spec_index(updated_target_spec, target_lib_id)
            for key, value in target_spec_index.items():
                if key not in updated_target_index:
                    updated_target_index[key] = value
            source_spec_index_path.write_text(
                json.dumps(updated_source_index, indent=2), encoding="utf-8"
            )
            target_spec_index_path.write_text(
                json.dumps(updated_target_index, indent=2), encoding="utf-8"
            )
            validation_issues = _validate_spec_content(
                source_lib_id, updated_source_spec, updated_source_index
            ) + _validate_spec_content(target_lib_id, updated_target_spec, updated_target_index)

        if validation_issues:
            raise RuntimeError("Move validation failed.")

        moved_validation_issues = _validate_moved_elements(
            updated_source_spec, updated_target_spec, filtered_ids, target_lib_id
        )
        if moved_validation_issues:
            raise RuntimeError("Moved element validation failed.")

        existing_target_ids = {
            element.get("element_id")
            for element in target_spec_index.get("elements", []) or []
            if isinstance(element, dict)
        }
        new_element_ids = [
            element.get("element_id")
            for element in updated_target_index.get("elements", []) or []
            if isinstance(element, dict)
            and element.get("element_id")
            and element.get("element_id") not in existing_target_ids
            and f"-{target_lib_id}-" in element.get("element_id")
        ]
        source_events = _read_library_events(source_dir)
        target_events = _read_library_events(target_dir)
        source_events.append(
            LibraryEvent(
                event_type=LibraryEventType.BOUNDARY_CHANGED,
                timestamp=datetime.now().isoformat(),
                lib_id=source_lib_id,
                metadata={
                    "action": "elements_moved_out",
                    "target_lib": target_lib_id,
                    "element_ids": filtered_ids,
                    "element_count": len(filtered_ids),
                    "reason": action.summary,
                },
                previous_state=None,
            )
        )
        target_events.append(
            LibraryEvent(
                event_type=LibraryEventType.BOUNDARY_CHANGED,
                timestamp=datetime.now().isoformat(),
                lib_id=target_lib_id,
                metadata={
                    "action": "elements_moved_in",
                    "source_lib": source_lib_id,
                    "element_ids": new_element_ids,
                    "element_count": len(new_element_ids),
                    "reason": action.summary,
                },
                previous_state=None,
            )
        )
        _rewrite_library_events(source_dir, source_events)
        _rewrite_library_events(target_dir, target_events)
    except Exception as exc:
        source_spec_path.write_text(source_spec_backup, encoding="utf-8")
        target_spec_path.write_text(target_spec_backup, encoding="utf-8")
        source_evidence_path.write_text(
            json.dumps(source_evidence_backup, indent=2), encoding="utf-8"
        )
        target_evidence_path.write_text(
            json.dumps(target_evidence_backup, indent=2), encoding="utf-8"
        )
        source_spec_index_path.write_text(source_spec_index_backup, encoding="utf-8")
        target_spec_index_path.write_text(target_spec_index_backup, encoding="utf-8")
        _rewrite_library_events(source_dir, source_events_backup)
        _rewrite_library_events(target_dir, target_events_backup)
        logger.exception(
            "Move action %s failed for %s -> %s",
            action.action_id,
            source_lib_id,
            target_lib_id,
        )
        result["errors"].append(
            {
                "type": "move_failed",
                "error": str(exc),
            }
        )
        return result

    result["elements_moved"] = len(filtered_ids)
    manager.save_state()
    return result


def apply_split_actions(
    manager: WorkspaceManager,
    review_actions_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply proposed library split actions from a review actions file."""
    summary: dict[str, Any] = {
        "applied_actions": [],
        "rejected_actions": [],
        "new_library_ids": [],
        "validation_issues": [],
        "action_errors": [],
        "errors": [],
        "dry_run": dry_run,
    }
    summary: dict[str, Any] = {
        "applied_actions": [],
        "rejected_actions": [],
        "new_library_ids": [],
        "validation_issues": [],
        "action_errors": [],
        "errors": [],
        "dry_run": dry_run,
    }

    try:
        report = read_review_actions_json(review_actions_path)
    except Exception as exc:
        summary["errors"].append({"type": "review_actions_read_failed", "error": str(exc)})
        summary["success"] = False
        return summary

    split_actions = [
        action
        for action in report.actions
        if action.type == "split" and action.status == "proposed"
    ]

    if dry_run:
        summary["applied_actions"] = [action.action_id for action in split_actions]
        summary["applied_count"] = len(summary["applied_actions"])
        summary["rejected_count"] = 0
        summary["success"] = True
        return summary

    for action in split_actions:
        split_group = _derive_split_group_from_action(action)
        result = _apply_single_split(manager, action, {"split_groups": [split_group]})
        if result.get("errors"):
            action.status = "rejected"
            action.notes = "; ".join(error.get("error", "error") for error in result["errors"])
            summary["rejected_actions"].append(action.action_id)
            summary["action_errors"].extend(result["errors"])
            if result.get("validation_issues"):
                summary["validation_issues"].extend(result["validation_issues"])
            continue

        new_lib_ids = result.get("new_lib_ids", [])
        action.status = "applied"
        if new_lib_ids:
            action.target_libs = list(new_lib_ids)
        summary["applied_actions"].append(action.action_id)
        summary["new_library_ids"].extend(new_lib_ids)
        if result.get("validation_issues"):
            summary["validation_issues"].extend(result["validation_issues"])

    try:
        write_review_actions_json(report, review_actions_path)
    except Exception as exc:
        summary["errors"].append({"type": "review_actions_write_failed", "error": str(exc)})

    summary["applied_count"] = len(summary["applied_actions"])
    summary["rejected_count"] = len(summary["rejected_actions"])
    summary["success"] = not summary["errors"]
    return summary


def apply_move_actions(
    manager: WorkspaceManager,
    actions: list[ReviewAction],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply proposed move_elements actions from a review actions list."""
    summary: dict[str, Any] = {
        "applied": 0,
        "failed": 0,
        "results": [],
    }

    move_actions = [
        action
        for action in actions
        if action.type == "move_elements" and action.status == "proposed"
    ]

    if dry_run:
        summary["applied"] = len(move_actions)
        summary["results"] = [
            {"action_id": action.action_id, "dry_run": True} for action in move_actions
        ]
        return summary

    for action in move_actions:
        logger.info("Applying move action %s", action.action_id)
        result = _apply_single_move(manager, action)
        summary["results"].append(result)
        if result.get("errors"):
            summary["failed"] += 1
        else:
            summary["applied"] += 1

    return summary


def review_library_structure(
    run_id: str,
    apply_splits: bool = False,
    apply_moves: bool = False,
) -> dict[str, Any]:
    """Run Phase 7 library structure review."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    stabilization_status = manager.state.phases[Phase.SPEC_STABILIZATION.value].status
    if stabilization_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Spec stabilization must be completed before library structure review.")

    manager.start_phase(Phase.LIBRARY_STRUCTURE_REVIEW)

    tracker = ProgressTracker(
        total=1,
        description="Reviewing library structure",
        manager=manager,
    )

    try:
        results = detect_structure_issues(manager, thresholds=None, consolidate=True)
    except Exception as exc:
        tracker.finish()
        manager.fail_phase(Phase.LIBRARY_STRUCTURE_REVIEW, error=str(exc))
        return {
            "success": False,
            "overlap_candidates_count": 0,
            "split_candidates_count": 0,
            "report_paths": {},
            "errors": [{"error": str(exc)}],
        }

    tracker.update(status="review complete")
    tracker.finish()

    overlap_candidates = results.get("overlap_candidates", [])
    split_candidates = results.get("split_candidates", [])
    report_paths = results.get("report_paths", {})
    errors = results.get("errors", [])
    split_application: dict[str, Any] | None = None
    move_application: dict[str, Any] | None = None

    review_actions_path: Path | None = None
    if apply_splits or apply_moves:
        report_path_value = report_paths.get("json") or (
            manager.structure.reports_dir / "review_actions.json"
        )
        review_actions_path = Path(report_path_value)

    if apply_splits:
        if not review_actions_path or not review_actions_path.exists():
            errors.append(
                {
                    "type": "review_actions_missing",
                    "error": f"Review actions report not found at {review_actions_path}",
                }
            )
        else:
            split_application = apply_split_actions(manager, review_actions_path)
            if split_application.get("errors"):
                errors.extend(
                    {
                        "type": "split_application_failed",
                        "error": error.get("error", "split application failed"),
                    }
                    for error in split_application["errors"]
                )

    if apply_moves:
        if not review_actions_path or not review_actions_path.exists():
            logger.warning(
                "Review actions report missing for move application at %s.",
                review_actions_path,
            )
        else:
            try:
                move_report = read_review_actions_json(review_actions_path)
            except Exception as exc:
                logger.warning("Failed to read review actions for moves: %s", exc)
            else:
                move_application = apply_move_actions(manager, move_report.actions, dry_run=False)
                logger.info(
                    "Applied %s move actions, %s failed",
                    move_application.get("applied", 0),
                    move_application.get("failed", 0),
                )
                if move_application.get("failed"):
                    logger.warning("Move action failures detected; moves are optional.")
    success = not errors

    outputs = {
        "overlap_candidates_count": len(overlap_candidates),
        "split_candidates_count": len(split_candidates),
        "report_paths": report_paths,
    }
    if split_application is not None:
        outputs["split_application"] = split_application
    if move_application is not None:
        outputs["move_application"] = move_application
    if success:
        manager.complete_phase(Phase.LIBRARY_STRUCTURE_REVIEW, outputs=outputs)
    else:
        manager.fail_phase(
            Phase.LIBRARY_STRUCTURE_REVIEW,
            error="; ".join(e.get("error", str(e)) for e in errors),
        )

    return {
        "success": success,
        "overlap_candidates_count": len(overlap_candidates),
        "split_candidates_count": len(split_candidates),
        "report_paths": report_paths,
        "split_application": split_application,
        "move_application": move_application,
        "errors": errors,
    }
