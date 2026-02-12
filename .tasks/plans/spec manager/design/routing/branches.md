# Branches

**Classification**: Structural (multi-branch management)
**Package**: `spec_manager/branches/`
**Files**: 11 + projections/
**Role**: Branch organization system maintaining parallel representations (algorithmic/architectural/analysis). Manages promotion workflows and horizontal/vertical slices.

---

## System

### Branch Manager
**Modules**: `types.py`, `layout.py`, `atoms.py`, `slices.py`, `manager.py`, `gap_detection.py`, `compliance.py`, `promotion.py`, `analysis.py`, `collapse.py`, `downward_flow.py`, `pins.py`, `projections/`
**Purpose**: Full branch lifecycle — create, organize, promote, collapse.
**Surface API**:
- `BranchManager.create_branch(kind: BranchKind) -> Branch`
- `BranchLayout.get_branch_root(kind) -> Path`
- `AtomRegistry.add(atom)`, `query(selector) -> list[Atom]`
- `SliceNavigator.get_slice(id) -> VerticalSlice`
- `PromotionEngine.promote(atoms) -> PromotionResult`
- `CollapseEngine.collapse(atoms) -> CollapseResult`
- `GapDetector.detect(atoms) -> list[GapItem]`
- `DownwardFlowEngine.trace(issue) -> DownwardTraceResult`
- `PinRegistry.get_pins(atom) -> list[Pin]`
**Dependencies**: `compliance.detection`, `compliance.promotion`, `analysis.adjacency`, `pin_functions`
**Consumers**: `orchestration.promotion_loop`, `branches.projections`

**Note**: Bidirectional dependency with `compliance` (12 total imports). Branches need compliance for gating; compliance needs branch atoms for analysis.
