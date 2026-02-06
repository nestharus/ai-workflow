from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from spec_manager.refinement.workflows.reports import (
    generate_compliance_report,
    generate_coverage_report,
    generate_drift_report,
    generate_run_audit,
)
from spec_manager.refinement.workflows.trace_indexes import build_trace_indexes
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager
from spec_manager.schemas.spec_indexes import SpecIndex
from spec_manager.schemas.task_status import TaskImplementationStatusSchema
from spec_manager.schemas.tasks import (
    TaskCoversSchema,
    TaskIndexEntrySchema,
    TaskIndexSchema,
    TaskSchema,
    write_task_index_json,
    write_task_json,
)

from tests.spec_refinement.fixtures.test_corpus import (
    create_interface_test_libraries,
    create_task_planning_prerequisites,
)
from tests.spec_refinement.utils import (
    _count_markdown_sections,
    _extract_table_rows,
    _validate_json_index,
    _validate_markdown_table,
)


def _get_primary_file_id(manager: WorkspaceManager) -> str:
    return sorted(manager.state.file_manifest.keys())[0]


def _write_sections(manager: WorkspaceManager, file_id: str) -> list[str]:
    sections = [
        {
            "section_id": f"SEC-{file_id}-0001",
            "start_line": 1,
            "end_line": 2,
            "label": "INTRO",
        },
        {
            "section_id": f"SEC-{file_id}-0002",
            "start_line": 3,
            "end_line": 4,
            "label": "DETAILS",
        },
    ]
    manager.write_file_sections(
        file_id,
        {
            "file_id": file_id,
            "sections": sections,
            "total_lines": 4,
        },
    )
    manager.save_state()
    return [section["section_id"] for section in sections]


def _write_atoms(manager: WorkspaceManager, file_id: str, section_ids: list[str]) -> None:
    atoms = []
    rev_id = "R0001"
    for index, section_id in enumerate(section_ids, start=1):
        text = f"Line {index}"
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        # atom_fingerprint is content-based fingerprint for cross-revision matching
        fingerprint = hashlib.sha256(f"{text}:{index}".encode()).hexdigest()
        atoms.append(
            {
                "atom_id": f"ATOM-{file_id}-{rev_id}-L{index:04d}",
                "atom_fingerprint": fingerprint,
                "file_uid": file_id,
                "rev_id": rev_id,
                "line_no": index,
                "sequence_index": index - 1,
                "section_id": section_id,
                "sha256": text_hash,
                "text": text,
            }
        )
    manager.write_file_atoms(file_id, atoms)


def _write_spec_index(
    manager: WorkspaceManager,
    lib_id: str,
    elements: list[dict[str, Any]],
) -> None:
    lib_dir = manager.structure.libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "lib_id": lib_id,
        "generated_at": "2024-01-01T00:00:00",
        "spec_path": f"libraries/{lib_id}/spec.md",
        "elements": elements,
    }
    SpecIndex.model_validate(payload)
    (lib_dir / "spec_index.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _build_status_payload(
    task_id: str,
    status: str,
    *,
    patch_sha256: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "repo_root": "/repo",
    }
    if status in {"in_progress", "done", "failed"}:
        payload["started_at"] = "2024-01-01T00:00:00"
    if status in {"done", "failed"}:
        payload["finished_at"] = "2024-01-01T00:10:00"
    if status == "done":
        payload["patch_sha256"] = patch_sha256
    if error:
        payload["error"] = error
    TaskImplementationStatusSchema.model_validate(payload)
    return payload


def _write_tasks(
    manager: WorkspaceManager,
    task_defs: list[dict[str, Any]],
) -> list[str]:
    tasks_dir = manager.structure.tasks_dir
    tasks_dir.mkdir(parents=True, exist_ok=True)
    entries: list[TaskIndexEntrySchema] = []
    task_ids: list[str] = []

    for spec in task_defs:
        task_id = spec["task_id"]
        element_ids = spec.get("elements", [])
        libraries = spec.get("libraries", ["LIB-0001"])
        task = TaskSchema(
            task_id=task_id,
            title=spec.get("title", f"Task {task_id}"),
            description=spec.get("description", "Finalize report task."),
            priority=spec.get("priority", "p1"),
            component=spec.get("component", "API Layer"),
            libraries=libraries,
            covers=TaskCoversSchema(
                elements=element_ids,
                edges=spec.get("edges", []),
                decisions=spec.get("decisions", []),
                gaps=spec.get("gaps", []),
            ),
            acceptance_criteria=spec.get("acceptance_criteria", ["Verify output."]),
            suggested_files=spec.get("suggested_files", []),
            risk_notes=spec.get("risk_notes", ""),
            validation_notes=spec.get("validation_notes", ""),
            citations=spec.get(
                "citations",
                ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
            ),
            depends_on=spec.get("depends_on", []),
        )
        write_task_json(task, tasks_dir / task_id / "task.json")

        entry_status = spec.get("index_status", spec.get("status", "planned"))
        entries.append(
            TaskIndexEntrySchema(
                task_id=task_id,
                title=task.title,
                status=entry_status,
                priority=task.priority,
                component=task.component,
                libraries=task.libraries,
                covers=task.covers,
                depends_on=task.depends_on,
            )
        )
        task_ids.append(task_id)

        task_dir = tasks_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        patch_sha256 = ""
        if spec.get("with_patch"):
            patch_text = spec.get("patch_text", f"diff --git a/{task_id}.txt b/{task_id}.txt\n")
            patch_path = task_dir / "patch.diff"
            patch_path.write_text(patch_text, encoding="utf-8")
            patch_sha256 = hashlib.sha256(patch_text.encode("utf-8")).hexdigest()

        if spec.get("write_status"):
            status_payload = spec.get("status_payload")
            if status_payload is None:
                status_payload = _build_status_payload(
                    task_id,
                    spec.get("status", "planned"),
                    patch_sha256=patch_sha256,
                    error=spec.get("error"),
                )
            (task_dir / "status.json").write_text(
                json.dumps(status_payload, indent=2),
                encoding="utf-8",
            )

    index = TaskIndexSchema(
        run_id=manager.run_id,
        generated_at="2024-01-01T00:00:00",
        tasks=entries,
    )
    write_task_index_json(index, tasks_dir / "task_index.json")
    return task_ids


def _write_qa_summary(manager: WorkspaceManager, payload: dict[str, Any]) -> None:
    qa_dir = manager.structure.audits_dir / "qa" / "20240101_000000"
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / "suite_summary.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _setup_finalize_prerequisites(interface_workspace, fs) -> WorkspaceManager:
    manager, manifest = interface_workspace(run_id="run_finalize_reports")
    create_interface_test_libraries(fs, run_id=manager.run_id)
    create_task_planning_prerequisites(fs, manager.run_id, manifest)

    file_id = _get_primary_file_id(manager)
    section_ids = _write_sections(manager, file_id)
    _write_atoms(manager, file_id, section_ids)

    _write_spec_index(
        manager,
        "LIB-0001",
        [
            {
                "element_id": "DTL-LIB-0001-0001",
                "kind": "detail",
                "section": "Details",
                "text": "Handle inbound requests.",
                "raw_line": "- DTL-LIB-0001-0001: Handle inbound requests.",
                "citations": [f"[spec_snapshot/input.md::{section_ids[0]}]"],
                "mentions_libs": [],
            },
            {
                "element_id": "DTL-LIB-0001-0002",
                "kind": "detail",
                "section": "Details",
                "text": "Validate processed output.",
                "raw_line": "- DTL-LIB-0001-0002: Validate processed output.",
                "citations": [f"[spec_snapshot/input.md::{section_ids[1]}]"],
                "mentions_libs": [],
            },
        ],
    )

    _write_tasks(
        manager,
        [
            {
                "task_id": "TASK-0001",
                "elements": ["DTL-LIB-0001-0001"],
                "status": "done",
                "with_patch": True,
                "write_status": True,
            },
            {
                "task_id": "TASK-0002",
                "elements": ["DTL-LIB-0001-0003"],
                "status": "failed",
                "with_patch": True,
                "write_status": True,
                "error": "Tests failed.",
            },
            {
                "task_id": "TASK-0003",
                "elements": ["CON-LIB-0001-0001"],
                "status": "blocked",
                "with_patch": False,
                "write_status": True,
                "error": "Waiting on upstream dependency.",
            },
        ],
    )

    build_trace_indexes(manager.run_id)
    return manager


class TestCoverageReport:
    def test_generate_coverage_report_basic(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_coverage_report(manager)

        report_path = manager.structure.reports_dir / "coverage.md"
        assert report_path.exists()
        assert "## Section Coverage" in content
        assert "## Library Coverage" in content
        assert "Coverage Ratio" in content
        sections = _count_markdown_sections(content)
        assert sections.get("Section Coverage") == 1

    def test_generate_coverage_report_section_metrics(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_coverage_report(manager)

        header = "| Total Sections | Referenced Sections | Coverage Ratio |"
        rows = _extract_table_rows(content, header)
        assert rows
        total_sections = int(rows[0][0])
        referenced = int(rows[0][1])
        assert total_sections == 2
        assert referenced == 2

    def test_generate_coverage_report_library_breakdown(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_coverage_report(manager)

        header = "| Library | Elements | Sections Cited | Coverage Ratio |"
        rows = _extract_table_rows(content, header)
        lib_rows = [row for row in rows if row and row[0] == "LIB-0001"]
        assert lib_rows
        assert lib_rows[0][1] == "2"
        assert lib_rows[0][2] == "2"

    def test_generate_coverage_report_zero_coverage(self, interface_workspace, fs) -> None:
        manager, _ = interface_workspace(run_id="run_coverage_zero")
        file_id = _get_primary_file_id(manager)
        _write_sections(manager, file_id)

        for lib_id in ["LIB-0001", "LIB-0002", "LIB-0003"]:
            _write_spec_index(
                manager,
                lib_id,
                [],
            )

        content = generate_coverage_report(manager)

        assert "| Total Sections | Referenced Sections | Coverage Ratio |" in content
        assert "0.00%" in content

    def test_generate_coverage_report_markdown_format(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_coverage_report(manager)

        assert _validate_markdown_table(
            content,
            ["Total Sections", "Referenced Sections", "Coverage Ratio"],
        )


class TestComplianceReport:
    def test_generate_compliance_report_basic(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)
        _write_qa_summary(
            manager,
            {
                "cases_total": 2,
                "cases_passed": 2,
                "cases_failed": 0,
                "results": [],
            },
        )

        content = generate_compliance_report(manager, run_qa=False)

        report_path = manager.structure.reports_dir / "compliance.md"
        assert report_path.exists()
        assert "## QA Validation Results" in content
        assert "## Bad Signature Detection" in content

    def test_generate_compliance_report_qa_integration(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)
        _write_qa_summary(
            manager,
            {
                "cases_total": 2,
                "cases_passed": 1,
                "cases_failed": 1,
                "results": [
                    {
                        "case_id": "QA-001",
                        "passed": False,
                        "summary": "Failure detail",
                    }
                ],
            },
        )

        content = generate_compliance_report(manager, run_qa=False)

        assert "QA-001: Failure detail" in content
        assert "50.00%" in content

    def test_generate_compliance_report_signature_detection(self, interface_workspace, fs) -> None:
        manager, _ = interface_workspace(run_id="run_compliance_signatures")
        create_interface_test_libraries(fs, run_id=manager.run_id)

        _write_spec_index(
            manager,
            "LIB-0001",
            [
                {
                    "element_id": "DTL-LIB-0001-0001",
                    "kind": "detail",
                    "section": "Details",
                    "text": "Refer to [F0001::INTRO] for context.",
                    "raw_line": "- DTL-LIB-0001-0001: Refer to [F0001::INTRO] for context.",
                    "citations": [],
                    "mentions_libs": [],
                }
            ],
        )

        content = generate_compliance_report(manager, run_qa=False)

        assert "legacy_pointer_format" in content

    def test_generate_compliance_report_no_qa_results(self, interface_workspace, fs) -> None:
        manager, _ = interface_workspace(run_id="run_compliance_no_qa")
        create_interface_test_libraries(fs, run_id=manager.run_id)

        content = generate_compliance_report(manager, run_qa=False)

        assert "## QA Validation Results" not in content

    def test_generate_compliance_report_markdown_format(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)
        _write_qa_summary(
            manager,
            {
                "cases_total": 1,
                "cases_passed": 1,
                "cases_failed": 0,
                "results": [],
            },
        )

        content = generate_compliance_report(manager, run_qa=False)

        assert _validate_markdown_table(
            content,
            ["Total Cases", "Passed", "Failed", "Pass Rate"],
        )
        assert _validate_markdown_table(
            content,
            ["Signature", "Count", "Description"],
        )


class TestDriftReport:
    def test_generate_drift_report_basic(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_drift_report(manager)

        report_path = manager.structure.reports_dir / "drift.md"
        assert report_path.exists()
        assert "## Uncovered Spec Elements" in content
        assert "## Failed/Blocked Tasks" in content
        assert "### Recommendations" in content

    def test_generate_drift_report_uncovered_elements(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_drift_report(manager)

        assert "DTL-LIB-0001-0002" in content

    def test_generate_drift_report_failed_tasks(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_drift_report(manager)

        assert "TASK-0002" in content
        assert "Tests failed." in content

    def test_generate_drift_report_uncovered_edges(self, interface_workspace, fs) -> None:
        manager, manifest = interface_workspace(run_id="run_drift_uncovered_edges")
        create_interface_test_libraries(fs, run_id=manager.run_id)
        create_task_planning_prerequisites(fs, manager.run_id, manifest)

        _write_tasks(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["DTL-LIB-0001-0001"],
                    "status": "done",
                    "with_patch": True,
                    "write_status": True,
                }
            ],
        )
        build_trace_indexes(manager.run_id)

        content = generate_drift_report(manager)

        assert "EDGE-LIB-0001-LIB-0003" in content

    def test_generate_drift_report_task_status_aggregation(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_drift_report(manager)

        header = "| Status | Count |"
        rows = _extract_table_rows(content, header)
        counts = {row[0]: int(row[1]) for row in rows if row}
        assert counts.get("done") == 1
        assert counts.get("failed") == 1
        assert counts.get("blocked") == 1

    def test_generate_drift_report_no_drift(self, interface_workspace, fs) -> None:
        manager, manifest = interface_workspace(run_id="run_drift_ok")
        create_interface_test_libraries(fs, run_id=manager.run_id)
        create_task_planning_prerequisites(fs, manager.run_id, manifest)

        _write_spec_index(
            manager,
            "LIB-0001",
            [
                {
                    "element_id": "DTL-LIB-0001-0001",
                    "kind": "detail",
                    "section": "Details",
                    "text": "Handle inbound requests.",
                    "raw_line": "- DTL-LIB-0001-0001: Handle inbound requests.",
                    "citations": ["[spec_snapshot/input.md::SEC-F0001-0001]"],
                    "mentions_libs": [],
                },
                {
                    "element_id": "DTL-LIB-0001-0002",
                    "kind": "detail",
                    "section": "Details",
                    "text": "Subscribe to events.",
                    "raw_line": "- DTL-LIB-0001-0002: Subscribe to events.",
                    "citations": ["[spec_snapshot/input.md::SEC-F0001-0001]"],
                    "mentions_libs": [],
                },
            ],
        )
        for lib_id in ["LIB-0002", "LIB-0003"]:
            _write_spec_index(manager, lib_id, [])

        # Cover all elements to make edges considered covered
        # Edge coverage is determined by whether edge's consumer/provider elements are covered
        _write_tasks(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["DTL-LIB-0001-0001", "DTL-LIB-0001-0002"],
                    "status": "done",
                    "with_patch": True,
                    "write_status": True,
                }
            ],
        )
        build_trace_indexes(manager.run_id)

        content = generate_drift_report(manager)

        assert "- overall_status: OK" in content
        assert "No immediate remediation required." in content

    def test_generate_drift_report_markdown_format(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_drift_report(manager)

        assert _validate_markdown_table(
            content,
            ["Element ID", "Library", "Kind"],
        )
        assert _validate_markdown_table(
            content,
            ["Task ID", "Status", "Details"],
        )


class TestRunAudit:
    def test_generate_run_audit_basic(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_run_audit(manager)

        report_path = manager.structure.audits_dir / "run_audit.md"
        assert report_path.exists()
        assert "## Phase Status" in content
        assert "## Library Summary" in content
        assert "## Task Summary" in content

    def test_generate_run_audit_phase_status(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)
        phase_result = manager.state.phases[Phase.INTERFACES.value]
        phase_result.status = PhaseStatus.COMPLETED
        phase_result.started_at = "2024-01-01T00:00:00"
        phase_result.completed_at = "2024-01-01T00:05:00"
        manager.save_state()

        content = generate_run_audit(manager)

        header = "| Phase | Status | Started At | Completed At | Duration |"
        rows = _extract_table_rows(content, header)
        assert rows
        assert any(row[0] == Phase.INTERFACES.value for row in rows)

    def test_generate_run_audit_library_metrics(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_run_audit(manager)

        header = "| Library | Elements | Open Decisions |"
        rows = _extract_table_rows(content, header)
        assert any(row[0] == "LIB-0001" for row in rows)

    def test_generate_run_audit_task_statistics(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_run_audit(manager)

        header = "| Status | Count |"
        rows = _extract_table_rows(content, header)
        counts = {row[0]: int(row[1]) for row in rows if row}
        assert counts.get("done") == 1
        assert counts.get("failed") == 1
        assert counts.get("blocked") == 1

    def test_generate_run_audit_artifact_links(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)
        generate_coverage_report(manager)
        generate_compliance_report(manager, run_qa=False)
        generate_drift_report(manager)

        content = generate_run_audit(manager)

        for artifact in [
            "../reports/coverage.md",
            "../reports/compliance.md",
            "../reports/drift.md",
            "../workspace/indexes/trace_index.json",
            "../workspace/indexes/interface_index.json",
        ]:
            assert artifact in content

    def test_generate_run_audit_markdown_format(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)

        content = generate_run_audit(manager)

        assert _validate_markdown_table(
            content,
            ["Phase", "Status", "Started At", "Completed At", "Duration"],
        )
        assert _validate_markdown_table(
            content,
            ["Library", "Elements", "Open Decisions"],
        )


class TestReportsIntegration:
    @pytest.mark.integration
    def test_all_reports_generated(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)
        generate_coverage_report(manager)
        generate_compliance_report(manager, run_qa=False)
        generate_drift_report(manager)
        generate_run_audit(manager)

        assert (manager.structure.reports_dir / "coverage.md").exists()
        assert (manager.structure.reports_dir / "compliance.md").exists()
        assert (manager.structure.reports_dir / "drift.md").exists()
        assert (manager.structure.audits_dir / "run_audit.md").exists()

    @pytest.mark.integration
    def test_reports_deterministic_output(self, interface_workspace, fs, monkeypatch) -> None:
        """Verify repeated report generation is stable with timestamps removed."""
        manager = _setup_finalize_prerequisites(interface_workspace, fs)
        _write_qa_summary(
            manager,
            {
                "cases_total": 1,
                "cases_passed": 1,
                "cases_failed": 0,
                "results": [],
            },
        )

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.reports._format_timestamp",
            lambda: "2024-01-01T00:00:00",
        )

        first = {
            "coverage": generate_coverage_report(manager),
            "compliance": generate_compliance_report(manager, run_qa=False),
            "drift": generate_drift_report(manager),
            "audit": generate_run_audit(manager),
        }

        second = {
            "coverage": generate_coverage_report(manager),
            "compliance": generate_compliance_report(manager, run_qa=False),
            "drift": generate_drift_report(manager),
            "audit": generate_run_audit(manager),
        }

        def strip_timestamps(content: str) -> str:
            return "\n".join(
                line for line in content.splitlines() if not line.startswith("- generated_at:")
            )

        assert {key: strip_timestamps(value) for key, value in first.items()} == {
            key: strip_timestamps(value) for key, value in second.items()
        }

    @pytest.mark.integration
    def test_reports_with_minimal_data(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_reports_minimal")

        generate_coverage_report(manager)
        generate_compliance_report(manager, run_qa=False)
        generate_drift_report(manager)
        generate_run_audit(manager)

        assert (manager.structure.reports_dir / "coverage.md").exists()
        assert (manager.structure.reports_dir / "compliance.md").exists()
        assert (manager.structure.reports_dir / "drift.md").exists()
        assert (manager.structure.audits_dir / "run_audit.md").exists()

    @pytest.mark.integration
    def test_reports_with_complete_data(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)
        generate_coverage_report(manager)
        generate_compliance_report(manager, run_qa=False)
        generate_drift_report(manager)
        generate_run_audit(manager)

        coverage = (manager.structure.reports_dir / "coverage.md").read_text(encoding="utf-8")
        compliance = (manager.structure.reports_dir / "compliance.md").read_text(encoding="utf-8")
        drift = (manager.structure.reports_dir / "drift.md").read_text(encoding="utf-8")
        audit = (manager.structure.audits_dir / "run_audit.md").read_text(encoding="utf-8")

        assert "## Section Coverage" in coverage
        assert (
            "## QA Validation Results" in compliance or "## Bad Signature Detection" in compliance
        )
        assert "## Uncovered Spec Elements" in drift
        assert "## Phase Status" in audit
        assert _validate_json_index(
            manager.structure.indexes_dir / "trace_index.json",
            {"run_id", "generated_at", "indexes"},
        )

    @pytest.mark.integration
    def test_report_file_permissions(self, interface_workspace, fs) -> None:
        manager = _setup_finalize_prerequisites(interface_workspace, fs)
        generate_coverage_report(manager)
        generate_compliance_report(manager, run_qa=False)
        generate_drift_report(manager)
        generate_run_audit(manager)

        report_paths = [
            manager.structure.reports_dir / "coverage.md",
            manager.structure.reports_dir / "compliance.md",
            manager.structure.reports_dir / "drift.md",
            manager.structure.audits_dir / "run_audit.md",
        ]
        for path in report_paths:
            content = path.read_text(encoding="utf-8")
            assert isinstance(content, str)
