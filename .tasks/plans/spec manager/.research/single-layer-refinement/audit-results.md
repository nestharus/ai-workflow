# Audit Results: Single-Layer Refinement Response

## Audit Process
- **Direction**: Opus (identified 8 divergence signals)
- **Execution**: Codex High2 (validated all 8, found 2 additional)
- **Interpretation**: Opus (this document)

## Divergence Summary

| # | Title | Severity | Constraint |
|---|-------|----------|------------|
| 1 | Extraction Surface Expansion | CRITICAL | C01 + DP#3 |
| 2 | Separate Mechanical Extraction Pipeline | CRITICAL | DP#10 |
| 3 | Upfront Schema Commitment Without Evidence | SIGNIFICANT | C00 |
| 4 | Single Graph Coupling Surface | SIGNIFICANT | C04 |
| 5 | Mixed Scope in One Representation | SIGNIFICANT | C05 |
| 6 | PIN Renaming, Not Retirement | SIGNIFICANT | DP#7 |
| 7 | LLM-Inferred Fingerprint as Convergence Authority | CRITICAL | C00 + C03 |
| 8 | Derived Work While Source Is Moving | SIGNIFICANT | C02 |
| 9 | Identity Scheme Mismatch | SIGNIFICANT | C10 |
| 10 | Parallel Truth During Migration | SIGNIFICANT | C02 |

## Opus Interpretation: What Went Wrong

### The fundamental framing error

The response approached the problem as: **"How do I build a richer replacement
for PINs?"** This led it to propose an annotated adjacency graph with edge
roles, projection types, algorithm groups, fingerprints, and cross-file
resolution — all of which are EXTRACTIONS from code.

The constraints say: **"Routing over extraction."** The correct frame is:
**"How do we route work without extracting structure from code?"**

The response designed a system that extracts MORE information from code than
the current PIN system does, in MORE separate passes, through a MORE tightly
coupled representation. This is the opposite direction from the constraints.

### The three critical divergences form a chain

1. **Extraction expansion** (D1): The response makes extracted graph
   annotations the operational authority for routing/gating. The annotations
   ARE the routing mechanism. But C01 says extractions are routing HINTS,
   not the route itself.

2. **Separate extraction passes** (D2): To populate the rich graph, the
   response introduces 4-5 standalone inference/classification passes
   (adjacency, cross-file resolution, role classification, boundary detection,
   fingerprints). DP#10 says the LLM should produce this information WHILE
   doing its actual task, not in separate mechanical steps.

3. **LLM-inferred fingerprints as authority** (D7): The convergence strategy
   depends on fingerprints derived from LLM-inferred edge roles. But LLM
   inference is non-deterministic. C00 says "don't treat unverified output as
   knowledge." The response's mitigation (thresholding, consensus) converts
   uncertainty into accepted state — which C03 says is absorbing errors.

### The chain effect

D1 → D2 → D7: The extraction-first design requires separate extraction passes,
and those passes produce LLM-inferred annotations that become the convergence
authority. Each link in this chain is a constraint violation, and together they
create a system where:
- Correctness depends on extraction accuracy (violates C01)
- Extraction happens outside the primary task (violates DP#10)
- Convergence depends on non-deterministic LLM output (violates C00, C03)

### What the response got right

1. **Phase-scoped authority** is a good concept — behavior before wiring
   before refactoring. This preserves sequential stabilization (C02).
2. **Demotion → escalation reframing** is correct — findings route to work
   items with stronger authority, not to lower layers.
3. **Progressive gating by aspect** preserves the gate ordering value.
4. **Block on ambiguity for UNKNOWN edges** is consistent with C00/DP#12.
5. **The hypothesis is plausible** — single-layer IS simpler IF the mechanism
   is correct. The problem is the mechanism, not the goal.

### What needs to be different in a refined solution

The refinement prompt should redirect toward a solution where:

1. **Graph annotations are produced DURING primary tasks** (implementing,
   reviewing, gap-checking) — not in separate extraction passes. The LLM
   already understands the code while doing its job; it should emit
   relationship signals as a byproduct, not as a separate pipeline.

2. **Routing uses the original spec/code text as the key** — not extracted
   graph positions. The current system routes by spec text (work items ARE
   spec text, per RP4 agent coordination design). Extracted positions are
   hints, not authorities.

3. **Convergence uses deterministic properties** — test results, spec comment
   presence/absence, file diffs. NOT LLM-inferred edge classifications.
   Fingerprints should be over code content, not over inferred annotations.

4. **Scope separation is maintained** — even without layers, logical concerns
   and structural concerns should be evaluated in separate passes with
   separate context, not mixed in one graph representation.

5. **PIN concepts may survive with less machinery** — the bridge between
   "what the algorithm does" and "where it sits in the architecture" is a
   real problem. The response was honest that it can't be fully eliminated.
   The refinement should explore lighter-weight bridging, not more extraction.

6. **Evidence before commitment** — the refinement should propose experiments
   (evals) before detailed schemas.
