"""Run folder structure for workspace path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spec_manager.core.project_root import resolve_from_root


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
    def reports_dir(self) -> Path:
        """Path to the reports directory."""
        return self.root / "reports"

    @property
    def analysis_dir(self) -> Path:
        """Path to the analysis artifacts directory."""
        return self.root / "analysis"

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

    @property
    def branches_dir(self) -> Path:
        """Path to the branches directory."""
        return self.root / "branches"

    @property
    def workspace_dir(self) -> Path:
        """Path to the workspace directory for intermediates."""
        return self.root / "workspace"

    @property
    def intermediates_dir(self) -> Path:
        """Path to the intermediates directory."""
        return self.workspace_dir / "intermediates"

    @property
    def pass_01_dir(self) -> Path:
        """Path to the Phase 1 pass directory."""
        return self.intermediates_dir / "pass_01"

    @property
    def pass_04_dir(self) -> Path:
        """Path to the Phase 4 (library synthesis) pass directory."""
        return self.intermediates_dir / "pass_04"

    @property
    def indexes_dir(self) -> Path:
        """Path to the indexes directory for cross-cutting data."""
        return self.workspace_dir / "indexes"

    @property
    def evidence_store_dir(self) -> Path:
        """Path to the hollowed-out spec evidence store directory."""
        return self.workspace_dir / "evidence_store"

    @property
    def evidence_index_path(self) -> Path:
        """Path to the evidence store index file."""
        return self.workspace_dir / "indexes" / "evidence_store_index.json"

    @property
    def registry_dir(self) -> Path:
        """Path to the workspace-global registry directory."""
        return resolve_from_root("runs", "_registry")

    @property
    def file_uids_json(self) -> Path:
        """Path to the file UID registry."""
        return self.registry_dir / "file_uids.json"

    @property
    def revisions_json(self) -> Path:
        """Path to the revision registry."""
        return self.registry_dir / "revisions.json"

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
