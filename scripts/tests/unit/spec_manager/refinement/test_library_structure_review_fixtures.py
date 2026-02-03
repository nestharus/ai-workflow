"""Fixtures that document expected inputs/outputs for library structure review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem
from spec_manager.refinement.workspace import WorkspaceManager


_DEF_GENERATED_AT = "2026-02-03T00:00:00"


def _spec_index_payload(lib_id: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "lib_id": lib_id,
        "generated_at": _DEF_GENERATED_AT,
        "spec_path": f"libraries/{lib_id}/spec.md",
        "elements": elements,
    }


def _element_payload(element_id: str, text: str) -> dict[str, Any]:
    return {
        "element_id": element_id,
        "kind": "requirement",
        "section": "Requirements",
        "text": text,
        "raw_line": f"- [{element_id}] {text}",
        "citations": [],
        "mentions_libs": [],
    }


@pytest.fixture
def structure_review_spec_indexes_payload() -> dict[str, dict[str, Any]]:
    overlap_texts = [
        "alphaone betatwo gamma",
        "deltaone epsilontwo zeta",
        "etaone thetatwo iota",
        "kappaone lambdatwo mu",
        "nuone xitwo omicron",
    ]
    lib_a_elements = [
        _element_payload(f"REQ-LIB-0001-{index:04d}", text)
        for index, text in enumerate(overlap_texts, start=1)
    ]
    lib_b_elements = [
        _element_payload(f"REQ-LIB-0002-{index:04d}", text)
        for index, text in enumerate(overlap_texts, start=1)
    ]

    split_texts = [
        "billing invoice payment",
        "billing invoice refund",
        "billing payment settlement",
        "billing tax invoice",
        "billing credit invoice",
        "billing payment ledger",
        "auth login token",
        "auth login session",
        "auth token refresh",
        "auth session expiry",
        "auth multi factor",
        "auth password reset",
    ]
    split_elements = [
        _element_payload(f"REQ-LIB-0003-{index:04d}", text)
        for index, text in enumerate(split_texts, start=1)
    ]

    return {
        "LIB-0001": _spec_index_payload("LIB-0001", lib_a_elements),
        "LIB-0002": _spec_index_payload("LIB-0002", lib_b_elements),
        "LIB-0003": _spec_index_payload("LIB-0003", split_elements),
    }


@pytest.fixture
def structure_review_manager(
    fs: FakeFilesystem,
    monkeypatch: pytest.MonkeyPatch,
    structure_review_spec_indexes_payload: dict[str, dict[str, Any]],
) -> WorkspaceManager:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "intro.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")

    manager = WorkspaceManager(run_id="run1", input_folder=input_dir)
    manager.initialize(force=True)

    for lib_id, payload in structure_review_spec_indexes_payload.items():
        lib_dir = manager.structure.libraries_dir / lib_id
        lib_dir.mkdir(parents=True, exist_ok=True)
        (lib_dir / "spec_index.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    return manager


@pytest.fixture
def expected_overlap_candidates() -> list[dict[str, Any]]:
    overlap_texts = [
        "alphaone betatwo gamma",
        "deltaone epsilontwo zeta",
        "etaone thetatwo iota",
        "kappaone lambdatwo mu",
        "nuone xitwo omicron",
    ]
    matched_elements = [
        {
            "element_a_id": f"REQ-LIB-0001-{index:04d}",
            "element_a_text": text,
            "element_b_id": f"REQ-LIB-0002-{index:04d}",
            "element_b_text": text,
            "similarity": 1.0,
        }
        for index, text in enumerate(overlap_texts, start=1)
    ]

    return [
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0002",
            "similarity": 1.0,
            "shared_element_count": len(matched_elements),
            "matched_elements": matched_elements,
        }
    ]


@pytest.fixture
def expected_split_groups() -> list[set[str]]:
    billing_ids = {f"REQ-LIB-0003-{index:04d}" for index in range(1, 7)}
    auth_ids = {f"REQ-LIB-0003-{index:04d}" for index in range(7, 13)}
    return [billing_ids, auth_ids]


@pytest.fixture
def expected_split_candidate(expected_split_groups: list[set[str]]) -> dict[str, Any]:
    return {
        "lib_id": "LIB-0003",
        "num_clusters": 2,
        "expected_groups": expected_split_groups,
    }
