"""Workspace manager for spec processing.

Manages the .workspace/ directory within a spec folder, providing:
- Workspace initialization and cleanup
- State persistence
- Agent input/output file management
- Report generation

The reports/ subdirectory contains:
- summary.md: Overall processing summary
- {phase}_report.md: Per-phase detailed reports
- migration.log: JSON Lines log of schema migration events
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .state import Phase, PhaseStatus, WorkspaceState


@dataclass
class SpecFolderStructure:
    """Expected structure of a spec folder."""

    root: Path

    @property
    def libraries_dir(self) -> Path:
        """Path to the libraries directory."""
        return self.root / "libraries"

    @property
    def patches_dir(self) -> Path:
        """Path to the patches directory."""
        return self.root / "patches"

    @property
    def inputs_dir(self) -> Path:
        """Path to the inputs directory."""
        return self.root / "inputs"

    @property
    def gaps_md(self) -> Path:
        """Path to the gaps.md file."""
        return self.root / "gaps.md"

    @property
    def plan_md(self) -> Path:
        """Path to the plan.md file."""
        return self.root / "plan.md"

    @property
    def pattern_spec_md(self) -> Path:
        """Path to the pattern_spec.md file."""
        return self.root / "pattern_spec.md"

    @property
    def workspace_dir(self) -> Path:
        """Path to the .workspace directory."""
        return self.root / ".workspace"

    def validate(self) -> list[str]:
        """Validate the spec folder structure. Returns list of issues."""
        issues = []

        if not self.root.exists():
            issues.append(f"Spec folder does not exist: {self.root}")
            return issues

        # libraries/ is optional - will be created by discovery phase
        # Just need at least one input source (patches/, plan.md, or inputs/)
        has_input = self.patches_dir.exists() or self.plan_md.exists() or self.inputs_dir.exists()
        if not has_input:
            issues.append("No input found: need patches/, plan.md, or inputs/")

        return issues


@dataclass
class WorkspaceManager:
    """Manages the workspace for spec processing.

    The workspace is a .workspace/ directory within the spec folder that contains:
    - state.json: Persistent state across phases
    - agent_input.yaml: Input for current agent
    - agent_output.yaml: Output from current agent
    - reports/: Generated reports including migration.log
    - cleaning/: Cleaning phase intermediate files
    - discovery/: Discovery phase intermediate files
    - review/: Review phase intermediate files
    - finalization/: Finalization phase intermediate files

    Migration Log:
        When loading state.json, schema version is detected and migration events
        are logged to reports/migration.log in JSON Lines format. Use
        `get_migration_log_path()` to get the log file path and
        `read_migration_log()` to parse and retrieve migration events.
    """

    spec_folder: Path
    state: WorkspaceState = field(init=False)
    structure: SpecFolderStructure = field(init=False)

    def __post_init__(self) -> None:
        """Initialize the workspace structure and state after dataclass construction."""
        self.structure = SpecFolderStructure(self.spec_folder)
        self._workspace = self.structure.workspace_dir

        # Load or create state
        state_file = self._workspace / "state.json"
        if state_file.exists():
            self.state = WorkspaceState.load(state_file)
        else:
            self.state = WorkspaceState(spec_folder=str(self.spec_folder))

    # --- Workspace Lifecycle ---

    def initialize(self, force: bool = False) -> list[str]:
        """Initialize the workspace.

        Args:
            force: If True, clear existing workspace

        Returns:
            List of validation issues (empty if valid)
        """
        # Validate spec folder structure
        issues = self.structure.validate()
        if issues:
            return issues

        # Create workspace directory
        if self._workspace.exists() and force:
            shutil.rmtree(self._workspace)

        self._workspace.mkdir(exist_ok=True)

        # Create subdirectories
        for subdir in ["reports", "cleaning", "discovery", "review", "finalization"]:
            (self._workspace / subdir).mkdir(exist_ok=True)

        # Find input files (patches, plan.md, inputs/)
        self.state.inputs = self._discover_inputs()

        # Save initial state
        self._save_state()

        return []

    def cleanup(self, keep_reports: bool = True) -> None:
        """Clean up the workspace.

        Args:
            keep_reports: If True, preserve the reports/ directory
        """
        if not self._workspace.exists():
            return

        for item in self._workspace.iterdir():
            if keep_reports and item.name == "reports":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        # Reinitialize state
        self.state = WorkspaceState(spec_folder=str(self.spec_folder))
        self._save_state()

    def finalize(self) -> None:
        """Finalize the workspace after successful processing.

        - Moves processed inputs to archive
        - Generates final report
        - Cleans up intermediate files
        """
        if not self.state.is_complete():
            raise RuntimeError("Cannot finalize incomplete workspace")

        # Generate final report
        self.generate_summary_report()

        # Archive processed inputs
        archive_dir = self._workspace / "archive"
        archive_dir.mkdir(exist_ok=True)

        for input_path in self.state.processed:
            src = Path(input_path)
            if src.exists():
                dst = archive_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{src.name}"
                shutil.move(str(src), str(dst))

        # Clean up intermediate files
        for subdir in ["cleaning", "discovery", "review", "finalization"]:
            subdir_path = self._workspace / subdir
            if subdir_path.exists():
                shutil.rmtree(subdir_path)
                subdir_path.mkdir()

    def _discover_inputs(self) -> list[str]:
        """Discover input files to process."""
        inputs = []

        # Check for any .md files in root (plan.md or any other)
        for md_file in sorted(self.structure.root.glob("*.md")):
            # Skip registry files
            if md_file.name in ("libs.md", "gaps.md", "pattern_spec.md"):
                continue
            inputs.append(str(md_file))

        # Check patches directory - sort by patch number
        if self.structure.patches_dir.exists():
            patches = list(self.structure.patches_dir.glob("*.md"))
            patches, ambiguous = self._sort_patches_with_ambiguity(patches)
            for patch in patches:
                inputs.append(str(patch))
            # Store ambiguous files in state for later resolution
            if ambiguous:
                self.state.ambiguous_inputs.extend([str(p) for p in ambiguous])

        # Check inputs directory
        if self.structure.inputs_dir.exists():
            input_files = list(self.structure.inputs_dir.glob("*.md"))
            sorted_inputs, ambiguous = self._sort_patches_with_ambiguity(input_files)
            for input_file in sorted_inputs:
                inputs.append(str(input_file))
            if ambiguous:
                self.state.ambiguous_inputs.extend([str(p) for p in ambiguous])

        return inputs

    def _sort_patches_with_ambiguity(self, patches: list[Path]) -> tuple[list[Path], list[Path]]:
        """Sort patch files by sequence number, detecting ambiguous ordering.

        Returns:
            (sorted_sequential, ambiguous) - sequential files sorted, ambiguous files separate
        """
        import re

        sequential = []
        ambiguous = []

        for path in patches:
            name = path.stem.lower()
            # Try patterns: p1, p2, patch1, patch-1, patch_1, 001, etc.
            match = re.search(r"(\d+)", name)
            if match:
                sequential.append((int(match.group(1)), name, path))
            else:
                # No number found - ambiguous
                ambiguous.append(path)

        # Sort sequential by number
        sequential.sort(key=lambda x: (x[0], x[1]))
        sorted_paths = [p[2] for p in sequential]

        return sorted_paths, ambiguous

    def _sort_patches(self, patches: list[Path]) -> list[Path]:
        """Sort patch files by sequence number (legacy method)."""
        sorted_patches, _ = self._sort_patches_with_ambiguity(patches)
        return sorted_patches

    def has_ambiguous_ordering(self) -> bool:
        """Check if there are files with ambiguous ordering."""
        return len(self.state.ambiguous_inputs) > 0

    def get_ambiguous_inputs(self) -> list[str]:
        """Get list of inputs with ambiguous ordering."""
        return self.state.ambiguous_inputs

    def set_input_order(self, ordered_inputs: list[str]) -> None:
        """Set the order of inputs after user clarification.

        Args:
            ordered_inputs: Full list of inputs in desired order
        """
        self.state.inputs = ordered_inputs
        self.state.ambiguous_inputs = []  # Clear after resolution
        self._save_state()

    def get_ordered_patches(self) -> list[Path]:
        """Get patch files in correct application order.

        Returns:
            List of patch file paths sorted by sequence number
        """
        if not self.structure.patches_dir.exists():
            return []

        patches = list(self.structure.patches_dir.glob("*.md"))
        return self._sort_patches(patches)

    def get_combined_content(self) -> str:
        """Get combined content from all inputs in order.

        This is the "canonical spec" that represents the current state
        after applying all inputs sequentially.

        Returns:
            Combined markdown content
        """
        parts = []

        # Process all inputs in order (already sorted in state.inputs)
        for input_path in self.state.inputs:
            path = Path(input_path)
            if path.exists():
                content = path.read_text(encoding="utf-8")
                parts.append(f"# === Source: {path.name} ===\n\n{content}")

        return "\n\n".join(parts)

    def get_all_input_content(self) -> dict[str, str]:
        """Get content from all input files keyed by filename.

        Returns:
            Dict mapping filename to content
        """
        result = {}

        for input_path in self.state.inputs:
            path = Path(input_path)
            if path.exists():
                result[path.name] = path.read_text(encoding="utf-8")

        return result

    def get_library_content(self) -> str:
        """Get combined content from all library files.

        This is the content that should be scanned for gaps - the actual
        spec content that has been organized into libraries.

        Returns:
            Combined markdown content from all libraries
        """
        parts = []

        if self.structure.libraries_dir.exists():
            for lib_file in sorted(self.structure.libraries_dir.glob("*.md")):
                content = lib_file.read_text(encoding="utf-8")
                parts.append(f"# === Library: {lib_file.name} ===\n\n{content}")

        return "\n\n".join(parts)

    def _save_state(self) -> None:
        """Save current state to disk."""
        state_file = self._workspace / "state.json"
        self.state.save(state_file)

    # --- Agent Interface ---

    def write_agent_input(self, phase: Phase, data: dict[str, Any]) -> Path:
        """Write input data for an agent.

        Args:
            phase: The phase this agent is executing
            data: Input data for the agent

        Returns:
            Path to the input file
        """
        import yaml

        phase_dir = self._workspace / phase.value
        phase_dir.mkdir(exist_ok=True)

        input_file = phase_dir / "agent_input.yaml"
        input_file.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")

        return input_file

    def read_agent_output(self, phase: Phase) -> dict[str, Any] | None:
        """Read output data from an agent.

        Args:
            phase: The phase the agent executed

        Returns:
            Output data or None if not found
        """
        import yaml

        output_file = self._workspace / phase.value / "agent_output.yaml"
        if not output_file.exists():
            return None

        return yaml.safe_load(output_file.read_text(encoding="utf-8"))

    def write_agent_output(self, phase: Phase, data: dict[str, Any]) -> Path:
        """Write output data from an agent (for agents to call).

        Args:
            phase: The phase this agent executed
            data: Output data from the agent

        Returns:
            Path to the output file
        """
        import yaml

        phase_dir = self._workspace / phase.value
        phase_dir.mkdir(exist_ok=True)

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

    def can_proceed(self) -> tuple[bool, str | None]:
        """Check if processing can proceed.

        Returns:
            (can_proceed, blocking_reason)
        """
        # Check for validation issues from cleaning
        cleaning_issues = self.state.get_phase_issues(Phase.CLEANING)
        blocking = [i for i in cleaning_issues if i.get("severity") == "error"]
        if blocking:
            return False, f"Blocking cleaning issues: {len(blocking)}"

        # Check for conflicts from discovery
        discovery_issues = self.state.get_phase_issues(Phase.DISCOVERY)
        conflicts = [i for i in discovery_issues if i.get("type") == "conflict"]
        if conflicts:
            return False, f"Unresolved conflicts: {len(conflicts)}"

        return True, None

    # --- Report Generation ---

    def generate_summary_report(self) -> Path:
        """Generate a summary report of the processing."""
        report_path = self._workspace / "reports" / "summary.md"
        report_path.parent.mkdir(exist_ok=True)

        lines = [
            "# Spec Processing Summary",
            "",
            f"**Spec Folder**: `{self.spec_folder}`",
            f"**Generated**: {datetime.now().isoformat()}",
            "",
            "## Phase Results",
            "",
        ]

        for phase in Phase:
            result = self.state.phases[phase.value]
            status_icon = {
                PhaseStatus.COMPLETED: "✅",
                PhaseStatus.FAILED: "❌",
                PhaseStatus.IN_PROGRESS: "🔄",
                PhaseStatus.SKIPPED: "⏭️",
                PhaseStatus.NOT_STARTED: "⏸️",
            }.get(result.status, "❓")

            lines.append(f"### {status_icon} {phase.value.title()}")
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

        # Inputs processed
        lines.append("## Inputs Processed")
        lines.append("")
        for input_path in self.state.processed:
            lines.append(f"- `{input_path}`")
        if not self.state.processed:
            lines.append("- *No inputs processed yet*")
        lines.append("")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    def generate_phase_report(self, phase: Phase) -> Path:
        """Generate a detailed report for a specific phase."""
        report_path = self._workspace / "reports" / f"{phase.value}_report.md"
        report_path.parent.mkdir(exist_ok=True)

        result = self.state.phases[phase.value]

        lines = [
            f"# {phase.value.title()} Phase Report",
            "",
            f"**Status**: {result.status.value}",
            "",
        ]

        if result.started_at:
            lines.append(f"**Started**: {result.started_at}")
        if result.completed_at:
            lines.append(f"**Completed**: {result.completed_at}")
        lines.append("")

        if result.error:
            lines.append("## Error")
            lines.append("")
            lines.append(f"```\n{result.error}\n```")
            lines.append("")

        if result.outputs:
            lines.append("## Outputs")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(result.outputs, indent=2))
            lines.append("```")
            lines.append("")

        if result.issues:
            lines.append("## Issues")
            lines.append("")
            for issue in result.issues:
                severity = issue.get("severity", "info")
                icon = {"error": "X", "warning": "! ", "info": "i "}.get(severity, "*")
                lines.append(f"- {icon} {issue.get('message', str(issue))}")
            lines.append("")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    # --- Convenience Properties ---

    @property
    def workspace_path(self) -> Path:
        """Get the workspace directory path."""
        return self._workspace

    @property
    def is_initialized(self) -> bool:
        """Check if workspace is initialized."""
        return self._workspace.exists() and (self._workspace / "state.json").exists()

    @property
    def is_complete(self) -> bool:
        """Check if all phases are complete."""
        return self.state.is_complete()

    # --- Migration Log Access ---

    def get_migration_log_path(self) -> Path:
        """Get the path to the migration log file.

        Returns:
            Path to `.workspace/reports/migration.log`.
        """
        return self._workspace / "reports" / "migration.log"

    def read_migration_log(self) -> list[dict[str, Any]]:
        """Read and parse the migration log file.

        Reads the migration.log file line by line, parsing each line as JSON.
        Malformed lines are skipped with a warning logged.

        Returns:
            List of migration event dictionaries. Returns empty list if
            the log file doesn't exist.
        """
        import logging

        migration_log = self.get_migration_log_path()
        if not migration_log.exists():
            return []

        entries = []
        with migration_log.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logging.warning(
                        "Malformed JSON at line %d in migration.log, skipping",
                        line_num,
                    )
        return entries
