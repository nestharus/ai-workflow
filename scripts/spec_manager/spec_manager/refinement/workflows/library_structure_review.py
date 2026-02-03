"""Phase 7 library structure review workflow for overlap and split detection.

This module scans stabilized spec indexes, builds TF-IDF similarity signals, and
returns in-memory overlap/split candidates for downstream review agents.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_similarity

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
            for element, label in zip(elements, best_labels)
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
        logger.exception("Overlap detection failed: %s", exc)
        errors.append({"type": "overlap_detection_failed", "error": str(exc)})

    try:
        results["split_candidates"] = detect_split_candidates(
            manager,
            min_silhouette=effective_thresholds["split_silhouette"],
            min_elements=int(effective_thresholds["split_min_elements"]),
        )
    except Exception as exc:
        logger.exception("Split detection failed: %s", exc)
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
