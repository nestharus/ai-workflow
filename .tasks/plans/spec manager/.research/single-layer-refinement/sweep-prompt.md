# Single-Layer Sweep: Add Integration TODOs from Proposal

## Your Task

Read the complete design proposal in `.tasks/plans/spec manager/.research/single-layer-refinement/response3.md`.
Then read each file listed below and add TODO comments directly into the source code
indicating what the proposal says should change and how.

**Format for every TODO:**

```python
# TODO(single-layer): [CATEGORY] description
#   Proposal ref: Section N — "quoted key phrase"
```

Categories:
- `DELETE` — this module/class/function is eliminated entirely
- `REPLACE` — this is replaced by a new mechanism (say which)
- `RESTRUCTURE` — this stays but its internals change significantly
- `KEEP` — this survives as-is or with minor adaptation
- `NEW` — placeholder for a module/function that needs to be created

Place TODOs at the **top of each file** (file-level summary) AND at **specific
functions/classes** that are affected. Be precise — quote the proposal section
that justifies the change.

---

## Files to Annotate (by category)

### PIN System — Proposal Section 12.2, 15 (eliminate)

These modules exist solely for the PIN bridging system. The proposal says
PINs are retired because single-layer has no layers to bridge.

Read each file, add file-level `DELETE` TODO explaining what replaces its role:

- `scripts/spec_manager/spec_manager/schemas/pin_functions.py`
- `scripts/spec_manager/spec_manager/core/pin_registry.py`
- `scripts/spec_manager/spec_manager/branches/pins.py`
- `scripts/spec_manager/spec_manager/pin_functions/__init__.py`
- `scripts/spec_manager/spec_manager/pin_functions/cli.py`
- `scripts/spec_manager/spec_manager/pin_functions/orchestrator.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/pin_coverage.py`
- `scripts/spec_manager/spec_manager/projection/pin_propagation.py`
- `scripts/spec_manager/spec_manager/projection/drift.py`
- `scripts/spec_manager/spec_manager/projection/lineage/drift_detector.py`
- `scripts/spec_manager/spec_manager/projection/lineage/test_pin_baseline.py`
- `scripts/spec_manager/spec_manager/projection/lineage/test_pin_discovery.py`
- `scripts/spec_manager/spec_manager/projection/lineage/test_pin_checker.py`

### Layer Pipeline — Proposal Sections 9, 12.2 (restructure/eliminate)

The three-layer pipeline (L1→L2→L3) is replaced by a single-layer
four-phase mechanism (Build→Algorithm→Architecture→Quality).

- `scripts/spec_manager/spec_manager/orchestration/pdd_lifecycle.py`
  — Layer sequence and transition machinery. Proposal says large portions eliminated.
    Read carefully: what parts are layer-specific vs reusable phase infrastructure?

- `scripts/spec_manager/spec_manager/orchestration/promotion_loop.py`
  — Layer-aware dispatch matrix. This is the largest file. Read it and identify:
    - Which dispatch branches are layer-specific (DELETE)
    - Which step implementations survive as phase implementations (RESTRUCTURE)
    - The 10-step state machine itself — does it survive or get replaced?

- `scripts/spec_manager/spec_manager/planner/router.py`
  — Layer-based planner routing. Collapses to phase routing.

- `scripts/spec_manager/spec_manager/planner/layers/l1.py`
- `scripts/spec_manager/spec_manager/planner/layers/l2.py`
- `scripts/spec_manager/spec_manager/planner/layers/l3.py`
  — Layer-specific planner strategies. These collapse into phase-specific strategies.

### Demotion — Proposal Section 11 (restructure)

Demotion becomes "work item escalation" — triage assigns
`{phase, shape_id, required_change_type, evidence}` instead of demoting to L1/L2.

- `scripts/spec_manager/spec_manager/orchestration/demotion/__init__.py`
- `scripts/spec_manager/spec_manager/orchestration/demotion/triage.py`
- `scripts/spec_manager/spec_manager/orchestration/demotion/router.py`
- `scripts/spec_manager/spec_manager/orchestration/downward_flow/engine.py`
  — Pin-driven downward flow. Proposal section 12.2 says eliminate.

### Compliance Gates — Proposal Section 10 (restructure)

Layer gates become aspect gates (Behavior/Architecture/Quality).
PIN gates eliminated. Call graph gate becomes soft routing signal.

- `scripts/spec_manager/spec_manager/compliance/promotion/__init__.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/config.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/algorithmic_gates.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/architectural_quality.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/call_graph.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/provenance.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/result.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/evidence_loader.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/introduction_checker.py`
- `scripts/spec_manager/spec_manager/compliance/promotion/test_pin_gate.py`

### Coordination / Work Items — Proposal Section 8 (restructure/extend)

Work items gain `shape_id` as primary routing handle. Coordination signals
may need shape-awareness.

- `scripts/spec_manager/spec_manager/orchestration/coordination/work_items.py`
- `scripts/spec_manager/spec_manager/orchestration/coordination/signals.py`
- `scripts/spec_manager/spec_manager/orchestration/coordination/monitors.py`
- `scripts/spec_manager/spec_manager/orchestration/coordination/monitor_executor.py`
- `scripts/spec_manager/spec_manager/orchestration/coordination/wake_queue.py`
- `scripts/spec_manager/spec_manager/orchestration/coordination/wait_graph.py`

### Projection / Lineage — Proposal Sections 6, 12 (restructure)

Lineage tracking survives but pin-based edges are replaced by
shape-based ownership. Import scan becomes input to shape matching.

- `scripts/spec_manager/spec_manager/projection/__init__.py`
- `scripts/spec_manager/spec_manager/projection/generator.py`
- `scripts/spec_manager/spec_manager/projection/lineage/builder.py`
- `scripts/spec_manager/spec_manager/projection/lineage/table.py`
- `scripts/spec_manager/spec_manager/projection/lineage/edges.py`
- `scripts/spec_manager/spec_manager/projection/lineage/data_flow.py`
- `scripts/spec_manager/spec_manager/projection/lineage/persistence.py`

### New Modules — Proposal Section 12.4 (create)

These don't exist yet. Add a NEW placeholder file for each with the
module's purpose documented:

- `scripts/spec_manager/spec_manager/routing/shapes.py`
  — Parse/load shape docs, path→shape mapping, IDs (Section 4, 5)
- `scripts/spec_manager/spec_manager/routing/verifiers.py`
  — Run verifier commands/checks, collect evidence (Section 4.1, 6.3)
- `scripts/spec_manager/spec_manager/routing/matcher.py`
  — Compare declared vs observed, emit work items (Section 6)
- `scripts/spec_manager/spec_manager/routing/__init__.py`

### Supporting Modules (check for layer/pin references)

These modules may reference layers or pins indirectly. Read and add
TODOs where layer/pin assumptions exist:

- `scripts/spec_manager/spec_manager/orchestration/pdd_orchestrator.py`
- `scripts/spec_manager/spec_manager/orchestration/implementation/runner.py`
- `scripts/spec_manager/spec_manager/orchestration/intent_agent/agent.py`
- `scripts/spec_manager/spec_manager/orchestration/intent_agent/taxonomy.py`
- `scripts/spec_manager/spec_manager/orchestration/evidence.py`
- `scripts/spec_manager/spec_manager/orchestration/run_state.py`
- `scripts/spec_manager/spec_manager/orchestration/pattern_library.py`
- `scripts/spec_manager/spec_manager/orchestration/review/findings_to_tickets.py`
- `scripts/spec_manager/spec_manager/orchestration/under_spec/manager.py`
- `scripts/spec_manager/spec_manager/core/layer_types.py`
- `scripts/spec_manager/spec_manager/schemas/projection.py`
- `scripts/spec_manager/spec_manager/planner/api.py`
- `scripts/spec_manager/spec_manager/planner/strategies/architecture_strategy.py`
- `scripts/spec_manager/spec_manager/planner/strategies/constraint_strategies.py`
- `scripts/spec_manager/spec_manager/planner/constraints/store.py`
- `scripts/spec_manager/spec_manager/planner/architecture/artifacts.py`

---

## Important

- **Read the proposal first** — every TODO must cite a specific section.
- **Read each file before annotating** — understand what it does before deciding what changes.
- **Be conservative with DELETE** — only mark entire files as DELETE if they have no
  purpose outside the layer/pin system. If a file has reusable logic, mark the
  reusable parts as KEEP and the layer/pin parts as DELETE.
- **For RESTRUCTURE files**, describe what the new shape should look like
  (e.g., "layer dispatch → phase dispatch", "pin coverage → shape verifier check").
- **Don't modify actual logic** — only add TODO comments. No code changes.
