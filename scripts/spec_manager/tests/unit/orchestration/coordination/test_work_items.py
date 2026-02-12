"""Tests for coordination/work_items.py."""

from __future__ import annotations

import json

import pytest

from spec_manager.orchestration.coordination.work_items import (
    SearchQuery,
    SearchResult,
    WorkItem,
    WorkItemLocation,
    WorkItemStore,
    _fingerprint,
    _normalize,
    _tokenize,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    spec_text: str = "Calculate risk exposure for the portfolio",
    owner: str = "slice-treasury",
    status: str = "NEW",
    symbol: str = "RiskEngine.check_exposure",
    file: str = "risk_engine.py",
    tags: list[str] | None = None,
) -> WorkItem:
    return WorkItem(
        work_item_id=_fingerprint(spec_text),
        spec_text=spec_text,
        owner_slice_id=owner,
        status=status,
        location=WorkItemLocation(file=file, symbol=symbol, line_hint=10),
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# WorkItem serialization
# ---------------------------------------------------------------------------


class TestWorkItemSerialization:
    def test_to_dict_roundtrip(self):
        item = _make_item()
        d = item.to_dict()
        restored = WorkItem.from_dict(d)
        assert restored.work_item_id == item.work_item_id
        assert restored.spec_text == item.spec_text
        assert restored.owner_slice_id == item.owner_slice_id
        assert restored.status == item.status
        assert restored.location.file == item.location.file
        assert restored.location.symbol == item.location.symbol
        assert restored.location.line_hint == item.location.line_hint
        assert restored.tags == item.tags

    def test_from_dict_defaults(self):
        d = {"work_item_id": "abc", "spec_text": "something", "owner_slice_id": "s1"}
        item = WorkItem.from_dict(d)
        assert item.status == "NEW"
        assert item.location.file == ""
        assert item.tags == []

    def test_location_roundtrip(self):
        loc = WorkItemLocation(file="foo.py", symbol="Foo.bar", line_hint=42)
        d = loc.to_dict()
        restored = WorkItemLocation.from_dict(d)
        assert restored.file == "foo.py"
        assert restored.symbol == "Foo.bar"
        assert restored.line_hint == 42


# ---------------------------------------------------------------------------
# WorkItemStore CRUD
# ---------------------------------------------------------------------------


class TestWorkItemStore:
    def test_add_and_get(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item()
        store.add(item)
        fetched = store.get(item.work_item_id)
        assert fetched is not None
        assert fetched.spec_text == item.spec_text

    def test_get_missing_returns_none(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        assert store.get("nonexistent") is None

    def test_update_status(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item()
        store.add(item)
        store.update_status(item.work_item_id, "IN_PROGRESS")
        fetched = store.get(item.work_item_id)
        assert fetched is not None
        assert fetched.status == "IN_PROGRESS"
        assert fetched.updated_at != ""

    def test_update_status_invalid(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item()
        store.add(item)
        with pytest.raises(ValueError, match="Invalid status"):
            store.update_status(item.work_item_id, "INVALID")

    def test_update_status_missing_item(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        with pytest.raises(KeyError, match="Work item not found"):
            store.update_status("no-such-id", "DONE")

    def test_get_by_slice(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item_a = _make_item(spec_text="task A", owner="slice-1")
        item_b = _make_item(spec_text="task B", owner="slice-2")
        item_c = _make_item(spec_text="task C", owner="slice-1")
        store.add(item_a)
        store.add(item_b)
        store.add(item_c)
        results = store.get_by_slice("slice-1")
        assert len(results) == 2
        ids = {r.work_item_id for r in results}
        assert item_a.work_item_id in ids
        assert item_c.work_item_id in ids

    def test_get_by_status(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item_a = _make_item(spec_text="task A", status="NEW")
        item_b = _make_item(spec_text="task B", status="DONE")
        store.add(item_a)
        store.add(item_b)
        new_items = store.get_by_status("NEW")
        assert len(new_items) == 1
        assert new_items[0].work_item_id == item_a.work_item_id

    def test_all_items(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.add(_make_item(spec_text="alpha"))
        store.add(_make_item(spec_text="beta"))
        assert len(store.all_items()) == 2


# ---------------------------------------------------------------------------
# JSONL persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_jsonl_written(self, tmp_path):
        coord_dir = tmp_path / "coordination"
        store = WorkItemStore(coord_dir)
        item = _make_item()
        store.add(item)
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
        store.add(item)

        # Create a new store pointing at the same directory
        store2 = WorkItemStore(coord_dir)
        fetched = store2.get(item.work_item_id)
        assert fetched is not None
        assert fetched.spec_text == item.spec_text

    def test_update_appends_to_jsonl(self, tmp_path):
        coord_dir = tmp_path / "coordination"
        store = WorkItemStore(coord_dir)
        item = _make_item()
        store.add(item)
        store.update_status(item.work_item_id, "DONE")

        jsonl_path = coord_dir / "work_items.jsonl"
        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        # Should have 2 lines: initial add + status update
        assert len(lines) == 2
        last_entry = json.loads(lines[-1])
        assert last_entry["status"] == "DONE"

    def test_index_rebuild_on_add(self, tmp_path):
        coord_dir = tmp_path / "coordination"
        store = WorkItemStore(coord_dir)
        item = _make_item()
        store.add(item)

        index_path = coord_dir / "work_items_index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert item.work_item_id in index
        assert index[item.work_item_id]["status"] == "NEW"
        assert index[item.work_item_id]["owner"] == item.owner_slice_id
        assert "spec_text_preview" in index[item.work_item_id]

    def test_reload_last_write_wins(self, tmp_path):
        """JSONL may contain duplicate IDs; last write wins on reload."""
        coord_dir = tmp_path / "coordination"
        store = WorkItemStore(coord_dir)
        item = _make_item()
        store.add(item)
        store.update_status(item.work_item_id, "BLOCKED")

        store2 = WorkItemStore(coord_dir)
        fetched = store2.get(item.work_item_id)
        assert fetched is not None
        assert fetched.status == "BLOCKED"


# ---------------------------------------------------------------------------
# Search Stage A: exact
# ---------------------------------------------------------------------------


class TestSearchExact:
    def test_fingerprint_match(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item(spec_text="Validate settlement amounts")
        store.add(item)

        results = store.search(SearchQuery(spec_text="Validate settlement amounts"))
        assert len(results) >= 1
        assert results[0].match_stage == "EXACT"
        assert results[0].match_reason == "fingerprint_match"
        assert results[0].score == 1.0
        assert results[0].work_item.work_item_id == item.work_item_id

    def test_fingerprint_case_insensitive(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item(spec_text="Validate settlement amounts")
        store.add(item)

        results = store.search(
            SearchQuery(spec_text="  VALIDATE  Settlement  Amounts  ")
        )
        assert len(results) >= 1
        assert results[0].match_stage == "EXACT"
        assert results[0].match_reason == "fingerprint_match"

    def test_substring_containment(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item(
            spec_text="Validate settlement amounts and reconcile with ledger"
        )
        store.add(item)

        # Query is a substring of the stored spec_text
        results = store.search(
            SearchQuery(spec_text="validate settlement amounts")
        )
        # Should get either fingerprint or substring match
        assert len(results) >= 1
        exact_results = [r for r in results if r.match_stage == "EXACT"]
        assert len(exact_results) >= 1


# ---------------------------------------------------------------------------
# Search Stage B: fuzzy
# ---------------------------------------------------------------------------


class TestSearchFuzzy:
    def test_fuzzy_token_matching(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item(
            spec_text="Calculate risk exposure for the portfolio",
            symbol="RiskEngine.check_exposure",
            tags=["risk", "exposure"],
        )
        store.add(item)

        results = store.search(
            SearchQuery(artifact_key="RiskEngine.check_exposure")
        )
        assert len(results) >= 1
        # Should match via fuzzy tokens + identifier boost
        assert any(r.work_item.work_item_id == item.work_item_id for r in results)

    def test_keyword_fuzzy_match(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        item = _make_item(
            spec_text="Process incoming trade confirmations and validate",
            symbol="TradeProcessor.validate",
            tags=["trade", "confirmation"],
        )
        store.add(item)

        results = store.search(SearchQuery(keywords=["trade", "validate"]))
        assert len(results) >= 1
        assert any(r.work_item.work_item_id == item.work_item_id for r in results)


# ---------------------------------------------------------------------------
# Search: edge cases
# ---------------------------------------------------------------------------


class TestSearchEdgeCases:
    def test_no_match_returns_empty(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.add(
            _make_item(spec_text="Calculate risk exposure for the portfolio")
        )
        results = store.search(
            SearchQuery(spec_text="completely unrelated database migration query")
        )
        # Might have some low-scoring fuzzy matches that don't meet threshold
        exact = [r for r in results if r.match_stage == "EXACT"]
        assert len(exact) == 0

    def test_empty_query_returns_empty(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.add(_make_item())
        results = store.search(SearchQuery())
        assert results == []

    def test_multiple_matches_sorted_by_score(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        store.add(
            _make_item(
                spec_text="Validate settlement amounts",
                symbol="Settlement.validate",
            )
        )
        store.add(
            _make_item(
                spec_text="Calculate exposure for settlement risk",
                symbol="Settlement.calculate_exposure",
            )
        )
        store.add(
            _make_item(
                spec_text="Process incoming trade confirmations",
                symbol="TradeProcessor.process",
            )
        )

        results = store.search(
            SearchQuery(keywords=["settlement", "validate"])
        )
        assert len(results) >= 1
        # Results should be sorted by score descending
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score


# ---------------------------------------------------------------------------
# Tokenizer and helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Rerank placeholder
# ---------------------------------------------------------------------------


class TestRerankPlaceholder:
    def test_rerank_returns_semantic_stage(self, tmp_path):
        store = WorkItemStore(tmp_path / "coordination")
        items = [
            _make_item(spec_text="alpha task", symbol="Alpha.run"),
            _make_item(spec_text="beta task", symbol="Beta.run"),
        ]
        for it in items:
            store.add(it)

        query = SearchQuery(keywords=["alpha"])
        results = store.rerank_with_llm(query, items)
        assert all(r.match_stage == "SEMANTIC" for r in results)
        assert all(r.match_reason == "llm_rerank_placeholder" for r in results)
        # Should be sorted by score
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score
