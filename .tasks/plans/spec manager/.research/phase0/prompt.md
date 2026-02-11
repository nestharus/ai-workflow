# Research: Restructuring Freeform Prose Into Structured Spec Format

## What I Need From You

I need an algorithm to take **freeform prose specifications** and restructure them into a **specific output format** that my downstream system (PDD — Prototype Driven Development) can operate on. This is NOT extraction. This is LLM-driven restructuring — summarizing, classifying, and organizing prose into a structured format through iterative refinement.

I have two prior design attempts. I need you to analyze their strengths and weaknesses, then design the Phase 0 algorithm that bridges freeform input to structured output.

---

## The Output Format (What PDD Needs)

PDD expects specs in four categories:

### 1. Analysis Docs
Options explored and why things were chosen. Tradeoff reasoning. Decision rationale.

Example:
> "We chose file-based queues over database-backed queues because this is a local-first CLI tool with no daemon requirement."

### 2. Constraints / Invariants
Guiding principles that must always hold **regardless of implementation**. These survive if you completely change how the system is built.

Example:
> "Trust > Friction > Performance" (product priority ordering)
> "No silent termination — no fixed max iteration caps as termination criteria"
> "Flat orchestration — root owns all step/agent OS processes"

### 3. Overview
Prose explanations of how things fit together and what things are. Can contain paragraphs. This is the high-level "what is this system" narrative.

### 4. Details — Algorithms, Stores, and Shapes
The pseudocode-level content. Three sub-types:

- **Algorithms**: Procedures, sequences of steps, "what to do when." Can contain ambiguities — that's fine. They describe behavior.
- **Stores**: Data persistence mechanisms, storage layouts, databases, queues.
- **Shapes**: Data structures, schemas, field definitions, type definitions.

All elements receive unique IDs. The format can be parsed and separates the noise (analysis) from the raw details while providing context (overview, constraints) to understand the raw details and expand upon them.

---

## The Input (What We Start With)

Freeform prose specifications. Key constraints about the input:

- **No assumed structure.** There may or may not be headers. There may or may not be sentences. Paragraph structure varies wildly.
- **No extractable patterns via regex.** You cannot assume that any text within a spec follows a set pattern. The patterns cannot be extracted by regex or any type of script. They can only be recognized contextually by an LLM.
- **Categories are interleaved.** A single section titled "Ticket Lifecycle" might contain shapes (state enum), invariants (terminal states rule), algorithms (conflict resolution sequence), analysis (a Mermaid diagram explaining the design), more algorithms (transition recording), and more shapes (audit log structure). A single paragraph might contain an invariant sentence followed by an algorithm sentence.
- **"MUST" does not mean invariant.** This is the biggest trap. In a real 13,700-line spec with ~500+ "MUST" statements, the breakdown was: ~60% algorithm steps, ~30% shape details, ~5% invariants, ~5% analysis. A naive "MUST = constraint" classifier puts 95% of content in the wrong category.
- **Input can be very large.** Multiple files, thousands of lines, hundreds of pages.

---

## The Classification Challenge (The Hard Part)

The core difficulty is separating invariants from algorithms/shapes. Real specs write algorithmic implementation details using constraint language.

### The Classification Rule

Ask: **Does this statement survive if you completely change the implementation?**

- If yes → Invariant / Constraint
- If no → Algorithm or Shape (a Detail)

### Examples That Fool Naive Classifiers

| Statement | Sounds like | Actually is | Why |
|-----------|------------|-------------|-----|
| "TM MUST perform ticket status transitions under `locks/ticket.<ticket_id>.lock`" | Constraint | Algorithm | A different implementation might use a database transaction or CAS instead of file locks. The underlying invariant: "Concurrent modifications must never corrupt ticket state." |
| "`blocker_kind` MUST be present when `status == blocked`" | Constraint | Shape | This is a field validation rule. A different implementation might use a different field name. The underlying invariant: "Blocked tickets must always explain why they're blocked." |
| "Steps MUST emit `step_start` / `step_stop` events" | Constraint | Algorithm | This prescribes specific event names — an implementation detail. The underlying invariant: "Every step must produce evidence sufficient to reconstruct what happened." |
| "Trust > Friction > Performance" | Constraint | Constraint (correct!) | This IS a guiding principle. It tells you WHY you might choose a slower but more durable approach. |
| "No silent termination — no fixed max iteration caps" | Constraint | Constraint (correct!) | This constrains ALL algorithms to use evidence-based stopping, regardless of implementation. |

### Common Traps

1. "MUST" does not mean invariant. Most "MUST" sentences are algorithms or shapes.
2. "normative" does not mean invariant. Normative sections contain ALL categories interleaved.
3. JSON schema field rules — written as rules but they're shape definitions.
4. State machine transitions — written as rules but they're algorithm procedures.
5. Lock ordering rules — written as rules but they're concurrency algorithms.
6. Error handling rules — written as rules but they're algorithm branches.

---

## Prior Design #1: Evidence Preservation (Strategy-Driven)

### Core Idea
"NEVER rewrite or summarize source material. Evidence = original lines from source files. Move lines using scripts. Build index mapping evidence to entities."

### Algorithm
- Phase 0: Evidence Extraction — index source lines to entities without rewriting. Create mapping: (file, start_line, end_line) → [entity1, entity2, ...]
- Phase 1: Structural Topology — build directed graph, identify roots and leaves
- Phase 2: Cluster Hunt — coupling analysis from entity co-occurrence (same section or within N lines)
- Phase 3: Semantic Classification — noun test (entity identification), reification test (verb-to-noun), shape test (pure logic)
- Phase 4-8: Responsibility annotation, data signal tracing, invariant extraction, candidate/tradeoff analysis, physical reorganization
- Phase 9: Convergence loop — resolve unknowns, tradeoffs, risks, ambiguities
- Phase 10: Coverage verification — annotation system ensuring 100% line coverage

### Supporting Concepts
- **Unitizer Strategies**: Multiple granularity levels based on input messiness — LineUnitizer (maximum tracking), SentenceUnitizer (semi-structured), ClauseUnitizer (compound statements), SectionUnitizer (clean annotated content), LLMUnitizer (hard-to-segment prose)
- **Strategy Library Framework**: Extensible strategies defined in YAML, selected based on content analysis. Strategies include sentence_decomposition, line_membership, structured_extraction, entity_resolution, multi_labeling, coverage_verification.
- **Line Membership Guarantee**: Every line from source must appear in target OR be explicitly handled. source_lines - target_lines = handled_lines.
- **LLM Inference as First-Class**: Infer requirements from prose, resolve vague references, infer missing proof obligations. LLM outputs are evidence with confidence scores, not truth.
- **Gap as First-Class Element**: Detectors produce GapEvidence, gaps synthesized by clustering related evidence into GapElements.
- **Library Discovery**: Libraries EMERGE from data. Multi-label assignment → shape aggregation → convergence analysis. NO hardcoded keywords.
- **Many-to-Many Membership**: Multiple prose fragments can be handled by one structured element. One source atom can contribute to multiple target elements.

### Strengths
- Rigorous provenance tracking
- No information loss by design (lines are moved, not rewritten)
- Strategy framework handles diverse input types
- Library discovery is data-driven

### Weaknesses for Our Purpose
- Assumes you CAN extract atoms from text (entities, flows, components) — but freeform prose may not have extractable atoms
- Phase 0 "Evidence Extraction" requires identifying entities, but freeform prose doesn't have clearly named entities
- Very complex (10+ phases) for what may be a simpler problem
- The "never rewrite" principle conflicts with the need to GENERATE structured output — we need to produce Analysis/Constraints/Overview/Details documents, not just index source lines

---

## Prior Design #2: Iterative LLM Summarization

### Core Idea
"You cannot assume that any text within a spec follows a set pattern. These patterns cannot be extracted by regex or any type of script. The best thing to recognize general patterns is an LLM."

### Algorithm
1. **Summarize** each spec document — the "what" is in there, not the details. Is an algorithm in there? Label it and state what it does (intent). Various stores or components? Summarize and state their intent. One GLM sub-agent per file. Summaries are annotated with the evidence sections used ([FILEPATH::SECTION]).
2. **Identify libraries** — for each summary identify high-level concerns. The "libraries" underneath the summary. Describe what each library is responsible for.
3. **Detect overlap** — between libraries. Assign overlap to one library or another, or create a new library. Isolate all concerns. Show how libraries use each other.
4. **Match libraries to summaries** — for each library × summary file pair, determine which summaries may help create the library.
5. **Recurse** — identify libraries that could have their own internal libraries. Repeat until no more candidates.
6. **Consolidate details** — rewrite and label. This translates input specs into isolated library specs.
7. **Refine** — for each library, refine specs. Continue refining until all details from the source are accounted for.

### Supporting Concepts
- **Multi-model approach**: GLM for summarizing and selecting what's important. Opus for recognizing patterns. ChatGPT for tracking details.
- **PDD (Prototype Driven Development)**: Work in phases. Each phase produces something messy. The next phase cleans it up. Plan as little as you can get away with. Constant baby steps.
- **Spec Format**: The output format — Analysis Docs, Constraints, Overview, Details (algorithms and shapes). All elements receive unique IDs.
- **Continuous refinement during implementation**: After identifying general libraries, implement in parallel. As you run into ambiguities, agents block and refinement happens.

### Strengths
- Accepts truly freeform input — no assumed structure
- LLM-driven, not regex-driven
- Library discovery is organic (identify from summaries, detect overlap, isolate)
- Simple conceptual model (summarize → identify → isolate → refine)

### Weaknesses for Our Purpose
- **Does not address the classification challenge.** The algorithm summarizes and identifies libraries but never explicitly classifies content into Analysis/Constraints/Overview/Details. Step 6 "consolidate details — rewrite, label" is underspecified. HOW do you classify each fragment?
- **The invariant trap is not addressed.** 95% of "MUST" statements in real specs are algorithms or shapes, not invariants. The algorithm doesn't discuss how to distinguish invariants from algorithmic steps written in constraint language.
- **Interleaved content is not addressed.** A single paragraph can contain an invariant, an algorithm step, and a shape definition. The algorithm discusses library-level isolation but not within-paragraph classification.
- **"Rewrite and label" is underspecified.** What does "rewrite" mean? What are the labels? How do you ensure the rewrite doesn't drop details?
- **Recursion stopping criterion.** "Until no more candidates" for sub-libraries — but how do you decide there are no more candidates?

---

## What I Need You To Design

### The Core Question

Design the Phase 0 algorithm that takes freeform prose and produces structured output in the Analysis/Constraints/Overview/Details format. Specifically:

### Question 1: The Classification Algorithm

How should an LLM classify prose fragments into the four categories (Analysis, Constraints, Overview, Details) reliably, given that:

- 95% of "MUST" statements are NOT invariants
- Categories are interleaved within paragraphs
- The classification rule is "does this survive a complete reimplementation?" but applying this rule requires understanding the ENTIRE system, not just the fragment
- Chunks of paragraphs can be pasted directly into Details (algorithms support ambiguity, no need for perfect decomposition)

Should classification happen:
- (a) After summarization and library discovery (you understand the system first, then classify)?
- (b) During summarization (classify as you summarize)?
- (c) As a separate pass over the original text after libraries are identified?
- (d) Some other ordering?

What is the prompt structure / few-shot approach that avoids the invariant trap?

### Question 2: Granularity of Classification

At what level do you classify?

- Whole paragraphs can go into Details as-is (algorithms support ambiguity, chunks of paragraphs are fine).
- But invariants and algorithm steps can coexist within a single paragraph.
- Splitting every sentence is expensive and may destroy context.

What is the right approach? Do you:
- (a) Classify at paragraph level, accepting some category mixing?
- (b) Classify at paragraph level, then do a second pass splitting only paragraphs flagged as mixed?
- (c) Always split at sentence level?
- (d) Use the LLM to identify natural break points within paragraphs?

### Question 3: Library Discovery and Classification Interaction

Design #2 discovers libraries from summaries. But libraries are about WHAT the system does (vertical slices). The four output categories are about the NATURE of the content (analysis vs constraint vs algorithm vs shape). These are orthogonal dimensions.

How do these interact? Does library discovery happen:
- (a) Before classification (discover libraries, then classify content within each library)?
- (b) After classification (classify everything first, then organize into libraries)?
- (c) Simultaneously (discover libraries and classify in one pass)?

### Question 4: Detail Accounting (Completeness Check)

The stopping criterion is: **all details from the source prose are accounted for** in the output. Not "all ambiguities resolved" — ambiguities are fine and expected. The pseudocode supports them.

How do you verify that every detail is accounted for without the heavy machinery of Design #1's line membership guarantee? We need something lighter — we can use an LLM judge to verify coverage — but what's the right structure?

Options:
- (a) Compare source paragraphs against output, using LLM to judge if each source paragraph is covered
- (b) Annotate output with source references ([from: section X, paragraph Y]) and verify coverage
- (c) After restructuring, have an LLM read both source and output and list anything missing
- (d) Some combination

### Question 5: The Overall Phase 0 Pipeline

Given your answers to Questions 1-4, propose the complete Phase 0 pipeline:

- What are the steps?
- What is the input to each step?
- What is the output of each step?
- What model should run each step (fast/cheap summarizer vs powerful classifier vs detail-tracker)?
- How many passes over the source material?
- What intermediate artifacts are produced?
- How do you handle very large inputs (hundreds of pages)?

Design it as an LLM-driven workflow — agents that can be run, producing files that other agents consume. File I/O for communication between agents to reduce context pressure.

### Question 6: Handling the Boundary Cases

Some content doesn't fit cleanly:
- **Mixed paragraphs**: Contains both an invariant and an algorithm step in the same paragraph. Example: "Terminal states MUST NOT transition except via explicit reopen [invariant]. The reopen flow requires admin approval, logs the override reason, and creates a new ticket revision [algorithm]."
- **Implied invariants**: The text never states an invariant explicitly but implies one through multiple algorithm rules. Example: Multiple rules all enforce "never lose data" without stating it.
- **Narrative that IS the algorithm**: Some algorithms are written as stories, not as steps. Example: "When a user submits a ticket, the system first validates all fields, then checks for duplicate titles against recent submissions, then assigns a priority based on the keyword analysis..."
- **Tables and diagrams**: Structured content embedded in prose (Mermaid diagrams, markdown tables, JSON examples).

How should each of these be handled?

---

## Constraints On Your Design

1. **No regex for content analysis.** Patterns cannot be extracted by regex or scripts. All pattern recognition must use LLMs.
2. **Chunks of paragraphs are acceptable output.** You don't need to decompose everything into atomic sentences. If a paragraph is clearly an algorithm, paste the whole paragraph as a Detail.
3. **Ambiguity in output is fine.** Algorithms and shapes can contain ambiguous language. Don't try to resolve all ambiguity — just classify and organize.
4. **Details must not be dropped.** Every detail from the source must appear somewhere in the output. Not every WORD — but every piece of information.
5. **Libraries emerge from data.** Don't hardcode library keywords. Libraries should be identified from the content itself.
6. **File I/O between agents.** Each step produces files that the next step consumes. This reduces context pressure and allows using different models for different steps.
7. **The system processes one spec at a time.** Not cross-spec. One spec (possibly multiple files) → one set of Analysis/Constraints/Overview/Details output.
