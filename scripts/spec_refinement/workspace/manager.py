"""Run-scoped workspace manager for spec refinement.

Agent Integration:
- glm-file-what-summarizer: Phase 1 file inventory extraction
- opus-library-synthesizer: Phase 2 library boundary detection
- See .agents/agents/ for full agent definitions
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from scripts.spec_manager.spec_manager.core.gaps import Severity
from scripts.spec_refinement.core.gap import (
    Gap,
    GapEvidence,
    GapType,
    compute_evidence_signature,
    format_gap_markdown,
    parse_gaps_markdown,
)
from scripts.spec_refinement.core.gap_queue import GapQueue

from .state import Phase, WorkspaceState


@dataclass
class RunFolderStructure:
    """Expected structure of a run folder."""

    run_id: str
    root: Path

    @property
    def spec_snapshot_dir(self) -> Path:
        """Path to the spec snapshot directory."""
        return self.root / "spec_snapshot"

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

    @property
    def manifest_sections_dir(self) -> Path:
        """Path to the per-file sections directory (Phase 1)."""
        return self.manifest_dir / "sections"

    @property
    def manifest_atoms_dir(self) -> Path:
        """Path to the per-file atoms directory (Phase 1)."""
        return self.manifest_dir / "atoms"

    @property
    def manifest_terms_dir(self) -> Path:
        """Path to the per-file terms directory (Phase 1)."""
        return self.manifest_dir / "terms"

    def validate(self) -> list[str]:
        """Validate run folder structure."""
        issues = []
        if not self.root.exists():
            issues.append(f"Run folder does not exist: {self.root}")
        if not self.spec_snapshot_dir.exists():
            issues.append(f"Spec snapshot directory missing: {self.spec_snapshot_dir}")
        elif not any(self.spec_snapshot_dir.rglob("*")):
            issues.append("Spec snapshot directory is empty")
        return issues


@dataclass
class WorkspaceManager:
    """Manages the workspace for spec refinement.

    Phase 0 creates an immutable spec snapshot, and all file operations
    reference the snapshot rather than the original input folder.
    """

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
        """Initialize the workspace.

        Creates an immutable spec snapshot in `spec_snapshot/`. Setting
        `force=True` deletes and recreates the entire run directory,
        including the snapshot. Subsequent phases must not modify the
        snapshot.
        """
        issues: list[str] = []

        if not self.input_folder.exists():
            return [f"Input folder does not exist: {self.input_folder}"]

        if self.structure.root.exists() and force:
            shutil.rmtree(self.structure.root)

        self.structure.root.mkdir(parents=True, exist_ok=True)
        for subdir in [
            self.structure.manifest_dir,
            self.structure.manifest_sections_dir,
            self.structure.manifest_atoms_dir,
            self.structure.manifest_terms_dir,
            self.structure.summaries_dir,
            self.structure.libraries_dir,
            self.structure.architecture_dir,
            self.structure.tasks_dir,
            self.structure.audits_dir,
        ]:
            subdir.mkdir(parents=True, exist_ok=True)

        snapshot_issues: list[str] = []
        snapshot_verified = False

        if self.structure.spec_snapshot_dir.exists() and not force:
            snapshot_issues.extend(self._validate_spec_snapshot_immutability())
            snapshot_verified = not snapshot_issues
        else:
            snapshot_issues.extend(self._create_spec_snapshot())
            snapshot_verified = not snapshot_issues

        if snapshot_issues:
            issues.extend(snapshot_issues)
            return issues

        if not snapshot_verified or not self.structure.spec_snapshot_dir.exists():
            return issues

        file_manifest, enumeration_issues = self._enumerate_files_with_hashes()
        if enumeration_issues:
            issues.extend(enumeration_issues)
        if not file_manifest:
            issues.append(f"No files found in: {self.structure.spec_snapshot_dir}")

        rel_paths = [file_data["relpath"] for file_data in file_manifest.values()]
        detected_mode = self._detect_mode_from_paths(rel_paths)

        manifest_conflict = self._check_manifest_resume_safety(file_manifest)
        if manifest_conflict is not None and not force:
            issues.append(manifest_conflict)
            return issues

        if self.is_initialized and self.state.mode != detected_mode:
            issues.append(
                f"Warning: Detected mode '{detected_mode}' differs from existing mode "
                f"'{self.state.mode}'. Using existing mode."
            )
        else:
            self.state.mode = detected_mode

        section_manifest: dict[str, list[str]] = {file_id: [] for file_id in file_manifest}
        section_files = sorted(self.structure.manifest_sections_dir.glob("*.sections.json"))
        for section_file in section_files:
            file_id = section_file.stem.replace(".sections", "")
            if file_id not in section_manifest:
                continue
            try:
                sections_data = json.loads(section_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                issues.append(f"Failed to read sections manifest {section_file}: {exc}")
                continue
            if not isinstance(sections_data, dict) or "sections" not in sections_data:
                issues.append(f"Invalid sections manifest format in {section_file}")
                continue
            try:
                section_manifest[file_id] = [
                    section["section_id"] for section in sections_data["sections"]
                ]
            except (KeyError, TypeError) as exc:
                issues.append(f"Invalid section entries in {section_file}: {exc}")
                continue

        self._write_manifest_files(file_manifest)

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
        section_manifest: dict[str, list[str]] = {
            file_id: [] for file_id in self.state.file_manifest
        }
        if self.structure.manifest_sections_dir.exists():
            for section_file in self.structure.manifest_sections_dir.glob("*.sections.json"):
                file_id = section_file.stem.replace(".sections", "")
                if file_id not in section_manifest:
                    continue
                try:
                    sections_data = json.loads(section_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if not isinstance(sections_data, dict) or "sections" not in sections_data:
                    continue
                try:
                    section_manifest[file_id] = [
                        section["section_id"] for section in sections_data["sections"]
                    ]
                except (KeyError, TypeError):
                    continue
        self.state.section_manifest = section_manifest
        self._save_state()

    def finalize(self) -> Path:
        """Finalize the workspace after successful processing."""
        if not self.state.is_complete():
            raise RuntimeError("Cannot finalize incomplete workspace")

        summary_path = self._generate_summary_report()

        archive_dir = self.structure.root / "archive"
        archive_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for file_id, file_data in self.state.file_manifest.items():
            src = self.structure.spec_snapshot_dir / file_data["relpath"]
            if src.exists():
                dst = archive_dir / f"{timestamp}_{file_id}_{src.name}"
                shutil.copy2(src, dst)

        return summary_path

    # --- Manifest Management ---

    def _enumerate_files_with_hashes(self) -> tuple[dict[str, dict[str, str]], list[str]]:
        """Enumerate files in the spec snapshot with stable IDs and hashes."""
        files: dict[str, dict[str, str]] = {}
        issues: list[str] = []

        snapshot_dir = self.structure.spec_snapshot_dir
        if not snapshot_dir.exists():
            issues.append(f"Spec snapshot directory missing: {snapshot_dir}")
            return files, issues

        rel_paths: list[str] = []
        for path in snapshot_dir.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            rel_paths.append(path.relative_to(snapshot_dir).as_posix())

        for index, relpath in enumerate(sorted(rel_paths), start=1):
            file_id = f"F{index:04d}"
            abs_path = snapshot_dir / relpath
            hasher = hashlib.sha256()
            try:
                with abs_path.open("rb") as handle:
                    while chunk := handle.read(65536):
                        hasher.update(chunk)
            except OSError as exc:
                issues.append(f"Failed to hash snapshot file {relpath}: {exc}")
                continue
            files[file_id] = {"relpath": relpath, "sha256": hasher.hexdigest()}

        return files, issues

    def _create_spec_snapshot(self) -> list[str]:
        """Create a spec snapshot and record its baseline."""
        issues: list[str] = []

        try:
            shutil.copytree(self.input_folder, self.structure.spec_snapshot_dir)
        except OSError as exc:
            issues.append(f"Failed to create spec snapshot: {exc}")
            return issues

        try:
            expected_count = sum(1 for path in self.input_folder.rglob("*") if path.is_file())
            actual_count = sum(
                1 for path in self.structure.spec_snapshot_dir.rglob("*") if path.is_file()
            )
        except OSError as exc:
            issues.append(f"Snapshot verification failed: {exc}")
            return issues

        if expected_count != actual_count:
            issues.append(
                "Snapshot verification failed: expected "
                f"{expected_count} files, found {actual_count}"
            )
            return issues

        baseline, baseline_issues = self._build_spec_snapshot_baseline()
        if baseline_issues:
            issues.extend(baseline_issues)
            return issues

        self.state.spec_snapshot_baseline = baseline
        return issues

    def _validate_spec_snapshot_immutability(self) -> list[str]:
        """Validate that the spec snapshot has not been modified."""
        issues: list[str] = []
        baseline = self.state.spec_snapshot_baseline
        if baseline is None:
            issues.append("Spec snapshot baseline missing. Use --force to recreate the snapshot.")
            return issues

        current, baseline_issues = self._build_spec_snapshot_baseline()
        if baseline_issues:
            issues.extend(baseline_issues)
            return issues

        drift = self._describe_spec_snapshot_drift(baseline, current)
        if drift:
            issues.append(drift)

        return issues

    def _build_spec_snapshot_baseline(self) -> tuple[dict[str, str], list[str]]:
        """Build a content hash baseline for the spec snapshot."""
        issues: list[str] = []
        baseline: dict[str, str] = {}

        snapshot_dir = self.structure.spec_snapshot_dir
        if not snapshot_dir.exists():
            issues.append(f"Spec snapshot directory missing: {snapshot_dir}")
            return baseline, issues

        for path in sorted(snapshot_dir.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(snapshot_dir).as_posix()
            try:
                baseline[rel_path] = self._hash_snapshot_file(path)
            except OSError as exc:
                issues.append(f"Failed to hash snapshot file {rel_path}: {exc}")

        return baseline, issues

    @staticmethod
    def _hash_snapshot_file(path: Path) -> str:
        """Compute a stable hash for a snapshot file."""
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _describe_spec_snapshot_drift(
        baseline: dict[str, str], current: dict[str, str]
    ) -> str | None:
        """Describe snapshot drift between baseline and current hashes."""
        missing = sorted(set(baseline) - set(current))
        added = sorted(set(current) - set(baseline))
        modified = sorted(
            path for path in baseline.keys() & current.keys() if baseline[path] != current[path]
        )

        if not missing and not added and not modified:
            return None

        parts: list[str] = []
        if missing:
            parts.append(f"{len(missing)} missing")
        if added:
            parts.append(f"{len(added)} added")
        if modified:
            parts.append(f"{len(modified)} modified")

        samples: list[str] = []
        if missing:
            samples.append(f"missing: {', '.join(missing[:3])}")
        if added:
            samples.append(f"added: {', '.join(added[:3])}")
        if modified:
            samples.append(f"modified: {', '.join(modified[:3])}")

        message = "Spec snapshot has changed since creation (" + ", ".join(parts) + ")."
        if samples:
            message += f" Examples: {'; '.join(samples)}."
        message += " Use --force to recreate the snapshot."
        return message

    def _check_manifest_resume_safety(self, new_manifest: dict[str, dict[str, str]]) -> str | None:
        """Check for manifest differences when resuming a workspace."""
        if not self.structure.files_json.exists():
            return None

        existing_manifest = json.loads(self.structure.files_json.read_text(encoding="utf-8"))

        existing_ids = set(existing_manifest.keys())
        new_ids = set(new_manifest.keys())

        added = new_ids - existing_ids
        removed = existing_ids - new_ids

        modified: list[str] = []
        for file_id in new_ids & existing_ids:
            existing_entry = existing_manifest[file_id]
            new_entry = new_manifest[file_id]
            if existing_entry.get("relpath") != new_entry.get("relpath") or existing_entry.get(
                "sha256"
            ) != new_entry.get("sha256"):
                modified.append(file_id)

        if not added and not removed and not modified:
            return None

        self._record_manifest_conflict_gap(
            existing_manifest=existing_manifest,
            new_manifest=new_manifest,
            added_ids=sorted(added),
            removed_ids=sorted(removed),
            modified_ids=sorted(modified),
        )

        return (
            "Manifest conflict detected: "
            f"{len(added)} files added, {len(removed)} removed, {len(modified)} modified. "
            "Use --force to recreate."
        )

    def _record_manifest_conflict_gap(
        self,
        *,
        existing_manifest: dict[str, dict[str, str]],
        new_manifest: dict[str, dict[str, str]],
        added_ids: list[str],
        removed_ids: list[str],
        modified_ids: list[str],
    ) -> Gap:
        modified_entries: list[dict[str, str | None]] = []
        for file_id in modified_ids:
            existing_entry = existing_manifest.get(file_id, {})
            new_entry = new_manifest.get(file_id, {})
            modified_entries.append(
                {
                    "file_id": file_id,
                    "existing_relpath": existing_entry.get("relpath"),
                    "new_relpath": new_entry.get("relpath"),
                    "existing_sha256": existing_entry.get("sha256"),
                    "new_sha256": new_entry.get("sha256"),
                }
            )

        evidence = [
            GapEvidence(
                invariant_family="content",
                description="Run manifest differs from current snapshot enumeration.",
                details={
                    "added_file_ids": added_ids,
                    "removed_file_ids": removed_ids,
                    "modified_file_ids": modified_ids,
                    "modified_entries": modified_entries,
                    "existing_manifest_path": str(self.structure.files_json),
                    "spec_snapshot_dir": str(self.structure.spec_snapshot_dir),
                },
                confidence=1.0,
                location="manifest/files.json",
                detector="workspace-manager",
            )
        ]
        gap_id = f"GAP-{compute_evidence_signature(evidence)}"
        gap = Gap(
            id=gap_id,
            gap_type=GapType.content_mismatch,
            severity=Severity.ERROR,
            source=["manifest/files.json", "spec_snapshot"],
            derived_artifact_target="manifest/files.json",
            description=(
                "Manifest mismatch detected between the existing run manifest and current "
                f"snapshot ({len(added_ids)} added, {len(removed_ids)} removed, "
                f"{len(modified_ids)} modified). Resume requires --force to recreate."
            ),
            evidence=evidence,
        )
        self._record_run_gap(gap)
        return gap

    def _detect_mode_from_paths(self, paths: list[str]) -> str:
        """Detect workspace mode based on snapshot paths."""
        for path in paths:
            if path.endswith(".patch") or path.endswith(".diff"):
                return "patch_stream"
            if path.startswith("patches/") or "/patches/" in path:
                return "patch_stream"
            if "_patch_" in path or "-patch-" in path:
                return "patch_stream"
        return "snapshot"

    def _write_manifest_files(self, file_manifest: dict[str, dict[str, str]]) -> None:
        """Write manifest files to disk."""
        self.structure.manifest_dir.mkdir(parents=True, exist_ok=True)
        self.structure.files_json.write_text(json.dumps(file_manifest, indent=2), encoding="utf-8")

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

    def _normalize_file_manifest(self) -> dict[str, dict[str, str]]:
        if not self.state.file_manifest:
            return {}
        if all(isinstance(value, dict) for value in self.state.file_manifest.values()):
            return self.state.file_manifest
        normalized: dict[str, dict[str, str]] = {}
        for file_id, file_data in self.state.file_manifest.items():
            if isinstance(file_data, dict):
                relpath = file_data.get("relpath")
                sha256 = file_data.get("sha256", "")
                if not isinstance(relpath, str) or not relpath:
                    continue
                normalized[file_id] = {
                    "relpath": relpath,
                    "sha256": sha256 if isinstance(sha256, str) else "",
                }
            elif isinstance(file_data, str):
                normalized[file_id] = {"relpath": file_data, "sha256": ""}
        return normalized

    def get_file_path(self, file_id: str) -> Path | None:
        """Get file path for a file ID."""
        file_data = self._normalize_file_manifest().get(file_id)
        relpath = file_data["relpath"] if file_data else None
        return self.structure.spec_snapshot_dir / relpath if relpath else None

    def get_section_labels(self, file_id: str) -> list[str]:
        """Get section labels for a file ID."""
        cached = self.state.section_manifest.get(file_id)
        if cached:
            return cached
        sections_data = self.read_file_sections(file_id)
        if not sections_data:
            return cached or []
        section_ids = [section["section_id"] for section in sections_data.get("sections", [])]
        self.state.section_manifest[file_id] = section_ids
        return section_ids

    def write_file_sections(self, file_id: str, sections: dict[str, Any]) -> Path:
        """Write Phase 1 sections manifest for a file."""
        from scripts.spec_refinement.schemas.sections import FileSections

        validated = FileSections.model_validate(sections)
        payload = validated.model_dump()

        self.structure.manifest_sections_dir.mkdir(parents=True, exist_ok=True)
        section_file = self.structure.manifest_sections_dir / f"{file_id}.sections.json"
        section_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.state.section_manifest[file_id] = [
            section["section_id"] for section in payload.get("sections", [])
        ]
        return section_file

    def write_file_atoms(self, file_id: str, atoms: list[dict[str, Any]]) -> Path:
        """Write Phase 1 atoms JSONL for a file."""
        from scripts.spec_refinement.schemas.atoms import LineAtom

        validated_atoms = [LineAtom.model_validate(atom).model_dump() for atom in atoms]

        self.structure.manifest_atoms_dir.mkdir(parents=True, exist_ok=True)
        atoms_file = self.structure.manifest_atoms_dir / f"{file_id}.atoms.jsonl"

        with atoms_file.open("w", encoding="utf-8") as handle:
            for atom in validated_atoms:
                handle.write(json.dumps(atom) + "\n")

        return atoms_file

    def write_file_terms(self, file_id: str, terms: dict[str, Any]) -> Path:
        """Write Phase 1 terms manifest for a file."""
        from scripts.spec_refinement.schemas.terms import FileTerms

        validated = FileTerms.model_validate(terms)
        payload = validated.model_dump()

        self.structure.manifest_terms_dir.mkdir(parents=True, exist_ok=True)
        terms_file = self.structure.manifest_terms_dir / f"{file_id}.terms.json"
        terms_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return terms_file

    def read_file_sections(self, file_id: str) -> dict[str, Any] | None:
        """Read Phase 1 sections manifest for a file."""
        section_file = self.structure.manifest_sections_dir / f"{file_id}.sections.json"
        if not section_file.exists():
            return None
        return cast("dict[str, Any]", json.loads(section_file.read_text(encoding="utf-8")))

    def read_file_atoms(self, file_id: str) -> list[dict[str, Any]]:
        """Read Phase 1 atoms JSONL for a file."""
        atoms_file = self.structure.manifest_atoms_dir / f"{file_id}.atoms.jsonl"
        if not atoms_file.exists():
            return []

        atoms: list[dict[str, Any]] = []
        with atoms_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    atoms.append(json.loads(line))
        return atoms

    def read_file_terms(self, file_id: str) -> dict[str, Any] | None:
        """Read Phase 1 terms manifest for a file."""
        terms_file = self.structure.manifest_terms_dir / f"{file_id}.terms.json"
        if not terms_file.exists():
            return None
        return cast("dict[str, Any]", json.loads(terms_file.read_text(encoding="utf-8")))

    def get_all_files(self) -> dict[str, Path]:
        """Get all files as {file_id: Path} mapping."""
        file_manifest = self._normalize_file_manifest()
        return {
            file_id: self.structure.spec_snapshot_dir / file_data["relpath"]
            for file_id, file_data in file_manifest.items()
        }

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

    def write_library_gaps(
        self,
        lib_id: str,
        gaps: list[Gap],
        *,
        gap_queue: GapQueue | None = None,
        update_queue: bool = True,
    ) -> Path:
        """Write gaps.md for a library."""
        lib_dir = self.structure.libraries_dir / lib_id
        lib_dir.mkdir(parents=True, exist_ok=True)
        gap_queue = gap_queue or self.get_library_gap_queue(lib_id)
        if update_queue:
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

    def _record_run_gap(self, gap: Gap) -> Path:
        """Persist a run-level gap in the audits directory."""
        audits_dir = self.structure.audits_dir
        audits_dir.mkdir(parents=True, exist_ok=True)
        run_gaps_path = audits_dir / "run_gaps.md"
        existing_gaps: list[Gap] = []
        if run_gaps_path.exists():
            existing_gaps = parse_gaps_markdown(run_gaps_path.read_text(encoding="utf-8"))
        if all(existing.id != gap.id for existing in existing_gaps):
            existing_gaps.append(gap)
        run_gaps_path.write_text(self.format_gaps_md(existing_gaps, None), encoding="utf-8")
        return run_gaps_path

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
        for file_id, file_data in self.state.file_manifest.items():
            relpath = file_data["relpath"]
            sha256 = file_data["sha256"]
            lines.append(f"- `{file_id}`: `{relpath}` (sha256: `{sha256[:8]}...`)")
        if not self.state.file_manifest:
            lines.append("- *No files recorded*")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path
