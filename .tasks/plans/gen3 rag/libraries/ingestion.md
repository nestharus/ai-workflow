## Algorithm 1: Streaming ingestion [(=Algorithm 1)]

Goal: create evidence nodes, create idea handles, build edges, update tiers, update the field locally.

---

### D58 CurriculumStage [(=D58)]

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

### D61 GrammarRuleCandidate [(=D61)]

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

## P5.1 Graph grammar semantics [(=P5.1)]

Represent the current world as a typed hypergraph (G).

A rule (p) is a rewrite:
[
L \xleftarrow{l} K \xrightarrow{r} R
]
where:

* (L) is the match pattern
* (K) is the interface preserved during rewriting
* (R) is the replacement graph

---

## P5.2 Probabilistic and scored rewriting [(=P5.2)]

Attach a score to each rule application. This can be probability or cost.

Define a derivation score for a hypothesis (h):
[
S(h) = \sum_{\text{rule apps } a \in h} \log P(a) ;-; \lambda \cdot \text{Tension}(h);-;\gamma \cdot \text{Complexity}(h)
]

* (P(a)) from the rule score model
* Tension comes from the field diagnostics inside the hypothesis
* Complexity penalizes overly complex parses

---

## Algorithm 17 [(=Algorithm 17)]

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

## Algorithm 18 [(=Algorithm 18)]

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

## Algorithm 19 [(=Algorithm 19)]

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

### Algorithm 26: Curriculum ingestion controller [(=Algorithm 26)]

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

## P5C3 Packed forest representation preserves derivations [(=P5C3)]

Spec requirement:

* grammar classes used online must satisfy a "uniform parsing budget" policy
* heavy grammars run in sleep-time or under strict scope limits

---

### P6C5 Grammar promotion controls error [(=P6C5)]

**Claim.** Beta posterior gating yields bounded promotion risk under the assumed win/loss observation model.
**Sketch.**

* Same as P4 (+[P4]) promotion proof pattern.

---

## G17 Graphs are the grammar [(=G17)]

* A grammar is a set of typed graph rewrite rules.
* Parsing is graph rewriting plus scoring.

---

## G18 Tokens are graph objects [(=G18)]

* Tokens exist inside a grammar as nodes, hyperedges, subgraphs, and pattern instances.
* Tokens can come from text spans, from graph coordinates, or from both.

---

## G20 Multi-interpretation ingestion [(=G20)]

* Ingestion maintains a parse forest of competing hypotheses.
* Re-ingestion happens by replaying evidence through a different grammar set or a different hypothesis mixture.

---

## G24 Low path dependence [(=G24)]

* Curriculum ingestion and periodic cold solves reduce first-mover geometry lock-in.

---

## G27 Grammar evolution is safe [(=G27)]

* Grammar rules emerge, then sandbox, then promote with measurable error bounds.

---

## D28 Graph token [(=D28)]

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

## D29 Grammar rule as graph rewrite [(=D29)]

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

This matches standard graph transformation and graph grammar formalisms in the DPO family.

---

## D30 Parse hypothesis [(=D30)]

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

## D31 Parse forest [(=D31)]

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


---

## P5 math

---

## Components

### Comp1 Ingestion Stream [(=Comp1)]

Main streaming ingestion pipeline.

---

### Comp11 Modality Router [(=Comp11)]

Routes raw input to appropriate tokenizer based on detected modality.

---

### Comp12 Tokenizer Stack [(=Comp12)]

Domain-specific tokenization engines for text, code, tables, images, etc.

---

### Comp13 Graph Grammar Engine [(=Comp13)]

Applies graph rewrite rules to token graphs to build parse hypotheses.

---

### Comp14 Parse Forest Store [(=Comp14)]

Stores packed parse forests with shared substructure across hypotheses.

---

### Comp15 Grammar Library [(=Comp15)]

Repository of graph rewrite rules organized by domain and version.

---

### Comp16 Grammar Miner and Compiler [(=Comp16)]

Discovers patterns and compiles them into executable grammar rules.

---

### Comp17 Token Type Registry [(=Comp17)]

Central registry of token types with schemas and versioning.

---

### Comp21 Re-ingestion Orchestrator [(=Comp21)]

Manages controlled replay of evidence through new grammars or adapters.

---

### Comp24 Secondary Ingestion Engine (H2) [(=Comp24)]

Hippocampal workspace ingestion engine for hypothesis exploration.

---

### Comp26 Curriculum Manager (CURR) [(=Comp26)]

Controls ingestion parameters based on curriculum stage (bootstrap, expansion, open).

---

### Comp30 Grammar Sandbox + Rule Promotion (GRAM-SBX) [(=Comp30)]

Sandboxes candidate grammar rules, measures performance, promotes based on confidence.

---

---

## Algorithm 23 [(=Algorithm 23)]

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

## C5 Ingestion produces stable idea handles [(=C5)]

Via graph-supported clustering, rather than geometry-only clustering.

---

## T7 Modality routing and tokenizer selection [(=T7)]

## T13 Re-ingestion under reinterpretation [(=T13)]

---

### P1I12 Ingestion hot path [(=P1I12)]

Embed once, add edges, local relax, push conflict candidates. Heavy work runs on the conflict queue.
