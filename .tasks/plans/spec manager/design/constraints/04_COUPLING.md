# Coupling

When component A encodes assumptions about component B's internal
structure, changes to B break A. The assumption is an invisible dependency
— it doesn't appear in any interface definition, any import graph, or any
contract. It exists only in A's implementation, discoverable only when B
changes and A breaks.

The more components that encode assumptions about each other's internals,
the more changes cascade unpredictably. A single change to one component
triggers failures in every other component that assumed the old internal
structure. The system becomes fragile in proportion to the density of
internal assumptions.

The alternative: components interact through explicit, stable contracts —
signal formats, projection types, interface definitions. Contracts are
visible, testable, and evolvable. Internals behind contracts can change
freely without affecting anything outside the contract boundary.

---

## Coordinate through signals, not direct calls

When agents or components need to coordinate, producers emit structured
signals describing what happened. Consumers subscribe to signal types and
react independently. The producer does not know who consumes. The consumer
does not know who produces. The signal format is the contract.

Adding a new consumer requires no change to the producer. Changing a
consumer's reaction logic requires no change to the producer. Both evolve
independently as long as they agree on the signal format.

Direct calls from producer to consumer create a dependency: the producer
must know who to call, with what arguments, in what order. Adding a
consumer means modifying the producer. Modifying a consumer's interface
means modifying every producer that calls it.

---

## Cross boundaries through projections, not internal access

When information needs to move between layers, stages, or components,
explicit projection types define what crosses and how. The projection is
a stable interface — it can be versioned, validated, and evolved without
either side knowing the other's internals.

Components that reach into each other's internal representations are
coupled to those representations. A change to how one component organizes
its data internally cascades into every component that reads that data
directly.

---

## Give each agent only the context it needs

An agent that receives the entire system state is coupled to the entire
system — it can (and will) develop assumptions about parts of the state
that are irrelevant to its task. When those parts change, the agent's
behavior changes in unpredictable ways.

An agent that receives only the information relevant to its task is
coupled only to that information. The coupling surface is minimal and
explicit. Irrelevant changes elsewhere in the system cannot affect it.

The narrower the context, the cheaper it is to run, the more focused the
output, and the fewer invisible dependencies exist.

---

## Match coordination richness to dependency complexity

Simple work with straightforward dependencies needs minimal
coordination — at most, blocking until inputs are available. Complex
work where multiple agents may discover mutual dependencies needs richer
coordination: dependency tracking, progress signaling, cycle detection.

Over-engineering coordination for simple work couples components through
coordination infrastructure they don't need. The infrastructure becomes
an invisible dependency — changes to the coordination mechanism affect
all participants, even the simple ones.

Under-engineering coordination for complex work fails to manage real
dependencies. Agents block on each other without knowing it, duplicate
work, or lose signals.

---

## Isolate each run's state from other runs

One run's artifacts must not leak into another run's workspace. If they
do, the second run is coupled to the first run's state — it may pass
because of leftover artifacts, fail because of stale state, or produce
unreproducible results that depend on which runs preceded it.

Cross-run sharing must be explicit and intentional — shared fixtures,
shared configuration. Accidental sharing through file system leakage is
an invisible coupling between runs.

---

## Bound every open-ended process explicitly

An operation that polls, retries, iterates, or waits for an external
condition is coupled to that condition. If the condition is never
satisfied, the operation runs forever — it has no internal reason to
stop.

Explicit bounds — maximum iterations, maximum time, maximum cost —
decouple the process from the assumption that the external condition
will eventually be met. When a bound is hit, the process stops and
reports why, rather than running indefinitely.

The bound is a contract with the rest of the system: this operation
will not consume resources beyond this limit, regardless of whether
its goal is achieved.
