from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from spec_manager.schemas.review_actions import (
    ReviewAction,
    ReviewActionsReport,
    allocate_action_id,
    generate_stable_action_ids,
    read_review_actions_json,
    write_review_actions_json,
    write_review_actions_markdown,
)


def _create_sample_action(
    *,
    action_id: str = "ACT-0001",
    action_type: str = "split",
    status: str = "proposed",
) -> dict[str, object]:
    return {
        "action_id": action_id,
        "type": action_type,
        "status": status,
        "source_libs": ["LIB-0001"],
        "target_libs": ["LIB-0002"],
        "elements": ["DTL-LIB-0001-0001"],
        "summary": "Split intake",
        "rationale": "Split rationale [LIB-0001::spec.md::DTL-LIB-0001-0001].",
        "evidence": ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
        "notes": None,
    }


def test_review_action_valid_split() -> None:
    action = ReviewAction.model_validate(_create_sample_action(action_type="split"))
    assert action.type == "split"


def test_review_action_valid_merge() -> None:
    action = ReviewAction.model_validate(_create_sample_action(action_type="merge"))
    assert action.type == "merge"


def test_review_action_valid_move_elements() -> None:
    payload = _create_sample_action(action_type="move_elements")
    payload["elements"] = ["DTL-LIB-0001-0001", "CON-LIB-0001-0002"]
    action = ReviewAction.model_validate(payload)
    assert action.type == "move_elements"


def test_review_action_invalid_action_id_format() -> None:
    payload = _create_sample_action(action_id="ACT-1")
    with pytest.raises(ValidationError):
        ReviewAction.model_validate(payload)


def test_review_action_invalid_lib_id_format() -> None:
    payload = _create_sample_action()
    payload["source_libs"] = ["LIB-1"]
    with pytest.raises(ValidationError):
        ReviewAction.model_validate(payload)


def test_review_action_invalid_element_id_format() -> None:
    payload = _create_sample_action()
    payload["elements"] = ["DTL-0001"]
    with pytest.raises(ValidationError):
        ReviewAction.model_validate(payload)


def test_review_action_invalid_evidence_pointer() -> None:
    payload = _create_sample_action()
    payload["evidence"] = ["[INVALID]"]
    with pytest.raises(ValidationError):
        ReviewAction.model_validate(payload)


def test_review_action_valid_multi_hop_pointer() -> None:
    payload = _create_sample_action()
    payload["evidence"] = ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"]
    action = ReviewAction.model_validate(payload)
    assert action.evidence[0].startswith("[LIB-0001")


def test_review_action_valid_source_pointer() -> None:
    payload = _create_sample_action()
    payload["evidence"] = ["[spec_snapshot/alpha.md::SEC-F0001-0001]"]
    action = ReviewAction.model_validate(payload)
    assert action.evidence[0].startswith("[spec_snapshot/")


def test_review_action_invalid_action_type() -> None:
    payload = _create_sample_action(action_type="invalid")
    with pytest.raises(ValidationError):
        ReviewAction.model_validate(payload)


def test_review_actions_report_valid() -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        thresholds={"overlap_similarity": 0.35, "min_shared_elements": 5},
        actions=[action],
    )
    assert report.run_id == "run_001"


def test_review_actions_report_invalid_timestamp() -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    with pytest.raises(ValidationError):
        ReviewActionsReport(
            run_id="run_001",
            generated_at="2024-01-01",
            actions=[action],
        )


def test_review_actions_report_empty_actions() -> None:
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[],
    )
    assert report.actions == []


def test_review_actions_report_default_thresholds() -> None:
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[],
    )
    assert report.thresholds == {"overlap_similarity": 0.35, "min_shared_elements": 5}


def test_allocate_action_id_first() -> None:
    assert allocate_action_id() == "ACT-0001"


def test_allocate_action_id_incremental() -> None:
    actions = [
        ReviewAction.model_validate(_create_sample_action(action_id="ACT-0001")),
        ReviewAction.model_validate(_create_sample_action(action_id="ACT-0003")),
    ]
    assert allocate_action_id(existing_actions=actions) == "ACT-0004"


def test_allocate_action_id_max_limit() -> None:
    actions = [ReviewAction.model_validate(_create_sample_action(action_id="ACT-9999"))]
    with pytest.raises(ValueError):
        allocate_action_id(existing_actions=actions)


def test_allocate_action_id_from_existing_actions() -> None:
    actions = [ReviewAction.model_validate(_create_sample_action(action_id="ACT-0002"))]
    assert allocate_action_id(existing_actions=actions) == "ACT-0003"


def test_allocate_action_id_from_existing_ids() -> None:
    assert allocate_action_id(existing_ids={"ACT-0001", "ACT-0005"}) == "ACT-0006"


def test_allocate_action_id_both_params_raises() -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    with pytest.raises(ValueError):
        allocate_action_id(existing_actions=[action], existing_ids={"ACT-0001"})


def test_generate_stable_action_ids_deterministic() -> None:
    actions = [
        _create_sample_action(action_id="ACT-0002", action_type="merge"),
        _create_sample_action(action_id="ACT-0001", action_type="split"),
    ]
    first = generate_stable_action_ids(actions)
    second = generate_stable_action_ids(actions)
    assert first == second


def test_generate_stable_action_ids_sorts_by_type() -> None:
    actions = [
        _create_sample_action(action_type="split"),
        _create_sample_action(action_type="move_elements"),
        _create_sample_action(action_type="merge"),
    ]
    assigned = generate_stable_action_ids(actions)
    assert [action["type"] for action in assigned] == ["merge", "move_elements", "split"]


def test_generate_stable_action_ids_sorts_by_libs() -> None:
    actions = [
        {
            **_create_sample_action(action_type="merge"),
            "source_libs": ["LIB-0002"],
            "target_libs": ["LIB-0003"],
        },
        {
            **_create_sample_action(action_type="merge"),
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0003"],
        },
    ]
    assigned = generate_stable_action_ids(actions)
    assert assigned[0]["source_libs"] == ["LIB-0001"]
    assert assigned[1]["source_libs"] == ["LIB-0002"]


def test_generate_stable_action_ids_sorts_by_elements() -> None:
    actions = [
        {
            **_create_sample_action(action_type="merge"),
            "elements": ["DTL-LIB-0001-0002"],
        },
        {
            **_create_sample_action(action_type="merge"),
            "elements": ["DTL-LIB-0001-0001"],
        },
    ]
    assigned = generate_stable_action_ids(actions)
    assert assigned[0]["elements"] == ["DTL-LIB-0001-0001"]
    assert assigned[1]["elements"] == ["DTL-LIB-0001-0002"]


def test_generate_stable_action_ids_sequential() -> None:
    actions = [
        _create_sample_action(action_type="merge"),
        _create_sample_action(action_type="split"),
        _create_sample_action(action_type="move_elements"),
    ]
    assigned = generate_stable_action_ids(actions)
    assert [action["action_id"] for action in assigned] == [
        "ACT-0001",
        "ACT-0002",
        "ACT-0003",
    ]


def test_write_review_actions_json(fs) -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[action],
    )
    output_path = Path("/work/review_actions.json")
    write_review_actions_json(report, output_path)

    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run_001"


def test_read_review_actions_json(fs) -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[action],
    )
    output_path = Path("/work/review_actions.json")
    write_review_actions_json(report, output_path)

    loaded = read_review_actions_json(output_path)
    assert loaded.run_id == report.run_id
    assert loaded.actions[0].action_id == "ACT-0001"


def test_review_actions_json_schema_compliance(fs) -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[action],
    )
    output_path = Path("/work/review_actions.json")
    write_review_actions_json(report, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {"run_id", "generated_at", "thresholds", "actions"}
    assert isinstance(payload["actions"], list)
    assert payload["actions"][0]["action_id"] == "ACT-0001"


def test_write_review_actions_markdown(fs) -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[action],
    )
    output_path = Path("/work/review_actions.md")
    write_review_actions_markdown(report, output_path)

    assert output_path.exists()


def test_review_actions_markdown_includes_metadata(fs) -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[action],
    )
    output_path = Path("/work/review_actions.md")
    write_review_actions_markdown(report, output_path)

    content = output_path.read_text(encoding="utf-8")
    assert "Run ID" in content
    assert "Generated At" in content
    assert "Thresholds" in content


def test_review_actions_markdown_includes_summary_table(fs) -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[action],
    )
    output_path = Path("/work/review_actions.md")
    write_review_actions_markdown(report, output_path)

    content = output_path.read_text(encoding="utf-8")
    assert "Actions Summary" in content
    assert "| Action ID | Type | Status |" in content


def test_review_actions_markdown_includes_action_details(fs) -> None:
    action = ReviewAction.model_validate(_create_sample_action())
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[action],
    )
    output_path = Path("/work/review_actions.md")
    write_review_actions_markdown(report, output_path)

    content = output_path.read_text(encoding="utf-8")
    assert "## Action Details" in content
    assert "#### Rationale" in content
    assert "#### Evidence" in content
    assert "#### Notes" in content


def test_review_actions_markdown_escapes_table_pipes(fs) -> None:
    payload = _create_sample_action()
    payload["summary"] = "Summary with | pipe"
    action = ReviewAction.model_validate(payload)
    report = ReviewActionsReport(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        actions=[action],
    )
    output_path = Path("/work/review_actions.md")
    write_review_actions_markdown(report, output_path)

    content = output_path.read_text(encoding="utf-8")
    assert "Summary with \\| pipe" in content
