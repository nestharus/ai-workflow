# Fractal Scoping

A problem that is too large to solve correctly as a whole can be solved
correctly at smaller scopes and composed. The solution quality at each
scope is bounded by the scope's complexity — smaller scopes have fewer
interacting concerns and therefore fewer opportunities for error.

The same problem structure recurs at different scales. A system composed
of libraries has the same structural concerns (cohesion, coupling,
contracts) as a library composed of components, as a component composed
of functions. The solution approach at each scale is the same approach
applied to a smaller problem.

The failure mode is the big-bang: attempting to solve the entire problem
in one pass. Big-bang solutions must reason about all interactions
simultaneously. The number of interactions grows combinatorially with
scope. A single reasoning pass over the full space will miss interactions
that scoped reasoning would catch.

---

## Work at the smallest self-contained scope

The smallest scope that contains all the information needed to make a
decision is the right scope for that decision. Smaller scopes have fewer
variables, fewer interactions, and fewer ways to be wrong. A decision
about how a single library is internally organized depends on that
library's responsibilities — not on the entire system's architecture.

Scoping too broadly means reasoning about irrelevant concerns, which
introduces noise and increases error probability. Scoping too narrowly
means missing dependencies — the decision is incomplete because relevant
information was excluded.

The question: what is the minimum context needed to make this decision
correctly?

---

## Compose scoped results rather than decomposing global solutions

Build up from small, correct pieces rather than breaking down a large,
approximate whole. Each piece is solved within its scope, verified within
its scope, and then composed with other pieces.

Composition requires explicit interfaces between scopes — what each scope
produces, what it expects, and what contracts it guarantees. The
interfaces are the points where scoped solutions meet. If the interfaces
are well-defined, the scoped solutions are independently correct and the
composition is a matter of connecting them.

Top-down decomposition imposes structure before the parts are understood.
Bottom-up composition lets structure emerge from what the parts actually
need. The imposed structure may not match reality. The emergent structure
necessarily does.

---

## Within a scope, focus on atomic units

Inside a scope, the concern is the individual units — their
completeness, their correctness, their internal coherence. What does each
unit do? Is it well-defined? Does it have a single responsibility?

This is the cohesion problem. Units within a scope should be cohesive —
each one does one thing, and everything it needs to do that thing is
contained within it. Cohesion is maximized by focusing on individual
units and making each one self-contained.

---

## Between scopes, focus on relationships

Across scope boundaries, the concern is not the units themselves but how
they interact. What data flows between scopes? What are the dependency
directions? What contracts exist at boundaries? What assumptions does
each scope make about the others?

This is the coupling problem. Scopes should interact through explicit,
minimal contracts. The less one scope knows about another's internals,
the more independently they can evolve.

Within a scope: maximize cohesion (make each unit complete).
Between scopes: minimize coupling (make interactions explicit and narrow).

---

## Apply the same process at every scale

If the process for handling a single library works — scope it, analyze
its units, verify its contracts, promote its output — the same process
works for a component within a library, and for the system as a whole.

Processes that work at one scale but not another indicate that the
process is coupled to the scale rather than to the problem. A
verification process that works for small inputs but breaks for large
ones is not a verification process — it's a special case that happened
to work on small inputs.

Scale-invariant processes are reusable, testable, and composable. They
can be applied at whatever scope the current problem requires without
modification.

---

## Scope decisions proportionally to their impact

A decision that affects one function within one library needs reasoning
at function scope. A decision that affects how multiple libraries
interact needs reasoning at inter-library scope. A decision that affects
the entire system's communication pattern needs reasoning at system scope.

The scope of reasoning should match the scope of impact. Reasoning at
system scope for a function-level decision wastes effort and introduces
irrelevant concerns. Reasoning at function scope for a system-level
decision misses the interactions that matter.

The question is always: what is the blast radius of this decision? The
blast radius determines the scope.

---

## Avoid mixing scopes in a single pass

When a single operation tries to reason about both the internal structure
of individual units and the relationships between units, it conflates
two different concerns. The internal structure depends on the unit's
responsibilities. The relationships depend on the system's architecture.
These are different problems with different inputs.

Separating scope-levels into distinct passes — first analyze units, then
analyze relationships — ensures that each pass has focused context and
produces clean output. Mixing them produces output that is partly about
units and partly about relationships, where neither concern is fully
addressed.
