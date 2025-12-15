## Canonical domains of artifact orchestration

The intent here is a **domain taxonomy** for creating, understanding, and maintaining artifacts—independent of any specific “agent catalog.” Each domain can be implemented by many agent types/algorithms.

The domains below are derived from the behaviors your artifacts require: intent structuring, information work, plan construction, artifact generation, validation (rule + conformance), governance, repair, and long-term evolution. The "Primary roles" doc already enumerates the raw ingredients (translator, planner, implementor, drift review, artifact review, oversight, investigator, researcher, crawler, orchestrator); this taxonomy collapses them into the **minimal complete set of domains**.

---

## Domain 1: Intent inference and specification

### Purpose

Turn human input into **operationally testable, machine-consumable specifications** that become the system-of-record for all downstream work.

This domain is explicitly described as taking “raw human input and determin[ing] the intent”  and (elsewhere) producing structured intake artifacts (intent / acceptance criteria / constraints / unknowns). Even when the implementation is automated, the pipeline needs an **initial contract** that downstream conformance checks can compare against.

### What this domain owns

* Defining success in *artifact-verifiable* terms (acceptance criteria, invariants, constraints).
* Eliminating ambiguity (or explicitly recording ambiguity as unknowns).
* Establishing the first “spec” artifact used later by conformance checks (plan drift: requirements → plan; implementation drift: plan → code; etc.)

### What it does not own

* Choosing architecture or wiring (“how”); that belongs to planning (Domain 4). Your planning section explicitly says strategy planners define the how, under oversight .

### Why this is a distinct domain

If this domain is weak, everything downstream becomes unstable:

* drift review loses a stable upstream spec
* planning can’t decompose reliably
* verification can’t assert correctness

---

## Domain 2: Orchestration control plane

### Purpose

Provide the **control plane**: sequencing, routing, looping, gating, escalation, and artifact handoffs.

Your doc states: “The orchestrator routes the information along the pipeline… Outputs may not be static… Orchestration decisions could rely on an LLM or a script.”
It also enumerates orchestration “types” (CREATE / REVIEW / INTEGRATE / REPAIR / AUDIT / UPDATE).

### What this domain owns

* State machine / DAG of stages (including retry loops).
* Routing decisions based on semantic outputs (PASS/FAIL, drift report content, suspicion signals).
* Enforcing “loop until clean” mechanics in review pipelines (review → patch → re-review) as a control-flow pattern (described in your artifact review orchestration mechanics).

### What it does not own

* Producing content inside artifacts (code, plans, findings). It coordinates; it does not create meaning.

### Why this domain is distinct

Without a control plane, you do not have a pipeline—you have a collection of tools. This domain is the “scheduler + router + escalation manager” for all other domains.

---

## Domain 3: Knowledge acquisition and discovery

### Purpose

Acquire raw signals needed to create or interpret artifacts: docs, codebase context, standards, prior decisions, patterns.

Your doc defines crawlers as: “small pattern recognition… large swarms to search for anything… optimized with graphs/databases/vector stores… can brute force unstructured text.”

### What this domain owns

* Coverage-oriented retrieval (breadth-first, swarm-based, topic-wave based).
* Producing raw evidence artifacts suitable for later synthesis (Domain 4).
* “Find anything related” behavior; high recall is prioritized.

### What it does not own

* Deduplication, conflict resolution, final findings. That is synthesis.

### Why this domain is distinct

Discovery is fundamentally different from synthesis: it’s “collect” not “decide.” Your own pipeline separates crawler work from researcher synthesis.

---

## Domain 4: Knowledge synthesis and evidence binding

### Purpose

Convert raw retrieved material into **decision-ready knowledge artifacts** with provenance.

Your doc: “Next is the researcher. They synthesize information. They deduplicate and organize.”
And the drift reviewer variant list explicitly includes “Research Coverage Drift Review” comparing questions vs findings —meaning your pipeline treats research output as a first-class spec/implementation pair.

### What this domain owns

* Deduplication (semantic equivalence collapsing).
* Conflict surfacing (not necessarily resolving by fiat).
* Evidence binding: claims ↔ evidence pointers.
* Producing research artifacts that planning can depend on (findings, open gaps, integration maps).

### What it does not own

* Selecting the “ship decision” or architecture policy; that belongs to planning.
* Modifying implementation artifacts (code/tests); that belongs to repair/execution.

### Why this domain is distinct

It is the “sensemaking layer.” Without it:

* Planning will be fed redundant or contradictory inputs
* Traceability becomes weak
* Review and drift become noisy

---

## Domain 5: Strategy, planning, and integration planning

### Purpose

Generate the **wiring documents** and strategy patterns that downstream execution can “print.”

Your primary roles doc makes this explicit:

* there are strategic planners and integration planners
* planning goes “to strategy and then to integration”
* strategy defines the how (with oversight); after that the rest is automated

### What this domain owns

* Strategy formation: patterns, approaches, risk posture.
* Integration planning: topology/wiring (“where does this go?”) that becomes a deterministic spec for executors.
* Producing explicit plans that serve as upstream specs for conformance checks (Domain 7).

### What it does not own

* Literal execution mechanics (exceptions, syntax-level detail) beyond what is necessary to make the plan executable; those details are “printed” in implementation.

### Why this domain is distinct

This is the “document” in your printer metaphor ecosystem. The entire system’s discipline depends on updates flowing back to strategy/plan rather than patching the printout.

---

## Domain 6: Artifact production and execution

### Purpose

Translate plans into concrete artifacts (code, tests, configs, docs) with **minimal interpretation**.

Your doc: “The job of the implementor is simply to follow instructions… powerful enough not to understand intent but to follow literal instructions.”

### What this domain owns

* Generating artifacts from a plan (mechanical translation).
* Emitting execution receipts / step logs (so governance can validate process).

### What it does not own

* Deciding what to build (planning) or what “good” looks like (review/validation).

### Why this domain is distinct

It is deliberately non-strategic. It exists to create predictable transformation: plan → artifact.

---

## Domain 7: Verification and review (V&V, broadly)

### Purpose

Provide **artifact eligibility decisions**: does this artifact advance, retry, or route back?

This domain has two fundamentally different verification modes that your docs explicitly distinguish:

1. **Rule-based artifact review**
   “The job of the artifact reviewer is to enforce a domain of artifact rules… architectural, anatomical, contextual… enforce best practices.”

2. **Conformance / drift review**
   “The job of the drift reviewer is fact extraction and matching… compare… where one artifact is the spec of another… focused on capturing drift.”
   And drift detection as an isomorphism validator: downstream must not add unauthorized content or omit required content.

### What this domain owns

* PASS/FAIL judgments for advancement.
* Producing structured reports: violations (rule-based) and drift reports (pairwise).
* Traceability matrices and coverage mappings (explicitly called out as drift reviewer responsibilities).
* Enforcing the split: drift review does not enforce code quality rules, and does not fix drift.

### What it does not own

* Actually applying fixes (execution/patching) or debugging why something fails (repair domain).

### Why this domain is distinct

Without a formal verification domain, the pipeline cannot be reliable:

* execution produces output
* but nothing enforces that output is correct, safe, or aligned to spec

### Diagram: verification as two orthogonal lenses

```text
                   Verification & Review Domain
                               |
       +-----------------------+-----------------------+
       |                                               |
       v                                               v
Rule-based Review                              Conformance/Drift Review
(artifact vs rules)                            (artifact pair comparison)
- conventions                                   - additions/omissions/deviations
- architectural/anatomical/contextual            - coverage matrices
- best practices                                 - “spec → implementation” fidelity
```

---

## Domain 8: Governance, assurance, and auditability

### Purpose

Ensure the pipeline is **trustworthy as a process**, not just “correct by luck.”

Your doc describes Pipeline Oversight in exactly these terms: it ensures agents follow rules, detects trickery, checks deviation receipts, flags suspicious missing outputs, and uses enforcers to recognize justified deviations.

And your enforcer artifact describes the governance primitive precisely:

* “Blindly verify that the process was followed (receipts exist) without reading the artifact content.”
* “Gates artifact transition to the next stage” based on receipt presence.

### What this domain owns

* Receipt requirements (what must be produced at each stage).
* Gate enforcement independent of content (“content-blind” process validation).
* Detection of manipulation patterns (log embedding, forged “decision already made” messages, missing receipts).
* Audit orchestration: when process integrity is questionable (your orchestration types include AUDIT).

### What it does not own

* Domain correctness of code or plans; it verifies that the checks happened and were attested.

### Why this domain is distinct

Verification without governance is brittle in multi-agent settings:

* an agent can skip steps, omit receipts, or fabricate status
* governance makes the system robust against those failure modes

### Diagram: governance gate sits “above” every stage

```text
Stage Output (artifact + receipts)
            |
            v
 Governance Gate (receipt + integrity checks)
   - PROCEED if compliant
   - HALT if missing / suspicious
            |
            v
Next Stage
```

---

## Domain 9: Remediation, debugging, and recovery (repair/RCA)

### Purpose

When verification fails, this domain is responsible for **making artifacts work** and producing **root-cause feedback** that improves upstream planning.

Your doc is explicit:

* Investigators “try to get an artifact working… in isolation on a copy… artifact is modified and the tests are modified until it works… reports why… goes back to strategy… artifacts cannot pass through until investigator approves.”

This is not the same thing as research synthesis:

* research synthesizes information and organizes knowledge
* remediation modifies failing artifacts/tests, in isolation, and blocks promotion until working

### What this domain owns

* Isolated reproduction (sandbox/worktree), diagnosis, repair.
* “Gatekeeping on functionality”: nothing ships if broken.
* Root cause artifacts that feed planning updates (feedback loop integration is explicitly called out).
* Repair orchestration as a first-class mode (your orchestration types include REPAIR).

### What it does not own

* Long-term policy decisions about architecture (those changes are pushed back into planning).
* Routine quality review; after repair, artifacts still go through review gates (investigator doc explicitly shows repair then artifact review orchestration).

### Diagram: repair as a loop triggered by verification failure

```text
Verification FAIL
      |
      v
Remediation (isolate → reproduce → fix → explain)
      |
      +----> produces: root-cause + patch summary + feedback-to-plan
      |
      v
Re-Verification / Review gates
```

---

## Domain 10: Evolution, maintenance, and knowledge integration

### Purpose

Ensure the system improves over time: fewer repeated failures, fewer repeated “gray area” escalations, and stable alignment between strategy/plan/artifacts as the codebase evolves.

Your docs already encode a formal integration loop (even if operationally you treat it as mostly auto-integrated with conditional oversight):

* pattern aggregation → classification → integration target (strategy/plan/artifact)
* approval logic differs: strategy integration requires approval every time; plan/artifact can be whitelisted for future auto-approval
* UPDATE orchestration exists as a first-class workflow mode

### What this domain owns

* Updating the “documents” that drive future prints (strategy docs, planning heuristics, artifact conventions).
* Managing controlled evolution of artifacts (update workflows, migrations, deprecations).
* Keeping the “Hierarchy of Truth” synchronized as new knowledge arrives:

    * if implementation reveals missing plan detail → update plan
    * if plan reveals missing strategy → update strategy
    * if repeated mechanical issue occurs → update artifact conventions/heuristics

### What it does not own

* Immediate functional repair in a failing run (that’s remediation).
* Day-to-day routing decisions (that’s orchestration control plane).

### Why this domain is required (for “maintaining artifacts”)

A pipeline that can only “create once” but cannot:

* incorporate learnings
* update plans/heuristics
* manage controlled change
  will accumulate drift and become expensive to operate.

### Diagram: evolution loop (learn → integrate → automate)

```text
Signals from runtime + review + drift + repair
                |
                v
Candidate patterns / heuristics / policy updates
                |
                v
Integrate into:
  - strategy patterns
  - plan heuristics
  - artifact conventions
                |
                v
Automation increases (fewer escalations; fewer repeated drifts)
```

---

## Completeness check: do these domains cover “create, understand, maintain”?

### Create

* Intent inference/spec → planning → execution (Domains 1, 5, 6), coordinated by orchestration (Domain 2), with research if needed (Domains 3–4).

### Understand (artifact comprehension)

* Conformance/drift review explicitly performs “fact extraction and matching” across artifacts  and produces coverage matrices ; rule review enforces semantics and conventions . Together, that is system-level understanding (Domain 7), with provenance and receipts (Domains 4 and 8).

### Maintain

* Governance/auditability (Domain 8) prevents process decay.
* Remediation/repair (Domain 9) keeps artifacts functional.
* Evolution/change management/integration loop (Domain 10) prevents repeating failures and manages long-term drift.
* Update orchestration exists explicitly .

---

## Notes on naming (industry-style “domain terms”)

If the goal is “most correct domain terms,” the stable, widely understood naming scheme for these domains is:

* **Requirements & Specification** (Domain 1)
* **Workflow Orchestration / Control Plane** (Domain 2)
* **Retrieval / Discovery** (Domain 3)
* **Synthesis / Evidence / Knowledge Management** (Domain 4)
* **Architecture & Planning** (Domain 5)
* **Build / Generation / Execution** (Domain 6)
* **Verification & Validation (V&V)** with:

    * rule-based review
    * conformance/traceability review (drift) (Domain 7)
* **Governance / Compliance / Auditability** (Domain 8)
* **Debugging / Remediation / Recovery (RCA)** (Domain 9)
* **Maintenance / Change Management / Continuous Improvement** (Domain 10)

That set is intentionally “domain-complete” for artifact systems: it covers initial creation, ongoing comprehension, and long-term upkeep without requiring you to enumerate every possible agent type inside each domain.
