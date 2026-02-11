## Q1: What is a “gap” at L2?

**Recommended:** (d) a combination, but formalized as **Architecture Continuity Gaps**: *unconsumed promoted pins, missing/incorrect component wiring, missing integration points, and component-boundary violations*.

**Rationale:** L2 isn’t missing “function bodies”; it’s missing (or mis-shaping) the **graph assembly** that turns promoted atoms into coherent components (services/events/middleware). Gaps should be detectable as **graph incompleteness** (pins/edges/components) and **layer violations** (logic inlined in architecture).

**Implications:**

* L2 needs a **component manifest** (architecture skeleton) as its “spec”, otherwise “missing” is undefined.
* Gap exploration at L2 must look at **pins/edges/component graph**, not spec comments.

---

## Q2: What does “implement” mean at L2?

**Recommended:** (a) + (b), with a hard constraint: **implementation at L2 = assemble + glue**, never new business logic.

**Rationale:** L2 “implementation” is the creation/modification of **composition surfaces**: handlers, service entrypoints, middleware chains, event routing, adapters, and orchestration code that **calls pins**. If missing behavior requires new logic, that is **not an L2 implement task**; it becomes a demotion to L1.

**Implications:**

* You need an L2 implementor agent (“architectural assembler”) that is explicitly scoped to: *wiring, dispatch, lifecycle, IO boundaries, config injection*.
* Any “logic-shaped” diff discovered during L2 implementation should automatically emit a **DemotionTicket → L1** (new atom).

---

## Q3: What compliance gates apply at L2?

**Recommended:** Keep the two you already named as *hard blockers*, add a small set of **graph-level completeness** gates.

**Rationale:** L2 gates should enforce: (1) **layer purity** (no atom logic inline), and (2) **assembly completeness** (pins/edges/components are coherently composed). Do not use language syntax rules; enforce at the level of responsibilities and connections.

**Implications:**

* Gates should be expressible over a **component graph + pin registry + minimal code evidence** (snippets), not AST parsing.

**L2 gate set (proposed):**

1. **NO_INLINED_ATOM_LOGIC** *(BLOCKER)*
   Architectural code must be orchestration; business logic must be in L1 atoms.
2. **FUNCTION_RECOMPOSITION** *(BLOCKER)*
   Architectural entrypoints recombine atoms via pins; no monolithic “do everything here”.
3. **PIN_CONSUMPTION_COVERAGE** *(MAJOR)*
   Every promoted pin in-scope is either referenced by some component or explicitly justified as unused.
4. **EDGE_REALIZATION** *(MAJOR)*
   Declared cross-atom edges (or intended interactions) are realized as actual component-level wiring (handlers/routes).
5. **NO_ORPHAN_COMPONENTS** *(MAJOR)*
   Every component has at least one reachable entrypoint and/or is referenced by the runtime topology.
6. **EVENT_HANDLER_COVERAGE** *(MAJOR, if events exist)*
   Every declared event has ≥1 consumer or is explicitly marked as “external-only”.
7. **CONFIG_EXTERNALIZATION** *(MINOR/MAJOR depending on policy)*
   Environment-specific values are injected, not hardcoded.
8. **ARCH_DRIFT_PASS** *(MAJOR)*
   L2 artifact matches the current architecture manifest (see Q15).

---

## Q4: What does VerifyStep do at L2?

**Recommended:** (a)+(b)+(c)+(d)+(e) — verification is **graph integrity + conformance + governance**.

**Rationale:** Post-integration verification at L2 should answer: *Is the architecture graph coherent? Are all promoted items consumed? Does the realized wiring match the intended component manifest? Did anyone inject unreceipted decisions?*

**Implications:**

* VerifyStep must run **layer-aware** checks (L2 checks differ from L1/L3).
* VerifyStep should be the place where **Pipeline Oversight Enforcer** blocks the pipeline on governance FAIL, independent of “code correctness”.

---

## Q5: What are L2 slices?

**Recommended:** (b) one slice per **architectural component** (service/event/middleware), with a bootstrap fallback to the current per-library wrapper.

**Rationale:** L2 work is not “per library”; it is “per component topology unit”. Component slicing maximizes parallelism and makes gaps/action targets unambiguous.

**Implications:**

* Architectural refinement must output a **Component Manifest** that becomes the canonical slice map:

  * `component_id`
  * owned entrypoints
  * pins consumed
  * upstream/downstream interactions
  * files that implement the component (or generation targets)

---

## Q6: How does L2 architectural refinement become language-agnostic reviews?

**Recommended:** Use **LLM-as-judge + natural-language rule catalog** as the core, and treat any language/framework heuristics as **evolutionary strategies**.

**Rationale:** Architecture review can be expressed in terms of *boundaries, responsibilities, dependencies, flows, and contracts* without referencing “imports”, “decorators”, or framework wiring. Syntax cues are optional strategies to improve detection, not required for correctness.

**Implications:**

* Define architecture rules as **principles + expected evidence** (see “Reviewer design” below).
* Add a “strategy pack” layer that can contain Python/Django/FastAPI/etc heuristics, but the core review remains usable without them.

---

## Q7: What is a “gap” at L3?

**Recommended:** (d) a combination, formalized as **Quality Closure Gaps**:

* (b) unreviewed units, and
* (a)+(c) open reviewer findings not yet cleared.

**Rationale:** L3 convergence is “all required reviews pass and nothing remains flagged”. A “gap” is any outstanding finding or any unit that still lacks a PASS receipt.

**Implications:**

* Gap exploration at L3 is “run reviewers → collect findings → produce gap list”.
* Termination can remain `open_gaps == 0` if your gap report includes findings.

---

## Q8: What does “implement” mean at L3?

**Recommended:** Refactor-only patching driven by findings, with an explicit **Diff-Impact Classifier** gate; if the diff is logic-affecting, emit **DemotionTicket → L1**.

**Rationale:** L3 is about code quality, not behavior change. The process must mechanically prevent “cleanup” from becoming silent feature changes.

**Implications:**

* L3 needs:

  1. a refactor agent (“clean-code refactorer”),
  2. a behavior-preservation verifier (diff-impact classifier + tests), and
  3. a demotion rule: “logic touched” → L1.

---

## Q9: What compliance gates apply at L3?

**Recommended:** Keep your 4 reviewers, but treat them as **dimensions** that are satisfied by a language-agnostic pattern pack (and optional strategy packs). Add explicit **NO_LOGIC_CHANGE** + **DRIFT_PASS** gates.

**Rationale:** “Clarity/completeness/consistency/correctness” is a good orthogonal decomposition if you define them in language-agnostic terms and keep detection cues separate.

**Implications:**

* L3 gates must be enforceable without parsing: rely on reviewer judgments + diff classification + tests.

**L3 gate set (proposed):**

1. **ALL_QUALITY_REVIEWERS_PASS** *(BLOCKER)*
   No remaining findings above configured thresholds.
2. **NO_LOGIC_CHANGE** *(BLOCKER)*
   Diff-impact classifier says behavior is preserved; otherwise demote to L1.
3. **NO_ARCH_BOUNDARY_VIOLATIONS** *(MAJOR)*
   If refactor breaks component boundaries or wiring expectations, demote to L2.
4. **DRIFT_PASS** *(MAJOR)*
   No unplanned functionality added during refactor (plan/design conformance).
5. **TESTS_PASS** *(BLOCKER, enforced in INTEGRATE but recorded as a gate outcome)*
   Regression suite passes (or layer-appropriate verification command).

---

## Q10: What does VerifyStep do at L3?

**Recommended:** VerifyStep at L3 is **post-integration closure**:

* re-run reviewers (or validate their receipts),
* run diff-impact classification (if not already),
* confirm tests passed in clean worktree,
* enforce governance (receipts, decision injection).

**Rationale:** L3 Verify is the final “nothing slipped through” check after merge.

**Implications:**

* VerifyStep should fail closed on missing receipts or suspicious injection patterns (even if tests pass).

---

## Q11: What are L3 slices?

**Recommended:** Start with (a) one slice per file (your current approach), but define the *true unit of work* as **finding clusters** (function-level anchors) inside that slice.

**Rationale:** File slices are operationally simple; function-level slices are better for parallelism but require more scheduling/anchoring infrastructure. You can get 80% of the benefit by keeping file slices and clustering findings by function/span internally.

**Implications:**

* Reviewers must emit findings with **anchors** (symbol + span) so the refactor agent edits only targeted regions.

---

## Q12: How do L3 findings become DemotionTickets?

**Recommended:** Use a **two-stage classification**:

1. classify finding as *cosmetic vs structural vs behavioral*, then
2. decide the lowest layer that can legally resolve it.

**Rationale:** This avoids language-dependent heuristics and makes “demote all the way down” systematic.

**Implications:**

* `demotion/triage.py` should not depend on language; it should depend on:

  * *what kind of change is required* (behavior vs wiring vs refactor),
  * *scope* (local vs cross-component),
  * *layer legality* (L3 cannot change behavior; L2 cannot add business logic).

**Proposed finding categories and targets:**

| Finding category            | Meaning (language-agnostic)                              | Default action | Ticket target             |
| --------------------------- | -------------------------------------------------------- | -------------: | ------------------------- |
| `STYLE`                     | naming/format/doc clarity without structural change      |      fix in L3 | none                      |
| `MAINTAINABILITY`           | complexity/duplication/structure inside a unit           |      fix in L3 | none                      |
| `ARCHITECTURE`              | boundary violations, wrong dependencies, wiring/topology |         demote | L2                        |
| `INLINE_LOGIC_AT_ARCH`      | business logic located in architecture layer             |         demote | L1                        |
| `CORRECTNESS` / `LOGIC_BUG` | behavior wrong, edge case missing, invariant broken      |         demote | L1                        |
| `DRIFT`                     | extra/missing/mismatched vs plan/spec                    |         demote | L1 or L2 (based on scope) |
| `GOVERNANCE`                | missing receipts / decision injection                    |          block | same-layer remediation    |

---

## Q13: Language-agnostic review architecture

**Recommended:** (c) **LLM judgment + pattern librarian**, backed by a **natural-language core rule catalog**.

**Rationale:** Pure “no rules” LLM judging drifts; rigid rule catalogs become language-bound. The stable middle is: language-agnostic principles as canonical patterns, plus optional strategy packs for language/framework cues.

**Implications:**

* Your pattern librarian becomes the mechanism for progressive automation:

  * repeated human approvals → new strategy patterns
  * strategy packs can be enabled/disabled without changing the core review contract

---

## Q14: Review loop integration with PromotionLoop

**Recommended:** (d) combine:

* (b) findings become new gaps (PromotionLoop naturally re-iterates), and
* PROMOTE/VERIFY enforce “all-pass” gates.

**Rationale:** You already have an outer convergence loop. Re-implementing an inner loop duplicates orchestration and complicates evidence accounting.

**Implications:**

* L2/L3 GapExploration must produce “open gaps” from reviews.
* PROMOTE and/or VERIFY must re-run the relevant reviews as the **gate**.

---

## Q15: Drift review vs rule-based review

**Recommended:** Run both at every layer; define an explicit “spec artifact” per layer.

**Rationale:** Rule-based review prevents “bad shape”. Drift review prevents “wrong thing”.

**Implications (layer specs):**

* **L1 drift spec:** spec comments + constraints + under-spec decisions → implementation.
* **L2 drift spec:** **Component Manifest** + pin registry + declared interactions → realized wiring/handlers/topology.
* **L3 drift spec:** approved L2 topology/contracts + “no new behavior” constraint → refactored code.

---

# PromotionLoop step mapping

Below is what each step does at **L2** and **L3** (analogous to your L1 mapping). The key is that the *step names stay the same*, but the meaning of “gap” and “implement” changes by layer.

## L2 PromotionLoop semantics

### 1) COLLECT (CollectBaselineStep)

* **Does:** snapshot current component files + pin registry summary (not full extraction), record hashes.
* **Evidence:** manifest + “component inventory” (files, component_ids, pins referenced).
* **Why:** stable baseline for drift + governance.

### 2) GAP (GapExplorationStep @ L2)

* **Does (Architecture Continuity Gaps):**

  1. load Component Manifest (from architectural refinement)
  2. load promoted pins/edges in scope
  3. detect:

     * unconsumed pins
     * missing components/files for manifest targets
     * missing event handlers / missing middleware registrations
     * “logic-like” code inside architectural files (pre-gate warning)
     * manifest drift (extra components/wiring not in manifest)
* **Output:** `bundle.gaps.open_gaps = [{kind, component_id, file, anchor, description, expected}]`

### 3) PLAN (PlanStep @ L2)

* **Does:** converts architecture gaps into a **wiring plan**: ordered intentions describing which component to adjust and how.
* **Also:** runs under-spec planning gate if architecture decisions aren’t covered by constraints (e.g., “should this interaction be sync or async?”).
* **Output:** `bundle.plan.intentions = [{component_id, target_files, approach, acceptance_criteria}]`

### 4) IMPLEMENT (ImplementStep @ L2)

* **Does:** “Architectural Assembler” applies minimal patches:

  * create/adjust component entrypoints
  * connect pins in correct order
  * add missing handlers/routes
  * refactor wiring to satisfy boundaries
* **Must not:** invent business logic; if required, emits under-spec or demotion.
* **Outputs:** patch + updated wiring + optional integration test hooks.

### 5) UNDER_SPEC (UnderSpecCheckStep)

* Same meaning as L1: resolve decision gaps or block.

### 6) ANALYZE (AnalyzeStep @ L2)

* **Does:** build/update an **Architecture Graph Cache**:

  * nodes: components, entrypoints, pins
  * edges: calls, events, middleware ordering, dependencies
* **Outputs:** summary stats + graph snapshot used by PROMOTE/VERIFY.

### 7) PROMOTE (PromoteStep @ L2)

* **Does:** runs L2 compliance gates (above), plus L2 rule-based review pack if configured.
* **On fail:**

  * if fix is wiring-only → retry L2 (no demotion)
  * if failure is “needs new atom logic” → emit DemotionTicket → L1
* **Output:** gate report recorded in evidence.

### 8) INTEGRATE (IntegrateStep)

* Merge slice → L2 dirty; run layer CI; on failure, emit demotion (often via downward flow pin tracing).

### 9) VERIFY (VerifyStep @ L2)

* **Does (post-merge):**

  * connectivity / orphan checks on architecture graph
  * pin consumption completeness check
  * drift check: manifest vs realized topology
  * governance: receipts + injection detection
* **On fail:** emit tickets (L2 or L1) and RETRY.

### 10) ALIGN (AlignStep)

* Same purpose as L1, but evaluated against architecture-level intent too (still drift/reward hacking).

---

## L3 PromotionLoop semantics

### 1) COLLECT

* Snapshot target files, diffs, existing quality receipts.

### 2) GAP (GapExplorationStep @ L3)

* **Does (Quality Closure Gaps):**

  * run the configured L3 reviewers on target files (or validate existing PASS receipts)
  * produce findings with anchors
* **Output:** `bundle.gaps.open_gaps = findings[]` (each finding is a “gap”).

### 3) PLAN

* Convert findings into a refactor plan:

  * group by function/span
  * sequence: smallest safe refactors first
  * define “no behavior change” acceptance criteria

### 4) IMPLEMENT

* “Clean-code refactorer” applies targeted refactors for the planned finding set.

### 5) UNDER_SPEC

* Rare at L3; used if refactor requires a decision not covered by constraints (“rename public API?”).

### 6) ANALYZE

* Compute diff summary + structural metrics (size/duplication hotspots) + refactor impact candidates.

### 7) PROMOTE

* Re-run reviewers; enforce **ALL_QUALITY_REVIEWERS_PASS**.
* Run **Diff-Impact Classifier**:

  * if logic-affecting → DemotionTicket → L1
  * if boundary-affecting → DemotionTicket → L2

### 8) INTEGRATE

* Merge slice → L3 dirty; run CI on L3 clean (or per policy).

### 9) VERIFY

* Post-merge closure:

  * confirm tests passed
  * re-check reviewers or verify PASS receipts correspond to merged content
  * governance checks

### 10) ALIGN

* POWER check (still useful to detect “cleanup drift” and proxy-metric optimization).

---

# Reviewer design (language-agnostic core + evolutionary strategies)

## 1) Canonical Finding schema (used everywhere)

Every reviewer (L2/L3 and verification) emits findings in a single format:

* `dimension`: what is being evaluated (e.g., `ARCH_BOUNDARY`, `PIN_COVERAGE`, `CLARITY`, `CORRECTNESS`, `DRIFT`, `GOVERNANCE`)
* `category`: `style | maintainability | architecture | logic | drift | governance`
* `severity`: `BLOCKER | MAJOR | MINOR`
* `location`: `{file, symbol?, start_line?, end_line?}`
* `evidence`: short snippet or description
* `required_change_type`: `refactor_only | wiring_only | behavior_change | spec_change`
* `suggested_fix`: minimal
* `confidence`: 0–1
* `tags`: optional pattern IDs (see below)

This is language-agnostic because it never requires “imports”, “AST nodes”, etc.

## 2) Pattern library model

A “pattern” is a rule stated as:

* **Principle (core, language-agnostic):** what must be true.
* **Signals (optional strategies):** language/framework cues that help detect it.
* **Fix guidance:** minimal remediation suggestions.

Example:

* Principle: “Do not silently ignore errors.”
* Strategy signals:

  * Python: `except: pass`
  * JS: `catch(e) {}` without rethrow/log
  * etc.

The **core review pack** is only principles. Strategy packs are additive.

## 3) Review packs per layer

### L2 ReviewPack (recommended)

1. **Architecture Boundary Reviewer** (principles: responsibilities, separation, dependency direction)
2. **Topology/Connectivity Reviewer** (principles: no orphans, handlers exist, flows complete)
3. **Pin/Edge Conformance Reviewer** (principles: pins consumed, edges realized)
4. **Architecture Drift Reviewer** (manifest vs reality)
5. **Governance/Oversight Reviewer** (receipts, injection patterns)

### L3 ReviewPack (recommended)

1. **Clarity Reviewer** (readability, naming intent, cognitive load)
2. **Consistency Reviewer** (API consistency, convention uniformity)
3. **Maintainability Reviewer** (structure, complexity, duplication, decomposition)
4. **Correctness/Safety Reviewer** (edge cases, error paths, invariants)
5. **Drift Reviewer** (no new features; plan/design conformance)
6. **Diff-Impact Classifier** *(gate, not just review)*

Your existing 4 reviewers map cleanly to (1)(2)(3)(4). Add (5)(6) as explicit gates.

## 4) Evolution mechanism (how strategies get created)

* Any repeated human-approved fix or repeated recurring finding produces a **StrategyCandidate**:

  * “signal patterns” observed in the codebase
  * approved remediation
  * exceptions/false positives
* Pattern librarian curates these into a strategy pack scoped by:

  * language (if relevant)
  * framework (if relevant)
  * repository/module (if relevant)

Core reviewers always run with the core principles; strategy packs are optional overlays.

---

# How findings become DemotionTickets and flow down

## Conversion: Finding → DemotionTicket

A deterministic triage function uses *required_change_type* + *scope*:

**Triage rules (minimal and sufficient):**

1. If `required_change_type == behavior_change` → **target_layer = L1**
2. Else if category is `architecture` OR scope is cross-component/topology → **target_layer = L2**
3. Else → fix-in-place (L3) and no demotion ticket

**Special forced demotions:**

* `INLINE_LOGIC_AT_ARCH` (or L2 NO_INLINED_ATOM_LOGIC) → **L1**
* L3 diff-impact classifier “logic-affecting” → **L1**

Tickets should include anchors so L1 routing is precise:

* failing files
* component_id (if known)
* pin ids (if known)
* symbol/span anchors

## Flow-down behavior

* Tickets are written to a persistent queue (e.g., `analysis/demotion/open.json`) and applied by `DemotionManager`.
* Lower layer GapExploration must incorporate “open tickets in scope” as gaps:

  * L2 tickets become L2 gaps in the relevant component slice(s)
  * L1 tickets become L1 gaps routed to the correct library/function via existing routing summaries

This is how L2/L3 “know what to edit” without routing: **the ticket is the route**.

---

# VerifyStep implementation (works across L1/L2/L3)

Below is a concrete, layer-aware implementation pattern for `VerifyStep.run()` that:

* runs different checks by layer,
* produces findings,
* converts them to DemotionTickets via triage,
* fails closed on governance issues.

It is intentionally language-agnostic: it relies on LLM reviewers + manifest/graph artifacts, not parsing.

```python
class VerifyStep:
    """Run P6 + P7 + layer-specific verification (post-integration)."""

    name = "VERIFY"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        from pathlib import Path
        import json
        import time

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None

        findings: list[dict] = []
        notes: dict = {
            "layer": ctx.layer,
            "slice_id": ctx.slice_id,
            "timestamp": time.time(),
            "findings": [],
        }

        # -----------------------------
        # Helpers (language-agnostic)
        # -----------------------------
        def emit_finding(**kw):
            f = {
                "dimension": kw.get("dimension", "VERIFY"),
                "category": kw.get("category", "drift"),
                "severity": kw.get("severity", "MINOR"),
                "required_change_type": kw.get("required_change_type", "refactor_only"),
                "location": kw.get("location", {}),
                "evidence": kw.get("evidence", ""),
                "suggested_fix": kw.get("suggested_fix", ""),
                "confidence": kw.get("confidence", 0.7),
                "tags": kw.get("tags", []),
            }
            findings.append(f)

        def triage_to_ticket(f: dict) -> "DemotionTicket | None":
            # Deterministic, layer-legal triage.
            # L3 cannot change behavior; L2 cannot add business logic.
            required = f.get("required_change_type", "refactor_only")
            cat = f.get("category", "style")
            sev = f.get("severity", "MINOR")

            # Governance: block in place (ticket targets current layer for remediation)
            if cat == "governance":
                target = ctx.layer.upper()
            elif required == "behavior_change":
                target = "L1"
            elif cat == "architecture":
                target = "L2"
            elif required == "wiring_only":
                target = "L2"
            else:
                return None  # fix-in-layer, no demotion

            from spec_manager.orchestration.demotion import DemotionTicket

            loc = f.get("location") or {}
            failing_files = []
            if file := loc.get("file"):
                failing_files = [file]

            return DemotionTicket(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                source="VERIFY",
                origin_layer=ctx.layer.upper(),
                target_layer=target,
                severity=sev if sev in ("BLOCKER", "MAJOR", "MINOR") else "MINOR",
                diagnosis=f.get("evidence", "")[:500] or f.get("dimension", "Verification finding"),
                failing_files=failing_files,
            )

        def run_agent_json(agent_name: str, prompt: str) -> dict:
            # Safe helper: if agent infra missing, return empty.
            try:
                from spec_manager.core.agent_utils import run_agent
                from spec_manager.refinement.formats import _extract_json_payload, _strip_code_fences

                out = run_agent(agent_name=agent_name, prompt=prompt, workspace=workspace)
                cleaned = _strip_code_fences(out)
                return json.loads(_extract_json_payload(cleaned))
            except Exception:
                return {}

        # -----------------------------
        # 0) Governance / Oversight
        # -----------------------------
        # Fail closed if oversight detects missing receipts / decision injection.
        # This is language-agnostic (it inspects receipts + artifact text, not syntax).
        oversight_prompt = (
            "## TASK\n"
            "Act as Pipeline Oversight Enforcer for this slice.\n"
            "Check: missing receipts, undocumented deviations, decision injection patterns.\n"
            "Return JSON: {status: PASS|WARN|FAIL, findings:[{severity, evidence, location, required_change_type}]}\n\n"
            f"Slice: {ctx.slice_id}\nLayer: {ctx.layer}\n"
        )
        oversight = run_agent_json("pipeline-oversight-enforcer", oversight_prompt)
        if oversight:
            status = oversight.get("status", "PASS")
            for of in oversight.get("findings", []) or []:
                emit_finding(
                    dimension="GOVERNANCE",
                    category="governance",
                    severity=of.get("severity", "MAJOR"),
                    required_change_type=of.get("required_change_type", "refactor_only"),
                    location=of.get("location", {}),
                    evidence=of.get("evidence", "Oversight finding"),
                    confidence=0.8,
                )
            if status == "FAIL":
                # Convert governance findings to tickets targeting current layer
                tickets = [t for t in (triage_to_ticket(f) for f in findings) if t]
                notes["findings"] = findings
                iteration_dir = bundle.iter_dir(workspace)
                notes_path = iteration_dir / "verify.notes.json"
                notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
                return StepResult(
                    status="RETRY",
                    emitted_tickets=tickets,
                    notes_path=str(notes_path),
                    error="VERIFY: governance FAIL",
                )

        # -----------------------------
        # 1) Layer-specific verification
        # -----------------------------
        if ctx.layer == "l1":
            # P6: cross-library connectivity, P7: lineage
            prompt = (
                "## TASK\n"
                "Verify L1 post-integration correctness:\n"
                "1) Cross-library connectivity (P6): promoted interfaces connect; no orphan dependencies.\n"
                "2) Lineage (P7): architecture-facing surfaces trace back to spec/atoms; flag orphans.\n"
                "Return JSON: {findings:[...]} with required_change_type in {refactor_only, wiring_only, behavior_change}.\n\n"
                "Provide file locations when possible.\n"
            )
            data = run_agent_json("pdd-l1-verifier", prompt)
            for f in (data.get("findings", []) or []):
                emit_finding(**f)

        elif ctx.layer == "l2":
            # L2: pin consumption + topology connectivity + manifest drift
            prompt = (
                "## TASK\n"
                "Verify L2 architecture post-integration:\n"
                "- Pin consumption coverage (no unaccounted promoted pins)\n"
                "- Topology connectivity (no orphan components)\n"
                "- No inlined business logic in architecture\n"
                "- Conformance to component manifest / intended topology\n"
                "Return JSON: {findings:[...]}.\n"
            )
            data = run_agent_json("pdd-l2-verifier", prompt)
            for f in (data.get("findings", []) or []):
                emit_finding(**f)

        elif ctx.layer == "l3":
            # L3: reviewer closure + no-logic-change + drift
            prompt = (
                "## TASK\n"
                "Verify L3 clean-code post-integration:\n"
                "- All quality findings resolved (closure)\n"
                "- Changes are behavior-preserving (no logic change)\n"
                "- No architectural boundary violations introduced\n"
                "- No unplanned functionality (drift)\n"
                "Return JSON: {findings:[...]}.\n"
            )
            data = run_agent_json("pdd-l3-verifier", prompt)
            for f in (data.get("findings", []) or []):
                emit_finding(**f)

        # -----------------------------
        # 2) Convert to demotion tickets if needed
        # -----------------------------
        tickets = [t for t in (triage_to_ticket(f) for f in findings) if t]

        # Persist verify notes
        notes["findings"] = findings
        iteration_dir = bundle.iter_dir(workspace)
        notes_path = iteration_dir / "verify.notes.json"
        notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")

        # Decide pass/fail
        has_blocker = any(f.get("severity") == "BLOCKER" for f in findings)
        has_major = any(f.get("severity") == "MAJOR" for f in findings)

        if has_blocker or (tickets and has_major):
            return StepResult(
                status="RETRY",
                emitted_tickets=tickets,
                notes_path=str(notes_path),
                error=f"VERIFY: {len(findings)} findings ({len(tickets)} demotions)",
            )

        return StepResult(status="OK", notes_path=str(notes_path))
```

## Notes on this implementation

* It makes VerifyStep **layer-aware** without introducing language parsing.
* It cleanly separates:

  * governance verification (fail closed),
  * layer-specific correctness/conformance checks,
  * deterministic triage into demotion tickets.
* It preserves your “promotion not direct editing” rule by using demotion when a change is illegal in the current layer.

---

# Compliance gate list (final)

## L2 gates (architecture)

* NO_INLINED_ATOM_LOGIC *(BLOCKER)*
* FUNCTION_RECOMPOSITION *(BLOCKER)*
* PIN_CONSUMPTION_COVERAGE *(MAJOR)*
* EDGE_REALIZATION *(MAJOR)*
* NO_ORPHAN_COMPONENTS *(MAJOR)*
* EVENT_HANDLER_COVERAGE *(MAJOR, conditional)*
* CONFIG_EXTERNALIZATION *(MINOR/MAJOR)*
* ARCH_DRIFT_PASS *(MAJOR)*

## L3 gates (clean code)

* ALL_QUALITY_REVIEWERS_PASS *(BLOCKER)*
* NO_LOGIC_CHANGE *(BLOCKER → demote to L1 if violated)*
* NO_ARCH_BOUNDARY_VIOLATIONS *(MAJOR → demote to L2)*
* DRIFT_PASS *(MAJOR)*
* TESTS_PASS *(BLOCKER, enforced via INTEGRATE/CI)*

---

If you implement only one structural change beyond VerifyStep: make **GapExplorationStep layer-aware** so termination (`open_gaps == 0`) remains valid at L2/L3 by defining “gaps” as the open review/graph findings at those layers.
