"""Tests for coordination/work_items.py."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from spec_manager.orchestration.coordination.work_items import (
    SearchQuery,
    WorkItem,
    WorkItemLocation,
    WorkItemStore,
    _fingerprint,
    _normalize,
    _tokenize,
)


def _make_item(
    title: str = "Calculate risk exposure for the portfolio",
    description: str = "",
    slice_id: str = "slice-treasury",
    status: str = "NEW",
    symbol: str = "RiskEngine.check_exposure",
    file_path: str = "risk_engine.py",
    shape_id: str = "shape.risk",
    phase: str = "architecture",
    required_change_type: str = "behavior_change",
    evidence_refs: list[str] | None = None,
    work_item_id: str | None = None,
) -> WorkItem:
    search_text = f"{title}\n{description}".strip()
    return WorkItem(
        work_item_id=work_item_id or _fingerprint(search_text),
        run_id="run-001",
        slice_id=slice_id,
        title=title,
        description=description,
        shape_id=shape_id,
        created_in_phase=phase,
        required_change_type=required_change_type,
        status=status,
        file_locations=[
            WorkItemLocation(file_path=file_path, symbol=symbol, line_start=10),
        ],
        evidence_refs=evidence_refs or [],
    )


class TestWorkItemSerialization:
    def test_to_dict_roundtrip(self):
        item = _make_item(evidence_refs=["tests/unit/test_file.py::test_case"])
        restored = WorkItem.from_dict(item.to_dict())
        assert restored.work_item_id == item.work_item_id
        assert restored.run_id == item.run_id
        assert restored.slice_id == item.slice_id
        assert restored.title == item.title
        assert restored.description == item.description
        assert restored.shape_id == item.shape_id
        assert restored.created_in_phase == item.created_in_phase
        assert restored.required_change_type == item.required_change_type
        assert restored.file_locations[0].file_path == item.file_locations[0].file_path
        assert restored.file_locations[0].symbol == item.file_locations[0].symbol
        assert restored.file_locations[0].line_start == item.file_locations[0].line_start
        assert restored.evidence_refs == item.evidence_refs

    def test_from_dict_requires_shape_id(self):
        with pytest.raises(ValueError, match="shape_id is required"):
            WorkItem.from_dict(
                {
                    "work_item_id": "abc",
                    "run_id": "run-001",
                    "slice_id": "slice-1",
                    "title": "T",
                    "description": "",
                    "created_in_phase": "architecture",
                    "required_change_type": "behavior_change",
                    "status": "NEW",
                }
            )

    def test_location_roundtrip(self):
        loc = WorkItemLocation(
            file_path="foo.py",
            symbol="Foo.bar",
            line_start=42,
            line_end=45,
        )
        restored = WorkItemLocation.from_dict(loc.to_dict())
        assert restored.file_path == "foo.py"
        assert restored.symbol == "Foo.bar"
        assert restored.line_start == 42
        assert restored.line_end == 45

    def test_location_legacy_fields_are_mapped(self):
        restored = WorkItemLocation.from_dict(
            {"file": "legacy.py", "symbol": "Legacy.run", "line_hint": "9", "end_line": "12"}
        )
        assert restored.file_path == "legacy.py"
        assert restored.symbol == "Legacy.run"
        assert restored.line_start == 9
        assert restored.line_end == 12


class TestWorkItemStore:
    def test_create_and_get(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item()
        store.create(item)
        fetched = store.get(item.work_item_id)
        assert fetched is not None
        assert fetched.title == item.title

    def test_get_missing_returns_none(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        assert store.get("nonexistent") is None

    def test_upsert_updates_status(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item()
        created = store.create(item)
        store.upsert(replace(created, status="IN_PROGRESS"))
        fetched = store.get(item.work_item_id)
        assert fetched is not None
        assert fetched.status == "IN_PROGRESS"
        assert fetched.updated_at != ""

    def test_upsert_invalid_status(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item()
        created = store.create(item)
        with pytest.raises(ValueError, match="Invalid status"):
            store.upsert(replace(created, status="INVALID"))

    def test_upsert_missing_item_creates(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item(work_item_id="upsert-created-id")
        created = store.upsert(item)
        assert created.work_item_id == "upsert-created-id"
        assert store.get("upsert-created-id") is not None

    def test_list_open_filters(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        open_arch = _make_item(
            title="open-arch",
            shape_id="shape.alpha",
            phase="architecture",
            status="NEW",
            work_item_id="open-arch",
        )
        open_lib = _make_item(
            title="open-lib",
            shape_id="shape.alpha",
            phase="libraries",
            status="IN_PROGRESS",
            work_item_id="open-lib",
        )
        done_arch = _make_item(
            title="done-arch",
            shape_id="shape.beta",
            phase="architecture",
            status="DONE",
            work_item_id="done-arch",
        )
        store.create(open_arch)
        store.create(open_lib)
        store.create(done_arch)

        all_open = {item.work_item_id for item in store.list_open()}
        assert "open-arch" in all_open
        assert "open-lib" in all_open
        assert "done-arch" not in all_open

        arch_open = {item.work_item_id for item in store.list_open(phase="architecture")}
        assert arch_open == {"open-arch"}

        shape_open = {item.work_item_id for item in store.list_open(shape_id="shape.alpha")}
        assert shape_open == {"open-arch", "open-lib"}

    def test_all_items(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.create(_make_item(title="alpha", work_item_id="alpha-id"))
        store.create(_make_item(title="beta", work_item_id="beta-id"))
        assert len(store.all_items()) == 2


class TestPersistence:
    def test_jsonl_written(self, tmp_path):
        coord_dir = tmp_path / "coordination"
        store = WorkItemStore(coord_dir)
        item = _make_item()
        store.create(item)
        jsonl_path = coord_dir / "work_items.jsonl"
        assert jsonl_path.exists()
        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        d = json.loads(lines[0])
        assert d["work_item_id"] == item.work_item_id

    def test_reload_from_disk(self, tmp_path):
        coord_dir = tmp_path / "coordination"
        store = WorkItemStore(coord_dir)
        item = _make_item()
        store.create(item)
        store2 = WorkItemStore(coord_dir)
        fetched = store2.get(item.work_item_id)
        assert fetched is not None
        assert fetched.title == item.title

    def test_upsert_appends_to_jsonl(self, tmp_path):
        coord_dir = tmp_path / "coordination"
        store = WorkItemStore(coord_dir)
        item = _make_item()
        created = store.create(item)
        store.upsert(replace(created, status="DONE"))

        jsonl_path = coord_dir / "work_items.jsonl"
        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        last_entry = json.loads(lines[-1])
        assert last_entry["status"] == "DONE"

    def test_index_rebuild_on_create(self, tmp_path):
        coord_dir = tmp_path / "coordination"
        store = WorkItemStore(coord_dir)
        item = _make_item()
        store.create(item)

        index_path = coord_dir / "work_items_index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert item.work_item_id in index
        assert index[item.work_item_id]["status"] == "NEW"
        assert index[item.work_item_id]["owner_slice_id"] == item.slice_id
        assert index[item.work_item_id]["title"] == item.title
        assert "spec_fingerprint" in index[item.work_item_id]

    def test_reload_last_write_wins(self, tmp_path):
        coord_dir = tmp_path / "coordination"
        store = WorkItemStore(coord_dir)
        item = _make_item(work_item_id="stable-id")
        created = store.create(item)
        store.upsert(replace(created, status="BLOCKED"))

        store2 = WorkItemStore(coord_dir)
        fetched = store2.get("stable-id")
        assert fetched is not None
        assert fetched.status == "BLOCKED"


class TestSearchExact:
    def test_fingerprint_match(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item(title="Validate settlement amounts", description="")
        store.create(item)

        results = store.search(SearchQuery(spec_text="Validate settlement amounts"))
        assert len(results) >= 1
        assert results[0].match_stage == "EXACT"
        assert results[0].match_reason == "fingerprint_match"
        assert results[0].score == 1.0
        assert results[0].work_item.work_item_id == item.work_item_id

    def test_fingerprint_case_insensitive(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.create(_make_item(title="Validate settlement amounts", description=""))

        results = store.search(SearchQuery(spec_text="  VALIDATE  Settlement  Amounts  "))
        assert len(results) >= 1
        assert results[0].match_stage == "EXACT"
        assert results[0].match_reason == "fingerprint_match"

    def test_substring_containment(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.create(
            _make_item(title="Validate settlement amounts and reconcile with ledger", description="")
        )

        results = store.search(SearchQuery(spec_text="validate settlement amounts"))
        exact_results = [r for r in results if r.match_stage == "EXACT"]
        assert len(exact_results) >= 1
        assert any(r.match_reason == "substring_containment" for r in exact_results)


class TestSearchFuzzy:
    def test_fuzzy_token_matching(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item(
            title="Calculate risk exposure for the portfolio",
            symbol="RiskEngine.check_exposure",
            evidence_refs=["risk", "exposure"],
        )
        store.create(item)

        results = store.search(SearchQuery(artifact_key="RiskEngine.check_exposure"))
        assert len(results) >= 1
        assert any(r.work_item.work_item_id == item.work_item_id for r in results)

    def test_keyword_fuzzy_match(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item(
            title="Process incoming trade confirmations and validate",
            symbol="TradeProcessor.validate",
            evidence_refs=["trade", "confirmation"],
        )
        store.create(item)

        results = store.search(SearchQuery(keywords=["trade", "validate"]))
        assert len(results) >= 1
        assert any(r.work_item.work_item_id == item.work_item_id for r in results)


class TestSearchEdgeCases:
    def test_no_match_returns_no_exact(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.create(_make_item(title="Calculate risk exposure for the portfolio"))
        results = store.search(
            SearchQuery(spec_text="completely unrelated database migration query")
        )
        exact = [r for r in results if r.match_stage == "EXACT"]
        assert len(exact) == 0

    def test_empty_query_returns_empty(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.create(_make_item())
        results = store.search(SearchQuery())
        assert results == []

    def test_multiple_matches_sorted_by_score(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.create(
            _make_item(
                title="Validate settlement amounts",
                symbol="Settlement.validate",
                work_item_id="item-a",
            )
        )
        store.create(
            _make_item(
                title="Calculate exposure for settlement risk",
                symbol="Settlement.calculate_exposure",
                work_item_id="item-b",
            )
        )
        store.create(
            _make_item(
                title="Process incoming trade confirmations",
                symbol="TradeProcessor.process",
                work_item_id="item-c",
            )
        )

        results = store.search(SearchQuery(keywords=["settlement", "validate"]))
        assert len(results) >= 1
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score


class TestTokenizer:
    def test_camel_case_split(self):
        tokens = _tokenize("checkExposure")
        assert "check" in tokens
        assert "exposure" in tokens

    def test_snake_case_split(self):
        tokens = _tokenize("check_exposure")
        assert "check" in tokens
        assert "exposure" in tokens

    def test_mixed(self):
        tokens = _tokenize("RiskEngine.check_exposure")
        assert "risk" in tokens
        assert "engine" in tokens
        assert "check" in tokens
        assert "exposure" in tokens

    def test_normalize(self):
        assert _normalize("  Hello   World  ") == "hello world"

    def test_fingerprint_deterministic(self):
        fp1 = _fingerprint("Hello World")
        fp2 = _fingerprint("  hello   world  ")
        assert fp1 == fp2

    def test_fingerprint_different(self):
        fp1 = _fingerprint("hello")
        fp2 = _fingerprint("goodbye")
        assert fp1 != fp2


class TestRerankPlaceholder:
    def test_rerank_returns_semantic_stage(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        items = [
            _make_item(title="alpha task", symbol="Alpha.run", work_item_id="alpha-task"),
            _make_item(title="beta task", symbol="Beta.run", work_item_id="beta-task"),
        ]
        for item in items:
            store.create(item)

        query = SearchQuery(keywords=["alpha"])
        results = store.rerank_with_llm(query, items)
        assert all(r.match_stage == "SEMANTIC" for r in results)
        assert all(r.match_reason == "llm_rerank_placeholder" for r in results)
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score
