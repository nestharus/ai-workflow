"""Workflow integration for real spec refinement evaluation.

Bridges sequence specs to actual workspace workflows, allowing evaluation
against real extraction rather than simulated results.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.inputs.sequence_spec import SequenceSpec
from spec_manager.refinement.workspace import WorkspaceManager

# Mapping from eval phase names to PDD Phase enum values.
# The eval uses 8 simplified names; the PDD system uses 11 phases.
# Each eval phase maps to the closest PDD phase(s).
_EVAL_TO_PDD_PHASES: dict[str, list[str]] = {
    "sectionization": ["structure"],
    "summarization": ["structure"],
    "library_synthesis": ["library"],
    "evidence_expansion": ["spec_build"],
    "spec_building": ["spec_build"],
    "architecture": ["cross_library", "projection"],
    "interfaces": ["cross_library"],
    "tasks": ["task_planning"],
}


@dataclass
class WorkspaceIntegration:
    """Bridge between sequence specs and workspace workflows.

    Creates temporary workspaces from specs, runs actual phase workflows,
    and extracts outputs for evaluation comparison.

    Attributes:
        temp_dir: Optional custom temp directory. If None, uses system temp.
        cleanup_on_exit: Whether to clean up workspaces after extraction.
        created_workspaces: List of workspace paths created (for cleanup).
        use_pdd: If True, dispatch to PDD orchestrator instead of refinement workflows.
    """

    temp_dir: Path | None = None
    cleanup_on_exit: bool = True
    created_workspaces: list[Path] = field(default_factory=list)
    use_pdd: bool = False

    def create_workspace_from_spec(self, spec: SequenceSpec) -> WorkspaceManager:
        """Create a workspace and populate spec_snapshot with spec content.

        Converts a SequenceSpec into a workspace that can be processed by
        the actual refinement workflows. The spec sections are written as
        markdown files in the spec_snapshot directory.

        Args:
            spec: The sequence spec to convert.

        Returns:
            WorkspaceManager initialized with the spec content.
        """
        # Create a temporary directory for the input folder
        base_dir = self.temp_dir or Path(tempfile.gettempdir())
        base_dir.mkdir(parents=True, exist_ok=True)

        input_folder = base_dir / f"spec_input_{spec.spec_id}_{uuid.uuid4().hex[:8]}"
        input_folder.mkdir(parents=True, exist_ok=True)

        # Write spec content as markdown files
        self._write_spec_to_input_folder(spec, input_folder)

        # Create workspace manager
        run_id = f"eval_{spec.spec_id}_{uuid.uuid4().hex[:8]}"
        manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)

        # Initialize the workspace
        issues = manager.initialize(force=True)
        if issues:
            # Log issues but continue - some may be warnings
            for issue in issues:
                if "error" in issue.lower():
                    raise RuntimeError(f"Workspace initialization failed: {issue}")

        # Track for cleanup
        self.created_workspaces.append(manager.workspace_path)
        self.created_workspaces.append(input_folder)

        return manager

    def _write_spec_to_input_folder(self, spec: SequenceSpec, input_folder: Path) -> None:
        """Write spec sections to the input folder as markdown files.

        Args:
            spec: The sequence spec containing sections.
            input_folder: Directory to write files to.
        """
        # Write the full spec as a single markdown file
        main_file = input_folder / f"{spec.spec_id}.md"
        main_file.write_text(spec.to_markdown(), encoding="utf-8")

        # Also write individual section files for finer-grained testing
        sections_dir = input_folder / "sections"
        sections_dir.mkdir(exist_ok=True)

        for section_label, content in spec.sections.items():
            section_file = sections_dir / f"{section_label.lower().replace(' ', '_')}.md"
            section_file.write_text(
                f"# {section_label}\n\n{content}\n",
                encoding="utf-8",
            )

        # Write rules as a separate file
        if spec.rules:
            rules_file = input_folder / "rules.md"
            rules_lines = ["# Rules\n"]
            for rule in spec.rules:
                rules_lines.append(f"\n## {rule.rule_id}: {rule.rule_type.upper()}\n")
                rules_lines.append(f"\n{rule.description}\n")
                if rule.formal_expression:
                    rules_lines.append(f"\n**Formula:** `{rule.formal_expression}`\n")
                if rule.dependencies:
                    deps = ", ".join(rule.dependencies)
                    rules_lines.append(f"\n**Depends on:** {deps}\n")
                if rule.examples:
                    rules_lines.append("\n**Examples:**\n")
                    for inp, out in rule.examples:
                        rules_lines.append(f"- f({inp}) = {out}\n")
            rules_file.write_text("".join(rules_lines), encoding="utf-8")

    def extract_phase_outputs(self, manager: WorkspaceManager, phase: str) -> list[str]:
        """Extract actual outputs from workspace for a phase.

        Reads the workspace structure directories to find outputs produced
        by the phase workflow.

        Args:
            manager: WorkspaceManager with completed phase.
            phase: Phase name to extract outputs from.

        Returns:
            List of extracted output strings (requirements, sections, etc.).
        """
        outputs: list[str] = []

        if phase == "sectionization":
            outputs = self._extract_sectionization_outputs(manager)
        elif phase == "summarization":
            outputs = self._extract_summarization_outputs(manager)
        elif phase == "library_synthesis":
            outputs = self._extract_library_synthesis_outputs(manager)
        elif phase == "evidence_expansion":
            outputs = self._extract_evidence_expansion_outputs(manager)
        elif phase == "spec_building":
            outputs = self._extract_spec_building_outputs(manager)
        elif phase == "architecture":
            outputs = self._extract_architecture_outputs(manager)
        elif phase == "interfaces":
            outputs = self._extract_interfaces_outputs(manager)
        elif phase == "tasks":
            outputs = self._extract_tasks_outputs(manager)

        return outputs

    def _extract_sectionization_outputs(self, manager: WorkspaceManager) -> list[str]:
        """Extract section labels from sectionization phase outputs.

        Only extracts human-readable section labels, not generated IDs
        (like SEC-F0001-0001) which would inflate the count vs ground truth.

        Args:
            manager: WorkspaceManager with sectionization completed.

        Returns:
            List of section label strings.
        """
        import json

        outputs: list[str] = []

        # Check manifest-level sections.json (aggregated section labels per file)
        sections_json = manager.structure.manifest_dir / "sections.json"
        if sections_json.exists():
            try:
                data = json.loads(sections_json.read_text(encoding="utf-8"))
                # sections.json is {file_id: [section_labels, ...]}
                for _file_id, section_labels in data.items():
                    if isinstance(section_labels, list):
                        outputs.extend(section_labels)
            except (json.JSONDecodeError, OSError):
                pass

        # If aggregated sections found, use those (avoid duplicates from per-file)
        if outputs:
            return sorted(set(outputs))

        # Fallback: extract labels from per-file sections
        sections_dir = manager.structure.manifest_sections_dir
        if sections_dir.exists():
            for sections_file in sections_dir.glob("*.sections.json"):
                try:
                    data = json.loads(sections_file.read_text(encoding="utf-8"))
                    for section in data.get("sections", []):
                        label = section.get("label")
                        if label:
                            outputs.append(label)
                except (json.JSONDecodeError, OSError):
                    continue

        return sorted(set(outputs))

    # Standard structural headings used in every summary file
    _STRUCTURAL_HEADINGS = frozenset(
        {
            "algorithms",
            "components",
            "workflows",
            "candidate responsibilities",
            "dependencies",
            "evidence map",
        }
    )

    def _extract_summarization_outputs(self, manager: WorkspaceManager) -> list[str]:
        """Extract summary content from summarization phase outputs.

        Prefers library-level summaries (``libraries_summary.md``) when
        available, since summarization ground truth typically expects
        per-library descriptions rather than raw section fragments.
        Falls back to all summary files if no library summary exists.

        Args:
            manager: WorkspaceManager with summarization completed.

        Returns:
            List of summary strings.
        """
        outputs: list[str] = []
        summaries_dir = manager.structure.summaries_dir

        if not summaries_dir.exists():
            return outputs

        # Extract from all summary files
        for summary_file in summaries_dir.glob("*.md"):
            try:
                content = summary_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    stripped = line.strip()
                    # Skip structural headings (always the same across files)
                    if stripped.startswith("## "):
                        continue
                    # Skip top-level file summary header
                    if stripped.startswith("# "):
                        continue
                    # Extract bullet points - take the key phrase before any pipe
                    if stripped.startswith("- ") or stripped.startswith("* "):
                        text = stripped[2:].strip()
                        # Strip "| Evidence: ..." and "| Description ..." suffixes
                        if " | " in text:
                            text = text.split(" | ")[0].strip()
                        if text and len(text) > 5:
                            outputs.append(text)
            except OSError:
                continue

        return outputs

    def _extract_library_synthesis_outputs(self, manager: WorkspaceManager) -> list[str]:
        """Extract library definitions from library synthesis phase outputs.

        Extracts charter intents and responsibility bullet points (not
        auto-generated library IDs like LIB-0001 which would inflate
        spurious counts).

        Args:
            manager: WorkspaceManager with library synthesis completed.

        Returns:
            List of library-related strings (intents, responsibilities).
        """
        outputs: list[str] = []
        libraries_dir = manager.structure.libraries_dir

        if not libraries_dir.exists():
            return outputs

        for lib_dir in libraries_dir.iterdir():
            if not lib_dir.is_dir():
                continue

            # Emit library directory name (matches expected library names)
            outputs.append(lib_dir.name)

            # Extract charter content (skip library IDs - they're auto-generated)
            charter_path = lib_dir / "charter.md"
            if charter_path.exists():
                try:
                    content = charter_path.read_text(encoding="utf-8")
                    current_section = ""
                    for line in content.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("## ") or stripped.startswith("#### "):
                            current_section = stripped.lstrip("#").strip()
                            continue
                        if current_section == "Intent" and stripped:
                            outputs.append(stripped)
                        elif current_section == "Responsibilities" and (
                            stripped.startswith("- ") or stripped.startswith("* ")
                        ):
                            outputs.append(stripped[2:].strip())
                except OSError:
                    continue

        return outputs

    def _extract_evidence_expansion_outputs(self, manager: WorkspaceManager) -> list[str]:
        """Extract evidence mappings from evidence expansion phase outputs.

        Args:
            manager: WorkspaceManager with evidence expansion completed.

        Returns:
            List of evidence-related strings.
        """
        outputs: list[str] = []
        libraries_dir = manager.structure.libraries_dir

        if not libraries_dir.exists():
            return outputs

        for lib_dir in libraries_dir.iterdir():
            if not lib_dir.is_dir():
                continue

            evidence_dir = lib_dir / "evidence"
            if evidence_dir.exists():
                for evidence_file in evidence_dir.glob("*.md"):
                    try:
                        content = evidence_file.read_text(encoding="utf-8")
                        # Extract section references and key points
                        for line in content.splitlines():
                            stripped = line.strip()
                            if stripped.startswith("## "):
                                outputs.append(stripped[3:].strip())
                            elif stripped.startswith("- ") or stripped.startswith("* "):
                                outputs.append(stripped[2:].strip())
                    except OSError:
                        continue

        return outputs

    def _extract_spec_building_outputs(self, manager: WorkspaceManager) -> list[str]:
        """Extract requirements from spec building phase outputs.

        Strips evidence citation pointers (``[spec_snapshot/...]``) from
        bullet items so the remaining text can be fuzzy-matched against
        ground truth requirements.

        Args:
            manager: WorkspaceManager with spec building completed.

        Returns:
            List of requirement strings.
        """
        import re

        citation_re = re.compile(r"\[spec_snapshot/[^\]]+\]")

        outputs: list[str] = []
        libraries_dir = manager.structure.libraries_dir

        if not libraries_dir.exists():
            return outputs

        for lib_dir in libraries_dir.iterdir():
            if not lib_dir.is_dir():
                continue

            spec_path = lib_dir / "spec.md"
            if spec_path.exists():
                try:
                    content = spec_path.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("- ") or stripped.startswith("* "):
                            text = stripped[2:].strip()
                            # Remove citation pointers
                            text = citation_re.sub("", text).strip()
                            if text and len(text) > 10:
                                outputs.append(text)
                except OSError:
                    continue

        return outputs

    def _extract_architecture_outputs(self, manager: WorkspaceManager) -> list[str]:
        """Extract architecture decisions from architecture phase outputs.

        Args:
            manager: WorkspaceManager with architecture completed.

        Returns:
            List of architecture decision strings.
        """
        outputs: list[str] = []
        architecture_dir = manager.structure.architecture_dir

        if not architecture_dir.exists():
            return outputs

        for arch_file in architecture_dir.glob("*.md"):
            try:
                content = arch_file.read_text(encoding="utf-8")
                # Extract decision headers and key points
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("## ") or stripped.startswith("### "):
                        # Extract header text (strip #)
                        header = stripped.lstrip("#").strip()
                        if header:
                            outputs.append(header)
                    elif stripped.startswith("- ") or stripped.startswith("* "):
                        text = stripped[2:].strip()
                        if len(text) > 10:
                            outputs.append(text)
            except OSError:
                continue

        return outputs

    def _extract_interfaces_outputs(self, manager: WorkspaceManager) -> list[str]:
        """Extract interface definitions from interfaces phase outputs.

        Args:
            manager: WorkspaceManager with interfaces completed.

        Returns:
            List of interface element strings.
        """
        import json

        outputs: list[str] = []
        libraries_dir = manager.structure.libraries_dir

        if not libraries_dir.exists():
            return outputs

        for lib_dir in libraries_dir.iterdir():
            if not lib_dir.is_dir():
                continue

            interfaces_dir = lib_dir / "interfaces"
            if interfaces_dir.exists():
                # Extract from JSON contracts
                for contract_file in interfaces_dir.glob("*.json"):
                    try:
                        data = json.loads(contract_file.read_text(encoding="utf-8"))
                        # Extract contract names and elements
                        if "name" in data:
                            outputs.append(data["name"])
                        if "elements" in data and isinstance(data["elements"], list):
                            for elem in data["elements"]:
                                if isinstance(elem, str):
                                    outputs.append(elem)
                                elif isinstance(elem, dict) and "name" in elem:
                                    outputs.append(elem["name"])
                    except (json.JSONDecodeError, OSError):
                        continue

                # Extract from markdown contracts
                for contract_file in interfaces_dir.glob("*.md"):
                    try:
                        content = contract_file.read_text(encoding="utf-8")
                        for line in content.splitlines():
                            stripped = line.strip()
                            if stripped.startswith("## "):
                                outputs.append(stripped[3:].strip())
                    except OSError:
                        continue

        return outputs

    def _extract_tasks_outputs(self, manager: WorkspaceManager) -> list[str]:
        """Extract task definitions from tasks phase outputs.

        Args:
            manager: WorkspaceManager with tasks completed.

        Returns:
            List of task-related strings.
        """
        outputs: list[str] = []
        tasks_dir = manager.structure.tasks_dir

        if not tasks_dir.exists():
            return outputs

        for task_file in tasks_dir.glob("*.md"):
            try:
                content = task_file.read_text(encoding="utf-8")
                # Extract task title (first # header)
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("# "):
                        outputs.append(stripped[2:].strip())
                        break
            except OSError:
                continue

        # Also check for task directories
        for task_dir in tasks_dir.iterdir():
            if task_dir.is_dir():
                outputs.append(task_dir.name)
                task_md = task_dir / "task.md"
                if task_md.exists():
                    try:
                        content = task_md.read_text(encoding="utf-8")
                        for line in content.splitlines():
                            stripped = line.strip()
                            if stripped.startswith("# "):
                                outputs.append(stripped[2:].strip())
                                break
                    except OSError:
                        continue

        return outputs

    def _build_error_message(self, result: dict[str, Any]) -> str | None:
        """Build error message from workflow result errors and issues.

        Combines both 'errors' and 'issues' fields from workflow results into
        a single error message. Some workflows populate one or the other.

        Args:
            result: Workflow result dictionary.

        Returns:
            Combined error message or None if no errors/issues.
        """
        error_parts: list[str] = []

        for e in result.get("errors", []):
            if isinstance(e, dict):
                error_parts.append(str(e.get("error", e)))
            else:
                error_parts.append(str(e))

        for issue in result.get("issues", []):
            if isinstance(issue, dict):
                error_parts.append(str(issue.get("message", issue)))
            else:
                error_parts.append(str(issue))

        return "; ".join(error_parts) if error_parts else None

    def run_phase_workflow(self, manager: WorkspaceManager, phase: str) -> dict[str, Any]:
        """Execute the actual phase workflow.

        Runs the real workflow implementation for the given phase.  When
        ``use_pdd`` is True, dispatches to the PDD orchestrator instead
        of the legacy refinement workflow functions.

        Args:
            manager: WorkspaceManager to run the workflow on.
            phase: Phase name to execute.

        Returns:
            Workflow result dictionary with success status and outputs.

        Raises:
            RuntimeError: If the workflow fails to execute.
        """
        if self.use_pdd:
            return self._run_pdd_phase(manager, phase)

        return self._run_refinement_phase(manager, phase)

    def _run_pdd_phase(self, manager: WorkspaceManager, phase: str) -> dict[str, Any]:
        """Dispatch an eval phase through the PDD orchestrator.

        Maps the eval's 8-phase names to PDD Phase enum values and runs
        each through ``PddOrchestrator.run_phase()``.  Before running any
        mapped phase, ensures that Phase 0 (extraction) has completed so
        that the workspace contains structured data from prose input.

        Args:
            manager: WorkspaceManager to run the workflow on.
            phase: Eval phase name (e.g. ``"sectionization"``).

        Returns:
            Workflow result dictionary.
        """
        from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator
        from spec_manager.refinement.workspace.state import Phase as PddPhase

        result: dict[str, Any] = {
            "success": False,
            "phase": phase,
            "outputs": {},
            "error": None,
        }

        pdd_phase_values = _EVAL_TO_PDD_PHASES.get(phase)
        if pdd_phase_values is None:
            result["error"] = f"No PDD mapping for eval phase: {phase}"
            return result

        orchestrator = PddOrchestrator(manager)

        # Ensure Phase 0 (extraction) has run — it populates the workspace
        # with structured artifacts (summaries, libraries, specs) from prose.
        libs_dir = manager.structure.libraries_dir
        extraction_needed = not libs_dir.exists() or not any(libs_dir.iterdir())
        if extraction_needed:
            try:
                orchestrator.run_phase(PddPhase.EXTRACTION)
            except Exception as exc:
                result["error"] = f"Phase 0 extraction failed: {exc}"
                return result

        combined_outputs: dict[str, Any] = {}

        for pdd_value in pdd_phase_values:
            try:
                pdd_phase = PddPhase(pdd_value)
            except ValueError:
                result["error"] = f"Unknown PDD phase value: {pdd_value}"
                return result

            try:
                phase_outputs = orchestrator.run_phase(pdd_phase)
                combined_outputs[pdd_value] = phase_outputs
            except Exception as exc:
                result["error"] = f"PDD phase {pdd_value} failed: {exc}"
                return result

        result["success"] = True
        result["outputs"] = combined_outputs
        return result

    def _run_refinement_phase(self, manager: WorkspaceManager, phase: str) -> dict[str, Any]:
        """Dispatch an eval phase through the legacy refinement workflows.

        This is the original dispatch path, preserved as a fallback when
        ``use_pdd`` is False.

        Args:
            manager: WorkspaceManager to run the workflow on.
            phase: Eval phase name.

        Returns:
            Workflow result dictionary.
        """
        result: dict[str, Any] = {
            "success": False,
            "phase": phase,
            "outputs": {},
            "error": None,
        }

        try:
            if phase == "sectionization":
                result = self._run_sectionization_workflow(manager)
            elif phase == "summarization":
                result = self._run_summarization_workflow(manager)
            elif phase == "library_synthesis":
                result = self._run_library_synthesis_workflow(manager)
            elif phase == "evidence_expansion":
                result = self._run_evidence_expansion_workflow(manager)
            elif phase == "spec_building":
                result = self._run_spec_building_workflow(manager)
            elif phase == "architecture":
                result = self._run_architecture_workflow(manager)
            elif phase == "interfaces":
                result = self._run_interfaces_workflow(manager)
            elif phase == "tasks":
                result = self._run_tasks_workflow(manager)
            else:
                result["error"] = f"Unknown phase: {phase}"

        except Exception as exc:
            result["error"] = str(exc)
            result["success"] = False

        return result

    def _run_sectionization_workflow(self, manager: WorkspaceManager) -> dict[str, Any]:
        """Run the sectionization workflow.

        Args:
            manager: WorkspaceManager to run the workflow on.

        Returns:
            Workflow result dictionary.
        """
        from spec_manager.refinement.workflows.phase_01_sectionization import sectionize_all

        result = sectionize_all(run_id=manager.run_id, parallel=False)

        return {
            "success": result.get("success", False),
            "phase": "sectionization",
            "outputs": result.get("outputs", {}),
            "error": self._build_error_message(result),
            "files_processed": result.get("files_processed", 0),
            "sections_written": result.get("sections_written", 0),
            "atoms_written": result.get("atoms_written", 0),
            "terms_written": result.get("terms_written", 0),
        }

    def _run_summarization_workflow(self, manager: WorkspaceManager) -> dict[str, Any]:
        """Run the summarization workflow.

        Args:
            manager: WorkspaceManager to run the workflow on.

        Returns:
            Workflow result dictionary.
        """
        from spec_manager.refinement.workflows.summarization import summarize_all

        result = summarize_all(run_id=manager.run_id, parallel=False)

        return {
            "success": result.get("success", False),
            "phase": "summarization",
            "outputs": result.get("outputs", {}),
            "error": self._build_error_message(result),
        }

    def _run_library_synthesis_workflow(self, manager: WorkspaceManager) -> dict[str, Any]:
        """Run the library synthesis workflow.

        Args:
            manager: WorkspaceManager to run the workflow on.

        Returns:
            Workflow result dictionary.
        """
        from spec_manager.refinement.workflows.library_synthesis import synthesize_libraries

        result = synthesize_libraries(run_id=manager.run_id)

        return {
            "success": result.get("success", False),
            "phase": "library_synthesis",
            "outputs": result.get("outputs", {}),
            "error": self._build_error_message(result),
        }

    def _run_evidence_expansion_workflow(self, manager: WorkspaceManager) -> dict[str, Any]:
        """Run the evidence expansion workflow.

        Args:
            manager: WorkspaceManager to run the workflow on.

        Returns:
            Workflow result dictionary.
        """
        from spec_manager.refinement.workflows.evidence_expansion import expand_evidence

        result = expand_evidence(run_id=manager.run_id)

        return {
            "success": result.get("success", False),
            "phase": "evidence_expansion",
            "outputs": result.get("outputs", {}),
            "error": self._build_error_message(result),
        }

    def _run_spec_building_workflow(self, manager: WorkspaceManager) -> dict[str, Any]:
        """Run the spec building workflow.

        Args:
            manager: WorkspaceManager to run the workflow on.

        Returns:
            Workflow result dictionary.
        """
        from spec_manager.refinement.workflows.spec_building import build_specs

        result = build_specs(run_id=manager.run_id)

        return {
            "success": result.get("success", False),
            "phase": "spec_building",
            "outputs": result.get("outputs", {}),
            "error": self._build_error_message(result),
        }

    def _run_architecture_workflow(self, manager: WorkspaceManager) -> dict[str, Any]:
        """Run the architecture workflow.

        Args:
            manager: WorkspaceManager to run the workflow on.

        Returns:
            Workflow result dictionary.
        """
        from spec_manager.refinement.workflows.architecture import propose_architectures

        result = propose_architectures(run_id=manager.run_id)

        return {
            "success": result.get("success", False),
            "phase": "architecture",
            "outputs": result.get("outputs", {}),
            "error": self._build_error_message(result),
        }

    def _run_interfaces_workflow(self, manager: WorkspaceManager) -> dict[str, Any]:
        """Run the interfaces workflow.

        Args:
            manager: WorkspaceManager to run the workflow on.

        Returns:
            Workflow result dictionary.
        """
        from spec_manager.refinement.workflows.interfaces import extract_interface_edges

        result = extract_interface_edges(run_id=manager.run_id)

        return {
            "success": result.get("success", False),
            "phase": "interfaces",
            "outputs": result.get("outputs", {}),
            "error": self._build_error_message(result),
        }

    def _run_tasks_workflow(self, manager: WorkspaceManager) -> dict[str, Any]:
        """Run the tasks workflow.

        Args:
            manager: WorkspaceManager to run the workflow on.

        Returns:
            Workflow result dictionary.
        """
        from spec_manager.refinement.workflows.tasks import plan_tasks

        result = plan_tasks(run_id=manager.run_id)

        return {
            "success": result.get("success", False),
            "phase": "tasks",
            "outputs": result.get("outputs", {}),
            "error": self._build_error_message(result),
        }

    def cleanup(self) -> None:
        """Clean up all created workspaces and temporary directories."""
        if not self.cleanup_on_exit:
            return

        for workspace_path in self.created_workspaces:
            if workspace_path.exists():
                with contextlib.suppress(OSError):
                    # Best effort cleanup
                    shutil.rmtree(workspace_path)

        self.created_workspaces.clear()

    def __enter__(self) -> WorkspaceIntegration:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit with cleanup."""
        self.cleanup()


def run_real_phase_evaluation(
    spec: SequenceSpec,
    phase: str,
    temp_dir: Path | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Run a real phase evaluation on a spec.

    Convenience function that creates a workspace from a spec, runs the
    actual workflow, and extracts outputs.

    Args:
        spec: The sequence spec to evaluate.
        phase: Phase name to run.
        temp_dir: Optional custom temp directory.

    Returns:
        Tuple of (extracted_outputs, workflow_result).
    """
    with WorkspaceIntegration(temp_dir=temp_dir) as integration:
        manager = integration.create_workspace_from_spec(spec)
        workflow_result = integration.run_phase_workflow(manager, phase)
        outputs = integration.extract_phase_outputs(manager, phase)

    return outputs, workflow_result
