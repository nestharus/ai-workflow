# Patch: Algorithmic Projection Model

Synthesized from conversation + ALGORITHM.md + PLAN.md + EVOLUTION_PLAN.md + implementation papers (Phases A-E).

---

## 1. Paradigm Shift: Edit-in-Place Replaces Extraction

ALGORITHM.md Phase 0 uses **extraction**: read source files, index line ranges to entities, build an evidence graph. The spec is a separate artifact derived from source material.

The new insight: **the code IS the spec**. There is no extraction step. Instead:

1. Start with pseudocode comments in actual code files
2. Translate comments into real code in place
3. Remaining comments = unimplemented spec (completeness detector)
4. No separate evidence graph, no line-range indexing, no Phase 0

This eliminates the entire extraction pipeline and the drift problem between spec and code — they are the same artifact. The spec evolves by editing code, not by maintaining a parallel document.

### How It Works

```python
# STAGE 1: Pure pseudocode (the initial spec)
def process_order(order):
    # validate payment against fraud rules
    # apply discount based on customer tier
    # charge card through payment gateway
    # send confirmation to customer
    pass

# STAGE 2: Partially translated (spec + code coexist)
def process_order(order):
    result = validate_payment(order.payment)
    discount = apply_discount(order, result)
    # charge card through payment gateway    <-- still spec
    # send confirmation to customer          <-- still spec
    return charge_card(order.payment, discount)

# STAGE 3: Fully translated (no comments = spec complete)
def process_order(order):
    result = validate_payment(order.payment)
    discount = apply_discount(order, result)
    charge = charge_card(order.payment, discount)
    send_confirmation(order.customer, charge)
    return charge
```

Comments are detectable. Code enforces "no comments in production." Any remaining comment is an unresolved spec element. This is mechanically verifiable.

### Language-Specific from Day One

The original papers discussed language-agnostic specs. We depart from that: **tie to a real language** so code is testable from the start. No loose spec translation step. Pseudocode comments live inside real function signatures in a real language. This means:

- Every stage is parseable and executable (stubs raise NotImplementedError)
- Type signatures constrain the spec before implementation begins
- Tests can be written against stubs immediately
- The gap between "spec" and "code" is zero — they are the same file

---

## 2. Core Problem

Architecture destroys algorithms. Business logic gets smeared across event handlers, middleware, retry policies, serializers. The original algorithm ceases to exist as a coherent unit. Architecture also introduces its own algorithms (routing, retry, circuit breaking) that have no counterpart in the business spec.

This means:
- You cannot reverse an architectural transformation to recover the algorithm
- You cannot incrementally patch architecture when algorithms change (the mapping is destroyed)
- Line-to-line provenance breaks because the structural relationship is many-to-many with introduced nodes

---

## 3. The Base Level: Algorithms, Stores, and Shapes

Before projecting into architecture, the algorithmic layer establishes three foundational elements:

**Algorithms**: Sequences of steps that transform data. Pure business logic. These are the edit-in-place code described above. They call each other directly — no indirection.

**Stores**: Persistent state (databases, files, queues). From ALGORITHM.md Phase 2.6:
- Type A (Persisted): survive restart (DB, files)
- Type B (Long-Lived Ephemeral): in-memory across steps (HIGH RISK)
- Type C (Pure Ephemeral): local/temporary within single step

**Shapes**: Pure logic with no external state or side effects (ALGORITHM.md Phase 3.3 Shape Test). Mappers, validators, transformers. These are the most portable atoms — they work identically in any architectural context.

Together, algorithms + stores + shapes form the **base projection**. Everything else (events, middleware, services, routing) is a higher-order projection that decorates around this base.

---

## 4. Planning: How New Work Enters the System

Planning is the inverse of translation. Translation turns pseudocode comments into code. Planning turns intentions into pseudocode comments.

### Adding New Plans

New work enters by inserting pseudocode comments into the algorithmic code:

```python
# BEFORE: existing algorithm
def process_order(order):
    result = validate_payment(order.payment)
    discount = apply_discount(order, result)
    charge = charge_card(order.payment, discount)
    return charge

# AFTER: new plan added as comments
def process_order(order):
    result = validate_payment(order.payment)
    # check if customer is flagged for manual review     <-- new plan
    # if flagged, route to human approval queue           <-- new plan
    discount = apply_discount(order, result)
    charge = charge_card(order.payment, discount)
    # send receipt to customer email                      <-- new plan
    return charge
```

Each new comment is a micro-plan. It sits in context — you can see exactly where it fits relative to existing code. No separate planning document that drifts.

### Reverse Translation for Replanning

Existing code can be translated BACK into pseudocode comments to replan a section:

```python
# Translate this back to pseudocode to replan:
def apply_discount(order, validation_result):
    # determine customer tier from account history
    # look up discount table for tier
    # apply seasonal modifier if applicable
    # cap discount at maximum allowed percentage
    pass
```

This is how you "reopen" a completed section for redesign. The code is replaced by comments describing what it did, and the translation cycle starts again.

### Small Self-Contained Units

Plans decompose into **micro-units** — individual comments that each describe one thing. Large plans are dangerous because decomposition gets sketchy. With micro-units:

- Each comment is a single responsibility
- Each translates to a small number of lines
- Dependencies between comments are visible (they're adjacent in the function)
- No need for a separate plan decomposition step — the code structure IS the decomposition

### Adjacent Detail Discovery During Planning

When adding new comments, we may miss adjacent details — things that interact with the new plan but aren't obvious. Detection: after adding comments, run the algorithmic code. The call graph reveals what the new code will touch. Anything touched that doesn't have test coverage is an adjacent detail that needs a plan too.

---

## 5. Pin-Functions: The Executable Bridge

### Pins Are Functions, Not Labels

The original pinning concept used annotation labels (`@pin`, `@from`). The new insight: **pins are actual extracted functions**. When we decompose an algorithm into atoms for projection, each atom becomes a real function.

```python
# ---- Atom functions (the pins) ----

def validate_payment(payment_data: dict) -> ValidationResult:
    """Validates payment against fraud rules."""
    if payment_data["amount"] <= 0:
        return ValidationResult(valid=False, reason="invalid amount")
    if payment_data["card_expired"]:
        return ValidationResult(valid=False, reason="expired card")
    return ValidationResult(valid=True)

def apply_discount(order: Order, tier: CustomerTier) -> Decimal:
    """Applies discount based on customer tier."""
    base_rate = TIER_DISCOUNTS[tier]
    return order.subtotal * base_rate

# ---- Algorithmic layer (clean, direct composition) ----

def process_order(order):
    result = validate_payment(order.payment)
    tier = get_customer_tier(order.customer_id)
    discount = apply_discount(order, tier)
    charge = charge_card(order.payment, order.subtotal - discount)
    send_confirmation(order.customer, charge)
    return charge

# ---- Architectural layer (recomposes the same functions) ----

class PaymentValidationMiddleware:
    async def handle(self, event):
        result = validate_payment(event.payload)  # Same function!
        await self.bus.publish("payment.validated", result)

class DiscountHandler:
    async def on_payment_validated(self, event):
        discount = apply_discount(event.order, event.tier)  # Same function!
        await self.bus.publish("discount.applied", discount)
```

### Why Functions Solve the Mapping Problem

Functions are **unambiguous addressable units**:
- They have names (stable identifiers)
- They have line numbers (precise location)
- They have signatures (type-checked contracts)
- They are importable (both layers literally import the same function)

When an algorithm changes, you change the atom function. Every layer that imports it gets the change automatically (for pass-through projections). For projections that wrap or transform the atom, the pin tells you exactly which architectural locations to update.

### Micro-Addressing via Functions

With pin-functions, addressing is precise:
- `validate_payment` — the whole atom
- `validate_payment:L3-L5` — specific lines within the atom
- `process_order:validate_payment` — the call site in the composition

No ambiguity about what is pinned. No fuzzy text matching. Functions are the natural unit of pinning.

### Incremental Change via Pins

When an algorithm changes:
1. Identify which atom functions changed
2. For each changed atom, follow all pins (imports) to architectural locations
3. For pass-through pins: change propagates automatically (same function)
4. For wrapping pins: check if the wrapper still correctly wraps the new version
5. For smearing pins: check if the aggregation still makes sense with the new atom

This is **incremental** — only affected atoms and their pins are touched. No full regeneration needed. The pin graph is the change propagation map.

---

## 6. Branch Organization and Promotion

### Multiple Representations, Maintained in Parallel

The system maintains multiple representations (branches) of the code:

```
branches/
  algorithmic/          # Layer 1: The spec. Pure algorithms + stores + shapes.
    atoms/              # Pin-functions (shared between all layers)
    compositions/       # How atoms compose into algorithms
    stores/             # Store definitions
    shapes/             # Pure logic shapes
  architectural/        # Layer 2: Real architecture.
    services/           # Atoms recomposed into services
    events/             # Event handlers wrapping atoms
    middleware/          # Middleware wrapping atoms
    infrastructure/     # Introduced algorithms (retry, circuit breaking)
  analysis/             # Computed artifact. Lineage table, pin map, adjacency graph.
```

### Promotion Between Branches

Changes flow **upward** from algorithmic to architectural:

1. **New plan** → add pseudocode comments in `algorithmic/`
2. **Translate** → comments become code in `algorithmic/`
3. **Pin** → extract atom functions into `atoms/` (shared)
4. **Project** → recompose atoms in `architectural/` with architectural patterns
5. **Verify** → run tests in both branches; analysis detects drift

Changes flow **downward** when architecture reveals algorithmic issues:

1. Architectural integration test fails
2. Trace pin back to algorithmic atom
3. Fix atom function (shared, so algorithmic layer updates too)
4. Re-verify both layers

### Collapsing Untracked Systems to Layer 1

When ingesting an existing codebase that has no layer separation: **collapse it to Layer 1**. Treat all existing code as a spec. Extract the algorithmic intent (what it does, stripped of architectural concerns) and represent it as algorithmic code with architecture removed. This is the reverse operation — from architectural code to algorithmic code + pins.

---

## 7. Executable Gap Detection

### Run the Code, Don't Theorize

The biggest power play of edit-in-place: **you can run the algorithmic code to detect gaps** instead of statically analyzing text for missing pieces.

### Comment Detection

```python
import ast, tokenize

def find_unimplemented(filepath):
    """Every comment in algorithmic code is an unimplemented spec element."""
    gaps = []
    with open(filepath) as f:
        for tok in tokenize.generate_tokens(f.readline):
            if tok.type == tokenize.COMMENT:
                gaps.append(Gap(
                    file=filepath,
                    line=tok.start[0],
                    text=tok.string.lstrip("# "),
                    type="unimplemented_comment"
                ))
    return gaps
```

This is **mechanically verifiable**. No LLM inference needed. No heuristics. Comments = gaps. Period.

### Stub Detection

Functions that exist but don't do real work:

```python
def detect_stubs(filepath):
    tree = ast.parse(open(filepath).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if is_stub(node):  # contains only pass, raise NotImplementedError, or ...
                yield Gap(file=filepath, line=node.lineno,
                         text=node.name, type="stub_function")
```

### Runtime Gap Detection

Run the algorithmic code with test inputs. Functions that raise `NotImplementedError` or return sentinel values are gaps. Functions that succeed are implemented. Coverage tools show which paths are exercised.

```python
# This IS a gap — it will fail at runtime
def charge_card(payment, amount):
    raise NotImplementedError("charge_card: integrate with payment gateway")

# This is NOT a gap — it runs
def validate_payment(payment_data):
    return payment_data["amount"] > 0
```

### Call Graph for Adjacent Details

After running, build a call graph. Two subgraphs that are disconnected in the UNION of (call graph + event graph) are truly isolated. But disconnected subgraphs in only the call graph may be connected via events, shared stores, or other architectural bridges.

This is how we detect adjacent details we might have missed: if algorithm A writes to a store and algorithm B reads from it, they are adjacent even if they never call each other.

---

## 8. Hollowed-Out Complete Specs as Evidence

### The Problem

When we receive a complete specification document (PRD, design doc, requirements), it contains far more detail than we need at any given moment. But we can't throw it away — agents will hit ambiguities that the spec already answers.

### The Solution: Hollow and Research

1. **Hollow out** the complete spec: extract the high-level structure (sections, headings, key entities) but don't try to process every detail upfront
2. **Use as evidence store**: when an agent hits an ambiguity during translation, perform needle-in-haystack research against the complete spec
3. **If no answer exists**: expand the spec (the ambiguity reveals a genuine gap in the requirements)

```
Agent translating: "# validate payment against fraud rules"
    → What fraud rules? Check amount? Check velocity? Check country?
    → Search complete spec for "fraud" + "payment" + "rules"
    → Found: Section 4.2.3 specifies velocity check + country blacklist
    → Translate with found details
```

### Trade-off: Adjacent Detail Loss

The risk: by not processing the full spec upfront, we may miss adjacent details (things that are related but not obviously connected). Mitigation:

- **Call graph analysis** after translation detects missing connections
- **Store touch analysis** finds algorithms that share state
- **Disconnected graph detection** flags isolation that may indicate missed adjacency
- **Iterative deepening**: each translation pass may reveal new adjacencies that trigger more spec research

---

## 9. Horizontal and Vertical Slices

From ALGORITHM.md Phase 8:

```
system/                       # Root vertical (the system)
  algorithms/                 # Horizontal: business logic
  stores/                     # Horizontal: persistent state
  shapes/                     # Horizontal: pure logic
  children/                   # Sub-verticals (components)
    payments/
      algorithms/             # Payment-specific algorithms
      stores/                 # Payment-specific stores
      shapes/                 # Payment-specific shapes
      children/
        fraud_detection/
          ...
```

**Vertical slices** = Components with state/lifecycle (entities). Each vertical owns its algorithms, stores, and shapes.

**Horizontal slices** = What exists INSIDE a vertical. The base level (algorithms, stores, shapes) is the first horizontal. Architecture adds more horizontals (events, middleware, routing).

**Recursive structure**: horizontal -> vertical -> horizontal -> vertical, as deep as needed.

**Store monogamy** (ALGORITHM.md 8.16): Every store lives inside ONE vertical slice. All other slices access it via algorithms (symbols), never directly. This prevents architectural fragmentation of data access.

### Navigating Layers

Each horizontal layer within a vertical is a projection. You can navigate:
- **Down** (toward algorithms): strip architecture, see business logic
- **Up** (toward architecture): see how business logic is deployed
- **Across** (between verticals): see component boundaries

Pin-functions are the navigation mechanism. Follow a pin from algorithmic layer up to its architectural locations. Follow a pin from architecture back down to its algorithmic origin.

---

## 10. Detecting Adjacencies and Disconnected Graphs

### The Problem

Adjacent details (things that are integrated with each other) can be missed if they aren't explicitly connected. Two algorithms that interact through an event bus appear disconnected in a static call graph.

### Using ALGORITHM.md's Coupling Analysis (Phase 2)

**Entity co-occurrence** (2.1): Algorithms tagged within the same evidence window form weighted edges. If `validate_payment` and `apply_discount` are discussed in the same section of the spec, they're likely adjacent.

**Store touch edges** (2.3): If two algorithms touch the same store (database table, queue, file), they're coupled even if they never call each other.

**Reference edges** (2.2): Explicit references between algorithms.

Combined, these three signals detect adjacency even when architecture has hidden the connections behind event buses and middleware.

### Call Graph + Event Graph = Complete Graph

From the algorithmic layer, build a direct call graph. From the architectural layer, build an event flow graph (who publishes to what topic, who subscribes). Union of both graphs reveals the complete dependency picture. Disconnected subgraphs in the UNION are truly isolated. Disconnected subgraphs in only the call graph may be connected via events.

---

## 11. Lineage Tracking Through Destructive Transformation

From EVOLUTION_PLAN.md 2.1.2:

```python
class LineageEdge:
    from_unit: str        # Algorithmic atom ID (pin-function name)
    to_unit: str          # Architectural location (file:class.method)
    transformation: str   # "pass_through", "event_bridge", "middleware_wrap", "retry_decorate"
    confidence: float     # 1.0 for mechanical (import), <1.0 for inferred
```

The transformation field records HOW the atom was projected into architecture. This enables:
- "Show me all architectural locations for this algorithm" (forward trace)
- "Show me what algorithm this middleware implements" (backward trace)
- "What transformation was applied?" (the projection type)

### Projection Types (from ALGORITHM.md Phase 5)

| Type | Description | Example |
|------|-------------|---------|
| Pass-Through | Architecture imports and calls atom directly | `handler.validate = validate_payment` |
| Projection/Slice | Architecture uses subset of atom's output | `event.payload = result.status` (drops details) |
| Aggregation/Smear | Architecture combines multiple atoms | `handler combines validate + discount into one event` |
| Introduction | Architecture adds new algorithm (no source atom) | `retry_policy`, `circuit_breaker` |

### Data Flow Projections

From ALGORITHM.md Phase 5: data signals live IN algorithms, not separate. Each step tracks signals in, signals out, stores touched.

**Data signal tracing through architecture:**

In the algorithmic layer, data flows are direct:
```python
def process_order(order):           # signal in: order
    result = validate(order)        # signal: order -> result
    discount = apply(order, result) # signal: order+result -> discount
    return charge(order, discount)  # signal out: charge_result
```

In the architectural layer, the same data gets projected differently:
- **Pass-Through**: event carries entire `order` unchanged to next handler
- **Projection/Slice**: event carries only `order.id` and `result.status` (data is lost between hops)
- **Aggregation/Smear**: event combines `validate_result + discount_result` into single payload

Each hop in the architectural data flow is a **data projection** that can be pinned back to the algorithmic data flow. When architecture slices data (drops fields between events), that's detectable — the algorithmic layer expected the full object, but the architectural projection only passes a subset.

**Store signal tracing** (ALGORITHM.md Phase 5.3): For each store, understand what signals go IN so when we read, we can trace signals back. This applies at both layers — the algorithmic store writes are direct, the architectural store writes may be fragmented across event handlers.

### Drift Detection via Pins

When an algorithmic atom changes:
1. Find all pins (imports/references) pointing to it
2. For pass-through: change propagates automatically (same function imported)
3. For wrapping: check if the wrapper still correctly wraps the new version
4. For smearing: check if the aggregation still makes sense with the new atom
5. Flag mismatches as drift gaps with the lineage edge that connected them

Pin-functions make this deterministic: grep for imports of the changed function → those are the affected architectural locations.

---

## 12. Compliance Gating and Quality

From implementation Phase E: don't project into architecture until the algorithmic layer passes quality thresholds.

### Gate: Algorithmic Layer Must Be Clean

Before projecting (promoting) from algorithmic to architectural branch:
- **No remaining comments** (all pseudocode translated)
- **No stub functions** (all atoms implemented)
- **All tests pass** at the algorithmic level
- **Call graph is connected** (no orphaned algorithms)
- **Store monogamy enforced** (each store in one vertical)

### Code Quality via Function Recomposition

Pin-functions create atom-level code that both layers share. But the architectural layer introduces its own composition patterns that may duplicate logic or create unreadable structures. Quality gates at the architectural layer:

- **No inlined atom logic** — if it's an atom, it must be a function call, not copy-pasted code
- **Pin coverage** — every architectural location must pin back to an algorithmic origin (except introduced algorithms)
- **Introduced algorithm specs** — architectural algorithms (retry, circuit breaking) that have no algorithmic origin must have their own spec comments (they are their own mini algorithmic layer for infrastructure)

### Provenance Tracking (from Implementation Phase A)

Each atom function carries provenance:
- `introduced_by`: which plan/patch added it
- `modified_by`: chain of changes
- `source_location`: where in the spec research the details came from

This enables "why does this code exist?" queries at any point.

---

## 13. The Analysis File as Computed Artifact

The analysis file explains HOW algorithms map to architecture. Rather than manually maintaining it, generate it from the pin-function import graph + lineage table:

```
For each algorithmic atom (pin-function):
  - List all architectural imports (forward trace)
  - List the projection type for each (pass-through, wrap, smear)
  - List co-occurrence and store-touch edges (adjacencies)
  - Flag any atoms with no architectural imports (unimplemented in architecture)
  - Flag any architectural code with no atom imports (undocumented/orphaned)
  - Show data flow: what goes in, what comes out, what stores are touched
```

This makes the analysis file a **projection** of the import graph — always up to date (regenerated on demand), never manually maintained, never drifting.

The analysis file is the **roadmap** between layers. When architecture changes, regenerate. When algorithms change, regenerate. The file itself has no state — it is always computed from the current state of both branches.

---

## 14. Strategy-Driven Processing (from Implementation Phase B)

When the system encounters something it cannot handle during translation or projection, it does not fail — it evolves.

### Strategy Evolution Loop

1. Agent attempts to translate a pseudocode comment into code
2. Translation fails (ambiguous, missing context, conflicting requirements)
3. System captures the failure as a **strategy gap** (first-class evidence)
4. System proposes a new strategy to handle this class of failure
5. New strategy is registered as experimental
6. Retry with new strategy
7. If successful, strategy is promoted to permanent

### Key Strategies

From implementation Phase B, adapted for the new paradigm:

| Strategy | When | What |
|----------|------|------|
| Sentence Decomposition | Comment describes multiple things | Split into separate comments |
| Entity Resolution | Comment references "the algorithm" | Resolve to specific function name |
| Ambiguity Research | Comment has insufficient detail | Search hollowed-out spec for details |
| Adjacency Detection | New code touches shared stores | Flag connected algorithms for review |
| Stub Promotion | Stub function has enough context | Translate stub into real implementation |

---

## 15. Open Questions

1. **Introduced algorithms**: Architectural algorithms (retry, circuit breaking) have no algorithmic origin. They need their own specs. Current proposal: treat them as a separate algorithmic layer (infrastructure algorithms vs business algorithms), each with their own edit-in-place lifecycle.

2. **Testing as anchor**: Can contract tests at system boundaries serve as a verification that pins are still valid? If tests pass, pins are correct. If tests fail, some pin has drifted. But test signatures can change when algorithms change — this verification is helpful but not complete.

3. **Pseudocode completeness beyond comments**: The "no comments in production" rule detects explicit gaps. But what about implicit gaps — things the spec mentions that have no corresponding atom at all? Mitigation: coverage comparison between hollowed-out spec entities and existing atom functions. Any spec entity with no atom = implicit gap.

4. **Granularity of pin-functions**: How small should atoms be? Too small → function explosion, unreadable. Too large → architectural projections can't cleanly wrap them. Heuristic: an atom is one logical step that would be described in one pseudocode comment.
