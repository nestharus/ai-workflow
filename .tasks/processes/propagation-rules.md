# Propagation Rules

This document defines how invariants, obligations, and capabilities flow through the
graph structure. These rules enable bug finding and decomposition analysis.

---

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Propagation Directions                     │
│                                                                 │
│   INVARIANTS (INV)                                              │
│   ├── Top-down: From root components to descendants             │
│   └── Surface barriers: CON can satisfy/pass/absorb             │
│                                                                 │
│   OBLIGATIONS (OBL)                                             │
│   ├── Bottom-up: From leaf demands to ancestors                 │
│   └── Surface barriers: CON can satisfy or leak                 │
│                                                                 │
│   CAPABILITIES (CAP)                                            │
│   ├── No propagation: Each CAP stays with its owner COM         │
│   └── Analysis: Detect overlaps and divergence across COMs      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Invariant Propagation (Top-Down)

Invariants cascade from root components down through the composition hierarchy.

### Rules

1. **Root declares context**: The root component's invariants define the execution context
2. **Surfaces act as barriers**: Each surface (SUR/CON) can:
   - **SATISFY**: Fulfill the invariant (stops propagation)
   - **PASS**: Allow invariant to continue to descendants
   - **ABSORB**: Block invariant (not relevant to subtree)
3. **Active invariants accumulate**: At any node, active = inherited + own

### Algorithm

```python
def cascade_invariants_down(graph: Graph, root_id: str):
    """Push invariants from root down through composition hierarchy."""

    def visit(com_id: str, inherited: Set[str]):
        com = graph.get_node(com_id)
        sur = graph.get_node(com.surface)

        # Active = inherited + own invariants
        active = inherited | com.own_invariants
        com.active_invariants = active

        # For each contract on the surface
        for con_id in sur.contracts:
            con = graph.get_node(con_id)

            # Determine what passes through this contract
            passed = compute_barrier(active, con)
            con.passes = passed
            con.absorbs = active - passed - con.satisfies

        # Recurse to composed children
        for child_id in com.composed_of:
            # Child inherits what passes through parent's surface
            child_inherited = get_passed_invariants(com, child_id)
            visit(child_id, child_inherited)

    root = graph.get_node(root_id)
    visit(root_id, root.own_invariants)
```

### Surface Barrier Determination

How to determine if a contract satisfies, passes, or absorbs an invariant:

**Option A: Explicit Declaration**

```markdown
## Contract: CON-01

Barrier properties:
- Satisfies: INV-THREAD-SAFE (internal synchronization)
- Passes: INV-DETERMINISTIC
- Absorbs: INV-ASYNC-CONTEXT
```

**Option B: LLM Inference**

When not explicitly declared, LLM infers from contract semantics:

```python
def infer_barrier(invariant: str, contract: Contract) -> str:
    """Returns: 'satisfies' | 'passes' | 'absorbs'"""
    prompt = f"""
    Contract: {contract.description}
    Invariant: {invariant.description}

    Does this contract:
    - SATISFY this invariant (handle it internally)?
    - PASS it through (still applies to internals)?
    - ABSORB it (not relevant to this subtree)?
    """
    return llm_inference(prompt)
```

---

## Obligation Propagation (Bottom-Up)

Obligations bubble up from leaf components/state holders to ancestors.

### Rules

1. **Leaves declare demands**: IAR and leaf CON declare what they require
2. **Propagation stops when satisfied**: If a surface satisfies the obligation, it stops
3. **Leaked obligations accumulate**: Unsatisfied obligations leak to callers

### Algorithm

```python
def propagate_obligations_up(graph: Graph):
    """Bubble up obligations from leaves to root."""

    # Find all nodes with obligations
    for node in graph.nodes_with_obligations():
        for obl_id in node.demands:
            propagate_single_obligation(graph, node.id, obl_id)

def propagate_single_obligation(graph: Graph, source_id: str, obl_id: str):
    """Propagate one obligation upward."""

    # Find callers (components whose surface contracts might satisfy this)
    for caller_id in graph.get_callers(source_id):
        caller = graph.get_node(caller_id)
        con = graph.get_connecting_contract(caller_id, source_id)

        # Does the contract satisfy this obligation?
        if obl_id in con.guarantees_satisfaction:
            con.satisfies.add(obl_id)
            # Stop propagation - handled here
        else:
            # Obligation leaks through - caller inherits demand
            caller.inherited_obligations.add(obl_id)
            # Continue propagating up
            propagate_single_obligation(graph, caller_id, obl_id)
```

### Violation: Leaked to Root

If an obligation propagates all the way to the root without being satisfied:

```python
def find_obligation_leakages(graph: Graph) -> List[Violation]:
    violations = []

    for root_id in graph.get_roots():
        root = graph.get_node(root_id)

        for obl_id in root.inherited_obligations:
            violations.append(ObligationLeakage(
                obligation=obl_id,
                leaked_to=root_id,
                path=trace_obligation_path(graph, obl_id, root_id)
            ))

    return violations
```

---

## Capability Analysis (No Propagation)

Capabilities don't propagate — each CAP stays with its owning COM. Instead, we analyze
the distribution of capabilities across the graph.

### Overlap Detection

```python
def find_capability_overlaps(graph: Graph) -> List[Overlap]:
    overlaps = []

    # Group components by capability
    cap_to_coms = defaultdict(list)
    for com in graph.get_components():
        for cap_id in com.capabilities:
            cap_to_coms[cap_id].append(com.id)

    # Find capabilities in multiple components
    for cap_id, com_ids in cap_to_coms.items():
        if len(com_ids) > 1:
            overlaps.append(CapabilityOverlap(
                capability=cap_id,
                components=com_ids,
                recommendation="merge_or_extract"
            ))

    return overlaps
```

### Divergence Detection

```python
def find_capability_divergence(graph: Graph) -> List[Divergence]:
    divergences = []

    for com in graph.get_components():
        caps = com.capabilities

        if len(caps) > THRESHOLD:
            # Cluster capabilities by semantic similarity
            clusters = cluster_capabilities(caps)

            if len(clusters) > 1:
                divergences.append(CapabilityDivergence(
                    component=com.id,
                    clusters=clusters,
                    recommendation="split_by_cluster"
                ))

    return divergences
```

---

## ALG ↔ CON Violation Detection

The key violation type: ALG guarantees don't match CON guarantees.

### Rule

For each contract on a component's surface, the algorithms inside that component
must collectively guarantee at least what the contract promises.

```python
def find_alg_con_violations(graph: Graph) -> List[Violation]:
    violations = []

    for com in graph.get_components():
        sur = graph.get_node(com.surface)

        # What the surface promises
        con_guarantees = set()
        for con_id in sur.contracts:
            con = graph.get_node(con_id)
            con_guarantees |= set(con.guarantees)

        # What the algorithms actually guarantee
        alg_guarantees = set()
        for alg_id in com.algorithms:
            alg = graph.get_node(alg_id)
            alg_guarantees |= set(alg.guarantees)

        # Find promises not backed by algorithms
        unmet = con_guarantees - alg_guarantees
        if unmet:
            violations.append(AlgConMismatch(
                component=com.id,
                contract_promises=con_guarantees,
                algorithm_provides=alg_guarantees,
                unmet=unmet
            ))

    return violations
```

---

## Inference During Updates

When algorithms are updated, the LLM infers changes to invariants and capabilities:

```python
def on_algorithm_update(com_id: str, alg_id: str, new_code: str):
    old_alg = graph.get_node(alg_id)

    # LLM infers new guarantees
    new_guarantees = llm.infer_invariants(new_code)
    new_capabilities = llm.infer_capabilities(new_code)

    # Detect changes
    added_inv = new_guarantees - old_alg.guarantees
    removed_inv = old_alg.guarantees - new_guarantees

    added_cap = new_capabilities - graph.get_component_capabilities(com_id)
    removed_cap = graph.get_component_capabilities(com_id) - new_capabilities

    # Log changes for review
    if added_inv or removed_inv:
        log(f"Invariant changes in {alg_id}: +{added_inv} -{removed_inv}")

    if added_cap or removed_cap:
        log(f"Capability changes in {com_id}: +{added_cap} -{removed_cap}")

    # Update graph
    graph.update_algorithm(alg_id, new_guarantees)
    graph.update_component_capabilities(com_id, new_capabilities)

    # Re-run violation detection
    violations = find_alg_con_violations(graph)
    if violations:
        alert(f"New violations introduced: {violations}")
```

---

## Summary

| Concept | Propagation | Direction | Barrier |
|---------|-------------|-----------|---------|
| INV (Invariant) | Yes | Top-down | SUR/CON can satisfy/pass/absorb |
| OBL (Obligation) | Yes | Bottom-up | CON can satisfy or leak |
| CAP (Capability) | No | N/A | Analyzed for overlap/divergence |

**Violations detected:**

1. **INV cascade collision**: Inherited INV conflicts with local OBL
2. **OBL leakage**: Obligation reaches root unsatisfied
3. **ALG ↔ CON mismatch**: Algorithm doesn't guarantee what contract promises
4. **CAP overlap**: Same capability in multiple components
5. **CAP divergence**: Unrelated capabilities in one component
