# Proportional Commitment

The quality of a solution is bounded by the quality of the problem framing,
not by the quality of the implementation within the frame. A solution that
is correct within the wrong frame is wrong.

Before committing to any interpretation, approach, or structural assumption,
explore the dimensions along which the problem varies. Then calibrate the
specificity of each decision to the certainty of the knowledge behind it.

Every decision narrows the space of possibilities. Narrowing based on
knowledge is efficiency — it eliminates irrelevant paths. Narrowing based
on assumption is debt — it excludes paths that may be relevant, and the
cost of discovering this grows with every dependent decision built on the
assumption.

The failure mode is frame fixation: committing to the first plausible
interpretation without asking what other interpretations exist, what
dimensions of variation haven't been explored, or what assumptions are
being made that haven't been tested.

---

## Match method to certainty

The tool you use to interpret something should reflect how much you know
about its structure. When you defined the format and control it completely,
deterministic parsing is appropriate — you have full knowledge and can
commit to a specific structural interpretation. When the format comes from
outside and you don't control it, inference is appropriate — you have
incomplete knowledge and must handle unbounded variety.

This is not a preference. It's a consequence of what you know. Deterministic
tools on uncontrolled input are overcommitments — they assume structure that
isn't guaranteed. Inference on well-defined internal formats is waste — it
explores a space that has already been fully mapped.

---

## Abstract what you chose, commit to what the problem requires

When a decision is dictated by the problem ("the spec says use git"), the
system can depend on it directly — it's a requirement, not a choice. When
a decision is arbitrary ("we chose this storage backend"), it could change.
Arbitrary choices must be behind abstractions so that changing them doesn't
cascade through the system.

The distinction: requirements are knowledge (they won't change because
you want them to). Choices are assumptions (they can change when
circumstances do). Commitment to requirements is safe. Commitment to
choices is debt proportional to how deeply the choice is embedded.

---

## Keep structure as flexible as the input demands

When you don't know whether the input will have classes, modules, traits,
or packages, the data model must accommodate all of them. A rigid type
that assumes specific constructs is a commitment to one structural form —
it works for the case you imagined and breaks for every other.

The generality of the model should match the actual variation in the input.
If input genuinely has one form, a specific type is correct. If input
varies, the type must be dynamic enough to represent the variation. The
question is always: what do I actually know about how this varies?

---

## Operate at the level that doesn't change

When cases differ in their surface details but share common structure at a
higher level, operating at the higher level makes the solution invariant
across cases. Relationships between things are often stable even when the
things themselves vary. The dependency graph of a system has the same
structure regardless of the programming language — even though the syntax
for expressing dependencies differs completely.

Operating at a level that varies across cases means rebuilding the solution
for every new case. Operating at a level that is invariant means building
it once.

---

## Plan only as far as current understanding reaches

A detailed plan is a commitment to a sequence of steps. If the later steps
will change as you learn from the earlier ones, the detail invested in
planning them is waste. Plan enough to take the next step. Execute. Learn.
Plan the next step from what you learned.

This is not imprecision — it's calibrated commitment. Planning far ahead
is appropriate when you have deep knowledge of all the steps. Planning
incrementally is appropriate when each step reveals information that
changes the plan.

---

## Surface ambiguity rather than resolving it silently

When the available information doesn't determine a unique interpretation,
choosing one silently is an assumption dressed as a fact. Every downstream
consumer treats the chosen interpretation as given. If it was wrong, the
error cascades through every dependent decision.

The cost of surfacing an ambiguity is one question. The cost of unwinding
a wrong silent assumption grows with every decision built on it. Blocking
on ambiguity is not overcautious — it is economically rational.

---

## Don't treat unverified output as knowledge

Automated output — from an LLM, a script, an agent — has not been verified.
Treating it as established fact is committing to its correctness without
evidence. It must pass validation before it enters the body of trusted
information. Invalid output is rejected, not silently accepted with
defaults.

---

## Require evidence before changing strategy

Changing how the system operates — new algorithms, new model configurations,
new quality criteria — is a commitment to the new approach. Without
evidence that the new approach produces better outcomes than the old one,
the commitment is unjustified. At minimum: a test suite that both
strategies can be evaluated against, and comparison on the same inputs.

---

## Assess only from complete, stable state

Drawing conclusions from partial or in-flux state is deciding with
incomplete knowledge. Issues found may resolve themselves when the
remaining work completes. Issues present may be invisible until the full
picture is available. Quality assessment should wait for natural
completion boundaries where the state being assessed is whole and stable.
