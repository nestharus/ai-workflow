"""Tests for spec_decomposition.execution module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.spec_decomposition.execution import (
    SpecStatus,
    SpecEntry,
    Gap,
    Ledger,
    compute_content_hash,
    load_ledger,
    save_ledger,
    save_gaps,
    compute_spec_hashes,
    detect_spec_changes,
    get_runnable_ids,
    generate_prompt_files,
    ingest_evidence,
    execute_spec,
)


class TestSpecEntry:
    """Tests for SpecEntry dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        entry = SpecEntry(spec_id="E-001")
        assert entry.status == SpecStatus.PENDING
        assert entry.hash == ""
        assert entry.run_id is None
        assert entry.files == []
        assert entry.needs == []
        assert entry.notes == ""

    def test_to_dict(self):
        """Test conversion to dict."""
        entry = SpecEntry(
            spec_id="E-001",
            status=SpecStatus.COMPLETE,
            hash="sha256:abc123",
            run_id="run_001",
            files=["src/service.py"],
            needs=[],
            notes="Implemented successfully",
        )
        result = entry.to_dict()
        assert result["status"] == "complete"
        assert result["hash"] == "sha256:abc123"
        assert result["run_id"] == "run_001"
        assert result["files"] == ["src/service.py"]
        assert result["notes"] == "Implemented successfully"

    def test_from_dict(self):
        """Test creation from dict."""
        data = {
            "status": "partial",
            "hash": "sha256:def456",
            "run_id": "run_002",
            "files": ["src/a.py", "src/b.py"],
            "needs": ["Database pool"],
            "notes": "Waiting on infrastructure",
        }
        entry = SpecEntry.from_dict("E-002", data)
        assert entry.spec_id == "E-002"
        assert entry.status == SpecStatus.PARTIAL
        assert entry.hash == "sha256:def456"
        assert entry.run_id == "run_002"
        assert entry.files == ["src/a.py", "src/b.py"]
        assert entry.needs == ["Database pool"]


class TestGap:
    """Tests for Gap dataclass."""

    def test_default_values(self):
        """Test default values."""
        gap = Gap(id="gap_001", description="Missing auth")
        assert gap.blocking == []
        assert gap.resolved_by is None
        assert gap.investigated is False

    def test_to_dict(self):
        """Test conversion to dict."""
        gap = Gap(
            id="gap_001",
            description="Need database pool",
            blocking=["E-002", "E-003"],
            resolved_by=None,
            investigated=True,
        )
        result = gap.to_dict()
        assert result["id"] == "gap_001"
        assert result["description"] == "Need database pool"
        assert result["blocking"] == ["E-002", "E-003"]
        assert result["resolved_by"] is None
        assert result["investigated"] is True

    def test_from_dict(self):
        """Test creation from dict."""
        data = {
            "id": "gap_002",
            "description": "Missing API key",
            "blocking": ["E-005"],
            "resolved_by": "E-010",
            "investigated": True,
        }
        gap = Gap.from_dict(data)
        assert gap.id == "gap_002"
        assert gap.description == "Missing API key"
        assert gap.blocking == ["E-005"]
        assert gap.resolved_by == "E-010"


class TestLedger:
    """Tests for Ledger dataclass."""

    def test_default_values(self):
        """Test default ledger is empty."""
        ledger = Ledger()
        assert ledger.version == 1
        assert ledger.spec_hashes == {}
        assert ledger.entries == {}
        assert ledger.gaps == []
        assert ledger.alias_links == {}

    def test_to_dict_roundtrip(self):
        """Test to_dict and from_dict preserve data."""
        ledger = Ledger()
        ledger.spec_hashes = {"E-001": "sha256:abc"}
        ledger.entries["E-001"] = SpecEntry(
            spec_id="E-001",
            status=SpecStatus.COMPLETE,
            hash="sha256:abc",
        )
        ledger.gaps.append(Gap(id="gap_001", description="Test gap"))
        ledger.alias_links = {"UserStore": "UserRepository"}

        data = ledger.to_dict()
        restored = Ledger.from_dict(data)

        assert restored.version == 1
        assert restored.spec_hashes == {"E-001": "sha256:abc"}
        assert "E-001" in restored.entries
        assert restored.entries["E-001"].status == SpecStatus.COMPLETE
        assert len(restored.gaps) == 1
        assert restored.gaps[0].id == "gap_001"
        assert restored.alias_links == {"UserStore": "UserRepository"}


class TestComputeContentHash:
    """Tests for compute_content_hash function."""

    def test_returns_sha256_prefix(self):
        """Test hash starts with sha256: prefix."""
        result = compute_content_hash("test content")
        assert result.startswith("sha256:")

    def test_same_content_same_hash(self):
        """Test same content produces same hash."""
        content = "Hello, World!"
        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Test different content produces different hash."""
        hash1 = compute_content_hash("content a")
        hash2 = compute_content_hash("content b")
        assert hash1 != hash2


class TestLoadSaveLedger:
    """Tests for load_ledger and save_ledger functions."""

    def test_save_creates_execution_dir(self, tmp_path: Path):
        """Test save creates execution directory if needed."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        ledger = Ledger()
        save_ledger(workspace, ledger)

        assert (workspace / "execution").exists()
        assert (workspace / "execution" / "ledger.json").exists()

    def test_load_returns_empty_ledger_when_no_file(self, tmp_path: Path):
        """Test load returns empty ledger when no file exists."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        ledger = load_ledger(workspace)
        assert ledger.version == 1
        assert ledger.entries == {}

    def test_save_load_roundtrip(self, tmp_path: Path):
        """Test save and load preserve ledger data."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        ledger = Ledger()
        ledger.spec_hashes = {"E-001": "sha256:abc123"}
        ledger.entries["E-001"] = SpecEntry(
            spec_id="E-001",
            status=SpecStatus.PENDING,
            hash="sha256:abc123",
        )

        save_ledger(workspace, ledger)
        loaded = load_ledger(workspace)

        assert loaded.spec_hashes == {"E-001": "sha256:abc123"}
        assert "E-001" in loaded.entries
        assert loaded.entries["E-001"].status == SpecStatus.PENDING


class TestSaveGaps:
    """Tests for save_gaps function."""

    def test_creates_gaps_file(self, tmp_path: Path):
        """Test creates gaps.json file."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        gaps = [
            Gap(id="gap_001", description="Missing dependency"),
            Gap(id="gap_002", description="Need config"),
        ]
        save_gaps(workspace, gaps)

        gaps_file = workspace / "execution" / "gaps.json"
        assert gaps_file.exists()

        data = json.loads(gaps_file.read_text())
        assert len(data) == 2
        assert data[0]["id"] == "gap_001"


class TestComputeSpecHashes:
    """Tests for compute_spec_hashes function."""

    def test_hashes_entity_files(self, tmp_path: Path):
        """Test computes hashes for entity files."""
        workspace = tmp_path / "workspace"
        entities_dir = workspace / "entities"
        entities_dir.mkdir(parents=True)

        (entities_dir / "E-001.md").write_text("# Entity 1\nDescription")
        (entities_dir / "E-002.md").write_text("# Entity 2\nOther content")

        hashes = compute_spec_hashes(workspace)

        assert "E-001" in hashes
        assert "E-002" in hashes
        assert hashes["E-001"].startswith("sha256:")
        assert hashes["E-001"] != hashes["E-002"]

    def test_hashes_relation_files(self, tmp_path: Path):
        """Test computes hashes for relation files."""
        workspace = tmp_path / "workspace"
        relations_dir = workspace / "relations"
        relations_dir.mkdir(parents=True)

        (relations_dir / "R-001.md").write_text("A -> B")

        hashes = compute_spec_hashes(workspace)
        assert "R-001" in hashes

    def test_returns_empty_for_empty_workspace(self, tmp_path: Path):
        """Test returns empty dict for workspace with no specs."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        hashes = compute_spec_hashes(workspace)
        assert hashes == {}


class TestDetectSpecChanges:
    """Tests for detect_spec_changes function."""

    def test_detects_new_ids(self):
        """Test detects new spec IDs."""
        ledger = Ledger()
        ledger.spec_hashes = {"E-001": "sha256:aaa"}

        current = {"E-001": "sha256:aaa", "E-002": "sha256:bbb"}

        new_ids, modified_ids, deleted_ids = detect_spec_changes(ledger, current)

        assert new_ids == ["E-002"]
        assert modified_ids == []
        assert deleted_ids == []

    def test_detects_modified_ids(self):
        """Test detects modified spec IDs."""
        ledger = Ledger()
        ledger.spec_hashes = {"E-001": "sha256:old"}

        current = {"E-001": "sha256:new"}

        new_ids, modified_ids, deleted_ids = detect_spec_changes(ledger, current)

        assert new_ids == []
        assert modified_ids == ["E-001"]
        assert deleted_ids == []

    def test_detects_deleted_ids(self):
        """Test detects deleted spec IDs."""
        ledger = Ledger()
        ledger.spec_hashes = {"E-001": "sha256:aaa", "E-002": "sha256:bbb"}

        current = {"E-001": "sha256:aaa"}

        new_ids, modified_ids, deleted_ids = detect_spec_changes(ledger, current)

        assert new_ids == []
        assert modified_ids == []
        assert deleted_ids == ["E-002"]


class TestGetRunnableIds:
    """Tests for get_runnable_ids function."""

    def test_returns_pending_ids(self):
        """Test returns IDs with pending status."""
        ledger = Ledger()
        ledger.entries["E-001"] = SpecEntry(spec_id="E-001", status=SpecStatus.PENDING)
        ledger.entries["E-002"] = SpecEntry(spec_id="E-002", status=SpecStatus.COMPLETE)

        runnable = get_runnable_ids(ledger)
        assert runnable == ["E-001"]

    def test_returns_modified_ids(self):
        """Test returns IDs with modified status."""
        ledger = Ledger()
        ledger.entries["E-001"] = SpecEntry(spec_id="E-001", status=SpecStatus.MODIFIED)

        runnable = get_runnable_ids(ledger)
        assert runnable == ["E-001"]

    def test_excludes_ids_blocked_by_gaps(self):
        """Test excludes IDs blocked by unresolved gaps."""
        ledger = Ledger()
        ledger.entries["E-001"] = SpecEntry(spec_id="E-001", status=SpecStatus.PENDING)
        ledger.entries["E-002"] = SpecEntry(spec_id="E-002", status=SpecStatus.PENDING)
        ledger.gaps.append(Gap(id="gap_001", description="Blocking", blocking=["E-001"]))

        runnable = get_runnable_ids(ledger)
        assert runnable == ["E-002"]

    def test_includes_ids_with_resolved_gaps(self):
        """Test includes IDs whose gaps are resolved."""
        ledger = Ledger()
        ledger.entries["E-001"] = SpecEntry(spec_id="E-001", status=SpecStatus.PENDING)
        ledger.gaps.append(
            Gap(id="gap_001", description="Resolved", blocking=["E-001"], resolved_by="E-010")
        )

        runnable = get_runnable_ids(ledger)
        assert runnable == ["E-001"]


class TestGeneratePromptFiles:
    """Tests for generate_prompt_files function."""

    def test_creates_prompt_files(self, tmp_path: Path):
        """Test creates plan, implement, and review prompts."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        prompts = generate_prompt_files(workspace, ["E-001", "E-002"])

        assert "plan" in prompts
        assert "implement" in prompts
        assert "review" in prompts

        for prompt_path in prompts.values():
            assert Path(prompt_path).exists()

    def test_prompts_contain_target_ids(self, tmp_path: Path):
        """Test prompt files contain target IDs."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        prompts = generate_prompt_files(workspace, ["E-001", "R-002"])

        plan_content = Path(prompts["plan"]).read_text()
        assert "E-001" in plan_content
        assert "R-002" in plan_content

    def test_returns_empty_for_no_runnable_ids(self, tmp_path: Path):
        """Test returns empty dict when no runnable IDs."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        prompts = generate_prompt_files(workspace, [])
        assert prompts == {}


class TestIngestEvidence:
    """Tests for ingest_evidence function."""

    def test_updates_entry_status(self, tmp_path: Path):
        """Test updates entry status from evidence."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        evidence_file = tmp_path / "evidence.json"
        evidence_file.write_text(
            json.dumps(
                {
                    "run_id": "run_001",
                    "implementations": [
                        {"spec_id": "E-001", "status": "complete", "files": ["src/a.py"]},
                    ],
                    "gaps": [],
                }
            )
        )

        ledger = Ledger()
        ledger.entries["E-001"] = SpecEntry(spec_id="E-001", status=SpecStatus.PENDING)

        updated = ingest_evidence(workspace, evidence_file, ledger)

        assert updated.entries["E-001"].status == SpecStatus.COMPLETE
        assert updated.entries["E-001"].run_id == "run_001"
        assert updated.entries["E-001"].files == ["src/a.py"]

    def test_adds_gaps_from_evidence(self, tmp_path: Path):
        """Test adds gaps from evidence."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        evidence_file = tmp_path / "evidence.json"
        evidence_file.write_text(
            json.dumps(
                {
                    "run_id": "run_001",
                    "implementations": [],
                    "gaps": [
                        {"description": "Need database", "blocking": ["E-001"]},
                    ],
                }
            )
        )

        ledger = Ledger()
        updated = ingest_evidence(workspace, evidence_file, ledger)

        assert len(updated.gaps) == 1
        assert updated.gaps[0].description == "Need database"
        assert updated.gaps[0].blocking == ["E-001"]


class TestExecuteSpec:
    """Tests for execute_spec function."""

    def test_creates_ledger_for_new_workspace(self, tmp_path: Path):
        """Test creates ledger for workspace with no prior execution."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create an entity file to hash
        entities_dir = workspace / "entities"
        entities_dir.mkdir()
        (entities_dir / "E-001.md").write_text("# Test Entity")

        result = execute_spec(workspace)

        assert result["action"] == "prepare"
        assert "E-001" in result["new_ids"]
        assert (workspace / "execution" / "ledger.json").exists()

    def test_detects_modified_specs(self, tmp_path: Path):
        """Test detects when specs are modified."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        execution_dir = workspace / "execution"
        execution_dir.mkdir()

        # Create entity and save initial ledger
        entities_dir = workspace / "entities"
        entities_dir.mkdir()
        (entities_dir / "E-001.md").write_text("# Original")

        # Run once to establish baseline
        execute_spec(workspace)

        # Modify the entity
        (entities_dir / "E-001.md").write_text("# Modified content")

        result = execute_spec(workspace)

        assert "E-001" in result["modified_ids"]

    def test_ingests_evidence_when_provided(self, tmp_path: Path):
        """Test ingests evidence file when path provided."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        evidence_file = tmp_path / "evidence.json"
        evidence_file.write_text(
            json.dumps(
                {
                    "run_id": "run_001",
                    "implementations": [
                        {"spec_id": "E-001", "status": "complete", "files": []},
                    ],
                    "gaps": [],
                }
            )
        )

        result = execute_spec(workspace, ingest_path=evidence_file)

        assert result["action"] == "ingest"
        assert result["ingested"] == str(evidence_file)
