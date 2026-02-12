# Error Amplification

The cost of an error is not constant. It grows with the distance between
where the error was introduced and where it is detected.

An error caught at its point of origin costs the fix. The same error
caught one stage downstream costs the fix plus rework of everything built
on the wrong output. At three stages, it requires unwinding an entire
chain of dependent work. At five stages, it may require discarding a full
body of work and starting over.

This is not linear growth — it is at minimum multiplicative. Each stage
adds work that depends on the error's output. Each piece of dependent
work must be identified, assessed, and either corrected or discarded.
The further the error traveled, the more dependent work exists.

---

## Check quality in sequential gates, not one final pass

Pass work through a sequence of checks, each addressing one quality
dimension. Each gate catches problems in its dimension before they
compound into the next. Work advances only when the current gate passes.
Failed work returns to the appropriate stage for correction.

The alternative — a single comprehensive check at the end — maximizes
propagation distance. Every error that an intermediate gate would have
caught instead travels to the end, where it arrives entangled with all
the downstream work built on it.

Gate ordering matters: put the gates most likely to fail, and cheapest
to correct, earliest. This catches the highest volume of errors at the
lowest cost.

---

## Surface errors immediately, don't absorb them

When a process receives invalid input or produces invalid output, it
must signal the error. Substituting a default value or silently
continuing hides the error — it still propagates, but now invisibly.

A default value that masks an error is a form of reward hacking: the
system's metrics look correct even though its behavior isn't. The error
still exists; it has merely been made undetectable until it surfaces
downstream in a more confusing form.

---

## Trace problems to their root cause

The visible symptom of an error may be several stages removed from the
actual cause. Fixing the symptom leaves the cause intact, where it will
produce more symptoms — possibly different ones that are harder to trace.

The question: why did this happen? What assumption was wrong? What would
have prevented this from occurring in the first place? The answer is
usually not at the stage where the symptom appeared.

---

## Assess blast radius before changing anything

Before making a fix, understand everything that depends on what you're
changing. A concept, data structure, or interface may be used in many
places. Changing it without updating all dependents creates new
inconsistencies — which are themselves errors that will amplify through
propagation.

The question: if I change X, what else depends on X? What would break?
What needs to be updated in parallel?

---

## Propagate fixes to all affected consumers

A fix that updates one artifact but not the others that depend on it
creates inconsistency. After fixing a root cause, identify and update
every downstream consumer: test expectations, validation criteria,
documentation, dependent artifacts, and any cached state derived from
the changed artifact.

An incomplete fix is a new error introduced at the point of the fix,
which then amplifies through all the consumers that weren't updated.

---

## Chain outputs forward through the pipeline

In a pipeline, each step consumes the output of the previous step — not
the original input. If step 2 uses the original input instead of step 1's
output, it operates on a state that doesn't exist in the real pipeline.

When a step is re-run after a fix, all downstream steps must also re-run.
Their prior outputs were derived from the old input and are now stale.
Skipping re-runs leaves downstream artifacts built on the wrong version —
errors that will surface later.

---

## Verify incrementally, not just at the end

Running an entire multi-step process and checking only the final output
misses intermediate failures. A bug at step 3 corrupts step 4's input,
which produces confusing output that looks like a step 4 problem. Verify
each step's output before feeding it forward.

---

## Classify error types before choosing a response

Not all failures have the same cause, and the correct response depends
on the cause.

A transient failure — an LLM returning malformed output due to
non-deterministic generation — responds to retry. The same input will
likely produce correct output on the next attempt.

A systematic failure — an agent consistently misunderstanding its
instructions — does not respond to retry. The instruction must be
changed. Retrying the same broken input will produce the same broken
output.

A dependency failure — a unit that cannot proceed because it awaits
another unit's output — is neither transient nor systematic. Retrying is
waste. Waiting for the dependency to resolve is the correct response.

Applying the wrong recovery strategy wastes resources (retrying a
systematic failure) or causes deadlock (waiting on a permanently failed
dependency).

---

## Don't note problems without fixing them

Recording a problem and moving on means the problem contaminates all
subsequent work. Future steps build on the flawed output, amplifying the
error. Fix each problem when it's found, while context is fresh and the
blast radius is small. The cost of fixing now is always less than the cost
of fixing later, because later includes all the dependent work built on
the error.
