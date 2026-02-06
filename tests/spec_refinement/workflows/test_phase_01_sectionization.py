from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from spec_manager.core.gaps import Severity
from spec_manager.refinement.core.gap import Gap, GapEvidence, GapType
from spec_manager.refinement.workflows import phase_01_sectionization as phase_one
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager


def _extract(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _extract_file_id(prompt: str) -> str:
    return _extract(r"File ID:\s*(F\d{4})", prompt) or "F0001"


def _extract_total_lines(prompt: str) -> int:
    value = _extract(r"Total Lines:\s*(\d+)", prompt)
    return int(value) if value else 1


def _extract_section_ids(prompt: str) -> list[str]:
    return sorted(set(re.findall(r"SEC-F\d{4}-\d{4}", prompt)))


def _make_agent_stub(
    call_log: list[dict[str, str]],
    *,
    truncate_sections_for: set[str] | None = None,
    bad_ordinal_for: set[str] | None = None,
    raise_for: dict[str, set[str]] | None = None,
) -> callable:
    truncate_sections_for = truncate_sections_for or set()
    bad_ordinal_for = bad_ordinal_for or set()
    raise_for = raise_for or {}

    def _run_agent(
        *,
        agent_name: str,
        prompt: str,
        workspace: Path,
        max_retries: int = 2,
        extra_env: dict[str, str] | None = None,
    ) -> str:
        _ = workspace
        _ = max_retries
        _ = extra_env

        file_id = _extract_file_id(prompt)
        call_log.append({"agent_name": agent_name, "file_id": file_id, "prompt": prompt})

        if agent_name in raise_for and file_id in raise_for[agent_name]:
            raise RuntimeError(f"boom ({agent_name})")

        if agent_name == "glm-section-span-lister":
            total_lines = _extract_total_lines(prompt)
            end_line = max(1, total_lines - 1) if file_id in truncate_sections_for else total_lines
            ordinal = "0099" if file_id in bad_ordinal_for else "0001"
            sections = [
                {
                    "section_id": f"SEC-{file_id}-{ordinal}",
                    "start_line": 1,
                    "end_line": end_line,
                    "label": "SECTION",
                }
            ]
            return json.dumps(sections)

        if agent_name == "glm-section-map-builder":
            return f"# Section Map: {file_id}\n- SEC-{file_id}-0001: SECTION\n"

        if agent_name == "glm-terms-per-section":
            section_ids = _extract_section_ids(prompt) or [f"SEC-{file_id}-0001"]
            payload = {
                "file_id": file_id,
                "section_terms": [
                    {"section_id": section_ids[0], "terms": ["term"], "confidence": 0.9}
                ],
                "global_terms": ["term"],
            }
            return json.dumps(payload)

        raise AssertionError(f"Unexpected agent name: {agent_name}")

    return _run_agent


def _load_manager(run_id: str) -> WorkspaceManager:
    return WorkspaceManager(run_id=run_id, input_folder=Path("."))


def test_sectionize_all_sequential_creates_outputs_and_updates_phase(
    spec_refinement_workspace, mock_all_agents, monkeypatch
) -> None:
    manager, manifest = spec_refinement_workspace(file_count=2)
    mock_all_agents(manifest, violation_rate=0.0)

    call_log: list[dict[str, str]] = []
    monkeypatch.setattr(phase_one, "run_agent", _make_agent_stub(call_log))

    result = phase_one.sectionize_all(manager.run_id, parallel=False)
    assert result["success"] is True

    refreshed = _load_manager(manager.run_id)
    phase_result = refreshed.state.phases[Phase.SECTIONIZATION.value]
    assert phase_result.status == PhaseStatus.COMPLETED

    for file_id in manifest:
        sections_path = refreshed.structure.manifest_sections_dir / f"{file_id}.sections.json"
        atoms_path = refreshed.structure.manifest_atoms_dir / f"{file_id}.atoms.jsonl"
        terms_path = refreshed.structure.manifest_terms_dir / f"{file_id}.terms.json"
        map_path = refreshed.structure.manifest_sections_dir / f"{file_id}.section_map.md"
        assert sections_path.exists()
        assert atoms_path.exists()
        assert terms_path.exists()
        assert map_path.exists()

    evidence_path = refreshed.structure.pass_01_dir / "evidence.jsonl"
    assert evidence_path.exists()

    by_file: dict[str, list[str]] = {}
    for entry in call_log:
        by_file.setdefault(entry["file_id"], []).append(entry["agent_name"])

    for sequence in by_file.values():
        assert sequence == [
            "glm-section-span-lister",
            "glm-section-map-builder",
            "glm-terms-per-section",
        ]

    for entry in call_log:
        prompt = entry["prompt"]
        assert "OUTPUT CONTRACT" in prompt
        assert f"File ID: {entry['file_id']}" in prompt
        assert "Source File Content:" in prompt

    progress_updates = [
        item for item in refreshed.state.history if item.get("event") == "progress_update"
    ]
    assert len(progress_updates) == len(manifest)


def test_sectionize_all_parallel_uses_threadpool(
    spec_refinement_workspace, mock_all_agents, monkeypatch
) -> None:
    manager, manifest = spec_refinement_workspace(file_count=2)
    mock_all_agents(manifest, violation_rate=0.0)

    call_log: list[dict[str, str]] = []
    monkeypatch.setattr(phase_one, "run_agent", _make_agent_stub(call_log))

    executor_used = {"value": False}

    class _Future:
        def __init__(self, result):
            self._result = result

        def result(self):
            return self._result

    class _Executor:
        def __init__(self, max_workers: int):
            self.max_workers = max_workers

        def __enter__(self):
            executor_used["value"] = True
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            return _Future(fn(*args, **kwargs))

    monkeypatch.setattr(phase_one, "ThreadPoolExecutor", _Executor)
    monkeypatch.setattr(phase_one, "as_completed", lambda futures: list(futures))

    result = phase_one.sectionize_all(manager.run_id, parallel=True)
    assert result["success"] is True
    assert executor_used["value"] is True


def test_sectionize_all_sequential_skips_threadpool(
    spec_refinement_workspace, mock_all_agents, monkeypatch
) -> None:
    manager, manifest = spec_refinement_workspace(file_count=1)
    mock_all_agents(manifest, violation_rate=0.0)

    call_log: list[dict[str, str]] = []
    monkeypatch.setattr(phase_one, "run_agent", _make_agent_stub(call_log))

    def _raise_executor(*args, **kwargs):
        raise AssertionError("ThreadPoolExecutor should not be used")

    monkeypatch.setattr(phase_one, "ThreadPoolExecutor", _raise_executor)

    result = phase_one.sectionize_all(manager.run_id, parallel=False)
    assert result["success"] is True


def test_sectionize_all_aggregates_evidence_and_synthesizes_gaps(
    spec_refinement_workspace, mock_all_agents, monkeypatch
) -> None:
    manager, manifest = spec_refinement_workspace(file_count=1)
    mock_all_agents(manifest, violation_rate=0.0)

    call_log: list[dict[str, str]] = []
    bad_ordinal = {next(iter(manifest.keys()))}
    monkeypatch.setattr(
        phase_one,
        "run_agent",
        _make_agent_stub(call_log, bad_ordinal_for=bad_ordinal),
    )

    class _Synthesizer:
        called_with: list[GapEvidence] | None = None

        def cluster_evidence(self, evidence: list[GapEvidence]) -> list[Gap]:
            _Synthesizer.called_with = evidence
            return [
                Gap(
                    id="GAP-test",
                    gap_type=GapType.coverage_failure,
                    severity=Severity.ERROR,
                    source=["spec_snapshot/alpha.md::SEC-F0001-0001"],
                    derived_artifact_target="F0001",
                    description="Missing coverage",
                    evidence=[],
                )
            ]

    monkeypatch.setattr(phase_one, "GapSynthesizer", _Synthesizer)

    result = phase_one.sectionize_all(manager.run_id, parallel=False)
    assert result["success"] is False

    refreshed = _load_manager(manager.run_id)
    evidence_path = refreshed.structure.pass_01_dir / "evidence.jsonl"
    gaps_path = refreshed.structure.pass_01_dir / "gaps.json"

    assert evidence_path.exists()
    assert gaps_path.exists()
    assert _Synthesizer.called_with

    gaps = json.loads(gaps_path.read_text(encoding="utf-8"))
    assert any(gap["id"] == "GAP-test" for gap in gaps)


def test_sectionize_all_reports_errors_and_failure_threshold(
    spec_refinement_workspace, mock_all_agents, monkeypatch
) -> None:
    manager, manifest = spec_refinement_workspace(file_count=3)
    mock_all_agents(manifest, violation_rate=0.0)

    call_log: list[dict[str, str]] = []
    file_ids = list(manifest.keys())
    raise_for = {"glm-section-span-lister": {file_ids[0], file_ids[1]}}
    monkeypatch.setattr(phase_one, "run_agent", _make_agent_stub(call_log, raise_for=raise_for))

    result = phase_one.sectionize_all(manager.run_id, parallel=False)
    assert result["success"] is False
    assert len(result["errors"]) == 2

    refreshed = _load_manager(manager.run_id)
    phase_result = refreshed.state.phases[Phase.SECTIONIZATION.value]
    assert phase_result.status == PhaseStatus.FAILED
    assert "file failure" in (phase_result.error or "")


class TestRepairSectionGaps:
    """Tests for _repair_section_gaps helper."""

    def test_closes_single_line_gap(self) -> None:
        sections = [
            {"section_id": "SEC-F0001-0001", "start_line": 1, "end_line": 1, "label": "A"},
            {"section_id": "SEC-F0001-0002", "start_line": 3, "end_line": 5, "label": "B"},
        ]
        repaired = phase_one._repair_section_gaps(sections, total_lines=5)
        assert repaired[1]["start_line"] == 2

    def test_extends_last_section_to_total_lines(self) -> None:
        sections = [
            {"section_id": "SEC-F0001-0001", "start_line": 1, "end_line": 3, "label": "A"},
        ]
        repaired = phase_one._repair_section_gaps(sections, total_lines=10)
        assert repaired[0]["end_line"] == 10

    def test_preserves_correct_sections(self) -> None:
        sections = [
            {"section_id": "SEC-F0001-0001", "start_line": 1, "end_line": 5, "label": "A"},
            {"section_id": "SEC-F0001-0002", "start_line": 6, "end_line": 10, "label": "B"},
        ]
        repaired = phase_one._repair_section_gaps(sections, total_lines=10)
        assert repaired[0]["start_line"] == 1
        assert repaired[0]["end_line"] == 5
        assert repaired[1]["start_line"] == 6
        assert repaired[1]["end_line"] == 10

    def test_empty_sections_unchanged(self) -> None:
        assert phase_one._repair_section_gaps([], total_lines=10) == []

    def test_sorts_by_start_line(self) -> None:
        sections = [
            {"section_id": "SEC-F0001-0002", "start_line": 10, "end_line": 15, "label": "B"},
            {"section_id": "SEC-F0001-0001", "start_line": 1, "end_line": 9, "label": "A"},
        ]
        repaired = phase_one._repair_section_gaps(sections, total_lines=15)
        assert repaired[0]["section_id"] == "SEC-F0001-0001"
        assert repaired[1]["section_id"] == "SEC-F0001-0002"
        assert repaired[1]["start_line"] == 10


class TestFixSingleQuoteJson:
    """Tests for _fix_single_quote_json helper."""

    def test_fixes_single_quotes(self) -> None:
        from spec_manager.refinement.formats import _fix_single_quote_json

        result = _fix_single_quote_json("{'key': 'value', 'num': 42}")
        parsed = json.loads(result)
        assert parsed == {"key": "value", "num": 42}

    def test_preserves_valid_json(self) -> None:
        from spec_manager.refinement.formats import _fix_single_quote_json

        original = '{"key": "value"}'
        assert _fix_single_quote_json(original) == original

    def test_handles_nested_single_quotes(self) -> None:
        from spec_manager.refinement.formats import _fix_single_quote_json

        result = _fix_single_quote_json("{'a': {'b': 'c'}}")
        parsed = json.loads(result)
        assert parsed == {"a": {"b": "c"}}

    def test_returns_original_on_invalid_input(self) -> None:
        from spec_manager.refinement.formats import _fix_single_quote_json

        original = "not json at all"
        assert _fix_single_quote_json(original) == original
