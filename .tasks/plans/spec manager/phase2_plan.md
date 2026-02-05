# Phase 2 Implementation Plan: Rebase L0 on Design ID Registry

## Overview

Phase 2 introduces the design's stable identifier and revision model while maintaining backward compatibility. The core changes enable file UIDs to persist across runs (stopping fresh enumeration each time) and add revision tracking with content-based identity.

## Current State Analysis

### File ID Allocation (Lines 347-348 in manager.py)
```python
for index, relpath in enumerate(sorted(rel_paths), start=1):
    file_id = f"F{index:04d}"
```
**Problem**: IDs are derived purely from sorted paths each run. Adding/removing files changes all subsequent IDs.

### Atom ID Format (atom_emitter.py line 66)
```python
atom_id = f"ATOM-{file_id}-L{line_no:04d}"
```
**Problem**: Missing revision component; no fingerprint for cross-revision stability.

### Registry Storage
**Problem**: No persistent registry exists. Design expects `runs/_registry/` for workspace-global state.

---

## Work Items

### WI-1: Persistent File UID Registry

**Goal**: Implement `AllocateFileUid` (ALG-CORE-0001) with persistent storage.

**New File**: `scripts/spec_manager/spec_manager/core/id_registry.py`

```python
# Data structures per DS-CORE-0003
@dataclass
class FileUidEntry:
    file_uid: str           # F####
    canonical_path: str     # Relative path (POSIX-normalized)
    first_seen_run_id: str
    created_at: str         # ISO8601

@dataclass
class FileUidRegistry:
    entries: dict[str, FileUidEntry]  # keyed by canonical_path
    next_seq: int

    def allocate(self, canonical_path: str, run_id: str) -> str:
        """ALG-CORE-0001 implementation"""
        if canonical_path in self.entries:
            return self.entries[canonical_path].file_uid
        file_uid = f"F{self.next_seq:04d}"
        self.entries[canonical_path] = FileUidEntry(
            file_uid=file_uid,
            canonical_path=canonical_path,
            first_seen_run_id=run_id,
            created_at=datetime.now().isoformat()
        )
        self.next_seq += 1
        return file_uid
```

**Storage Location**: `runs/_registry/file_uids.json`

**Schema**:
```json
{
  "schema_version": "1.0",
  "next_seq": 3,
  "entries": {
    "requirements/core.md": {
      "file_uid": "F0001",
      "canonical_path": "requirements/core.md",
      "first_seen_run_id": "run_001",
      "created_at": "2024-01-15T10:30:00Z"
    }
  }
}
```

**Modifications to manager.py**:
- Add `_load_file_uid_registry()` and `_save_file_uid_registry()` methods
- Replace enumeration-based allocation in `_enumerate_files_with_hashes()` with registry lookup
- Registry path: `Path("runs/_registry/file_uids.json")`

---

### WI-2: File Revision IDs (R####)

**Goal**: Implement `AllocateRevisionId` (ALG-CORE-0002) per file_uid keyed by content hash.

**New Data Structure** (add to `id_registry.py`):

```python
@dataclass
class RevisionEntry:
    rev_id: str         # R####
    file_uid: str
    sha256: str         # Content hash
    created_at: str

@dataclass
class RevisionRegistry:
    entries: dict[str, list[RevisionEntry]]  # keyed by file_uid

    def allocate(self, file_uid: str, sha256: str) -> str:
        """ALG-CORE-0002 implementation - CON-0001 compliant"""
        revisions = self.entries.get(file_uid, [])

        # Return existing rev_id if content unchanged
        for rev in revisions:
            if rev.sha256 == sha256:
                return rev.rev_id

        # Allocate new revision (append-only per CON-0001)
        next_seq = len(revisions) + 1
        rev_id = f"R{next_seq:04d}"

        new_rev = RevisionEntry(
            rev_id=rev_id,
            file_uid=file_uid,
            sha256=sha256,
            created_at=datetime.now().isoformat()
        )
        self.entries.setdefault(file_uid, []).append(new_rev)
        return rev_id
```

**Storage Location**: `runs/_registry/revisions.json`

**CON-0001 Compliance**: Revisions are append-only. Once a revision entry exists, it is never mutated or removed.

---

### WI-3: Update Atom Emission to Design Shape

**Goal**: Atoms include `file_uid`, `rev_id`, and `atom_fingerprint` per DS-EVID-0001.

**Modify schemas/atoms.py**:

```python
# New pattern: ATOM-{file_uid}-{rev_id}-L{line:04d}
ATOM_ID_PATTERN = re.compile(
    r"^ATOM-(?P<file_uid>F\d{4})-(?P<rev_id>R\d{4})-L(?P<line_no>\d{4})$"
)

class LineAtom(BaseModel):
    atom_id: str
    atom_fingerprint: str = Field(min_length=64, max_length=64)
    file_uid: str         # NEW
    rev_id: str           # NEW
    line_no: int
    sequence_index: int   # NEW (position in file)
    section_id: str
    sha256: str           # Line content hash
    text: str
```

**Modify atom_emitter.py**:

```python
def emit_atoms(
    file_uid: str,      # Changed from file_id
    rev_id: str,        # NEW parameter
    file_path: Path,
    sections: FileSections,
    output_path: Path,
    evidence_output: Path,
) -> int:
    # ... normalize content ...

    occurrence_counter = Counter()  # For fingerprint disambiguation
    nonblank_prev = None
    nonblank_next_cache = _compute_next_nonblank(lines)

    for idx, text in enumerate(lines):
        line_no = idx + 1
        normalized_text = _normalize_for_fingerprint(text)
        occurrence_index = occurrence_counter[normalized_text]
        occurrence_counter[normalized_text] += 1

        # ALG-CORE-0004: BuildAtomFingerprint
        fingerprint = _build_atom_fingerprint(
            content=text,
            prev_nonblank=nonblank_prev,
            next_nonblank=nonblank_next_cache[idx],
            occurrence_index=occurrence_index
        )

        atom_id = f"ATOM-{file_uid}-{rev_id}-L{line_no:04d}"

        atom = LineAtom(
            atom_id=atom_id,
            atom_fingerprint=fingerprint,
            file_uid=file_uid,
            rev_id=rev_id,
            line_no=line_no,
            sequence_index=idx,
            section_id=section_id,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            text=text,
        )
```

**New helper function**:

```python
def _build_atom_fingerprint(
    content: str,
    prev_nonblank: str | None,
    next_nonblank: str | None,
    occurrence_index: int
) -> str:
    """ALG-CORE-0004 implementation"""
    normalized = _normalize_for_fingerprint(content)
    prev = _normalize_for_fingerprint(prev_nonblank or "")
    next_ = _normalize_for_fingerprint(next_nonblank or "")

    payload = "\n---\n".join([prev, normalized, next_, str(occurrence_index)])
    return hashlib.sha256(payload.encode()).hexdigest()
```

---

### WI-4: Compatibility Layer

**Goal**: Support reading old IDs by mapping legacy formats to new schema with default rev_id=R0001.

**New File**: `scripts/spec_manager/spec_manager/core/compat.py`

```python
LEGACY_ATOM_PATTERN = re.compile(r"^ATOM-(?P<file_id>F\d{4})-L(?P<line_no>\d{4})$")

def parse_atom_id(atom_id: str) -> dict:
    """Parse atom ID, supporting both legacy and new formats."""
    # Try new format first
    new_match = ATOM_ID_PATTERN.fullmatch(atom_id)
    if new_match:
        return {
            "file_uid": new_match.group("file_uid"),
            "rev_id": new_match.group("rev_id"),
            "line_no": int(new_match.group("line_no")),
            "format": "v2"
        }

    # Fall back to legacy format
    legacy_match = LEGACY_ATOM_PATTERN.fullmatch(atom_id)
    if legacy_match:
        return {
            "file_uid": legacy_match.group("file_id"),  # file_id -> file_uid
            "rev_id": "R0001",  # Default revision for legacy
            "line_no": int(legacy_match.group("line_no")),
            "format": "v1"
        }

    raise ValueError(f"Invalid atom ID format: {atom_id}")

def upgrade_atom_id(legacy_id: str) -> str:
    """Convert legacy atom ID to new format."""
    parsed = parse_atom_id(legacy_id)
    if parsed["format"] == "v2":
        return legacy_id
    return f"ATOM-{parsed['file_uid']}-{parsed['rev_id']}-L{parsed['line_no']:04d}"
```

---

## Updated Manifest Schemas

### files.json (Updated)

```json
{
  "schema_version": "2.0",
  "run_id": "run_001",
  "created_at": "2024-01-15T10:30:00Z",
  "files": {
    "F0001": {
      "file_uid": "F0001",
      "rev_id": "R0001",
      "relpath": "requirements/core.md",
      "sha256": "abc123...",
      "line_count": 150,
      "created_at": "2024-01-15T10:30:00Z"
    }
  }
}
```

### atoms.jsonl (Updated Line Format)

```json
{
  "atom_id": "ATOM-F0001-R0001-L0042",
  "atom_fingerprint": "deadbeef...",
  "file_uid": "F0001",
  "rev_id": "R0001",
  "line_no": 42,
  "sequence_index": 41,
  "section_id": "SEC-F0001-0001",
  "sha256": "...",
  "text": "The system SHALL support..."
}
```

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `scripts/spec_manager/spec_manager/core/id_registry.py` | NEW | FileUidRegistry, RevisionRegistry, ALG-CORE-0001/0002 |
| `scripts/spec_manager/spec_manager/core/compat.py` | NEW | Legacy ID parsing and upgrade utilities |
| `scripts/spec_manager/spec_manager/schemas/atoms.py` | MODIFY | Add rev_id, atom_fingerprint; update pattern |
| `scripts/spec_manager/spec_manager/schemas/files.py` | MODIFY | Add rev_id, schema_version fields |
| `scripts/spec_manager/spec_manager/refinement/workflows/atom_emitter.py` | MODIFY | Add fingerprint calculation, rev_id parameter |
| `scripts/spec_manager/spec_manager/refinement/workspace/manager.py` | MODIFY | Registry loading/saving, use allocators |

---

## Test Plan

### Unit Tests

1. **test_file_uid_registry.py**
   - `test_allocate_new_file_uid` - Fresh allocation increments sequence
   - `test_allocate_existing_returns_same_uid` - Idempotent on same path
   - `test_registry_persistence_roundtrip` - Save/load preserves state
   - `test_concurrent_paths_get_unique_uids` - No collisions

2. **test_revision_registry.py**
   - `test_allocate_new_revision` - Fresh content gets R0001
   - `test_same_content_returns_same_revision` - Idempotent per CON-0001
   - `test_modified_content_increments_revision` - R0001 -> R0002
   - `test_revisions_append_only` - Old revisions never removed

3. **test_atom_fingerprint.py**
   - `test_identical_lines_different_context_different_fingerprint`
   - `test_same_line_same_context_same_fingerprint`
   - `test_occurrence_index_disambiguates_duplicates`

4. **test_compat.py**
   - `test_parse_legacy_atom_id` - ATOM-F0001-L0042 -> rev_id=R0001
   - `test_parse_new_atom_id` - ATOM-F0001-R0002-L0042 parsed correctly
   - `test_upgrade_atom_id` - Legacy format converted to new

### Integration Tests

1. **test_atom_emitter_with_registry.py**
   - Verify atoms emitted with correct file_uid, rev_id, fingerprint
   - Verify re-run with unchanged content produces same rev_id
   - Verify content change produces new rev_id

---

## Implementation Sequence

1. **Step 1**: Create `id_registry.py` with FileUidRegistry and RevisionRegistry
2. **Step 2**: Create `compat.py` with legacy parsing utilities
3. **Step 3**: Update `atoms.py` schema with new fields and pattern
4. **Step 4**: Update `files.py` schema with rev_id field
5. **Step 5**: Modify `atom_emitter.py` to compute fingerprints and accept rev_id
6. **Step 6**: Modify `manager.py` to use registry-based allocation
7. **Step 7**: Write unit tests for new modules
8. **Step 8**: Update existing tests for new atom format

---

## Constraints Addressed

| Constraint | Implementation |
|------------|----------------|
| CON-0001 | Revisions append-only; no mutation of existing entries |
| CON-0008 | File UIDs stable across runs via persistent registry |
| INV-ACC-0001 | Atom IDs deterministic from file_uid + rev_id + line |
| INV-ACC-0002 | Atom fingerprints enable cross-revision matching |
