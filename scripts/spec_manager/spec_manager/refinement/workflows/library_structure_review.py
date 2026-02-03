"""Phase 7 library structure review workflow for overlap and split detection.

This module scans stabilized spec indexes, builds TF-IDF similarity signals, and
returns in-memory overlap/split candidates for downstream review agents.
"""

from __future__ import annotations

import json
import logging
import re
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
from spec_manager.refinement.workspace import WorkspaceManager
from spec_manager.schemas.review_actions import ReviewActionsReport
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
) -> dict[str, Any]:
    """Run overlap and split detection with configurable thresholds.

    Args:
        manager: Workspace manager for the active refinement run.
        thresholds: Optional overrides for detection thresholds.

    Returns:
        Dictionary containing overlap/split candidates, applied thresholds, and any errors.
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
