## 1) Risk assessment table (1–5; 5 = best)

Interpretation:

* **Bug isolation / Coupling reduction / Testability / Incremental adoption**: higher is better
* **Implementation risk**: higher = *lower* regression risk
* **Complexity overhead**: higher = less overhead

| Candidate                  | Bug Isolation (6.3/6.4/6.5) | Coupling Reduction | Implementation Risk | Testability | Incremental Adoption | Complexity Overhead | Primary risks                                                                                                            |
| -------------------------- | --------------------------: | -----------------: | ------------------: | ----------: | -------------------: | ------------------: | ------------------------------------------------------------------------------------------------------------------------ |
| 1. State-centric           |                           4 |                  3 |                   4 |           5 |                    5 |                   3 | Orchestrator remains a “god coordinator”; read-heavy coupling via ErrorRegistry-like queries still high                  |
| 2. Lifecycle               |                           2 |                  3 |                   4 |           3 |                    4 |                   4 | Cross-cutting concerns (staleness, `<PROJECT>`, lock semantics) remain smeared across phases; weak isolation for 6.4/6.5 |
| 3. Responsibility (domain) |                           5 |                  5 |                   3 |           5 |                    4 |                   3 | More components and interfaces; needs disciplined boundaries to avoid “domain soup”                                      |
| 4. Event-driven            |                           5 |                  5 |                   1 |           5 |                    2 |                   2 | High architectural risk; event ordering and “who owns truth” can introduce subtle regressions                            |
| 5. Layered                 |                           4 |                  4 |                 3–4 |           5 |                    4 |                   3 | Can become over-abstracted unless policies/workflows are kept lean; `<PROJECT>` semantics can leak upward                |

**Conclusion:** Candidate **3** is the best *structural fit for bug isolation and coupling reduction*, but should be implemented **incrementally using Candidate 1’s explicit state ownership**, and organized using **Candidate 5’s light layering (State/Policy/Workflow)**. Avoid full Candidate 4; use “events” only as typed in-process messages if needed.

(Algorithm reference: )

---

## 2) Selected approach

### Recommended strategy: **Hybrid (Candidate 3 + Candidate 1 + light Candidate 5 layering)**

**Why this is optimal for the given constraints:**

* **Bug isolation (HIGH):** The critical issues (6.4/6.5) are fundamentally **stale-linter state machine + lock interaction + linter execution failure** problems; Candidate 3 naturally isolates those into **LinterStaleness**, **Concurrency/Locks**, and **LinterExecution** components, while Candidate 1 enforces **single-writer ownership** of the shared maps that currently drive coupling.
* **Coupling reduction (HIGH):** Breaks the tight, implicit sharing between `stale_linters`, `investigation_futures`, `errors_by_linter`, and transient tick variables by moving to:

    * “stores” (exclusive state owners),
    * “policies” (pure decisions),
    * “workflows” (multi-step mutations with explicit inputs/outputs).
* **Incremental adoption (MEDIUM/HIGH):** You can wrap existing dicts first (no behavior change), then move logic behind interfaces one seam at a time (Investigation, Staleness, ChangeTracking), keeping the algorithm running throughout.
* **Preserves race semantics:** Explicitly keeps the current ordering guarantees (reserve-before-dispatch, staleness validation at async boundaries), but makes them testable.

---

## 3) Component specification (final recommended design)

### Core data types (shared, small, and strict)

These are not “components” but are prerequisites to reduce hidden coupling.

**TargetId**

* `FileTarget(path: NormalizedPath)` or `ProjectTarget(<PROJECT>)`
* Guarantees normalization at construction time.
* Key invariant: `<PROJECT>` is never hashed as a file; project fingerprint is used instead.

**ChangeSet**

* `changed_files: Set[FileTarget]`
* `project_changed: bool`
* `source: Literal["Agent","Investigator","External","RefreshOnly"]`

**InvestigationContext**

* `error_snapshot: ErrorsByLinter` *(already excludes stale linters)*
* `agent_output_snapshot: AgentOutput`
* `created_at_tick_id` (optional, for debugging)

---

### Component 1: DiagnosticStore

**Purpose:** Single owner of all linter diagnostics and “what errors exist”.

**Owns state:**

* `errors_by_linter`

**API surface:**

```python
class DiagnosticStore:
    def snapshot(self) -> "DiagnosticsSnapshot": ...
    def update_linter(
        self,
        linter: LinterId,
        diagnostics: "DiagnosticsByTarget",
        *,
        preserve_targets: set[TargetId],   # locked + unlintable
        clear_targets: set[TargetId],      # files_to_check not in output (FILES linters)
    ) -> None: ...

    def clear_target(self, target: TargetId) -> None: ...
    def clear_targets(self, targets: set[TargetId]) -> None: ...

    def actionable_errors(
        self,
        *,
        excluded_linters: set[LinterId],
        excluded_targets: set[TargetId],
    ) -> "ErrorsByLinter": ...

    def targets_with_errors(
        self,
        *,
        excluded_linters: set[LinterId],
        excluded_targets: set[TargetId],
    ) -> set[TargetId]: ...

    def linters_with_errors_for_target(self, target: TargetId) -> set[LinterId]: ...
```

**Dependencies:** TargetId normalization utilities.

---

### Component 2: TargetStatusStore

**Purpose:** Single owner of target classification: `unlintable` and `passed_linters`.

**Owns state:**

* `unlintable_targets`
* `passed_linters`

**API surface:**

```python
class TargetStatusStore:
    def mark_unlintable(self, target: TargetId, reason: str) -> None: ...
    def unmark_unlintable(self, targets: set[TargetId]) -> None: ...
    def is_unlintable(self, target: TargetId) -> bool: ...
    def project_is_unlintable(self) -> bool: ...

    def record_passed(self, linter: LinterId, targets: set[FileTarget]) -> None: ...
    def clear_passed_for_targets(self, targets: set[TargetId]) -> None: ...
    def clear_all_passed(self) -> None: ...
```

**Dependencies:** None (pure state).

---

### Component 3: ChangeTracker

**Purpose:** Centralizes file hashing, project fingerprinting, CAS checks, and `seen_hashes`.

**Owns state:**

* `seen_hashes`
* (optional) version counter / logical clock (recommended)

**API surface:**

```python
class ChangeTracker:
    def snapshot_for_agent(self, files: set[FileTarget], include_project: bool) -> "Snapshot": ...
    def snapshot_for_investigation(self, target: TargetId) -> "Snapshot": ...

    def verify_unchanged(self, snapshot: "Snapshot") -> bool: ...  # CAS gate
    def diff(self, before: "Snapshot", after: "Snapshot") -> ChangeSet: ...

    def record_seen(self, snapshot: "Snapshot") -> None: ...
    def forget_targets(self, targets: set[TargetId]) -> None: ...
```

**Dependencies:** FileSystem hashing + project fingerprint provider.

---

### Component 4: InvestigationCoordinator

**Purpose:** Owns the investigation lifecycle: reserve → dispatch → poll → completed.

**Owns state:**

* `investigation_futures` (including per-target start snapshot)
* (optionally) the async executor integration

**API surface:**

```python
class InvestigationCoordinator:
    def locked_targets(self) -> set[TargetId]: ...

    def reserve_and_dispatch(
        self,
        targets: set[TargetId],
        *,
        context_by_target: dict[TargetId, InvestigationContext],
        start_snapshot_by_target: dict[TargetId, Snapshot],
    ) -> None: ...

    def poll_completed(self) -> list["CompletedInvestigation"]: ...
```

`CompletedInvestigation` includes:

* `target`
* `status: Literal["MODIFIED","NO_OP","FAILURE"]`
* `start_snapshot`
* `result_payload` (diff or error)

**Dependencies:** Async executor + Investigator client; ChangeTracker for start snapshots (or caller supplies them).

---

### Component 5: LinterStalenessManager

**Purpose:** Single owner of stale linter state machine and wake-up gating.

**Owns state:**

* `stale_linters` with explicit states:

    * `STALE(blocked_by=set[TargetId])`
    * `PENDING_REFRESH(blocked_by=empty)`
    * `FAILED(last_error, retry_policy)` *(added to address “FAILURE case”)*
    * ACTIVE = not present

**API surface:**

```python
class LinterStalenessManager:
    def mark_stale(self, linter: LinterId, blocked_by: set[TargetId]) -> None: ...

    def on_lock_released(self, target: TargetId) -> set[LinterId]:
        """Removes target from blocked_by; returns newly-unblocked linters that should enter PENDING_REFRESH."""
        ...

    def excluded_linters(self) -> set[LinterId]:
        """Linters whose diagnostics must be excluded from actionable errors and investigation payloads."""
        ...

    def has_pending_refresh(self) -> bool: ...

    def prepare_refresh_only_tick(
        self,
        *,
        locked_targets: set[TargetId],
        compute_blockers: "Callable[[LinterId, set[TargetId]], set[TargetId]]",
    ) -> bool:
        """
        BUG 6.4 fix point:
        - If a PENDING_REFRESH linter is blocked again, revert it to STALE(blocked_by).
        - Returns True only if at least one linter remains truly PENDING_REFRESH (safe to refresh now).
        """
        ...

    def on_linter_run_success(self, linter: LinterId) -> None: ...
    def on_linter_run_failure(self, linter: LinterId, error: Exception) -> None:
        """
        BUG 6.5 fix point:
        - Must not leave linter stuck in PENDING_REFRESH.
        - Transition to FAILED with retry/backoff, and/or surface failure as actionable <PROJECT> diagnostic.
        """
        ...
```

**Dependencies:** None directly; requires a callback to compute blockers per linter (owned by LintWorkflow / linter metadata).

---

### Component 6: ActionabilityPolicy

**Purpose:** Pure logic replacing the “ErrorCheck” set math and filtering.

**Owns state:** None.

**API surface:**

```python
class ActionabilityPolicy:
    def compute(
        self,
        *,
        diagnostics: DiagnosticsSnapshot,
        excluded_linters: set[LinterId],
        locked: set[TargetId],
        pending: set[TargetId],
        unlintable: set[TargetId],
    ) -> "ActionablePlan":
        """
        Returns actionable_errors_by_linter, actionable_targets, actionable_files.
        Applies <PROJECT> gating when locked targets exist.
        """
        ...
```

**Dependencies:** None (inputs are snapshots/sets).

---

### Component 7: AgentWorkflow

**Purpose:** Implements AgentPhase with CAS protection and candidate stall extraction.

**Owns state:**

* (optional) last agent output snapshot (for debugging and stall context)

**API surface:**

```python
class AgentWorkflow:
    def run(
        self,
        *,
        actionable_files: set[FileTarget],
        actionable_targets: set[TargetId],
        actionable_errors: ErrorsByLinter,
        project_context_files: set[FileTarget],
    ) -> "AgentRunResult": ...
```

`AgentRunResult` includes:

* `agent_output_snapshot`
* `change_set`
* `candidate_stalled_targets` (includes `<PROJECT>` if it was actionable and project_changed == False)

**Dependencies:** Agent client + ChangeTracker + FileSystem.

---

### Component 8: LintWorkflow

**Purpose:** Runs linters, updates diagnostics, updates passed cache, and integrates stale logic.

**Owns state:**

* Linter configuration/metadata:

    * scope (PROJECT vs FILES)
    * supports excluding blockers
    * per-linter blocking rules (optional cache)

**API surface:**

```python
class LintWorkflow:
    def run_post_change(
        self,
        *,
        change_set: ChangeSet,
        candidate_stalled_files: set[FileTarget],
        locked_targets: set[TargetId],
        unlintable_targets: set[TargetId],
        diagnostics: DiagnosticStore,
        target_status: TargetStatusStore,
        staleness: LinterStalenessManager,
    ) -> None: ...

    def run_refresh_only(
        self,
        *,
        locked_targets: set[TargetId],
        unlintable_targets: set[TargetId],
        diagnostics: DiagnosticStore,
        target_status: TargetStatusStore,
        staleness: LinterStalenessManager,
    ) -> None: ...
```

**Dependencies:** Linter runner + FileSystem + LinterStalenessManager.

---

### Component 9: StallDetector

**Purpose:** Implements UpdateState stall confirmation + granular gating + deferral context storage.

**Owns state:**

* `candidate_stalled_targets` (debounced)
* `pending_investigation_targets` (deferred contexts)

**API surface:**

```python
class StallDetector:
    def set_candidates(self, *, targets: set[TargetId], agent_output_snapshot: AgentOutput) -> None: ...

    def drop_on_external_change(self, changed: set[TargetId]) -> None: ...

    def plan_investigations(
        self,
        *,
        diagnostics: DiagnosticStore,
        staleness: LinterStalenessManager,
    ) -> tuple[set[TargetId], dict[TargetId, InvestigationContext]]:
        """
        Returns:
        - targets_to_submit
        - context_by_target (error_snapshot + agent_output_snapshot)
        Also updates internal deferred store (pending_investigation_targets).
        
        BUG 6.3 fix point: deferral decision must be well-defined when multiple linters affect a target.
        """
        ...

    def pending_targets(self) -> set[TargetId]: ...
    def consume_pending_context(self, targets: set[TargetId]) -> dict[TargetId, InvestigationContext]: ...
```

**Dependencies:** DiagnosticStore (for error snapshots), LinterStalenessManager.

---

### Component 10: TerminationPolicy + Reporter

**Purpose:** Pure termination checks + final report build.

**Owns state:** None.

**API surface:**

```python
class TerminationPolicy:
    def decide(
        self,
        *,
        actionable_errors_empty: bool,
        stale_linters_empty: bool,
        investigations_empty: bool,
        pending_investigations_empty: bool,
        project_unlintable: bool,
    ) -> "TerminationDecision": ...
```

**Dependencies:** None.

---

## 4) Extraction plan (ordered, with prerequisites, risk, validation)

### Step 0 — Characterization test harness (prerequisite for everything)

* **Extract:** none (tests only)
* **Risk:** Low
* **Validation strategy:**

    * Golden-state integration tests that simulate:

        * `<PROJECT>` errors → agent input includes project context files.
        * Investigation staleness drop (hash mismatch) → re-lint path.
        * Locked-target diagnostic preservation.
        * Refresh-only tick behavior when PENDING_REFRESH present.
    * Add deterministic fake scheduler for investigations (to reproduce races).

---

### Step 1 — TargetId + normalization boundary

* **Extract:** TargetId / normalization utilities
* **Prerequisites:** Step 0
* **Risk:** Low–Medium (wide callsite change, but mechanical)
* **Validation strategy:**

    * Property tests: set operations stable under path variants.
    * Regression test for “invariant violation” abort path (should disappear).

---

### Step 2 — Wrap shared maps with stores (no behavior change)

* **Extract:** `DiagnosticStore`, `TargetStatusStore`
* **Prerequisites:** Step 1
* **Risk:** Low
* **Validation strategy:**

    * Diff-based assertion: before/after wrapper refactor produces identical `errors_by_linter`, `passed_linters`, `unlintable_targets`.

---

### Step 3 — Extract LinterStalenessManager (fix 6.4 + 6.5 here)

* **Extract:** `LinterStalenessManager`
* **Prerequisites:** Step 2
* **Risk:** Medium (touches multiple subgraphs, but localized state machine)
* **Validation strategy:**

    * Unit tests for state machine transitions:

        * ACTIVE → STALE(blocked_by) → PENDING_REFRESH → ACTIVE
        * **6.4**: PENDING_REFRESH → STALE if blockers reappear before refresh
        * **6.5**: PENDING_REFRESH + linter failure → not stuck (FAILED or cleared)
    * Integration: “refresh-only tick” triggers exactly once per unblocking.

---

### Step 4 — Extract InvestigationCoordinator (in-flight only first)

* **Extract:** `InvestigationCoordinator` (reserve/dispatch/poll)
* **Prerequisites:** Step 3
* **Risk:** Medium–High (async boundary + lock semantics)
* **Validation strategy:**

    * Unit tests:

        * reserve-before-dispatch prevents agent touching locked targets.
        * polling returns completed results exactly once.
    * Integration:

        * investigation completion updates stale-linter blocked_by via manager call.

---

### Step 5 — Extract ChangeTracker (centralize staleness + seen_hashes)

* **Extract:** `ChangeTracker`
* **Prerequisites:** Steps 2–4
* **Risk:** Medium (cross-cutting)
* **Validation strategy:**

    * Unit tests for snapshot/diff and CAS failure → external change path.
    * Integration tests for investigator staleness rejection and cleanup of `seen_hashes`.

---

### Step 6 — Extract ActionabilityPolicy + TerminationPolicy (pure)

* **Extract:** `ActionabilityPolicy`, `TerminationPolicy`
* **Prerequisites:** Steps 2–5
* **Risk:** Low (pure functions)
* **Validation strategy:**

    * Exhaustive table tests on combinations of:

        * locked targets present/absent
        * pending present/absent
        * stale linters present/absent
        * `<PROJECT>` errors present/absent

---

### Step 7 — Extract LintWorkflow

* **Extract:** `LintWorkflow`
* **Prerequisites:** Steps 2–6
* **Risk:** Medium–High (large logic move)
* **Validation strategy:**

    * Compare outputs of legacy ProcessLinters vs new workflow on recorded fixtures.
    * Explicit test: “locked-target diagnostic preservation” is enforced via `preserve_targets`.

---

### Step 8 — Extract AgentWorkflow

* **Extract:** `AgentWorkflow`
* **Prerequisites:** Step 5 (ChangeTracker)
* **Risk:** Medium
* **Validation strategy:**

    * CAS failure test: pre-write check fails → triggers refresh/external change behavior.
    * Candidate stall extraction test (files unchanged + errors persist).

---

### Step 9 — Extract StallDetector (fix 6.3 here)

* **Extract:** `StallDetector` + pending deferred context store
* **Prerequisites:** Steps 2–8
* **Risk:** Medium (touches investigation submission logic + gating)
* **Validation strategy:**

    * Unit tests for:

        * confirmed stalls = candidate ∩ verified errors (excluding stale linters)
        * **6.3** multi-linter ambiguity resolution (see below)
    * Integration test:

        * deferred target uses stored `{error_snapshot, agent_output_snapshot}` when dispatched later.

---

## 5) Bug fix integration (6.3, 6.4, 6.5)

### Bug 6.3 — `required_linter` ambiguity (MEDIUM)

**Problem:** When a target has errors from multiple linters and at least one is stale, “required_linter” is underspecified; the gating decision can submit when it should defer (or vice versa).

**Fix (in StallDetector):** Make deferral rule explicit and conservative:

* For each stalled target, compute:

    * `linters_with_errors = diagnostics.linters_with_errors_for_target(target)`
    * `should_defer = any(l in staleness.excluded_linters() for l in linters_with_errors)`
* If `should_defer`: defer and store context.
* Else: submit.

This removes “choose one required_linter” ambiguity entirely; the rule becomes “**defer if any part of the target’s error context is stale**.”

**Validation:** unit test with:

* Target T has errors from L1 (active) and L2 (stale) → must defer.
* Target U has errors from L1 only (active) → may submit.

---

### Bug 6.4 — Refresh-only tick race (HIGH)

**Problem:** A linter marked PENDING_REFRESH can become blocked again before the refresh-only tick runs, causing it to flip back to stale mid-refresh and potentially lose liveness.

**Fix (in LinterStalenessManager + ActionabilityPolicy integration):**

* Before executing refresh-only tick, call:

    * `staleness.prepare_refresh_only_tick(locked_targets=snapshot, compute_blockers=...)`
* If it returns **False**, do **not** run refresh-only tick; normal flow continues (or you remain in stale state).
* Ensure LintWorkflow always recomputes `locked_targets` from InvestigationCoordinator at the start of its execution (no dependence on a transient `inv_files` value).

**Validation:** deterministic test:

* Linter enters PENDING_REFRESH
* Simulate lock set changing before refresh tick starts
* Verify linter is reverted to STALE(blocked_by) and refresh-only tick is skipped.

---

### Bug 6.5 — Stale linter entry leakage / missing FAILURE state (HIGH)

**Problem:** If a PENDING_REFRESH linter fails to run, it can remain stuck in PENDING_REFRESH, forcing refresh-only ticks forever.

**Fix (in LintWorkflow + LinterStalenessManager):**

* LintWorkflow wraps linter execution:

    * On success: `staleness.on_linter_run_success(linter)` (clears from stale set)
    * On failure: `staleness.on_linter_run_failure(linter, err)`

        * Must **not** leave PENDING_REFRESH.
        * Transition to `FAILED` with retry/backoff (or clear staleness entirely and surface failure as actionable `<PROJECT>` diagnostic).
* TerminationPolicy must treat FAILED linters as “not clean” (i.e., do not allow success while a linter is in FAILED unless you intentionally downgrade).

**Validation:** unit test:

* Put linter in PENDING_REFRESH
* Force linter run failure
* Assert: `has_pending_refresh()` becomes false (no infinite refresh loop)
* Assert: algorithm does not incorrectly report success while failure persists (FAILED counted as blocking).

---

If you implement only one slice first: **LinterStalenessManager + its integration points (Steps 3 and 7)**, because it directly contains the highest-severity correctness/liveness risks (6.4 and 6.5) while also reducing coupling to locks and linter execution.
