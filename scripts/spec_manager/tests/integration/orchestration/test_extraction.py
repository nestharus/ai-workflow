"""Tests for Phase 0 prose extraction (orchestration/extraction.py)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from spec_manager.orchestration.extraction import (
    _CAMEL_CASE_RE,
    _NORMATIVE_PATTERNS,
    ProseExtractor,
)

# Re-export _match_section_by_name was removed; tests now use _best_candidate_for_section


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TREASURY_SETTLEMENT = textwrap.dedent("""\
    Settlement processing begins the moment an instruction file is
    ingested from the upstream trade-capture platform. Each instruction
    carries a counterparty identifier, a value date, a currency pair,
    and a notional amount. The processor first validates that all
    mandatory fields are present. The netting threshold is $1,000,000:
    any set of instructions between the same counterparty on the same
    value date whose aggregate notional falls below this threshold is
    collapsed into a single net obligation. Instructions at or above the
    threshold are processed gross to maintain full audit granularity.
    Cross-currency instructions require FX conversion before netting can
    proceed. The applicable rate is the ECB reference rate captured at
    T-1; if the rate cache does not contain the required pair the
    processor falls back to a triangulation through EUR.
""")

TREASURY_RISK = textwrap.dedent("""\
    The RiskEngine maintains a real-time exposure model for every active
    counterparty. Each counterparty is assigned a credit limit and the
    current implementation caps that limit at $50M per counterparty.
    Exposure is calculated across a window spanning T+0 to T+2 inclusive.
    When the aggregate exposure for a counterparty reaches 80% of its
    assigned limit the RiskEngine automatically issues a margin call.
    Concentration risk is also monitored: no single counterparty may
    represent more than 25% of the total outstanding exposure across all
    counterparties at any point in time.
""")


def _make_manager(tmp_path: Path, sections: dict[str, str]) -> MagicMock:
    """Create a mock WorkspaceManager with spec_snapshot sections."""
    snapshot_dir = tmp_path / "spec_snapshot"
    sections_dir = snapshot_dir / "sections"
    sections_dir.mkdir(parents=True)

    for label, content in sections.items():
        section_file = sections_dir / f"{label.lower()}.md"
        section_file.write_text(f"# {label}\n\n{content}\n", encoding="utf-8")

    # Create workspace directories
    for subdir in ["manifest", "summaries", "libraries", "architecture", "tasks"]:
        (tmp_path / subdir).mkdir(exist_ok=True)

    manager = MagicMock()
    manager.structure.spec_snapshot_dir = snapshot_dir
    manager.structure.manifest_dir = tmp_path / "manifest"
    manager.structure.summaries_dir = tmp_path / "summaries"
    manager.structure.libraries_dir = tmp_path / "libraries"
    manager.structure.root = tmp_path

    return manager


# ---------------------------------------------------------------------------
# Unit tests — patterns
# ---------------------------------------------------------------------------


class TestCamelCaseRegex:
    """Test CamelCase entity detection."""

    def test_finds_two_segment_names(self):
        matches = _CAMEL_CASE_RE.findall("The RiskEngine is used by SettlementProcessor.")
        assert "RiskEngine" in matches
        assert "SettlementProcessor" in matches

    def test_ignores_single_word(self):
        matches = _CAMEL_CASE_RE.findall("The Risk is high.")
        assert matches == []

    def test_ignores_all_caps(self):
        matches = _CAMEL_CASE_RE.findall("Use ECB and SFTP protocols.")
        assert matches == []

    def test_ignores_lowercase(self):
        matches = _CAMEL_CASE_RE.findall("The processor runs.")
        assert matches == []


class TestNormativePatterns:
    """Test normative indicator detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "The netting threshold is $1,000,000.",
            "Counterparty credit limit capped at $50M.",
            "When exposure reaches 80% of its limit.",
            "Audit writes must complete within 50ms.",
            "Events purged after 90 days.",
            "Reported within 15 minutes of confirmation.",
            "Dead-letter queue after 3 failed attempts.",
            "Notification routing by event type.",
            "Detect duplicate acknowledgements.",
        ],
    )
    def test_normative_sentence_detected(self, text):
        assert any(pat.search(text) for pat in _NORMATIVE_PATTERNS), (
            f"Expected normative match for: {text}"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "This is the backbone of our clearing infrastructure.",
            "At the highest level an inbound settlement instruction passes through a pipeline.",
        ],
    )
    def test_narrative_sentence_not_detected(self, text):
        assert not any(pat.search(text) for pat in _NORMATIVE_PATTERNS), (
            f"Unexpected normative match for: {text}"
        )


# ---------------------------------------------------------------------------
# Unit tests — splitting
# ---------------------------------------------------------------------------


class TestSplitIntoFragments:
    def test_splits_on_period_boundary(self):
        text = (
            "Settlement processing begins here and continues onward. "
            "The netting threshold is one million dollars for all counterparties. "
            "Cross-currency instructions need conversion first."
        )
        fragments = ProseExtractor._split_into_fragments(text)
        assert len(fragments) >= 2

    def test_splits_on_semicolons(self):
        text = (
            "The applicable rate is the ECB reference rate captured at T-1 from the central bank; "
            "if the rate cache does not contain the required pair the processor falls back to EUR."
        )
        fragments = ProseExtractor._split_into_fragments(text)
        assert len(fragments) >= 2

    def test_splits_on_colons(self):
        text = (
            "The netting threshold is $1,000,000: any set of instructions "
            "between the same counterparty on the same value date whose "
            "aggregate notional falls below this threshold is collapsed."
        )
        fragments = ProseExtractor._split_into_fragments(text)
        # Should split into two parts at the colon
        assert any("$1,000,000" in f for f in fragments)
        assert len(fragments) >= 2

    def test_filters_short_fragments(self):
        text = "OK. This is a much longer fragment that should be kept for extraction purposes."
        fragments = ProseExtractor._split_into_fragments(text)
        assert all(len(f) >= 25 for f in fragments)


# ---------------------------------------------------------------------------
# Integration tests — section reading
# ---------------------------------------------------------------------------


class TestReadSections:
    def test_reads_from_sections_subdirectory(self, tmp_path):
        manager = _make_manager(
            tmp_path,
            {"SETTLEMENT_PROCESSING": TREASURY_SETTLEMENT, "RISK_ENGINE": TREASURY_RISK},
        )
        extractor = ProseExtractor(manager)
        sections = extractor._read_sections()
        assert "SETTLEMENT_PROCESSING" in sections
        assert "RISK_ENGINE" in sections

    def test_reads_from_main_markdown(self, tmp_path):
        """Fallback: parse headings from a single markdown file."""
        snapshot_dir = tmp_path / "spec_snapshot"
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "spec.md").write_text(
            "# OVERVIEW\n\nHello world.\n\n# DETAILS\n\nMore info here.\n",
            encoding="utf-8",
        )
        for subdir in ["manifest", "summaries", "libraries"]:
            (tmp_path / subdir).mkdir(exist_ok=True)

        manager = MagicMock()
        manager.structure.spec_snapshot_dir = snapshot_dir
        manager.structure.summaries_dir = tmp_path / "summaries"
        manager.structure.libraries_dir = tmp_path / "libraries"
        manager.structure.root = tmp_path

        extractor = ProseExtractor(manager)
        sections = extractor._read_sections()
        assert "OVERVIEW" in sections
        assert "DETAILS" in sections


# ---------------------------------------------------------------------------
# Integration tests — library identification
# ---------------------------------------------------------------------------


class TestIdentifyLibraries:
    def test_finds_treasury_libraries(self, tmp_path):
        manager = _make_manager(
            tmp_path,
            {
                "OVERVIEW": "The RiskEngine and SettlementProcessor interact daily. "
                "The RiskEngine checks limits. The SettlementProcessor handles netting.",
                "RISK_ENGINE": "The RiskEngine maintains exposure. The RiskEngine caps at $50M.",
                "SETTLEMENT_PROCESSING": "The SettlementProcessor nets instructions. "
                "SettlementProcessor validates fields.",
            },
        )
        extractor = ProseExtractor(manager)
        sections = extractor._read_sections()
        libraries = extractor._identify_libraries(sections)
        names = {lib.name for lib in libraries.values()}
        assert "RiskEngine" in names
        assert "SettlementProcessor" in names

    def test_assigns_correct_primary_sections(self, tmp_path):
        manager = _make_manager(
            tmp_path,
            {
                "OVERVIEW": "The RiskEngine and SettlementProcessor work together.",
                "RISK_ENGINE": "The RiskEngine caps limits at $50M. RiskEngine monitors.",
                "SETTLEMENT_PROCESSING": "SettlementProcessor nets. SettlementProcessor validates.",
            },
        )
        extractor = ProseExtractor(manager)
        sections = extractor._read_sections()
        libraries = extractor._identify_libraries(sections)
        if "RiskEngine" in libraries:
            assert libraries["RiskEngine"].primary_section == "RISK_ENGINE"
        if "SettlementProcessor" in libraries:
            assert libraries["SettlementProcessor"].primary_section == "SETTLEMENT_PROCESSING"

    def test_section_first_matching(self, tmp_path):
        """Libraries named only in OVERVIEW are matched to sections by name."""
        manager = _make_manager(
            tmp_path,
            {
                "OVERVIEW": "The EventPipeline distributes events. "
                "The AuditNotification records audit trails.",
                "EVENT_PIPELINE": "Events are published to topics. Ordering is guaranteed.",
                "NOTIFICATION_AND_AUDIT": "Every write must complete within 50ms.",
            },
        )
        extractor = ProseExtractor(manager)
        sections = extractor._read_sections()
        libraries = extractor._identify_libraries(sections)
        names = {lib.name for lib in libraries.values()}
        assert "EventPipeline" in names
        assert "AuditNotification" in names
        if "EventPipeline" in libraries:
            assert libraries["EventPipeline"].primary_section == "EVENT_PIPELINE"
        if "AuditNotification" in libraries:
            assert libraries["AuditNotification"].primary_section == "NOTIFICATION_AND_AUDIT"

    def test_best_candidate_for_section(self):
        """Static method matches section labels to CamelCase candidates."""
        candidates = {"SettlementProcessor", "RiskEngine", "EventPipeline"}
        assert (
            ProseExtractor._best_candidate_for_section("SETTLEMENT_PROCESSING", candidates)
            == "SettlementProcessor"
        )
        assert ProseExtractor._best_candidate_for_section("RISK_ENGINE", candidates) == "RiskEngine"
        assert (
            ProseExtractor._best_candidate_for_section("EVENT_PIPELINE", candidates)
            == "EventPipeline"
        )


# ---------------------------------------------------------------------------
# Integration tests — full extraction
# ---------------------------------------------------------------------------


class TestFullExtraction:
    def test_treasury_extraction_produces_outputs(self, tmp_path):
        manager = _make_manager(
            tmp_path,
            {
                "OVERVIEW": "The SettlementProcessor and RiskEngine handle netting. "
                "RiskEngine checks limits. SettlementProcessor validates instructions.",
                "SETTLEMENT_PROCESSING": TREASURY_SETTLEMENT,
                "RISK_ENGINE": TREASURY_RISK,
            },
        )
        extractor = ProseExtractor(manager)
        result = extractor.extract()

        assert result["sections_found"] >= 2
        assert result["libraries_found"] >= 1
        assert result["total_requirements"] > 0

        # Summaries were written
        summaries_dir = tmp_path / "summaries"
        assert any(summaries_dir.glob("*.md"))

        # Libraries were written
        libraries_dir = tmp_path / "libraries"
        lib_dirs = [d for d in libraries_dir.iterdir() if d.is_dir()]
        assert len(lib_dirs) >= 1

        # Each library has charter, spec, evidence
        for lib_dir in lib_dirs:
            assert (lib_dir / "charter.md").exists()
            assert (lib_dir / "spec.md").exists()
            assert (lib_dir / "evidence").is_dir()

    def test_requirements_contain_dollar_amounts(self, tmp_path):
        manager = _make_manager(
            tmp_path,
            {
                "OVERVIEW": "SettlementProcessor handles all netting. SettlementProcessor validates.",
                "SETTLEMENT_PROCESSING": TREASURY_SETTLEMENT,
            },
        )
        extractor = ProseExtractor(manager)
        extractor.extract()

        # SettlementProcessor should map to SETTLEMENT_PROCESSING via name matching
        libraries_dir = tmp_path / "libraries"
        sp_dir = libraries_dir / "SettlementProcessor"
        assert sp_dir.exists(), (
            f"SettlementProcessor library not found. Libraries: "
            f"{[d.name for d in libraries_dir.iterdir() if d.is_dir()]}"
        )
        spec_text = (sp_dir / "spec.md").read_text(encoding="utf-8")
        assert "$1,000,000" in spec_text

    def test_charter_has_intent_and_responsibilities(self, tmp_path):
        manager = _make_manager(
            tmp_path,
            {
                "OVERVIEW": "RiskEngine monitors exposure. RiskEngine caps limits.",
                "RISK_ENGINE": TREASURY_RISK,
            },
        )
        extractor = ProseExtractor(manager)
        extractor.extract()

        libraries_dir = tmp_path / "libraries"
        re_dir = libraries_dir / "RiskEngine"
        if re_dir.exists():
            charter = (re_dir / "charter.md").read_text(encoding="utf-8")
            assert "## Intent" in charter
            assert "## Responsibilities" in charter

    def test_empty_input_returns_error(self, tmp_path):
        snapshot_dir = tmp_path / "spec_snapshot"
        snapshot_dir.mkdir(parents=True)
        for subdir in ["manifest", "summaries", "libraries"]:
            (tmp_path / subdir).mkdir(exist_ok=True)

        manager = MagicMock()
        manager.structure.spec_snapshot_dir = snapshot_dir
        manager.structure.summaries_dir = tmp_path / "summaries"
        manager.structure.libraries_dir = tmp_path / "libraries"
        manager.structure.root = tmp_path

        extractor = ProseExtractor(manager)
        result = extractor.extract()
        assert result["sections_found"] == 0
