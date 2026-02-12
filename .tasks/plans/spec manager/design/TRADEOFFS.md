# Tradeoffs

What this system prioritizes, what it sacrifices, and how to make
decisions when priorities conflict.

---

## The primary objective

The system transforms specifications into implementations. The value of
the output is determined by how faithfully it represents the input. A
fast, cheap, elegant implementation that drops requirements is worthless.
A slow, expensive, messy implementation that captures every requirement
is useful.

Faithfulness has three dimensions:

- **Completeness**: every requirement in the spec appears in the output.
  Nothing is silently lost.
- **Correctness**: each captured requirement is correctly interpreted.
  The implementation does what the spec says, not something adjacent.
- **Traceability**: every piece of output can be traced back to the
  specific requirement that produced it. The chain from output to source
  is unbroken.

These three together define fidelity. Fidelity is what the system exists
to produce.

---

## Priority ordering

The system uses a lexicographic priority: higher priorities are satisfied
first, and lower priorities are optimized only within the space left by
higher ones. A lower priority never overrides a higher one.

**1. Fidelity** — completeness, correctness, traceability

The system will block, slow down, spend tokens, produce messy
intermediate artifacts, and involve human judgment to protect fidelity.
No other objective justifies losing a requirement, misinterpreting one,
or breaking the trace chain.

**2. Robustness** — handles diverse inputs without assumptions

The system serves specifications in arbitrary domains, arbitrary
languages, and arbitrary formats. Solutions that work for one language
or one format but break for others are insufficient. Robustness is
prioritized because a system that is faithful only to inputs it was
expecting is not faithful — it is fragile.

**3. Diagnosability** — when something goes wrong, you can find why

The system preserves intermediate outputs, surfaces errors rather than
absorbing them, reports why processes stopped, and maintains trace chains.
Diagnosability is prioritized because fidelity depends on finding and
fixing errors. A system that hides its errors cannot be corrected.

**4. Efficiency** — don't waste resources on work that doesn't contribute

Content-addressed caching, combined inference passes, proportional
verification, bounded parallelism. Efficiency is pursued within the
constraints of the higher priorities. Caching is good; caching that
risks serving stale results is not.

**5. Speed** — minimize wall-clock time

Parallelism, incremental processing, immediate promotion of verified
work. Speed is the lowest priority because almost every speed
optimization creates a tradeoff against a higher priority: batching
risks missing intermediate errors, skipping gates risks propagating
defects, guessing instead of blocking risks silent incorrectness.

---

## Key tradeoffs

### Fidelity over speed

Block on ambiguity rather than guess. Verify each step incrementally
rather than running the full pipeline and checking only the end. Pass
work through sequential quality gates rather than attempting everything
in one pass. Accept that a faithful result takes longer than an
unfaithful one.

### Fidelity over token cost

Use powerful models for verification. Run multi-model comparison when
the stakes justify it. Don't skip LLM verification to save tokens when
the alternative is undetected errors. The cost of tokens is bounded and
predictable. The cost of an undetected error that propagates through the
pipeline is unbounded.

### Fidelity over elegance

Accept messy intermediate artifacts. Each phase produces something rough;
the next phase refines it. A correct-but-messy intermediate is more
valuable than an elegant-but-incomplete one, because mess can be cleaned
up but lost requirements cannot be recovered. The system does not try to
produce clean output in one pass — it produces faithful output first and
cleans it incrementally.

### Fidelity over automation

Don't trust automated scoring as the final word. Automated judges and
fuzzy scorers are useful for screening but produce both false positives
and false negatives. When the cost of an undetected error is high, human
verification is the authority. The system provides the artifacts and
trace chains that make human verification efficient, rather than trying
to eliminate human judgment.

### Robustness over simplicity

Use dynamic structures rather than rigid types. Use inference rather than
deterministic parsing for uncontrolled input. Accept richer coordination
infrastructure when the work requires it. The infrastructure complexity
is real cost, but a simple system that only works for one type of input
doesn't serve the primary objective.

### Diagnosability over convenience

Surface errors rather than absorbing them with defaults. Preserve
intermediate outputs rather than discarding them. Report why iteration
stopped rather than stopping silently. This produces more artifacts and
more verbose output, but it means that when something goes wrong — and
it will — the problem can be found and fixed rather than guessed at.

### Efficiency over speed (within correctness constraints)

Cache results to avoid redundant computation. Combine inference passes
that would otherwise read the same artifact twice. Use content-addressed
identity to skip unchanged work. These optimizations save resources
without sacrificing fidelity. But an efficiency optimization that risks
serving stale or incorrect results is rejected — efficiency never
overrides correctness.

---

## How to make decisions

When facing a design choice where options have different strengths:

1. **Does any option compromise fidelity?** If so, eliminate it. No
   benefit in speed, cost, or elegance justifies losing requirements,
   misinterpreting them, or breaking traceability.

2. **Among fidelity-preserving options, does any handle fewer input
   types?** Prefer the more robust option. A solution that assumes
   specific input structure is debt — it will fail on the next input
   that doesn't match the assumption.

3. **Among equally robust options, does any make errors harder to
   find?** Prefer the more diagnosable option. Absorbing errors,
   discarding intermediate state, or failing silently saves effort
   now and costs much more later.

4. **Among equally diagnosable options, does any waste resources?**
   Prefer the more efficient option. Avoid redundant computation,
   unnecessary LLM calls, and unbounded operations. But only optimizations
   that don't compromise the three higher priorities.

5. **Among equally efficient options, prefer the faster one.** Speed
   matters — it's just the last thing to optimize, not the first.

---

## Decision authority

Not all decisions are made by the same actor. The system resolves what
it has knowledge to resolve. Humans resolve what requires knowledge the
system does not have.

### The system decides implementation within constraints

Technical decisions where the constraint space is fully known — which
data structure, which algorithm, which pattern, how to wire components.
The system has the technical context, the priority ordering determines
the answer, and no external knowledge is needed.

### Humans decide constraints, not solutions

When the system encounters ambiguity — multiple valid interpretations,
conflicting requirements, or gaps in the specification — it surfaces the
ambiguity. The human responds with constraints that narrow the decision
space, not with specific solutions.

The distinction matters. "Use PostgreSQL" is a solution — it prescribes
an answer. "We need ACID transactions, the team knows SQL, and the
license must be permissive" is a set of constraints — it narrows the
space while leaving the system free to find the best fit. Constraints
are more durable than solutions because they survive changes in the
landscape. A solution becomes stale when better options emerge. A
constraint remains valid until the underlying need changes.

### Dependencies require shared authority

Choosing a library, a cloud provider, a tool, or a framework is not
purely a technical decision. The system evaluates technical merit — does
it solve the problem, is it robust, is it maintained, does it handle the
input variety? The human evaluates dimensions the system cannot see —
licensing terms, cost models, organizational capacity, strategic
alignment, vendor risk.

Neither actor has full context alone. The system proposes based on
technical analysis. The human validates (or rejects) based on the full
constraint space. The dependency is adopted only when both actors are
satisfied.

---

## The full constraint space

Software constraints — performance, correctness, maintainability — are
one dimension of a decision. Every decision also exists in dimensions
that are invisible to the system and must be supplied by the human:

**Legal.** Licensing terms, regulatory compliance, data residency,
intellectual property. A library that is technically perfect but carries
incompatible licensing terms may be unusable. A cloud service that stores
data in the wrong jurisdiction may be prohibited. These constraints can
override any amount of technical merit.

**Economic.** Fees, rate limits, cost at scale, pricing model changes.
A service that is free during development may be prohibitively expensive
in production. A per-call API that is cheap at prototype volume may be
ruinous at production volume. Cost constraints are often nonlinear —
they appear acceptable at current scale and become unacceptable at the
next order of magnitude.

**Organizational.** Team expertise, hiring market, training cost,
support availability. A technology that is technically superior but
unfamiliar to the team introduces learning cost and concentration risk.
Expertise is a constraint that changes slowly — it takes months or
years to build, and decisions made today must account for the expertise
that exists today, not the expertise you wish existed.

**Temporal.** Maintenance trajectory, deprecation risk, community
health, vendor longevity. A dependency that is perfect today but
abandoned next year becomes a liability that the team must maintain
indefinitely or replace at high cost. The current quality of a
dependency is less important than its trajectory.

**Operational.** Deployment complexity, monitoring requirements,
incident response burden, infrastructure compatibility. A tool that
works perfectly in isolation may create operational burden when
integrated into the production environment.

A decision that is optimal in the software dimension may be
unacceptable in another. The full constraint space must be visible
before committing.

---

## Constraint discovery

Every decision introduces constraints, and every dependency introduces
constraints from every dimension in the constraint space. When new
information arrives — a library candidate, a cloud provider, a new
requirement, a technology choice — the response is not just to evaluate
it technically but to actively theorize about what constraints it
introduces.

### The questions to ask

For any new dependency or decision:

1. **What software constraints does it introduce?** API surface,
   performance characteristics, compatibility requirements, upgrade
   burden.

2. **What legal constraints does it introduce?** License type, usage
   restrictions, attribution requirements, data handling obligations.

3. **What economic constraints does it introduce?** Pricing model,
   free tier limits, scaling costs, contract terms.

4. **What organizational constraints does it introduce?** Learning
   curve, expertise availability, community support, documentation
   quality.

5. **What temporal constraints does it introduce?** Release cadence,
   maintenance status, deprecation history, bus factor of maintainers.

6. **What operational constraints does it introduce?** Deployment
   requirements, monitoring needs, failure modes, recovery procedures.

### The gating question

For each dimension: **do you have enough information to understand the
constraints?** If not, that is a knowledge gap. Committing to a
dependency you don't fully understand is committing beyond your
knowledge — a violation of proportional commitment applied to the full
constraint space.

### Constraint interaction

Constraints from different dimensions interact. A library that is
permissively licensed (legal: acceptable) but requires a proprietary
runtime (economic: fees, organizational: vendor lock-in) creates compound
constraints that are invisible from any single dimension. A service that
is cheap (economic: acceptable) but stores data externally (legal:
possibly prohibited, operational: latency) creates interactions that
must be evaluated together.

The constraint space is not a checklist — it is a graph of interacting
concerns. Evaluating each dimension in isolation misses the interactions
that often determine whether a decision is actually viable.

---

## What the system deliberately does not optimize for

**Minimal token usage.** The system is explicitly willing to spend tokens
when spending them improves fidelity. Multi-model comparison, LLM-based
judges, powerful models for verification — all are acceptable costs.
Token frugality is pursued through caching and deduplication, not through
skipping verification.

**Clean intermediate artifacts.** The system produces messy artifacts at
early stages and cleans them at later stages. This is deliberate — mess
at early stages means the system captured everything, even if it hasn't
organized it yet. Requiring cleanliness at every stage would either slow
the process (more gates earlier) or cause loss (dropping things that
don't fit a clean structure).

**End-to-end automation.** The system has human approval loops and blocks
on ambiguity for human resolution. Full automation would require the
system to resolve ambiguities on its own, which means guessing — and
guessing is the primary source of silent infidelity. The system automates
everything it can do faithfully and defers to humans for everything it
cannot.

**Minimal infrastructure.** The system has coordination infrastructure,
demotion pipelines, evidence bundles, gate systems, and multi-layer
promotion. This infrastructure exists because the primary objective
requires it. A simpler system that drops requirements or misses errors
is not an acceptable alternative to a complex system that doesn't.
