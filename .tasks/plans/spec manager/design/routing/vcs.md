# VCS

**Classification**: Structural (version control)
**Package**: `spec_manager/vcs/`
**Files**: 3
**Role**: Version control abstraction and worktree management.

---

## Systems

### VCS Operations
**Module**: `operations.py`
**Purpose**: VCS abstraction layer. Protocol-based so git can be swapped.
**Surface API**:
- `VcsOperations` — abstract protocol
- `GitVcs` — git implementation
**Dependencies**: None
**Consumers**: `vcs.worktree`, `orchestration.pdd_lifecycle`, CLI

### Worktree Manager
**Module**: `worktree.py`
**Purpose**: 6-worktree hierarchy (L1/L2/L3 dirty+clean pairs).
**Surface API**:
- `WorktreeManager(vcs, root).setup()` — create worktree structure
- Merge, batch, propagate operations
**Dependencies**: `vcs.operations`, `core.layer_types`
**Consumers**: `orchestration.pdd_lifecycle`, CLI
