"""Component tests for orchestration.review.findings_to_tickets module."""

from __future__ import annotations

from typing import Any

import spec_manager.orchestration.review.findings_to_tickets as findings_to_tickets_module
from spec_manager.orchestration.coordination.work_items import WorkItem, WorkItemLocation
from spec_manager.orchestration.demotion.router import RoutingBatch
from spec_manager.orchestration.review.findings_to_tickets import (
    ConversionResult,
    ReviewFinding,
    convert_findings,
)
from spec_manager.routing.shapes import Shape, ShapeId, ShapePackIndex


def _shape_index_for_files(file_to_shape: dict[str, str]) -> ShapePackIndex:
    shapes: dict[ShapeId, Shape] = {}
    ownership_prefixes: list[tuple[str, ShapeId]] = []

    for file_path, shape_name in file_to_shape.items():
        shape_id = ShapeId(shape_name)
        if shape_id not in shapes:
            shapes[shape_id] = Shape(
                shape_id=shape_id,
                classification="library",
                package=shape_name,
                files=[],
                role="component",
                status="ACTIVE",
            )
        shapes[shape_id].files.append(file_path)
        ownership_prefixes.append((file_path.lower(), shape_id))

    return ShapePackIndex(
        system_shapes_dir="",
        run_shapes_dir="",
        shapes=shapes,
        ownership_prefixes=ownership_prefixes,
    )


def _make_work_item(shape_id: str, slice_id: str) -> WorkItem:
    return WorkItem(
        work_item_id=f"wi-{shape_id}",
        run_id="run-1",
        slice_id=slice_id,
        title=f"title-{shape_id}",
        description="desc",
        shape_id=ShapeId(shape_id),
        created_in_phase="libraries",
        required_change_type="behavior_change",
        status="NEW",
        file_locations=[WorkItemLocation(file_path=f"{shape_id}.py")],
        evidence_refs=[],
        contract_ids=[],
        verifier_ids=[],
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        metadata={},
    )


def _install_router_stub(monkeypatch: Any) -> None:
    def _fake_route_review_findings(
        self: Any,
        *,
        slice_id: str,
        findings: list[dict[str, Any]],
        shape_index: ShapePackIndex,
    ) -> RoutingBatch:
        del self, shape_index
        created = []
        for finding in findings:
            for shape_id in finding.get("resolved_shape_ids", []):
                created.append(_make_work_item(str(shape_id), slice_id))
        return RoutingBatch(
            created_work_items=created,
            blocked_findings=[],
            diagnostics=["ROUTER_STUB_USED"],
        )

    monkeypatch.setattr(
        findings_to_tickets_module.DemotionRouter,
        "route_review_findings",
        _fake_route_review_findings,
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
        assert r.produced_work_items == []
        assert r.blocked_findings == []
        assert r.diagnostics == []


class TestConvertFindingsLogic:
    def test_logic_finding_produces_work_item(self, monkeypatch: Any) -> None:
        _install_router_stub(monkeypatch)
        shape_index = _shape_index_for_files({"calc.py": "shape-calc"})
        result = convert_findings(
            findings=[
                {
                    "category": "LOGIC",
                    "description": "Wrong calculation",
                    "files": ["calc.py"],
                }
            ],
            shape_index=shape_index,
            run_id="run-1",
            slice_id="slice-1",
            active_phase="libraries",
        )
        assert len(result.produced_work_items) == 1
        work_item = result.produced_work_items[0]
        assert str(work_item.shape_id) == "shape-calc"
        assert work_item.created_in_phase == "libraries"
        assert work_item.slice_id == "slice-1"
        assert work_item.run_id == "run-1"
        assert work_item.metadata["finding_index"] == 0
        assert result.blocked_findings == []
        assert "ROUTER_STUB_USED" in result.diagnostics

    def test_multiple_file_finding_fans_out_per_shape(self, monkeypatch: Any) -> None:
        _install_router_stub(monkeypatch)
        shape_index = _shape_index_for_files(
            {
                "a.py": "shape-a",
                "b.py": "shape-b",
            }
        )
        result = convert_findings(
            findings=[
                {
                    "category": "LOGIC",
                    "description": "Bug",
                    "files": ["a.py", "b.py"],
                }
            ],
            shape_index=shape_index,
            active_phase="libraries",
        )
        assert len(result.produced_work_items) == 2
        assert sorted(str(item.shape_id) for item in result.produced_work_items) == [
            "shape-a",
            "shape-b",
        ]
        assert result.blocked_findings == []


class TestConvertFindingsUnderSpec:
    def test_under_spec_finding_produces_work_item(self, monkeypatch: Any) -> None:
        _install_router_stub(monkeypatch)
        shape_index = _shape_index_for_files({"x.py": "shape-x"})
        result = convert_findings(
            findings=[
                {
                    "category": "UNDER_SPEC",
                    "description": "Unclear behavior",
                    "files": ["x.py"],
                }
            ],
            shape_index=shape_index,
        )
        assert len(result.produced_work_items) == 1
        assert result.blocked_findings == []

    def test_unresolved_file_is_blocked(self) -> None:
        shape_index = _shape_index_for_files({"a.py": "shape-a"})
        result = convert_findings(
            findings=[
                {
                    "category": "UNDER_SPEC",
                    "description": "Ambiguous",
                    "files": ["b.py"],
                }
            ],
            shape_index=shape_index,
        )
        assert result.produced_work_items == []
        assert len(result.blocked_findings) == 1
        assert result.blocked_findings[0]["failing_files"] == ["b.py"]
        assert result.blocked_findings[0]["reason"] == (
            "ownership could not be resolved for one or more finding files"
        )


class TestConvertFindingsSkips:
    def test_blocks_findings_with_no_category(self) -> None:
        shape_index = _shape_index_for_files({"y.py": "shape-y"})
        result = convert_findings(
            findings=[
                {"description": "No category here", "files": ["y.py"]},
            ],
            shape_index=shape_index,
        )
        assert result.produced_work_items == []
        assert len(result.blocked_findings) == 1
        assert result.blocked_findings[0]["reason"] == "invalid_finding"
        assert "category is required" in result.blocked_findings[0]["errors"]

    def test_blocks_non_list_findings_payload(self) -> None:
        shape_index = _shape_index_for_files({"a.py": "shape-a"})
        invalid_payload: Any = {"category": "LOGIC"}
        result = convert_findings(
            findings=invalid_payload,
            shape_index=shape_index,
        )
        assert result.produced_work_items == []
        assert len(result.blocked_findings) == 1
        assert result.blocked_findings[0]["reason"] == "findings must be a list"
        assert "FINDINGS_BATCH_INVALID:findings must be a list" in result.diagnostics
