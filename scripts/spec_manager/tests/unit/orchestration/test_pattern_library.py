"""Comprehensive unit tests for the pattern library module.

Tests cover:
- Pattern dataclass: to_dict/from_dict roundtrip, unknown key handling
- StrategyPack dataclass: to_dict/from_dict roundtrip with nested patterns
- StrategyCandidate dataclass: to_dict serialization
- PatternLibrary: default loading, dimension queries, prompt generation,
  candidate recording/merging, save/load persistence, disabled pattern
  filtering, and strategy pack language/framework filtering
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from spec_manager.orchestration.pattern_library import (
    Pattern,
    PatternLibrary,
    StrategyCandidate,
    StrategyPack,
)

# ===================================================================
# 1. Pattern dataclass tests
# ===================================================================


class TestPatternRoundtrip:
    """Verify Pattern.to_dict and Pattern.from_dict are inverses."""

    def test_pattern_to_dict_from_dict_roundtrip(self) -> None:
        """A Pattern serialized and deserialized should equal the original."""
        pattern = Pattern(
            pattern_id="TEST-001",
            principle="Every module must have a single responsibility.",
            signals=[{"language": "python", "cue": "class with >5 methods"}],
            fix_guidance="Split the module into focused sub-modules.",
            dimension="ARCH_BOUNDARY",
            enabled=True,
        )
        serialized = pattern.to_dict()
        restored = Pattern.from_dict(serialized)

        assert restored.pattern_id == pattern.pattern_id
        assert restored.principle == pattern.principle
        assert restored.signals == pattern.signals
        assert restored.fix_guidance == pattern.fix_guidance
        assert restored.dimension == pattern.dimension
        assert restored.enabled == pattern.enabled

    def test_pattern_roundtrip_disabled(self) -> None:
        """Roundtrip preserves enabled=False."""
        pattern = Pattern(
            pattern_id="DIS-001",
            principle="Disabled pattern.",
            dimension="CLARITY",
            enabled=False,
        )
        restored = Pattern.from_dict(pattern.to_dict())
        assert restored.enabled is False

    def test_pattern_roundtrip_empty_signals(self) -> None:
        """Roundtrip preserves empty signals list."""
        pattern = Pattern(pattern_id="EMPTY-001", dimension="TOPOLOGY")
        restored = Pattern.from_dict(pattern.to_dict())
        assert restored.signals == []

    def test_pattern_roundtrip_multiple_signals(self) -> None:
        """Roundtrip preserves multiple signal entries."""
        signals = [
            {"language": "python", "cue": "import *"},
            {"language": "java", "cue": "public static"},
        ]
        pattern = Pattern(pattern_id="MS-001", signals=signals, dimension="DRIFT")
        restored = Pattern.from_dict(pattern.to_dict())
        assert len(restored.signals) == 2
        assert restored.signals[0]["language"] == "python"
        assert restored.signals[1]["language"] == "java"


class TestPatternFromDictUnknownKeys:
    """Verify Pattern.from_dict ignores keys not in the dataclass."""

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """Extra keys in the dict should not raise or appear on the result."""
        data = {
            "pattern_id": "UNK-001",
            "principle": "Some principle.",
            "dimension": "GOVERNANCE",
            "unknown_field": "should be ignored",
            "another_unknown": 42,
        }
        pattern = Pattern.from_dict(data)

        assert pattern.pattern_id == "UNK-001"
        assert pattern.principle == "Some principle."
        assert pattern.dimension == "GOVERNANCE"
        assert not hasattr(pattern, "unknown_field")
        assert not hasattr(pattern, "another_unknown")

    def test_from_dict_with_only_unknown_keys(self) -> None:
        """All unknown keys results in a default Pattern."""
        data = {"bogus_a": 1, "bogus_b": "x"}
        pattern = Pattern.from_dict(data)
        assert pattern.pattern_id == ""
        assert pattern.principle == ""
        assert pattern.dimension == ""
        assert pattern.enabled is True


# ===================================================================
# 2. StrategyPack dataclass tests
# ===================================================================


class TestStrategyPackRoundtrip:
    """Verify StrategyPack.to_dict and StrategyPack.from_dict are inverses."""

    def test_strategy_pack_to_dict_from_dict_roundtrip(self) -> None:
        """A StrategyPack with nested patterns should survive roundtrip."""
        inner_pattern = Pattern(
            pattern_id="SP-001",
            principle="Strategy-specific principle.",
            signals=[{"language": "python", "cue": "def __init__"}],
            fix_guidance="Refactor constructor.",
            dimension="MAINTAINABILITY",
            enabled=True,
        )
        pack = StrategyPack(
            pack_id="python-pack",
            language="python",
            framework="fastapi",
            scope="my-repo",
            patterns=[inner_pattern],
        )

        serialized = pack.to_dict()
        restored = StrategyPack.from_dict(serialized)

        assert restored.pack_id == pack.pack_id
        assert restored.language == pack.language
        assert restored.framework == pack.framework
        assert restored.scope == pack.scope
        assert len(restored.patterns) == 1
        assert restored.patterns[0].pattern_id == "SP-001"
        assert restored.patterns[0].principle == "Strategy-specific principle."
        assert restored.patterns[0].signals == [{"language": "python", "cue": "def __init__"}]

    def test_strategy_pack_empty_patterns(self) -> None:
        """StrategyPack with no patterns survives roundtrip."""
        pack = StrategyPack(pack_id="empty-pack", language="go")
        restored = StrategyPack.from_dict(pack.to_dict())
        assert restored.pack_id == "empty-pack"
        assert restored.language == "go"
        assert restored.patterns == []

    def test_strategy_pack_multiple_patterns(self) -> None:
        """StrategyPack with multiple patterns survives roundtrip."""
        patterns = [Pattern(pattern_id=f"MP-{i}", dimension="TOPOLOGY") for i in range(5)]
        pack = StrategyPack(pack_id="multi", patterns=patterns)
        restored = StrategyPack.from_dict(pack.to_dict())
        assert len(restored.patterns) == 5
        assert [p.pattern_id for p in restored.patterns] == [f"MP-{i}" for i in range(5)]

    def test_strategy_pack_from_dict_ignores_unknown_keys(self) -> None:
        """Extra keys in the dict should not raise."""
        data = {
            "pack_id": "test",
            "language": "rust",
            "unknown_extra": True,
            "patterns": [],
        }
        pack = StrategyPack.from_dict(data)
        assert pack.pack_id == "test"
        assert pack.language == "rust"
        assert not hasattr(pack, "unknown_extra")


# ===================================================================
# 3. StrategyCandidate dataclass tests
# ===================================================================


class TestStrategyCandidateToDict:
    """Verify StrategyCandidate.to_dict serialization."""

    def test_strategy_candidate_to_dict(self) -> None:
        """to_dict should serialize all fields to a plain dict."""
        candidate = StrategyCandidate(
            signal_patterns=["import os", "subprocess.call"],
            approved_remediation="Use pathlib instead of os.path.",
            exceptions=["os.environ is acceptable"],
            occurrences=7,
            source_dimension="CORRECTNESS",
        )
        d = candidate.to_dict()

        assert d["signal_patterns"] == ["import os", "subprocess.call"]
        assert d["approved_remediation"] == "Use pathlib instead of os.path."
        assert d["exceptions"] == ["os.environ is acceptable"]
        assert d["occurrences"] == 7
        assert d["source_dimension"] == "CORRECTNESS"

    def test_strategy_candidate_to_dict_defaults(self) -> None:
        """Default StrategyCandidate serializes with default values."""
        candidate = StrategyCandidate()
        d = candidate.to_dict()

        assert d["signal_patterns"] == []
        assert d["approved_remediation"] == ""
        assert d["exceptions"] == []
        assert d["occurrences"] == 1
        assert d["source_dimension"] == ""


# ===================================================================
# 4. PatternLibrary default loading tests
# ===================================================================


class TestPatternLibraryDefaults:
    """Verify PatternLibrary loads default core patterns correctly."""

    def test_default_loading_total_count(self) -> None:
        """Default library should contain exactly 27 core patterns."""
        lib = PatternLibrary()
        assert len(lib.core_patterns) == 27

    def test_default_loading_dimensions(self) -> None:
        """Default library should cover exactly 10 dimensions."""
        lib = PatternLibrary()
        dimensions = {p.dimension for p in lib.core_patterns}
        expected = {
            "ARCH_BOUNDARY",
            "TOPOLOGY",
            "PIN_COVERAGE",
            "ARCH_DRIFT",
            "GOVERNANCE",
            "CLARITY",
            "CONSISTENCY",
            "MAINTAINABILITY",
            "CORRECTNESS",
            "DRIFT",
        }
        assert dimensions == expected

    def test_default_loading_dimension_counts(self) -> None:
        """Verify per-dimension pattern counts match expected distribution."""
        lib = PatternLibrary()
        counts: dict[str, int] = {}
        for p in lib.core_patterns:
            counts[p.dimension] = counts.get(p.dimension, 0) + 1

        assert counts["ARCH_BOUNDARY"] == 4
        assert counts["TOPOLOGY"] == 4
        assert counts["PIN_COVERAGE"] == 3
        assert counts["ARCH_DRIFT"] == 3
        assert counts["GOVERNANCE"] == 3
        assert counts["CLARITY"] == 2
        assert counts["CONSISTENCY"] == 2
        assert counts["MAINTAINABILITY"] == 2
        assert counts["CORRECTNESS"] == 2
        assert counts["DRIFT"] == 2

    def test_default_loading_no_strategy_packs(self) -> None:
        """Default library has no strategy packs."""
        lib = PatternLibrary()
        assert lib.strategy_packs == []

    def test_default_loading_no_candidates(self) -> None:
        """Default library has no candidates."""
        lib = PatternLibrary()
        assert lib.candidates == []

    def test_default_loading_all_enabled(self) -> None:
        """All default patterns are enabled."""
        lib = PatternLibrary()
        assert all(p.enabled for p in lib.core_patterns)

    def test_default_loading_unique_ids(self) -> None:
        """All default pattern IDs are unique."""
        lib = PatternLibrary()
        ids = [p.pattern_id for p in lib.core_patterns]
        assert len(ids) == len(set(ids))

    def test_default_loading_nonexistent_path(self, tmp_path: Path) -> None:
        """When given a path that does not exist, defaults are loaded."""
        nonexistent = tmp_path / "does_not_exist.json"
        lib = PatternLibrary(library_path=nonexistent)
        assert len(lib.core_patterns) == 27

    def test_default_loading_none_path(self) -> None:
        """When library_path is None, defaults are loaded."""
        lib = PatternLibrary(library_path=None)
        assert len(lib.core_patterns) == 27


# ===================================================================
# 5. PatternLibrary.get_patterns_for_dimension tests
# ===================================================================


class TestGetPatternsForDimension:
    """Verify dimension filtering returns correct patterns."""

    def test_returns_correct_patterns_for_arch_boundary(self) -> None:
        """get_patterns_for_dimension('ARCH_BOUNDARY') returns exactly 4."""
        lib = PatternLibrary()
        patterns = lib.get_patterns_for_dimension("ARCH_BOUNDARY")
        assert len(patterns) == 4
        assert all(p.dimension == "ARCH_BOUNDARY" for p in patterns)

    def test_returns_correct_patterns_for_topology(self) -> None:
        """get_patterns_for_dimension('TOPOLOGY') returns exactly 4."""
        lib = PatternLibrary()
        patterns = lib.get_patterns_for_dimension("TOPOLOGY")
        assert len(patterns) == 4

    def test_returns_correct_patterns_for_clarity(self) -> None:
        """get_patterns_for_dimension('CLARITY') returns exactly 2."""
        lib = PatternLibrary()
        patterns = lib.get_patterns_for_dimension("CLARITY")
        assert len(patterns) == 2

    def test_returns_empty_for_unknown_dimension(self) -> None:
        """Unknown dimension returns empty list."""
        lib = PatternLibrary()
        patterns = lib.get_patterns_for_dimension("NONEXISTENT")
        assert patterns == []

    def test_returns_empty_for_empty_string_dimension(self) -> None:
        """Empty string dimension returns empty list."""
        lib = PatternLibrary()
        patterns = lib.get_patterns_for_dimension("")
        assert patterns == []


# ===================================================================
# 6. Disabled patterns filtering tests
# ===================================================================


class TestDisabledPatternsExclusion:
    """Verify disabled patterns are excluded from get_patterns_for_dimension."""

    def test_disabled_patterns_excluded(self) -> None:
        """Patterns with enabled=False should not appear in dimension queries."""
        lib = PatternLibrary()
        # Directly disable a pattern in the internal list
        target_dim = "ARCH_BOUNDARY"
        original_count = len(lib.get_patterns_for_dimension(target_dim))
        assert original_count == 4

        # Disable the first ARCH_BOUNDARY pattern
        for p in lib._core_patterns:
            if p.dimension == target_dim:
                p.enabled = False
                break

        filtered = lib.get_patterns_for_dimension(target_dim)
        assert len(filtered) == original_count - 1

    def test_all_disabled_returns_empty(self) -> None:
        """When all patterns for a dimension are disabled, returns empty."""
        lib = PatternLibrary()
        for p in lib._core_patterns:
            if p.dimension == "CLARITY":
                p.enabled = False

        patterns = lib.get_patterns_for_dimension("CLARITY")
        assert patterns == []

    def test_disabled_in_strategy_pack_excluded(self) -> None:
        """Disabled patterns in strategy packs are also excluded."""
        lib = PatternLibrary()
        pack = StrategyPack(
            pack_id="test-pack",
            language="python",
            patterns=[
                Pattern(
                    pattern_id="TP-001-PY",
                    dimension="TOPOLOGY",
                    enabled=True,
                ),
                Pattern(
                    pattern_id="TP-002-PY",
                    dimension="TOPOLOGY",
                    enabled=False,
                ),
            ],
        )
        lib._strategy_packs.append(pack)

        patterns = lib.get_patterns_for_dimension("TOPOLOGY", language="python")
        pack_patterns = [p for p in patterns if p.pattern_id.endswith("-PY")]
        assert len(pack_patterns) == 1
        assert pack_patterns[0].pattern_id == "TP-001-PY"


# ===================================================================
# 7. Strategy pack language/framework filtering tests
# ===================================================================


class TestGetPatternsWithStrategyPacks:
    """Verify language/framework filtering from strategy packs."""

    def _lib_with_packs(self) -> PatternLibrary:
        """Create a library with two strategy packs for testing."""
        lib = PatternLibrary()
        python_pack = StrategyPack(
            pack_id="python",
            language="python",
            framework="",
            patterns=[
                Pattern(
                    pattern_id="PY-AB-001",
                    principle="Python-specific boundary rule.",
                    dimension="ARCH_BOUNDARY",
                    enabled=True,
                ),
            ],
        )
        fastapi_pack = StrategyPack(
            pack_id="fastapi",
            language="python",
            framework="fastapi",
            patterns=[
                Pattern(
                    pattern_id="FA-AB-001",
                    principle="FastAPI-specific boundary rule.",
                    dimension="ARCH_BOUNDARY",
                    enabled=True,
                ),
            ],
        )
        lib._strategy_packs = [python_pack, fastapi_pack]
        return lib

    def test_no_language_filter_includes_all_packs(self) -> None:
        """Without language filter, strategy pack patterns are included."""
        lib = self._lib_with_packs()
        patterns = lib.get_patterns_for_dimension("ARCH_BOUNDARY")
        ids = {p.pattern_id for p in patterns}
        # Core (4) + python (1) + fastapi (1) = 6
        assert "PY-AB-001" in ids
        assert "FA-AB-001" in ids
        assert len(patterns) == 6

    def test_language_filter_matches(self) -> None:
        """Language filter includes matching packs."""
        lib = self._lib_with_packs()
        patterns = lib.get_patterns_for_dimension("ARCH_BOUNDARY", language="python")
        ids = {p.pattern_id for p in patterns}
        assert "PY-AB-001" in ids
        assert "FA-AB-001" in ids

    def test_language_filter_excludes_non_matching(self) -> None:
        """Language filter excludes packs with different language."""
        lib = self._lib_with_packs()
        patterns = lib.get_patterns_for_dimension("ARCH_BOUNDARY", language="java")
        ids = {p.pattern_id for p in patterns}
        # Java does not match python packs
        assert "PY-AB-001" not in ids
        assert "FA-AB-001" not in ids
        # Only core patterns
        assert len(patterns) == 4

    def test_framework_filter_matches(self) -> None:
        """Framework filter includes matching packs."""
        lib = self._lib_with_packs()
        patterns = lib.get_patterns_for_dimension(
            "ARCH_BOUNDARY", language="python", framework="fastapi"
        )
        ids = {p.pattern_id for p in patterns}
        assert "PY-AB-001" in ids
        assert "FA-AB-001" in ids

    def test_framework_filter_excludes_non_matching(self) -> None:
        """Framework filter excludes packs with different framework."""
        lib = self._lib_with_packs()
        patterns = lib.get_patterns_for_dimension(
            "ARCH_BOUNDARY", language="python", framework="django"
        )
        ids = {p.pattern_id for p in patterns}
        # python pack has no framework (empty), so it passes framework filter
        assert "PY-AB-001" in ids
        # fastapi pack has framework="fastapi", which != "django"
        assert "FA-AB-001" not in ids
        # Core (4) + python (1) = 5
        assert len(patterns) == 5


# ===================================================================
# 8. PatternLibrary.get_review_prompt_section tests
# ===================================================================


class TestGetReviewPromptSection:
    """Verify prompt section generation."""

    def test_generates_markdown(self) -> None:
        """Should produce markdown with pattern IDs and principles."""
        lib = PatternLibrary()
        section = lib.get_review_prompt_section("GOVERNANCE")

        assert "## Review Patterns" in section
        assert "GV-001" in section
        assert "GV-002" in section
        assert "GV-003" in section
        assert "###" in section

    def test_contains_fix_guidance(self) -> None:
        """Fix guidance should appear in the output."""
        lib = PatternLibrary()
        section = lib.get_review_prompt_section("CLARITY")
        assert "Fix:" in section

    def test_contains_signals_when_present(self) -> None:
        """When patterns have signals, they appear in the output."""
        lib = PatternLibrary()
        # Add a signal to a core pattern
        for p in lib._core_patterns:
            if p.pattern_id == "CL-001":
                p.signals = [{"language": "python", "cue": "single-letter vars"}]
                break

        section = lib.get_review_prompt_section("CLARITY")
        assert "Signals:" in section
        assert "[python]" in section
        assert "single-letter vars" in section

    def test_empty_string_for_unknown_dimension(self) -> None:
        """Unknown dimension returns empty string, not markdown."""
        lib = PatternLibrary()
        section = lib.get_review_prompt_section("TOTALLY_UNKNOWN")
        assert section == ""

    def test_empty_string_for_empty_dimension(self) -> None:
        """Empty dimension string returns empty string."""
        lib = PatternLibrary()
        section = lib.get_review_prompt_section("")
        assert section == ""

    def test_prompt_section_with_language_filter(self) -> None:
        """Language kwarg is forwarded to get_patterns_for_dimension."""
        lib = PatternLibrary()
        pack = StrategyPack(
            pack_id="go",
            language="go",
            patterns=[
                Pattern(
                    pattern_id="GO-GV-001",
                    principle="Go governance rule.",
                    dimension="GOVERNANCE",
                    fix_guidance="Fix go stuff.",
                ),
            ],
        )
        lib._strategy_packs.append(pack)

        section = lib.get_review_prompt_section("GOVERNANCE", language="go")
        assert "GO-GV-001" in section

        # With non-matching language, go pack is excluded
        section_java = lib.get_review_prompt_section("GOVERNANCE", language="java")
        assert "GO-GV-001" not in section_java


# ===================================================================
# 9. PatternLibrary.record_candidate tests
# ===================================================================


class TestRecordCandidate:
    """Verify candidate recording and merging logic."""

    def test_record_candidate_adds_new(self) -> None:
        """A new candidate is appended to the candidates list."""
        lib = PatternLibrary()
        assert lib.candidates == []

        candidate = StrategyCandidate(
            signal_patterns=["pattern_a"],
            approved_remediation="Fix A.",
            source_dimension="CLARITY",
            occurrences=1,
        )
        lib.record_candidate(candidate)

        assert len(lib.candidates) == 1
        assert lib.candidates[0].signal_patterns == ["pattern_a"]
        assert lib.candidates[0].source_dimension == "CLARITY"
        assert lib.candidates[0].occurrences == 1

    def test_record_multiple_non_overlapping_candidates(self) -> None:
        """Non-overlapping candidates are kept separate."""
        lib = PatternLibrary()

        c1 = StrategyCandidate(
            signal_patterns=["alpha"],
            source_dimension="CLARITY",
        )
        c2 = StrategyCandidate(
            signal_patterns=["beta"],
            source_dimension="TOPOLOGY",
        )
        c3 = StrategyCandidate(
            signal_patterns=["gamma"],
            source_dimension="CLARITY",
        )
        lib.record_candidate(c1)
        lib.record_candidate(c2)
        lib.record_candidate(c3)

        assert len(lib.candidates) == 3

    def test_record_candidate_merges_overlapping(self) -> None:
        """Candidates with same dimension and overlapping signal_patterns merge."""
        lib = PatternLibrary()

        c1 = StrategyCandidate(
            signal_patterns=["pattern_a", "pattern_b"],
            approved_remediation="Fix AB.",
            source_dimension="ARCH_BOUNDARY",
            occurrences=2,
        )
        c2 = StrategyCandidate(
            signal_patterns=["pattern_b", "pattern_c"],
            approved_remediation="Fix BC.",
            source_dimension="ARCH_BOUNDARY",
            occurrences=3,
        )
        lib.record_candidate(c1)
        lib.record_candidate(c2)

        assert len(lib.candidates) == 1
        merged = lib.candidates[0]
        assert merged.occurrences == 5  # 2 + 3
        assert set(merged.signal_patterns) == {"pattern_a", "pattern_b", "pattern_c"}

    def test_record_candidate_no_merge_different_dimension(self) -> None:
        """Same signal patterns but different dimension do not merge."""
        lib = PatternLibrary()

        c1 = StrategyCandidate(
            signal_patterns=["shared_pattern"],
            source_dimension="CLARITY",
            occurrences=1,
        )
        c2 = StrategyCandidate(
            signal_patterns=["shared_pattern"],
            source_dimension="TOPOLOGY",
            occurrences=1,
        )
        lib.record_candidate(c1)
        lib.record_candidate(c2)

        assert len(lib.candidates) == 2

    def test_record_candidate_no_merge_disjoint_signals(self) -> None:
        """Same dimension but disjoint signal patterns do not merge."""
        lib = PatternLibrary()

        c1 = StrategyCandidate(
            signal_patterns=["alpha"],
            source_dimension="CLARITY",
            occurrences=1,
        )
        c2 = StrategyCandidate(
            signal_patterns=["beta"],
            source_dimension="CLARITY",
            occurrences=1,
        )
        lib.record_candidate(c1)
        lib.record_candidate(c2)

        assert len(lib.candidates) == 2

    def test_record_candidate_merges_incrementally(self) -> None:
        """Multiple overlapping candidates merge incrementally."""
        lib = PatternLibrary()

        c1 = StrategyCandidate(
            signal_patterns=["x"],
            source_dimension="DRIFT",
            occurrences=1,
        )
        c2 = StrategyCandidate(
            signal_patterns=["x", "y"],
            source_dimension="DRIFT",
            occurrences=2,
        )
        c3 = StrategyCandidate(
            signal_patterns=["y", "z"],
            source_dimension="DRIFT",
            occurrences=3,
        )

        lib.record_candidate(c1)
        lib.record_candidate(c2)  # Merges with c1 (overlap on "x")
        lib.record_candidate(c3)  # Merges with combined (overlap on "y")

        assert len(lib.candidates) == 1
        merged = lib.candidates[0]
        assert merged.occurrences == 6  # 1 + 2 + 3
        assert set(merged.signal_patterns) == {"x", "y", "z"}


# ===================================================================
# 10. PatternLibrary save/load persistence tests
# ===================================================================


class TestPatternLibrarySaveLoad:
    """Verify save and load roundtrip using tmp_path."""

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        """Saving and loading the library preserves all data."""
        lib = PatternLibrary()
        # Add a strategy pack and a candidate to exercise full serialization
        pack = StrategyPack(
            pack_id="test-pack",
            language="python",
            framework="flask",
            patterns=[
                Pattern(
                    pattern_id="FLASK-001",
                    principle="Flask-specific rule.",
                    dimension="ARCH_BOUNDARY",
                ),
            ],
        )
        lib._strategy_packs.append(pack)

        candidate = StrategyCandidate(
            signal_patterns=["flask.Blueprint"],
            approved_remediation="Use app factory pattern.",
            source_dimension="ARCH_BOUNDARY",
            occurrences=3,
        )
        lib.record_candidate(candidate)

        # Save
        save_path = tmp_path / "library.json"
        returned_path = lib.save(save_path)
        assert returned_path == save_path
        assert save_path.exists()

        # Load into new library
        lib2 = PatternLibrary(library_path=save_path)

        assert len(lib2.core_patterns) == 27
        assert len(lib2.strategy_packs) == 1
        assert lib2.strategy_packs[0].pack_id == "test-pack"
        assert lib2.strategy_packs[0].language == "python"
        assert lib2.strategy_packs[0].framework == "flask"
        assert len(lib2.strategy_packs[0].patterns) == 1
        assert lib2.strategy_packs[0].patterns[0].pattern_id == "FLASK-001"

        assert len(lib2.candidates) == 1
        assert lib2.candidates[0].signal_patterns == ["flask.Blueprint"]
        assert lib2.candidates[0].occurrences == 3

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        """save() creates parent directories if they do not exist."""
        lib = PatternLibrary()
        deep_path = tmp_path / "a" / "b" / "c" / "library.json"
        lib.save(deep_path)
        assert deep_path.exists()

    def test_save_uses_library_path_when_no_arg(self, tmp_path: Path) -> None:
        """save() uses the library_path from __init__ when no path given."""
        lib_path = tmp_path / "default_lib.json"
        lib = PatternLibrary(library_path=lib_path)
        returned = lib.save()
        assert returned == lib_path
        assert lib_path.exists()

    def test_save_uses_default_name_when_no_path(self) -> None:
        """save() falls back to 'pattern_library.json' when no path at all."""
        lib = PatternLibrary()
        default = Path("pattern_library.json")
        try:
            returned = lib.save()
            assert returned == default
            assert default.exists()
        finally:
            if default.exists():
                default.unlink()

    def test_load_file_contents_valid_json(self, tmp_path: Path) -> None:
        """The saved file contains valid JSON with expected top-level keys."""
        lib = PatternLibrary()
        save_path = tmp_path / "check.json"
        lib.save(save_path)

        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert "core_patterns" in data
        assert "strategy_packs" in data
        assert "candidates" in data
        assert len(data["core_patterns"]) == 27


class TestPatternLibraryLoadsFromFile:
    """Verify PatternLibrary loads from an existing file on init."""

    def test_loads_from_file_on_init(self, tmp_path: Path) -> None:
        """When a valid JSON file exists at library_path, it is loaded."""
        # Create a minimal library file with 2 patterns
        data = {
            "core_patterns": [
                {
                    "pattern_id": "CUSTOM-001",
                    "principle": "Custom principle one.",
                    "dimension": "CLARITY",
                    "enabled": True,
                    "signals": [],
                    "fix_guidance": "",
                },
                {
                    "pattern_id": "CUSTOM-002",
                    "principle": "Custom principle two.",
                    "dimension": "TOPOLOGY",
                    "enabled": False,
                    "signals": [],
                    "fix_guidance": "Fix it.",
                },
            ],
            "strategy_packs": [],
            "candidates": [
                {
                    "signal_patterns": ["cand_sig"],
                    "approved_remediation": "do something",
                    "exceptions": [],
                    "occurrences": 5,
                    "source_dimension": "DRIFT",
                },
            ],
        }
        lib_path = tmp_path / "custom_lib.json"
        lib_path.write_text(json.dumps(data), encoding="utf-8")

        lib = PatternLibrary(library_path=lib_path)

        # Should have our custom patterns, NOT the 27 defaults
        assert len(lib.core_patterns) == 2
        assert lib.core_patterns[0].pattern_id == "CUSTOM-001"
        assert lib.core_patterns[1].pattern_id == "CUSTOM-002"
        assert lib.core_patterns[1].enabled is False

        # Candidates loaded
        assert len(lib.candidates) == 1
        assert lib.candidates[0].occurrences == 5
        assert lib.candidates[0].source_dimension == "DRIFT"

    def test_loads_strategy_packs_from_file(self, tmp_path: Path) -> None:
        """Strategy packs in the file are loaded with nested patterns."""
        data = {
            "core_patterns": [],
            "strategy_packs": [
                {
                    "pack_id": "file-pack",
                    "language": "typescript",
                    "framework": "react",
                    "scope": "",
                    "patterns": [
                        {
                            "pattern_id": "REACT-001",
                            "principle": "Use hooks correctly.",
                            "dimension": "CORRECTNESS",
                            "enabled": True,
                            "signals": [{"language": "typescript", "cue": "useState"}],
                            "fix_guidance": "Follow rules of hooks.",
                        },
                    ],
                },
            ],
            "candidates": [],
        }
        lib_path = tmp_path / "ts_lib.json"
        lib_path.write_text(json.dumps(data), encoding="utf-8")

        lib = PatternLibrary(library_path=lib_path)

        assert len(lib.core_patterns) == 0
        assert len(lib.strategy_packs) == 1
        assert lib.strategy_packs[0].pack_id == "file-pack"
        assert lib.strategy_packs[0].language == "typescript"
        assert lib.strategy_packs[0].framework == "react"
        assert len(lib.strategy_packs[0].patterns) == 1
        assert lib.strategy_packs[0].patterns[0].pattern_id == "REACT-001"
        assert lib.strategy_packs[0].patterns[0].signals[0]["cue"] == "useState"


# ===================================================================
# 11. Properties return copies tests
# ===================================================================


class TestPropertiesReturnCopies:
    """Verify properties return copies, not internal references."""

    def test_core_patterns_returns_copy(self) -> None:
        """Modifying the returned list should not affect the library."""
        lib = PatternLibrary()
        patterns = lib.core_patterns
        original_len = len(patterns)
        patterns.append(Pattern(pattern_id="EXTRA"))
        assert len(lib.core_patterns) == original_len

    def test_strategy_packs_returns_copy(self) -> None:
        """Modifying the returned list should not affect the library."""
        lib = PatternLibrary()
        packs = lib.strategy_packs
        packs.append(StrategyPack(pack_id="EXTRA"))
        assert len(lib.strategy_packs) == 0

    def test_candidates_returns_copy(self) -> None:
        """Modifying the returned list should not affect the library."""
        lib = PatternLibrary()
        lib.record_candidate(StrategyCandidate(signal_patterns=["x"], source_dimension="DRIFT"))
        candidates = lib.candidates
        candidates.clear()
        assert len(lib.candidates) == 1
