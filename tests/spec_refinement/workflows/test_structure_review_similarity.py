from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from spec_manager.refinement.workflows.library_structure_review import (
    _build_tfidf_vectors,
    _compute_pairwise_similarity,
    _compute_shared_element_count,
    _extract_matched_element_pairs,
    detect_overlap_candidates,
    detect_split_candidates,
)
from spec_manager.schemas.spec_indexes import SpecElement, SpecIndex


def _element_dict(
    lib_id: str,
    index: int,
    *,
    kind: str = "requirement",
    text: str = "alpha",
    element_id: str | None = None,
) -> dict[str, object]:
    lib_suffix = lib_id.split("-", 1)[1]
    if element_id is None:
        if kind == "requirement":
            element_id = f"REQ-LIB-{lib_suffix}-{index:04d}"
        elif kind == "invariant":
            element_id = f"INV-LIB-{lib_suffix}-{index:04d}"
        elif kind == "flow":
            element_id = f"FLOW-LIB-{lib_suffix}-{index:02d}"
        else:
            element_id = f"REQ-LIB-{lib_suffix}-{index:04d}"
    section = "Requirements"
    if kind == "flow":
        section = "Flows"
    elif kind == "invariant":
        section = "Constraints"
    return {
        "element_id": element_id,
        "kind": kind,
        "section": section,
        "text": text,
        "raw_line": f"- {element_id}: {text}",
        "citations": [],
        "mentions_libs": [],
    }


def _spec_index_payload(lib_id: str, elements: list[dict[str, object]]) -> dict[str, object]:
    return {
        "lib_id": lib_id,
        "generated_at": "2024-01-01T00:00:00",
        "spec_path": f"libraries/{lib_id}/spec.md",
        "elements": elements,
    }


def _create_spec_index(manager, lib_id: str, elements: list[dict[str, object]]) -> None:
    lib_dir = manager.structure.libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)
    payload = _spec_index_payload(lib_id, elements)
    (lib_dir / "spec_index.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_build_tfidf_vectors_from_spec_indexes() -> None:
    spec_indexes = {
        "LIB-0001": SpecIndex.model_validate(
            _spec_index_payload(
                "LIB-0001",
                [_element_dict("LIB-0001", 1, text="alpha beta")],
            )
        ),
        "LIB-0002": SpecIndex.model_validate(
            _spec_index_payload(
                "LIB-0002",
                [_element_dict("LIB-0002", 1, text="gamma delta")],
            )
        ),
    }

    vectors, vectorizer = _build_tfidf_vectors(spec_indexes)

    assert set(vectors.keys()) == {"LIB-0001", "LIB-0002"}
    vocab_size = len(vectorizer.vocabulary_)
    assert vocab_size > 0
    for vector in vectors.values():
        assert vector.shape[0] == vocab_size


def test_tfidf_ignores_element_ids_and_citations() -> None:
    text = (
        "Alpha REQ-LIB-9999-9999 "
        "[LIB-9999::spec.md::REQ-LIB-9999-9999] "
        "[spec_snapshot/specs/alpha.md::SEC-F0001-0001]"
    )
    spec_indexes = {
        "LIB-0001": SpecIndex.model_validate(
            _spec_index_payload(
                "LIB-0001",
                [_element_dict("LIB-0001", 1, text=text)],
            )
        )
    }

    _vectors, vectorizer = _build_tfidf_vectors(spec_indexes)
    vocab = set(vectorizer.vocabulary_)

    assert "alpha" in vocab
    assert "9999" not in vocab
    assert "lib" not in vocab
    assert "spec" not in vocab


def test_tfidf_handles_empty_library() -> None:
    spec_indexes = {
        "LIB-0001": SpecIndex.model_validate(_spec_index_payload("LIB-0001", [])),
        "LIB-0002": SpecIndex.model_validate(
            _spec_index_payload("LIB-0002", [_element_dict("LIB-0002", 1, text="alpha")])
        ),
    }

    vectors, _vectorizer = _build_tfidf_vectors(spec_indexes)

    assert np.allclose(vectors["LIB-0001"], 0.0)
    assert not np.allclose(vectors["LIB-0002"], 0.0)


def test_tfidf_normalizes_text() -> None:
    spec_indexes = {
        "LIB-0001": SpecIndex.model_validate(
            _spec_index_payload(
                "LIB-0001",
                [_element_dict("LIB-0001", 1, text="Hello, WORLD! cache-size")],
            )
        )
    }

    _vectors, vectorizer = _build_tfidf_vectors(spec_indexes)
    vocab = set(vectorizer.vocabulary_)

    assert "hello" in vocab
    assert "world" in vocab
    assert "cache" in vocab
    assert "size" in vocab
    assert "WORLD" not in vocab


def test_compute_pairwise_similarity_basic() -> None:
    spec_indexes = {
        "LIB-0001": SpecIndex.model_validate(
            _spec_index_payload(
                "LIB-0001",
                [_element_dict("LIB-0001", 1, text="alpha beta")],
            )
        ),
        "LIB-0002": SpecIndex.model_validate(
            _spec_index_payload(
                "LIB-0002",
                [_element_dict("LIB-0002", 1, text="alpha gamma")],
            )
        ),
    }
    vectors, _vectorizer = _build_tfidf_vectors(spec_indexes)
    similarities = _compute_pairwise_similarity(vectors)

    score = similarities[("LIB-0001", "LIB-0002")]
    assert 0.0 < score < 1.0


def test_compute_pairwise_similarity_identical_libraries() -> None:
    elements = [_element_dict("LIB-0001", 1, text="alpha beta")]
    spec_indexes = {
        "LIB-0001": SpecIndex.model_validate(_spec_index_payload("LIB-0001", elements)),
        "LIB-0002": SpecIndex.model_validate(
            _spec_index_payload("LIB-0002", [_element_dict("LIB-0002", 1, text="alpha beta")])
        ),
    }
    vectors, _vectorizer = _build_tfidf_vectors(spec_indexes)
    similarities = _compute_pairwise_similarity(vectors)

    score = similarities[("LIB-0001", "LIB-0002")]
    assert score == pytest.approx(1.0, rel=1e-5)


def test_compute_pairwise_similarity_disjoint_libraries() -> None:
    spec_indexes = {
        "LIB-0001": SpecIndex.model_validate(
            _spec_index_payload("LIB-0001", [_element_dict("LIB-0001", 1, text="alpha")])
        ),
        "LIB-0002": SpecIndex.model_validate(
            _spec_index_payload("LIB-0002", [_element_dict("LIB-0002", 1, text="beta")])
        ),
    }
    vectors, _vectorizer = _build_tfidf_vectors(spec_indexes)
    similarities = _compute_pairwise_similarity(vectors)

    score = similarities[("LIB-0001", "LIB-0002")]
    assert score <= 0.01


def test_compute_pairwise_similarity_matrix_symmetry() -> None:
    spec_indexes = {
        "LIB-0001": SpecIndex.model_validate(
            _spec_index_payload("LIB-0001", [_element_dict("LIB-0001", 1, text="alpha beta")])
        ),
        "LIB-0002": SpecIndex.model_validate(
            _spec_index_payload("LIB-0002", [_element_dict("LIB-0002", 1, text="alpha beta")])
        ),
    }
    vectors, _vectorizer = _build_tfidf_vectors(spec_indexes)
    similarities_a = _compute_pairwise_similarity(vectors)
    similarities_b = _compute_pairwise_similarity(
        {"LIB-0002": vectors["LIB-0002"], "LIB-0001": vectors["LIB-0001"]}
    )

    assert similarities_a[("LIB-0001", "LIB-0002")] == pytest.approx(
        similarities_b[("LIB-0001", "LIB-0002")]
    )


def test_compute_shared_element_count() -> None:
    spec_a = SpecIndex.model_validate(
        _spec_index_payload(
            "LIB-0001",
            [
                _element_dict("LIB-0001", 1, text="alpha"),
                _element_dict("LIB-0001", 2, text="beta"),
                _element_dict("LIB-0001", 3, text="gamma"),
            ],
        )
    )
    spec_b = SpecIndex.model_validate(
        _spec_index_payload(
            "LIB-0002",
            [
                _element_dict("LIB-0002", 1, text="alpha"),
                _element_dict("LIB-0002", 2, text="beta"),
                _element_dict("LIB-0002", 3, text="gamma"),
            ],
        )
    )
    _, vectorizer = _build_tfidf_vectors({"LIB-0001": spec_a, "LIB-0002": spec_b})
    assert _compute_shared_element_count(spec_a, spec_b, vectorizer) == 3


def test_extract_matched_element_pairs() -> None:
    spec_a = SpecIndex.model_validate(
        _spec_index_payload(
            "LIB-0001",
            [
                _element_dict("LIB-0001", 1, text="alpha beta"),
                _element_dict("LIB-0001", 2, text="gamma delta"),
            ],
        )
    )
    spec_b = SpecIndex.model_validate(
        _spec_index_payload(
            "LIB-0002",
            [
                _element_dict("LIB-0002", 1, text="alpha beta"),
                _element_dict("LIB-0002", 2, text="gamma delta"),
            ],
        )
    )

    _vectors, vectorizer = _build_tfidf_vectors({"LIB-0001": spec_a, "LIB-0002": spec_b})
    pairs = _extract_matched_element_pairs(spec_a, spec_b, vectorizer, top_n=2)

    assert len(pairs) == 2
    assert pairs[0]["similarity"] >= pairs[1]["similarity"]


def test_matched_pairs_include_all_element_types() -> None:
    elements_a = [
        SpecElement.model_construct(
            element_id="REQ-LIB-0001-0001",
            kind="requirement",
            section="Requirements",
            text="alpha req",
            raw_line="",
            citations=[],
            mentions_libs=[],
        ),
        SpecElement.model_construct(
            element_id="INV-LIB-0001-0001",
            kind="invariant",
            section="Constraints",
            text="beta inv",
            raw_line="",
            citations=[],
            mentions_libs=[],
        ),
        SpecElement.model_construct(
            element_id="FLOW-LIB-0001-01",
            kind="flow",
            section="Flows",
            text="gamma flow",
            raw_line="",
            citations=[],
            mentions_libs=[],
        ),
        SpecElement.model_construct(
            element_id="DEC-LIB-0001-0001",
            kind="decision",
            section="Decisions",
            text="delta decision",
            raw_line="",
            citations=[],
            mentions_libs=[],
        ),
    ]
    elements_b = [
        SpecElement.model_construct(
            element_id="REQ-LIB-0002-0001",
            kind="requirement",
            section="Requirements",
            text="alpha req",
            raw_line="",
            citations=[],
            mentions_libs=[],
        ),
        SpecElement.model_construct(
            element_id="INV-LIB-0002-0001",
            kind="invariant",
            section="Constraints",
            text="beta inv",
            raw_line="",
            citations=[],
            mentions_libs=[],
        ),
        SpecElement.model_construct(
            element_id="FLOW-LIB-0002-01",
            kind="flow",
            section="Flows",
            text="gamma flow",
            raw_line="",
            citations=[],
            mentions_libs=[],
        ),
        SpecElement.model_construct(
            element_id="DEC-LIB-0002-0001",
            kind="decision",
            section="Decisions",
            text="delta decision",
            raw_line="",
            citations=[],
            mentions_libs=[],
        ),
    ]

    spec_a = SpecIndex.model_construct(
        lib_id="LIB-0001",
        generated_at="2024-01-01T00:00:00",
        spec_path="libraries/LIB-0001/spec.md",
        elements=elements_a,
    )
    spec_b = SpecIndex.model_construct(
        lib_id="LIB-0002",
        generated_at="2024-01-01T00:00:00",
        spec_path="libraries/LIB-0002/spec.md",
        elements=elements_b,
    )

    _vectors, vectorizer = _build_tfidf_vectors({"LIB-0001": spec_a, "LIB-0002": spec_b})
    pairs = _extract_matched_element_pairs(spec_a, spec_b, vectorizer, top_n=10)

    prefixes = {pair["element_a_id"].split("-", 1)[0] for pair in pairs}
    assert {"REQ", "INV", "FLOW", "DEC"}.issubset(prefixes)


def test_detect_overlap_candidates_above_threshold(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text="shared alpha") for idx in range(1, 7)]
    elements_b = [_element_dict("LIB-0002", idx, text="shared alpha") for idx in range(1, 7)]
    _create_spec_index(manager, "LIB-0001", elements)
    _create_spec_index(manager, "LIB-0002", elements_b)

    candidates = detect_overlap_candidates(manager, overlap_threshold=0.4, min_shared_elements=5)

    assert len(candidates) == 1
    assert candidates[0]["shared_element_count"] >= 5
    assert candidates[0]["similarity"] >= 0.4


def test_detect_overlap_candidates_below_similarity_threshold(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    _create_spec_index(
        manager,
        "LIB-0001",
        [_element_dict("LIB-0001", 1, text="alpha")],
    )
    _create_spec_index(
        manager,
        "LIB-0002",
        [_element_dict("LIB-0002", 1, text="beta")],
    )

    candidates = detect_overlap_candidates(manager, overlap_threshold=0.3, min_shared_elements=1)

    assert candidates == []


def test_detect_overlap_candidates_below_shared_elements_threshold(
    spec_refinement_workspace,
) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text="shared alpha") for idx in range(1, 4)]
    elements_b = [_element_dict("LIB-0002", idx, text="shared alpha") for idx in range(1, 4)]
    _create_spec_index(manager, "LIB-0001", elements)
    _create_spec_index(manager, "LIB-0002", elements_b)

    candidates = detect_overlap_candidates(manager, overlap_threshold=0.3, min_shared_elements=5)

    assert candidates == []


def test_detect_overlap_candidates_returns_evidence(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text=f"shared alpha {idx}") for idx in range(1, 7)]
    elements_b = [_element_dict("LIB-0002", idx, text=f"shared alpha {idx}") for idx in range(1, 7)]
    _create_spec_index(manager, "LIB-0001", elements)
    _create_spec_index(manager, "LIB-0002", elements_b)

    candidates = detect_overlap_candidates(manager, overlap_threshold=0.3, min_shared_elements=5)

    assert candidates
    evidence = candidates[0]["matched_elements"]
    assert evidence
    assert all("element_a_id" in pair and "element_b_id" in pair for pair in evidence)


def test_detect_overlap_candidates_deterministic_ordering(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text="shared alpha") for idx in range(1, 7)]
    elements_b = [_element_dict("LIB-0002", idx, text="shared alpha") for idx in range(1, 7)]
    _create_spec_index(manager, "LIB-0001", elements)
    _create_spec_index(manager, "LIB-0002", elements_b)

    first = detect_overlap_candidates(manager, overlap_threshold=0.3, min_shared_elements=5)
    second = detect_overlap_candidates(manager, overlap_threshold=0.3, min_shared_elements=5)

    assert first == second


def test_kmeans_clustering_basic(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text="alpha group") for idx in range(1, 6)] + [
        _element_dict("LIB-0001", idx + 5, text="beta group") for idx in range(1, 6)
    ]
    _create_spec_index(manager, "LIB-0001", elements)

    candidates = detect_split_candidates(manager, min_silhouette=0.0, min_elements=2)

    assert candidates
    assert candidates[0]["num_clusters"] == 2


def test_compute_silhouette_score(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text="alpha group") for idx in range(1, 6)] + [
        _element_dict("LIB-0001", idx + 5, text="beta group") for idx in range(1, 6)
    ]
    _create_spec_index(manager, "LIB-0001", elements)

    candidates = detect_split_candidates(manager, min_silhouette=0.0, min_elements=2)

    score = candidates[0]["silhouette_score"]
    assert -1.0 <= score <= 1.0


def test_clustering_with_insufficient_elements(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    _create_spec_index(manager, "LIB-0001", [_element_dict("LIB-0001", 1, text="alpha")])

    candidates = detect_split_candidates(manager, min_silhouette=0.0, min_elements=1)

    assert candidates == []


def test_clustering_deterministic_with_random_state(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text="alpha group") for idx in range(1, 6)] + [
        _element_dict("LIB-0001", idx + 5, text="beta group") for idx in range(1, 6)
    ]
    _create_spec_index(manager, "LIB-0001", elements)

    first = detect_split_candidates(manager, min_silhouette=0.0, min_elements=2)
    second = detect_split_candidates(manager, min_silhouette=0.0, min_elements=2)

    assert first == second


def test_detect_split_candidates_high_silhouette(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text="alpha group") for idx in range(1, 6)] + [
        _element_dict("LIB-0001", idx + 5, text="beta group") for idx in range(1, 6)
    ]
    _create_spec_index(manager, "LIB-0001", elements)

    candidates = detect_split_candidates(manager, min_silhouette=0.4, min_elements=10)

    assert candidates
    assert candidates[0]["silhouette_score"] >= 0.4


def test_detect_split_candidates_low_silhouette(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text="alpha") for idx in range(1, 11)]
    _create_spec_index(manager, "LIB-0001", elements)

    candidates = detect_split_candidates(manager, min_silhouette=0.4, min_elements=10)

    assert candidates == []


def test_detect_split_candidates_tries_multiple_k(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 7)]
    _create_spec_index(manager, "LIB-0001", elements)

    called: list[int] = []

    def _fake_cluster(spec_index: SpecIndex, vectorizer, k: int):
        called.append(k)
        labels = np.zeros(len(spec_index.elements), dtype=int)
        score = {2: 0.1, 3: 0.4, 4: 0.2, 5: 0.3}[k]
        return labels, score

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review._cluster_library_elements",
        _fake_cluster,
    )

    candidates = detect_split_candidates(manager, min_silhouette=0.0, min_elements=2)

    assert called == [2, 3, 4, 5]
    assert candidates[0]["num_clusters"] == 3


def test_detect_split_candidates_includes_cluster_assignments(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_element_dict("LIB-0001", idx, text="alpha group") for idx in range(1, 6)] + [
        _element_dict("LIB-0001", idx + 5, text="beta group") for idx in range(1, 6)
    ]
    _create_spec_index(manager, "LIB-0001", elements)

    candidates = detect_split_candidates(manager, min_silhouette=0.0, min_elements=2)

    assignments = candidates[0]["cluster_assignments"]
    assert len(assignments) == len(elements)
    assert all(isinstance(value, int) for value in assignments.values())
