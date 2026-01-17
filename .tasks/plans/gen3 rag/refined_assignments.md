# Refined Library Assignments

This document refines the primary library assignment for elements that appear in 4+ libraries across different contexts (e.g., P1, P10 versions).

## Algorithm 2 (combined P1 + P10)
- **primary**: field
- **related**: foundation, storage, graph, exploration, patterns, embedding, uncertainty
- **reason**: Both versions focus on field computation. P1 version does field updates with diagnostics and gating. P10 version (Idea candidate selection) seeds field state from evidence. The core operation in both is field state management, with other libraries providing input/output context.

## Algorithm 1 (combined P1 + P10)
- **primary**: ingestion
- **related**: foundation, storage, graph, field, embedding
- **reason**: Both P1 and P10 versions are fundamentally about ingestion - converting input streams/spans into graph nodes with embeddings. P1 makes it append-only (storage concern), P10 defines the streaming flow. The core purpose is to ingest data, with field/embedding/graph as downstream operations.

## EdgeBelief
- **primary**: graph
- **related**: foundation, storage, field, uncertainty
- **reason**: EdgeBelief is fundamentally a graph edge structure with metadata (beliefs, weights, gates, robust weights). It defines HOW edges work in this system. Other libraries consume it: field uses edge weights for relaxation, uncertainty tracks belief confidence, storage persists it, foundation defines its lifecycle.

## NoiseSeed
- **primary**: exploration
- **related**: foundation, uncertainty, storage, graph
- **reason**: NoiseSeed is the exploration queue - it identifies anomalies/tensions/gaps that trigger further investigation. Created by Algorithm 33 (noise scan), it drives the exploration budget. Uncertainty provides detection metrics, storage persists the queue, graph provides coordinates, but exploration is the core purpose.

## Algorithm 3 (combined P1 + P10)
- **primary**: field
- **related**: foundation, storage, graph, uncertainty
- **reason**: P1 version scans for conflicts (high tension/residual in field state). P10 version does Gauss-Seidel field relaxation. Both are field operations - one detects field anomalies, one updates field values. Graph provides topology, uncertainty flags problems, but field computation is central.

## Algorithm 4 (combined P1 + P10)
- **primary**: uncertainty
- **related**: foundation, storage, graph, field
- **reason**: P1 version resolves conflicts by validating edges and updating beliefs. P10 version manages tier promotion/demotion. Both manage uncertainty - P1 explicitly resolves ambiguity, P10 manages activation uncertainty (what's in focus vs context). Field/graph provide context, storage persists decisions, but uncertainty management is the core.

## Algorithm 5 (combined P1 + P10)
- **primary**: patterns
- **related**: foundation, storage, graph, field
- **reason**: P1 version branches hypotheses to preserve ambiguity. P10 version detects boundaries without fixed chunking (BOCPD). Both identify patterns - P1 finds divergence patterns requiring multiple hypotheses, P10 finds structural boundary patterns. Foundation defines how patterns are stored, but pattern detection/creation is central.

## Algorithm 25
- **primary**: workspace
- **related**: storage, foundation, uncertainty, field
- **reason**: Two-stage commit from neocortex to hippocampus. This is workspace coordination - managing how proposals from the main workspace (neocortex) are vetted and committed to stable storage (hippocampus). Storage is the destination, uncertainty drives admission decisions, field provides context, but workspace orchestration is the core purpose.

## Algorithm 33
- **primary**: exploration
- **related**: uncertainty, field, graph, storage
- **reason**: Noise scan that creates NoiseSeed records. This is the exploration trigger - it identifies where to explore next based on field tensions, grammar misses, bridge gaps, adapter drift. It populates the exploration queue. Uncertainty provides detection thresholds, field/graph provide metrics, storage persists seeds, but exploration planning is the core.

## NodeState
- **primary**: field
- **related**: foundation, graph, storage
- **reason**: NodeState stores field state over time and across hypotheses. It's fundamentally a field state snapshot - tracking the field vector (x) and uncertainty (u) at a node. Graph provides the node context, storage persists it, foundation defines lifecycle, but the core purpose is to capture field state evolution.

## ConflictRecord
- **primary**: uncertainty
- **related**: foundation, graph, storage
- **reason**: ConflictRecord is an explicit ambiguity store that tracks conflicts detected via field tensions/residuals. This is uncertainty management - recording where the system detected irresolvable ambiguity requiring branching. Graph/field provide the conflict location and metrics, storage persists it, but tracking and managing uncertainty is the core purpose.

## PatternInstance
- **primary**: patterns
- **related**: foundation, graph, storage
- **reason**: PatternInstance binds a pattern to a concrete part of the evidence graph via lossless mapping. This is pattern instantiation - the core operation of the patterns library. Graph provides the concrete nodes/edges, storage persists instances, foundation defines lifecycle, but pattern binding is the primary function.

## FailureCase
- **primary**: patterns
- **related**: foundation, storage, uncertainty
- **reason**: FailureCase is explicit bad memory storing pattern failures with signatures and context features. This is pattern learning - tracking which patterns failed in which contexts to avoid repetition (Algorithm 14). Uncertainty provides severity scores, storage persists failures, but pattern anti-learning is the core purpose.

## AmbiguityLedgerEntry
- **primary**: uncertainty
- **related**: foundation, graph, storage
- **reason**: AmbiguityLedgerEntry tracks ambiguity with metrics (residual, tension, variance) and risk scores. This is the uncertainty ledger - explicitly cataloging unresolved ambiguities. Graph provides coordinates, storage persists entries, foundation defines lifecycle, but uncertainty quantification and tracking is the primary function.

## ExplorationTrace
- **primary**: exploration
- **related**: foundation, storage, uncertainty
- **reason**: ExplorationTrace records exploration actions (walk, expand, branch, validate, propose) with before/after metrics and evidence used. This is exploration provenance - tracking what the exploration budget was spent on. Uncertainty provides metrics, storage persists traces, but exploration accountability is the core purpose.

## EvidenceBundle
- **primary**: exploration
- **related**: foundation, graph, patterns
- **reason**: EvidenceBundle packages neighborhood context for exploration - nodes/edges by tension, competing hypotheses, support spans, near-miss patterns, candidate bridges. This is exploration input - assembling relevant context for an exploration episode. Graph provides structure, patterns provide candidates, but exploration context assembly is the primary function.

## WorkspaceGraph
- **primary**: workspace
- **related**: foundation, graph, storage
- **reason**: WorkspaceGraph is the mutable workspace graph with nodes, edges, and tombstones. This is workspace state - the volatile working memory where experiments happen before commitment. Graph defines structure, storage provides persistence pattern, foundation defines lifecycle, but workspace isolation is the core purpose.

## Capsule
- **primary**: workspace
- **related**: foundation, graph, storage
- **reason**: Capsule is a portable subgraph export with manifest, fingerprint, and hop trace. This is workspace mobility - packaging workspace artifacts for transfer between workspaces (Algorithms 56-57). Graph provides content, storage provides format, foundation defines lifecycle, but workspace portability is the primary function.

## WorkspaceCommitEnvelope
- **primary**: workspace
- **related**: foundation, storage, uncertainty
- **reason**: WorkspaceCommitEnvelope packages workspace artifacts for commit to ingest with provenance and confidence. This is workspace graduation - how volatile workspace state transitions to stable storage (Algorithm 60). Storage is destination, uncertainty drives admission, but workspace lifecycle management is the core purpose.

## TranslationProposal
- **primary**: field
- **related**: deployment, foundation, uncertainty
- **reason**: TranslationProposal proposes bridges/rules/patterns/adapters based on manifold view with gain/risk deltas. This is field-to-graph translation - pulling back geometric insights into structural changes (Algorithm 49). Uncertainty provides risk, deployment uses results, but field geometry analysis is the primary function.

## NeocortexProposal
- **primary**: workspace
- **related**: foundation, storage, uncertainty
- **reason**: NeocortexProposal is a workspace proposal with payload (tokens, edges, candidate rules/adapters), provenance, and confidence. This is workspace proposal mechanism - how neocortex workspace suggests changes for hippocampus admission (Algorithm 25). Storage receives it, uncertainty evaluates it, but workspace proposal lifecycle is the core.

## CommitRecord
- **primary**: workspace
- **related**: foundation, storage, uncertainty
- **reason**: CommitRecord tracks commit decisions (committed, branched, quarantined, rejected) with reasons and metrics. This is workspace commit history - the audit trail of what was admitted from workspace to stable storage. Storage is destination, uncertainty drives decisions, but workspace governance is the primary function.

## Algorithm 14
- **primary**: patterns
- **related**: foundation, storage, uncertainty
- **reason**: Failure memory write and avoid - records pattern failures with context and applies failure brake to pattern scoring. This is pattern anti-learning - the patterns library learns what NOT to do. Uncertainty provides severity, storage persists failures, foundation provides primitives, but pattern failure avoidance is the core.

## Algorithm 56
- **primary**: workspace
- **related**: foundation, graph, storage
- **reason**: EXPORT_CAPSULE extracts subgraph from workspace with overlap signature and hop trace. This is workspace export - packaging workspace artifacts for transfer. Graph provides content, storage provides format, foundation provides primitives, but workspace portability is the primary operation.

## Algorithm 57
- **primary**: workspace
- **related**: foundation, graph, storage
- **reason**: IMPORT_CAPSULE imports capsule into workspace with loop guard, idempotence, and ID remapping. This is workspace import - safely merging external capsules into workspace. Graph provides structure, storage provides format, foundation provides primitives, but workspace merging is the primary operation.

## Algorithm 60
- **primary**: workspace
- **related**: foundation, ingestion, storage
- **reason**: COMMIT_TO_INGEST packages workspace artifacts into envelope and submits to ingest. This is workspace-to-storage graduation - how workspace results enter the stable ingestion pipeline. Ingestion receives it, storage is destination, foundation provides primitives, but workspace lifecycle management is the core.

## Algorithm 49
- **primary**: field
- **related**: foundation, graph, uncertainty
- **reason**: MANIFOLD_TO_GRAPH_PROPOSALS detects geometric wormholes (geometrically close, structurally far) and proposes bridges. This is field geometry analysis - using manifold structure to identify missing graph edges. Graph is target, uncertainty provides risk, foundation provides primitives, but field-based discovery is the primary operation.

## P1 Lean 1
- **primary**: verification
- **related**: foundation, graph, storage
- **reason**: Gated quadratic uniqueness theorem proving unique minimizer of field energy. This is formal verification - using Lean to prove field relaxation properties. Graph provides context (nodes), storage provides state, foundation provides types, but verification of algorithmic correctness is the primary purpose.

## TradeoffProfile
- **primary**: patterns
- **related**: field, storage, uncertainty
- **reason**: TradeoffProfile characterizes pattern functionality and performance across contexts with factor profiles, effect metrics, and variance. This is pattern characterization - profiling how patterns behave across different situations. Field provides energy metrics, storage persists profiles, uncertainty provides variance, but pattern analytics is the core purpose.

## IdeaCandidate
- **primary**: patterns
- **related**: exploration, graph, storage
- **reason**: IdeaCandidate proposes pattern substitution or hybrid with rewrite spec, gain estimates, and region targeting. This is pattern innovation - proposing new pattern combinations. Exploration discovers candidates, graph provides region, storage persists proposals, but pattern recombination is the primary function.
