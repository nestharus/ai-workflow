# Stale Linter Management: Comprehensive Analysis

## Executive Summary

The stale linter management system is a sophisticated mechanism designed to prevent deadlocks and premature termination when PROJECT-scoped linters cannot run due to locked targets (files under investigation). The system uses three states (STALE/SUSPENDED, PENDING_REFRESH, and ACTIVE) and employs granular gating to defer only targets whose required linter is unavailable while allowing unrelated targets to proceed.

**Key Insight:** This is fundamentally a **selective suspension** system that prevents the algorithm from declaring false success when errors exist but cannot be refreshed, while avoiding blocking unrelated work.

---

## 1. All stale_linters Read/Write Locations

### 1.1 Initialization (WRITE)
**Location:** Node F3
**Line:** 12
**Operation:** `Initialize stale_linters = empty (linter -> STALE/SUSPENDED + blocked_by)`
**Purpose:** Set up the tracking structure at workflow start. Each entry maps a linter to its state (STALE or PENDING_REFRESH) and the set of targets blocking it.

**Data Structure:**
```python
stale_linters: Dict[Linter, StaleState]

StaleState = {
    "status": Literal["STALE", "PENDING_REFRESH"],
    "blocked_by": Set[Target]  # Files preventing linter from running
}
```

### 1.2 Investigation Completion - blocked_by Update (WRITE)
**Location:** Node I2A
**Line:** 23
**Operation:** `Update stale_linters blocked_by (remove completed target)`
**Purpose:** When an investigation completes and releases its lock, remove that target from all stale linters' blocked_by sets.
**Trigger:** Investigation future completion (any status)

**Pseudocode:**
```python
def on_investigation_complete(completed_target):
    for linter in stale_linters:
        stale_linters[linter].blocked_by.discard(completed_target)
```

### 1.3 Investigation Completion - Transition to PENDING_REFRESH (WRITE)
**Location:** Nodes I2B, I2C
**Lines:** 24-25
**Operation:** `Mark unblocked stale_linters as PENDING_REFRESH (blocked_by empty); keep excluded until refreshed`
**Purpose:** When a linter's blocked_by becomes empty, transition it from STALE to PENDING_REFRESH to force a refresh-only tick.
**Trigger:** After updating blocked_by, check if any linter now has empty blocked_by set.

**State Transition:** `STALE/SUSPENDED` → `PENDING_REFRESH`

**Pseudocode:**
```python
def check_unblocked_linters():
    newly_unblocked = []
    for linter, state in stale_linters.items():
        if len(state.blocked_by) == 0 and state.status == "STALE":
            state.status = "PENDING_REFRESH"
            newly_unblocked.append(linter)
    return newly_unblocked
```

### 1.4 ErrorCheck - PENDING_REFRESH Detection (READ)
**Location:** Node NREF
**Line:** 65
**Operation:** `Any stale linter PENDING_REFRESH? (blocked_by empty)`
**Purpose:** Check if any linter needs a refresh-only tick before normal processing can continue.
**Trigger:** Start of ErrorCheck subgraph, after investigation completion handling.

**Effect:** If yes, skip agent phase and go directly to ProcessLinters (refresh-only tick).

### 1.5 ErrorCheck - Actionable Errors Filtering (READ)
**Location:** Node O0
**Line:** 73
**Operation:** `actionable_errors_by_linter = errors_by_linter excluding stale_linters AND unlintable`
**Purpose:** Exclude diagnostics from stale linters when building actionable error set. Stale diagnostics are not trustworthy.
**Trigger:** Every main loop tick when determining what work is actionable.

**Critical Invariant:** Stale linter errors are NEVER actionable until the linter is refreshed.

### 1.6 ErrorCheck - Pending Deferral Gate (READ)
**Location:** Node O4A
**Line:** 76
**Operation:** `pending non-empty AND stale_linters empty?`
**Purpose:** Only dispatch pending investigations when no linters are stale (ensures context is current).
**Trigger:** When pending_investigation_targets is not empty.

**Logic:** If stale_linters is empty, it's safe to dispatch deferred investigations. Otherwise, wait for refresh.

### 1.7 AgentPhase - Agent Input Building (READ)
**Location:** Node R2
**Line:** 103
**Operation:** `Build agent input: agent_input_files contents + relevant errors + project errors (exclude stale_linters)`
**Purpose:** Ensure agent receives only actionable (non-stale) diagnostics.
**Trigger:** When preparing to invoke lint-fixer agent.

**Key Concept #4 Reference:** "Agent receives actionable file content + project_context_files when <PROJECT> errors are actionable + relevant errors (exclude stale_linters)"

### 1.8 ProcessLinters - PROJECT Linter Wake-Up (WRITE)
**Location:** Nodes AI0A
**Line:** 127
**Operation:** `Clear stale_linters entry for this linter (wake-up is post-refresh)`
**Purpose:** Remove linter from stale_linters after successfully running it.
**Trigger:** When PROJECT linter runs successfully (blocking files empty or excludable).

**State Transition:** `PENDING_REFRESH` → `ACTIVE` (removed from stale_linters)

**Critical:** This happens AFTER the linter has been run, confirming diagnostics are fresh.

### 1.9 ProcessLinters - PROJECT Linter Suspension (WRITE)
**Location:** Nodes AG2, AG2A
**Lines:** 133-134
**Operation:** `Skip project run; mark this linter's diagnostics as STALE/SUSPENDED (blocked by blocking_files_for_linter)`
**Purpose:** When PROJECT linter cannot run due to locked files, mark it as stale.
**Trigger:** When blocking_files_for_linter is non-empty AND linter cannot exclude them.

**State Transition:** `ACTIVE` → `STALE/SUSPENDED`

**Pseudocode:**
```python
def suspend_project_linter(linter, blocking_files):
    stale_linters[linter] = StaleState(
        status="STALE",
        blocked_by=blocking_files
    )
```

### 1.10 UpdateState - Verified Error Target Extraction (READ)
**Location:** Node BG0
**Line:** 156
**Operation:** `verified_error_targets = extract targets from errors_by_linter excluding stale_linters`
**Purpose:** When confirming stalled targets, only consider non-stale errors as verified.
**Trigger:** After ProcessLinters completes, when building stalled target set.

**Why:** Stale diagnostics may be outdated, so we cannot trust them for stall detection.

### 1.11 UpdateState - Granular Gating (READ)
**Location:** Node BG2A
**Line:** 161
**Operation:** `Granular gating: partition stalled_targets_ready into targets_to_defer and targets_to_submit (target required_linter in stale_linters)`
**Purpose:** Only defer targets whose specific required linter is stale. Submit all others.
**Trigger:** When stalled targets are detected and ready for investigation.

**This is the CRITICAL fix from feedback item #2** (Async State Blocking violation).

**Pseudocode:**
```python
def partition_stalled_targets(stalled_targets_ready):
    targets_to_defer = []
    targets_to_submit = []

    for target in stalled_targets_ready:
        required_linter = get_required_linter(target, errors_by_linter)
        if required_linter in stale_linters:
            targets_to_defer.append(target)
        else:
            targets_to_submit.append(target)

    return targets_to_defer, targets_to_submit
```

**Definition of required_linter:** The linter producing the remaining actionable errors for this target. If multiple linters have errors for a target, the algorithm must determine which one to use (likely: any/all stale = defer, or: primary linter based on error severity).

### 1.12 Termination Checks (READ)

**Location 1:** Node Q2
**Line:** 91
**Operation:** `actionable_errors_by_linter empty AND stale_linters empty?`
**Purpose:** Prevent premature success when only stale errors exist.
**Fixed by:** Feedback item #4 (Premature Success Declaration)

**Location 2:** Node Q3
**Line:** 93
**Operation:** `stale_linters non-empty OR pending_investigation_targets non-empty?`
**Purpose:** Prevent false invariant violation when stale linters exist.
**Related to:** Feedback item #5 (False Invariant Violation)

**Location 3:** Node BH
**Line:** 172
**Operation:** `errors_by_linter empty AND stale_linters empty AND investigation_futures empty?`
**Purpose:** Final termination condition - no errors, no stale linters, no pending investigations.

### 1.13 Key Concept References (READ - Implicit)

**Concept #7:** "Investigation payload includes context - Provide per-target error_snapshot (errors_by_linter excluding stale_linters)"
**Concept #13:** "Granular stale-linter gating - Only defer stalled targets whose required_linter is STALE/SUSPENDED/PENDING_REFRESH"
**Concept #18:** "Termination uses actionable errors - exit when actionable_errors_by_linter is empty AND stale_linters empty"
**Concept #19:** "Post-lint escalation - Only submit stalled_targets_ready after verifying errors persist (exclude stale_linters)"

---

## 2. State Transitions

### 2.1 Complete State Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         ACTIVE                              │
│         (linter not in stale_linters)                       │
│                                                             │
│  • Linter can run normally                                  │
│  • Diagnostics are actionable                               │
│  • Errors are sent to agent                                 │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ [PROJECT linter cannot run due to locked files]
                  │ Location: AG2 → AG2A
                  │ Trigger: blocking_files_for_linter non-empty
                  │          AND linter cannot exclude them
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                   STALE/SUSPENDED                           │
│       (in stale_linters, blocked_by = {targets})            │
│                                                             │
│  • Linter cannot run (blocked by locked files)              │
│  • Diagnostics are EXCLUDED from actionable_errors          │
│  • Errors are NOT sent to agent                             │
│  • Errors are NOT used for stall detection                  │
│  • Errors are NOT included in investigation payloads        │
│  • blocked_by tracks which targets prevent linter from      │
│    running (subset of investigation_futures)                │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ [Investigation completes, blocked_by becomes empty]
                  │ Location: I2A → I2B → I2C
                  │ Trigger: Investigation completion removes target
                  │          from blocked_by, resulting in empty set
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    PENDING_REFRESH                          │
│     (in stale_linters, status=PENDING_REFRESH,              │
│      blocked_by = {})                                       │
│                                                             │
│  • Linter CAN physically run now (no locks)                 │
│  • Diagnostics are STILL EXCLUDED from actionable_errors    │
│  • Linter is WAITING for a refresh-only tick                │
│  • Forces NREF → NREF0 path (skip agent, go to linter)      │
│  • Prevents dispatching pending investigations (O4A gate)   │
│  • Granular gating still defers targets requiring this      │
│    linter (BG2A)                                            │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ [Refresh-only tick runs linter successfully]
                  │ Location: NREF → NREF0 → AC → ProcessLinters
                  │          → AI0A
                  │ Trigger: Linter executes and updates diagnostics
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                         ACTIVE                              │
│         (removed from stale_linters)                        │
│                                                             │
│  • Linter diagnostics are now fresh                         │
│  • Errors become actionable again                           │
│  • Deferred targets (from pending_investigation_targets)    │
│    can now be dispatched (if no other stale linters remain) │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Detailed State Properties

#### ACTIVE State
**Characteristics:**
- Linter key is NOT present in `stale_linters` dict
- Can run in current tick
- Diagnostics are included in `actionable_errors_by_linter`
- Errors contribute to `verified_error_targets`
- Errors are passed to agent input
- Errors are included in investigation payloads

**Entry Conditions:**
1. Initial state (all linters start ACTIVE)
2. Successful linter execution after PENDING_REFRESH (AI0A)
3. FILE-scoped linter (never becomes stale)

**Exit Conditions:**
1. PROJECT linter blocked by locked files (→ STALE/SUSPENDED)

#### STALE/SUSPENDED State
**Characteristics:**
- Entry exists in `stale_linters` with `status = "STALE"`
- `blocked_by` is a non-empty set of targets (files under investigation)
- Cannot run until `blocked_by` becomes empty
- Diagnostics are excluded everywhere:
  - `actionable_errors_by_linter` (O0)
  - Agent input errors (R2)
  - Investigation payload errors (Key Concept #7)
  - `verified_error_targets` (BG0)
- Termination checks include `stale_linters empty` (Q2, BH)

**Entry Conditions:**
1. PROJECT linter scope (AG0)
2. `blocking_files_for_linter` is non-empty (locked targets exist)
3. Linter does NOT support excluding `blocking_files_for_linter` (AG1 → No)
4. Algorithm executes AG2 → AG2A

**Exit Conditions:**
1. Investigation completes, `blocked_by` becomes empty (→ PENDING_REFRESH)

**Why This State Exists:**
- Prevents using outdated diagnostics that may be invalidated by ongoing investigations
- Prevents deadlock where agent tries to act on errors it cannot fix (locked files)
- Maintains system invariant: never act on unverifiable information

#### PENDING_REFRESH State
**Characteristics:**
- Entry exists in `stale_linters` with `status = "PENDING_REFRESH"`
- `blocked_by` is EMPTY (locks released)
- Linter CAN physically run, but diagnostics are STILL not actionable
- Forces a refresh-only tick (NREF → NREF0)
- Blocks agent phase (O4A gate for pending investigations)
- Diagnostics remain excluded from actionable_errors (O0)
- Granular gating still defers targets requiring this linter (BG2A)

**Entry Conditions:**
1. Previously in STALE/SUSPENDED state
2. All targets in `blocked_by` completed investigation (I2A reduces blocked_by to empty)
3. Check at I2B detects empty `blocked_by`
4. I2C transitions to PENDING_REFRESH

**Exit Conditions:**
1. Refresh-only tick path executes (NREF → NREF0 → AC → ProcessLinters)
2. Linter runs successfully (reaches AI0A)
3. AI0A clears entry from `stale_linters` (→ ACTIVE)

**Why This State Exists:**
- Ensures diagnostics are refreshed BEFORE becoming actionable again
- Prevents race condition where stale diagnostics are used immediately after locks release
- Enforces temporal ordering: lock release → refresh → actionable
- Implements Key Concept #12: "Stale linter refresh gating"

### 2.3 State Transition Edge Cases

#### Case 1: Multiple Linters Stale Simultaneously
**Scenario:** PROJECT Linter A is blocked by file1.py, PROJECT Linter B is blocked by file2.py.

**Behavior:**
- Both enter STALE/SUSPENDED state with different `blocked_by` sets
- When file1.py investigation completes:
  - Linter A transitions to PENDING_REFRESH
  - Linter B remains STALE/SUSPENDED
- NREF check: "Any stale linter PENDING_REFRESH?" → Yes
- Refresh-only tick runs ALL linters (including Linter A)
- Linter A clears from stale_linters (→ ACTIVE)
- Linter B remains in stale_linters (still has file2.py in blocked_by)
- Next tick: NREF check → No, proceed to normal flow
- When file2.py completes, repeat process for Linter B

**Critical:** Refresh-only tick runs ALL configured linters, not just PENDING_REFRESH ones. This ensures complete diagnostic refresh.

#### Case 2: Investigation Completes During Agent Phase
**Scenario:** Agent is running when an investigation completes.

**Flow:**
1. Agent phase is executing (R → S → T → U)
2. Investigation completes asynchronously
3. Next loop tick (G) checks InvCheck first (H)
4. I2A updates `blocked_by`
5. I2B/I2C transition to PENDING_REFRESH if needed
6. Flow continues through investigator result processing (J branches)
7. Eventually reaches ErrorCheck subgraph (N)
8. NREF detects PENDING_REFRESH linter
9. Skips agent phase (NREF0 → AC), sets refresh-only mode
10. ProcessLinters runs and clears staleness

**No race condition:** State changes propagate on next tick.

#### Case 3: External Change While Linter is PENDING_REFRESH
**Scenario:** File watcher detects external change while linter is waiting for refresh.

**Flow:**
1. Linter is in PENDING_REFRESH state
2. External change detected at WAIT2 (→ EXT)
3. EXT: "detect externally modified files; set changed_files + project_changed"
4. EXT: "clear candidate_stalled_*; unlintable_targets -= changed_files"
5. EXT: "pending_investigation_targets -= changed_files"
6. EXT: "seen_hashes -= changed_files"
7. EXT → AC (enter ProcessLinters)

**Question:** Should EXT also clear PENDING_REFRESH linters?

**Analysis:** EXT path does NOT explicitly clear `stale_linters`. This seems like a potential bug:
- If the externally changed file was in `blocked_by` of a stale linter, the linter should be reevaluated
- However, since `blocked_by` is updated based on `investigation_futures`, and external changes don't affect investigations already in flight, this may be correct
- The PENDING_REFRESH linter will be cleared on next refresh-only tick regardless

**Verdict:** Not a bug, but PENDING_REFRESH state may persist one extra tick if external change happens. Benign because diagnostics remain excluded.

#### Case 4: Linter Becomes Stale While Already Stale
**Scenario:** AG2A called twice for same linter (should not happen, but defensive check).

**Expected Behavior:** Upsert operation (update or insert). If linter already in `stale_linters`, update `blocked_by` set.

**Implementation Consideration:**
```python
# Defensive upsert
if linter in stale_linters:
    stale_linters[linter].blocked_by.update(blocking_files_for_linter)
else:
    stale_linters[linter] = StaleState(
        status="STALE",
        blocked_by=blocking_files_for_linter
    )
```

---

## 3. Granular Gating Logic

### 3.1 Problem Statement (from Feedback #2)

**Original Defect:**
> BG2A checks if any linter is STALE (blocked). If yes, it defers ALL stalled_targets_ready into the pending queue. This means a lock on the Project Linter (caused by File A) prevents File B (which needs an available File Linter) from being submitted to the Investigator.

**Constraint Violated:** ASYNC STATE
**Fix Required:** Granular gating based on required_linter

### 3.2 Granular Gating Algorithm (BG2A)

**Input:** `stalled_targets_ready` (set of targets with confirmed stalled errors)

**Output:**
- `targets_to_defer` (targets whose required_linter is stale)
- `targets_to_submit` (targets whose required_linter is active)

**Pseudocode:**
```python
def partition_stalled_targets(stalled_targets_ready, errors_by_linter, stale_linters):
    targets_to_defer = []
    targets_to_submit = []

    for target in stalled_targets_ready:
        # Determine which linter is required to fix this target
        required_linter = compute_required_linter(target, errors_by_linter)

        # Check if required linter is stale (includes STALE and PENDING_REFRESH)
        if required_linter in stale_linters:
            targets_to_defer.append(target)
        else:
            targets_to_submit.append(target)

    return targets_to_defer, targets_to_submit


def compute_required_linter(target, errors_by_linter):
    """
    Determine which linter is "required" to fix this target.

    Strategy options:
    1. Primary linter (first alphabetically, or by priority)
    2. All linters (defer if ANY linter for this target is stale)
    3. Severity-based (linter with highest severity error)
    4. Scope-based (PROJECT linters take precedence)

    Key Concept #13 suggests: "required_linter = the linter producing
    the remaining actionable errors for the target"
    """

    # Extract linters that have errors for this target
    linters_for_target = []
    for linter, diagnostics_by_target in errors_by_linter.items():
        if target in diagnostics_by_target:
            linters_for_target.append(linter)

    # Strategy: Return first linter (simple, deterministic)
    # Alternative: Return all linters and check if any are stale
    if linters_for_target:
        return linters_for_target[0]
    else:
        raise ValueError(f"No linters have errors for {target} (should not happen)")
```

### 3.3 Deferred vs Submitted Target Handling

#### Deferred Targets (targets_to_defer)
**Location:** BG2B
**Operation:** `Upsert pending_investigation_targets for targets_to_defer (store {error_snapshot, agent_output_snapshot})`

**Purpose:** Store investigation context for later submission when required linter becomes active.

**Data Structure:**
```python
pending_investigation_targets: Dict[Target, InvestigationContext]

InvestigationContext = {
    "error_snapshot": ErrorsByLinter,      # errors_by_linter at deferral time
    "agent_output_snapshot": AgentOutput   # agent output from stall tick
}
```

**Lifecycle:**
1. Target deferred at BG2B (stored in `pending_investigation_targets`)
2. Cleared from `candidate_stalled_targets` (BG2B)
3. Required linter transitions STALE → PENDING_REFRESH → ACTIVE
4. At O4A, check `pending non-empty AND stale_linters empty?`
5. If yes, O4B: Reserve in `investigation_futures` and dispatch using stored context
6. Remove from `pending_investigation_targets`

**Critical Fix (Feedback #7 - Context Loss):**
> BG2B defers targets into pending_investigation_targets (a list of paths). When these are eventually submitted via O4B, the "last agent output" (from the tick they were stalled) is lost or stale.

**Solution:** Store full context `{error_snapshot, agent_output_snapshot}` in `pending_investigation_targets`.

#### Submitted Targets (targets_to_submit)
**Location:** BG3 → BG4 → BG4A
**Operation:** Immediate submission to investigator

**Flow:**
1. BG3: Build investigation context using:
   - Stored context from `pending_investigation_targets` if present (target was previously deferred)
   - Current tick context otherwise: `{error_snapshot: errors_by_linter, agent_output_snapshot: from this tick}`
2. BG3A: Snapshot start hashes/fingerprint NOW
3. BG4: Add to `investigation_futures` (reserve/lock targets)
4. BG4A: Dispatch async
5. BG5: Remove from `pending_investigation_targets`, clear `candidate_stalled_targets`, clear `passed_linters`

### 3.4 Granular Gating Interaction with PENDING_REFRESH

**Key Question:** Are PENDING_REFRESH linters treated as stale in granular gating?

**Answer:** YES (from Key Concept #13)
> "Only defer stalled targets whose required_linter is STALE/SUSPENDED/PENDING_REFRESH"

**Rationale:**
- PENDING_REFRESH linters have stale diagnostics (not refreshed yet)
- If investigation uses stale diagnostics, investigator may produce incorrect analysis
- Safer to defer until diagnostics are refreshed

**Implementation:**
```python
def is_linter_stale_for_gating(linter, stale_linters):
    """
    Check if linter should be considered stale for granular gating.
    Includes both STALE and PENDING_REFRESH states.
    """
    return linter in stale_linters  # Presence in dict indicates not fully active
```

### 3.5 Edge Cases in Granular Gating

#### Edge Case 1: Target Has Errors from Both Stale and Active Linters
**Scenario:** Target has error from Linter A (STALE) and Linter B (ACTIVE).

**Question:** Should target be deferred or submitted?

**Options:**
1. **Conservative (Defer):** Defer if ANY linter is stale
2. **Permissive (Submit):** Submit if AT LEAST ONE linter is active
3. **Primary-based:** Use primary/required linter determination

**Recommended:** Option 1 (Conservative)
- Ensures investigator has complete context
- Avoids partial information
- Aligns with Key Concept #13 interpretation

**Implementation:**
```python
def compute_required_linters(target, errors_by_linter):
    """Return ALL linters with errors for this target."""
    linters_for_target = []
    for linter, diagnostics_by_target in errors_by_linter.items():
        if target in diagnostics_by_target:
            linters_for_target.append(linter)
    return linters_for_target

def should_defer_target(target, errors_by_linter, stale_linters):
    required_linters = compute_required_linters(target, errors_by_linter)
    # Defer if ANY required linter is stale
    return any(linter in stale_linters for linter in required_linters)
```

#### Edge Case 2: Required Linter Becomes Stale After Target Is Submitted
**Scenario:** Target submitted at BG4A, then its required linter becomes stale on next tick.

**Analysis:**
- Investigation is already in flight (in `investigation_futures`)
- Linter becoming stale adds target to `blocked_by` at AG2A
- When investigation completes, I2A removes target from `blocked_by`
- Linter may transition to PENDING_REFRESH if `blocked_by` becomes empty

**Behavior:** No issue. Investigation completes with snapshot from submission time. Linter staleness does not affect in-flight investigations.

#### Edge Case 3: <PROJECT> Target Deferral
**Scenario:** `<PROJECT>` pseudo-target is stalled, and the PROJECT linter is PENDING_REFRESH.

**Question:** Should <PROJECT> be deferred?

**Answer:** YES
- <PROJECT> errors come from PROJECT linters by definition
- If PROJECT linter is PENDING_REFRESH, its diagnostics are stale
- Defer until linter is refreshed

**Special Case:** Key Concept #20
> "<PROJECT> UNLINTABLE implication - Abort the workflow (global failure)"

If <PROJECT> is deferred indefinitely (required linter never becomes active), this is a different failure mode than UNLINTABLE. Should there be a timeout or deadlock detection?

**Recommendation:** Add staleness cycle detection (separate from ping-pong detection).

---

## 4. Interaction with Investigation Completion

### 4.1 Investigation Completion Flow with Staleness

**Entry Point:** Node H (InvCheck subgraph)
**Trigger:** `Any investigations completed?`

**Complete Flow:**
```
H (check)
→ I (get result)
→ I2 (remove from futures)
→ I2A (update blocked_by)
→ I2B (check unblocked)
→ I2C (mark PENDING_REFRESH) [if unblocked]
→ J (process investigator status)
```

### 4.2 blocked_by Update Logic (I2A)

**Purpose:** Remove completed target from all stale linters' blocked_by sets.

**Pseudocode:**
```python
def update_blocked_by_on_completion(completed_target, stale_linters):
    """
    Called when an investigation completes (any status).
    Removes the target from all linters' blocked_by sets.
    """
    for linter, state in stale_linters.items():
        if completed_target in state.blocked_by:
            state.blocked_by.remove(completed_target)

    # Note: This happens BEFORE checking investigator status
    # Even if investigation fails/is stale, we update blocked_by
    # because the lock is released regardless
```

**Critical Timing:** This happens BEFORE processing investigator result (J branches). Lock release is immediate and unconditional.

### 4.3 Unblocking Detection (I2B, I2C)

**Purpose:** Check if any linter's blocked_by became empty and transition to PENDING_REFRESH.

**Pseudocode:**
```python
def check_and_mark_pending_refresh(stale_linters):
    """
    After updating blocked_by, check for newly unblocked linters.
    Returns list of linters transitioned to PENDING_REFRESH.
    """
    newly_unblocked = []

    for linter, state in stale_linters.items():
        # Only transition if currently STALE and now unblocked
        if state.status == "STALE" and len(state.blocked_by) == 0:
            state.status = "PENDING_REFRESH"
            newly_unblocked.append(linter)
            # Note: Keep entry in stale_linters dict
            # Will be removed at AI0A after refresh

    return newly_unblocked
```

**Key Insight:** "keep excluded until refreshed" (line 25)
- Linter remains in `stale_linters` dict
- Diagnostics remain excluded from actionable_errors
- Forces refresh-only tick before becoming actionable

### 4.4 Investigator Status Processing (J branches)

After updating staleness state, the algorithm processes the investigator result:

**J → MODIFIED:**
- J0: Check if safe to apply (hash unchanged since investigation start)
- If No → JDROP (discard as stale, treat as external change)
- If Yes:
  - J1: Check for actual diff
  - If No → Mark UNLINTABLE (Investigator lied)
  - If Yes → K: Record new hash, set changed_files/project_changed

**J → NO_OP:**
- NOOP0: Check if safe to trust (hash unchanged)
- If No → JDROP
- If Yes → Mark target UNLINTABLE, remove diagnostics

**J → FAILURE:**
- FAIL0: Check if safe to trust
- If No → JDROP
- If Yes → Mark target UNLINTABLE, remove diagnostics

**JDROP path:** "set changed_files/project_changed from current state; clear candidate_stalled_*; unlintable_targets -= changed_files; pending_investigation_targets -= changed_files; seen_hashes -= changed_files"

**Critical:** JDROP does NOT mention clearing `stale_linters` or updating `blocked_by` again. This is correct because:
1. blocked_by was already updated at I2A (lock released)
2. Stale linters will be refreshed on next tick via PENDING_REFRESH mechanism
3. Treating as external change (EXT path behavior) is sufficient

### 4.5 Refresh-Only Tick (NREF, NREF0)

**Entry:** Node N (start of ErrorCheck)
**Condition:** `Any stale linter PENDING_REFRESH? (blocked_by empty)`

**If Yes:**
```
NREF → NREF0 (Refresh-only tick)
```

**NREF0 Actions:**
```
set changed_files = empty
set project_changed = false
set candidate_stalled_files = empty
set candidate_stalled_targets = empty
```

**Effect:** Skip agent phase entirely, go directly to ProcessLinters (AC).

**Why these settings?**
- `changed_files = empty`: No files changed (we're just refreshing diagnostics)
- `project_changed = false`: Project config didn't change
- `candidate_stalled_*` = empty: Not running agent, so no stalls to detect

**Then:** ProcessLinters runs all linters
- PROJECT linters with PENDING_REFRESH status will run (no blocked_by)
- Reach AI0A: "Clear stale_linters entry for this linter"
- Linter transitions to ACTIVE

**Next tick:** NREF check will be false, normal processing resumes.

### 4.6 Pending Investigation Dispatch Gate (O4A, O4B)

**Location:** Node O4A
**Condition:** `pending non-empty AND stale_linters empty?`

**Purpose:** Only dispatch deferred investigations when ALL linters are active (no stale linters).

**Why?**
- Deferred investigations have stored context from when they were stalled
- If new linters became stale since deferral, context may be incomplete
- Wait until all linters are active to ensure consistent state

**If condition is true:**
```
O4B: Reserve pending in investigation_futures (snapshot start hashes/fingerprint NOW);
     dispatch async using stored {error_snapshot, agent_output_snapshot};
     clear pending_investigation_targets
```

**Then:** Loop back to G (start next tick)

**Critical (Feedback #8 - Race Condition):**
> The flow implies "Submit async" then "Add to investigation_futures". If "Submit async" is non-blocking, the Main Loop G might tick again before the target is added to investigation_futures.

**Fix:** Reserve synchronously BEFORE dispatch.

**Corrected O4B:**
```python
def dispatch_pending_investigations(pending_investigation_targets, investigation_futures):
    targets = list(pending_investigation_targets.keys())

    # 1. Snapshot start hashes NOW (synchronous)
    start_snapshots = {}
    for target in targets:
        start_snapshots[target] = snapshot_target_now(target)

    # 2. Reserve in investigation_futures (synchronous)
    for target in targets:
        investigation_futures[target] = {
            "start_snapshot": start_snapshots[target],
            "future": None  # Placeholder, will be set below
        }

    # 3. Dispatch async (non-blocking)
    for target in targets:
        context = pending_investigation_targets[target]
        future = dispatch_investigation_async(
            target=target,
            error_snapshot=context.error_snapshot,
            agent_output_snapshot=context.agent_output_snapshot
        )
        investigation_futures[target]["future"] = future

    # 4. Clear pending (synchronous)
    pending_investigation_targets.clear()
```

---

## 5. Potential Simplifications

### 5.1 Simplification Opportunity: Merge STALE and PENDING_REFRESH

**Current Design:** Two distinct states (STALE/SUSPENDED, PENDING_REFRESH)

**Alternative:** Single STALE state with a "needs_refresh" flag

**Proposed:**
```python
StaleState = {
    "blocked_by": Set[Target],
    "needs_refresh": bool  # True if blocked_by was non-empty and now is empty
}
```

**State Logic:**
```python
# Mark stale
stale_linters[linter] = StaleState(blocked_by={targets}, needs_refresh=False)

# On completion
for linter in stale_linters:
    stale_linters[linter].blocked_by.discard(completed_target)
    if len(stale_linters[linter].blocked_by) == 0:
        stale_linters[linter].needs_refresh = True

# NREF check
any(state.needs_refresh for state in stale_linters.values())
```

**Pros:**
- Simpler conceptual model (one state variable)
- Clearer that PENDING_REFRESH is just a phase of STALE

**Cons:**
- Loses explicit state labeling (STALE vs PENDING_REFRESH)
- May be harder to debug (less visible state)

**Verdict:** Minor simplification, not worth changing unless refactoring entire system.

### 5.2 Simplification Opportunity: Unified Deferral Mechanism

**Current Design:** Two deferral paths
1. Granular gating deferral (BG2B) → `pending_investigation_targets`
2. Pending dispatch gate (O4A) → wait until `stale_linters empty`

**Alternative:** Single pending queue with priority/scheduling

**Proposed:**
```python
class PendingInvestigation:
    target: Target
    context: InvestigationContext
    defer_reason: Literal["stale_linter", "other"]
    can_dispatch: Callable[[], bool]  # Custom dispatch condition
```

**Pros:**
- More general deferral mechanism
- Could support other deferral reasons in future
- Clearer separation between "why deferred" and "when to dispatch"

**Cons:**
- More complex abstraction
- Current design is simple and correct
- No clear future need for other deferral reasons

**Verdict:** Over-engineering. Current design is sufficient.

### 5.3 Simplification Opportunity: Automatic required_linter Detection

**Current Design:** Algorithm must compute `required_linter` for each target during granular gating.

**Alternative:** Store `required_linter` in error data structure when errors are recorded.

**Proposed:**
```python
errors_by_linter: Dict[Linter, Dict[Target, List[Diagnostic]]]

# Add reverse index
errors_by_target: Dict[Target, Dict[Linter, List[Diagnostic]]]

def get_required_linter(target):
    linters = list(errors_by_target[target].keys())
    return linters[0]  # Or apply priority logic
```

**Pros:**
- Avoid re-computing on every granular gating check
- More efficient (O(1) lookup vs O(L*T) iteration)

**Cons:**
- Requires maintaining two indexes (errors_by_linter, errors_by_target)
- Adds complexity to error update logic
- Memory overhead

**Verdict:** Premature optimization. Wait for performance profiling.

### 5.4 Simplification Opportunity: Eliminate PENDING_REFRESH State

**Current Design:** PENDING_REFRESH forces a refresh-only tick before diagnostics become actionable.

**Alternative:** Allow linters to become immediately actionable when `blocked_by` is empty. Use version/epoch tagging on diagnostics to track freshness.

**Proposed:**
```python
class Diagnostics:
    errors: List[Error]
    epoch: int  # Incremented on each linter run

# When linter is stale, mark current epoch as stale
stale_epochs[linter] = current_epoch[linter]

# When using diagnostics, check if epoch is stale
if current_epoch[linter] == stale_epochs[linter]:
    # Diagnostics are stale, exclude
else:
    # Diagnostics are fresh, include
```

**Pros:**
- No need for special PENDING_REFRESH state
- More fine-grained staleness tracking
- Could support partial refreshes

**Cons:**
- More complex epoch tracking
- Hard to reason about correctness
- PENDING_REFRESH state is simple and foolproof

**Verdict:** Not recommended. PENDING_REFRESH provides clear semantic guarantee: "diagnostics are fresh."

---

## 6. Potential Bugs and Issues

### 6.1 BUG: External Change Path Does Not Clear PENDING_REFRESH

**Location:** Node EXT (line 89)
**Operation:** "Refresh: detect externally modified files; set changed_files + project_changed; clear candidate_stalled_*; unlintable_targets -= changed_files; pending_investigation_targets -= changed_files; seen_hashes -= changed_files; go to AC"

**Issue:** No mention of clearing `stale_linters` or checking if external change affects PENDING_REFRESH linters.

**Scenario:**
1. Linter is in PENDING_REFRESH state
2. External change modifies a file
3. EXT path triggered
4. Linter remains in PENDING_REFRESH
5. Next tick: NREF detects PENDING_REFRESH, forces refresh-only tick
6. Linter refreshes and becomes ACTIVE

**Analysis:** This is probably benign (one extra tick delay), but semantically unclear.

**Recommendation:** Add explicit handling in EXT path:
```python
# In EXT path, after clearing other state:
# Check if any PENDING_REFRESH linters are affected by external change
for linter, state in stale_linters.items():
    if state.status == "PENDING_REFRESH":
        # External change happened, just clear the linter
        # The external change will cause a full re-lint anyway
        pass  # Or: del stale_linters[linter]

# Alternative: Always clear PENDING_REFRESH on external change
stale_linters = {
    linter: state
    for linter, state in stale_linters.items()
    if state.status != "PENDING_REFRESH"
}
```

**Severity:** Low (minor inefficiency, not a correctness bug)

### 6.2 BUG: JDROP Path Interaction with Stale Linters

**Location:** Node JDROP (line 30)
**Operation:** "Discard result as STALE (external change detected); set changed_files/project_changed from current state; clear candidate_stalled_*; unlintable_targets -= changed_files; pending_investigation_targets -= changed_files; seen_hashes -= changed_files"

**Issue:** Same as 6.1 - no mention of `stale_linters` interaction.

**Scenario:**
1. Investigation dispatched for target that was blocking a stale linter
2. File modified externally during investigation
3. Investigation completes, but hash check fails (J0/NOOP0/FAIL0 → No)
4. JDROP path taken
5. blocked_by was already updated at I2A (target removed)
6. If blocked_by is now empty, linter is in PENDING_REFRESH
7. JDROP path doesn't clear PENDING_REFRESH

**Analysis:** This is correct! The linter should still be refreshed because its diagnostics are stale. PENDING_REFRESH state is still valid.

**Verdict:** Not a bug. Working as intended.

### 6.3 POTENTIAL BUG: required_linter Ambiguity with Multiple Linters

**Location:** Node BG2A (line 161)
**Issue:** Algorithm does not specify how to determine `required_linter` when multiple linters have errors for a target.

**Scenario:**
- Target has errors from Linter A (ACTIVE) and Linter B (STALE)
- What is the `required_linter`?

**Options:**
1. Linter A (first active linter)
2. Linter B (first linter alphabetically)
3. ALL linters (defer if ANY is stale)
4. PRIMARY linter (based on priority/severity)

**Current Specification:** Key Concept #13
> "required_linter = the linter producing the remaining actionable errors for the target"

**Interpretation:** "remaining actionable errors" implies errors from ACTIVE linters only (stale linter errors are not actionable).

**Recommended Logic:**
```python
def get_required_linter(target, errors_by_linter, stale_linters):
    """
    Get the required linter for a target.

    Strategy: Use the first ACTIVE linter with errors for this target.
    If all linters are stale, this function should not be called
    (target would not be in verified_error_targets).
    """
    active_linters_for_target = []

    for linter, diagnostics_by_target in errors_by_linter.items():
        if linter in stale_linters:
            continue  # Skip stale linters
        if target in diagnostics_by_target and len(diagnostics_by_target[target]) > 0:
            active_linters_for_target.append(linter)

    if not active_linters_for_target:
        raise ValueError(f"No active linters for target {target}")

    # Return first active linter (deterministic)
    return active_linters_for_target[0]
```

**Alternative Conservative Approach:**
```python
def should_defer_target_conservative(target, errors_by_linter, stale_linters):
    """
    Defer if ANY linter (stale or active) has errors for this target
    and that linter is in stale_linters.

    This ensures we never submit a target when part of its error
    context is stale.
    """
    for linter in stale_linters:
        if target in errors_by_linter.get(linter, {}):
            return True  # Defer
    return False  # Submit
```

**Recommendation:** Use conservative approach. It's simpler and safer.

**Severity:** Medium (affects correctness of granular gating)

### 6.4 POTENTIAL BUG: Refresh-Only Tick May Run PROJECT Linter on Locked Files

**Location:** NREF0 → AC (lines 66-67)
**Issue:** Refresh-only tick sets `changed_files = empty` and `project_changed = false`, then jumps to ProcessLinters.

**Flow in ProcessLinters (for PROJECT linter):**
1. AG0: Determine `blocking_files_for_linter = inv_files`
2. AG1: Check if `blocking_files_for_linter empty OR linter supports excluding`
3. If No → AG2 (Skip project run, mark STALE)

**Question:** Can this happen during a refresh-only tick?

**Scenario:**
1. Linter A in PENDING_REFRESH (blocked_by empty)
2. Refresh-only tick triggered (NREF → NREF0)
3. Meanwhile, new investigation started for file X (added to inv_files)
4. ProcessLinters runs
5. Linter A checks blocking_files (blocking_files = inv_files = {X})
6. AG1 → No (linter cannot exclude X)
7. AG2: Mark Linter A as STALE again!

**Analysis:** This is a race condition! PENDING_REFRESH linter can become STALE again during its own refresh tick.

**Root Cause:** `investigation_futures` can change between NREF check and ProcessLinters execution.

**Fix:** Lock `investigation_futures` during refresh-only tick, OR check PENDING_REFRESH linters' `blocked_by` at NREF time and ensure they remain unblocked.

**Recommended Fix:**
```python
# At NREF check (line 65):
pending_refresh_linters = get_pending_refresh_linters()
current_inv_files = get_locked_targets()

for linter in pending_refresh_linters:
    blocking_files = get_blocking_files(linter, current_inv_files)
    if blocking_files:
        # Linter became blocked again! Don't force refresh yet
        # Wait for next unblocking
        # Mark it back to STALE
        stale_linters[linter].status = "STALE"
        stale_linters[linter].blocked_by = blocking_files
        pending_refresh_linters.remove(linter)

# Only proceed to NREF0 if pending_refresh_linters is still non-empty
if pending_refresh_linters:
    # Refresh-only tick
else:
    # Normal processing
```

**Severity:** HIGH (correctness bug, can cause liveness issues)

### 6.5 POTENTIAL BUG: Stale Linter Entry Leakage

**Location:** AI0A (line 127)
**Operation:** "Clear stale_linters entry for this linter (wake-up is post-refresh)"

**Issue:** What if linter fails to run or produces no output?

**Scenario:**
1. Linter in PENDING_REFRESH
2. Refresh-only tick runs
3. Linter execution fails (crash, timeout, etc.)
4. AI0A not reached
5. Linter remains in PENDING_REFRESH forever

**Analysis:** This would cause a deadlock. NREF would keep forcing refresh-only ticks, but linter would never clear.

**Recommended Fix:** Add error handling in ProcessLinters:
```python
try:
    result = run_linter(linter, files_to_check)
    # Update diagnostics
    # ...
    # Clear staleness
    if linter in stale_linters:
        del stale_linters[linter]
except LinterError as e:
    # Linter failed to run
    if linter in stale_linters:
        # Remove from stale_linters to prevent deadlock
        del stale_linters[linter]
    # Mark all targets expecting this linter as UNLINTABLE?
    # Or: Retry on next tick?
    # Or: Abort workflow?
    log_error(f"Linter {linter} failed: {e}")
```

**Severity:** HIGH (can cause infinite loop / deadlock)

### 6.6 POTENTIAL BUG: Granular Gating Check Happens Too Late

**Location:** BG2A (line 161)
**Timing:** Granular gating happens AFTER post-agent lint, when stalls are confirmed.

**Issue:** What if a linter becomes stale DURING the agent phase?

**Scenario:**
1. Agent phase starts, linters are all ACTIVE
2. Agent runs on files F1, F2
3. Investigation starts for F3 (new investigation)
4. F3 blocks PROJECT linter L1
5. L1 becomes STALE
6. Agent completes, post-agent lint runs
7. L1 is skipped (marked STALE)
8. Stalled targets detected (targets still have L1 errors from PRE-agent lint)
9. BG2A: Granular gating defers targets with required_linter = L1

**Question:** Are the stalled targets using stale diagnostics?

**Analysis:**
- Stalled targets use errors from post-agent lint (BG0: `verified_error_targets = extract targets from errors_by_linter excluding stale_linters`)
- Since L1 is in `stale_linters`, its errors are excluded from `verified_error_targets`
- Therefore, stalled targets CANNOT have L1 as their required_linter (L1 errors are not in `verified_error_targets`)
- Granular gating works correctly!

**Verdict:** Not a bug. The `excluding stale_linters` filter at BG0 prevents this issue.

### 6.7 AMBIGUITY: What Happens to Stale Linter Errors in errors_by_linter?

**Question:** When a linter becomes STALE (AG2A), are its diagnostics removed from `errors_by_linter`?

**Analysis of Algorithm:**
- AG2: "Skip project run; mark this linter's diagnostics as STALE/SUSPENDED"
- AG2A: "Upsert stale_linters entry"
- No mention of clearing `errors_by_linter[linter]`

**Interpretation:** Diagnostics remain in `errors_by_linter`, but are excluded by filters:
- O0: `actionable_errors_by_linter = errors_by_linter excluding stale_linters`
- BG0: `verified_error_targets = extract targets from errors_by_linter excluding stale_linters`

**Why Keep Them?**
- When linter becomes ACTIVE again (after refresh), its NEW diagnostics replace the old ones
- If errors are cleared when linter becomes stale, they'd need to be restored, which is complex
- Simpler to keep them and just exclude via filters

**Potential Issue:** If errors are never cleared, they accumulate. But this is fine because:
1. Linter refresh (AI step) updates diagnostics, replacing old ones
2. Stale linter errors are never used (always excluded)

**Recommendation:** Add explicit comment in algorithm:
```
AG2: Skip project run; mark this linter's diagnostics as STALE/SUSPENDED
     (diagnostics remain in errors_by_linter but are excluded by filters
      until linter refreshes)
```

**Severity:** Low (documentation clarity issue, not a bug)

---

## 7. Summary and Recommendations

### 7.1 System Design Assessment

**Strengths:**
- Sophisticated state machine prevents deadlocks and false termination
- Granular gating allows parallel progress on unrelated targets
- PENDING_REFRESH state ensures diagnostics are refreshed before use
- Integration with investigation completion is well-designed

**Weaknesses:**
- Complex state transitions hard to reason about
- Multiple potential race conditions (6.4, 6.5)
- Ambiguity in required_linter computation (6.3)
- Documentation gaps (6.7)

### 7.2 Critical Bugs (Must Fix)

1. **Bug 6.4: Refresh-Only Tick Race Condition**
   - Linter can become blocked again during its own refresh tick
   - Can cause liveness issues (linter ping-pongs between PENDING_REFRESH and STALE)
   - **Fix:** Check for blocking at NREF time, re-mark as STALE if blocked

2. **Bug 6.5: Linter Failure Causes Deadlock**
   - Failed linter execution leaves entry in stale_linters forever
   - NREF will keep triggering refresh-only ticks infinitely
   - **Fix:** Add error handling to clear stale_linters on linter failure

3. **Ambiguity 6.3: required_linter Computation**
   - Algorithm doesn't specify how to handle multiple linters per target
   - Can cause incorrect deferral/submission decisions
   - **Fix:** Use conservative approach (defer if ANY linter is stale)

### 7.3 Minor Issues (Should Fix)

4. **Issue 6.1: External Change and PENDING_REFRESH**
   - EXT path doesn't explicitly handle PENDING_REFRESH linters
   - Benign but semantically unclear
   - **Fix:** Add explicit clearing of PENDING_REFRESH on external change

5. **Issue 6.7: Documentation Clarity**
   - Unclear whether stale linter errors remain in errors_by_linter
   - **Fix:** Add explicit documentation

### 7.4 Simplification Recommendations

**Do NOT simplify:**
- PENDING_REFRESH state (provides clear semantic guarantee)
- Granular gating mechanism (necessary for async state constraint)

**Could simplify (low priority):**
- Add reverse index for required_linter lookup (if performance becomes issue)
- Merge STALE and PENDING_REFRESH into single state with flag (minor benefit)

### 7.5 Additional Recommendations

1. **Add Staleness Cycle Detection**
   - Detect if linter ping-pongs between STALE and PENDING_REFRESH
   - Abort with clear error message if detected
   - Helps diagnose configuration issues (linter that can't run with exclusions)

2. **Add Metrics/Logging**
   - Log state transitions (ACTIVE → STALE → PENDING_REFRESH → ACTIVE)
   - Track time spent in each state
   - Count refresh-only ticks
   - Helps debugging and performance optimization

3. **Formalize required_linter Strategy**
   - Document clearly in algorithm which linter is chosen when multiple exist
   - Consider adding priority/severity-based selection
   - Make it configurable if needed

4. **Add Invariant Checks**
   - Assert that PENDING_REFRESH linters have empty blocked_by
   - Assert that stale linters are excluded from actionable_errors
   - Assert that required_linter for deferred target is in stale_linters
   - Helps catch bugs early

### 7.6 Testing Recommendations

**Critical Test Cases:**
1. Single linter becomes stale, then unblocked, then refreshed
2. Multiple linters stale simultaneously with different blocked_by sets
3. Linter becomes stale during agent phase
4. Linter fails during refresh-only tick
5. External change during PENDING_REFRESH state
6. Target with errors from both stale and active linters
7. Investigation completes while linter is PENDING_REFRESH
8. New investigation starts during refresh-only tick (race in 6.4)

**Edge Cases:**
- All linters stale (should wait, not terminate)
- No linters ever become stale (normal happy path)
- Linter alternates between STALE and PENDING_REFRESH (cycle detection)
- <PROJECT> target deferred due to stale PROJECT linter

---

## Appendix A: Complete State Transition Table

| Current State | Event | Next State | Updates |
|---------------|-------|------------|---------|
| ACTIVE | PROJECT linter blocked by inv_files (AG1→No, AG2→AG2A) | STALE/SUSPENDED | Add to stale_linters, set blocked_by=blocking_files |
| STALE/SUSPENDED | Investigation completes, blocked_by becomes empty (I2A→I2B→I2C) | PENDING_REFRESH | Update status to PENDING_REFRESH, keep in stale_linters |
| STALE/SUSPENDED | Investigation completes, blocked_by still non-empty (I2A→I2B→No) | STALE/SUSPENDED | Update blocked_by (remove completed target) |
| PENDING_REFRESH | Refresh-only tick runs linter successfully (NREF→NREF0→AC→AI0A) | ACTIVE | Remove from stale_linters |
| PENDING_REFRESH | Refresh-only tick blocked again (race - Bug 6.4) | STALE/SUSPENDED | Re-mark as STALE, update blocked_by |
| PENDING_REFRESH | Linter execution fails (Bug 6.5) | ACTIVE (with errors) or DEADLOCK | Should clear from stale_linters |
| ACTIVE | External change detected (EXT path) | ACTIVE | No state change (not mentioned in EXT) |
| PENDING_REFRESH | External change detected (EXT path) | PENDING_REFRESH | No state change (Issue 6.1) |
| STALE/SUSPENDED | External change detected (JDROP path) | STALE/SUSPENDED or PENDING_REFRESH | blocked_by updated, may transition to PENDING_REFRESH |

---

## Appendix B: Cross-Reference Index

**stale_linters Reads:**
- Line 65 (NREF): Check for PENDING_REFRESH
- Line 73 (O0): Exclude from actionable_errors
- Line 76 (O4A): Check if empty before dispatching pending
- Line 91 (Q2): Termination condition
- Line 93 (Q3): Loop vs invariant violation
- Line 103 (R2): Exclude from agent input
- Line 156 (BG0): Exclude from verified_error_targets
- Line 161 (BG2A): Granular gating check
- Line 172 (BH): Final termination condition

**stale_linters Writes:**
- Line 12 (F3): Initialize empty
- Line 23 (I2A): Update blocked_by
- Line 25 (I2C): Mark PENDING_REFRESH
- Line 127 (AI0A): Clear entry (linter becomes ACTIVE)
- Line 134 (AG2A): Upsert entry (linter becomes STALE)

**blocked_by References:**
- Line 12 (F3): Part of stale_linters structure
- Line 23 (I2A): Updated on investigation completion
- Line 24 (I2B): Check if empty
- Line 25 (I2C): Mentioned in PENDING_REFRESH transition
- Line 65 (NREF): Mentioned in check condition
- Line 134 (AG2A): Set to blocking_files_for_linter

**PENDING_REFRESH References:**
- Line 25 (I2C): Transition from STALE
- Line 65 (NREF): Detection for refresh-only tick
- Line 209 (Concept #13): Included in granular gating

**required_linter References:**
- Line 161 (BG2A): Used in granular gating
- Line 209 (Concept #13): Definition and usage

---

## Appendix C: Glossary

**actionable_errors_by_linter:** Subset of errors_by_linter excluding stale linters and unlintable targets. Represents errors the system can currently act on.

**blocked_by:** Set of targets (files under investigation) preventing a stale linter from running.

**granular gating:** Mechanism to defer only targets whose required_linter is stale, while submitting other stalled targets immediately.

**inv_files:** Set of targets currently locked by investigation_futures (investigations in progress).

**pending_investigation_targets:** Targets that are stalled but deferred because their required_linter is stale. Stores context for later submission.

**refresh-only tick:** Special main loop iteration that skips agent phase and runs only ProcessLinters to refresh stale linters.

**required_linter:** The linter responsible for the actionable errors on a given target. Used in granular gating to determine if target should be deferred.

**stale_linters:** Dict mapping linters to their stale state (STALE/SUSPENDED or PENDING_REFRESH) and blocked_by set.

**STALE/SUSPENDED:** State where linter cannot run due to locked files, and its diagnostics are excluded from actionable errors.

**PENDING_REFRESH:** State where linter is unblocked but diagnostics are still excluded until a refresh-only tick runs the linter.

**verified_error_targets:** Targets with confirmed errors from actionable (non-stale) linters after post-agent lint.
