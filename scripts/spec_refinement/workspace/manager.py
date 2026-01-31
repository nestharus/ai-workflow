"""Run-scoped workspace manager for spec refinement.

Agent Integration:
- glm-file-what-summarizer: Phase 1 file inventory extraction
- opus-library-synthesizer: Phase 2 library boundary detection
- See .agents/agents/ for full agent definitions
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.spec_refinement.core.gap import Gap, format_gap_markdown, parse_gaps_markdown
from scripts.spec_refinement.core.gap_queue import GapQueue

from .state import Phase, WorkspaceState


@dataclass
class RunFolderStructure:
    """Expected structure of a run folder."""

    run_id: str
    root: Path

    @property
    def manifest_dir(self) -> Path:
        """Path to the manifest directory."""
        return self.root / "manifest"

    @property
    def summaries_dir(self) -> Path:
        """Path to the summaries directory."""
        return self.root / "summaries"

    @property
    def libraries_dir(self) -> Path:
        """Path to the libraries directory."""
        return self.root / "libraries"

    @property
    def architecture_dir(self) -> Path:
        """Path to the architecture directory."""
        return self.root / "architecture"

    @property
    def tasks_dir(self) -> Path:
        """Path to the tasks directory."""
        return self.root / "tasks"

    @property
    def audits_dir(self) -> Path:
        """Path to the audits directory."""
        return self.root / "audits"

    @property
    def files_json(self) -> Path:
        """Path to the files manifest."""
        return self.manifest_dir / "files.json"

    @property
    def sections_json(self) -> Path:
        """Path to the sections manifest."""
        return self.manifest_dir / "sections.json"

    def validate(self) -> list[str]:
        """Validate run folder structure."""
        issues = []
        if not self.root.exists():
            issues.append(f"Run folder does not exist: {self.root}")
        return issues


@dataclass
class WorkspaceManager:
    """Manages the workspace for spec refinement."""

    run_id: str
    input_folder: Path
    state: WorkspaceState = field(init=False)
    structure: RunFolderStructure = field(init=False)

    def __post_init__(self) -> None:
        """Initialize the workspace structure and state after dataclass construction."""
        self.structure = RunFolderStructure(
            run_id=self.run_id,
            root=Path("runs") / self.run_id,
        )

        state_file = self.structure.root / "state.json"
        if state_file.exists():
            self.state = WorkspaceState.load(state_file)
        else:
            self.state = WorkspaceState(run_id=self.run_id, input_folder=str(self.input_folder))

    # --- Workspace Lifecycle ---

    def initialize(self, force: bool = False) -> list[str]:
        """Initialize the workspace."""
        issues: list[str] = []

        if not self.input_folder.exists():
            return [f"Input folder does not exist: {self.input_folder}"]

        if self.structure.root.exists() and force:
            shutil.rmtree(self.structure.root)

        self.structure.root.mkdir(parents=True, exist_ok=True)
        for subdir in [
            self.structure.manifest_dir,
            self.structure.summaries_dir,
            self.structure.libraries_dir,
            self.structure.architecture_dir,
            self.structure.tasks_dir,
            self.structure.audits_dir,
        ]:
            subdir.mkdir(parents=True, exist_ok=True)

        file_manifest = self._enumerate_files()
        if not file_manifest:
            issues.append(f"No markdown files found in: {self.input_folder}")

        section_manifest: dict[str, list[str]] = {}
        for file_id, file_path in file_manifest.items():
            sections = self._extract_section_labels(Path(file_path))
            section_manifest[file_id] = sections
            if not sections:
                issues.append(f"No section labels found in: {file_path}")

        self._write_manifest_files(file_manifest, section_manifest)

        self.state.run_id = self.run_id
        self.state.input_folder = str(self.input_folder)
        self.state.file_manifest = file_manifest
        self.state.section_manifest = section_manifest
        self._save_state()

        return issues

    def cleanup(self, keep_audits: bool = True) -> None:
        """Clean up the workspace, keeping manifest and state."""
        if not self.structure.root.exists():
            return

        for item in self.structure.root.iterdir():
            if item.name in {"manifest", "state.json"}:
                continue
            if keep_audits and item.name == "audits":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        self.state = WorkspaceState(run_id=self.run_id, input_folder=str(self.input_folder))
        if self.structure.files_json.exists():
            self.state.file_manifest = json.loads(
                self.structure.files_json.read_text(encoding="utf-8")
            )
        if self.structure.sections_json.exists():
            self.state.section_manifest = json.loads(
                self.structure.sections_json.read_text(encoding="utf-8")
            )
        self._save_state()

    def finalize(self) -> Path:
        """Finalize the workspace after successful processing."""
        if not self.state.is_complete():
            raise RuntimeError("Cannot finalize incomplete workspace")

        summary_path = self._generate_summary_report()

        archive_dir = self.structure.root / "archive"
        archive_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for file_id, path_str in self.state.file_manifest.items():
            src = Path(path_str)
            if src.exists():
                dst = archive_dir / f"{timestamp}_{file_id}_{src.name}"
                shutil.copy2(src, dst)

        return summary_path

    # --- Manifest Management ---

    def _enumerate_files(self) -> dict[str, str]:
        """Enumerate files in input folder and assign stable IDs."""
        files: dict[str, str] = {}
        for index, md_file in enumerate(sorted(self.input_folder.glob("*.md")), start=1):
            file_id = f"file_{index:03d}"
            files[file_id] = str(md_file)
        return files

    def _extract_section_labels(self, file_path: Path) -> list[str]:
        """Extract stable section labels from a file.

        Preference order:
        1) Explicit bracket labels like `[INTRO]` (assumed to be stable anchors).
        2) Markdown headings (as a fallback) normalized to `UPPER_SNAKE_CASE`.

        Returned labels are de-duplicated while preserving first-seen order.
        """
        import re

        content = file_path.read_text(encoding="utf-8")

        def _dedupe_keep_order(items: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for item in items:
                if item in seen:
                    continue
                seen.add(item)
                out.append(item)
            return out

        explicit = [match.group(1) for match in re.finditer(r"\[([A-Z_]+)\]", content)]
        explicit = [item.strip() for item in explicit if item and item.strip()]
        explicit = _dedupe_keep_order(explicit)
        if explicit:
            return explicit

        headings: list[str] = []
        for match in re.finditer(r"^##\s+(.+)$", content, re.MULTILINE):
            heading = match.group(1).strip()
            if not heading:
                continue
            headings.append(heading.upper().replace(" ", "_"))

        return _dedupe_keep_order(headings)

    def _write_manifest_files(
        self, file_manifest: dict[str, str], section_manifest: dict[str, list[str]]
    ) -> None:
        """Write manifest files to disk."""
        self.structure.manifest_dir.mkdir(parents=True, exist_ok=True)
        self.structure.files_json.write_text(json.dumps(file_manifest, indent=2), encoding="utf-8")
        self.structure.sections_json.write_text(
            json.dumps(section_manifest, indent=2), encoding="utf-8"
        )

    # --- Agent Interface ---

    def write_agent_input(self, phase: Phase, data: dict[str, Any]) -> Path:
        """Write input data for an agent."""
        import yaml

        phase_dir = self.structure.root / phase.value
        phase_dir.mkdir(parents=True, exist_ok=True)
        input_file = phase_dir / "agent_input.yaml"
        input_file.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
        return input_file

    def read_agent_output(self, phase: Phase) -> dict[str, Any] | None:
        """Read output data from an agent."""
        from typing import cast

        import yaml

        output_file = self.structure.root / phase.value / "agent_output.yaml"
        if not output_file.exists():
            return None
        return cast("dict[str, Any]", yaml.safe_load(output_file.read_text(encoding="utf-8")))

    def write_agent_output(self, phase: Phase, data: dict[str, Any]) -> Path:
        """Write output data from an agent."""
        import yaml

        phase_dir = self.structure.root / phase.value
        phase_dir.mkdir(parents=True, exist_ok=True)
        output_file = phase_dir / "agent_output.yaml"
        output_file.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
        return output_file

    # --- Phase Management ---

    def start_phase(self, phase: Phase) -> None:
        """Start a phase."""
        self.state.start_phase(phase)
        self._save_state()

    def complete_phase(self, phase: Phase, outputs: dict[str, Any] | None = None) -> None:
        """Complete a phase."""
        self.state.complete_phase(phase, outputs)
        self._save_state()

    def fail_phase(self, phase: Phase, error: str) -> None:
        """Mark a phase as failed."""
        self.state.fail_phase(phase, error)
        self._save_state()

    def get_next_phase(self) -> Phase | None:
        """Get the next phase to execute."""
        return self.state.get_next_phase()

    # --- Convenience Properties ---

    @property
    def workspace_path(self) -> Path:
        """Get the workspace directory path."""
        return self.structure.root

    @property
    def is_initialized(self) -> bool:
        """Check if workspace is initialized."""
        return self.structure.root.exists() and (self.structure.root / "state.json").exists()

    @property
    def is_complete(self) -> bool:
        """Check if all phases are complete."""
        return self.state.is_complete()

    # --- Manifest Access ---

    def get_file_path(self, file_id: str) -> Path | None:
        """Get file path for a file ID."""
        path_str = self.state.file_manifest.get(file_id)
        return Path(path_str) if path_str else None

    def get_section_labels(self, file_id: str) -> list[str]:
        """Get section labels for a file ID."""
        return self.state.section_manifest.get(file_id, [])

    def get_all_files(self) -> dict[str, Path]:
        """Get all files as {file_id: Path} mapping."""
        return {file_id: Path(path_str) for file_id, path_str in self.state.file_manifest.items()}

    def get_sublibrary_path(self, parent_lib_id: str, sub_lib_id: str) -> Path:
        """Get path to a sub-library directory."""
        return self.structure.libraries_dir / parent_lib_id / "sublibraries" / sub_lib_id

    def list_sublibraries(self, parent_lib_id: str) -> list[str]:
        """List all sub-libraries for a parent library."""
        sublibraries_dir = self.structure.libraries_dir / parent_lib_id / "sublibraries"
        if not sublibraries_dir.exists():
            return []
        return [d.name for d in sorted(sublibraries_dir.iterdir()) if d.is_dir()]

    def get_all_libraries_recursive(self) -> dict[str, Path]:
        """Get all libraries including sub-libraries as {lib_id: Path} mapping."""
        libraries: dict[str, Path] = {}

        def _traverse(current_dir: Path, prefix: str = "") -> None:
            lib_id = f"{prefix}{current_dir.name}" if prefix else current_dir.name
            libraries[lib_id] = current_dir

            sublibraries_dir = current_dir / "sublibraries"
            if sublibraries_dir.exists():
                for sub_dir in sorted(sublibraries_dir.iterdir()):
                    if sub_dir.is_dir():
                        _traverse(sub_dir, f"{lib_id}/")

        for lib_dir in sorted(self.structure.libraries_dir.iterdir()):
            if lib_dir.is_dir():
                _traverse(lib_dir)

        return libraries

    # --- Gap Management ---

    def write_library_gaps(self, lib_id: str, gaps: list[Gap]) -> Path:
        """Write gaps.md for a library."""
        lib_dir = self.structure.libraries_dir / lib_id
        lib_dir.mkdir(parents=True, exist_ok=True)
        gap_queue = self.get_library_gap_queue(lib_id)
        gap_queue.update(gaps)
        self.write_library_gap_queue(lib_id, gap_queue)
        metrics = gap_queue.get_coverage_metrics()
        gaps_path = lib_dir / "gaps.md"
        gaps_path.write_text(self.format_gaps_md(gaps, metrics), encoding="utf-8")
        return gaps_path

    def read_library_gaps(self, lib_id: str) -> list[Gap]:
        """Read gaps.md for a library."""
        gaps_path = self.structure.libraries_dir / lib_id / "gaps.md"
        if not gaps_path.exists():
            return []
        return parse_gaps_markdown(gaps_path.read_text(encoding="utf-8"))

    def write_task_gaps(self, task_id: str, gaps: list[Gap]) -> Path:
        """Write gaps.md for a task."""
        task_dir = self.structure.tasks_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        gaps_path = task_dir / "gaps.md"
        gaps_path.write_text(self.format_gaps_md(gaps, None), encoding="utf-8")
        return gaps_path

    def read_task_gaps(self, task_id: str) -> list[Gap]:
        """Read gaps.md for a task."""
        gaps_path = self.structure.tasks_dir / task_id / "gaps.md"
        if not gaps_path.exists():
            return []
        return parse_gaps_markdown(gaps_path.read_text(encoding="utf-8"))

    def get_all_gaps(self, run_id: str) -> dict[str, list[Gap]]:
        """Aggregate gaps across all libraries and tasks."""
        gaps: dict[str, list[Gap]] = {}
        if self.structure.libraries_dir.exists():
            for lib_dir in sorted(self.structure.libraries_dir.iterdir()):
                if not lib_dir.is_dir():
                    continue
                gaps_path = lib_dir / "gaps.md"
                if gaps_path.exists():
                    gaps[lib_dir.name] = self.read_library_gaps(lib_dir.name)
        if self.structure.tasks_dir.exists():
            for task_dir in sorted(self.structure.tasks_dir.iterdir()):
                if not task_dir.is_dir():
                    continue
                gaps_path = task_dir / "gaps.md"
                if gaps_path.exists():
                    gaps[task_dir.name] = self.read_task_gaps(task_dir.name)
        return gaps

    def record_gap_audit(
        self,
        phase: Phase,
        gaps: list[Gap],
        converged: bool,
        coverage_metrics: dict[str, Any] | None = None,
    ) -> None:
        """Record gap audit convergence stats for a phase."""
        result = self.state.phases[phase.value]
        result.gap_audit_iterations += 1
        result.gap_audit_converged = converged
        result.open_gaps_count = len([gap for gap in gaps if gap.status == "open"])
        if coverage_metrics is not None:
            result.coverage_metrics = coverage_metrics
        self._save_state()

    def get_gap_audit_status(self, phase: Phase) -> dict[str, Any]:
        """Get gap audit status for a phase."""
        result = self.state.phases[phase.value]
        return {
            "iterations": result.gap_audit_iterations,
            "converged": result.gap_audit_converged,
            "open_gaps_count": result.open_gaps_count,
        }

    @staticmethod
    def format_gaps_md(gaps: list[Gap], metrics: dict[str, Any] | None = None) -> str:
        """Format a list of gaps into markdown sections."""
        sections = [
            ("open", "Open Gaps"),
            ("integrated", "Integrated Gaps"),
            ("deferred", "Deferred Gaps"),
            ("rejected", "Rejected Gaps"),
        ]
        grouped: dict[str, list[Gap]] = {key: [] for key, _ in sections}
        for gap in gaps:
            grouped.setdefault(gap.status, []).append(gap)

        lines: list[str] = []
        if metrics is not None:
            total_gaps = metrics.get("total_gaps", len(gaps))
            open_gaps = metrics.get("open_gaps", len([gap for gap in gaps if gap.status == "open"]))
            closed_gaps = metrics.get(
                "closed_gaps", len([gap for gap in gaps if gap.status == "integrated"])
            )
            convergence_ratio = metrics.get(
                "convergence_ratio",
                (closed_gaps / total_gaps if total_gaps > 0 else 1.0),
            )
            lines.extend(
                [
                    "## Coverage Metrics",
                    "",
                    f"- **Total Gaps**: {total_gaps}",
                    f"- **Open Gaps**: {open_gaps}",
                    f"- **Closed Gaps**: {closed_gaps}",
                    f"- **Convergence Ratio**: {convergence_ratio:.2%}",
                    "",
                ]
            )
        for status, title in sections:
            lines.append(f"## {title}")
            lines.append("")
            for gap in grouped.get(status, []):
                lines.append(format_gap_markdown(gap))
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def get_library_gap_queue(self, lib_id: str) -> GapQueue:
        """Get gap queue for a library."""
        queue_path = self.structure.libraries_dir / lib_id / "gap_queue.json"
        if queue_path.exists():
            data = json.loads(queue_path.read_text(encoding="utf-8"))
            return GapQueue.from_dict(data)
        return GapQueue(gaps=self.read_library_gaps(lib_id))

    def write_library_gap_queue(self, lib_id: str, queue: GapQueue) -> Path:
        """Write gap queue for a library."""
        lib_dir = self.structure.libraries_dir / lib_id
        lib_dir.mkdir(parents=True, exist_ok=True)
        queue_path = lib_dir / "gap_queue.json"
        queue_path.write_text(json.dumps(queue.to_dict(), indent=2), encoding="utf-8")
        return queue_path

    def get_gap_coverage_metrics(self, lib_id: str) -> dict[str, Any]:
        """Get gap coverage metrics for a library."""
        queue = self.get_library_gap_queue(lib_id)
        return queue.get_coverage_metrics()

    def _save_state(self) -> None:
        """Save current state to disk."""
        state_file = self.structure.root / "state.json"
        self.state.save(state_file)

    def _generate_summary_report(self) -> Path:
        """Generate a summary report of the run."""
        report_path = self.structure.summaries_dir / "summary.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# Spec Refinement Summary",
            "",
            f"**Run ID**: `{self.run_id}`",
            f"**Input Folder**: `{self.input_folder}`",
            f"**Generated**: {datetime.now().isoformat()}",
            "",
            "## Phase Results",
            "",
        ]

        for phase in Phase:
            result = self.state.phases[phase.value]
            lines.append(f"### {phase.value.title()}")
            lines.append("")
            lines.append(f"- **Status**: {result.status.value}")
            if result.started_at:
                lines.append(f"- **Started**: {result.started_at}")
            if result.completed_at:
                lines.append(f"- **Completed**: {result.completed_at}")
            if result.error:
                lines.append(f"- **Error**: {result.error}")
            if result.issues:
                lines.append(f"- **Issues**: {len(result.issues)}")
            lines.append("")

        lines.append("## Files")
        lines.append("")
        for file_id, file_path in self.state.file_manifest.items():
            lines.append(f"- `{file_id}`: `{file_path}`")
        if not self.state.file_manifest:
            lines.append("- *No files recorded*")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path
