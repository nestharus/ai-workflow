from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from spec_manager.refinement.formats import (
    EVIDENCE_POINTER_RE,
    LibraryCharter,
    _extract_sections,
    _parse_overlap_resolutions,
)
from spec_manager.refinement.validation_utils import strip_invalid_file_pointers
from spec_manager.refinement.workflows.architecture import (
    _validate_architecture_citations,
    map_libraries_to_architecture,
    propose_architectures,
    select_architecture,
)
from spec_manager.refinement.workflows.evidence_expansion import (
    _validate_evidence_entry,
    expand_evidence,
)
from spec_manager.refinement.workflows.library_synthesis import (
    _validate_evidence_sources,
    _validate_library_ids,
    _validate_overlap_resolutions,
    synthesize_libraries,
)
from spec_manager.refinement.workflows.spec_building import _validate_spec_citations, build_specs
from spec_manager.refinement.workflows.sublibrary_detection import detect_sublibraries
from spec_manager.refinement.workflows.summarization import (
    _validate_evidence_pointers,
    summarize_all,
)
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager
from spec_manager.schemas.library_labels import LibraryLabelerOutput

from tests.spec_refinement.fixtures.expected_outputs import (
    EXPECTED_GAP_CONVERGENCE_RATIO,
    EXPECTED_PERFORMANCE_BOUNDS,
    EXPECTED_PHASE_OUTPUTS,
)
from tests.spec_refinement.test_performance import (
    benchmark_phase,
    generate_performance_report,
)


def _assert_phase_completed(run_id: str, phase: Phase) -> dict[str, object]:
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    phase_result = manager.state.phases[phase.value]
    assert phase_result.status == PhaseStatus.COMPLETED
    return phase_result.outputs


def _assert_phase_outputs(outputs: dict[str, object], expected_keys: set[str]) -> None:
    assert expected_keys.issubset(outputs.keys())


def _validate_summary_files(manager: WorkspaceManager) -> None:
    for file_id in manager.state.file_manifest:
        summary_path = manager.structure.summaries_dir / f"{file_id}.what.md"
        assert summary_path.exists()
        issues = _validate_evidence_pointers(
            summary_path.read_text(encoding="utf-8"), manager, file_id
        )
        assert issues == []


def _validate_spec_files(manager: WorkspaceManager) -> None:
    for lib_id in manager.get_all_libraries_recursive():
        spec_path = manager.structure.libraries_dir / lib_id / "spec.md"
        assert spec_path.exists()
        issues = _validate_spec_citations(spec_path.read_text(encoding="utf-8"), manager, lib_id)
        assert issues == []


def _validate_summary_file(manager: WorkspaceManager, file_id: str) -> bool:
    summary_path = manager.structure.summaries_dir / f"{file_id}.what.md"
    if not summary_path.exists():
        return False
    issues = _validate_evidence_pointers(summary_path.read_text(encoding="utf-8"), manager, file_id)
    return issues == []


def _validate_spec_file(manager: WorkspaceManager, lib_id: str) -> bool:
    spec_path = manager.structure.libraries_dir / lib_id / "spec.md"
    if not spec_path.exists():
        return False
    issues = _validate_spec_citations(spec_path.read_text(encoding="utf-8"), manager, lib_id)
    return issues == []


def _validate_architecture_file(manager: WorkspaceManager, filename: str) -> bool:
    path = manager.structure.architecture_dir / filename
    if not path.exists():
        return False
    issues = _validate_architecture_citations(path.read_text(encoding="utf-8"), manager)
    return issues == []


def _validate_evidence_file(manager: WorkspaceManager, lib_id: str, file_id: str | None) -> bool:
    evidence_path = manager.structure.libraries_dir / lib_id / "evidence.json"
    if not evidence_path.exists():
        return False
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    sources = payload.get("sources", [])
    if not isinstance(sources, list):
        return False
    relevant_sources = [
        entry for entry in sources if file_id is None or entry.get("file_id") == file_id
    ]
    if file_id is not None and not relevant_sources:
        return False
    for entry in relevant_sources:
        issues, _ = _validate_evidence_entry(entry, manager, lib_id)
        if issues:
            return False
    return True


def _parse_charter_content(content: str, lib_id: str) -> LibraryCharter:
    sections = _extract_sections(content, level=2)
    responsibilities: list[str] = []
    for line in sections.get("Responsibilities", "").splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            responsibilities.append(stripped.lstrip("-* ").strip())

    evidence_sources: dict[str, set[str]] = {}
    for file_ref, section_ref in EVIDENCE_POINTER_RE.findall(sections.get("Evidence", "")):
        evidence_sources.setdefault(file_ref, set()).add(section_ref)

    overlap_resolutions = _parse_overlap_resolutions(sections.get("Overlap Resolutions", ""))

    return LibraryCharter(
        lib_id=lib_id,
        intent=sections.get("Intent", "").strip(),
        boundaries=sections.get("Boundaries", "").strip(),
        responsibilities=responsibilities,
        evidence_sources=[
            {"file_id": file_ref, "sections": sorted(sections)}
            for file_ref, sections in evidence_sources.items()
        ],
        overlap_resolutions=overlap_resolutions,
    )


def _validate_charter_file(manager: WorkspaceManager, lib_id: str) -> bool:
    charter_path = manager.structure.libraries_dir / lib_id / "charter.md"
    if not charter_path.exists():
        return False
    charter = _parse_charter_content(charter_path.read_text(encoding="utf-8"), lib_id)
    issues: list[dict[str, object]] = []
    issues.extend(_validate_library_ids([charter]))
    issues.extend(_validate_evidence_sources([charter], manager))
    issues.extend(_validate_overlap_resolutions([charter]))
    return issues == []


def _validate_library_labels(manager: WorkspaceManager, file_id: str) -> bool:
    labels_path = manager.structure.libraries_dir / "file_labels.json"
    if not labels_path.exists():
        return False
    try:
        payload = json.loads(labels_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    entry = payload.get(file_id)
    if not isinstance(entry, dict):
        return False
    try:
        LibraryLabelerOutput.model_validate(
            {
                "file_id": file_id,
                "candidate_labels": entry.get("candidate_labels", []),
                "uncertain_labels": entry.get("uncertain_labels", []),
            }
        )
    except ValidationError:
        return False
    return True


def _validate_repair_call(call: dict[str, object], manager: WorkspaceManager) -> bool:
    artifact_type = call.get("artifact_type")
    file_id = call.get("file_id") if isinstance(call.get("file_id"), str) else None
    lib_id = call.get("lib_id") if isinstance(call.get("lib_id"), str) else None

    if artifact_type == "summary" and file_id:
        return _validate_summary_file(manager, file_id)
    if artifact_type == "library_labels" and file_id:
        return _validate_library_labels(manager, file_id)
    if artifact_type == "charter" and lib_id:
        return _validate_charter_file(manager, lib_id)
    if artifact_type == "evidence_json" and lib_id:
        return _validate_evidence_file(manager, lib_id, file_id)
    if artifact_type in {"spec", "spec_patches"} and lib_id:
        return _validate_spec_file(manager, lib_id)
    if artifact_type == "architecture_selection":
        return _validate_architecture_file(manager, "selected.md")
    if artifact_type == "architecture_mapping":
        return _validate_architecture_file(manager, "mapping.md")
    return False


def _collect_repair_failures(manager: WorkspaceManager) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for phase_result in manager.state.phases.values():
        for issue in phase_result.issues:
            if issue.get("type") == "repair_failed":
                failures.append(
                    {
                        "phase": phase_result.phase.value,
                        "issue": issue,
                    }
                )
    return failures


def _run_full_workflow(run_id: str, *, max_iterations: int = 2) -> None:
    summarize_all(run_id, parallel=False)
    synthesize_libraries(run_id)
    expand_evidence(run_id)
    build_specs(run_id, max_iterations=max_iterations)
    detect_sublibraries(run_id)
    propose_architectures(run_id)
    select_architecture(run_id)
    map_libraries_to_architecture(run_id)


class TestFullWorkflowIntegration:
    """End-to-end integration tests for 6-phase spec refinement workflow."""

    @pytest.mark.integration
    def test_full_workflow_success_path(self, spec_refinement_workspace, mock_all_agents) -> None:
        manager, manifest = spec_refinement_workspace()
        mock_all_agents(manifest, violation_rate=0.0)

        run_id = manager.run_id
        summarize_all(run_id, parallel=False)
        outputs = _assert_phase_completed(run_id, Phase.SUMMARIZATION)
        _assert_phase_outputs(outputs, EXPECTED_PHASE_OUTPUTS["summarization"]["required_keys"])
        _validate_summary_files(manager)

        synthesize_libraries(run_id)
        outputs = _assert_phase_completed(run_id, Phase.LIBRARY_SYNTHESIS)
        _assert_phase_outputs(outputs, EXPECTED_PHASE_OUTPUTS["library_synthesis"]["required_keys"])
        libraries_dir = manager.structure.libraries_dir
        assert (libraries_dir / "library_index.md").exists()

        expand_evidence(run_id)
        outputs = _assert_phase_completed(run_id, Phase.EVIDENCE_EXPANSION)
        _assert_phase_outputs(
            outputs, EXPECTED_PHASE_OUTPUTS["evidence_expansion"]["required_keys"]
        )

        build_specs(run_id, max_iterations=2)
        outputs = _assert_phase_completed(run_id, Phase.SPEC_BUILDING)
        _assert_phase_outputs(outputs, EXPECTED_PHASE_OUTPUTS["spec_building"]["required_keys"])
        _validate_spec_files(manager)

        detect_sublibraries(run_id)
        outputs = _assert_phase_completed(run_id, Phase.SUBLIBRARY_DETECTION)
        _assert_phase_outputs(
            outputs, EXPECTED_PHASE_OUTPUTS["sublibrary_detection"]["required_keys"]
        )

        propose_architectures(run_id)
        outputs = _assert_phase_completed(run_id, Phase.ARCHITECTURE_PROPOSAL)
        _assert_phase_outputs(
            outputs, EXPECTED_PHASE_OUTPUTS["architecture_proposal"]["required_keys"]
        )

        select_architecture(run_id)
        outputs = _assert_phase_completed(run_id, Phase.ARCHITECTURE_SELECTION)
        _assert_phase_outputs(
            outputs, EXPECTED_PHASE_OUTPUTS["architecture_selection"]["required_keys"]
        )

        map_libraries_to_architecture(run_id)
        outputs = _assert_phase_completed(run_id, Phase.ARCHITECTURE_MAPPING)
        _assert_phase_outputs(
            outputs, EXPECTED_PHASE_OUTPUTS["architecture_mapping"]["required_keys"]
        )

        refreshed = WorkspaceManager(run_id=run_id, input_folder=Path("."))
        spec_phase = refreshed.state.phases[Phase.SPEC_BUILDING.value]
        coverage = spec_phase.outputs.get("coverage_metrics", {})
        total_ratio = coverage.get("total_coverage_ratio", 0)
        assert total_ratio >= EXPECTED_GAP_CONVERGENCE_RATIO
        assert spec_phase.gap_audit_converged is True
        assert spec_phase.open_gaps_count == 0
        for metrics in coverage.get("libraries", {}).values():
            ratio = metrics.get("convergence_ratio", 1.0)
            assert ratio >= EXPECTED_GAP_CONVERGENCE_RATIO

        mapping_path = refreshed.structure.architecture_dir / "mapping.md"
        mapping_text = mapping_path.read_text(encoding="utf-8")
        for lib_id in refreshed.get_all_libraries_recursive():
            assert lib_id in mapping_text

    @pytest.mark.integration
    def test_full_workflow_with_repair_gates(
        self, spec_refinement_workspace, mock_all_agents
    ) -> None:
        manager, manifest = spec_refinement_workspace(run_id="run_repair")
        controller = mock_all_agents(
            manifest,
            violation_rate=0.3,
            overrides={
                "glm-library-evidence-mapper": 0.1,
                "chatgpt-library-spec-gap-judge": 0.0,
            },
        )

        run_id = manager.run_id
        _run_full_workflow(run_id, max_iterations=2)

        refreshed = WorkspaceManager(run_id=run_id, input_folder=Path("."))
        assert (
            refreshed.state.phases[Phase.ARCHITECTURE_MAPPING.value].status == PhaseStatus.COMPLETED
        )
        repair_calls = list(controller.repair_calls)
        if not repair_calls:
            pytest.skip("No repairs triggered; skipping repair success rate check.")
        repair_failures = _collect_repair_failures(refreshed)
        assert not repair_failures
        failed_repairs = [
            call for call in repair_calls if not _validate_repair_call(call, refreshed)
        ]
        success_rate = (len(repair_calls) - len(failed_repairs)) / len(repair_calls)
        assert success_rate >= 0.8
        _validate_summary_files(refreshed)
        _validate_spec_files(refreshed)

    @pytest.mark.integration
    def test_invalid_pointers_recovered(self, spec_refinement_workspace, mock_all_agents) -> None:
        manager, manifest = spec_refinement_workspace(run_id="run_invalid_ptr")
        controller = mock_all_agents(
            manifest,
            violation_rate=0.0,
            overrides={"glm-file-what-summarizer": 1.0},
        )

        summarize_all(manager.run_id, parallel=False)
        assert controller.repair_calls
        _validate_summary_files(manager)

    @pytest.mark.integration
    def test_missing_sections_recovered(self, spec_refinement_workspace, mock_all_agents) -> None:
        manager, manifest = spec_refinement_workspace(run_id="run_missing_section")
        mock_all_agents(
            manifest,
            violation_rate=0.0,
            overrides={"glm-library-evidence-mapper": 1.0},
        )

        run_id = manager.run_id
        summarize_all(run_id, parallel=False)
        synthesize_libraries(run_id)
        result = expand_evidence(run_id)

        assert not any(issue["type"] == "unknown_section_reference" for issue in result["issues"])
        evidence_path = manager.structure.libraries_dir / "lib_001" / "evidence.json"
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert payload.get("sources")

    @pytest.mark.integration
    def test_non_monotonic_updates_prevented(
        self, spec_refinement_workspace, mock_all_agents
    ) -> None:
        manager, manifest = spec_refinement_workspace(run_id="run_non_monotonic")
        mock_all_agents(
            manifest,
            violation_rate=0.0,
            spec_patch_violation="invalid_op",
            overrides={"glm-library-spec-integrator": 1.0},
        )

        run_id = manager.run_id
        summarize_all(run_id, parallel=False)
        synthesize_libraries(run_id)
        expand_evidence(run_id)
        result = build_specs(run_id, max_iterations=1)

        assert any(issue["type"] == "invalid_patch_operation" for issue in result["issues"])

    @pytest.mark.integration
    def test_unmapped_libraries_detected(self, spec_refinement_workspace, mock_all_agents) -> None:
        manager, manifest = spec_refinement_workspace(run_id="run_unmapped")
        mock_all_agents(
            manifest,
            violation_rate=0.0,
            mapping_violation_mode="missing_citations",
            overrides={"glm-architecture-library-mapper": 1.0},
        )

        run_id = manager.run_id
        _run_full_workflow(run_id, max_iterations=1)
        mapping_result = map_libraries_to_architecture(run_id)
        assert mapping_result["unmapped_libraries"]

    @pytest.mark.integration
    def test_gap_convergence_failure(self, spec_refinement_workspace, mock_all_agents) -> None:
        manager, manifest = spec_refinement_workspace(run_id="run_gap_fail")
        mock_all_agents(manifest, violation_rate=0.0, gap_mode="persistent")

        run_id = manager.run_id
        summarize_all(run_id, parallel=False)
        synthesize_libraries(run_id)
        expand_evidence(run_id)
        result = build_specs(run_id, max_iterations=1)

        assert result["total_coverage_ratio"] < EXPECTED_GAP_CONVERGENCE_RATIO

    @pytest.mark.integration
    def test_phase_dependency_validation(self, spec_refinement_workspace) -> None:
        manager, _ = spec_refinement_workspace(run_id="run_dependency")
        with pytest.raises(RuntimeError):
            expand_evidence(manager.run_id)

    @pytest.mark.integration
    @pytest.mark.parametrize("file_count", [5, 10, 20])
    def test_distributed_phase2_library_discovery(
        self,
        spec_refinement_workspace,
        mock_all_agents,
        file_count: int,
    ) -> None:
        manager, manifest = spec_refinement_workspace(
            run_id=f"run_phase2_{file_count}", file_count=file_count
        )
        mock_all_agents(manifest, violation_rate=0.0)

        run_id = manager.run_id
        summarize_all(run_id, parallel=False)
        result = synthesize_libraries(run_id)

        assert result["libraries_created"] >= 1
        file_labels_path = manager.structure.libraries_dir / "file_labels.json"
        label_clusters_path = manager.structure.libraries_dir / "label_clusters.json"
        refined_labels_path = manager.structure.libraries_dir / "refined_labels.json"
        assert file_labels_path.exists()
        assert label_clusters_path.exists()
        assert refined_labels_path.exists()

        label_clusters = json.loads(label_clusters_path.read_text(encoding="utf-8"))
        metadata = label_clusters.get("metadata", {})
        assert "total_clusters" in metadata
        assert "singleton_count" in metadata

    @pytest.mark.integration
    def test_patch_based_phase4_integration(
        self, spec_refinement_workspace, mock_all_agents
    ) -> None:
        manager, manifest = spec_refinement_workspace(run_id="run_patch")
        mock_all_agents(manifest, violation_rate=0.0)

        run_id = manager.run_id
        summarize_all(run_id, parallel=False)
        synthesize_libraries(run_id)
        expand_evidence(run_id)
        result = build_specs(run_id, max_iterations=1)

        assert result["outputs"]["total_patches_applied"] > 0
        spec_path = manager.structure.libraries_dir / "lib_001" / "spec.md"
        spec_text = spec_path.read_text(encoding="utf-8")
        assert "# Library Spec" in spec_text
        assert "[F" in spec_text

    @pytest.mark.integration
    @pytest.mark.slow
    def test_performance_benchmarks(
        self,
        spec_refinement_workspace,
        mock_all_agents,
        performance_tracker,
        benchmark,
    ) -> None:
        manager, manifest = spec_refinement_workspace(run_id="run_perf", file_count=10)
        controller = mock_all_agents(manifest, violation_rate=0.0)

        run_id = manager.run_id

        def _run_full() -> None:
            with benchmark_phase(
                "summarization", performance_tracker, lambda: len(controller.call_log)
            ):
                summarize_all(run_id, parallel=False)
            with benchmark_phase(
                "library_synthesis", performance_tracker, lambda: len(controller.call_log)
            ):
                synthesize_libraries(run_id)
            with benchmark_phase(
                "evidence_expansion", performance_tracker, lambda: len(controller.call_log)
            ):
                expand_evidence(run_id)
            with benchmark_phase(
                "spec_building", performance_tracker, lambda: len(controller.call_log)
            ):
                build_specs(run_id, max_iterations=1)
            with benchmark_phase(
                "sublibrary_detection", performance_tracker, lambda: len(controller.call_log)
            ):
                detect_sublibraries(run_id)
            with benchmark_phase(
                "architecture", performance_tracker, lambda: len(controller.call_log)
            ):
                propose_architectures(run_id)
                select_architecture(run_id)
                map_libraries_to_architecture(run_id)

        memory_before = None
        try:
            import resource

            memory_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except Exception:
            memory_before = None

        benchmark.pedantic(_run_full, rounds=1, iterations=1)

        total_time = performance_tracker.total_latency()
        assert total_time < EXPECTED_PERFORMANCE_BOUNDS["total_seconds"]
        assert performance_tracker.total_tokens() > 0
        assert performance_tracker.total_cost() >= 0.0
        for phase_name, metric in performance_tracker.phases.items():
            bound = EXPECTED_PERFORMANCE_BOUNDS["phase_seconds"].get(phase_name)
            if bound is not None:
                assert metric.latency_seconds < bound

        report = generate_performance_report(performance_tracker)
        report_path = manager.structure.audits_dir / "integration_performance.md"
        report_path.write_text(report, encoding="utf-8")

        if memory_before is not None:
            try:
                import resource
            except ImportError:
                pass
            else:
                memory_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                assert (memory_after - memory_before) < 50 * 1024


def test_basename_stem_resolution(spec_refinement_workspace) -> None:
    manager, manifest = spec_refinement_workspace(run_id="run_basename")
    sec_id = manifest["F0001"]["sections"][0]
    content = f"Evidence: [alpha.md::{sec_id}]\nEvidence: [alpha::{sec_id}]"
    issues = _validate_evidence_pointers(content, manager, "F0001")
    assert issues == []


def test_legacy_label_rejected(spec_refinement_workspace) -> None:
    """Legacy labels like 'intro' or 'INTRO' are flagged as unknown section references."""
    manager, _ = spec_refinement_workspace(run_id="run_case")
    content = "Evidence: [F0001::intro] Evidence: [F0001::INTRO] Evidence: [F0001::Intro]"
    issues = _validate_evidence_pointers(content, manager, "F0001")
    section_issues = [i for i in issues if i["type"] == "unknown_section_reference"]
    assert len(section_issues) == 3


def test_normalized_label_rejected(spec_refinement_workspace) -> None:
    """Normalized labels like 'user-requirements' are flagged as unknown section references."""
    manager, _ = spec_refinement_workspace(run_id="run_separator")
    content = "Evidence: [F0001::user-requirements]"
    issues = _validate_evidence_pointers(content, manager, "F0001")
    assert any(i["type"] == "unknown_section_reference" for i in issues)


def test_derived_pointer_scrubbing(spec_refinement_workspace) -> None:
    manager, _ = spec_refinement_workspace(run_id="run_derived")
    content = (
        "Evidence: [charter::INTENT] [libraries/lib_001/spec.md::OVERVIEW] "
        "[runs/run_001/summaries/F0001.what.md::SUMMARY]"
    )
    cleaned = strip_invalid_file_pointers(content, manager.state.file_manifest)
    assert "charter::INTENT" not in cleaned
    assert "libraries/lib_001" not in cleaned
    assert "runs/run_001" not in cleaned


def test_compound_pointer_rejection(spec_refinement_workspace, mock_all_agents) -> None:
    manager, manifest = spec_refinement_workspace(run_id="run_compound")
    controller = mock_all_agents(
        manifest,
        violation_rate=0.0,
        spec_patch_violation="compound_pointer",
        overrides={"glm-library-spec-integrator": 1.0},
    )

    run_id = manager.run_id
    summarize_all(run_id, parallel=False)
    synthesize_libraries(run_id)
    expand_evidence(run_id)
    build_specs(run_id, max_iterations=1)

    assert any(call["artifact_type"] == "spec_patches" for call in controller.repair_calls)


def test_priority_ranking_over_skip_heuristics(spec_refinement_workspace, mock_all_agents) -> None:
    manager, manifest = spec_refinement_workspace(run_id="run_priority")
    controller = mock_all_agents(manifest, violation_rate=0.0)

    run_id = manager.run_id
    summarize_all(run_id, parallel=False)
    synthesize_libraries(run_id)

    labels_path = manager.structure.libraries_dir / "file_labels.json"
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    for entry in payload.values():
        for label in entry.get("candidate_labels", []):
            label["confidence"] = 0.4
    labels_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    expand_evidence(run_id)
    classifier_calls = [
        call
        for call in controller.call_log
        if call["agent_name"] == "glm-library-relevance-classifier"
    ]
    assert classifier_calls
