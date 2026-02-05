# Research Report: State-of-the-Art Techniques for Specification Refinement, Management, and Quality Assurance

**Date**: 2026-02-04
**Scope**: Algorithms and techniques applicable to LLM-based hybrid spec management systems

---

## Table of Contents

1. [Requirements Traceability](#1-requirements-traceability)
2. [NLP for Requirements Engineering](#2-nlp-for-requirements-engineering)
3. [Specification Decomposition](#3-specification-decomposition)
4. [Drift Detection](#4-drift-detection)
5. [Overlap and Redundancy Detection](#5-overlap-and-redundancy-detection)
6. [Fact Extraction from Natural Language](#6-fact-extraction-from-natural-language)
7. [Provenance Tracking](#7-provenance-tracking)
8. [Verification and Validation of Requirements](#8-verification-and-validation-of-requirements)
9. [Cross-Cutting Themes and Synthesis](#9-cross-cutting-themes-and-synthesis)

---

## 1. Requirements Traceability

### Key Algorithms and Techniques

**Traditional Information Retrieval (IR) Methods:**
- **TF-IDF + Cosine Similarity**: The baseline approach. Requirements and artifacts are vectorized using term frequency-inverse document frequency, then similarity is computed via cosine distance. Simple but suffers from vocabulary mismatch.
- **Latent Semantic Indexing (LSI)**: Applies SVD to the term-document matrix to capture latent semantic relationships. Addresses synonymy but not polysemy.
- **Latent Dirichlet Allocation (LDA)**: Topic-model-based tracing that groups requirements and code by latent topics.

**Deep Learning Approaches:**
- **Word2Vec / Doc2Vec Embeddings**: Map requirements and artifacts into continuous vector spaces. The traceability pipeline uses preprocessing -> embedding -> link generation -> link refinement stages (Rosado da Cruz & Cruz, 2025).
- **BERT-based Models**: Pre-trained transformers fine-tuned on traceability datasets. Lin et al. (2021) showed BERT models significantly outperform IR baselines for trace link recovery.
- **CodeBERT**: A bimodal pre-trained model for programming and natural languages (Feng et al., 2020), enabling cross-modal tracing between requirements (NL) and code.

**TraceLLM (2025 -- State of the Art):**
- Leverages LLMs with systematic prompt engineering for requirements traceability.
- Key innovation: **Label-aware demonstration sampling** for few-shot prompting that selects the most informative examples.
- Achieves state-of-the-art F2 scores across multiple traceability datasets.
- Demonstrates that **lightweight models with good prompts can match larger models**, making the approach cost-effective.
- Uses structured prompt design methodology rather than ad-hoc prompting.

**RTM Construction Methods:**
- **Full re-recovery**: Rebuild entire traceability matrix when artifacts change. Simple but expensive.
- **Incremental update**: Only recompute links for changed artifacts. More efficient but risks propagation errors.
- **TrusTrace**: Mines software repositories to improve accuracy of requirement traceability links by incorporating version history and developer activity patterns (Ali et al., 2012).

### Strengths and Limitations

| Technique | Strengths | Limitations |
|-----------|-----------|-------------|
| TF-IDF/LSI | Fast, interpretable, no training data | Misses semantic similarity, vocabulary mismatch |
| BERT/CodeBERT | Captures deep semantics, cross-modal | Needs fine-tuning data, computationally expensive |
| TraceLLM | No fine-tuning needed, flexible, SOTA results | API costs, prompt sensitivity, non-deterministic |
| LDA | Discovers latent structure | Requires tuning number of topics |

### Application to LLM-Based Spec Management

- **TraceLLM's prompt engineering approach is directly applicable**: Design structured prompts that ask the LLM to identify trace links between spec units and implementation artifacts.
- **Hybrid approach recommended**: Use embedding-based methods (BERT/sentence transformers) for candidate retrieval (fast, cheap), then use LLM for verification and refinement (accurate, expensive).
- **Incremental traceability**: When specs change, only re-trace affected units rather than rebuilding the entire matrix.
- **Bidirectional tracing**: Maintain both forward (requirement -> code) and backward (code -> requirement) links for complete coverage analysis.

---

## 2. NLP for Requirements Engineering

### Key Algorithms and Techniques

**Ambiguity Detection:**
- **Lexical indicator scanning**: Rules-based detection of ambiguity markers (e.g., "may", "could", "appropriate", "etc.", "some"). Tools like QVscribe implement this approach.
- **VIBE (Variability In amBiguous rEquirements)**: Detects ambiguity by searching for specific linguistic indicators while also capturing variability indicators that may masquerade as ambiguity (Sciencedirect, 2022).
- **ML-based ambiguity classifiers**: Novel machine learning approaches train on labeled ambiguous/unambiguous requirements. Recent work (IEEE Access, 2025) proposes ML classifiers that enhance clarity and quality of software requirements.
- **Automated Repair of Ambiguous Requirements (2025)**: Goes beyond detection to automatically rewrite ambiguous requirements in a fully-automated fashion, demonstrating that repair (not just detection) is feasible.

**Incompleteness Detection:**
- **Template conformance checking**: Compare requirements against predefined templates (e.g., EARS -- Easy Approach to Requirements Syntax) to identify missing elements.
- **LLM-based gap analysis**: Using LLMs with the "Recipe Pattern" prompt to detect missing requirements by analyzing the logical completeness of a requirement set (demonstrated on ISS collision avoidance requirements).

**Inconsistency Detection:**
- **Pairwise contradiction checking**: Compare requirement pairs to find logical conflicts.
- **Ontology-based consistency**: Build domain ontology and check requirements against it.

**Quality Metrics (from INCOSE Guide to Writing Requirements v4):**
- Requirements should be: Necessary, Appropriate, Unambiguous, Complete, Singular (atomic), Feasible, Verifiable, Correct, Conforming.
- Each characteristic maps to automated checks.

**LLM Impact on RE (Emergent Mind, 2025):**
- LLMs reduce drafting time by **60-70%** for requirements artifacts.
- LLMs outperformed humans in requirement elicitation tasks, producing more aligned and complete results.
- However, LLMs show **over-correction bias** and **performance drops under complexity** for verification tasks.
- Multi-agent strategies and prompt engineering are crucial for maximizing utility.

### Strengths and Limitations

| Technique | Strengths | Limitations |
|-----------|-----------|-------------|
| Rule-based indicators | Fast, deterministic, explainable | High false positive rate, misses context-dependent ambiguity |
| ML classifiers | Learn from data, capture patterns | Need labeled training data, domain-specific |
| BERT-based models | Deep semantic understanding | Computationally expensive, opaque |
| LLM-based analysis | Flexible, no training needed, can repair | Non-deterministic, hallucination risk, expensive |

### Application to LLM-Based Spec Management

- **Multi-layer quality checking**: Use fast rule-based checks first (INCOSE criteria), then LLM-based deep analysis for flagged issues.
- **Automated repair pipeline**: When ambiguity is detected, use LLMs to generate disambiguated alternatives for human review.
- **Quality scoring**: Assign quantitative quality scores to each spec unit based on multiple dimensions (ambiguity, completeness, testability, atomicity).
- **Template enforcement**: Use EARS or similar templates as structural guides for LLM-generated requirements.

---

## 3. Specification Decomposition

### Key Algorithms and Techniques

**Atomic Requirements Principle (QRA Corp / INCOSE):**
- An atomic requirement describes a **single system function or capability**.
- Test for atomicity: Can this requirement be broken into sub-requirements that are independently verifiable?
- Non-atomic indicator words: "and", "or", "with", "also", "including", "but".
- Decomposition types:
  - **Horizontal**: Break compound requirements into parallel sibling requirements.
  - **Vertical**: Break high-level requirements into lower-level derived requirements.

**Functional Decomposition (Systems Engineering):**
- **Top-down decomposition**: Start from system-level requirements and recursively decompose into subsystem, component, and unit requirements.
- **Function-means trees**: Map high-level functions to the means of achieving them, creating a hierarchy.
- **Goal-oriented decomposition**: AND/OR decomposition of goals into subgoals (Mylopoulos et al.).
  - AND-decomposition: All children must be satisfied.
  - OR-decomposition: At least one child must be satisfied.

**Specification Decomposition for Reactive Synthesis (Springer, 2022):**
- Formal algorithm that **automatically decomposes specifications into smaller subspecifications**.
- Sound and complete modular synthesis that preserves semantic equivalence.
- Key insight: Decomposed subspecifications can be independently verified, then composed.

**LLM-Based Decomposition:**
- Using task decomposition frameworks (e.g., COLA multi-agent framework) to break complex specifications into manageable units.
- Intent extraction through decomposition: Small models can achieve big results when tasks are decomposed into stages.

**INCOSE Decomposition Guidelines (v4 Summary):**
- Requirements must be: Singular (one requirement per statement), Traceable (linked to parent), Verifiable (testable in isolation).
- Derivation: Creating child requirements that collectively satisfy the parent requirement.
- Allocation: Assigning requirements to specific system components or subsystems.

### Strengths and Limitations

| Technique | Strengths | Limitations |
|-----------|-----------|-------------|
| Manual INCOSE rules | Industry standard, well-understood | Labor-intensive, subjective |
| AND/OR goal decomposition | Formal, preserves semantics | Requires formal specification |
| LLM-based decomposition | Fast, handles NL directly | May lose nuance, hallucinate sub-requirements |
| Modular synthesis | Sound and complete, provably correct | Limited to reactive/formal specs |

### Application to LLM-Based Spec Management

- **Automated atomicity checking**: Use LLM to detect compound requirements (look for conjunction patterns, multiple verbs, multiple conditions).
- **Guided decomposition**: LLM proposes decomposition, human validates that no information is lost.
- **Bidirectional linking**: Every derived requirement must link back to its parent, with an explanation of the derivation relationship.
- **Lossless decomposition verification**: After decomposition, recombine child requirements and check semantic equivalence with the parent (using embedding similarity or LLM verification).
- **Decomposition depth limits**: Set maximum decomposition levels to prevent over-fragmentation.

---

## 4. Drift Detection

### Key Algorithms and Techniques

**Architecture Drift Analysis (ScienceDirect, 2024):**
- Detects when implemented code diverges from documented software architecture.
- Uses **model-driven development and domain-specific languages** to analyze architectural views.
- Compares multiple architectural views (structural, behavioral, deployment) against code artifacts.
- Key finding: Multi-view analysis catches drift that single-view analysis misses.

**Spec-Driven Development (SDD) Drift Prevention (arXiv, 2026):**
- Three levels of specification rigor:
  1. **Spec-first**: Write specs before code, use for guidance.
  2. **Spec-anchored**: Specs are the source of truth, tests derived from specs.
  3. **Spec-as-source**: Code is generated from specs, specs ARE the program.
- Automated checks (typically test-based) ensure spec and code remain aligned.
- If they drift, tests fail, providing immediate feedback.

**Schema Drift Detection (Specmatic, 2025):**
- Detects mismatches between declared schemas and actual implementations.
- Generates tests automatically based on declared input-output schemas.
- Performs **resiliency testing** to explore varied input combinations.
- Integrates into CI pipelines for continuous drift detection.

**Configuration Drift Detection (IaC domain):**
- Compares desired state (specification) with actual state (infrastructure).
- Algorithms: State hashing, tree-diff algorithms, property-by-property comparison.
- Tools: Terraform plan, CloudFormation drift detection, Ansible --check mode.

**Statistical Drift Detection (ML domain -- transferable concepts):**
- **Kolmogorov-Smirnov test**: Tests whether two distributions differ significantly.
- **Population Stability Index (PSI)**: Measures how much a distribution has shifted.
- **Page-Hinkley test**: Sequential change detection for streaming data.
- **ADWIN (Adaptive Windowing)**: Automatically adjusts window size to detect distribution changes.
- These statistical methods can be adapted for detecting semantic drift in spec-implementation alignment.

### Strengths and Limitations

| Technique | Strengths | Limitations |
|-----------|-----------|-------------|
| Architecture view analysis | Multi-dimensional, catches subtle drift | Requires formal architecture docs |
| Test-derived-from-spec | Immediate feedback, CI-integrated | Only catches drift covered by tests |
| Schema comparison | Precise, deterministic | Only works for structured schemas |
| Statistical methods | Principled, handles noise | Need numerical representation of drift |

### Application to LLM-Based Spec Management

- **Spec-to-code semantic comparison**: Embed both spec units and corresponding code, track embedding distance over time. Alert when distance exceeds threshold.
- **Continuous reconciliation**: Periodically use LLM to compare spec text against current code implementation and flag discrepancies.
- **Drift scoring**: Compute per-unit drift scores combining multiple signals (test coverage, embedding distance, last-verified timestamp, code change frequency).
- **Proactive drift alerts**: When code changes are detected in files associated with spec units, automatically trigger a drift check.
- **Temporal drift tracking**: Maintain a time series of spec-implementation alignment scores to detect gradual drift trends.

---

## 5. Overlap and Redundancy Detection

### Key Algorithms and Techniques

**PassionNet Framework (Expert Systems with Applications, 2025):**
- Innovative framework for **duplicate and conflicting requirements identification**.
- Integrates a similarity computation module that assesses **semantic, lexical, structural, and logical dimensions simultaneously**.
- Uses hybrid predictive pipelines with automated design.
- Achieves notable F1-score enhancements over existing approaches across multiple datasets.
- Key insight: Multi-dimensional similarity (not just text similarity) is needed for accurate duplicate detection.

**SR-BERT: Transfer Learning for Conflict and Duplicate Detection (2023):**
- Formulates conflict and duplicate detection as a **requirement pair classification task**.
- Uses transformer-based framework with domain adaptation strategies.
- Implements **sequence multi-stage fine-tuning** for cross-domain transfer.
- Rule-based post-processing refinements reduce false positives.
- High precision and recall, especially with larger datasets.

**Semantic Pruning (IJRASET, 2025):**
- NLP approach for redundancy identification in software requirement specifications.
- Compares multiple methods: CountVectorizer, TF-IDF, Word2Vec, and BERT.
- Results: BERT achieves best F1-score (0.87) and recall (0.77) for redundancy detection.
- Trade-off: BERT runtime is significantly longer than simpler methods.

**Requirements Similarity Analysis (Abbas et al., 2023):**
- Comprehensive comparison of NLP approaches from lexical to deep-learning.
- Evaluated: TF-IDF, FastText, Doc2Vec, Word2Vec, Universal Sentence Encoder, BERT.
- Finding: **BERT with preprocessing outperforms all other models** for correlation between requirements similarity and software similarity.
- Practical insight: Requirements similarity is a reliable (moderate correlation) proxy for software similarity, useful for reuse detection.

**LLM-Based Redundancy Detection (2024):**
- Using LLMs with the "Recipe Pattern" prompt to detect redundant requirements.
- Demonstrated on ISS collision avoidance requirements.
- Can also detect missing requirements alongside redundancies.
- Approach: Prompt LLM to analyze full requirement set and identify semantically overlapping entries.

### Strengths and Limitations

| Technique | Strengths | Limitations |
|-----------|-----------|-------------|
| TF-IDF cosine similarity | Fast, simple baseline | Misses semantic overlap |
| BERT embeddings | Best accuracy, captures semantics | Slow, expensive |
| PassionNet multi-dimensional | Catches structural/logical overlap | Complex pipeline |
| SR-BERT transfer learning | Works across domains | Needs initial fine-tuning data |
| LLM prompting | Flexible, explains overlaps | Expensive at scale, non-deterministic |

### Application to LLM-Based Spec Management

- **Tiered similarity detection**:
  1. Fast pass with sentence-transformer embeddings (cosine > 0.85 threshold).
  2. BERT pairwise comparison for borderline cases (0.65-0.85).
  3. LLM adjudication for identified candidates (with explanation).
- **Overlap types to detect**: Exact duplicates, semantic duplicates, partial overlaps, conflicting requirements, subsumption (one requirement contains another).
- **Merge recommendations**: When overlap is detected, suggest consolidated requirements that preserve all information from both.
- **Overlap graph**: Build a graph where edges represent similarity scores between requirement pairs, enabling cluster analysis.

---

## 6. Fact Extraction from Natural Language

### Key Algorithms and Techniques

**LLM-Based Formal Specification Extraction (arXiv, 2025):**
- Evaluated GPT-4o and Claude-3.5 for extracting formal specifications from software documents.
- End-to-end accuracy: Up to **51.7%** -- highlighting fundamental challenges.
- Key problems: **Oversimplification of complex requirements** and **fabrication of non-existent specifications** (hallucination).
- Novel **two-stage annotation-then-conversion method**:
  1. Stage 1 -- Annotation: LLM annotates natural language text to identify specification-relevant segments.
  2. Stage 2 -- Conversion: Annotated segments are converted to formal specifications.
  - Improved extraction accuracy by **14.0%** and increased correct extraction rate by **29.2%**.
- Key insight: Separating identification from conversion dramatically improves reliability.

**LLM Protocol Specification Extraction (SIGCOMM HotNets, 2023):**
- Uses GPT-3.5-turbo to extract protocol specifications from RFC documents.
- Focuses on extracting state machines, message formats, and constraints.
- Demonstrates feasibility but highlights accuracy limitations.

**Classical NLP Information Extraction Pipeline:**
1. **Named Entity Recognition (NER)**: Identify actors, systems, data entities, constraints.
2. **Relation Extraction**: Identify relationships between entities (requires, depends-on, produces).
3. **Event Extraction**: Identify actions, triggers, and conditions.
4. **Coreference Resolution**: Link pronouns and references to their antecedents.

**Knowledge Graph Construction from Requirements:**
- LLM-empowered knowledge graph construction has reached **production maturity in 2024-2025** (300-320% ROI reported).
- Approach: Extract (entity, relation, entity) triples from requirements text.
- LlamaIndex Property Graph Index provides structured extraction pipelines.
- Enables reasoning over requirement relationships through graph traversal.

**Domain-Specific Extraction:**
- **Glossary extraction**: Automated extraction and clustering of requirements glossary terms (Arora et al., 2016).
- **Use case extraction**: Identifying use case scenarios from textual requirements (Tiwari et al., 2019).
- **User story extraction**: CASPAR system extracts and synthesizes user stories from app reviews (Guo & Singh, 2020).

### Strengths and Limitations

| Technique | Strengths | Limitations |
|-----------|-----------|-------------|
| Two-stage LLM extraction | Separates concerns, higher accuracy | Still only ~65% accuracy, expensive |
| Classical NER pipeline | Mature, well-understood | Misses complex relationships |
| Knowledge graph construction | Enables reasoning, queryable | Complex to maintain, schema drift |
| Domain-specific extraction | High precision for specific patterns | Narrow applicability |

### Application to LLM-Based Spec Management

- **Two-stage extraction pipeline**: First annotate/highlight relevant text, then extract structured facts. This aligns well with the spec decomposition workflow.
- **Structured fact schema**: Define a standard schema for extracted facts:
  ```
  {
    "actors": [...],
    "actions": [...],
    "conditions": [...],
    "constraints": [...],
    "data_entities": [...],
    "relationships": [...]
  }
  ```
- **Confidence scoring**: Assign confidence scores to extracted facts; low-confidence extractions are flagged for human review.
- **Lossless extraction strategy**: Maintain original text alongside extracted facts. The structured facts are an index into the original text, not a replacement.
- **Cross-reference extraction**: Extract references between requirements (implicit and explicit) to build the dependency graph.

---

## 7. Provenance Tracking

### Key Algorithms and Techniques

**W3C PROV Standard:**
- The W3C PROV family of specifications is the de facto standard for provenance representation.
- Core model concepts:
  - **Entity**: A thing (e.g., a requirement, a spec unit).
  - **Activity**: A process that transforms entities (e.g., decomposition, refinement).
  - **Agent**: Actor responsible for the activity (e.g., human analyst, LLM, automated tool).
- Key relations: `wasGeneratedBy`, `wasDerivedFrom`, `wasAttributedTo`, `used`, `wasAssociatedWith`.
- **PROV-O**: OWL2 ontology for Linked Data / Semantic Web provenance.

**Data Lineage Patterns:**
- **Forward lineage**: Track where data goes (entity -> derived entities).
- **Backward lineage**: Track where data came from (entity -> source entities).
- **Complete lineage**: Full DAG of transformations from source to current state.
- Lineage granularity levels: Document-level, section-level, requirement-level, fact-level.

**Software Provenance (JFrog, 2025):**
- Full record of a software component's origin, changes, and development.
- SBOM (Software Bill of Materials) as a provenance artifact.
- Supply chain provenance: SLSA framework levels for build provenance.
- Applicable pattern: Track the "supply chain" of requirements from source through transformations.

**Provenance in Data Spaces (DSSC, 2025):**
- Building blocks for observability, provenance, traceability, logging, and audits.
- Standardized manner for recording who did what, when, why, and how.
- Emphasis on machine-readable provenance records.

**Immutable Audit Logs:**
- Append-only logs recording every transformation.
- Merkle trees / hash chains for tamper-evident provenance records.
- Git-style content-addressable storage for provenance DAGs.

### Strengths and Limitations

| Technique | Strengths | Limitations |
|-----------|-----------|-------------|
| W3C PROV | Standard, interoperable, well-defined | Complex for simple use cases |
| Data lineage DAGs | Intuitive, queryable | Can grow very large |
| Git-style hashing | Tamper-evident, content-addressable | Storage overhead |
| SBOM-style tracking | Industry standard for supply chains | Focused on artifacts, not semantics |

### Application to LLM-Based Spec Management

- **Requirements PROV model**: Every spec unit should record:
  - `wasDerivedFrom`: Parent requirement or source document.
  - `wasGeneratedBy`: The decomposition/refinement activity.
  - `wasAttributedTo`: The agent (human, LLM, tool) that created it.
  - `generatedAtTime`: Timestamp.
  - `usedPrompt`: For LLM-generated content, record the prompt used (prompt provenance).
- **Transformation chain**: Record every transformation step:
  ```
  SourceDoc -> (ingest) -> RawSpec -> (decompose) -> Units[] -> (refine) -> RefinedUnits[]
  ```
- **LLM-specific provenance**: Track model version, temperature, prompt, and response for every LLM interaction that modifies specs.
- **Diff-based tracking**: Store deltas (diffs) between versions rather than full copies for efficiency.
- **Provenance queries**: Enable queries like "What was the original source of this requirement?" and "What changed between v1 and v2 of this spec unit?"

---

## 8. Verification and Validation of Requirements

### Key Algorithms and Techniques

**Formal Verification Methods:**
- **Model Checking**: Exhaustive state-space exploration to verify properties against a system model.
  - Specification languages: PSL, CTL, LTL (temporal logics).
  - Tools: SPIN, NuSMV, CBMC.
  - Works well for finite-state systems but suffers from state explosion.
- **Deductive Verification**: Uses theorem proving to verify that code satisfies specifications.
  - Specification languages: ACSL (for C), JML (for Java).
  - Tools: Frama-C, KeY.
  - Complete but requires formal specification writing expertise.
- **Counterexample-Guided Abstraction Refinement (CEGAR)**: Iteratively refines abstractions using counterexamples.

**Automated Formal Verification (AUFOVER -- Red Hat/Honeywell):**
- Automates detection of software defects in safety-critical C/C++ code.
- Key innovation: Aggregates results from multiple formal tools to enhance defect detection.
- Includes **semantic analysis of requirements** as part of the verification pipeline.
- Goal: Integrate formal tools into normal development workflows (not just safety-critical).

**Requirements-Level V&V Techniques:**
1. **Test case generation**: Derive test cases from requirements to verify implementability.
2. **Prototyping**: Build quick prototypes to validate requirements with stakeholders.
3. **Requirements reviews / inspections**: Structured peer review processes.
4. **Automated consistency analysis**: Check requirements set for internal consistency.
5. **Walk-throughs**: Step through requirements with stakeholders.
6. **Simulation-based validation**: Use Simulink or similar to validate requirements via simulation (MathWorks approach).

**LLM-Based Verification (2025):**
- LLMs show promise for automated requirements verification but have limitations:
  - **Over-correction bias**: Tendency to flag correct requirements as problematic.
  - **Performance drops under complexity**: Verification accuracy degrades for complex, interconnected requirements.
- Multi-agent verification strategies improve accuracy.
- Best used as a "second pair of eyes" with human oversight.

**Specification Property Checking:**
- **Completeness**: Are all scenarios covered? (Missing requirements detection)
- **Consistency**: Do any requirements contradict each other?
- **Feasibility**: Can all requirements be implemented given constraints?
- **Traceability**: Can every requirement be traced to a source and a verification method?
- **Unambiguity**: Does each requirement have exactly one interpretation?

### Strengths and Limitations

| Technique | Strengths | Limitations |
|-----------|-----------|-------------|
| Model checking | Exhaustive, finds all violations | State explosion, needs formal specs |
| Deductive verification | Complete proofs | Expert-intensive, high overhead |
| LLM-based V&V | Flexible, handles NL, fast | Over-correction, hallucination, unreliable for critical systems |
| Test case generation | Practical, validates implementability | Only validates what's tested |
| Simulation-based | Visual, stakeholder-friendly | Expensive to set up |

### Application to LLM-Based Spec Management

- **Automated quality gates**: Before a spec unit is marked "approved", it must pass:
  1. INCOSE quality criteria checks (rule-based).
  2. Ambiguity detection (NLP-based).
  3. Atomicity verification (LLM-based).
  4. Consistency check against existing units (embedding + LLM).
  5. Traceability completeness check (graph-based).
- **Testability scoring**: For each spec unit, generate candidate test cases using LLM. If test cases cannot be generated, the requirement is likely untestable.
- **Cross-validation**: Use multiple LLM passes with different prompts to verify requirements. Agreement between passes increases confidence.
- **Formal-informal bridge**: Extract checkable assertions from NL requirements using the two-stage extraction method, then verify assertions formally.

---

## 9. Cross-Cutting Themes and Synthesis

### Theme 1: The Rise of LLMs in Requirements Engineering

The period 2024-2025 represents a paradigm shift. LLMs are being applied to every stage of requirements engineering:
- **Elicitation**: LLMs outperform humans in completeness and alignment.
- **Specification**: 60-70% reduction in drafting time.
- **Traceability**: TraceLLM achieves SOTA without fine-tuning.
- **Quality**: Automated ambiguity detection and repair.
- **Verification**: Multi-agent verification strategies.

**Key caveat**: LLMs introduce new failure modes (hallucination, over-correction, non-determinism) that require **human oversight and ensemble methods**.

### Theme 2: Embedding-Based Similarity is the Universal Substrate

Nearly every technique surveyed relies on some form of semantic similarity computation:
- Traceability: Embedding distance between requirements and code.
- Redundancy detection: Cosine similarity between requirement embeddings.
- Drift detection: Tracking embedding distance over time.
- Classification: Using embeddings as features for ML classifiers.

**BERT with domain-specific preprocessing consistently outperforms other embedding methods** across multiple studies (Abbas et al., Semantic Pruning study, SR-BERT).

**Recommendation**: Build a shared embedding infrastructure that serves all spec management functions.

### Theme 3: Multi-Stage Pipelines Beat Single-Pass Approaches

The most successful approaches decompose complex tasks into stages:
- Fact extraction: Annotate first, then convert (14% accuracy improvement).
- Traceability: Candidate retrieval first, then verification.
- Redundancy: Fast screening first, then deep analysis.
- Quality checking: Rule-based first, then ML, then LLM.

**Recommendation**: Design the spec management system as a pipeline of increasingly sophisticated (and expensive) analysis stages.

### Theme 4: Provenance is Non-Negotiable

Every transformation of a requirement must be tracked:
- W3C PROV provides the standard data model.
- Git provides the operational paradigm (content-addressable, append-only, DAG).
- LLM interactions require special provenance tracking (prompt, model, parameters).

**Recommendation**: Build provenance tracking into the core data model, not as an afterthought.

### Theme 5: Formal Methods and NL Methods are Converging

The two-stage approach (NL -> annotation -> formal spec) bridges the gap:
- NL requirements are accessible to stakeholders.
- Formal specifications enable automated verification.
- LLMs can serve as the bridge, translating between representations.

**Recommendation**: Maintain NL as the primary representation but extract formal checkable assertions for automated verification.

---

## Novel Approaches from 2024-2025

1. **TraceLLM (2025)**: Systematic prompt engineering for SOTA traceability without fine-tuning.
2. **PassionNet (2025)**: Multi-dimensional similarity for duplicate/conflict detection.
3. **Automated Ambiguity Repair (2025)**: Moving beyond detection to automated fix generation.
4. **Two-stage LLM Specification Extraction (2025)**: Annotation-then-conversion for reliable fact extraction.
5. **SR-BERT (2023-2024)**: Transfer learning across requirement domains for conflict detection.
6. **Semantic Pruning with BERT (2025)**: Transformer-based redundancy identification in SRS.
7. **Spec-Driven Development (2026)**: Three-level rigor framework for spec-code alignment.
8. **Specmatic MCP Auto-Test (2025)**: Automated schema drift detection with resiliency testing.
9. **LLM Recipe Pattern for Gap Analysis (2024)**: Using structured prompts to find missing/redundant requirements.
10. **LLM-empowered Knowledge Graphs (2024-2025)**: Production-ready extraction of structured knowledge from requirements.

---

## Recommended Architecture for an LLM-Based Spec Management System

Based on this research, the optimal architecture combines:

```
Input Documents
     |
     v
[Stage 1: Ingestion & Extraction]
  - Two-stage LLM extraction (annotate, then convert)
  - Confidence scoring per extracted fact
  - Original text preserved alongside structured facts
     |
     v
[Stage 2: Decomposition]
  - Atomicity checking (INCOSE criteria + LLM)
  - AND/OR goal decomposition
  - Parent-child linking with derivation rationale
  - Lossless verification (semantic equivalence check)
     |
     v
[Stage 3: Quality Analysis]
  - Rule-based INCOSE quality checks (fast)
  - NLP ambiguity/completeness detection (medium)
  - LLM deep analysis for flagged items (slow, accurate)
  - Quality scores per dimension
     |
     v
[Stage 4: Overlap & Consistency]
  - Embedding-based similarity screening (fast)
  - BERT pairwise comparison for candidates
  - LLM adjudication with explanations
  - Conflict graph construction
     |
     v
[Stage 5: Traceability]
  - Bidirectional trace links (requirements <-> code)
  - TraceLLM-style prompt engineering for link recovery
  - Incremental trace updates on changes
     |
     v
[Stage 6: Drift Monitoring]
  - Continuous spec-code alignment scoring
  - Change-triggered drift checks
  - Temporal drift trend analysis
     |
     v
[Stage 7: Provenance & Audit]
  - W3C PROV-compatible transformation records
  - Git-style content addressing
  - Full LLM interaction provenance
  - Queryable lineage DAG
```

Each stage feeds the next, with provenance tracking woven throughout.

---

## Key References

1. TraceLLM -- arXiv:2602.01253 (2025)
2. Rosado da Cruz & Cruz, "ML Techniques for RE" -- MDPI Software (2025)
3. PassionNet -- Expert Systems with Applications (2025)
4. Semantic Pruning -- IJRASET (2025)
5. Abbas et al., "Similar Requirements and Similar Software" -- Requirements Engineering (2023)
6. SR-BERT -- arXiv:2301.03709 (2023)
7. LLM Formal Specification Extraction -- arXiv:2504.01294 (2025)
8. Spec-Driven Development -- arXiv:2602.00180 (2026)
9. INCOSE Guide to Writing Requirements v4 (2023)
10. W3C PROV Ontology -- https://www.w3.org/TR/prov-o/
11. Specmatic MCP Auto-Test (2025)
12. AUFOVER Automated Formal Verification -- Red Hat/Honeywell
13. VIBE Ambiguity Detection -- Science Direct (2022)
14. Automated Repair of Ambiguous Requirements -- arXiv:2505.07270 (2025)
15. LLMs in Requirements Engineering -- Emergent Mind (2025)
