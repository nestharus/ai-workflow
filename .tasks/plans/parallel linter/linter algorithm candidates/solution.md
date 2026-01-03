## Risk Assessment Summary

| Candidate                         | Implementation Risk | Scope Creep Risk | Integration Risk | Regression Risk | Complexity Risk |
| --------------------------------- | ------------------- | ---------------- | ---------------- | --------------- | --------------- |
| 1) Data Flow Pipeline (11 stages) | High                | High             | High             | High            | High            |
| 2) Domain-Driven (5 domains)      | Medium              | Medium           | Medium           | Medium          | Medium          |
| 3) Layered (5 layers)             | Low                 | Low              | Low              | Medium          | Low             |
| 4) State Machine (6 states)       | High                | High             | High             | High            | Medium          |
| 5) Process-Centric (5 concerns)   | Medium              | High             | High             | High            | High            |

### Trade-off Analysis

* **Testability improvements vs. abstraction overhead**

    * **Highest testability**: (1) Pipeline, (5) Process-centric (many units become mockable/pure)
    * **Best balance**: (2) Domain-driven (big testability win with moderate surface area)
    * **Lowest overhead**: (3) Layered (mostly reorganizes; fewer new types), but test seams are weaker unless you also add cross-cutting abstractions.

* **Isolation benefits vs. interface proliferation**

    * **Most interfaces**: (1) Pipeline, (5) Process-centric (risk of “component soup” and glue code).
    * **Controlled interfaces**: (2) Domain-driven (interfaces map to real responsibilities).
    * **Least interface growth**: (3) Layered, (4) State machine (but (4) replaces interfaces with a large shared context, which is a different kind of coupling).

* **Platform abstraction vs. performance impact**

    * **Best platform isolation**: (5) Process-centric (POSIX/Windows process trees, termination, etc.).
    * **Performance risk** is mostly from:

        * extra copying/serialization (pipeline-style data passing),
        * larger result objects crossing process boundaries (execution),
        * excessive buffering in text-mode ordering.
    * (2) and (3) typically keep performance closest to today because they can preserve current algorithms and only move code.

* **Explicit control flow vs. code verbosity**

    * **Most explicit**: (4) State machine (very readable transitions, but verbose and introduces a large mutable context).
    * **Moderately explicit**: (2) Domain-driven (explicit ownership, still normal control flow).
    * **Least intrusive**: (3) Layered (control flow remains mostly the same; boundaries are conceptual unless enforced).

---

## Critical Coupling Points

1. **Shutdown coordination spans signal handling, execution loop, and cleanup**

    * SIGINT / shutdown must: set `shutdown_event`, stop executors, cancel futures, terminate process trees (POSIX group / Windows Job Objects), restore snapshots, and flush output. This is cross-cutting and timing-sensitive.

2. **Snapshot lifecycle is coupled to task identity and cancellation paths**

    * Snapshots are created **in the main process before submit** for mutators, tracked per task, and later restored:

        * on mutator crash: restore only the crashed task’s fileset snapshot (atomic).
        * on fail-fast/SIGINT: restore snapshots for in-flight/terminated mutator tasks.

3. **Text output ordering is coupled to chunking and concurrency**

    * Deterministic output depends on:

        * sequential `chunk_id` assignment at phase-item generation,
        * buffering keyed by `chunk_id`,
        * sliding-window flush using `next_expected_chunk_id`,
        * `as_completed` collection + shutdown checks.

4. **`fileset_by_linter` cache couples scheduling ↔ execution ↔ post-mutation refresh**

    * The cache is built once (applicability pre-scan), reused for phase-items, and only pruned for deleted paths *after a mutating phase that actually modified files*—without re-running `calculate_fileset` or re-querying git. This creates a hard boundary: execution must know when to invalidate/prune and how.

5. **Linter instance identity is a correctness constraint, not just an implementation detail**

    * Each linter instance gets a unique `instance_id` participating in hashing/equality so “same config” instances don’t collapse in dict keys; extraction must preserve this exactly or results/caches will silently merge.

6. **Mutator phase packing depends on shared understanding of “resources”**

    * Scheduling packs mutators in parallel only when resource sets are disjoint, and resource scope is linter-defined (File vs Directory). If the resource model moves, the scheduler and `calculate_fileset`/scope metadata must remain consistent.

---

## Recommendation

**Selected Strategy:** **Candidate 2 (Domain-Driven) as the primary decomposition, with selective Candidate 5 (Process-Centric) extractions inside the Execution domain.**

### Rationale

* **Minimizes refactor blast radius**: The algorithm already clusters naturally into file discovery → linter config → scheduling → execution → output; domain-driven makes those boundaries explicit without rewriting control flow.
* **Allows safe, incremental extraction**: Start with leaf/pure domains, leaving the concurrency/snapshot/shutdown core intact until supporting scaffolding exists.
* **Targets the real risk areas without forcing a full rewrite**: The most error-prone logic is concentrated in execution/shutdown/snapshot/output-ordering; process-centric components are valuable there, but too risky as a first-step “primary architecture.”
* **Improves testability quickly**: File discovery, spec expansion, chunking, scheduling, and result aggregation can become deterministic, unit-testable modules while preserving today’s runtime behavior.
  (The execution domain remains integration-tested until later hardening.)

### Extraction Plan

1. **File Discovery Domain** (first extraction target) — *Why first*

    * It is effectively a “leaf” concern and can be extracted with minimal coupling to execution/scheduling.
    * It encapsulates: git commands, normalize→dedupe→ignore→exists-filter→sort pipeline.
    * Immediate benefits:

        * deterministic tests via mocking subprocess + filesystem,
        * reduces branching complexity in the main orchestrator,
        * provides a stable `files` contract for everything downstream.

2. **Linter Configuration Domain** — *Depends on (1)*

    * Extract:

        * `_expand_linter_spec` (operator parsing, range slicing),
        * explicit linter tracking,
        * conversion to instances + `instance_id` assignment invariants.
    * Key safety rule: preserve `instance_id`-based identity semantics exactly.

3. **Scheduling Domain** — *Depends on (2)*

    * Extract:

        * classification (mutating / read-only parallel-safe / read-only sequential),
        * deterministic ordering,
        * mutator packing by resource disjointness,
        * commit-mode restriction,
        * applicability pre-scan + `fileset_by_linter` cache creation.
    * Keep the output identical: skipped reasons for empty filesets, and “no linters / no applicable linters” behaviors.

4. **Phase Item Generation utilities (pure, within Scheduling)** — *Depends on (3)*

    * Extract `ArgMaxChunker` + chunk-id assignment into scheduling, so execution receives fully formed `(linter, fileset_chunk, chunk_id, snapshot_needed)` items.
    * This reduces coupling where execution currently “knows” chunking rules and ordering invariants.

5. **Output Domain** — *Can run in parallel with (4), but easiest after*

    * Introduce an `OutputStrategy` abstraction:

        * YAML: accumulate structured results + meta
        * Text: phase headers + ordered chunk output
    * Goal: remove scattered `yaml_output?` conditionals from deep execution paths and centralize formatting.

6. **Execution Domain (stabilize boundaries first; then process-centric internals)** — *Depends on (3)/(4)/(5)*

    * Step 6a (boundary extraction): wrap existing `execute_phase` behind an `Executor` interface that consumes phase items and returns raw chunk results.
    * Step 6b (process-centric internals, incremental order):

        1. **OrderedOutputBuffer** (if not fully moved into OutputStrategy)
        2. **ResultCollector** (chunk aggregation + diagnostic dedupe)
        3. **SnapshotManager** (explicit lifecycle + cleanup)
        4. **ShutdownCoordinator** (idempotent, callback-based)
        5. **ProcessTreeManager/SubprocessRunner** (POSIX/Windows isolation, timeouts, termination)
    * This order ensures you don’t touch termination + snapshots until you have a single coordination point and tests around it.
    * Preserve critical behaviors: fail-fast cancellation semantics, late-result ignoring, and snapshot restore rules.

### Success Criteria

* **Behavioral equivalence**

    * Same exit codes for the same scenarios:

        * invalid options/spec/unknown linter → 1
        * no changes / no files in commit / no applicable linters → 0
        * SIGINT → 130
    * Same scheduling guarantees: mutating phases before read-only; deterministic mutator ordering; commit-mode forbids mutators.

* **Determinism**

    * File discovery outputs are stable (normalized + deduped + sorted).
    * Text-mode output remains chunk-ordered, regardless of `as_completed` completion order.

* **Correctness under failure**

    * Mutating linter crash restores *only* the crashed task’s fileset snapshot and aborts immediately.
    * Fail-fast/SIGINT terminates running process trees and restores in-flight mutator snapshots, and does not continue to subsequent phases.

* **Testability improvements**

    * Unit tests exist for:

        * spec expansion edge cases (empty expansion, invalid operator/name),
        * file discovery modes (changed-only, commit, explicit, whole-repo),
        * ARG_MAX chunking boundaries,
        * scheduler packing behavior (resource overlaps),
        * result aggregation/deduplication.

### Rollback Plan

* **Keep the current monolith as the reference path** until the new domain modules are proven.
* Introduce each extracted domain behind a thin wrapper that can route to:

    * **old implementation** (default) or
    * **new implementation** (flag / environment variable / config toggle).
* Rollback strategy by step:

    * If step N regresses, disable routing for step N only and keep earlier extracted leaf domains (which should be behaviorally identical).
    * Avoid “big bang” merges—each step must be revertable without reverting unrelated steps.

### Risks to Monitor

* **Semantic drift in identity and keying**

    * Any change to `instance_id` semantics can silently merge dict entries and corrupt `fileset_by_linter` / `all_results`.

* **Output ordering regressions**

    * Chunk IDs must remain contiguous and assigned in the same order as before; buffering must flush correctly on shutdown/fail-fast.

* **Shutdown/snapshot ordering**

    * Termination must precede restore to avoid restoring while a process still writes. The “restore in-flight mutator snapshots created in main process” invariant must hold.

* **Fileset drift handling**

    * Must prune deleted files after *mutating phase actually modified files*, and must not re-run git queries or `calculate_fileset` (behavioral contract).

* **Cross-platform process-tree differences**

    * POSIX process groups vs Windows Job Objects: termination and orphan prevention are high-risk and must be covered by platform-specific tests or CI runners. 

