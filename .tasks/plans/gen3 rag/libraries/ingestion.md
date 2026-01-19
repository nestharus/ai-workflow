## Algorithm 1: Streaming ingestion [(=Algorithm 1)]

Goal: create evidence nodes, create idea handles, build edges, update tiers, update the field locally.

Ingestion becomes append-only for state. `x` updates create `NodeState` records.

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

DPO and related algebraic approaches define when a match is valid and how rewriting constructs the new graph via pushouts.

For language-like parsing on graphs, HRG and related formalisms provide the “context-free grammar for graphs” analogue.

## P5.2 Probabilistic and scored rewriting [(=P5.2)]

Attach a score to each rule application. This can be probability or cost.

Probabilistic graph grammars exist with rule probabilities inducing derivation probabilities.

Define a derivation score for a hypothesis (h):
[
S(h) = \sum_{\text{rule apps } a \in h} \log P(a) ;-; \lambda \cdot \text{Tension}(h);-;\gamma \cdot \text{Complexity}(h)
]

* (P(a)) from the rule score model
* Tension comes from the field diagnostics inside the hypothesis
* Complexity penalizes overly complex parses

## Algorithm 17 [(=Algorithm 17)]

## Algorithm 18 [(=Algorithm 18)]

## Algorithm 19 [(=Algorithm 19)]

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

## P5C3 Packed forest representation preserves derivations [(=P5C3)]

For the string case, packed forests and graph-structured stacks are standard ways to share substructure and represent ambiguity compactly in GLR style parsing.
For graph grammars, completeness depends on grammar restrictions and parsing algorithm. HRG parsing has known polynomial-time recognition under restrictions, and general cases can be hard.

Spec requirement:

* grammar classes used online must satisfy a “uniform parsing budget” policy
* heavy grammars run in sleep-time or under strict scope limits

### P6C5 Grammar promotion controls error [(=P6C5)]

**Claim.** Beta posterior gating yields bounded promotion risk under the assumed win/loss observation model.
**Sketch.**

* Same as P4 promotion proof pattern.

## G17 Graphs are the grammar [(=G17)]

* A grammar is a set of typed graph rewrite rules.
* Parsing is graph rewriting plus scoring.

## G18 Tokens are graph objects [(=G18)]

* Tokens exist inside a grammar as nodes, hyperedges, subgraphs, and pattern instances.
* Tokens can come from text spans, from graph coordinates, or from both.

## G20 Multi-interpretation ingestion [(=G20)]

* Ingestion maintains a parse forest of competing hypotheses.
* Re-ingestion happens by replaying evidence through a different grammar set or a different hypothesis mixture.

## G24 Low path dependence [(=G24)]

* Curriculum ingestion and periodic cold solves reduce first-mover geometry lock-in.

## G27 Grammar evolution is safe [(=G27)]

* Grammar rules emerge, then sandbox, then promote with measurable error bounds.

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

This mirrors packed forest and graph-structured stack ideas used to control ambiguity blow-up in GLR style parsing.

## Algorithm 23 [(=Algorithm 23)]

## C5 Ingestion produces stable idea handles [(=C5)]

Via graph-supported clustering, rather than geometry-only clustering.

### P1I12 Ingestion hot path [(=P1I12)]

Embed once, add edges, local relax, push conflict candidates. Heavy work runs on the conflict queue.

## P5C4 Orthogonal adapter preserves geometry [(=P5C4)]

If (A_v) is orthogonal, then (|A_v x - A_v y| = |x-y|). This gives stable similarity across mapped spaces. Procrustes-based alignment provides a practical way to fit such maps.

Lean target:

* prove distance preservation for orthogonal matrices
* prove the Procrustes minimizer exists under standard assumptions, optional


### P5I1 Parse forest versioning [(=P5I1)]

Parse forests are versioned by epoch. Old hypotheses compact via P2 (+[P2]) sleep cycle, with provenance and failures retained.

---



### P5I2 Strict beam width [(=P5I2)]

Strict beam width per region. Packed DAG sharing across hypotheses, similar in spirit to graph-structured stacks for ambiguity.


### P5I3 Grammar class restrictions per tier [(=P5I3)]

Focus and Active: restricted grammars with cheap matching and bounded-degree neighborhoods. Context and Sleep: heavier grammars and deeper matching. Graph grammar parsing complexity varies widely across grammar classes and restrictions.


### P5I4 Match candidate indexing [(=P5I4)]

Index rule LHS patterns by WL-style neighborhood signatures. Use WL hashing to prune match candidates before subgraph matching.


### P5I5 Coordinate transforms cached [(=P5I5)]

Cache canonical projections (A_v b_i^{(v)}). Refit adapters in sleep-time, then bulk-refresh projections during consolidation.


### P5I6 Domain embedders specialized [(=P5I6)]

Text embedder stays as the semantic anchor. Graph embedder covers topology. Code embedder covers AST and code structure.

