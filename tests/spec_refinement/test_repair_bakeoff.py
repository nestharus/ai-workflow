from __future__ import annotations

from pathlib import Path

from scripts.spec_refinement.evaluation import repair_bakeoff as bakeoff
from scripts.spec_refinement.evaluation.fixtures import FixtureCategory, RepairFixture
from scripts.spec_refinement.workflows.repair import ArtifactType


def test_fixture_loading() -> None:
    fixtures = bakeoff._load_fixtures()
    assert fixtures

    categories: set[FixtureCategory] = set()
    for fixture in fixtures:
        categories |= bakeoff._infer_fixture_categories(fixture)

    assert categories == set(FixtureCategory)


def test_validation_helpers() -> None:
    fixture = bakeoff._load_fixtures()[0]
    errors = bakeoff.validate_repaired_output(
        fixture.invalid_output, fixture.artifact_type, fixture.allowlists
    )
    assert errors
    assert any(error.get("type") == fixture.expected_errors[0]["type"] for error in errors)


def test_edit_distance_calculation() -> None:
    assert bakeoff.compute_edit_distance("kitten", "sitting") == 3
    assert bakeoff.compute_edit_distance("same", "same") == 0
    assert bakeoff.compute_edit_distance("", "abc") == 3


def test_model_runner(monkeypatch, tmp_path: Path) -> None:
    fixture = RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: F0001\n"
            "File ID: F0001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [alpha::INTRO]\n"
        ),
        expected_errors=[{"type": "unknown_file_reference"}],
        allowlists={
            "file_id": "F0001",
            "file_ids": ["F0001"],
            "sections": {"F0001": ["INTRO"]},
        },
        description="Invalid file id",
    )
    bakeoff._index_fixtures([fixture])

    def _fake_repair_artifact(**_kwargs: object) -> str:
        return (
            "# File Summary: F0001\n"
            "File ID: F0001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [F0001::INTRO]\n"
        )

    monkeypatch.setattr(bakeoff, "repair_artifact", _fake_repair_artifact)

    model = bakeoff.ModelConfig(
        name="gpt-5.2-none",
        provider="openai",
        model_id="gpt-5.2-none",
        cost_per_1k_tokens=(0.0, 0.0),
    )
    result = bakeoff.run_repair_with_model(fixture, model, tmp_path)

    assert result.model_name == model.name
    assert result.success is True
    assert result.edit_distance > 0


def test_report_generation(tmp_path: Path) -> None:
    fixture = RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output="# File Summary: F0001\n",
        expected_errors=[{"type": "missing_citation"}],
        allowlists={
            "file_id": "F0001",
            "file_ids": ["F0001"],
            "sections": {"F0001": ["INTRO"]},
        },
        description="Missing citation",
    )
    bakeoff._index_fixtures([fixture])
    fixture_id = bakeoff._FIXTURE_ID_BY_OBJECT[id(fixture)]

    results = [
        bakeoff.RepairResult(
            fixture_id=fixture_id,
            model_name="gpt-5.2-none",
            success=True,
            validation_errors=[],
            edit_distance=1,
            latency_ms=10.0,
            input_tokens=10,
            output_tokens=10,
            cost_usd=0.0,
        )
    ]

    report_path = tmp_path / "report.md"
    bakeoff.generate_report(results, report_path)

    contents = report_path.read_text(encoding="utf-8")
    assert "Executive Summary" in contents
    assert "Per-Category Breakdown" in contents
    assert "Recommendation" in contents
