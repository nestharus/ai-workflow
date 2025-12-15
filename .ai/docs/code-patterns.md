1. Building blocks (closed set)
   Process primitives

Extractor — derives structured facts/fields from an input.

Transformer — maps input → output (reshape/convert/enrich; may be lossy or lossless).

Validator — asserts invariants; raises/returns invalid.

Filter — keeps/discards items or fields based on a predicate.

Reducer — folds many → one (aggregate, combine, summarize).

Control-flow primitives

Orchestration — explicit step-by-step calls; no internal branching/loops (except allowed guard exits).

Guard clause — early exit at the top (return/raise) when precondition fails.

Condition — named predicate (a boolean check treated as a reusable unit).

Router / Dispatcher — table-driven selection of a path/handler/strategy based on keys/conditions.

Traversal — applies a function across a structure/collection/stream (walk/visit/map).

Middleware — “around” wrapper for cross-cutting behavior (pre/post, intercept, error boundary).

State & coordination primitives (needed for real systems)

State store — read/write state (in-memory, DB, cache); defines consistency boundary.

Side-effect boundary — a declared external interaction point (IO, network, filesystem, clock).

Message / Event envelope — standardized unit of work (id, type, payload, metadata).

Idempotency key — stable key ensuring repeated work is safe.

Clock / scheduler — time source and scheduling trigger (explicit, injectable).

Resiliency primitives (typically middleware)

Exception boundary — where exceptions are caught/translated (often middleware).

Retry policy — retry rules (max attempts, backoff/jitter, retryable classes).

Timeout — time budget on an operation.

Circuit breaker — stop calls when dependency is unhealthy.

Bulkhead / concurrency limit — isolate and cap resource usage.

Rate limiter — cap request rate.

Fallback — alternate behavior when primary fails.

Dead-letter / quarantine — divert poison inputs for later inspection.

Compensation — explicit undo/mitigation step for partial work.

2. Specializations (derived from building blocks)
   Process specializations

Parser — Extractor that turns bytes/text into structured form (AST/model).

Normalizer — Transformer that canonicalizes representation (units, casing, schema).

Projector — Transformer that selects/reorders fields (often lossy).

Enricher — Transformer that adds data via lookup/compute (crosses side-effect boundary).

Resolver — Transformer that turns refs/IDs into concrete objects (often Enricher + Validator).

Annotator / Labeler — Extractor/Transformer that attaches derived tags/metadata.

Sanitizer / Scrubber — Filter + Transformer that removes/escapes unsafe content.

Serializer / Deserializer — Transformer between in-memory and wire/storage formats.

Formatter / Renderer — Transformer to human-facing representation (text/JSON view/UI model).

Deduplicator — Filter/Reducer that removes duplicates by key/hash.

Join / Merge — Reducer that combines sources (often keyed) into one representation.

Splitter — Transformer that turns one item into many (fan-out at data level).

Sorter / Ranker — Transformer/Reducer that orders items by comparator/score.

Sampler — Filter that selects subset by policy.

Control-flow specializations

Pipeline — Orchestration where each step consumes previous output.

Chain of Responsibility — Traversal over handlers with stop/continue policy (guards).

Fan-out / Fan-in — Traversal to scatter work + Reducer to gather results.

Scatter–gather — fan-out to sources + fan-in merge (often with Router/Dispatcher).

Map–reduce — Traversal(map) + Reducer(reduce).

State machine — Router/Dispatcher keyed by state + Validator for legal transitions.

Strategy selection — Router/Dispatcher chooses an algorithm implementation.

Template skeleton — Orchestration with injected step implementations (via router).

Workflow / Saga — Orchestration + state store + compensation + resiliency middleware.

Event consumer loop — Traversal over messages + dispatch + ack/retry middleware.

3. Design patterns (canonical library)
   Creational (GoF)

Factory Method — subclasses supply the concrete product; construction deferred.

Abstract Factory — create families of related objects without specifying classes.

Builder — stepwise construction of complex object; separates build process from representation.

Prototype — create by cloning an existing instance/template.

Singleton — ensure exactly one instance (or one per scope) with controlled access.

Structural (GoF)

Adapter — translate one interface to another expected interface.

Bridge — separate abstraction from implementation so both vary independently.

Composite — tree structure where single and group are treated uniformly.

Decorator — wrap to add behavior without changing underlying type.

Facade — simplified interface over a complex subsystem.

Flyweight — share immutable state to reduce memory/creation cost.

Proxy — surrogate that controls access (remote, virtual, protective, caching).

Behavioral (GoF)

Chain of Responsibility — pass request along handlers until handled.

Command — encapsulate an action + parameters as an object (queue, log, undo).

Interpreter — represent grammar and evaluate expressions (DSL evaluation).

Iterator — traverse a collection without exposing internal representation.

Mediator — central coordinator to reduce many-to-many coupling.

Memento — capture/restore object state without exposing internals.

Observer — publish-subscribe notifications to dependents on change.

State — behavior changes with internal state (state objects/handlers).

Strategy — interchangeable algorithms selected at runtime.

Template Method — fixed algorithm skeleton with overridable steps.

Visitor — add operations to object structure without modifying element classes.

Concurrency / coordination (commonly used)

Active Object — method calls become queued tasks executed asynchronously.

Future / Promise — placeholder for async result.

Producer–Consumer — decouple producers from consumers via queue.

Reactor — event loop dispatching handlers (non-blocking IO).

Proactor — async completion events trigger continuations.

Thread Pool / Worker Pool — bounded workers execute tasks from queue.

Actor Model — isolated actors communicate via messages; no shared mutable state.

Semaphore / Mutex / RWLock — synchronization primitives controlling access.

Enterprise integration / architectural (widely used)

Layered Architecture — separate concerns into layers (UI/app/domain/infra).

Hexagonal / Ports & Adapters — domain core with inbound/outbound ports; adapters at edges.

Clean Architecture — dependency rule inward; entities/use cases at center.

MVC / MVP / MVVM — presentation separation patterns.

Repository — collection-like interface to persistence.

Unit of Work — batch changes into a single commit/transaction boundary.

DTO — transfer object for boundaries (API, service-to-service).

Service Layer — application services encapsulating use cases.

Dependency Injection — supply dependencies externally (constructor/provider/container).

Event-Driven Architecture — events drive reactions; producers decoupled from consumers.

Pub/Sub — broadcast events to subscribers (topic-based).

Message Queue — buffered async work distribution.

Saga — distributed transaction via steps + compensations.

Outbox — write DB + event record atomically; publish from outbox.

CQRS — separate write model (commands) from read model (queries).

Event Sourcing — persist as append-only events; rebuild state by replay.

API Gateway — single entrypoint routing to services; auth, rate limits, aggregation.

Circuit Breaker — stop calling failing dependency (resiliency pattern).

Bulkhead — isolate failures by partitioning resources.

Strangler Fig — incrementally replace legacy system by routing traffic to new components.

Blue/Green / Canary — deployment patterns for safe rollouts.