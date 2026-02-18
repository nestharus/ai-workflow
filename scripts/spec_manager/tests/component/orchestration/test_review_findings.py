"""Component tests for orchestration.review.findings_to_tickets module."""

from __future__ import annotations

from spec_manager.orchestration.review.findings_to_tickets import (
    ConversionResult,
    ReviewFinding,
    convert_findings,
)


class TestReviewFindingFromDict:
    def test_from_dict_populates_fields(self) -> None:
        data = {
            "category": "LOGIC",
            "description": "Wrong calculation",
            "files": ["calc.py"],
            "pins": ["PIN-001"],
            "evidence_paths": ["/evidence/1.json"],
            "severity": "BLOCKER",
        }
        f = ReviewFinding.from_dict(data)
        assert f.category == "LOGIC"
        assert f.description == "Wrong calculation"
        assert f.files == ["calc.py"]
        assert f.pins == ["PIN-001"]
        assert f.evidence_paths == ["/evidence/1.json"]
        assert f.severity == "BLOCKER"

    def test_from_dict_defaults(self) -> None:
        f = ReviewFinding.from_dict({})
        assert f.category == ""
        assert f.description == ""
        assert f.files == []
        assert f.severity == "MAJOR"


class TestConversionResultDefaults:
    def test_defaults(self) -> None:
        r = ConversionResult()
        assert r.tickets == []
        assert r.under_spec_events == []
        assert r.skipped == 0


class TestConvertFindingsLogic:
    def test_logic_finding_produces_ticket(self) -> None:
        result = convert_findings(
            findings=[
                {
                    "category": "LOGIC",
                    "description": "Wrong calculation",
                    "files": ["calc.py"],
                }
            ],
            active_layer="L1",
        )
        assert len(result.tickets) == 1
        assert result.tickets[0].diagnosis == "Wrong calculation"

    def test_logic_finding_routes_to_l1(self) -> None:
        result = convert_findings(
            findings=[
                {
                    "category": "LOGIC",
                    "description": "Bug",
                    "files": ["x.py"],
                }
            ],
            active_layer="L1",
        )
        assert result.tickets[0].target_layer == "L1"


class TestConvertFindingsUnderSpec:
    def test_under_spec_produces_event(self) -> None:
        result = convert_findings(
            findings=[
                {
                    "category": "UNDER_SPEC",
                    "description": "Unclear behavior",
                    "files": ["x.py"],
                }
            ],
        )
        assert len(result.under_spec_events) == 1
        assert result.tickets == []
        assert result.under_spec_events[0]["kind"] == "REVIEW_UNDER_SPEC"
        assert result.under_spec_events[0]["question"] == "Unclear behavior"

    def test_under_spec_with_multiple_files(self) -> None:
        result = convert_findings(
            findings=[
                {
                    "category": "UNDER_SPEC",
                    "description": "Ambiguous",
                    "files": ["a.py", "b.py"],
                }
            ],
        )
        assert "a.py" in result.under_spec_events[0]["needed_for"]
        assert "b.py" in result.under_spec_events[0]["needed_for"]


class TestConvertFindingsSkips:
    def test_skips_findings_with_no_category(self) -> None:
        result = convert_findings(
            findings=[
                {"description": "No category here", "files": ["y.py"]},
            ],
        )
        assert result.tickets == []
        assert result.under_spec_events == []
        assert result.skipped == 1

    def test_mixed_findings(self) -> None:
        result = convert_findings(
            findings=[
                {"category": "LOGIC", "description": "Bug", "files": ["a.py"]},
                {"category": "UNDER_SPEC", "description": "Unclear", "files": ["b.py"]},
                {"description": "No category"},
            ],
            active_layer="L1",
        )
        assert len(result.tickets) == 1
        assert len(result.under_spec_events) == 1
        assert result.skipped == 1
