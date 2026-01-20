## G39 Dragon closure ([=G39])

* Every open gap becomes either:
  * an implemented method,
  * an explicit bypass rule, or
  * a deliberate non-goal with an alternative.

### P1C6: Evidence permanence proof sketch ([=P1C6]) (@[+P1C1])

By construction:

* all raw spans remain in the raw store referenced by `SpanRef`
* each node creation writes an `ObservationRecord`
* each derived update appends to event log
* node states append to `NodeState` history
* merges and splits create alias edges and lineage pointers

Therefore any current state and any prior state is reconstructible from the append-only log plus raw store.

### P1C7: Unique field minimizer and convergence proof sketch ([=P1C7]) (@[+P1C2]) (@[+P1C3])

For a fixed hypothesis (h), gated quadratic energy remains strictly convex when (\alpha_i + \mu_i > 0) per connected component.
The matrix (Q = L_g + A + M) stays SPD.
Coordinate descent decreases energy and converges to the unique minimizer.

This is the same style of argument used for harmonic energy minimization on graphs.

### P1C8: Persistent conflict durability proof sketch ([=P1C8]) (@[+P1C4])

Conflict scores derive from residual and tension.
If tension remains above threshold after validator updates and local relaxation, the policy triggers branching.
Since branching is append-only and the conflict record persists, ambiguity becomes durable.

### T1 Structural disentanglement ([=T1])

Take complex patterns and decompose them into smaller reusable modules with typed interfaces.

* Pattern = a graph template or a grammar rewrite rule (P4/P5)
* Module = a subpattern used across many patterns, with a stable boundary
* Boundary = the slots and edge-types that connect module to the rest

Goal: represent a pattern as "modules + wiring" rather than a monolith.


### T10 Grammar emergence from patterns ([=T10])

See Algorithm 20 (@[+Algorithm 20]).

### T11 Graph token embedding bundle and canonical projection ([=T11])

See Algorithm 21 (@[+Algorithm 21]).

### T12 Traversal across coordinate systems ([=T12])

See Algorithm 22 (@[+Algorithm 22]).

### T13 Re-ingestion under reinterpretation ([=T13])

See Algorithm 23 (@[+Algorithm 23]).

#### T14 Notes on BUILD_INDICES ([=T14])

This is a versioned build, then swap. The Lucene style segment approach is a practical reference point for "build new segments, then open them" behavior.


### T2 Direction disentanglement ([=T2])

Represent canonical vectors as sparse combinations of basis directions.

* Token canonical vector (x \in \mathbb{R}^{d_C})
* Factor dictionary (D \in \mathbb{R}^{d_C \times K})
* Sparse coefficients (a \in \mathbb{R}^K)

Goal: replace "one entangled vector" with "few active factors."

This is the same family of ideas as sparse coding and dictionary learning. A major warning: fully unsupervised disentanglement has identifiability limits. It needs inductive bias and constraints. Your system already has strong biases: typed edges, slot schemas, hypotheses, provenance, and outcome feedback. That is exactly how you escape the "disentanglement is impossible" regime.


### T3 Module extraction idea ([=T3])

Given a corpus of pattern graphs, find subgraphs that:

* recur across patterns
* have stable boundaries (interfaces)
* reduce description length when added as reusable primitives

This is structurally the same principle as your MDL compression work in P4, just one level deeper. It turns patterns into an algebra of parts.

Result:

* Pattern = DAG of modules + wiring constraints
* Module = token type in the grammar

This gives "components" that can be moved between contexts.


#### T4 Confidence-weighted MDL ([=T4])

Add a penalty for low-confidence patterns:
[
L'(G,\mathcal{P},\mathcal{I}) = L(G,\mathcal{P},\mathcal{I}) + \sum_{p\in\mathcal{P}} \lambda \cdot \phi(\text{conf}(p))
]
where (\phi) decreases as confidence increases (example: (\phi(c)= -\log(c+\epsilon))).

This aligns with "abstract with confidence".


### T5 Orthogonal Procrustes map ([=T5])

For paired vectors ((u_k, v_k)) in two spaces, find an orthogonal matrix (R) minimizing:
[
\min_{R^\top R = I} |UR - V|_F


### T6 General multi-view alignment ([=T6])

Use alignment and fusion approaches from multi-view representation learning when orthogonal mapping feels too rigid.


### T7 Modality routing and tokenizer selection ([=T7])

See Algorithm 17 (@[+Algorithm 17]).

### T8 Incremental graph grammar parsing with hypothesis beam ([=T8])

See Algorithm 18 (@[+Algorithm 18]).

### T9 Rule application as graph rewrite with provenance ([=T9])

See Algorithm 19 (@[+Algorithm 19]).
