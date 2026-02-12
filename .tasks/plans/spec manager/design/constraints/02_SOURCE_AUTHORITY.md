# Source Authority

In any chain of transformations, each stage derives from the previous one.
The stage closest to the original input has the highest fidelity to the
source truth. Each subsequent transformation introduces the possibility
of distortion — through lossy summarization, format conversion,
reinterpretation, or error.

When two stages disagree about what the truth is, the one closer to the
source wins. Authority — the right to be believed when representations
conflict — decreases with derivation distance.

---

## Derived representations cannot override their sources

A view, summary, report, or higher-layer artifact must be regenerable
from its source. If someone edits a derived artifact directly, that edit
is drift — evidence that something might be wrong, not an authoritative
change.

If derived layers can override sources, there are now two sources of
truth that can conflict. Every consumer must decide which to believe.
The system loses its single point of authority and all the consistency
guarantees that come with it.

---

## Fix problems at the layer that has authority over them

When a problem manifests at one layer but originates at a lower layer,
patching the symptom at the higher layer is waste. The patch will be
overwritten on the next derivation cycle. Worse, it masks the real
problem — the symptom disappears but the cause remains, producing new
symptoms elsewhere.

The question: does this layer have the authority to make this change, or
did the problem originate closer to the source? If the answer is "closer
to the source," the fix belongs there.

---

## Don't invest in derived work while the source is changing

Working on higher-layer concerns — architecture, style, optimization —
while lower-layer concerns — correctness, completeness — are still in
flux, is building on unstable ground. Changes at the lower layer
invalidate the higher-layer work.

Sequential stabilization from source outward minimizes this waste. Each
layer stabilizes before the next layer begins serious work. The cost of
waiting is small compared to the cost of reworking derived artifacts after
their source changes underneath them.

---

## Don't maintain parallel representations of the same truth

When the specification and the implementation are separate artifacts, they
drift. The specification says one thing, the implementation does another,
and reconciliation is expensive. When the artifact being worked on carries
its own specification — as embedded comments, contracts, or annotations —
the plan and the reality are one thing. Drift is structurally impossible.

The general principle: wherever two representations of the same truth
exist, they will eventually disagree. Eliminate the duplication by making
one the single authority and deriving the other, or by collapsing them
into one artifact.

---

## Bridge layers through explicit projections

When information crosses a boundary between layers or stages, explicit
projection types define what crosses and how it is assembled on the other
side. The projection is a derived view — read-only, regenerable from its
source layer.

Layers that reach into each other's internal representations are coupled
to those representations. Changes to one layer's internals cascade
unpredictably into others. Projections are the stable interface between
layers — they can evolve explicitly without either layer needing to know
the other's internals.
