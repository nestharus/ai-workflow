# Ingestion Library

Multi-modality routing, tokenization, graph grammar parsing, parse forests.

---

## Algorithm 1: Streaming ingestion

Goal: create evidence nodes, create idea handles, build edges, update tiers, update the field locally.

```pseudo
function INGEST_STREAM(stream):
  for span in STREAM_TO_SPANS(stream):                 // sentence-level or structure markers
    v = NEW_NODE(level=EVIDENCE, span_ref=span.ref)

    v.b = EMBED(span.text)                             // base observation
    v.x = v.b                                          // init field state
    v.u = HIGH
    v.tier = FOCUS
    v.a = INIT_ACTIVATION()

    GRAPH.ADD_NODE(v)

    // structural edges
    ADD_ADJACENCY_EDGES(v)
    ADD_CONTAINMENT_EDGES(v)
    ADD_REFERENCE_EDGES(v, span.text)

    // idea attachment
    candidates = FIND_IDEA_CANDIDATES(v.x)              // ANN over idea nodes in context+inactive
    best = SELECT_OR_CREATE_IDEA(candidates, v)

    GRAPH.ADD_EDGE(v.id, best.id, type=MEMBERSHIP, w=INIT_MEMBERSHIP_WEIGHT(v,best))

    // tier maintenance
    UPDATE_ACTIVATION(v)
    PROMOTE_DEMOTE_TIERS()

    // local field update
    AFFECTED = NEIGHBORHOOD(v, radius=r_tier(v.tier))
    FIELD_RELAX(AFFECTED, steps=s_tier(v.tier))

    UPDATE_INDICES(AFFECTED)
    LOG_EVENT(...)
```

---

### D58 CurriculumStage

```text
CurriculumStage {
  stage_id: enum {bootstrap, expansion, open}
  default_alpha: float
  default_gate: float
  beam_width: int
  validation_budget: int
  grammar_policy: GrammarPolicyRef
  adapter_policy: AdapterPolicyRef
}
```

---

### D61 GrammarRuleCandidate

```text
GrammarRuleCandidate {
  rule_id: RuleId
  source_pattern: PatId?
  domain: DomainId
  version: int
  status: enum {shadow, canary, promoted, rolled_back}
  stats: {precision, conflict_rate, drift_rate}
  posterior: BetaParams
}
```

---

## P5.1 Graph grammar semantics

Represent the current world as a typed hypergraph (G).

A rule (p) is a rewrite:
[
L \xleftarrow{l} K \xrightarrow{r} R
]
where:

* (L) is the match pattern
* (K) is the interface preserved during rewriting
* (R) is the replacement graph

DPO and related algebraic approaches define when a match is valid and how rewriting constructs the new graph via pushouts. ([University of Leicester Computer Science][4])

For language-like parsing on graphs, HRG and related formalisms provide the "context-free grammar for graphs" analogue. ([People CS Umeå][5])

---

## P5.2 Probabilistic and scored rewriting

Attach a score to each rule application. This can be probability or cost.

Probabilistic graph grammars exist with rule probabilities inducing derivation probabilities. ([Springer][6])

Define a derivation score for a hypothesis (h):
[
S(h) = \sum_{\text{rule apps } a \in h} \log P(a) ;-; \lambda \cdot \text{Tension}(h);-;\gamma \cdot \text{Complexity}(h)
]

* (P(a)) from the rule score model
* Tension comes from the field diagnostics inside the hypothesis
* Complexity penalizes overly complex parses

---

### Algorithm 1

Ingestion becomes append-only for state.

Patch `INGEST_STREAM` so `x` updates create `NodeState` records.

```pseudo
function INGEST_STREAM(stream):
  for span in STREAM_TO_SPANS(stream):
    v = NEW_NODE(level=EVIDENCE, span_ref=span.ref)

    b = EMBED(span.text)
    STORE ObservationRecord(node=v.id, b=b, embedder_id, version, input_hash)

    INIT NodeState for each active hypothesis h:
      state = NEW_STATE(node=v.id, hyp=h, x=b, u=HIGH, r=0, T=0)
      v.current_state[h] = state.id

    GRAPH.ADD_NODE(v)
    ADD_EDGES_WITH_BELIEFS(v, span.text)        // creates EdgeBelief with g default values

    ATTACH_TO_IDEAS(v)                          // membership edges become EdgeBelief too

    PROMOTE_DEMOTE_TIERS()

    AFFECTED = NEIGHBORHOOD(v, radius=r_tier(v.tier))
    FIELD_UPDATE_WITH_DIAGNOSTICS(AFFECTED)

    CONFLICT_SCAN_AND_QUEUE(AFFECTED)
    UPDATE_INDICES(AFFECTED)
    LOG_EVENT(...)
```

---

## Algorithm 17

### Modality routing and tokenizer selection

Starts from raw unstructured input.

```pseudo
function ROUTE_AND_TOKENIZE(input stream):
  regions = SEGMENT_STREAM(stream)              // rough boundaries
  for region in regions:
    dom = PREDICT_DOMAIN(region)                // English, code, table, image, logs, mixed
    tokset = TOKENIZER_STACK[dom].TOKENIZE(region)
    yield (region, dom, tokset)
```

Domain routing can be light at first and later refined using hypothesis outcomes.

---

## Algorithm 18

### Incremental graph grammar parsing with hypothesis beam

Grammar is applied to tokens to produce new graph tokens and token graphs.

```pseudo
function PARSE_REGION(region, dom, tokset):
  forest = INIT_PARSE_FOREST(region)

  // seed hypothesis with raw token graph
  h0 = NEW_HYP(region, dom)
  h0.token_graph = BUILD_TOKEN_GRAPH(tokset)          // adjacency edges, containment edges
  PUSH(forest.active_hyps, h0)

  for step in 1..MAX_STEPS:
    next = []
    for h in TOPK_BY_SCORE(forest.active_hyps, BEAM):
      matches = RULE_MATCH_INDEX[dom].CANDIDATE_MATCHES(h.token_graph)

      for m in matches:
        if PASS_FAST_MATCH_CHECK(m):
          h2 = APPLY_RULE(h, m)                       // graph rewrite, emits GraphTokens
          SCORE_UPDATE(h2)                            // rule prob, tension, complexity
          next.append(h2)

    forest = PACK_AND_MERGE(forest, next)             // share subgraphs across hyps
    if STOP_CONDITION(forest): break

  return forest
```

This mirrors the packed-forest idea used to manage ambiguity growth in GLR style parsing. ([IJCAI][2])

---

## Algorithm 19

### Rule application as graph rewrite with provenance

Uses DPO-like rewrite semantics, keeps non-destructive update invariants.

```pseudo
function APPLY_RULE(h, match m):
  rule = m.rule
  g2 = COPY_VIEW(h.token_graph)

  // rewrite in a new graph view, never overwrites the old view
  g2 = GRAPH_REWRITE_DPO(g2, rule, m)                 // produces new graph

  // emit tokens from rhs
  emitted = EMIT_TOKENS(rule.emit, bindings=m.bindings, hyp=h.hyp_id)
  ATTACH_PROVENANCE(emitted, m.support_spans)

  h2 = NEW_HYP_FROM(h)
  h2.token_graph = g2
  h2.bindings += (rule, m.bindings)
  return h2
```

Graph transformation via DPO gives a formal foundation for safe rewrites and composition. ([University of Leicester Computer Science][4])

---

### Algorithm 26: Curriculum ingestion controller

```pseudo
function CURRICULUM_STAGE(epoch e, stats):
  if e < E_BOOT: return bootstrap
  if stats.drift_high or stats.conflict_high: return expansion
  return open

function APPLY_CURRICULUM_PARAMS(stage):
  set default_alpha, gate, beam_width, validation_budget
  set grammar_policy, adapter_policy
```

Curriculum learning is a standard stabilization strategy.

---

## P5C3 Packed forest representation preserves derivations

For the string case, packed forests and graph-structured stacks are standard ways to share substructure and represent ambiguity compactly in GLR style parsing. ([IJCAI][2])
For graph grammars, completeness depends on grammar restrictions and parsing algorithm. HRG parsing has known polynomial-time recognition under restrictions, and general cases can be hard. ([ACL Anthology][10])

Spec requirement:

* grammar classes used online must satisfy a "uniform parsing budget" policy
* heavy grammars run in sleep-time or under strict scope limits

---

### P6C5 Grammar promotion controls error

**Claim.** Beta posterior gating yields bounded promotion risk under the assumed win/loss observation model.
**Sketch.**

* Same as P4 promotion proof pattern.

---

## G17 Graphs are the grammar

* A grammar is a set of typed graph rewrite rules.
* Parsing is graph rewriting plus scoring.

---

## G18 Tokens are graph objects

* Tokens exist inside a grammar as nodes, hyperedges, subgraphs, and pattern instances.
* Tokens can come from text spans, from graph coordinates, or from both.

---

## G20 Multi-interpretation ingestion

* Ingestion maintains a parse forest of competing hypotheses.
* Re-ingestion happens by replaying evidence through a different grammar set or a different hypothesis mixture.

---

## G24 Low path dependence

* Curriculum ingestion and periodic cold solves reduce first-mover geometry lock-in.

---

## G27 Grammar evolution is safe

* Grammar rules emerge, then sandbox, then promote with measurable error bounds.

---

## D28 Graph token

A token that exists in a grammar, not necessarily in text.

```text
GraphToken {
  tok_id: TokId
  tok_type: TokTypeId                 // word, sentence, ASTNode, Function, Subsystem, Pattern, Idea, Hypothesis, ...
  provenance: list<SpanRef>           // can be empty when tok is purely structural
  anchor_nodes: list<NodeId>          // links into evidence graph
  graph_coords: GraphCoordRef         // pointers to subgraph or match bindings
  hyp_id: HypId
  tier: Tier
  created_t: Time
}
```

---

## D29 Grammar rule as graph rewrite

Use an algebraic graph transformation style rule object.

```text
Rule {
  rule_id: RuleId
  domain: DomainId                    // English, Python, Logs, Images, Mixed, ...
  lhs: PatternGraph                   // match graph
  interface: PatternGraph             // glue graph
  rhs: PatternGraph                   // output graph
  emit: EmitSpec                      // token types to create, edges to add
  score: RuleScoreModel               // probability, cost, priors
  conf: float                         // learned or curated confidence
  version: int
}
```

This matches standard graph transformation and graph grammar formalisms in the DPO family. ([ACM Digital Library][1])

---

## D30 Parse hypothesis

A single interpretation state, contains a token graph plus mappings back to evidence.

```text
ParseHypothesis {
  hyp_id: HypId
  domain: DomainId
  input_region: RegionRef
  token_graph: GraphViewRef
  bindings: list<Binding>             // rule matches and slot bindings
  score: float
  uncertainty: float
  parent: HypId?
}
```

---

## D31 Parse forest

Packed storage of many hypotheses sharing substructure.

```text
ParseForest {
  region: RegionRef
  packed_dag: DAGRef                  // shared subgraphs across hypotheses
  active_hyps: list<HypId>
  best_hyps: list<HypId>
}
```

This mirrors packed forest and graph-structured stack ideas used to control ambiguity blow-up in GLR style parsing. ([IJCAI][2])

---

## Incremental graph grammar parsing with hypothesis beam

Grammar is applied to tokens to produce new graph tokens and token graphs.

```pseudo
function PARSE_REGION(region, dom, tokset):
  forest = INIT_PARSE_FOREST(region)

  // seed hypothesis with raw token graph
  h0 = NEW_HYP(region, dom)
  h0.token_graph = BUILD_TOKEN_GRAPH(tokset)          // adjacency edges, containment edges
  PUSH(forest.active_hyps, h0)

  for step in 1..MAX_STEPS:
    next = []
    for h in TOPK_BY_SCORE(forest.active_hyps, BEAM):
      matches = RULE_MATCH_INDEX[dom].CANDIDATE_MATCHES(h.token_graph)

      for m in matches:
        if PASS_FAST_MATCH_CHECK(m):
          h2 = APPLY_RULE(h, m)                       // graph rewrite, emits GraphTokens
          SCORE_UPDATE(h2)                            // rule prob, tension, complexity
          next.append(h2)

    forest = PACK_AND_MERGE(forest, next)             // share subgraphs across hyps
    if STOP_CONDITION(forest): break

  return forest
```

This mirrors the packed-forest idea used to manage ambiguity growth in GLR style parsing. ([IJCAI][2])

---

## Graph token embedding bundle and canonical projection

Every new graph token gets multi-embedder observations plus canonical anchor.

```pseudo
function EMBED_TOKEN(tok):
  obs = []

  if tok.provenance has spans:
    obs.append( TEXT_EMBED(tok.support_text) )

  obs.append( STRUCT_EMBED(tok.graph_coords) )         // WL hashes, graph2vec, GNN, etc.
  if tok.tok_type in CODE_TYPES:
    obs.append( CODE_EMBED(tok.graph_coords) )

  // map each obs into canonical space and combine by confidence
  b_bar = WEIGHTED_CANONICAL_COMBINE(obs, adapters, confidences)

  STORE_OBSERVATIONS(tok, obs)
  STORE_CANONICAL_ANCHOR(tok, b_bar)
```

Graph embeddings and substructure signatures like WL-based features and graph-level embeddings are standard tools. ([Journal of Machine Learning Research][8])
Code embeddings from AST structure exist as well. ([ACM Digital Library][9])

---

## Re-ingestion under reinterpretation

This is the controlled way to replay the same evidence through a new grammar set or new adapters.

```pseudo
function REINTERPRET(epoch e, region R, new_grammar_set G*):
  snap = CREATE_SNAPSHOT(e.snapshot_lsn)
  forest = PARSE_REGION(R, dom=ROUTE(R), tokset=EXTRACT_RAW_TOKENS(R), grammar=G*)
  hyps = SELECT_TOP_HYPOTHESES(forest)

  for h in hyps:
    INTEGRATE_PARSE_GRAPH_AS_HYPOTHESIS(h)             // creates tokens, edges, anchors
    RUN_LOCAL_FIELD_REPAIR(h.scope)

  SCHEDULE_GLOBAL_CONSOLIDATION()
```

Graph parsing for HRG and related grammars is studied, and complexity varies a lot by restrictions, so this is designed with hypothesis beams and domain restrictions. ([ACL Anthology][10])

---

## P5 components

1. **Modality Router**
2. **Tokenizer Stack**
3. **Graph Grammar Engine**
4. **Parse Forest Store**
5. **Grammar Library**
6. **Grammar Miner and Compiler**
7. **Token Type Registry**
8. **Coordinate System Registry**
9. **Adapter and Alignment Trainer**
10. **Traversal Planner**
11. **Re-ingestion Orchestrator**

---

---

## P5 math

---

## Components

### Comp1 Ingestion Stream

Main streaming ingestion pipeline.

---

### Comp11 Modality Router

Routes raw input to appropriate tokenizer based on detected modality.

---

### Comp12 Tokenizer Stack

Domain-specific tokenization engines for text, code, tables, images, etc.

---

### Comp13 Graph Grammar Engine

Applies graph rewrite rules to token graphs to build parse hypotheses.

---

### Comp14 Parse Forest Store

Stores packed parse forests with shared substructure across hypotheses.

---

### Comp15 Grammar Library

Repository of graph rewrite rules organized by domain and version.

---

### Comp16 Grammar Miner and Compiler

Discovers patterns and compiles them into executable grammar rules.

---

### Comp17 Token Type Registry

Central registry of token types with schemas and versioning.

---

### Comp21 Re-ingestion Orchestrator

Manages controlled replay of evidence through new grammars or adapters.

---

### Comp24 Secondary Ingestion Engine (H2)

Hippocampal workspace ingestion engine for hypothesis exploration.

---

### Comp26 Curriculum Manager (CURR)

Controls ingestion parameters based on curriculum stage (bootstrap, expansion, open).

---

### Comp30 Grammar Sandbox + Rule Promotion (GRAM-SBX)

Sandboxes candidate grammar rules, measures performance, promotes based on confidence.

---

---

### D61 GrammarRuleCandidate

```text
GrammarRuleCandidate {
  rule_id: RuleId
  source_pattern: PatId?
  domain: DomainId
  version: int
  status: enum {shadow, canary, promoted, rolled_back}
  stats: {precision, conflict_rate, drift_rate}
  posterior: BetaParams
}
```

---

---

## Algorithm 23

### Re-ingestion under reinterpretation

This is the controlled way to replay the same evidence through a new grammar set or new adapters.

```pseudo
function REINTERPRET(epoch e, region R, new_grammar_set G*):
  snap = CREATE_SNAPSHOT(e.snapshot_lsn)
  forest = PARSE_REGION(R, dom=ROUTE(R), tokset=EXTRACT_RAW_TOKENS(R), grammar=G*)
  hyps = SELECT_TOP_HYPOTHESES(forest)

  for h in hyps:
    INTEGRATE_PARSE_GRAPH_AS_HYPOTHESIS(h)             // creates tokens, edges, anchors
    RUN_LOCAL_FIELD_REPAIR(h.scope)

  SCHEDULE_GLOBAL_CONSOLIDATION()
```

Graph parsing for HRG and related grammars is studied, and complexity varies a lot by restrictions, so this is designed with hypothesis beams and domain restrictions.

### Algorithm 24: Hippocampal workspace session

```pseudo
function HWS_OPEN(region R, base_epoch e):
  hws.base_epoch = e
  hws.overlay_graph = NEW_OVERLAY(e)
  hws.forest = INIT_PARSE_FOREST(R)
  return hws

function HWS_STEP(hws, proposal_or_input X):
  // build workspace tokens and graphs
  forest = PARSE_REGION_WITH_P5(hws, X)
  RUN_LOCAL_FIELD_REPAIR(hws.overlay_graph, forest.active_hyps)
  UPDATE_DIAGNOSTICS(hws)
  return hws

function HWS_CLOSE(hws):
  ARCHIVE(hws)         // TTL based
```

### Algorithm 25: Two-stage commit from neocortex to hippocampus

```pseudo
function HIPPOCAMPUS_2SC(proposal P):
  // Stage 0: admission
  if P.prov_score < P0 and P.confidence < C0:
    return QUARANTINE(P, reason="low provenance")

  // Stage 1: secondary ingestion into HWS
  hws = HWS_OPEN(P.region, P.base_epoch)
  hws = HWS_STEP(hws, P.payload)

  // Stage 2: choose best hypothesis and decision
  h_star = SELECT_BEST_HYP(hws.forest, metrics=hws.diagnostics, risk=P.risk_tags)

  decision = DECIDE_COMMIT_BRANCH_QUAR(h_star, budgets=SURP, curr=CURR.stage)
  record = WRITE_COMMIT_RECORD(P, h_star, decision)

  if decision == committed:
    APPLY_COMMIT_AS_NEW_EPOCH(h_star)     // append events, build indices async
  if decision == branched:
    STORE_BRANCH(h_star)                  // keep both
  if decision == quarantined:
    STORE_QUARANTINED(P, h_star)

  return record
```

This resembles snapshot read plus write-as-new-version discipline.

### Algorithm 26: Curriculum ingestion controller

```pseudo
function CURRICULUM_STAGE(epoch e, stats):
  if e < E_BOOT: return bootstrap
  if stats.drift_high or stats.conflict_high: return expansion
  return open

function APPLY_CURRICULUM_PARAMS(stage):
  set default_alpha, gate, beam_width, validation_budget
  set grammar_policy, adapter_policy
```

Curriculum learning is a standard stabilization strategy.

### Algorithm 27: Cold solve and re-rooting

```pseudo
function SHOULD_COLD_SOLVE(global_metrics M):
  return (M.path_dependence_score > θp) or (M.adapter_drift > θd) or (M.tension > θt)

function GLOBAL_CONSOLIDATION_COLD(epoch e):
  snap = SNAPSHOT_EVIDENCE_LOG(e)                  // raw event log
  REBUILD_GRAPH_FROM_EVIDENCE(snap)                // no warm-start states
  REFIT_ADAPTERS(snap)
  REMINE_PATTERNS_AND_GRAMMARS(snap)
  SOLVE_CANONICAL_FIELD(snap)
  SWAP_IN_NEW_INDICES_AT_EPOCH_BOUNDARY()
```

### Algorithm 28: Surprise budget and provenance override

```pseudo
function HANDLE_DISRUPTIVE_EVIDENCE(hws, evidence e):
  surp = prov(e) * sigmoid(tension_contrib(e))
  if surp < S0: return

  if SURP.budget_remaining(domain(e)) > surp:
    SURP.spend(surp)
    CLAMP_ROBUST_WEIGHTS_FOR(e)          // keep it active in solve
    FORCE_BRANCH_IF_CONFLICT(hws, e)     // preserve both sides
  else:
    QUEUE_FOR_GLOBAL_REVIEW(e)
```

### Algorithm 29: Connectivity guard and bridge repair

```pseudo
function ON_GATE_CHANGE(epoch e, updates U):
  affected = FIND_AFFECTED_CLUSTERS(U)
  for cluster in affected:
    if RISK_OF_DISCONNECT(cluster, e):
      bridges = PROPOSE_BRIDGES(cluster, e)        // embedding + co-retrieval
      VALIDATE_BRIDGES(bridges)                    // inquiry tasks
      ADD_SKIP_CONNECTIONS(accepted_bridges)
```

Small-world connectivity is the target pattern.

### Algorithm 31: Adapter lifecycle and drift management

```pseudo
function ADAPTER_FIT(src_cs, dst_cs, paired_samples):
  cand = FIT_MAP(paired_samples)
  cand.status = shadow
  E0 = EVAL_OFFLINE(cand)

  if E0 > EMAX: return REJECT(cand)

  cand.status = canary
  CANARY_ROUTE(cand, traffic=f)                    // apply to a subset
  if CANARY_METRICS_OK(cand):
    PROMOTE(cand)
  else:
    ROLLBACK(cand)

function ADAPTER_DRIFT_MONITOR(adapter a):
  series = STREAM_ALIGNMENT_ERRORS(a)
  if ADWIN_DETECT(series):                         // change point
    TRIGGER_REFIT(a)
```

ADWIN is a standard drift detector with adaptive windowing.
Canary rollouts are a standard safety practice for changing live systems.

### Algorithm 32: Diagnostics-driven inquiry planning

```pseudo
function PLAN_INQUIRIES(epoch e):
  candidates = FIND_HIGH_VALUE_AMBIGUITIES(e)        // high usage, high tension, high variance
  tasks = []
  for c in candidates:
    gain = EST_EXPECTED_UNCERTAINTY_REDUCTION(c)
    cost = EST_COST(c)
    tasks.append((gain/cost, MAKE_TASK(c)))

  return TOPK(tasks, budget=validation_budget)
```

Active learning literature gives the template for selecting data to reduce uncertainty efficiently.

---

### Algorithm 33: Noise scan

Runs after any of:

* local field update
* grammar parse step
* gating change
* adapter drift event
* repeated branch events

```pseudo
function NSCAN(epoch e, workspace_view W):
  seeds = []

  for v in W.nodes_touched:
    if T(v) > T0: seeds.add(SEED(high_tension, v))
    if r(v) > r0: seeds.add(SEED(high_residual, v))
    if var(v) > v0: seeds.add(SEED(high_variance, v))

  for m in W.grammar_near_misses:
    seeds.add(SEED(grammar_near_miss, m.subgraph_anchor))

  for gap in W.bridge_gaps:
    seeds.add(SEED(bridge_gap, gap.cluster_pair))

  for drift in W.adapter_drift_events:
    seeds.add(SEED(adapter_drift, drift.adapter_id))

  WRITE_SEEDS_APPEND_ONLY(seeds)
  return seeds
```

**P4C2 proof sketch: MDL-driven abstraction reduces description length**

**Claim.** Given a candidate pattern set, choosing patterns by MDL yields shorter descriptions than raw graph encoding (for those patterns). (Algorithm is heuristic; objective is principled.)

**Sketch.** The objective directly minimizes description length. Greedy selection may not find global optimum but provides local improvement guarantees standard in submodular-style optimization.

**P4C3 proof sketch: Promotion guarantee**

**Claim.** If a pattern is promoted only when (\Pr(\theta_p \ge \tau) \ge 1-\delta), then promotion implies a posterior reliability guarantee.

**Sketch.** Direct from the posterior CDF of the Beta distribution.

**P4C5 proof sketch: Risk governance calibration**

**Claim.** Conformal prediction can convert heuristic uncertainty into prediction sets with distribution-free coverage, and selective conformal risk control combines deferral with risk control.

**Sketch.** Conformal coverage guarantee is standard; selection layer trades coverage vs abstention.

### Algorithm 34: Thread queue update

```pseudo
function UPDATE_THREAD_QUEUE(new_seeds):
  for s in new_seeds:
    s.metrics.novelty = NOVELTY(s)
    s.metrics.recurry = RECURRENCE(s)
    s.prov_score = PROVENANCE(s)
    score = ISCORE(s)

    if score > TH_QUEUE:
      TQ.push(s, priority=score)
    else:
      s.status = parked
```

### Algorithm 35: Explore a seed

Two-stage: cheap structure first, then LLM refinement when value exists.

```pseudo
function EXPLORE_SEED(seed s):
  if CBUD.llm_remaining(domain(s)) <= 0 and CBUD.explore_remaining(domain(s)) <= 0:
    s.status = parked
    return

  bundle = EBC_COMPILE(s, budget_tokens=K)

  // Stage A: structural probes
  probes = RUN_STRUCTURAL_PROBES(bundle)
  if probes.outcome == "resolved":
    trace = WRITE_TRACE(s, probes)
    return

  // Stage B: LLM refine
  if SHOULD_CALL_LLM(s, bundle):
    proposal = LLMR_PROPOSE(bundle)            // actions + rationale + confidence
    APPLY_PROPOSAL_AS_HYPOTHESES(proposal)     // workspace overlay only
    CBUD.spend_llm(domain(s), cost_llm(proposal))

  // Stage C: validate and measure learning progress
  RUN_LOCAL_FIELD_REPAIR(bundle.scope)
  after = MEASURE_METRICS(s)

  trace = WRITE_TRACE(s, before_metrics, after, proposals)
  UPDATE_LEARNING_PROGRESS(s, trace)
  UPDATE_FAILURE_MEMORY(s, trace)
```

LLM-driven curiosity and intrinsic reward signals for LLM training and auditing exist in recent work, so "LLM used as refiner" fits the current research direction.

### Algorithm 36: Distill traces into tokens

```pseudo
function DISTILL(epoch e):
  traces = FETCH_RECENT_TRACES(e)
  clusters = CLUSTER_TRACES_BY_SIGNATURE(traces)

  for c in clusters:
    if RECURRENCE_HIGH(c) and LP_HIGH(c):
      idea = MAKE_IDEA_TOKEN(c)
      PROMOTE_IDEA(idea)                      // IdeaToken, PatternCandidate, BridgeCandidate, RuleCandidate
    else if FAILURE_HIGH(c):
      QUARANTINE_SIGNATURE(c.signature)
```

Learning progress guided exploration and goal selection is a standard curiosity mechanism in intrinsic motivation systems.

### Algorithm 37: Curiosity scheduler

Online plus sleep-time pass.

```pseudo
function CURIOSITY_SCHEDULER():
  while CBUD.explore_remaining > 0:
    s = TQ.pop()
    if s == none: break
    EXPLORE_SEED(s)

function SLEEP_CURIOSITY_PASS(snapshot snap):
  // deeper budgets, heavier probes
  for s in TOPN_SEEDS(snap, Nsleep):
    EXPLORE_SEED(s)
  DISTILL(snap.epoch)
```

### Algorithm 38: Decay and cleanup

```pseudo
function SEED_DECAY(seed s):
  if STALE(s) and RECURRENCE_LOW(s):
    s.status = archived
  if FAILURE_HIGH(s) and LP_LOW(s):
    s.status = quarantined
```

### P10I10 Memory layer operations

The memory layer must support the following operations. A coordination system may call them, but P10 does not define the policy for when.

* WS_OPEN(agent_id, base_epoch, base_lsn_end, ttl) -> ws_id
* WS_CLOSE(ws_id, reason)
* WS_SPAWN_CHILD(parent_ws_id, ttl, seed_capsules[]) -> child_ws_id
* WS_EXPORT(parent_ws_id, selection_spec) -> capsule
* WS_IMPORT(ws_id, capsule) -> import_record
* WS_SEND(from_ws, to_ws, capsule, note)
* WS_QUERY(ws_id, query_spec) -> results
* WS_VIEW(ws_id, viewport_spec) -> prompt_pack
* WS_COMMIT(ws_id, exported_capsules, intent) -> commit_envelope

### Algorithm 53: OPEN_WORKSPACE

```pseudo
OPEN_WORKSPACE(agent_id, base_epoch, base_lsn_end, ttl):
  ws = new Workspace
  ws.base_epoch = base_epoch
  ws.base_lsn_end = base_lsn_end
  ws.status = open
  ws.ttl = ttl
  ws.event_log = empty
  return ws
```

### Algorithm 54: CLOSE_WORKSPACE_CASCADE (structured lifetime)

```pseudo
CLOSE_WORKSPACE_CASCADE(ws_id):
  if ws.status != open: return
  ws.status = closing
  for child in ws.children:
    CLOSE_WORKSPACE_CASCADE(child)
  ws.status = closed
  WGC.schedule(ws_id)
```

### Algorithm 55: SPAWN_CHILD (fork-join)

```pseudo
SPAWN_CHILD(parent_ws, ttl, seed_capsules):
  child = OPEN_WORKSPACE(agent_id = parent.agent_id,
                         base_epoch = parent.base_epoch,
                         base_lsn_end = parent.base_lsn_end,
                         ttl = ttl)
  child.parent_ws = parent.ws_id
  parent.children.add(child.ws_id)

  for cap in seed_capsules:
    WS_IMPORT(child.ws_id, cap)

  log event create_child
  return child.ws_id
```

### Algorithm 56: EXPORT_CAPSULE

```pseudo
EXPORT_CAPSULE(ws_id, selection_spec):
  subgraph = EXTRACT_SUBGRAPH(ws_id, selection_spec)
  fp = OVERLAP_SIGNATURE(subgraph)
  cap = Capsule(subgraph, manifest, fp)
  cap.hop_trace = [ws_id]
  log event export_capsule
  return cap
```

### Algorithm 57: IMPORT_CAPSULE (idempotent)

```pseudo
IMPORT_CAPSULE(ws_id, cap):
  // loop guard
  if ws_id in cap.hop_trace: reject

  // idempotence
  if cap.capsule_id in ws.import_registry: return existing_record

  // remap IDs to avoid collision
  mapping = BUILD_ID_REMAP(ws_id, cap.manifest)
  APPLY_SUBGRAPH_WITH_REMAP(ws_id, cap.subgraph, mapping)

  // record lineage
  ws.import_registry.add(cap.capsule_id)
  log event import_capsule

  // update overlap index
  OVI.add(ws_id, cap.fingerprint)

  return import_record
```

### Algorithm 58: MESSAGE_SEND

```pseudo
MESSAGE_SEND(from_ws, to_ws, cap, note):
  cap.hop_trace.append(to_ws)
  msg = WorkspaceMessage(from_ws, to_ws, cap, note)
  MSG.deliver(msg)
```

### Algorithm 59: RECONCILE_CHILD_TO_PARENT

```pseudo
RECONCILE_CHILD_TO_PARENT(parent_ws, child_ws, selection_spec):
  cap = EXPORT_CAPSULE(child_ws, selection_spec)
  overlap = OVERLAP_QUERY(parent_ws, cap.fingerprint)

  // RECON does not decide policy; it only computes signals.
  rec = ReconcileRecord(parent_ws, child_ws, cap.capsule_id, overlap)
  return rec, cap
```

### Algorithm 60: COMMIT_TO_INGEST (no LLM diffs)

```pseudo
COMMIT_TO_INGEST(ws_id, exported_capsules, intent):
  payload = BUILD_GRAPH_PAYLOAD(ws_id, exported_capsules)
  env = WorkspaceCommitEnvelope(ws_id, payload, base_epoch, base_lsn_end)
  CGW.submit_to_ingest(env)
  return env
```

### Algorithm 61: OVERLAP_SIGNATURE (structure + content)

```pseudo
OVERLAP_SIGNATURE(subgraph):
  wl_hash  = WL_HASH(subgraph, iterations = k)
  shingle_set = SHINGLES(subgraph)                // labels, edge types, local WL labels
  minhash = MINHASH(shingle_set)
  simhash = SIMHASH(EMBED(shingle_set))
  return {wl_hash, minhash, simhash}
```

### Algorithm 62: OVERLAP_DETECT

```pseudo
OVERLAP_DETECT(fingerprint_a, fingerprint_b):
  // fast filters
  if HAMMING(simhash_a, simhash_b) > H: return low_overlap

  // approximate set similarity
  j_hat = MINHASH_ESTIMATE(minhash_a, minhash_b)
  return j_hat
```

### Algorithm 63: OSCILLATION_SIGNAL

```pseudo
OSCILLATION_SIGNAL(ws_id, window):
  // Detect repeated edits with high overlap and low net progress.
  // This is a signal for an external coordinator, not an automatic stop.

  recent_exports = exports_in_window(ws_id, window)
  if count(recent_exports) < N: return none

  overlaps = pairwise_overlap(recent_exports)
  if median(overlaps) > tau_overlap and net_progress(ws_id, window) < eps:
    return signal("oscillation_suspected")
```

### Algorithm 64: WORKSPACE_GC

```pseudo
WORKSPACE_GC(ws_id):
  // Only for closed workspaces or expired TTL.
  // Preserve audit log pointers, remove bulk graph payload.
  compact event log; drop scratch-only regions; keep exported capsules and commit envelopes.
```

### Algorithm 39: Factor learning in sleep

```pseudo
function LEARN_FACTORS(epoch e):
  X = SAMPLE_CANONICAL_VECTORS(e)              // token canonical x_i
  (D, Enc) = TRAIN_SPARSE_AUTOENCODER(X)       // x ≈ D a, a sparse
  STORE_FACTOR_DICT(D, Enc, version=e)
```

Basis: sparse coding style factorization.

### Algorithm 40: Module mining from pattern graphs

```pseudo
function MINE_MODULES(patterns P):
  C = CANDIDATE_SUBGRAPHS(P)                   // frequent motifs + stable interfaces
  M = {}
  for cand in C:
    gain = MDL_GAIN_WITH_MODULE(cand)
    if gain > 0:
      M.add(cand)
  PROMOTE_TOP_MODULES(M)
  return M
```

### Algorithm 41: Build pattern functionality profiles

```pseudo
function BUILD_PROFILES(pattern_instances I, Enc):
  for inst in I:
    a = Enc( CANONICAL_VECTOR(inst.macro_node) )
    UPDATE_FACTOR_PROFILE(inst.pattern_id, a)
    UPDATE_CONTEXT_PROFILE(inst.pattern_id, inst.neighborhood_types)
    UPDATE_EFFECT_PROFILE(inst.pattern_id, DELTA_ENERGY(inst))
```

### Algorithm 42: Idea proposal via substitution and hybridization

```pseudo
function PROPOSE_IDEAS(context subgraph G, Enc):
  need = AGGREGATE_FACTORS(Enc, nodes_in(G))
  candidates = RETRIEVE_PATTERNS_BY_FACTOR_SIMILARITY(need)

  // filter by interface compatibility
  candidates = FILTER_BY_MODULE_INTERFACE(candidates, G)

  // tradeoff selection
  candidates = PARETO_FILTER(candidates, metrics={stability,cost,robustness})

  hybrids = GENERATE_HYBRIDS(candidates)       // module splice + connector search
  return TOPK(candidates ∪ hybrids)
```

### Algorithm 43: Simulate and validate an idea candidate

```pseudo
function EVALUATE_IDEA(candidate c):
  hws = HWS_OPEN(region=c.region, base_epoch=c.epoch)
  APPLY_REWRITE_IN_WORKSPACE(hws, c.rewrite)
  RUN_LOCAL_FIELD_REPAIR(hws)
  delta = MEASURE_DELTA(hws, baseline)

  if delta.good:
    bundle = COMPILE_EVIDENCE_BUNDLE(c, hws)
    llm = LLM_REFINE(bundle)                   // label + missing evidence
    STORE_IDEA_TOKEN(c, delta, llm)
    return PROMOTE_AS_HYPOTHESIS(c)
  else:
    RECORD_FAILURE(c)
```

---

---

## C5 Ingestion produces stable idea handles

Via graph-supported clustering, rather than geometry-only clustering.

---
