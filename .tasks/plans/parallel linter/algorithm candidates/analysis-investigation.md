# Investigation Lifecycle Analysis

## Executive Summary

The investigation system is a sophisticated state machine designed to handle stalled targets (files or `<PROJECT>`) that the lint-fixer agent cannot resolve. This analysis maps the complete lifecycle, identifies critical state transitions, traces data flows, and highlights potential race conditions and edge cases.

---

## 1. Complete Investigation State Machine

### 1.1 Investigation Target States

```
┌─────────────────────────────────────────────────────────────────────┐
│                    INVESTIGATION TARGET LIFECYCLE                    │
└─────────────────────────────────────────────────────────────────────┘

                              ┌──────────────┐
                              │  NOT STALLED │
                              │   (Normal)   │
                              └──────┬───────┘
                                     │
                                     │ Agent runs but target unchanged
                                     │ + errors persist post-lint
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  CANDIDATE_STALLED    │◄─────────┐
                         │                       │          │
                         │ candidate_stalled_    │          │
                         │ targets contains      │          │
                         └───────┬───────────────┘          │
                                 │                          │
                                 │ confirmed_stalled_       │
                                 │ targets = candidate ∩    │
                                 │ verified_error_targets   │
                                 │                          │
                                 ▼                          │
                    ┌────────────────────────┐              │
                    │ CONFIRMED_STALLED      │              │
                    │ (errors persist)       │              │
                    └────┬──────────┬────────┘              │
                         │          │                       │
            Granular     │          │ No stale_linters      │
            gating       │          │ blocking              │
            detects      │          │                       │
            blocking     │          │                       │
                         │          ▼                       │
                         │   ┌──────────────┐               │
                         │   │ READY_TO_    │               │
                         │   │ SUBMIT       │               │
                         │   └──────┬───────┘               │
                         │          │                       │
                         │          │ Snapshot & dispatch   │
                         │          │                       │
                         ▼          ▼                       │
                  ┌──────────────────────┐                 │
                  │  PENDING_DEFERRED    │                 │
                  │                      │                 │
                  │  pending_            │                 │
                  │  investigation_      │                 │
                  │  targets             │                 │
                  │  + context stored    │                 │
                  └──────────────────────┘                 │
                              │                            │
                              │ Unblocked                  │
                              │ (stale_linters cleared)    │
                              └────────────────────────────┘

                         ┌──────────────────────┐
                         │  IN_FLIGHT           │
                         │                      │
                         │  investigation_      │
                         │  futures             │
                         │  + start hash        │
                         └──────┬───────────────┘
                                │
                                │ Investigation completes
                                │
                ┌───────────────┼───────────────┐
                │               │               │
                ▼               ▼               ▼
         ┌──────────┐    ┌──────────┐   ┌──────────┐
         │ MODIFIED │    │  NO_OP   │   │ FAILURE  │
         └────┬─────┘    └────┬─────┘   └────┬─────┘
              │               │               │
              │               │               │
              ▼               ▼               ▼
      ┌────────────────────────────────────────────┐
      │     STALENESS CHECK (hash comparison)      │
      │     current_hash == investigation_start    │
      └───────┬──────────────────┬─────────────────┘
              │                  │
      ┌───────▼─────┐    ┌──────▼──────┐
      │ STALE:      │    │ VALID:      │
      │ Discard &   │    │ Process     │
      │ Refresh     │    │ Outcome     │
      └─────────────┘    └──────┬──────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
      ┌────────────┐    ┌────────────┐   ┌────────────┐
      │ MODIFIED:  │    │  NO_OP:    │   │ FAILURE:   │
      │ Check diff │    │ UNLINTABLE │   │ UNLINTABLE │
      └─────┬──────┘    └─────┬──────┘   └─────┬──────┘
            │                 │                │
            ▼                 ▼                ▼
     ┌──────────┐      ┌──────────────┐  ┌──────────────┐
     │ Has diff?│      │  Remove from │  │  Remove from │
     └─┬────┬───┘      │  errors_by_  │  │  errors_by_  │
       │    │          │  linter      │  │  linter      │
    No │    │ Yes      │              │  │              │
       │    │          │  Clear       │  │  Clear       │
       │    │          │  passed_     │  │  passed_     │
       │    │          │  linters     │  │  linters     │
       │    │          └──────┬───────┘  └──────┬───────┘
       │    │                 │                 │
       │    │                 │                 │
       │    │                 ▼                 ▼
       │    │          ┌────────────────────────────┐
       │    │          │  <PROJECT> CHECK           │
       │    │          │  Is target == <PROJECT>?   │
       │    │          └───┬────────────────────┬───┘
       │    │              │                    │
       │    │              │ Yes                │ No
       │    │              ▼                    ▼
       │    │        ┌──────────┐        ┌──────────┐
       │    │        │  ABORT   │        │ Continue │
       │    │        │ (FATAL)  │        │  (Target │
       │    │        └──────────┘        │  removed)│
       │    │                            └──────────┘
       │    │
       │    └───────────────────┐
       │                        │
       ▼                        ▼
┌────────────┐         ┌─────────────────┐
│ UNLINTABLE │         │  BACK_TO_NORMAL │
│ (lie)      │         │  (cleared state, │
└────────────┘         │   re-lint)       │
                       └──────────────────┘
```

### 1.2 Investigation Future States

```
┌─────────────────────────────────────────────────┐
│         INVESTIGATION FUTURE STATE FLOW         │
└─────────────────────────────────────────────────┘

    ┌─────────────┐
    │   PENDING   │ (target deferred in pending_investigation_targets)
    │   (stored)  │
    └──────┬──────┘
           │
           │ stale_linters cleared (target unblocked)
           │
           ▼
    ┌─────────────┐
    │  RESERVED   │ (added to investigation_futures, start hash captured)
    └──────┬──────┘
           │
           │ async dispatch (payload sent to investigator)
           │
           ▼
    ┌─────────────┐
    │  IN_FLIGHT  │ (future in investigation_futures, awaiting result)
    └──────┬──────┘
           │
           │ future.completed()
           │
           ▼
    ┌─────────────┐
    │  COMPLETED  │ (result available)
    └──────┬──────┘
           │
           │ Removed from investigation_futures
           │
           ▼
    ┌─────────────┐
    │   CONSUMED  │ (result processed, state updated)
    └─────────────┘
```

### 1.3 Stale Linter States (Related to Investigation)

```
┌──────────────────────────────────────────────────┐
│          STALE LINTER STATE MACHINE              │
└──────────────────────────────────────────────────┘

    ┌──────────┐
    │  ACTIVE  │ (not in stale_linters)
    └────┬─────┘
         │
         │ PROJECT linter blocked by locked files
         │
         ▼
    ┌────────────────┐
    │ STALE/         │
    │ SUSPENDED      │ (in stale_linters, blocked_by = set of locked files)
    │ + blocked_by   │
    └───────┬────────┘
            │
            │ Investigation completes for file in blocked_by
            │ → Update blocked_by (remove completed file)
            │
            ▼
    ┌─────────────┐
    │ blocked_by  │
    │  empty?     │
    └──┬──────┬───┘
       │      │
    No │      │ Yes
       │      │
       ▼      ▼
    ┌──────┐ ┌────────────────┐
    │ KEEP │ │  PENDING_      │ (blocked_by empty but not yet refreshed)
    │ AS   │ │  REFRESH       │
    │ STALE│ └───────┬────────┘
    └──────┘         │
                     │ Refresh-only tick (NREF path)
                     │
                     ▼
              ┌──────────────┐
              │  REFRESHED   │ (removed from stale_linters)
              │  → ACTIVE    │
              └──────────────┘
```

---

## 2. State Transition Conditions

### 2.1 Entry into Investigation

**From Normal → CANDIDATE_STALLED**
- **Trigger**: Lines V-V2 in algorithm
- **Conditions**:
  1. Agent phase completed (lines R-U1)
  2. Target was in `actionable_targets` (sent to agent)
  3. `changed_files` does NOT include target (file hash unchanged)
  4. OR `project_changed` = false (for `<PROJECT>` target)
  5. Target is in `candidate_stalled_files` or `candidate_stalled_targets`

**From CANDIDATE_STALLED → CONFIRMED_STALLED**
- **Trigger**: Line BG1
- **Conditions**:
  1. Post-agent linting completed (lines AE-AS)
  2. Target still has errors in `errors_by_linter` (excluding `stale_linters`)
  3. `confirmed_stalled_targets = candidate_stalled_targets ∩ verified_error_targets`

**From CONFIRMED_STALLED → PENDING_DEFERRED**
- **Trigger**: Lines BG2A-BG2B (granular gating)
- **Conditions**:
  1. Target's `required_linter` is in `stale_linters` (STALE/SUSPENDED/PENDING_REFRESH)
  2. `required_linter` = linter producing remaining actionable errors for target
  3. Target added to `pending_investigation_targets` with `{error_snapshot, agent_output_snapshot}`

**From CONFIRMED_STALLED → READY_TO_SUBMIT**
- **Trigger**: Lines BG2A-BG2C
- **Conditions**:
  1. Target's `required_linter` is NOT in `stale_linters`
  2. Target in `targets_to_submit` after granular gating

**From PENDING_DEFERRED → READY_TO_SUBMIT**
- **Trigger**: Lines O4A-O4B OR Lines I2B-I2C
- **Conditions**:
  1. `stale_linters` is empty OR target unblocked
  2. `pending_investigation_targets` non-empty
  3. No active `stale_linters` blocking dispatch

**From READY_TO_SUBMIT → IN_FLIGHT**
- **Trigger**: Lines BG3-BG4A OR Lines O4A-O4B
- **Conditions**:
  1. Start hash/fingerprint captured NOW (line BG3A or O4B)
  2. Added to `investigation_futures` (reserve synchronously)
  3. Async dispatch with payload `{error_snapshot, agent_output_snapshot, target}`
  4. Removed from `pending_investigation_targets`
  5. Cleared from `candidate_stalled_targets`

### 2.2 Investigation Completion Transitions

**From IN_FLIGHT → Result Processing**
- **Trigger**: Lines H-I2 (investigation completed)
- **Conditions**:
  1. Future in `investigation_futures` completes
  2. Result retrieved with status (MODIFIED/NO_OP/FAILURE)

**Staleness Check (Critical Gate)**
- **Trigger**: Lines J0, NOOP0, FAIL0
- **Condition**: `current_hash == investigation_start_hash`
  - **If FALSE**: → JDROP (discard as STALE)
  - **If TRUE**: → Process outcome based on status

**STALE Outcome → Refresh**
- **Trigger**: Line JDROP
- **Actions**:
  1. Discard investigator result
  2. Detect current state: `set changed_files/project_changed`
  3. Clear `candidate_stalled_*`
  4. Remove from `unlintable_targets` (for `changed_files`)
  5. Remove from `pending_investigation_targets` (for `changed_files`)
  6. Remove from `seen_hashes` (for `changed_files`)
  7. Continue to ProcessLinters (line AC)

**MODIFIED Outcome Processing**
- **Trigger**: Lines J0-K3 (staleness check passed)
- **Sub-conditions**:
  1. **No actual diff** (line J1): `new_hash == investigation_start_hash`
     - → Mark as UNLINTABLE (reason: "Investigator MODIFIED but no diff")
     - → If `<PROJECT>`: ABORT (line ABORT)
     - → Else: Continue to NOOP2 (remove from errors)

  2. **Has diff** (line J1): `new_hash != investigation_start_hash`
     - → Record new hash in `seen_hashes` (line K)
     - → Clear state for modified targets (errors, passed_linters)
     - → Set `changed_files` = truly modified file targets
     - → Set `project_changed` = true if `<PROJECT>` modified
     - → Clear `candidate_stalled_*`
     - → Remove from `pending_investigation_targets`
     - → Continue to ProcessLinters (line AC)

**NO_OP Outcome Processing**
- **Trigger**: Lines NOOP0-NOOP3 (staleness check passed)
- **Actions**:
  1. Check if `target == <PROJECT>`:
     - **Yes**: Mark as UNLINTABLE → ABORT (lines NOOPPROJ-ABORT)
     - **No**: Mark as UNLINTABLE (reason: "Investigator NO_OP")
  2. Remove target diagnostics from `errors_by_linter`
  3. Clear `passed_linters` for target
  4. Back to investigation check loop (line H)

**FAILURE Outcome Processing**
- **Trigger**: Lines FAIL0-FAIL3 (staleness check passed)
- **Actions**:
  1. Check if `target == <PROJECT>`:
     - **Yes**: Mark as UNLINTABLE → ABORT (lines FAILPROJ-ABORT)
     - **No**: Mark as UNLINTABLE (reason: "Investigator FAILURE")
  2. Remove target diagnostics from `errors_by_linter`
  3. Clear `passed_linters` for target
  4. Back to investigation check loop (line H)

### 2.3 Stale Linter Transitions (Investigation-Related)

**From ACTIVE → STALE/SUSPENDED**
- **Trigger**: Lines AG1-AG2A
- **Conditions**:
  1. `linter_scope == PROJECT`
  2. `blocking_files_for_linter` non-empty
  3. Linter does NOT support excluding `blocking_files_for_linter`
  4. Upsert `stale_linters` entry with `blocked_by = blocking_files_for_linter`

**Update blocked_by (Investigation Completion)**
- **Trigger**: Line I2A
- **Condition**: Investigation completes for target
- **Action**: Remove completed target from all `stale_linters[*].blocked_by`

**From STALE/SUSPENDED → PENDING_REFRESH**
- **Trigger**: Lines I2B-I2C
- **Conditions**:
  1. Investigation completed and updated `blocked_by`
  2. Any `stale_linters` entry now has `blocked_by == empty`
- **Action**: Mark unblocked linter as PENDING_REFRESH (keep in `stale_linters`, excluded from actionable)

**From PENDING_REFRESH → ACTIVE**
- **Trigger**: Lines NREF-NREF0
- **Conditions**:
  1. Main loop detects `stale_linters` with PENDING_REFRESH state
  2. Refresh-only tick executed:
     - Set `changed_files = empty`
     - Set `project_changed = false`
     - Set `candidate_stalled_files = empty`
     - Set `candidate_stalled_targets = empty`
  3. Linter runs and refreshes (lines AE-AS)
  4. Clear `stale_linters` entry (line AI0A)

---

## 3. Data Flow for Investigation Payloads

### 3.1 Payload Creation

```
┌──────────────────────────────────────────────────────────────────────┐
│                   INVESTIGATION PAYLOAD DATA FLOW                    │
└──────────────────────────────────────────────────────────────────────┘

PHASE 1: Agent Execution
└─ Lines R-S2
   └─ agent_input_files = actionable_files ∪ project_context_files
   └─ Agent produces output → captured as agent_output_snapshot

PHASE 2: Post-Agent Linting
└─ Lines AE-AS
   └─ Linters run → produces errors_by_linter (excluding stale_linters)
   └─ Extract verified_error_targets

PHASE 3: Stall Detection
└─ Lines V-BG1
   └─ candidate_stalled_targets = targets sent to agent but unchanged
   └─ confirmed_stalled_targets = candidate ∩ verified_error_targets

PHASE 4: Context Snapshot (for deferred targets)
└─ Lines BG2A-BG2B
   └─ IF target in targets_to_defer:
      └─ Store in pending_investigation_targets:
         └─ error_snapshot = current errors_by_linter (excluding stale_linters)
         └─ agent_output_snapshot = from agent execution (line S2)

PHASE 5: Context Snapshot (for immediate submission)
└─ Lines BG3-BG3A
   └─ IF target in targets_to_submit:
      └─ Use pending snapshot if present (from pending_investigation_targets)
      └─ ELSE: Build from current tick
         └─ error_snapshot = current errors_by_linter (excluding stale_linters)
         └─ agent_output_snapshot = from agent execution (line S2)
      └─ Snapshot investigation_start_hash/fingerprint NOW

PHASE 6: Dispatch
└─ Lines BG4-BG4A OR O4B
   └─ Dispatch async with payload:
      {
        target: <file_path> or <PROJECT>,
        error_snapshot: errors_by_linter (filtered),
        agent_output_snapshot: agent output from causing tick,
        investigation_start_hash: hash/fingerprint at dispatch time
      }
```

### 3.2 Payload Lifecycle

```
┌────────────────────────────────────────────────────────────┐
│          INVESTIGATION CONTEXT STORAGE TIMELINE            │
└────────────────────────────────────────────────────────────┘

Tick N: Agent runs, stall detected
  └─ Stalled target identified (lines V-BG1)
  └─ Granular gating decides: defer or submit

  BRANCH A: DEFER (target's required_linter is stale)
  └─ Store in pending_investigation_targets (line BG2B):
     └─ pending_investigation_targets[target] = {
          error_snapshot: <errors at tick N>,
          agent_output_snapshot: <agent output from tick N>
        }
  └─ Clear from candidate_stalled_targets
  └─ WAIT for stale_linters to clear

  BRANCH B: SUBMIT (no blocking stale_linters)
  └─ Build payload from current tick (lines BG3-BG3A):
     └─ error_snapshot: <errors at tick N>
     └─ agent_output_snapshot: <agent output from tick N>
  └─ Snapshot start_hash NOW (exact version being sent)
  └─ Add to investigation_futures
  └─ Dispatch async
  └─ Clear from candidate_stalled_targets

Tick N+1..N+M: Waiting for unblock (BRANCH A only)
  └─ Target remains in pending_investigation_targets
  └─ Context preserved across ticks
  └─ Investigations for OTHER targets may complete
  └─ blocked_by updates (line I2A)
  └─ When blocked_by becomes empty → PENDING_REFRESH (lines I2B-I2C)

Tick N+M+1: Refresh-only tick (BRANCH A only)
  └─ Lines NREF-NREF0
  └─ Linters refresh
  └─ stale_linters cleared (line AI0A)

Tick N+M+2: Deferred target now ready (BRANCH A only)
  └─ Lines O4A-O4B
  └─ pending non-empty AND stale_linters empty
  └─ Reserve in investigation_futures
  └─ Snapshot start_hash NOW (exact version being sent)
  └─ Dispatch async using STORED {error_snapshot, agent_output_snapshot}
  └─ Clear pending_investigation_targets

Investigation completes (BRANCH A or B)
  └─ Lines H-I2
  └─ Result retrieved with status
  └─ Staleness check: current_hash == investigation_start_hash?
     └─ If NO: Discard (line JDROP)
     └─ If YES: Process outcome
```

### 3.3 Hash/Fingerprint Tracking

```
┌─────────────────────────────────────────────────────────────┐
│              HASH TRACKING THROUGH INVESTIGATION            │
└─────────────────────────────────────────────────────────────┘

1. PRE-AGENT SNAPSHOT (Line R)
   └─ Snapshot agent_input_files BEFORE agent
   └─ Capture file hashes + project fingerprint
   └─ Update seen_hashes (line R1)

2. AGENT EXECUTION (Lines S-S2)
   └─ CAS-protected writes verify hashes from step 1 (line S0)
   └─ If hash changed since R: Discard → EXT (external change)

3. POST-AGENT SNAPSHOT (Line T)
   └─ Snapshot agent_input_files AFTER agent
   └─ Detect changes (line U): changed_files, project_changed
   └─ Update seen_hashes for changed (line U1)

4. INVESTIGATION START SNAPSHOT (Lines BG3A or O4B)
   └─ Snapshot investigation_start_hash/fingerprint NOW
   └─ This is the reference for staleness check
   └─ Stored per-target in investigation_futures

5. INVESTIGATION COMPLETION SNAPSHOT (Lines J0, NOOP0, FAIL0)
   └─ Retrieve current_hash/fingerprint
   └─ Compare: current_hash == investigation_start_hash?
      └─ Match: Proceed with outcome processing
      └─ Mismatch: STALE → Discard (line JDROP)

6. POST-MODIFICATION SNAPSHOT (Lines J1-K)
   └─ IF MODIFIED outcome AND staleness check passed:
      └─ Capture new_hash after investigator changes
      └─ Compare: new_hash != investigation_start_hash?
         └─ YES: Real modification → record in seen_hashes
         └─ NO: Lie (MODIFIED but no diff) → UNLINTABLE
```

---

## 4. Potential Race Conditions and Edge Cases

### 4.1 Race Conditions

#### Race 1: External Modification During Investigation
**Scenario**: File modified externally while investigation is in-flight

**Timeline**:
1. Investigation dispatched with `start_hash = H1`
2. External process modifies file → `current_hash = H2`
3. Investigation completes with result
4. Staleness check: `current_hash (H2) != start_hash (H1)`

**Mitigation**: Line JDROP - Discard result, refresh state, re-lint

**Potential Issue**: If external changes are rapid and continuous, investigations may never complete successfully (livelock)

**Detection**: Monitor discard rate in `seen_hashes` churn

---

#### Race 2: Concurrent Investigation and Agent
**Scenario**: Agent modifies file while investigation for same file is pending

**Prevention**: Line O6 - `actionable_targets` excludes files in `investigation_futures`

**Enforcement**: Reserve target in `investigation_futures` BEFORE dispatch (synchronous, line BG4)

**Gap**: If investigation completes BETWEEN lines O2 and O6, target may become actionable before removal from `investigation_futures` completes

**Mitigation**: Investigation completion (lines I-I2) removes from `investigation_futures` before processing result, so next tick will see target as no longer locked

---

#### Race 3: Stale Linter Unblock During Payload Build
**Scenario**:
1. Target deferred because `required_linter` in `stale_linters` (line BG2A)
2. Investigation for blocking file completes (line I2A)
3. `blocked_by` becomes empty (line I2B)
4. Linter marked PENDING_REFRESH
5. Before refresh-only tick, another agent tick runs

**Issue**: Target still in `pending_investigation_targets`, but granular gating (line BG2A) may re-evaluate and create duplicate submission

**Mitigation**: Line BG0A - `pending_investigation_targets` filtered to `verified_error_targets` (drop resolved), preventing duplicates if errors cleared

**Gap**: If errors persist but linter transitions PENDING_REFRESH → ACTIVE between ticks, target could be submitted twice (once from pending, once from new stall)

**Detection**: Check if target already in `investigation_futures` before dispatch

---

#### Race 4: Multiple Investigations for <PROJECT>
**Scenario**:
1. `<PROJECT>` stalls → investigation dispatched
2. While in-flight, another agent tick stalls `<PROJECT>` again

**Prevention**: Line O6 - `<PROJECT>` excluded from `actionable_targets` if in `investigation_futures`

**Enforcement**: Lines O5-O6 explicitly remove `<PROJECT>` from actionable when locks exist

**Gap**: If first investigation completes with MODIFIED → clears errors → re-lints → new errors appear → stalls again in same tick

**Mitigation**: Line BG5 - If `<PROJECT>` in `targets_to_submit`, clear ALL `passed_linters` (forces full re-check)

---

### 4.2 Edge Cases

#### Edge Case 1: Investigator Returns MODIFIED with No Diff
**Detection**: Line J1 - `new_hash == investigation_start_hash`

**Handling**: Mark as UNLINTABLE (reason: "Investigator MODIFIED but no diff")

**Special Case**: If `target == <PROJECT>` → ABORT (line ABORT)

**Justification**: Investigator claiming modification without producing changes indicates a fundamental issue (lie or broken investigator)

**Question**: Should this trigger investigator debugging/logging before aborting?

---

#### Edge Case 2: All Targets Become UNLINTABLE
**Scenario**: All files marked UNLINTABLE due to repeated NO_OP/FAILURE

**Detection**: Lines O3P-ABORT - Check if `<PROJECT>` in `unlintable_targets`

**Handling**:
- If `<PROJECT>` UNLINTABLE → ABORT (global failure)
- If only file targets UNLINTABLE → Continue until `actionable_errors_by_linter` empty

**Terminal Condition**: Line Q2 - `actionable_errors_by_linter empty AND stale_linters empty` → SUCCESS

**Gap**: If all files UNLINTABLE but errors persist (should be impossible), hits line Q4 invariant violation

---

#### Edge Case 3: Investigation Completes After Errors Resolved
**Scenario**:
1. Investigation dispatched for target with errors
2. While in-flight, agent modifies other file that fixes target's errors
3. Investigation completes, but target no longer in `errors_by_linter`

**Handling**: Staleness check passes (hash unchanged), outcome processed:
- **MODIFIED**: Lines K-K3 - Clear errors, set `changed_files`, continue
- **NO_OP**: Line NOOP2 - Remove from `errors_by_linter` (already removed, no-op)
- **FAILURE**: Line FAIL2 - Remove from `errors_by_linter` (already removed, no-op)

**Result**: Investigation result processed but has no effect (benign)

---

#### Edge Case 4: Pending Investigation Outlives Error
**Scenario**:
1. Target deferred in `pending_investigation_targets` due to stale linter
2. While waiting, agent fixes errors for target
3. Linter unblocks → attempts to dispatch pending investigation

**Handling**: Line BG0A - `pending_investigation_targets = filter keys to verified_error_targets`

**Result**: Target removed from pending before dispatch (drop resolved)

**Gap**: If errors return AFTER filter but BEFORE dispatch, could dispatch investigation for stale error snapshot

**Mitigation**: Investigation will fail staleness check if file changed, or mark as UNLINTABLE if legitimate stall

---

#### Edge Case 5: Circular Dependency in Stale Linters
**Scenario**:
1. Linter A blocked by file X (in investigation)
2. Investigation for X requires linter A to verify fix
3. Deadlock?

**Prevention**: Investigations are NOT blocked by stale linters (they operate independently)

**Flow**:
1. Investigation for X completes
2. Line I2A updates `blocked_by` (remove X)
3. Linter A marked PENDING_REFRESH (line I2C)
4. Refresh-only tick runs linter A (lines NREF-NREF0)
5. Linter A results available

**Conclusion**: No circular dependency possible (investigations don't wait for linters)

---

#### Edge Case 6: Agent Creates New File During Investigation
**Scenario**:
1. Investigation for file A in-flight
2. Agent creates new file B
3. New file B introduces errors in file A

**Handling**:
- Investigation staleness check compares hash of file A only
- File A hash unchanged → staleness check passes
- Investigation outcome processed
- Next lint tick discovers errors in file B (line AM1 with `project_changed`)

**Gap**: Investigation context (error_snapshot) doesn't include errors from new file B

**Mitigation**: Investigation should focus on target's direct errors, not transitive dependencies

---

#### Edge Case 7: Rapid PENDING_REFRESH → ACTIVE Transition
**Scenario**:
1. Linter unblocked → PENDING_REFRESH (line I2C)
2. Refresh-only tick scheduled (line NREF)
3. Before refresh executes, external change triggers full refresh (line EXT)

**Handling**:
- External change refresh (line EXT) → ProcessLinters (line AC)
- Linters run (lines AE-AS)
- Line AI0A clears `stale_linters` entry

**Result**: Linter transitions directly to ACTIVE without dedicated refresh-only tick (benign optimization)

---

#### Edge Case 8: Investigation Result Arrives After Abort
**Scenario**:
1. Investigation for file A in-flight
2. Investigation for `<PROJECT>` completes with FAILURE → ABORT
3. Investigation for file A completes after abort initiated

**Handling**: Lines BI-BK - Cleanup phase collects all investigation reports regardless of abort

**Question**: Should in-flight investigations be cancelled on abort, or allowed to complete for reporting?

**Current Behavior**: Reports collected (line BI), suggesting completion is preferred

---

### 4.3 Staleness Protection Analysis

#### Hash Comparison Points

**Point 1: Agent CAS Protection (Line S0)**
```
Pre-write check: hash/fingerprint unchanged since R (pre-agent snapshot)
```
- **Purpose**: Prevent agent from overwriting external changes
- **Action if failed**: Discard agent write → EXT (external change refresh)
- **Coverage**: All `agent_input_files`

**Point 2: Investigation Staleness Check (Lines J0, NOOP0, FAIL0)**
```
Pre-processing check: current_hash == investigation_start_hash
```
- **Purpose**: Prevent processing stale investigation results
- **Action if failed**: Discard result → JDROP (refresh)
- **Coverage**: Target file or project fingerprint

**Point 3: MODIFIED Diff Verification (Line J1)**
```
Post-modification check: new_hash != investigation_start_hash
```
- **Purpose**: Verify investigator actually changed something
- **Action if failed**: Mark UNLINTABLE (lie detection)
- **Coverage**: Target file or project fingerprint

#### Hash Consistency Across seen_hashes

**Update Points**:
1. Line R1: Pre-agent snapshot
2. Line U1: Post-agent snapshot (for `changed_files`)
3. Line K: Post-investigation MODIFIED (for modified targets)

**Removal Points**:
1. Line JDROP: External change detected → clear `changed_files`
2. Line EXT: External change refresh → clear `changed_files`

**Purpose**: Track all hashes observed in current processing window to detect cycles or repeated modifications

**Gap**: `seen_hashes` cleared for `changed_files` but not for unchanged files → could accumulate indefinitely

**Mitigation**: Consider clearing `seen_hashes` for successfully linted files (in `passed_linters`)

---

### 4.4 Blocking and Dependency Analysis

#### Stale Linter Blocking Semantics

**Blocker**: Files in `investigation_futures` (locked)

**Blocked**: PROJECT linters that cannot exclude locked files (line AG1)

**Transitive Block**: Targets whose `required_linter` is stale (line BG2A)

**Unblock Trigger**: Investigation completion → update `blocked_by` (line I2A)

**Unblock Verification**: Check if `blocked_by` empty (line I2B)

**Unblock Action**: Mark PENDING_REFRESH (line I2C) → Refresh-only tick (lines NREF-NREF0) → Clear stale (line AI0A)

#### Granular Gating Logic (Lines BG2A-BG2C)

**Input**: `stalled_targets_ready` (confirmed stalls + pending deferrals)

**Partition**:
```
FOR each target in stalled_targets_ready:
  required_linter = linter producing remaining actionable errors for target
  IF required_linter in stale_linters:
    targets_to_defer.add(target)
  ELSE:
    targets_to_submit.add(target)
```

**Defer Action**: Store in `pending_investigation_targets` with context (line BG2B)

**Submit Action**: Dispatch investigation immediately (lines BG3-BG4A)

**Gap**: Definition of `required_linter` not explicit in algorithm

**Assumption**: `required_linter` = linter(s) producing errors for target in `errors_by_linter` (excluding `stale_linters`)

**Edge Case**: If target has errors from multiple linters, and ANY is stale, should defer?

**Recommendation**: Defer ONLY if ALL linters producing errors for target are stale (conservative)

---

### 4.5 <PROJECT> Special Handling

#### <PROJECT> as Target

**Definition**: Pseudo-target representing project-level/configuration errors (line 199)

**Never Hashed**: Line 199 - "never hash <PROJECT> as a file"

**Hash Equivalent**: Project fingerprint (key configs: package.json, pom.xml, tox.ini, pyproject.toml)

**Error Source**: Fatal linter crashes, unknown failures, or project-scoped diagnostics

#### <PROJECT> Locking Behavior

**Lock Check**: Line O5 - If `inv_files` non-empty (any locked files exist)

**Lock Action**: Line O6 - Remove `<PROJECT>` from `actionable_targets`

**Justification**: Project fixes may require modifying multiple files, unsafe with locks

**Log**: "Waiting for locks to clear before fixing Project"

**Gap**: If `<PROJECT>` errors can be fixed without touching locked files, this blocks unnecessarily

**Mitigation**: Consider finer-grained `<PROJECT>` locking (per-config-file basis)

#### <PROJECT> UNLINTABLE Implications

**Trigger**: Investigation for `<PROJECT>` returns NO_OP or FAILURE

**Action**: Line ABORT - Abort entire workflow

**Justification**: Line 216 - Avoid "slow death" file-by-file ejections when project config broken

**Alternative**: Could mark `<PROJECT>` as UNLINTABLE and continue with file-level fixes

**Tradeoff**: Abort provides clear signal that fundamental issue exists, but prevents partial progress

#### <PROJECT> Modification Ripple

**Trigger**: Line K3 - `project_changed = true` if `<PROJECT>` truly modified

**Action**: Line AC - Clear ALL `passed_linters` (every file)

**Justification**: Project config change may affect any file's linting results

**Alternative**: Line AM0-AM1 - Re-lint ALL_TRACKED_FILES on `project_changed`

**Gap**: If project change affects only subset of files (e.g., lint rule disabled for specific pattern), full re-lint is overkill

**Mitigation**: Could track config-change impact scope, but complexity likely not worth it

---

## 5. Investigation Lifecycle Summary

### Key Invariants

1. **Exclusive Access**: Target in `investigation_futures` → NOT in `actionable_targets` (prevents concurrent edits)

2. **Staleness Protection**: Investigation result discarded if target hash changed since dispatch (prevents stale modifications)

3. **Context Preservation**: Deferred investigations store `{error_snapshot, agent_output_snapshot}` to maintain original context

4. **Granular Blocking**: Only defer stalled targets whose `required_linter` is blocked (minimize false deferrals)

5. **UNLINTABLE is Terminal**: Once marked UNLINTABLE, target removed from `errors_by_linter` and workflow (unless external change clears it)

6. **<PROJECT> UNLINTABLE → Abort**: Prevents slow degradation when project config fundamentally broken

7. **PENDING_REFRESH Isolation**: Stale linters remain excluded from actionable errors until refresh-only tick completes

8. **No Hot Loop**: WAIT2 uses non-blocking selector with yield/sleep to prevent CPU spin

### Critical Paths

**Path 1: Immediate Investigation (No Blocking)**
```
Stall detected → Granular gating (no stale linters) → Snapshot → Dispatch → Complete → Process outcome
```

**Path 2: Deferred Investigation (Stale Linter Blocking)**
```
Stall detected → Granular gating (stale linter detected) → Defer → Wait for unblock → Snapshot → Dispatch → Complete → Process outcome
```

**Path 3: Stale Linter Recovery**
```
Investigation completes → Update blocked_by → Check empty → Mark PENDING_REFRESH → Refresh-only tick → Clear stale → Resume
```

**Path 4: Staleness Discard**
```
Investigation completes → Staleness check fails → Discard → Refresh state → Re-lint
```

### Failure Modes

**Mode 1: Livelock** - Continuous external changes prevent investigation completion
- **Detection**: High discard rate in staleness checks
- **Mitigation**: Monitor file watch events, pause agent if high churn

**Mode 2: Investigation Deadlock** - All targets deferred waiting for stale linters that never unblock
- **Detection**: `pending_investigation_targets` non-empty, `stale_linters` non-empty, no progress
- **Mitigation**: Timeout on PENDING_REFRESH state, force refresh or abort

**Mode 3: Invariant Violation** - Actionable errors exist but nothing actionable (line Q4)
- **Detection**: Line Q4 triggered
- **Mitigation**: Likely path normalization bug, log full state for debugging

**Mode 4: <PROJECT> Unrecoverable** - Investigation marks `<PROJECT>` as UNLINTABLE → abort
- **Detection**: Lines ABORT triggered
- **Mitigation**: Human intervention required (fix project config manually)

---

## 6. Recommendations

### 6.1 Potential Improvements

1. **Duplicate Dispatch Prevention**: Check if target already in `investigation_futures` before dispatch (Race 3)

2. **Required Linter Definition**: Explicitly define "required_linter" logic in algorithm (Section 4.4)

3. **seen_hashes Cleanup**: Clear `seen_hashes` for successfully linted files to prevent unbounded growth

4. **Finer-Grained <PROJECT> Locking**: Allow `<PROJECT>` fixes when they don't conflict with locked files

5. **Investigation Cancellation**: Cancel in-flight investigations on abort for faster shutdown

6. **PENDING_REFRESH Timeout**: Add timeout to PENDING_REFRESH state to detect livelock

7. **Investigator Instrumentation**: Log when investigator returns MODIFIED with no diff (Edge Case 1)

### 6.2 Testing Scenarios

1. **Concurrent External Modifications**: Simulate rapid file changes during investigations

2. **Stale Linter Cascades**: Create scenarios where multiple linters become stale simultaneously

3. **<PROJECT> Failure Recovery**: Test abort behavior and cleanup completeness

4. **Deferred Investigation Overflow**: Submit many deferrals to test memory/performance bounds

5. **Hash Collision**: Test behavior with hash collisions (if using non-cryptographic hashes)

6. **Investigation Result Race**: Simulate results arriving in reverse order of dispatch

7. **Granular Gating Correctness**: Verify targets deferred only when truly blocked

### 6.3 Monitoring Metrics

1. **Investigation Queue Depth**: `len(investigation_futures) + len(pending_investigation_targets)`

2. **Discard Rate**: Staleness check failures (JDROP trigger count)

3. **Deferral Rate**: `targets_to_defer / stalled_targets_ready` ratio

4. **Stale Linter Duration**: Time spent in STALE/SUSPENDED/PENDING_REFRESH states

5. **UNLINTABLE Accumulation**: Growth rate of `unlintable_targets`

6. **<PROJECT> Lock Blocks**: Frequency of line O6 execution (project fixes blocked)

7. **Investigation Latency**: Time from dispatch to result processing

---

## Conclusion

The investigation lifecycle is a sophisticated multi-state system with careful synchronization, staleness protection, and granular blocking logic. The design handles most race conditions through hash-based verification and exclusive locking, but some edge cases (rapid state transitions, duplicate dispatch potential) warrant additional safeguards.

The <PROJECT> special case adds complexity but provides critical fail-fast behavior for broken configurations. The deferred investigation mechanism (pending_investigation_targets) elegantly preserves context while waiting for blockers to clear, though explicit definition of "required_linter" logic would improve clarity.

Overall, the investigation system demonstrates strong engineering principles: defensive staleness checks, minimal blocking, graceful degradation (UNLINTABLE), and clear terminal conditions.
