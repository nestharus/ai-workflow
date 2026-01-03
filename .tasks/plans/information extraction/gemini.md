Here are the high-level components, algorithms, and rules for the Atomic Fact Extraction System.

### Part 1: Indexed Rule List

This section defines the unique identifiers for all Non-negotiable Invariants (INV), Validation Rules (VAL), and Operational Constraints (OPS). These IDs are referenced in the diagrams below to ensure every component and logic step traces back to the requirements.

#### **Category 1: Core Invariants (INV)**

| ID | Rule Name | Requirement Definition |
| --- | --- | --- |
| **INV-01** | **Byte-Exact Provenance** | Source text is the canonical input string. References are character offsets. Reconstruction must reproduce the exact original substring byte-for-byte. |
| **INV-02** | **No Semantic Classification** | Links between facts are untyped hypotheses. No forced ontology (e.g., "is-a") is permitted. |
| **INV-03** | **Incompleteness Expected** | Graphs are assumed incomplete. Incompleteness is surfaced only via reconstruction failure. |
| **INV-04** | **Span Lifecycle** | Spans transition from `ATTEMPTABLE`  `PROVEN` (threshold met) or `FAILED` (uncovered text remains). |
| **INV-05** | **Facts Explain, Don't Own** | Facts are latent explanations. Multiple facts can explain overlapping text. Facts do not "own" text. |
| **INV-06** | **Progress Test** | Failure classification is not attempted directly. Failures trigger **Anchoring**. If Anchoring fails (stalls), emit Clarification Question. |
| **INV-07** | **Anchoring Operation** | Uncovered text triggers: Entity Position Index query  Context Expansion  New Fact Extraction. |
| **INV-08** | **Island Join Failures** | Distinct failure where two `PROVEN` islands cannot be connected. Triggers specific "Island Join" Clarification Question. |
| **INV-09** | **No Illegal Fabrication** | Honest incompleteness (Entity Declarations) is preferred over fabricated triplets. Do not invent structure. |
| **INV-10** | **No Formal Proof Languages** | Validation is text-based formal reconstruction (Opus) + deterministic diff (Python), not Lean/Coq. |
| **INV-11** | **Derivability Principle** | Extraction is COMPLETE if base facts are sufficient to derive all implications. Exhaustive enumeration is not required. |
| **INV-12** | **Transitive Anchors** | Contextual conditions are deduplicated; facts under different conditions share transitive anchors. |

#### **Category 2: Grammar Validation Rules (VAL-G)**

*Enforced by NLTK (Deterministic Pre-Filter)*
| ID | Rule Name | Constraint |
| :--- | :--- | :--- |
| **VAL-G1** | **Hidden Copula** | Reject adding verbs (is/are) to noun phrases lacking finite verbs. |
| **VAL-G2** | **Attribute-to-Process** | Reject converting static adjectives to temporal verbs (e.g., "remains"). |
| **VAL-G3** | **Pronoun Concord** | Subject/Object/Pronoun agreement (number/gender/person) must match source. |
| **VAL-G4** | **Tense Fabrication** | Reject assigning tense to timeless/inherent property constructions. |
| **VAL-G5** | **Forced Subject** | Reject inventing entities to complete triplets for syntactic orphans. |

#### **Category 3: Inference Validation Rules (VAL-I)**

*Enforced by Opus (Logic/Reasoning Validation)*
| ID | Rule Name | Constraint |
| :--- | :--- | :--- |
| **VAL-I1** | **Coreference Consistency** | Inferred antecedents must agree in number/gender/person with the pronoun. |
| **VAL-I2** | **Logical Entailment** | Implications must logically follow from base facts (e.g., spatial containment). |
| **VAL-I3** | **Context Scope** | Inferences must not span unrelated document sections without markers. |
| **VAL-I4** | **Phantom Entities** | Inferred entities must exist in base facts or source text. |

#### **Category 4: Operational Constraints (OPS)**

| ID | Rule Name | Constraint |
| --- | --- | --- |
| **OPS-01** | **Local Execution** | No cloud dependencies. Local Python + Local Models + SQLite. |
| **OPS-02** | **Two-Phase Extraction** | Extraction is sequential: Phase 1 (Raw Details)  Phase 2 (Fact Construction). |
| **OPS-03** | **Dual Representation** | Facts have **Canonical Text** (normalized, for embedding) and **Source Context** (offsets, for reconstruction). |
| **OPS-04** | **Artifact Generation** | Failures generate structured artifacts (JSON), not just logs. |

---

### Part 2: High-Level Component Diagrams

#### Diagram 1: System Context & Architecture

This diagram outlines the local execution environment, the agent hierarchy (Claude Code Harness), and the data flow constraints.

```mermaid
graph TB
    subgraph "Local Execution Environment (Ref: OPS-01)"
        
        Input[("Input Documents")]
        
        subgraph "Orchestration Layer (Claude Code Harness)"
            Orchestrator["<b>Opus 4.5 Orchestrator</b><br/>Pipeline Management<br/>Reconstruction Proofs<br/>QA Validation<br/>(Ref: INV-01, INV-06, INV-10)"]
        end

        subgraph "Sub-Agent Layer (File I/O Communication)"
            Agent_Detail["<b>Haiku 4.5 (Sub-agent 1)</b><br/>Detail Extraction<br/>(Ref: OPS-02)"]
            Agent_Fact["<b>Haiku 4.5 (Sub-agent 2)</b><br/>Fact Construction<br/>Anchoring<br/>Deduplication<br/>(Ref: INV-09, INV-12)"]
        end

        subgraph "Validation & Tools Layer"
            NLTK["<b>NLTK Grammar Validator</b><br/>Deterministic Syntax Check<br/>(Ref: VAL-G1 to G5)"]
            InferenceEngine["<b>Inference Validation</b><br/>(Opus Logic Check)<br/>(Ref: VAL-I1 to I4)"]
            PyTools["<b>Python Tools</b><br/>String Diff<br/>Grammar Scaffolding<br/>Synonym Dict<br/>(Ref: INV-01, INV-10)"]
            EmbModel["<b>Qwen-3 Embedding (0.6B)</b><br/>Semantic Vectors<br/>(Ref: OPS-03)"]
        end

        subgraph "Storage Layer (Local)"
            CanonicalStr[("Canonical String<br/>(UTF-8)<br/>(Ref: INV-01)")]
            VectorDB[("SQLite + vss<br/>Vector Store<br/>(Ref: INV-05)")]
            EntityIndex[("Entity Position Index<br/>Spatial Lookup<br/>(Ref: INV-07)")]
            Artifacts[("Artifact Store<br/>Failures, CQs, Logs<br/>(Ref: OPS-04)")]
        end

    end

    Input --> Orchestrator
    Orchestrator --> CanonicalStr
    Orchestrator --> Agent_Detail
    Agent_Detail --> Agent_Fact
    Agent_Fact --> NLTK
    NLTK --> InferenceEngine
    InferenceEngine --> VectorDB
    Orchestrator --> PyTools
    PyTools --> Artifacts
    Agent_Fact --> EmbModel
    EmbModel --> VectorDB
    Agent_Fact --> EntityIndex
    EntityIndex --> Orchestrator

```

#### Diagram 2: Data Objects & State

This class diagram details the structure of Facts, Artifacts, and Spans, referencing the specific invariants they enforce.

```mermaid
classDiagram
    note "Ref: OPS-03, INV-05"
    class AtomicFact {
        +String ID
        +String CanonicalText
        +List~Range~ SourceContext
        +Vector Embedding
        +List~Link~ TransitiveAnchors (Ref: INV-12)
        +Enum Type (Base/Implied) (Ref: INV-11)
    }

    note "Ref: INV-06, INV-08"
    class ReconstructionFailure {
        +String SpanID
        +String OriginalText
        +String ReconstructedText
        +List~String~ UncoveredSubstrings
        +List~Fact~ FactsUsed
        +Object IslandJoinInfo (Ref: INV-08)
    }

    note "Ref: INV-07"
    class EntityPositionIndex {
        +String EntityText
        +List~Range~ Spans
        +Method FindNearest(offset)
    }

    note "Ref: INV-09, OPS-04"
    class FabricationAttempt {
        +String SourceText
        +Triplet AttemptedTriplet
        +Enum ViolationType (VAL-G1..G5)
        +String DetectionRule
    }
    
    note "Ref: INV-04"
    class SpanState {
        <<Enumeration>>
        ATTEMPTABLE
        PROVEN
        FAILED
    }

    AtomicFact --> EntityPositionIndex : Indexes Entities
    ReconstructionFailure --> AtomicFact : Uses
    ReconstructionFailure --> SpanState : Triggers FAILED
    FabricationAttempt --|> AtomicFact : Rejected Candidate

```

---

### Part 3: Algorithm Flowcharts

#### Algorithm 1: The Main Extraction Pipeline

This covers the outer loop of processing work regions, terminating only when the Derivability Principle (INV-11) is met.

```mermaid
flowchart TD
    Start([Start Pipeline]) --> Ingest[Ingest & Create Canonical String<br/>Ref: INV-01]
    Ingest --> InitRegions[Initialize Work Regions<br/>Set: ATTEMPTABLE<br/>Ref: INV-04]
    
    subgraph "Extraction Loop (Ref: OPS-02)"
        InitRegions --> CheckRegions{Unprocessed<br/>Regions?}
        CheckRegions -- Yes --> SelectRegion[Select Work Region]
        
        SelectRegion --> RunExtraction[["<b>Run Two-Phase Extraction</b><br/>(See Algo 2)"]]
        
        RunExtraction --> RunRecon[["<b>Run Reconstruction Proof</b><br/>(See Algo 3)"]]
        
        RunRecon -- "Span: PROVEN" --> CheckDeriv{Derivability Met?<br/>Ref: INV-11}
        CheckDeriv -- Yes --> MarkProcessed[Mark Region Processed]
        
        RunRecon -- "Span: FAILED" --> FailureHandler[["<b>Handle Failure/Anchoring</b><br/>(See Algo 4)"]]
        
        FailureHandler -- "New Facts Anchored" --> RunRecon
        FailureHandler -- "Clarification Emitted" --> MarkFailed[Mark Region FAILED<br/>Ref: INV-06]
        
        MarkFailed --> MarkProcessed
        MarkProcessed --> CheckRegions
    end
    
    CheckRegions -- No --> Dedupe[["<b>Deduplication</b><br/>(See Algo 5)"]]
    Dedupe --> End([End Pipeline])

```

#### Algorithm 2: Two-Phase Extraction & Validation

This details how Haiku sub-agents interact to produce candidate facts and how NLTK acts as a pre-filter.

```mermaid
flowchart TD
    Input([Input: Source Text Span])
    
    subgraph "Phase 1: Detail Extraction"
        Haiku1["Haiku 4.5 (Sub-agent 1)"]
        ExtractDetails["Extract Raw Observations/Claims<br/>(Not yet triplets)<br/>[Ref: OPS-02]"]
        WriteFile1["Write Details to File System"]
    end
    
    Input --> Haiku1 --> ExtractDetails --> WriteFile1
    
    subgraph "Phase 2: Fact Construction"
        ReadFile1["Read Details from File System"]
        Haiku2["Haiku 4.5 (Sub-agent 2)"]
        Anchor["Anchor Details to Source Offsets<br/>[Ref: INV-01, INV-05]"]
        FormTriplets["Form Subject-Predicate-Object"]
    end
    
    WriteFile1 --> ReadFile1 --> Haiku2 --> Anchor --> FormTriplets
    
    subgraph "Validation Pipeline"
        NLTK_Check{"NLTK Grammar Check<br/>[Ref: VAL-G1..G5]"}
        
        FormTriplets --> NLTK_Check
        
        NLTK_Check -- "Fail (Grammar)" --> LogFab["Log 'FabricationAttempt'<br/>Extract Entity Only<br/>[Ref: INV-09]"]
        
        NLTK_Check -- "Pass" --> TypeCheck{Is Implied Fact?}
        
        TypeCheck -- "No (Base Fact)" --> ValidFact
        TypeCheck -- "Yes" --> OpusCheck{Opus Inference Check<br/>[Ref: VAL-I1..I4]}
        
        OpusCheck -- "Fail (Logic)" --> LogInf["Log 'InvalidInferenceAttempt'"]
        OpusCheck -- "Pass" --> ValidFact
    end
    
    LogFab --> ValidFact([Return Candidate Facts])
    LogInf --> ValidFact

    style NLTK_Check fill:#ffccbc,stroke:#bf360c
    style OpusCheck fill:#fff9c4,stroke:#fbc02d

```

#### Algorithm 3: Reconstruction Proof & Inference Validation

This details the "Explanation Test" logic.

```mermaid
flowchart TD
    Input([Input: Target Span T_S + Candidate Facts])
    
    subgraph "Opus 4.5 Execution"
        GenProof["Generate Reconstruction Proof<br/>Logic: Derive T_S from Facts<br/>[Ref: INV-10]"]
        GenRecon["Generate Reconstructed Text R_S"]
        GenProof --> GenRecon
    end
    
    subgraph "Python Deterministic Tools"
        Diff["Byte-Exact Diff(T_S, R_S)<br/>[Ref: INV-01]"]
    end
    
    GenRecon --> Diff
    
    Result{"Uncovered Words Empty?"}
    Diff --> Result
    
    Result -- Yes --> Proven["Set Span State: PROVEN<br/>[Ref: INV-04, INV-11]"]
    Result -- No --> Failed["Set Span State: FAILED<br/>Log 'ReconstructionFailure'<br/>[Ref: INV-03]"]

    Proven --> Output([Return Result])
    Failed --> Output
    
    style Diff fill:#e1f5fe,stroke:#01579b

```

#### Algorithm 4: Failure Handling (Anchoring & Island Joins)

This details the "Progress Test" and how the system distinguishes between missing facts and structural failures.

```mermaid
flowchart TD
    Input([Input: ReconstructionFailure]) --> TypeCheck{Failure Type?}
    
    %% Path A: Island Join Failure
    TypeCheck -- "Islands Proven,<br/>Join Failed" --> IslandFail["Ref: INV-08<br/>Detect Island Join Failure"]
    IslandFail --> EmitCQ_Join["Emit Clarification Question:<br/>Island Join Failure"]
    EmitCQ_Join --> ReturnFail([Return: Failed])
    
    %% Path B: Unanchored Text
    TypeCheck -- "Unanchored<br/>Text" --> AnchorLoop["Start Anchoring Loop"]
    
    subgraph "Anchoring Operation [Ref: INV-07]"
        AnchorLoop --> PosQuery[Query Entity Position Index]
        PosQuery --> ContextExp[Expand Context around Uncovered]
        ContextExp --> NewExt[Extract New Facts (Call Algo 2)]
        
        NewExt --> ReRunRec[Re-Run Reconstruction]
        ReRunRec --> CheckProgress{Uncovered<br/>Reduced?<br/>Ref: INV-06}
        
        CheckProgress -- Yes --> LoopCheck{Max Attempts?}
        LoopCheck -- No --> AnchorLoop
    end
    
    LoopCheck -- Yes --> EmitCQ_Unanchored["Emit Clarification Question:<br/>Structural Failure<br/>[Ref: INV-06]"]
    CheckProgress -- No --> EmitCQ_Unanchored
    
    EmitCQ_Unanchored --> ReturnFail
    LoopCheck -- No --> ReturnSuccess([Return: New Facts Found])
    
    style AnchorLoop fill:#e1f5fe,stroke:#01579b
    style EmitCQ_Unanchored fill:#ffccbc,stroke:#bf360c

```

#### Algorithm 5: Deduplication Logic

This details the handling of duplicate facts, specifically preserving **Transitive Anchors** per Invariant 12.

```mermaid
flowchart TD
    Start([Input: Fact List]) --> ComputeEmbed[Compute Embeddings <br/> (Canonical Text Only) <br/> Ref: OPS-03]
    ComputeEmbed --> VectorIndex[Build/Update SQLite VSS]
    
    IterateFacts[Select Next Fact A] --> Query[Query Vector DB: <br/> Find Nearest Neighbors]
    Query --> Candidates[List Candidates]
    
    subgraph "Dedup Logic (Haiku 2)"
        Candidates --> Compare{Are Facts <br/> Semantically Identical?}
        
        Compare -- Yes --> CheckContext{Check Transitive Anchors <br/> [Ref: INV-12]}
        
        CheckContext -- Different Conditions --> MergeRef[Merge Content <br/> Keep Distinct Condition Links]
        CheckContext -- Same Conditions --> MergeFull[Consolidate to Fact A <br/> Remove Duplicate]
        
        Compare -- No --> Keep[Keep as Distinct Fact]
    end
    
    MergeRef --> UpdateDB[Update Vector DB & Graph]
    MergeFull --> UpdateDB
    Keep --> Next{More Facts?}
    UpdateDB --> Next
    
    Next -- Yes --> IterateFacts
    Next -- No --> End([End Dedup])

```