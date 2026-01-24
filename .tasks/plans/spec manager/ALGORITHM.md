# Specification Reorganization Algorithm

Composed from feedback.md enhancements.

---

## Core Principle: Evidence Preservation

**NEVER rewrite or summarize source material.**

- Evidence = original lines from source files
- Move lines using scripts (cut line ranges directly)
- Build index mapping evidence → entities
- One evidence range can point to multiple entities
- One entity can have multiple evidence ranges
- To understand an entity: query all evidence discussing it
- Invariants, flows, specs - everything is evidence

---

## Input

- Source specification files (7 markdown files)
- Lines are preserved exactly as written

---

## Phase 0: Evidence Extraction (Line Indexing)

**Objective**: Index source lines to entities without rewriting.

### Steps

0.1. **Read source files**
   - Preserve exact line numbers and content
   - Each file has line ranges that become evidence

0.2. **For each section/line range**
   - Identify which entities it discusses
   - Create index entry: `(file, start_line, end_line) → [entity1, entity2, ...]`
   - One range can discuss multiple entities

0.3. **Entity types**
   - Components: Ticket, Project, Task, Step, Run, WSS, Log, Queue, Sandbox, Conclusion
   - Flows: F0, F1, F2, ..., F14
   - Protocols: atomic_write, merge_patch, journals, ULID
   - Actors: User, PM, TM, Root, Step Process
   - System (top-level entity - many things relate to it)

0.4. **Build evidence graph**
   - Nodes: entities + evidence ranges
   - Edges: evidence → entities it discusses
   - This enables: "show me all evidence for entity X"

---

## Phase 1: Structural Topology (Identifying Origins)

**Objective**: Build directed graph, identify roots and leaves.

### Steps

1.1. **Scan all files**
   - Tokenize content of every flow/section

1.2. **Build Directed Graph**
   - Nodes = Flows / Use Cases / Sections
   - Edges = Explicit calls/references (e.g., "Execute: OtherFlow", "See: Section X")

1.3. **Identify Roots (Indegree = 0)**
   - Find nodes with zero incoming edges
   - Label: Originating Flow

1.4. **Classify Roots**
   - If Trigger == User_Action OR Critical_Event → **Core Flow**
   - If Trigger == System_Maint OR Aux_Event → **Auxiliary Flow**

1.5. **Identify Leaves**
   - Find nodes referenced by multiple roots or other flows
   - Label: Shared Sub-Flow

---

## Phase 2: Cluster Hunt (Coupling Analysis from Co-occurrence)

**Objective**: Detect high coupling blocks using spec-native signals (no code parsing).

### Signals (deterministic, no embeddings)

2.1. **Entity Co-occurrence**
   - Entities tagged within the same evidence window form weighted edges
   - Window = same section OR within N lines
   - Higher weight = more frequent co-occurrence

2.2. **Reference Edges**
   - Explicit references: "Execute: X", "See: Y", "calls Z"
   - Direct structural coupling between entities

2.3. **Store Touch Edges**
   - If steps/flows reference the same store, increase coupling weight
   - Stores: WSS paths, Log shards, Queue paths, PGS stacks

### Steps

2.4. **Build Coupling Graph**
   - Nodes = entities from Phase 0
   - Edges = weighted by co-occurrence + references + store touches
   - Edge weight = sum of signal weights

2.5. **Detect Clusters**
   - Apply threshold-based connected components, OR
   - Use modularity/community detection (Louvain, etc.)
   - Result: entity groups that are tightly coupled

2.6. **Classify Store Lifecycle**
   - **Type A (Persisted)**: WSS docs, Log shards, PGS stacks (survive restart)
   - **Type B (Long-Lived Ephemeral)**: In-memory across steps (HIGH RISK)
   - **Type C (Pure Ephemeral)**: Local/temporary within single step

2.7. **Mark Cluster Candidates**
   - Clusters with Type A/B stores = candidates for component extraction
   - Clusters with only references = candidates for taxonomy/protocol

---

## Phase 3: Semantic Classification (DDD Sorter)

**Objective**: Assign extracted cluster to a home (component or taxonomy).

### Tests (in order)

3.1. **Noun Test (Entity Identification)**
   - Does cluster manage lifecycle of a specific "Thing" (User, Ticket, Project)?
   - If Yes → Create Component: `[Noun]/`
   - Move cluster logic here

3.2. **Reification Test (Verb-to-Noun)**
   - Does cluster manage relationship or complex action between entities?
   - If Yes → Reify the Verb (Invite → Invitation)
   - Create Component: `[New_Noun]/`

3.3. **Shape Test (Pure Logic)**
   - Does cluster rely only on inputs (no external state, no side effects on Type A/B vars)?
   - If Yes → Classify as Taxonomy: Utility / Mapper / Algorithm / Protocol
   - Place in appropriate taxonomy folder

### Result

- **Components** = Vertical slices (entities with state/lifecycle)
- **Taxonomies** = Vertical slices (pure logic, no state)
- Both can live side by side
- Within a component, can organize by taxonomy

---

## Phase 4: Responsibility Annotation

**Objective**: Annotate steps with responsibilities they fulfill.

### Steps

4.1. **For each step in evidence**
   - Ask: Which responsibility is this trying to fulfill?
   - Ask: What might use that responsibility?

4.2. **If doesn't map to existing responsibility**
   - Return to Phase 0: gather more evidence to grow understanding
   - Then return here with new evidence

4.3. **Annotate steps with responsibilities**
   - Don't annotate components - annotate STEPS
   - Steps can have many responsibilities
   - Annotations go in index (not inline in evidence)
   - This enables responsibility-based search

### Responsibility Categories
- R-DURABILITY: Data persistence
- R-EVIDENCE: Audit trail
- R-CONTROL: Execution control (pause/resume)
- R-ISOLATION: Sandboxing
- R-VALIDATION: Quality gates
- R-RECOVERY: Failure handling
- R-COORDINATION: Multi-process sync
- R-USER-FEEDBACK: User communication

---

## Phase 5: Data Signal Tracing

**Objective**: Track data from origins through transformations.

### Steps

5.1. **Identify Data Origins (0-Edge Data)**
   - **Persisted Roots**: Database records, file systems (exist before process starts)
   - **External Roots**: User input, API payloads (enter at runtime)

5.2. **Trace Transformations**
   - **Pass-Through**: Function(A) → Returns A (signal identical)
   - **Projection (Slicing)**: Function(User) → User.ID (subset of signals)
   - **Aggregation (Smearing)**: Function(List<Prices>) → Total (signals from all inputs)

5.3. **For each store**
   - Understand signals going INTO the store
   - So when we read, we can trace signals back

5.4. **Embed in algorithms**
   - Data signals live IN algorithms, not separate
   - Each step tracks: signals in, signals out, stores touched

---

## Phase 6: Invariant Extraction & Identity Resolution

**Objective**: Extract invariants, resolve entity identity, detect candidates.

### Steps

6.1. **Extract Invariants per Step/Entity**
   - Tag "Musts" (e.g., @Invariant: Unique, @Invariant: ThreadSafe)
   - Invariants govern how steps must operate

6.2. **Entity Identity Resolution**
   - Identity = Union of Invariants (not just data shape)

   **Case A: Same Entity (Contextual Projections)**
   - Entity A: Shape {email, password}, Invariant: email must be unique
   - Entity B: Shape {email, credit_card}, Invariant: email must be verified
   - Invariants are ORTHOGONAL (don't conflict) → MERGE
   - These are two vertical slices operating on same identity

   **Case B: Different Candidates (Tradeoff)**
   - Entity A: Shape {data}, Invariant: Low Latency, Weak Consistency
   - Entity B: Shape {data}, Invariant: High Latency, Strong Consistency
   - Invariants CONFLICT → Different implementations of same Symbol
   - This triggers Tradeoff Engine

6.3. **Invariant Propagation (Bubbling Up)**
   - Parent (Symbol) defines Requirements (Must-Have Invariants)
   - Child (Candidate) defines Capabilities (Provided Invariants)
   - Mismatch between Child Capabilities and Parent Requirements = Tradeoff
   - Violations bubble up explicitly to parent

---

## Phase 7: Candidate & Tradeoff Analysis

**Objective**: Handle parallel symbols, score candidates, resolve tradeoffs.

### Steps

7.1. **Identify Candidates**
   - Symbols in graph can map to MULTIPLE symbols (parallel candidates)
   - Graph is "what code COULD be", not code itself
   - When we choose a candidate, we choose part of horizontal slice within vertical slice

7.2. **Score Candidates**
   - Compare Candidate Invariants vs Parent Symbol Requirements
   - Match → Perfect Candidate
   - Mismatch → The difference is the Risk/Tradeoff

7.3. **Apply Higher-Order Invariants**
   - Trust > Friction > Performance (decision order)
   - Use to resolve conflicts when candidate cannot fulfill all invariants

7.4. **Record Tradeoffs**
   - What we gain vs what we lose
   - Which higher-order invariant guided the decision
   - Tradeoffs live IN the structure (in the step/component)

### Tradeoff Dimensions
- Data, memory, latency, speed
- Recovery, exfiltration, evidence breadth
- Audience, platform, runtime context
- Footprint, concurrency, volume, size
- Maintenance model (AI-only? Human review?)
- Cost of ownership (maintenance, hardware, user satisfaction)

---

## Phase 8: Physical Reorganization (Iterative)

**Objective**: Create folder structure based on discoveries. ITERATE, don't finalize immediately.

### Structure Rules

8.1. **Root is a component**
   - Start with `system/` or similar as root folder
   - Everything lives in ONE unified structure

8.2. **Vertical Slices**
   - Components (entities with state/lifecycle)
   - Taxonomies (pure logic, no state)
   - Can live side by side as siblings
   - Within a component, can organize by taxonomy

8.3. **Horizontal Slices**
   - What exists INSIDE a vertical (component)
   - Abstraction levels within that component

8.4. **Recursive Structure**
   - horizontal → vertical → horizontal → vertical
   - As deep as needed per branch

### Physical Organization Details

8.5. **Moving Evidence (Line Ranges)**
   - Use scripts to cut exact line ranges from source files
   - Move lines into entity folders (NOT copy, NOT rewrite)
   - Each entity folder contains the original evidence lines
   - Maintain line provenance: `(original_file, start_line, end_line)`

8.6. **Entity Folders**
   - Each entity gets a folder (component or taxonomy)
   - Folder contains: evidence files (original lines moved here)
   - Evidence that discusses multiple entities:
     - Lives in ONE primary entity folder
     - Index references it from other entities
     - OR split if cleanly separable at line boundaries

8.7. **Index Structure**
   - `_index.md` or `_index.json` at each level
   - Maps: entity → evidence locations
   - Maps: evidence → entities it discusses
   - Enables queries: "all evidence for entity X"
   - Enables reverse: "what entities does this evidence discuss"

8.8. **Algorithms in Structure**
   - Algorithms live in horizontal slices (inside components)
   - Steps are symbols referencing other algorithms
   - Symbols can reference algorithms from ANYWHERE (graph, not tree)
   - Algorithm file contains original evidence lines about that algorithm

8.9. **Composite Step Content**
   Each step (as evidence) contains or references:
   - Behavior: original lines describing the algorithm
   - Data signals: original lines about inputs/outputs/stores
   - Invariants: original lines stating constraints
   - Unknowns: gaps detected (step never resolves to technical stack)
   - Tradeoffs: original lines about decisions + analysis
   - Responsibilities: annotations (index entries, not rewritten)
   - Candidates: original lines about alternatives

8.10. **Unknowns Detection**
   - A step is unknown if it never translates to technical stack
   - If it always remains a symbol, it's underspecified
   - Track in index: `unknown_steps[]`
   - Evidence for unknowns = the unresolved symbol references

8.11. **Candidate Organization**
   - Parallel candidates for same symbol = siblings in structure
   - Each candidate has its own evidence
   - Parent symbol references all candidates
   - Tradeoff analysis links candidates with conflicts

8.12. **Cross-References**
   - When evidence discusses entity X but lives in entity Y folder:
     - Add index entry in X pointing to Y's evidence
   - When algorithm A references algorithm B:
     - Add edge in graph index
   - Preserve all relationships without duplicating content

### Content Rules (Evidence-Based)

8.13. **Never Rewrite**
   - All content is original source lines
   - Analysis/annotations go in index, not inline
   - If you need to add context, add as separate annotation file
   - Annotation files clearly marked as non-source

8.14. **Invariants Storage**
   - Original invariant statements stay as evidence
   - Extracted invariant list goes in index
   - Identity resolution results go in index
   - Conflicts and tradeoffs documented in index

8.15. **Responsibility Annotations**
   - Don't modify source evidence
   - Add responsibility tags in index: `step_id → [R-DURABILITY, R-EVIDENCE, ...]`
   - Enables responsibility-based search via index

8.16. **Store Monogamy**
   - Every Store (DB table, persistent file, global var) must physically live inside ONE vertical slice
   - All other slices must access it via an Algorithm (Symbol), never directly
   - No direct cross-slice store access
   - Enforces clean boundaries and explicit dependencies

---

## Iteration Loop

After each phase, loop back as needed:

```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7 → Phase 8
    ↑                                                                              |
    └──────────────────────────────────────────────────────────────────────────────┘
```

- New evidence may reveal new entities
- New clusters may emerge from evidence
- New invariants may change entity identity
- New candidates may surface tradeoffs
- Structure evolves as understanding grows
- Index grows with each iteration

---

## Execution Order

1. **Phase 0**: Index source files → entities (build evidence graph)
2. **Phase 1**: Build topology graph from evidence (roots, leaves, edges)
3. **Phase 2**: Hunt clusters in evidence (state mutation analysis)
4. **Phase 3**: Classify clusters semantically (noun/reification/shape tests)
5. **Phase 4**: Gather more evidence if understanding incomplete
6. **Phase 5**: Trace data signals through evidence
7. **Phase 6**: Extract invariants, resolve entity identity
8. **Phase 7**: Analyze candidates and tradeoffs
9. **Phase 8**: Physically reorganize (move lines, build folders, update index)
10. **ITERATE**: Return to Phase 0 with new understanding

### Key Constraint

Structure emerges from evidence. Don't design upfront.
Move lines, don't summarize. Index, don't rewrite.

---

## Phase 9: Convergence (Question → Answer → Evidence Loop)

**Objective**: Resolve all unknowns, tradeoffs, risks, and ambiguities.

### What Remains After Phase 8

9.1. **Unknowns**
   - Steps that never resolve to technical stack
   - Symbols that remain abstract

9.2. **Open Tradeoffs**
   - Invariant conflicts without resolution
   - Candidates without selection

9.3. **Open Risks**
   - Identified risks without mitigations
   - Unaddressed concerns

9.4. **Ambiguous Evidence**
   - Evidence not understood well enough to distribute
   - Unclear which entities evidence discusses

### Resolution Process

9.5. **Answer Own Questions (Research)**
   - Use Firecrawl to research technical solutions
   - Create candidate solutions based on research
   - Identify tradeoffs between candidates (may not be in source material)
   - Risk analysis feeds into decision making
   - Research answers become NEW EVIDENCE

   **Research Bounding Guardrail (Prevent Analysis Paralysis)**:
   - Risk: Can research forever seeking "perfect diversity"
   - Confidence threshold: If `candidates.count > 3` AND `distinct_tradeoffs.count` hasn't increased in last iteration → STOP
   - When stopped: Select candidate that maximizes Highest-Order Invariant (per 7.3)
   - Don't chase perfection - chase sufficient diversity to see tradeoffs

9.6. **Only Ask User About Invariant Priorities**
   - When tradeoffs exist but unclear which to prioritize
   - Ask: "Which invariant takes priority? Trust vs Speed? Durability vs Simplicity?"
   - User answers about priorities → new evidence
   - Don't ask user to solve technical problems (research those)

9.7. **Candidates and Tradeoff Discovery**
   - Goal: discover tradeoffs through candidate diversity
   - **When to generate more candidates:**
     - No clear answer on which approach to take
     - All current candidates look too similar
     - Not enough differentiation to see tradeoffs
   - **Types of candidates:**
     - Structural candidates (architecture choices)
     - Technical candidates (implementation choices)
   - Keep generating candidates until tradeoffs emerge
   - Similar candidates = not enough diversity = keep searching
   - Risk without tradeoff = need more candidate research

9.8. **Entity Promotion**
   - Can't promote entities to Phase 1 until understood enough
   - May have no entities initially → gather more evidence first
   - Phase 9 feeds back to Phase 0 with new evidence
   - Entities emerge from evidence, not upfront

9.9. **Ingest New Evidence**
   - Research results → Phase 0 (index as evidence)
   - User answers about priorities → Phase 0 (index as evidence)
   - Created candidates → Phase 0 (index as evidence)
   - Iterate through all phases again

9.10. **Iterate Until Convergence**
   - 0 unknowns remaining
   - All tradeoffs resolved (with candidate selection)
   - All risks addressed (with mitigations or accepted)
   - No ambiguous evidence
   - Everything cleanly distributed to entities

### Note on Source Material

The tech plans contain analysis but tradeoffs may not be explicitly captured.
Must infer/discover tradeoffs through:
- Comparing candidates in the plans
- Researching alternatives not mentioned
- Identifying implicit decisions that were made

### Convergence Criteria

```
DONE when:
  unknowns.count == 0
  AND open_tradeoffs.count == 0
  AND open_risks.count == 0
  AND ambiguous_evidence.count == 0
  AND all_evidence_distributed == true
```

---

## Summary

```
Phase 0: Index evidence → entities
Phase 1: Build topology graph
Phase 2: Hunt clusters
Phase 3: Classify semantically
Phase 4: Annotate responsibilities
Phase 5: Trace data signals
Phase 6: Extract invariants, resolve identity
Phase 7: Analyze candidates and tradeoffs
Phase 8: Physical reorganization
Phase 9: Convergence loop (questions → answers → new evidence)
         ↓
      ITERATE until done
```

---

## Phase 10: Coverage Verification (Annotation System)

**Objective**: Ensure 100% line coverage of source material through traceable annotations.

### 10.1 Annotation System

Final spec files are coherent, standalone documents - NOT copies of raw evidence.
Each spec element has an annotation marker (e.g., `[F0.1]`, `[TICKET.inv.2]`).

Required files:
- `evidence_index.json`: maps evidence IDs to source file line ranges
- `annotations.json`: maps annotation IDs to evidence IDs
- `non_evidence.json`: lines explicitly excluded (headers, formatting)

### 10.2 Two-Phase Coverage Check

**Phase 1: Source Line Coverage**
Every line in every source file must be either:
- Covered by an evidence entry, OR
- Explicitly marked as non-useful in `non_evidence.json`

**Phase 2: Evidence → Annotation Coverage**
Every evidence entry must be referenced by at least one annotation.

### 10.3 Coverage Script

```python
# check_coverage.py verifies:
# 1. All source lines are in evidence or excluded
# 2. All evidence is referenced by annotations
```

Run: `python3 check_coverage.py`

### 10.4 Annotation Naming Convention

- Flows: `F<N>`, `F<N>.<step>`, `F<N>.inv.<n>`, `F<N>.evidence.<n>`
- Components: `<NAME>`, `<NAME>.shape`, `<NAME>.fields`, `<NAME>.inv.<n>`
- Global invariants: `INV-<NAME>`

---

## Structure Clarifications

### Horizontal vs Vertical Slices

```
system/                     # Root vertical (the system)
  flows/                    # First horizontal slice (universal algorithms)
    f0_bootstrap.md
    f1_project_manager.md
    ...
  invariants.md             # System-level invariants (part of describing system)
  children/                 # Sub-verticals (components)
    ticket/
      spec.md               # Describes ticket
      flows/                # Ticket's horizontal slice (ticket-specific algorithms)
      children/             # Ticket's sub-verticals
        task/
          spec.md
          children/
            step/
              ...
    wss/
      spec.md
      children/
        ...
```

### Self vs Children

At each level:
- Everything EXCEPT `children/` describes THIS component (self)
- `children/` contains sub-components (other verticals)

### Where Invariants Live

Invariants are NOT separate folders. They live INSIDE algorithms/steps:

```markdown
# F12 — PAUSE/RESUME Protocol

[F12] Mandatory protocol for pausing step execution.

## Steps
...

## Invariants
[F12.inv.1] PAUSE is mandatory - every step must implement the control loop.
[F12.inv.2] Pause requests and ACKs are durable files.
```

Each algorithm file is a composite containing:
- Behavior (steps/logic)
- Invariants (constraints)
- Data signals (inputs/outputs)
- Evidence markers (annotations)

Global invariants that apply to everything live in `system/invariants.md`.
