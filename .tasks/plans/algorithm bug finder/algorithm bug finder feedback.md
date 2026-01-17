# Algorithm Bug Finder

## Purpose

Detects constraint violations in distributed algorithms by analyzing the decorated
graph from the [Algorithm Graph Creator](../algorithm%20graph%20creator/feedback.md).
This system finds bugs through **invariant collision detection**—identifying
mismatches between what components expect and what they receive.

This is a **verification tool**, not an enhancement tool. It answers: "Is the
algorithm internally consistent with its declared constraints?"

---

## Input

The bug finder consumes a `DecoratedGraph` from the graph creator, which contains:

* Nodes with active invariants and inherited obligations
* Surfaces with expectations, guarantees, and barrier analysis
* Leakage analysis for each boundary

---

## Violation Types

### Type 1: Expectation/Guarantee Mismatch

A caller expects something that the callee does not guarantee.

### ExpectationViolation

* The surface where mismatch occurred
* The caller and callee involved
* The set of unmet expectations

**Detection Flow:**

```mermaid
flowchart LR
    Start([For each Surface]) --> Check
    subgraph Check[Mismatch Detection]
        A{Unmet expectations?}
    end
    A -->|Non-empty| violation
    A -->|Empty| C[Continue]
    subgraph violation[Violation Handling]
        direction LR
        B[Create Violation]:::error --> D[Add to list]
    end
    D --> C

    classDef error fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
    style Check fill:#3b82f6,stroke:#1e40af,color:#ffffff
    style violation fill:#ef4444,stroke:#b91c1c,color:#ffffff
```

**Example:**

```mermaid
flowchart TB
    subgraph caller[Caller]
        COM14["COM-14 (Orchestrator)"]:::orchestrator
        EXP["expects: INV-DETERMINISTIC"]:::expect
    end
    subgraph callee[Callee]
        COM05["COM-05"]:::component
        GUAR["guarantees: {INV-ORDERED}"]:::guarantee
    end

    COM14 -->|"CON-05"| COM05
    COM14 ~~~ EXP
    COM05 ~~~ GUAR

    classDef orchestrator fill:#dbeafe,stroke:#1e40af,stroke-width:2px,color:#1e3a8a
    classDef component fill:#fee2e2,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d
    classDef expect fill:#fef3c7,stroke:#d97706,color:#92400e
    classDef guarantee fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
    style caller fill:#3b82f6,stroke:#1e40af,color:#ffffff
    style callee fill:#ef4444,stroke:#b91c1c,color:#ffffff

    linkStyle 0 stroke:#b91c1c,stroke-width:2px
```

> **VIOLATION:** COM-14 expects `INV-DETERMINISTIC` from COM-05 via CON-05, but
> COM-05 does not guarantee it.

---

### Type 2: Unsatisfied Obligation Leakage

An obligation from a leaf component bubbles up without ever being satisfied.

### ObligationLeakageViolation

* The unsatisfied obligation
* Where it originated
* How far up it leaked (root = critical)
* The path of surfaces it passed through

**Detection Flow:**

```mermaid
flowchart LR
    A([For each Node]):::iterator --> B{Root?}
    B -->|No| C([Continue]):::continue
    B -->|Yes| obligations
    subgraph obligations[Obligation Check]
        direction LR
        D([Start]):::start --> E{Has inherited<br>obligations?}
        E -->|Yes| F[Find origin]:::process --> G[Create Violation]:::error --> H[Add to list]
    end
    E -->|No| C
    H --> C

    classDef iterator fill:#e0e7ff,stroke:#4338ca,color:#312e81
    classDef start fill:#dcfce7,stroke:#15803d,color:#14532d
    classDef process fill:#ffedd5,stroke:#c2410c,color:#7c2d12
    classDef error fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
    classDef continue fill:#f3f4f6,stroke:#4b5563,color:#1f2937
    style obligations fill:#d97706,stroke:#92400e,stroke-width:2px,color:#ffffff
```

**Example:**

```mermaid
flowchart LR
    subgraph leakage[Obligation Leakage Path]
        direction LR
        subgraph origin[Origin]
            COM99["COM-99"]:::component
            INV99["INV-STORES-FILE-REGISTRY"]:::invariant
        end
        subgraph propagation[Propagation]
            COM05["COM-05"]:::inherit
        end
        subgraph root[Root - Critical!]
            COM14["COM-14 (ROOT)"]:::critical
        end
    end

    COM99 -.->|"state invariant"| INV99
    COM99 -->|"EXE-OBL-SEQUENTIAL"| COM05
    COM05 -.->|"not satisfied"| COM14
    COM14 -.->|"Not Satisfied"| BOOM["💥 VIOLATION"]:::violation

    classDef component fill:#dbeafe,stroke:#1e40af,stroke-width:2px,color:#1e3a8a
    classDef invariant fill:#e0e7ff,stroke:#4338ca,color:#312e81
    classDef inherit fill:#fef3c7,stroke:#d97706,color:#92400e
    classDef critical fill:#fee2e2,stroke:#b91c1c,stroke-width:3px,color:#7f1d1d
    classDef violation fill:#b91c1c,stroke:#7f1d1d,stroke-width:3px,color:#ffffff

    style origin fill:#3b82f6,stroke:#1e40af,color:#ffffff
    style propagation fill:#d97706,stroke:#92400e,color:#ffffff
    style root fill:#ef4444,stroke:#b91c1c,stroke-width:2px,color:#ffffff
    style leakage fill:#6b7280,stroke:#4b5563,color:#ffffff

    linkStyle 1,2 stroke:#b91c1c,stroke-width:2px,stroke-dasharray:5
```

> **VIOLATION:** `EXE-OBL-SEQUENTIAL` from COM-99 (which has invariant
> INV-STORES-FILE-REGISTRY) leaked to root COM-14. No component in the path
> provides serialization.

---

### Type 3: Execution Invariant/Obligation Conflict

An execution invariant from the calling context conflicts with an execution
obligation from a component (often one with state storage invariants).

### ExecutionConflict

* The execution invariant (top-down, e.g., EXE-INV-PARALLEL)
* The execution obligation (bottom-up, e.g., EXE-OBL-SEQUENTIAL)
* Where the conflict occurs
* Sources of both the invariant and obligation

**Detection Flow:**

```mermaid
flowchart LR
    Start([For each Node]):::iterator --> ForInv([For each invariant]):::iterator
    ForInv --> detection
    subgraph detection[Conflict Detection]
        direction LR
        A[Lookup rules]:::lookup --> B{Conflicts?}
    end
    B -->|Yes| collision
    B -->|No| C([Continue]):::continue
    subgraph collision[Conflict Handling]
        D[Create ExecutionConflict]:::error
    end
    D --> C

    classDef iterator fill:#e0e7ff,stroke:#4338ca,color:#312e81
    classDef lookup fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
    classDef error fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
    classDef continue fill:#f3f4f6,stroke:#4b5563,color:#1f2937

    style detection fill:#3b82f6,stroke:#1e40af,stroke-width:2px,color:#ffffff
    style collision fill:#ef4444,stroke:#b91c1c,stroke-width:2px,color:#ffffff
```

**Example:**

```mermaid
flowchart TB
    subgraph context[Execution Invariant Flow ⬇]
        direction TB
        COM14["COM-14"]:::source
        SET["EXE-INV-05 (Parallel)"]:::exeinv
        COM05["COM-05"]:::collision
        ACTIVE["{EXE-INV-05}"]:::exeinv
    end
    subgraph state[State Boundary ⬆]
        COM99["COM-99"]:::statecomponent
        INV99["INV-STORES-REGISTRY"]:::stateinvariant
        OBL["EXE-OBL-20 (Sequential)"]:::exeobl
    end

    COM14 -->|"declares"| SET
    COM14 -->|"passes through"| COM05
    COM05 -->|"inherits"| ACTIVE
    COM05 ==>|"touches"| COM99
    COM99 -.->|"has invariant"| INV99
    COM99 -->|"declares"| OBL

    classDef source fill:#dbeafe,stroke:#1e40af,stroke-width:2px,color:#1e3a8a
    classDef exeinv fill:#bfdbfe,stroke:#1e40af,color:#1e3a8a
    classDef collision fill:#fee2e2,stroke:#b91c1c,stroke-width:3px,color:#7f1d1d
    classDef statecomponent fill:#dcfce7,stroke:#15803d,stroke-width:2px,color:#14532d
    classDef stateinvariant fill:#bbf7d0,stroke:#15803d,color:#14532d
    classDef exeobl fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d

    style context fill:#3b82f6,stroke:#1e40af,stroke-width:2px,color:#ffffff
    style state fill:#22c55e,stroke:#15803d,stroke-width:2px,color:#ffffff

    linkStyle 3 stroke:#b91c1c,stroke-width:3px
```

> **CONFLICT at COM-05:**
>
> * **Execution Invariant:** EXE-INV-05 (Parallel) from COM-14
> * **Execution Obligation:** EXE-OBL-20 (Sequential) from COM-99 (state invariant
>   INV-STORES-REGISTRY)
> * These are incompatible—COM-05 must implement synchronization.

---

## The Execution Conflict Prompt

When a conflict is detected, generate a focused prompt for LLM analysis:

| Section | Content |
|---------|---------|
| 1: Operating Environment | Component X called by Y; Active Execution Invariants |
| 2: Deep State Boundary | Component X touches Z; Active Execution Obligations |
| 3: The Conflict | Running with invariants A but touching resource with obligations B |
| 4: Analysis Required | Real conflict; What mechanism needed; Where to implement |

---

## Conflict Rules

The bug finder needs rules defining which invariants conflict:

```mermaid
flowchart LR
    subgraph Concurrency["🔄 Concurrency Conflicts"]
        direction LR
        PAR["EXE-INV-PARALLEL"]:::exeinv -.->|conflicts| SER["EXE-OBL-SEQUENTIAL"]:::exeobl
        PAR -.->|conflicts| SW["EXE-OBL-ATOMIC"]:::exeobl
        ASYNC["EXE-INV-ASYNC"]:::exeinv -.->|conflicts| SYNC["EXE-OBL-SYNC"]:::exeobl
        ASYNC -.->|conflicts| BLOCK["OBL-BLOCKING-ALLOWED"]:::exeobl
    end

    subgraph Ordering["📋 Ordering Conflicts"]
        direction LR
        UNORD["INV-UNORDERED-OUTPUT"]:::exeinv -.->|conflicts| ORD["OBL-ORDERED-INPUT"]:::exeobl
    end

    subgraph State["💾 State Conflicts"]
        direction LR
        STATELESS["SET-STATELESS"]:::exeinv -.->|conflicts| STATEREQ["OBL-STATE-REQUIRED"]:::exeobl
    end

    subgraph Resource["🔌 Resource Conflicts"]
        direction LR
        UNBOUNDED["SET-UNBOUNDED-CONCURRENCY"]:::exeinv -.->|conflicts| LIMITED["OBL-LIMITED-CONNECTIONS"]:::exeobl
    end

    classDef exeinv fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
    classDef exeobl fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d

    style Concurrency fill:#6366f1,stroke:#4338ca,stroke-width:2px,color:#ffffff
    style Ordering fill:#f59e0b,stroke:#d97706,stroke-width:2px,color:#ffffff
    style State fill:#22c55e,stroke:#15803d,stroke-width:2px,color:#ffffff
    style Resource fill:#ec4899,stroke:#be185d,stroke-width:2px,color:#ffffff
```

### Option: LLM-Inferred Conflicts

When conflict rules aren't predefined:

```mermaid
flowchart LR
    subgraph inputs[📥 Inputs]
        direction TB
        InvA["Invariant A<br>+ definition"]:::invariant
        InvB["Invariant B<br>+ definition"]:::invariant
    end
    subgraph inference[🤖 Inference]
        LLM{{"LLM Analysis"}}:::llm
        Q["Can both be<br>satisfied?"]:::question
    end
    subgraph outputs[📤 Outcomes]
        direction TB
        CONFLICT["❌ CONFLICT"]:::error
        COMPATIBLE["✅ COMPATIBLE"]:::success
    end

    InvA --> LLM
    InvB --> LLM
    LLM --> Q
    Q -->|No| CONFLICT
    Q -->|Yes| COMPATIBLE

    classDef invariant fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
    classDef llm fill:#f3e8ff,stroke:#7c3aed,stroke-width:2px,color:#5b21b6
    classDef question fill:#ffedd5,stroke:#c2410c,color:#7c2d12
    classDef error fill:#fee2e2,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d
    classDef success fill:#dcfce7,stroke:#15803d,stroke-width:2px,color:#14532d

    style inputs fill:#3b82f6,stroke:#1e40af,stroke-width:2px,color:#ffffff
    style inference fill:#8b5cf6,stroke:#7c3aed,stroke-width:2px,color:#ffffff
    style outputs fill:#22c55e,stroke:#15803d,stroke-width:2px,color:#ffffff
```

---

## Surface Isolation Analysis

Beyond finding violations, analyze what each surface isolates:

### IsolationReport

* The surface being analyzed
* What is fully isolated (doesn't leak)
* Inward leakage (context entering interior)
* Outward leakage (demands escaping interior)

```mermaid
flowchart LR
    subgraph exterior[🌍 Exterior]
        Outside["Caller Context"]:::external
    end
    subgraph boundary[🛡️ Boundary]
        direction TB
        Surface{{"Surface"}}:::surface
        Isolated["✅ Fully Isolated"]:::isolated
    end
    subgraph interior[🏠 Interior]
        Inside["Interior State"]:::internal
    end

    Outside -->|"inward_leakage ➡️"| Surface
    Surface -->|"passes through"| Inside
    Inside -->|"⬅️ outward_leakage"| Surface
    Surface -->|"🚫 blocked"| Isolated

    classDef external fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
    classDef surface fill:#ffedd5,stroke:#c2410c,stroke-width:2px,color:#7c2d12
    classDef internal fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
    classDef isolated fill:#dcfce7,stroke:#15803d,stroke-width:2px,color:#14532d

    style exterior fill:#ef4444,stroke:#b91c1c,stroke-width:2px,color:#ffffff
    style boundary fill:#f97316,stroke:#c2410c,stroke-width:2px,color:#ffffff
    style interior fill:#3b82f6,stroke:#1e40af,stroke-width:2px,color:#ffffff

    linkStyle 0 stroke:#b91c1c,stroke-width:2px
    linkStyle 2 stroke:#b91c1c,stroke-width:2px
    linkStyle 3 stroke:#15803d,stroke-width:2px
```

**Use Case:** Understanding which components are truly isolated (safe to reason
about independently) vs. which are coupled through leaked constraints.

---

## Full Bug Finding Pipeline

```mermaid
flowchart LR
    subgraph input[📥 Input]
        Input[("DecoratedGraph")]:::data
    end
    subgraph processor[🔍 BugFinder]
        BF["BugFinder"]:::processor
    end
    subgraph analysis[⚙️ Analysis Methods]
        direction TB
        EV["find_expectation_violations"]:::method
        OL["find_obligation_leakages"]:::method
        CC["find_execution_conflicts"]:::method
        SA["analyze_all_surfaces"]:::method
    end
    subgraph output[📤 Output]
        Report[("BugReport")]:::report
    end

    Input --> BF
    BF --> EV & OL & CC & SA
    EV & OL & CC & SA --> Report

    classDef data fill:#dbeafe,stroke:#1e40af,stroke-width:2px,color:#1e3a8a
    classDef processor fill:#f3e8ff,stroke:#7c3aed,stroke-width:2px,color:#5b21b6
    classDef method fill:#ffedd5,stroke:#c2410c,color:#7c2d12
    classDef report fill:#fee2e2,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d

    style input fill:#3b82f6,stroke:#1e40af,stroke-width:2px,color:#ffffff
    style processor fill:#8b5cf6,stroke:#7c3aed,stroke-width:2px,color:#ffffff
    style analysis fill:#f97316,stroke:#c2410c,stroke-width:2px,color:#ffffff
    style output fill:#ef4444,stroke:#b91c1c,stroke-width:2px,color:#ffffff
```

**BugReport Methods:**

| Method | Description |
|--------|-------------|
| `to_markdown()` | Human-readable report |
| `get_critical()` | Root-leaked violations only |
| `get_by_component(id)` | Violations for specific component |

---

## Scope

The bug finder handles **correctness** (constraint violations).

The [Algorithm Enhancer](../algorithm%20enhancer/feedback.md) handles **quality** (performance, simplification, optimization).

These are complementary tools with distinct purposes:

| Tool | Question | Domain |
|------|----------|--------|
| Bug Finder | "Is this correct?" | Constraint satisfaction |
| Enhancer | "Can this be better?" | Performance, clarity, efficiency |

Note on "logic bugs": If behavior is incorrect, it violates some expectation—which
is an invariant. The system catches this through:

* **Inherited invariants** (from parents) vs **inferred behavior** (from code)
  mismatches
* Parent says "output must be sorted" → code produces unsorted → violation detected

Note on "missing constraints": The [Graph Creator](../algorithm%20graph%20creator/feedback.md)
infers implicit invariants from algorithm content. You don't have to manually
declare every invariant—the LLM expands the invariant set by analyzing what the
code actually assumes and requires.

The bug finder answers: "Given the constraints (declared + inferred + inherited),
is the system internally consistent?"
