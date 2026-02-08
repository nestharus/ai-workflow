# Phase 0 Research Response (Feb 8 2026)

External research response to PHASE0_RESEARCH_PROMPT.md. This is the
analysis that led to the "routing-based restructuring" conclusion in
CONSOLIDATION_CONCLUSIONS.md.

---

## What's wrong with the spec refinement algorithm (as stated)

### 1) It treats "refinement" like rewriting, but refinement is only allowed to be routing

Your constraint ("no extraction; summaries only for routing") implies:

* **The structured output must be built from *verbatim source spans*** (line ranges / blocks), not from paraphrases.
* "Refine" cannot mean "rewrite the content into shapes/algorithms."
  It can only mean "move/duplicate the exact text into the right buckets and wrap it with IDs."

Most refinement descriptions accidentally slip into "rewrite and label," which is extraction-by-another-name (even if you call it restructuring): you're generating new atomic representations and inevitably dropping details.

**Failure mode:** refinement drift. After a couple iterations, the refined spec becomes a lossy reinterpretation rather than a reorganization of the original.

### 2) It has no routing unit definition that preserves context *without chunking*

Even if you forbid extraction, the system still needs a **unit of movement**. If you don't define it, you'll implicitly fall back to:

* paragraph units (you already said this loses context), or
* overlapping windows (you said this fails), or
* semantic retrieval (embeddings / TF-IDF; you said this fails).

So the algorithm is missing a legal routing unit.

**What you actually need** is a *routing unit that is a contiguous span in the original files*, chosen to preserve context *and* stable enough to cover everything.

If the refinement algorithm doesn't define a routing unit, it can't be implemented without violating one of your constraints.

### 3) It has no formal notion of completeness ("accounted for") in a routing-only world

"Refine until all details are accounted for" is undefined unless you have a ledger like:

* **Every source line is either routed to >=1 output element, or explicitly marked "ignored" with a reason.**

Without that, you can't know whether you're done, and the system will (a) stop early while missing content, or (b) loop forever.

This is exactly why Design #1's membership guarantee exists. You don't need its full complexity, but you **do** need the concept.

### 4) It doesn't solve the invariant trap, because summaries/libraries don't solve it

Your hardest problem is still: **invariants vs mechanisms**.

* Libraries answer "*what area is this about?*"
* Categories answer "*what kind of statement is this?*"

Those are orthogonal. Library discovery alone cannot reliably separate:

* "must emit `step_start` / `step_stop`" (mechanism detail)
  from
* "must be able to reconstruct what happened" (invariant)

If refinement only routes based on summaries, it will systematically misroute constraint-language mechanisms into Constraints.

To fix it, the refinement step needs a **routing decision rule** that uses your reimplementation test *at routing time*.

### 5) Cross-file references break "summarize first" unless refinement can point into raw files

Because you can't load all files at once, and you can't use embeddings/TF-IDF to find referenced places later, the only stable solution is:

* When a cross-file reference is encountered, refinement must be able to record it as a **pointer to unresolved evidence** ("REF-STUB") and later resolve it to a **file + line range** once that file is processed.

If refinement can't create and resolve these pointer stubs, it will either:

* hallucinate the referenced content, or
* drop it, or
* incorrectly "summarize it away."

### 6) The recursion stopping rule is not operational

"Recurse until no more candidates" for sub-libraries is not measurable without:

* a coverage ledger, and
* a stability criterion ("library map stops changing while coverage stays 100%").

Otherwise recursion is either premature (misses structure) or endless.

---

## The key point

**Nothing is inherently wrong with "summaries -> libraries -> refinement."**
What's wrong is that the described refinement step is **underspecified for your constraints**.

It's missing three required operators:

1. **A legal routing unit** (contiguous source spans, not paragraphs/windows/embeddings)
2. **A routing ledger** (coverage = termination)
3. **A routing-time invariant test** (mechanism -> invariant mapping without paraphrasing)

---

## What "spec refinement" must mean under your constraints

If extraction is prohibited and summaries are only for routing, then refinement is:

> **Build a routing table that maps raw source spans (file, start_line, end_line) into structured destinations (library + category + element ID), then assemble output by verbatim copy.**

No paraphrase. No decomposition into atoms. No semantic retrieval.

### Minimal artifacts (file I/O friendly)

* `summaries/FILE.md`
  High-level only; used for routing. No details.
* `libraries.yaml`
  Emergent library buckets + short descriptions (from summaries).
* `route_table.jsonl`
  The *only* "refinement" output that matters.
  Each entry is a move/copy instruction:

  ```json
  {
    "route_id": "R-000812",
    "src": {"file": "tickets.md", "start": 410, "end": 487},
    "dest": {"library": "LIB-03", "bucket": "DETAIL/ALGORITHM", "element_id": "ALG-LIB03-014"},
    "notes": "Ticket lifecycle procedure; contains one invariant-like sentence at lines 412-413"
  }
  ```
* `coverage_ledger.jsonl`

  ```json
  {"file":"tickets.md","start":1,"end":1200,"status":"fully_routed","exceptions":[]}
  ```
* Output assembly is deterministic: apply the routing table and copy line ranges.

This is "restructuring," not extraction.

---

## Why summaries + libraries are still useful (but only as routing hints)

They're useful for:

* proposing initial library buckets,
* prioritizing where to route a span (which library),
* suggesting which bucket is plausible (overview vs details vs analysis),
* spotting likely cross-file reference targets ("this file seems to define the ticket schema").

They are **not** allowed to replace the source text in the final structured spec.

---

## The missing piece: routing-time classification that avoids the invariant trap (without extraction)

You can do this without extracting atoms by enforcing a *routing rule*:

### Routing rule (mechanism vs invariant) in a routing-only system

When deciding whether a span goes to Constraints vs Details:

* If the span's meaning survives a complete reimplementation **and it's stated as a general guarantee/principle**, route the span (or the smallest contiguous lines that contain the guarantee verbatim) to **Constraints**.
* If it's a mechanism (locks, event names, field names, ordering steps), route to **Details** and optionally add a **derived-invariant stub** (a pointer, not a paraphrase).

In other words:

* Constraints bucket contains **verbatim invariant lines** (when present).
* Details bucket contains **everything else** (including most MUST language).
* "Implied invariants" are handled as **stubs** unless/until you explicitly allow inference.

This stays inside your "no extraction" constraint.

---

## So what's the direct answer?

You *can* do summarizations, libraries, then refinement.
But the refinement algorithm (as currently described) fails because:

* It implicitly requires forbidden extraction (rewriting into structured shapes/algorithms),
* It has no legal routing unit under your no-chunk/no-overlap/no-retrieval constraints,
* It has no coverage ledger (so it can't converge or prove completeness),
* It doesn't embed the reimplementation test into routing decisions,
* It can't resolve cross-file references without pointer stubs,
* It has no operational stopping criterion.

If you redefine "spec refinement" as **routing-table construction + coverage closure + verbatim assembly**, then the pipeline becomes workable under your constraints.
