# Plan: Update `docs/plans/fact_redesign.md` for the new fact-finding workflow

## Goal

Correct the semantic fact-extraction workflow by making **artifact text the mutable state** and driving extraction via an **Iterative Sanitization** loop:

`Discover Entities → Resolve → Extract Facts → Sanitize (rewrite-remove) → Repeat`

This replaces the current per-sentence / per-target approach with a **document-state-driven** approach that naturally terminates when the Hunter cannot find further facts.

---

## What must be true (design invariants)

**Apply to `docs/plans/fact_redesign.md` (normative):** Copy the entire list below verbatim into `docs/plans/fact_redesign.md` as its own dedicated subsection (e.g., titled “Design invariants”) placed near the top of the doc (for example, immediately after “0. Scope and non-goals”).

1. **The text is the state**. Anything not extracted yet must still exist in the current artifact text state.
2. **Extraction must be monotonic**. Each committed rewrite strictly reduces extractable information (or triggers safety handling).
3. **Rewrites are localized**. Only the span(s) returned by the Hunter are rewritten/replaced, never wholesale “delete the document” behavior.
4. **Non-target preservation is mandatory**. If a span contains overlap, the rewrite preserves all non-target (“Anchor”) information.
5. **Entity discovery and fact discovery are unified**. The system alternates between finding entities and exhausting facts per entity until no entities remain.

---

## Edits to make inside `fact_redesign.md` (concrete patch plan)

### 1) Update “0. Scope and non-goals” to reserve hooks for non-text / query-only artifacts

**Change**: Keep v1 extraction/rendering limited to fully-extractable textual artifacts, but reserve schema hooks needed by the broader registry.

**Doc edits**:
- In **0.2 Out of scope**, split into:
    - “Out of scope for v1 extraction/rendering”
    - “Representable but not fully processed (reserved schema hooks)”
- Extend the Artifact and Artifact Kind Registry schemas (in-doc) to include:
    - `modality: text|image|audio|video|other`
    - `extraction_mode: full|incremental|query_only`
    - State explicitly: only `modality=text AND extraction_mode=full` participates in the current render-from-facts loop.

**Why**: avoids future breaking schema changes while keeping v1 execution narrow.

---

### 2) Replace “### Fact extraction from artifacts” with a document-level iterative sanitization contract

**Replace the current prose/code bullets** with a new section:

**New subsection**: “Document-level semantic fact extraction (Iterative Sanitization)”

Include:
- **Artifact text state**: for each `role==artifact_root`, define `state_text` initialized from the inline field (or referenced payload).
- **Chunking strategy (internal)**: allowed for runtime efficiency, but correctness is defined on the evolving `state_text`.
    - Recommend “chunk IDs” (sentinel markers) to avoid brittle char-offset matching.
- **Loop** (high-level):
    1) Hunter finds entities (or picks the most salient entity) in `state_text`.
    2) Resolve entity mentions to canonical entities.
    3) For one entity, Hunter extracts **as many explicit facts as possible** about it and identifies minimal span(s).
    4) Surgeon rewrites each span to remove those facts for that entity, preserving Anchors.
    5) Commit rewrite(s) into `state_text`.
    6) Repeat until Hunter returns no more facts for that entity; then return to entity discovery.
    7) Terminate when entity discovery yields nothing and a final audit confirms no remaining facts.

**Termination / safety**:
- No-op detection: if `hash(state_text)` repeats, break and escalate to fallback.
- Hard iteration caps (per artifact and per entity) to prevent infinite loops.
- Residue handling: if text remains but Hunter returns no entities/facts, use strategy selection + Opus audit.

---

### 3) Add a dedicated “LLM roles and contracts” section (Hunter / Surgeon / Auditor)

Add under the semantic extraction section.

**Important separation to apply in `docs/plans/fact_redesign.md`:**
- Copy only the **Abstract role contract** subsections below into `docs/plans/fact_redesign.md` (design-level requirements).
- Do **not** copy the **Reference configuration / current model recommendation** subsections into `docs/plans/fact_redesign.md`; put them in an operational or configuration-focused document (for example, a runbook or `.claude/agents/*` docs).

#### 3.1 Hunter

**Abstract role contract (copy into `fact_redesign.md`)**

Responsibilities:
- **Entity discovery**: return some entities mentioned in the current `state_text` (optimize for recall).
- **Fact extraction**: for a chosen entity, return all explicit facts about that entity and the minimal span(s) that contain those facts.
- **Termination**: return an explicit empty result when no entities / no facts remain.

Output contract (JSON; add to the core design doc):
- `mode: "entities"|"facts"`
- `entities: [{mention, type_hint?, evidence_span_id?}]`
- `target_entity: {mention, resolved_id?}`
- `facts: [{fact_text, evidence_span_id, confidence?}]`
- `spans: [{span_id, original_text}]`
- `done: bool`
- `reason?: string`

**Reference configuration / current model recommendation (do not copy into `fact_redesign.md`)**
- Current recommendation: Ministral 8B 2512 Instruct, loaded via HuggingFace Transformers in Python.
- Wiring: called from the orchestrator as the “Hunter” step; returns JSON parsed by Python.

#### 3.2 Surgeon

**Abstract role contract (copy into `fact_redesign.md`)**

Responsibilities:
- Given an original span and a list of target facts for one entity, rewrite the span so those facts are impossible to infer while preserving all non-target (“Anchor”) information.
- Rewrite must be localized to the span(s) provided by the Hunter unless cross-span dependencies require grouping.
- If the span contains only target facts (no Anchors), output `[DELETE]`.

Required behaviors:
- **Anchor listing**: explicitly enumerate `anchors_to_keep` (non-target facts to preserve) before producing the final rewrite.
- **Self-check**: before outputting, verify `target_inferable == false`; if inferable, rewrite again.
- **Coreference safety**: if removing the target facts would strand pronouns or references elsewhere, inject the explicit referent (or mark spans for joint rewrite) before deletion.

Output contract (JSON; add to the core design doc):
- `span_id`
- `replacement_text` or `[DELETE]`
- `anchors_to_keep[]`
- `targets_removed[]`
- `self_check: {target_inferable: bool, notes?: string}`

**Reference configuration / current model recommendation (do not copy into `fact_redesign.md`)**
- Current recommendation: Claude Haiku, invoked via `claude --agent <surgeon-agent>`.
- Wiring: called once per Hunter “fact batch” per span.

#### 3.3 Auditor / Unknown-case handler

**Abstract role contract (copy into `fact_redesign.md`)**

Responsibilities:
- **Residue audit**: given final `state_text`, determine whether any extractable facts remain; if yes, return a structured report of what remains.
- **Stuck handling**: when the orchestrator detects oscillation/no-op, propose a safe remediation strategy (or an escalation decision).

Output contract (JSON; add to the core design doc):
- `has_remaining_facts: bool`
- `remaining_facts?: [{entity_mention?, fact_text, evidence_span_id?, notes?}]`
- `recommended_action: "terminate"|"retry_with_strategy"|"escalate"`
- `notes?: string`

**Reference configuration / current model recommendation (do not copy into `fact_redesign.md`)**
- Current recommendation: Claude Opus 4.5, invoked via `claude --agent <auditor-agent>`.
- Wiring: invoked for final residue audit and for unknown/stuck cases.


---

### 4) Add “Artifact-level fact extraction orchestrator” section (the canonical control flow)

Add a new top-level section describing:
- Input: artifact manifest (artifact_id, source_file, element_id, field_path, initial text).
- Orchestrator loop implementing the Hunter/Surgeon/Auditor pipeline.
- How it integrates with movement tracking and fact storage.

This section should explicitly name the **canonical CLI** (planned) and the internal modules it uses, e.g.:
- `uv run knowledge.extract-artifact-facts` (or similar)
- Uses: `fact_extraction.py` (or new orchestrator module), `movement_tracker.py`, embeddings validator.

Clarify that sentence-level tools remain as debugging utilities, not the production path.

---

### 5) Update `.knowledge` storage + CSV schemas to support artifact-level iterative sanitization

#### 5.1 `facts/extractions.csv` (append columns)
Document additions needed for artifact-level provenance and batching:
- `artifact_id`
- `source_file`
- `source_element_id`
- `source_field_path`
- `span_id` (chunk/span identifier)
- `pass_id` (one Hunter→Surgeon commit)
- `entity_mention` (original mention)
- `entity_id` (resolved canonical entity id, when available)
- `extraction_model`, `rewrite_model`
- `state_hash_before`, `state_hash_after`

#### 5.2 New “passes” table (recommended)
Add `.knowledge/facts/passes.csv` (or similar) to record each commit:
- `pass_id`, `artifact_id`, `entity_id/mention`, `span_id`
- `span_before`, `span_after`
- `facts_removed[]` (serialized list or join table)
- `similarity_score`
- `status` / `failure_reason`

#### 5.3 Movements tracking
Extend/clarify:
- `movements/iterative_movements.csv` was sentence-level; document that:
    - either it becomes span-level, or
    - it remains “per-fact” but references `pass_id` and `span_id`.

#### 5.4 Residue snapshots
Add `.knowledge/facts/residue/` storing:
- `artifact_id.before.txt`
- `artifact_id.after.txt`
- (optional) intermediate `pass_id` snapshots for debugging

#### 5.5 Fact identity and deduplication

Define a canonical fact identity so storage remains stable across passes and overlapping queries.

- Canonical identity key:
    - `fact_key = sha256(normalize(fact_text) + "|" + entity_id + "|" + artifact_id)`
    - If `entity_id` is unavailable, use `entity_mention` in place of `entity_id` for keying.
    - `normalize(fact_text)` should be deterministic (e.g., Unicode normalization, trim, collapse internal whitespace, and stable punctuation normalization).

- Deduplication rule:
    - The orchestrator/storage layer must avoid inserting a duplicate fact with the same `fact_key`.
    - On duplicates, merge/append provenance instead of producing another canonical fact row.

- Provenance merge mechanism (recommended):
    - Treat `.knowledge/facts/extractions.csv` as the canonical fact table (one row per `fact_key`), and store multiple “where this came from” references in a separate join table such as `.knowledge/facts/fact_provenance.csv` with rows like:
        - `fact_id`, `fact_key`, `artifact_id`, `pass_id`, `span_id`, `source_file`, `source_element_id`, `source_field_path`, `extracted_at`, `confidence`

**Apply to `docs/plans/fact_redesign.md`:** Document this deduplication policy in the storage/facts section so downstream users can rely on a stable, deduplicated fact set per entity–artifact pair.

#### 5.6 Migration strategy for existing `.knowledge` data

Introduce the new artifact/span/pass concepts without breaking existing `.knowledge` data, and define how legacy sentence-level records are treated during rollout.

High-level migration approach:
- `facts/extractions.csv`:
    - Add the new columns (`artifact_id`, `span_id`, `pass_id`, plus any new provenance columns) as append-only schema evolution.
    - Backfill legacy rows:
        - `pass_id`: set to the existing `fact_id` (each legacy extraction iteration becomes a pass).
        - `span_id`: set to a stable legacy marker (e.g., `legacy:sentence`), or a hash derived from `source_sentence` if you need uniqueness.
        - `artifact_id`: if legacy records have no artifact provenance, set to a stable synthetic identifier (e.g., `legacy:sentence:<sha256(source_sentence)>`). If provenance columns exist (file/element/field), prefer `sha256(source_file + ":" + source_element_id + ":" + source_field_path)`.

- `passes` table initialization:
    - Create `.knowledge/facts/passes.csv` for the new pipeline.
    - For legacy data, optionally backfill one pass row per legacy `fact_id`:
        - `pass_id = fact_id`
        - `span_before = source_sentence`
        - `span_after = rewritten_sentence`
        - `facts_removed[] = [fact_text]`
        - Mark with a legacy flag or status (e.g., `status=legacy_backfill`) to distinguish from new orchestrator passes.

- Existing movement records (`movements/iterative_movements.csv`):
    - Treat existing rows as legacy and either:
        - append new columns (`pass_id`, `span_id`, `artifact_id`, `schema_version`) and backfill them consistently, or
        - keep the legacy file unchanged and write new span/pass-aware movements to a new file (while documenting both as supported inputs during transition).
    - If backfilling: set `pass_id = fact_id`, and derive `artifact_id`/`span_id` using the same rules as `facts/extractions.csv`. Tag legacy rows via `schema_version` (or equivalent) to prevent accidental mixing.

**Apply to `docs/plans/fact_redesign.md`:** Add a corresponding “Migration strategy” section so operators know how to interpret legacy vs new data during rollout.



---

### 6) Update “Entity Resolution Rules” to cover Hunter-discovered entities + feedback into keywords

Add a subsection: “Resolution of discovered entity mentions”
- Resolution precedence:
    1) Exact match to YAML `id` entities
    2) Exact match to canonical keywords
    3) Variant match via variant table (validated merges)
    4) Embedding similarity (Qwen3) above threshold → candidate mapping
    5) Else: record as unresolved candidate (do not hallucinate identity)

Add a feedback channel:
- Create/update `.knowledge/entities/entity_candidates.csv` (or extend an existing candidates table) with:
    - mention, context, artifact_id, source_file, confidence, suggested canonical
- This becomes an input to the keyword/variant review workflow.

---

### 7) Update “Implementation Phases” to include the new orchestrator phase and agent split

Add phases after the existing FieldFact/Artifact registry scaffolding:
1) Implement orchestrator and stateful sanitization loop (artifact-level).
2) Implement Hunter (Ministral) adapter + prompts + JSON parsing.
3) Implement Surgeon (Haiku) prompt and self-check + coreference rules.
4) Add pass-level persistence + schema evolution.
5) Add stuck detection + fallback strategy selection + Opus audit.
6) Add tests (see below).

---

## System changes required outside `fact_redesign.md` (callouts to include in the doc as “Required follow-ups”)

### Agents (Claude)
- Update or replace `.claude/agents/fact-extractor.md`:
    - Either split into `fact-hunter` + `fact-surgeon` + `fact-auditor`
    - Or redefine `fact-extractor` as the Surgeon and add new agents for Auditor.

### Python orchestrator + models
- Update `scripts/knowledge/fact_extraction.py`:
    - Replace “extract facts from a sentence for a given entity” as the main path.
    - Add artifact-level loop and Hunter/Surgeon delegation.
- Add `scripts/knowledge/ministral_hunter.py` (or similar) using HF Transformers:
    - `ministral-8b-2512-instruct` load + inference + JSON output parsing.
- Update `scripts/knowledge/fact_isolation.py`:
    - Move from sentence-only isolation to span/commit isolation aligned with `pass_id`.
- Update `scripts/knowledge/movement_tracker.py`:
    - Add pass-level records, link to fact rows, store similarity + hashes.

### Validation (Qwen)
- Keep Qwen embeddings-based similarity check, but make it pass-level:
    - validate `original_span ~ (facts_removed + residual_span)`
- Optional: use Qwen reranker to rank candidate entities/facts/spans.

### Documentation alignment
- Update `.knowledge/README.md` and `scripts/knowledge/README.md` to match:
    - new orchestrator command
    - new CSV columns / tables
    - updated meaning of iterative movements

---

## Testing / acceptance criteria to encode in the plan

**Apply to `docs/plans/fact_redesign.md` (normative):** Copy the entire list below verbatim into `docs/plans/fact_redesign.md` as its own dedicated subsection (e.g., titled “Testing / acceptance criteria”) placed in or near the implementation/testing phases section so it reads as a requirement, not a side note.

1) **Idempotence**: rerunning extraction on an already-sanitized artifact yields no new facts and no text changes.
2) **No overlap loss**: “Alice and Bob are 25” extracts both ages without losing either.
3) **Coreference safety**: deletion doesn’t strand pronouns; orphans are corrected.
4) **Stuck detection**: repeated state hash triggers fallback path, never infinite loops.
5) **Residue audit**: Opus confirms residue contains no extractable facts, or produces a structured “remaining facts” report.
6) **Provenance completeness**: every extracted fact row links back to (artifact_id, file, element, field_path, span_id, pass_id).

---

## Minimal set of `fact_redesign.md` sections that must change

- “0. Scope and non-goals”
- “Artifact Extraction and Rendering → Fact extraction from artifacts”
- “Storage: extend `.knowledge/facts/extractions.csv` provenance”
- “Integration with Existing Fact Workflows”
- “Implementation Phases”
- Add: “LLM roles and contracts” + “Artifact-level fact extraction orchestrator” + residue/termination strategy sections
