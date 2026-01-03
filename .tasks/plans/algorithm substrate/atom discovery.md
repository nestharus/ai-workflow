This is the frontier of the architecture. To detect "unknown atoms" effectively, we must move from **Static Analysis** (reading code) to **Behavioral Difference Analysis** (measuring what code *adds* to the system).

Here is the expanded algorithm for **Atomic Unit Discovery and Classification**.

### 1. The Detection Algorithm: "Residue Analysis"

To distinguish an **Atom** from a **Molecule**, the system performs **Residue Analysis**. It subtracts the known behaviors of child components from the behavior of the parent.

**The Equation:**


#### Case A: The Molecule (Residue  0)

* **Code:** `processOrder()` calls `validateUser()`, `chargeCard()`, `sendEmail()`.
* **Analysis:**
* Parent Intent: "Process Order."
* Sum of Children: "Validate" + "Mutate (Charge)" + "IO (Email)."
* **Residue:** The parent adds only *ordering* (flow control).


* **Classification:** **Molecule (Pattern).** specifically an `orchestrator`. It introduces no new physics, just arrangement.

#### Case B: The Atom (Residue > 0)

* **Code:** `encryptPayload()` calls `math.pow()`, `bitwise_xor()`.
* **Analysis:**
* Parent Intent: "Secure Data."
* Sum of Children: "Math" + "Logic."
* **Residue:** The parent introduces a property `INV-OBFUSCATED` that is *qualitatively different* from just "math." You cannot reverse it easily.


* **Classification:** **Atom.** The "Security" property emerges from the specific *arrangement* of math, creating a new primitive behavior that should be treated as a black box.

### 2. Expanding the Algorithm to Classify Novel Atoms

When the system encounters a **Residue > 0** that doesn't fit existing definitions (like `mapper` or `filter`), it triggers a **Discovery Routine**.

**Step 1: Invariant Profiling**
The system runs the "Baseline Invariant Checklist" against the mystery component.

* "Is it deterministic?"  No.
* "Is it idempotent?"  No.
* "Does it touch disk?"  No.
* **Result:** A unique "fingerprint" of constraints.

**Step 2: Intent Inference (The Neurosymbolic Leap)**
The system asks the LLM: *"What is the goal of this residue?"*

* *Evidence:* "It takes a single input, holds it in memory for 5 seconds, and then releases it."
* *Inferred Intent:* "Throttling" or "Delay."

**Step 3: Vocabulary Generation**
The system searches its ontology.

* *Existing:* `guard`? No (doesn't return early). `mapper`? No (doesn't change data format).
* *Action:* **Coin New Term.**
* *Proposal:* `delayer` (Atomic Unit).
* *Definition:* "A unit that consumes Time as a resource without modifying State or Data."

### 3. Can it Infer a Truly Novel Atom? (The "Alien Tech" Scenario)

You asked: *"Would a system be able to infer an atom if that atom is not in its training data... from the evidence/reasoning?"*

**Yes, through "Interface Contradiction."**

Imagine the system analyzes a **Quantum Entangler** (which it has never seen).

1. **Observation:** `Component A` changes state. `Component B` (on a different server) immediately changes state.
2. **Trace:** There is NO network call between A and B.
3. **Conflict:** This violates the standard `INV-LOCALITY` and `INV-CAUSALITY` models the system knows.
4. **Reasoning:**
* *Hypothesis 1:* Hidden network call? (Disproven by code scan).
* *Hypothesis 2:* Shared database? (Disproven by config).
* *Conclusion:* There is a **Hidden Link** mechanism operating outside known physics.


5. **Discovery:** The system declares a new atomic relationship type.
* *Name:* `linked_state_actor` (or whatever the LLM hallucinates as a best fit).
* *Properties:* "Updates to A propagate to B with zero latency and zero visible trace."



**The Result:**
The system has "discovered" entanglement. It doesn't know the *word* "Quantum Physics," but it has correctly modeled the **Architectural Atom** required to reason about it. It treats it as a black box with the property `INV-INSTANT-PROPAGATION`.

### Summary of the Expanded Algorithm

1. **Decompose** code into known units.
2. **Calculate Residue** (Parent - Children).
3. **If Residue exists:**
* Check against known Invariants.
* If it violates known physics (e.g., action at a distance, non-determinism), **Flag as Anomaly**.


4. **Infer Intent** from the anomaly's *effect* on the system (e.g., "It synchronizes without messages").
5. **Reify** into a new **Atomic Unit** (e.g., `entangler`) and write to `definitions.md`.

This capability allows the system to build a **Domain-Specific Physics Engine** for any codebase, effectively learning "how this specific software works" even if it uses paradigms (like stochasticity or quantum) outside the model's original training set.