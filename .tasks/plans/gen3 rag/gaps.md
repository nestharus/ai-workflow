# Spec Gaps, Dragons, and Proof Obligations

This file tracks unresolved gaps, dragons (known issues), and proof obligations across all patches.

## Legend

- **Gap**: Missing specification detail
- **Dragon**: Known issue or complexity that needs addressing
- **Proof Obligation**: Mathematical claim requiring formal proof
- **Status**: `OPEN` | `RESOLVED` | `BYPASSED` | `DEFERRED` | `LEAN_PROOF` | `APPLIED`

---

## Missing Lean Proofs Summary

This section tracks proof sketches that currently lack formal Lean proofs.

### Claims with Lean Proofs (proof sketches deleted)
| ID | Claim | Lean Proof Location |
|----|-------|-------------------|
| P4C1 | Lossless structural abstraction | plan.md line 4234: Lean: Lossless compress/expand |
| P4C4 | Failure memory suppression | plan.md line 4265: Lean: Monotone failure brake |
| P1C5 | Robust loss reduces influence | plan.md line 4288: Lean 3: IRLS descent and stationary point |

### Claims Needing Lean Proofs (proof sketches retained)
| ID | Claim | Proof Sketch Location | Priority |
|----|-------|----------------------|----------|
| P4C2 | MDL-driven abstraction reduces description length | plan.md line 3172 | MEDIUM |
| P4C3 | Promotion guarantee (Beta posterior) | plan.md line 3178 | HIGH |
| P4C5 | Risk governance calibration (conformal prediction) | plan.md line 3184 | MEDIUM |
| P1C1 | Evidence permanence holds under all operations | plan.md line 3802 | HIGH |
| P1C2 | Gated quadratic field has unique minimizer | plan.md line 3814 | HIGH |
| P1C3 | Field relaxation converges per hypothesis | plan.md line 3814 | HIGH |
| P1C4 | Persistent conflict produces durable ambiguity | plan.md line 3822 | MEDIUM |

---

## plan.md Original Gaps

| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| GAP-0.1 | Edge types and default weights per type | OPEN | |
| GAP-0.2 | Anchor policy (α_i) by node level and tier | OPEN | |
| GAP-0.3 | Validation budget policy, including when an LLM is called | OPEN | |
| GAP-0.4 | Merge and split rules for idea nodes | OPEN | |
| GAP-0.5 | Exact uncertainty update rule (u_i) tied to residuals or local variance | OPEN | |

---

## P1 Gaps and Dragons

### Gaps Resolved by P1
| Original Gap | P1 Resolution |
|--------------|---------------|
| Field overwrites | NodeState append-only history |
| Edge overwrites | EdgeBelief with status, gate, evidence, tension |
| Merges losing alternatives | Non-destructive aliasing plus lineage |
| Ambiguity averaged away | Conflict ledger plus branching |
| Quantization losing detail | Lossless or near-lossless backstore |
| Missing diagnostics | Residual, tension, uncertainty, confidence proxies |
| Missing information seeking | Conflict resolution loop |

### Proof Obligations
| ID | Claim | Status | Notes |
|----|-------|--------|-------|
| P1C1 | Evidence permanence holds under all operations | APPLIED | Proof sketch provided in plan.md - NO Lean proof |
| P1C2 | Gated quadratic field per hypothesis has unique minimizer | APPLIED | Same SPD argument as v0.1 - NO Lean proof |
| P1C3 | Field relaxation converges per hypothesis | APPLIED | Block coordinate descent - NO Lean proof |
| P1C4 | Persistent conflict produces durable ambiguity artifact | APPLIED | By construction - NO Lean proof |
| P1C5 | Robust loss reduces influence of large disagreements | LEAN_PROOF | Lean proof provided in plan.md (line 4288) - proof sketch deleted |

### New Gaps Introduced by P1
| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| GAP-P1.1 | Default gate values (g) for different edge types | OPEN | Need policy specification |
| GAP-P1.2 | Threshold values for TH_TENSION and TH_RESID | OPEN | Need empirical calibration |
| GAP-P1.3 | Conflict resolution budget allocation policy | OPEN | Need cost model |
| GAP-P1.4 | Hypothesis branch scope determination | OPEN | Need scoping algorithm |
| GAP-P1.5 | Gate adjustment rates in INCREASE_GATE/DECREASE_GATE | OPEN | Need update policy |

---

## P2 Gaps and Dragons

### Gaps Addressed
| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| Gap G2.1 | Global solve exists only as a note | RESOLVED | Algorithm 6 (Global Consolidation) |
| Gap G2.2 | Robust loss has no IRLS update rule | RESOLVED | Algorithm 7 (Robust Field Solve via IRLS) |
| Gap G2.3 | Index rebuild/swap protocol missing | RESOLVED | Algorithm 9 (RCU-style publish) |

### Proof Obligations
| ID | Claim | Status | Notes |
|----|-------|--------|-------|
| P2C1 | Snapshot consistency | APPLIED | Proof sketch provided - MVCC-based |
| P2C2 | Non-blocking commit | APPLIED | Proof sketch provided - RCU grace period |
| P2C3 | IRLS descent | APPLIED | Proof sketch provided - MM majorization |
| P2C4 | IRLS convergence to stationary point | APPLIED | Proof sketch provided - Standard MM theorem |
| P2C5 | No evidence loss | APPLIED | Proof sketch provided - Event sourcing |

### New Gaps Introduced by P2
| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| GAP-P2.1 | Consolidation trigger thresholds (drift, tension, recall decay) | OPEN | Need empirical calibration |
| GAP-P2.2 | IRLS stopping rule parameters (τ, Kmax, solver tolerance) | OPEN | Need performance tuning |
| GAP-P2.3 | RCU grace period duration | OPEN | Need based on reader quiescence |
| GAP-P2.4 | Warm start initialization strategy | OPEN | Need interpolation policy |
| GAP-P2.5 | Delta catch-up budget and local repair scope | OPEN | Need cost model |


---

## P4 Gaps and Dragons

### Proof Obligations
| ID | Claim | Status | Notes |
|----|-------|--------|-------|
| P4C1 | Lossless structural compression | LEAN_PROOF | Lean proof provided in plan.md (line 4234) - proof sketch deleted |
| P4C2 | MDL-driven abstraction reduces description length | APPLIED | Proof sketch provided in plan.md - NO Lean proof |
| P4C3 | Confidence-weighted promotion has probabilistic meaning | APPLIED | Proof sketch provided in plan.md - NO Lean proof |
| P4C4 | Failure memory decreases repeat error probability | LEAN_PROOF | Lean proof provided in plan.md (line 4265) - proof sketch deleted |
| P4C5 | Risk governance provides calibrated deferral | APPLIED | Proof sketch provided in plan.md - NO Lean proof |

---

## P5 Gaps and Dragons

### Proof Obligations
| ID | Claim | Status | Notes |
|----|-------|--------|-------|
| P5C1 | Multi-view canonical field solve exists and is unique | APPLIED | SPD argument with multi-view anchors |
| P5C2 | Rewrite steps preserve evidence permanence | APPLIED | Graph rewrite preserves provenance by construction |
| P5C3 | Packed forest representation preserves derivations | APPLIED | Grammar class restrictions required for polynomial parsing |
| P5C4 | Orthogonal adapter preserves geometry | APPLIED | Distance preservation for orthogonal matrices |

### New Gaps Introduced by P5
| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| GAP-P5.1 | Grammar class restrictions per tier | OPEN | Need policy for which grammar classes allowed in Focus/Active/Context/Sleep |
| GAP-P5.2 | Rule scoring model specification | OPEN | Need concrete probability/cost models for rule applications |
| GAP-P5.3 | Parse forest beam width policy | OPEN | Need thresholds for hypothesis pruning |
| GAP-P5.4 | Adapter fitting frequency and triggers | OPEN | When to refit adapters during sleep-time |
| GAP-P5.5 | Grammar promotion criteria | OPEN | Confidence thresholds and shadow run requirements |
| GAP-P5.6 | Token type registry and coordination | OPEN | How token types register embedding spaces and coordinate systems |
| GAP-P5.7 | Re-ingestion scheduling policy | OPEN | When and how to trigger re-interpretation |

---

## P6 Gaps and Dragons

### Proof Obligations
| ID | Claim | Status | Notes |
|----|-------|--------|-------|
| P6C1 | Workspace isolation | OPEN | |
| P6C2 | Snapshot consistency | OPEN | |
| P6C3 | Safe reclamation | OPEN | |
| P6C4 | Surprise budget prevents calcification | OPEN | |
| P6C5 | Grammar promotion controls error | OPEN | |
| P6C6 | Adapter rollout is safe under canary plus rollback | OPEN | |

---

## P8 Gaps and Dragons

### Gaps Addressed by P8
| Original Gap | P8 Resolution |
|--------------|---------------|
| Pattern transfer mechanism | Factor profiles + effect metrics enable pattern transfer |
| Pattern purpose/functionality | Effect signatures make purpose computable |
| Module reusability | Module extraction with stable interfaces |
| Idea generation beyond noise | Pattern transfer + hybridization as generative drivers |

### Known Limitations
| ID | Description | Status | Mitigation |
|----|-------------|--------|------------|
| GAP-P8.1 | Unsupervised disentanglement has identifiability limits (Locatello et al.) | KNOWN | System has strong inductive biases: typed edges, slot schemas, hypotheses, provenance, outcome feedback |
| GAP-P8.2 | MDL gain computation for modules not specified | OPEN | Need concrete algorithm for MDL_GAIN_WITH_MODULE |
| GAP-P8.3 | Interface compatibility checking not specified | OPEN | Need algorithm for FILTER_BY_MODULE_INTERFACE |
| GAP-P8.4 | Pareto frontier computation details missing | OPEN | Need concrete multi-objective optimization approach |
| GAP-P8.5 | Hybrid connector module generation not specified | OPEN | Need algorithm for connector synthesis |
| GAP-P8.6 | Factor dictionary size K selection | OPEN | Need policy for choosing number of factors |
| GAP-P8.7 | Sparse autoencoder hyperparameters (lambda) | OPEN | Need calibration policy |
| GAP-P8.8 | CANDIDATE_SUBGRAPHS algorithm not specified | OPEN | Need frequent motif mining with stable interface detection |
| GAP-P8.9 | Effect metric thresholds and weights | OPEN | Need policy for stability/generality/brittleness/cost tradeoffs |

### Design Notes
| Note | Description |
|------|-------------|
| NOTE-P8.1 | P8 reframes P7 creativity mechanism from pure noise to pattern transfer + recombination |
| NOTE-P8.2 | Module extraction is MDL compression one level deeper than P4 patterns |
| NOTE-P8.3 | LLM role: naming, interpreting tradeoffs, proposing evidence/connectors - NOT primary disentanglement |
| NOTE-P8.4 | Disentanglement runs in P6 sleep cycle |
| NOTE-P8.5 | Factor learning uses sparse coding family (Dictionary Learning, ICA, NMF options) |
| NOTE-P8.6 | Pattern functionality measured via effects (energy reduction, conflict resolution, retrieval utility, cost) |

---

## P9 Dragons (All Closed Per P9 Document)

| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| D1 | Edge types and default weights | CLOSED | defaults defined (P4/P9) + learn deltas via feedback |
| D2 | Anchor policy α by level/tier | CLOSED | explicit table policy + curriculum overrides |
| D3 | Validation budget policy | CLOSED | budgets + two-stage commit + scheduling |
| D4 | Merge/split rules for idea nodes | CLOSED | non-destructive aliasing + lineage |
| D5 | Exact uncertainty update rule | CLOSED | u is explicit diagnostic field (EWMA over r/T/var/conflicts) |
| D6 | Vector ↔ manifold translation | CLOSED | charts + connection Laplacian transport + pullback proposals |
| D7 | Force → topology promotion | CLOSED | governed promotion (reproduced + stable + guardrails) |
| D8 | Cross-epoch comparability | CLOSED | pinned reads by lsn + optional anchor-based alignment |
| D9 | LLM latent → topology inverse | BYPASSED | forbidden; must go through proposal→validate→commit |
| D10 | Zero downtime sleep | CLOSED | snapshot + delta catch-up + routing |
| D11 | A/B continuous deployment | CLOSED | shadow + canary + rollback + graduate |

---
---


## P7 Gaps and Dragons

### Proof Obligations
| ID | Claim | Status | Notes |
|----|-------|--------|-------|
| P7C1 | Evidence stays | OPEN | |
| P7C2 | Exploration stays bounded | OPEN | Lean skeleton provided |
| P7C3 | Learning progress avoids random noise trap | OPEN | |
| P7C4 | Novelty helps coverage | OPEN | |
| P7C5 | Information gain guides ambiguity resolution | OPEN | Optional submodularity guarantee |

### New Gaps Introduced by P7
| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| GAP-P7.1 | Threshold values for TH_QUEUE, T0, r0, v0 | OPEN | Need empirical calibration |
| GAP-P7.2 | Weight values for interestingness score | OPEN | Need domain-specific tuning |
| GAP-P7.3 | Budget allocation policy across domains | OPEN | Need cost model |
| GAP-P7.4 | LLM call decision criteria in SHOULD_CALL_LLM | OPEN | Need heuristic or learned policy |
| GAP-P7.5 | Seed decay and quarantine thresholds | OPEN | Need empirical calibration |

---

## Cross-Cutting Issues

### Algorithm Numbering Collision
- **Issue**: Multiple patches use same algorithm numbers
  - P6: Algorithm 24-32
  - P9: Algorithm 24-32
  - P10: Algorithm 31-42
- **Status**: OPEN
- **Resolution**: Need global renumbering during patch application

### Invariant Format Inconsistency
- **Issue**: P1 uses I1-I5, later patches use P#I# format
- **Status**: OPEN
- **Resolution**: Normalize P1 to P1I1-P1I5 during application

### Lean Skeleton Format Inconsistency
- **Issue**: P1 uses Track A/B, P2 uses Lean A/B, others use Lean 1/2
- **Status**: OPEN
- **Resolution**: Normalize to Lean # format during application

---

## P6 Gaps Added

### Proof Obligations Status Update
| ID | Claim | Status | Notes |
|----|-------|--------|-------|
| P6C1 | Workspace isolation | APPLIED | LTM mutates only by commit events; proof sketch provided |
| P6C2 | Snapshot consistency | APPLIED | MVCC-style readers/writers; proof sketch provided |
| P6C3 | Safe reclamation | APPLIED | RCU grace period style; proof sketch provided |
| P6C4 | Surprise budget prevents calcification | APPLIED | Weight clamp prevents suppression; proof sketch provided |
| P6C5 | Grammar promotion controls error | APPLIED | Beta posterior gating; proof sketch provided |
| P6C6 | Adapter rollout is safe under canary plus rollback | APPLIED | Canary safety pattern; proof sketch provided |

### New Gaps Introduced by P6
| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| GAP-P6.1 | Specific values for provenance threshold P0 and confidence threshold C0 | OPEN | Need empirical calibration |
| GAP-P6.2 | Curriculum stage transition thresholds (E_BOOT, drift_high, conflict_high) | OPEN | Need policy specification |
| GAP-P6.3 | Surprise budget allocation per domain and replenishment policy | OPEN | Need budget model |
| GAP-P6.4 | Cold solve trigger thresholds (θp, θd, θt) | OPEN | Need metric definitions |
| GAP-P6.5 | Connectivity redundancy target (k disjoint bridges) | OPEN | Need co-retrieval analysis |
| GAP-P6.6 | Grammar sandbox canary fraction (f) and promotion thresholds | OPEN | Need error bound analysis |
| GAP-P6.7 | Adapter drift detection sensitivity (ADWIN parameters) | OPEN | Need drift characterization |


### New Gaps Introduced by P4
| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| GAP-P4.1 | Pattern mining candidate generation heuristics not specified | OPEN | Need concrete motif/subgraph mining algorithm |
| GAP-P4.2 | MDL description length encoding scheme not specified | OPEN | Need concrete encoding for patterns, instances, residuals |
| GAP-P4.3 | Failure signature hash function not specified | OPEN | Need concrete context bucketing scheme |
| GAP-P4.4 | Risk score computation not specified | OPEN | Need concrete formula for COMPUTE_RISK |
| GAP-P4.5 | Pattern promotion thresholds (τ, δ, Nmin) not specified | OPEN | Need empirical calibration |
| GAP-P4.6 | Bandit algorithm choice (UCB vs Thompson) not specified | OPEN | Need algorithm selection criteria |

## P6 Gaps and Dragons

### Proof Obligations
| ID | Claim | Status | Notes |
|----|-------|--------|-------|
| P6C1 | Workspace isolation | OPEN | LTM mutates only by commit events |
| P6C2 | Snapshot consistency | OPEN | MVCC-based stable views |
| P6C3 | Safe reclamation | OPEN | RCU grace period based |
| P6C4 | Surprise budget prevents calcification | OPEN | High-prov evidence forces branch/re-anchor |
| P6C5 | Grammar promotion controls error | OPEN | Beta posterior gating |
| P6C6 | Adapter rollout is safe under canary plus rollback | OPEN | Canary deployment safety |

---

---

## P10 Gaps and Proof Obligations

### Proof Obligations
| ID | Claim | Status | Notes |
|----|-------|--------|-------|
| P10C1 | Event-set join convergence | OPEN | Need formal proof of semilattice properties |
| P10C2 | CRDT workspace graph correctness | OPEN | Prove convergence under concurrent edits |
| P10C3 | Idempotent import preserves semantics | OPEN | Prove capsule reimport has no effect |
| P10C4 | Structured concurrency cascade safety | OPEN | Prove parent closure implies child closure |
| P10C5 | Overlap detection accuracy | OPEN | Bound false positive/negative rates |
| P10C6 | Oscillation detection effectiveness | OPEN | Prove signal detects loops with bounded delay |

### New Gaps Introduced by P10
| ID | Description | Status | Resolution |
|----|-------------|--------|------------|
| GAP-P10.1 | Workspace TTL policy and default values | OPEN | Need specification |
| GAP-P10.2 | Capsule size limits and quotas | OPEN | Need memory budget model |
| GAP-P10.3 | Overlap threshold values (tau_overlap, H, etc.) | OPEN | Need empirical calibration |
| GAP-P10.4 | WL hash iteration count (k) | OPEN | Trade-off analysis needed |
| GAP-P10.5 | Workspace tree depth limits | OPEN | Need policy for fork-join depth |
| GAP-P10.6 | Reconciliation decision policy | OPEN | When to import/park/reject |
| GAP-P10.7 | GC grace period for closed workspaces | OPEN | Balance audit vs storage cost |

---

## Undefined Function Gaps

The following 311 functions are called in algorithm pseudocode but lack explicit definitions. Many are trivial helpers or standard library calls, but some require specification.

### Priority Classifications

- **NEEDS_DEFINITION**: Must be specified (complex logic, domain-specific)
- **HAS_MATH_NEEDS_PSEUDO**: Mathematical definition exists but needs pseudocode
- **TRIVIAL_HELPER**: Self-documenting (SET, GET, APPEND, etc.)
- **STANDARD_ALGORITHM**: Well-known algorithm (use standard implementation)
- **EXTERNAL_DEPENDENCY**: External library call (embeddings, ANN, etc.)

---

### PATTERN Functions (13 functions)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| ANN_PATTERN_RETRIEVE | EXTERNAL_DEPENDENCY | Called in Algorithm 11 | ANN index lookup for pattern vectors |
| BASE_PATTERN_SCORE | NEEDS_DEFINITION | Called in Algorithm 14 | Missing scoring formula |
| CANONICALIZE_TO_PATTERN | HAS_MATH_NEEDS_PSEUDO | P4 MDL section | MDL-based pattern canonicalization |
| COMPILE_PATTERN_TO_RULE | NEEDS_DEFINITION | Called in Algorithm 20 | Grammar rule compilation |
| ESTIMATE_PATTERN_CONFIDENCE | HAS_MATH_NEEDS_PSEUDO | P4C3 Beta posterior | Use Beta(α,β) posterior |
| PROMOTE_PATTERN | NEEDS_DEFINITION | Called in Algorithm 13 | Pattern tier promotion logic |
| REMINE_PATTERNS_AND_GRAMMARS | NEEDS_DEFINITION | Called in Algorithm 27 | Sleep-time pattern refresh |
| RENDER_PATTERN_FRAME | NEEDS_DEFINITION | Called in Algorithm 12 | LLM expansion rendering |
| RETRIEVE_PATTERNS_BY_FACTOR_SIMILARITY | NEEDS_DEFINITION | Called in Algorithm 42 | P8 factor-based retrieval |
| RETRIEVE_RELEVANT_NODES_AND_PATTERNS | NEEDS_DEFINITION | Called in Algorithm 12 | Context retrieval for expansion |
| UPDATE_PATTERN_STATS_ON_USE | TRIVIAL_HELPER | Called in Algorithm 11 | Increment usage counters |
| WRITE_PATTERN_INSTANCES | TRIVIAL_HELPER | Called in Algorithm 10 | Persist pattern instances |
| WRITE_PATTERN_LIBRARY | TRIVIAL_HELPER | Called in Algorithm 10 | Persist pattern library |

---

### FIELD Functions (3 functions)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| FIELD_RELAX | HAS_MATH_NEEDS_PSEUDO | P1I2 field equation | Original non-gated relaxation (deprecated by FIELD_RELAX_GATED) |
| RUN_LOCAL_FIELD_REPAIR | NEEDS_DEFINITION | Called 16x | Local repair after delta application |
| SOLVE_CANONICAL_FIELD | HAS_MATH_NEEDS_PSEUDO | P2 IRLS section | Full field solve using IRLS |

---

### EMBED Functions (5 functions)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| CODE_EMBED | EXTERNAL_DEPENDENCY | Called in Algorithm 21 | Code embedding model call |
| EMBED | EXTERNAL_DEPENDENCY | Called 7x | Generic embedding dispatch |
| EMBED_QUERY_BUNDLE | EXTERNAL_DEPENDENCY | Called in Algorithm 22 | Query bundle embedding |
| STRUCT_EMBED | EXTERNAL_DEPENDENCY | Called in Algorithm 21 | Structural embedding |
| TEXT_EMBED | EXTERNAL_DEPENDENCY | Called in Algorithm 21 | Text embedding model call |

---

### GRAPH Functions (10 functions)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| APPLY_SUBGRAPH_WITH_REMAP | NEEDS_DEFINITION | Called in Algorithm 57 | Capsule import with ID remapping |
| BUILD_GRAPH_PAYLOAD | NEEDS_DEFINITION | Called in Algorithm 60 | CRDT graph payload construction |
| BUILD_TOKEN_GRAPH | NEEDS_DEFINITION | Called in Algorithm 18 | Token adjacency graph |
| CANDIDATE_SUBGRAPHS | NEEDS_DEFINITION | GAP-P8.8 | Frequent motif mining |
| EXTRACT_SUBGRAPH | NEEDS_DEFINITION | Called in Algorithm 56 | Capsule export subgraph extraction |
| GRAPH_REWRITE_DPO | STANDARD_ALGORITHM | P5 DPO reference | Double-pushout graph rewriting |
| INTEGRATE_PARSE_GRAPH_AS_HYPOTHESIS | NEEDS_DEFINITION | Called in Algorithm 23 | Parse graph integration |
| LOCAL_SUBGRAPH_MATCH | STANDARD_ALGORITHM | Called in Algorithm 11 | VF2 or similar subgraph isomorphism |
| MINE_CANDIDATE_SUBGRAPHS | NEEDS_DEFINITION | Called in Algorithm 10 | Frequent subgraph mining |
| REBUILD_GRAPH_FROM_EVIDENCE | NEEDS_DEFINITION | Called in Algorithm 27 | Cold rebuild from event log |

---

### PARSE Functions (4 functions)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| INIT_PARSE_FOREST | NEEDS_DEFINITION | Called 8x | Packed forest initialization |
| PARSE_REGION_WITH_P5 | NEEDS_DEFINITION | Called in Algorithm 24 | P5 grammar-based parsing |
| RUN_SHADOW_PARSE | NEEDS_DEFINITION | Called in Algorithm 30 | Shadow grammar testing |
| TRAIN_SPARSE_AUTOENCODER | STANDARD_ALGORITHM | P8 factor learning | Standard sparse autoencoder |

---

### WORKSPACE Functions (4 functions)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| APPLY_REWRITE_IN_WORKSPACE | NEEDS_DEFINITION | Called in Algorithm 43 | Workspace-local graph rewrite |
| CLOSE_WORKSPACE_CASCADE | DEFINED | Algorithm 54 | Already defined |
| OPEN_WORKSPACE | DEFINED | Algorithm 53 | Already defined |
| WORKSPACE_GC | DEFINED | Algorithm 64 | Already defined |

---

### HYPOTHESIS Functions (2 functions)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| NEW_HYPOTHESIS | TRIVIAL_HELPER | Called in Algorithm 8 | Hypothesis ID allocation |
| PROMOTE_AS_HYPOTHESIS | NEEDS_DEFINITION | Called in Algorithm 43 | Idea-to-hypothesis promotion |

---

### INDEX Functions (2 functions)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| FINALIZE_INDEX_DELTAS | NEEDS_DEFINITION | Called in Algorithm 9 | Index delta application |
| UPDATE_INDEX_DELTAS | NEEDS_DEFINITION | Called in Algorithm 66 | Incremental index update |

---

### STATE Functions (5 functions)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| APPEND_STATE_METRICS | TRIVIAL_HELPER | Called in Algorithm 3 | Append to state history |
| NEW_STATE | TRIVIAL_HELPER | Called 5x | State object constructor |
| SET_CURRENT_STATE | TRIVIAL_HELPER | Called in Algorithm 8 | State pointer update |
| STATE | TRIVIAL_HELPER | Called 21x | State accessor |
| WRITE_NODE_STATES | TRIVIAL_HELPER | Called in Algorithm 9 | Persist node states |

---

### High-Priority Undefined Functions (OTHER category - requiring definition)

| Function | Classification | Evidence | Notes |
|----------|----------------|----------|-------|
| COMPUTE_RISK | NEEDS_DEFINITION | GAP-P4.4 | Risk score computation |
| MDL_GAIN | HAS_MATH_NEEDS_PSEUDO | P4 MDL section | Description length reduction |
| MDL_GAIN_WITH_MODULE | NEEDS_DEFINITION | GAP-P8.2 | Module-aware MDL |
| FILTER_BY_MODULE_INTERFACE | NEEDS_DEFINITION | GAP-P8.3 | Module interface checking |
| PARETO_FILTER | STANDARD_ALGORITHM | Called in Algorithm 42 | Multi-objective Pareto frontier |
| SHOULD_CALL_LLM | NEEDS_DEFINITION | GAP-P7.4 | LLM call decision heuristic |
| ISCORE | HAS_MATH_NEEDS_PSEUDO | P7 interestingness | Interestingness score formula |
| SELECT_ACTION_UCB_OR_TS | STANDARD_ALGORITHM | P4.4 bandit | UCB or Thompson sampling |
| HUBER_WEIGHT | HAS_MATH_NEEDS_PSEUDO | P2 IRLS | Huber loss weight function |
| ORTHOGONAL_PROCRUSTES | STANDARD_ALGORITHM | P5 alignment | Standard Procrustes solution |
| ADWIN_DETECT | STANDARD_ALGORITHM | P6 drift | ADWIN change detection |
| MINHASH | STANDARD_ALGORITHM | P10 overlap | MinHash signature |
| SIMHASH | STANDARD_ALGORITHM | P10 overlap | SimHash signature |
| WL_HASH | STANDARD_ALGORITHM | P10 overlap | Weisfeiler-Lehman hash |
| BETA_UPDATE | HAS_MATH_NEEDS_PSEUDO | P4C3 | Beta distribution update |
| OSCILLATION_SIGNAL | NEEDS_DEFINITION | P10C6 | Retract-reinstate cycle detection |

---

### Standard Library Functions (TRIVIAL_HELPER - no definition needed)

The following 150+ functions are standard operations requiring no specification:
- Collection: ADD, PUSH, POP, APPEND, SORT_BY_SCORE, TOPK_BY_SCORE, FILTER, etc.
- Accessors: GET_STATS, FETCH_SPAN, READ_RANGE, LOOKUP, etc.
- Iteration: N (neighbors), NEIGHBORHOOD, OUT_EDGES, etc.
- Math: SUM, NORMALIZE, DECAY, E (energy), etc.
- Control: PROMOTE, DEMOTE, ARCHIVE, REJECT, ROLLBACK, etc.

---

### Summary Statistics

| Category | Count | NEEDS_DEFINITION | HAS_MATH | TRIVIAL | STANDARD | EXTERNAL |
|----------|-------|------------------|----------|---------|----------|----------|
| PATTERN | 13 | 7 | 2 | 3 | 0 | 1 |
| FIELD | 3 | 1 | 2 | 0 | 0 | 0 |
| EMBED | 5 | 0 | 0 | 0 | 0 | 5 |
| GRAPH | 10 | 6 | 0 | 0 | 2 | 0 |
| PARSE | 4 | 3 | 0 | 0 | 1 | 0 |
| WORKSPACE | 4 | 1 | 0 | 0 | 0 | 0 |
| HYPOTHESIS | 2 | 1 | 0 | 1 | 0 | 0 |
| INDEX | 2 | 2 | 0 | 0 | 0 | 0 |
| STATE | 5 | 0 | 0 | 5 | 0 | 0 |
| OTHER | 263 | ~40 | ~15 | ~150 | ~15 | ~10 |
| **TOTAL** | 311 | ~61 | ~19 | ~159 | ~18 | ~16 |

**Actionable gaps**: ~80 functions need explicit pseudocode definitions or mathematical specifications
