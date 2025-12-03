Here's a redesign that fully treats:

* object IDs as entities,
* field names as part of the fact,
* and object membership (ancestor chain) as the core context.

I'll start with the shared data model and then show how `extract_ids_and_text`, `resolution_tracker.py`, and `candidate_extraction.py` change, plus how this plugs into your fact pipeline.

---

## 0. Scope and non-goals (textual artifacts only)

### 0.1 Supported artifact scope

This redesign **only supports fully-extractable textual artifacts**.

“Ingestable artifacts” include:
- inline text fields (e.g., `text`, `summary`, `description`, `scope`)
- structured text formats represented as text blobs (e.g., **Mermaid** diagrams stored as text)
- structured YAML subtrees that can be deterministically rendered into text (e.g., list-of-dict “tables”)
- plain-text directory listings / trees

All artifacts must be extractable into **FieldFacts** and, when applicable, re-renderable back to a textual artifact.

### 0.2 Out of scope for v1 extraction/rendering

Out of scope for this plan (not first-class artifact kinds, not ingested/extracted/rendered):
- images, audio, video, and any other non-text modalities
- "query-only" artifacts (data that cannot be fully extracted from source at ingest time)
- partially-extractable artifacts that require external transforms outside the ingest process

If a YAML document contains references to non-text media (e.g., URLs), they may be indexed as **plain string metadata** or **entity references**, but are not treated as artifact roots.

### 0.2.1 Representable but not fully processed (reserved schema hooks)

To avoid future breaking schema changes while keeping v1 execution narrow, the Artifact and Artifact Kind Registry schemas include reserved hooks for broader artifact modalities and extraction modes:

- `modality`: `text` | `image` | `audio` | `video` | `other`
- `extraction_mode`: `full` | `incremental` | `query_only`

**V1 participation rule**: Only artifacts where `modality=text AND extraction_mode=full` participate in the current render-from-facts loop. All other combinations are representable in the schema but bypassed by v1 extraction/rendering pipelines.

---

## 0.3 Design invariants

1. **The text is the state**. Anything not extracted yet must still exist in the current artifact text state.
2. **Extraction must be monotonic**. Each committed rewrite strictly reduces extractable information (or triggers safety handling).
3. **Rewrites are localized**. Only the span(s) returned by the Hunter are rewritten/replaced, never wholesale “delete the document” behavior.
4. **Non-target preservation is mandatory**. If a span contains overlap, the rewrite preserves all non-target (“Anchor”) information.
5. **Entity discovery and fact discovery are unified**. The system alternates between finding entities and exhausting facts per entity until no entities remain.

---

## 1. Core data model: elements, field-facts, and containment

### 1.1 Element boundaries

Definition:

* **Element** = any dict with an `id` field whose value is a string.
* Every such dict is a node in your graph, regardless of where it appears in the tree.
* When you traverse the YAML, you track a stack of ancestor element IDs.

This is already how you conceptually treat elements in `compare_yaml_docs.extract_ids_and_objects`, but that function currently ignores ancestor context.

### 1.2 Containment and nested `id`s

Rule:

* If you're "viewing" element `E` (root id `E.id`), and you encounter a nested dict with its own `id`, you:

    * treat that nested dict as a separate element `C`,
    * record a **containment edge** from `E` to `C` at a specific field path,
    * and **do not inline C's internals** when computing facts or hashes for `E`.

Containment edge structure:

```python
@dataclass
class ContainmentEdge:
    parent_id: str        # E
    child_id: str         # C
    field_path: str       # e.g. "items[2]" or "routes[0].handler"
    source_file: str      # for provenance
```

In the parent's data, the nested object is replaced with a **reference**:

```yaml
items:
  - $ref: child_id
```

(concretely: a dict like `{"$ref": "child_id"}` or just `"child_id"`—pick one and standardize).

This solves your "nested objects with IDs" question: children are entities in their own right; parents only carry **edges** to them, not their internal content.

---

## Nested ID-bearing Objects (Slicing + Containment Edges)

Canonical example for deep nesting + containment edges: `docs/development/MODULE-DEFINITIONS.yml`.

### Standardized reference replacement (required)

When slicing an element for:
- hashing (resolution_tracker)
- text projection (extract_ids_and_text)
- candidate extraction context

Any nested dict that contains its own string `id` (and is not the root element) MUST be replaced with:

{ "$ref": "<child_id>" }

No inlining of the child's internal fields is allowed in the parent slice.

### ContainmentEdge record (required)

Every such replacement MUST emit a ContainmentEdge with:
- parent_id
- child_id
- field_path (where the child appeared in the parent)
- source_file

Containment edges must be persisted (planned store):
- `.knowledge/graph/containment_edges.csv` (or equivalent), keyed by (source_file, parent_id, child_id, field_path)

### Implications

- resolution_tracker hashes ONLY the sliced representation (child content excluded)
- candidate_extraction runs ONLY on the same sliced projection (child visible as `$ref` token only)
- artifacts and render plans can traverse containment edges to reason about hierarchical constraints without duplication

---

## 2. Field-facts: how to represent "facts" structurally

The unit of raw information is a **field-fact**:

### FieldFact (v2: role- and group-aware)

FieldFact:
- element_id: string
- ancestors: [string]
- source_file: string
- field_path: string
- scope_path: string
- key: string
- value_kind: enum
- value: any

- role: enum
    - constraint | entity_ref | artifact_root | metadata

- artifact_kind: string (optional; REQUIRED when role == artifact_root)
    - Open-ended hierarchical kind string (schema-driven; see Artifact Kind Registry), e.g.:
        - prose/paragraph
        - prose/markdown_contract
        - code/python
        - diagram/mermaid.sequence
        - directory/tree
        - schema/json_schema
        - data/yaml_object

- artifact_format: string (optional; REQUIRED when role == artifact_root)
    - Preferred: MIME type for textual artifacts (e.g. text/markdown, text/plain, text/x-mermaid, application/yaml, application/json)

- artifact_locator: enum (optional; REQUIRED when role == artifact_root)
    - inline | reference

- artifact_uri: string (optional; REQUIRED when artifact_locator == reference)

- group_key: string
    - explicit semantic grouping key (see below)
- group_id: string
    - sha256(group_key) for stable identity across reorder/reformat

```python
@dataclass
class FieldFact:
    element_id: str          # which element this fact belongs to
    field_path: str          # full path from element root, e.g. "raises[0].status_code"
    key: str                 # last segment: "status_code"
    scope_path: str          # prefix: "raises[0]"
    value: Any               # normalized leaf value, or a ref
    value_kind: Literal[
        "scalar-str", "scalar-num", "scalar-bool",
        "scalar-null", "ref", "list-scalar", "list-object", "object"
    ]
    ancestors: list[str]     # ancestor element IDs (outer objects this lives under)
    source_file: str         # optional, for provenance
    role: Literal[
        "constraint", "entity_ref", "artifact_root", "metadata"
    ]
    artifact_kind: str | None
    artifact_format: str | None
    artifact_locator: Literal["inline", "reference"] | None
    artifact_uri: str | None
    group_key: str           # explicit semantic grouping key
    group_id: str            # sha256(group_key) for stable identity
```

Notes:

* `field_path` encodes **all anonymous containers** (`fields[0].constraints.min`) so you can travel "up and down" without needing synthetic IDs.
* Sibling fields that share the same `scope_path` form **constraint groups** (e.g. a `raises[0]` block where `type`, `status_code`, and `description` combine into one semantic constraint).
* The **field name is part of the fact**: "`status_code=404`" means nothing without the name `status_code` and the scope `raises[0]`.

#### Role assignment rules (deterministic)

Role assignment MUST be deterministic and based on:
- field_path / key name
- parent container structure
- value_kind
- known "artifact root" paths

Baseline rules:
1) If value_kind == `$ref` → role = entity_ref
2) If key in {doc_id, id, version_hint, kind, index, category, domain} → role = metadata
3) If the field is an artifact root (see Artifact Kind Registry) → role = artifact_root and set:
    - artifact_kind (open-ended)
    - artifact_format (MIME)
    - artifact_locator (inline/reference)
    - artifact_uri (when reference)
      Artifact roots are discovered by deterministic rules based on:
    - field_path / key name (e.g., text/description/summary)
    - sibling + parent structure (e.g., objects with `type: code` / `type: text`)
    - content sniffing (e.g., Mermaid preambles like `sequenceDiagram`; example: `docs/architecture/event-flow.yml`)
4) Otherwise → role = constraint (default for normative/structured fields)
   Examples from docs:
- `http_method_defaults[*].method`, `success_status`, `error_statuses[*]` → constraint
- `sample_code.code` → artifact_root (artifact_kind=code/<lang>) (example: `docs/development/general/general.python.docstrings-guide.yml`)
- `title`, `name` (string-valued labels) → entity_ref unless explicitly configured as metadata

#### Constraint grouping (semantic units)

Fields can only be reasoned about correctly when grouped into semantic units.
A **constraint group** is the set of FieldFacts that share a semantic "row/object".

Default grouping:
- group_key = scope_path

Discriminator-based grouping (recommended for lists-of-dicts):
- If a container is a list of dict entries that represent "rows", group identity should use a discriminator field:
  group_key = f"{container_path}::{discriminator_field}={discriminator_value}"

Required built-in discriminator mappings:
- `http_method_defaults[*]` discriminator_field = "method"
    - group_key example: "http_method_defaults::method=GET"
    - includes all FieldFacts under that list entry (usage, success_status, error_statuses[*], etc.)
    - canonical example: `docs/development/general/general.rest.api-patterns.yml`
- `sample_code` discriminator_field = "language" (optional)
    - group_key example: "sample_code::language=python"
    - canonical example: `docs/development/general/general.python.docstrings-guide.yml`

Group semantics:
- All FieldFacts with the same group_id form one semantic constraint unit.
- Render plans and entity resolution attach constraints at the group level when applicable.

Extraction algorithm (per element `E`):

1. Build the **element slice**: same dict, but nested `id`-bearing dicts replaced by `{"$ref": child_id}`; record a `ContainmentEdge` for each.
2. Flatten the slice into `FieldFact`s:

    * Skip root `id` if you don't want it as a fact.
    * For dicts-without-id, recurse.
    * For lists, recurse; include indices in path.
    * When you hit a scalar or a ref, emit a `FieldFact`.
    * Assign `role` based on deterministic rules.
    * Compute `group_key` and `group_id` based on grouping rules.

This gives you a pure structural representation that is:

* aware of field names,
* anchored in element ID,
* can reconstruct constraint groups (anything sharing `scope_path` or `group_id`),
* and distinguishes role (constraint vs entity_ref vs artifact_root (+ artifact_kind) vs metadata).

---

## Artifact Layer (Explicit)

### Artifact (definition)

An **Artifact** is an irreducible, user-facing *view* rendered from a collection of facts.
Artifacts are **not edited directly**. Editing occurs by changing the underlying facts and then re-rendering.

Artifacts exist because:
- documentation fields (paragraphs, code blocks, tables, dictionaries) are dense "integrated facts"
- users consume integrated views (paragraphs, code examples), not atomized facts
- validation requires a closed loop: extract facts ⇒ re-render ⇒ compare

#### Artifact object model

Artifact:
- artifact_id: string
    - stable identifier; recommended: sha256(f"{source_file}:{source_element_id}:{field_path}:{artifact_kind}")
- artifact_kind: string
    - Registry kind identifier (open-ended string; schema-driven); examples: prose/paragraph, code/python, diagram/mermaid.sequence, directory/tree, schema/json_schema
- artifact_format: string
    - MIME type for textual artifacts (e.g. text/markdown, text/plain, text/x-mermaid, application/yaml, application/json)
- source_file: string
- source_element_id: string
- field_path: string
    - the artifact root field path within the source element (e.g. "text", "items[0].text", "sample_code.code")
- source_locator: enum
    - inline | reference
- source_uri: string (optional; REQUIRED when source_locator == reference)
    - must point to a fully-extractable textual payload (repo path or otherwise retrievable at ingest time)
- render_engine: enum
    - text_llm | none
- render_plan_id: string
    - identifier for a deterministic render procedure (stored in `.knowledge/artifacts/render_plans/`)
- projection_version: string
    - ties to the FieldFact projection version used to build contributors and synthetic projections
- modality: enum (reserved schema hook)
    - text | image | audio | video | other
    - V1 only processes `text`; other values are representable but bypassed
- extraction_mode: enum (reserved schema hook)
    - full | incremental | query_only
    - V1 only processes `full`; other values are representable but bypassed


Artifacts are always backed by an **Artifact Manifest** in `.knowledge` and (optionally) a rendered payload file.

### Artifact roots (how artifacts are discovered)

Some FieldFacts are tagged as **artifact roots** (`role == artifact_root`) when the field (or subtree) is recognized as a user-facing **textual** artifact.

Artifact roots MUST be discovered deterministically by applying **Artifact Kind Registry** `structure_pattern` rules over the **sliced** element representation (nested `id` dicts replaced by `$ref`).

Textual-only constraint:
- Only roots whose payload is fully-extractable text (inline text blobs or structured YAML subtrees renderable to text) are eligible.
- Images, audio, video, and any non-text modalities are not eligible as artifact roots/kinds in this plan.

Artifact roots map 1:1 to Artifact Manifests stored in `.knowledge/artifacts/*.yml`.

---

## Artifact Kind Registry (data-driven, schema-stable, LLM-extensible)

The system MUST NOT hardcode a closed enum of artifact kinds. Instead:
- implementation treats the registry **schema** as stable
- the set of kinds is **open-ended** and grows by adding new registry entries that conform to the schema

Recommended storage:
- `.knowledge/artifacts/kinds.*` (append-only; data-driven)

### Registry entry schema (canonical field names)

Each registry entry MUST use these canonical top-level keys, with requiredness as shown:

FieldFacts store the matched `kind_id` in `artifact_kind`.

Required:
- `kind_id` (string): stable identifier used in FieldFacts/Artifacts (e.g., `diagram/mermaid.sequence`)
- `content_form` (string): describes the textual payload shape (free-form string)
- `structure_pattern` (object): deterministic matching rules that identify artifact roots
- `extraction_contract` (object): contract for how to extract contributors + semantic facts (if any)
- `rendering_contract` (object): contract for how to render + validate the artifact

Optional metadata fields (non-exhaustive; not a closed list):
- `default_format`, `allowed_formats`
- `aliases` (list of kind_ids), `supersedes` (kind_id), `deprecation_note`
- `examples` (sample artifacts / roots), `notes`
- `modality` (enum): `text` | `image` | `audio` | `video` | `other` (reserved; defaults to `text` for v1)
- `extraction_mode` (enum): `full` | `incremental` | `query_only` (reserved; defaults to `full` for v1)

Small example entry (uses the exact required keys):

```yml
- kind_id: diagram/mermaid.sequence
  content_form: text_blob
  structure_pattern:
    root_path: sections[*].items[*].text
    sibling_constraints:
      - key: type
        equals: code
    content_sniff:
      starts_with_any: ["sequenceDiagram"]
  extraction_contract:
    contributors:
      - field_path: text
    semantic_extraction: optional
  rendering_contract:
    render_plan_id: diagram.mermaid.sequence.v1
    output_mime: text/x-mermaid
    validation:
      comparator: normalized_text
      normalization: [trim_trailing_ws, normalize_newlines]
```

### Initial registry entries (explicit repo grounding)

These are examples of dynamic kinds expressed as registry data (not a fixed enum):

1) Discriminator-grouped tables  
   Example file: `docs/development/general/general.rest.api-patterns.yml`

- `content_form`: structured list-of-dict “row tables”
- `structure_pattern`: roots at `sections[*].http_method_defaults` with discriminator `method`
- `extraction_contract`: group_by `http_method_defaults::method=<METHOD>`; treat each row as one semantic constraint unit
- `rendering_contract`: render deterministic Markdown table; validate by comparing normalized rows by discriminator

2) Prose-plus-code blocks  
   Example file: `docs/development/general/general.python.docstrings-guide.yml`

- `content_form`: structured object with prose + code fields (e.g., `sample_code.description`, `sample_code.language`, `sample_code.code`)
- `structure_pattern`: roots at `sections[*].sample_code` (required_fields present)
- `extraction_contract`: contributors include prose + code; optional sentence/line semantic facts with provenance back to the block
- `rendering_contract`: render Markdown with fenced code; validate via normalized diff while preserving code verbatim

3) Nested hierarchies + containment  
   Example file: `docs/development/MODULE-DEFINITIONS.yml`

- `content_form`: structured YAML tree containing nested id-bearing objects
- `structure_pattern`: roots align to section/item hierarchies; child elements discovered via slicing + `$ref` replacement
- `extraction_contract`: preserve containment edges; do not inline child internals into parent contributors
- `rendering_contract`: render stable outline/nested list; validate structure + leaf text

4) Mermaid diagrams stored as text  
   Example file: `docs/architecture/event-flow.yml`

- `content_form`: mermaid text blob inside an item (e.g., `type: code`, `text: |`, `sequenceDiagram`)
- `structure_pattern`: root at `sections[*].items[*].text` where sibling `type == code` and content sniff matches mermaid preamble
- `extraction_contract`: contributors include the `text` blob; optional keyword/entity mentions only
- `rendering_contract`: render `.mmd` text (or fenced mermaid); validate by normalized text or mermaid AST if available

### Governance loop for new LLM-defined artifact kinds (drift/duplication prevention)

New kinds are allowed, but must be introduced with automatic validation to prevent drift, duplication, and invalid contracts.

#### When validation runs (operational triggers)

Validation SHOULD be runnable locally and in CI:

- Local: `uv run knowledge.validate-artifact-kinds`
- CI: a job that runs on any change to:
    - `.knowledge/artifacts/kinds.*`
    - `.knowledge/artifacts/render_plans/*`
    - extraction/rendering code paths

#### What validation checks (minimum set)

`knowledge.validate-artifact-kinds` SHOULD perform:

1) Schema checks (blocking)
- required fields present with canonical names: `kind_id`, `content_form`, `structure_pattern`, `extraction_contract`, `rendering_contract`
- `kind_id` uniqueness; alias targets exist
- `rendering_contract.render_plan_id` refers to an existing render plan

2) Sample execution checks (blocking when samples present)
- for each kind, run extraction + rendering on at least one declared sample root:
    - load sample artifact root from source YAML using `structure_pattern` selectors
    - extract contributor FieldFacts per `extraction_contract`
    - render via `rendering_contract.render_plan_id`
    - run the comparator declared in `rendering_contract.validation`

3) Determinism and coherence checks (blocking)
- `structure_pattern` match must be deterministic (no semantic inference)
- contributor paths referenced by `extraction_contract` must exist in samples (or be explicitly optional)

4) Duplicate / near-duplicate detection (warning or blocking by policy)
- compute similarity between new kind and existing kinds using:
    - normalized `structure_pattern` signature (paths + discriminators + sniff rules)
    - overlap of matched sample roots
- if similarity exceeds threshold:
    - suggest a merge or alias (`aliases`) instead of adding a new kind

#### Failure reporting / strictness

- Blocking CI errors:
    - schema violations
    - missing referenced render plans
    - sample extraction/render/validation failures
- Non-blocking warnings (default):
    - near-duplicate kinds above similarity threshold (unless configured to block)
    - missing/insufficient samples (can be upgraded to blocking once the registry matures)

### Artifact manifest (stored in `.knowledge/artifacts/*.yml`)

Artifact manifests define:
- identity of the artifact (artifact_id, type)
- provenance of the source artifact blob
- the complete set of contributing facts (structural FieldFacts + optional semantic facts)
- the render plan to use
- validation status

Example:

artifact_id: <stable>
artifact_kind: prose/paragraph
artifact_format: text/markdown
source_locator: inline
render_engine: text_llm
source:
source_file: docs/development/general/general.rest.api-patterns.yml
source_element_id: url.health.liveness
field_path: text
render_plan_id: prose.paragraph.v1
projection_version: fieldfacts.v2
contributors:
structural:
- element_id: url.health.liveness
  field_path: text
- element_id: url.health.liveness
  field_path: type
  semantic:
- fact_id: <uuid>   # from facts/extractions.csv (sentence/code facts)
  entities:
- entity_id: <uuid>   # from keyword variant resolution when available
- keyword: GET
  rendered:
  path: .knowledge/artifacts/rendered/<artifact_id>.md
  validation:
  last_validated_at: ""
  similarity: ""
  passed: ""
  notes: ""

### Render plans (stored in `.knowledge/artifacts/render_plans/*.yml`)

A render plan is a deterministic, stepwise algorithm that a renderer follows to produce an artifact.

Renderers are selected via `render_engine`:
- `text_llm`: text-based rendering (Markdown, Mermaid, YAML, JSON, directory trees)
- `none`: referenced textual artifacts that are tracked/indexed but not re-rendered

Render plans must specify:
- artifact_kind
- ordered steps (gather → normalize → order → render → self-check)
- stable ordering rules (to reduce churn)
- output format constraints

Example schema:

render_plan_id: prose.paragraph.v1
render_engine: text_llm
artifact_kind: prose/paragraph
inputs:
use_structural_fieldfacts: true
use_semantic_facts: true
determinism:
ordering:
- role_priority
- group_id
- field_path
  steps:
- id: gather
  instruction: Collect all contributor facts; inline `$ref` only as references, never expand child content.
- id: normalize
  instruction: Normalize terminology to canonical keywords (variant system canonical forms).
- id: order
  instruction: Order constraints first, then prose, then references; keep stable ordering rules.
- id: render
  instruction: Render exactly one paragraph; no extra claims beyond facts; no missing facts.
- id: self_check
  instruction: Verify every statement maps to at least one contributor fact.

### Artifact lifecycle (with validation loop)

1) Detect artifact roots and assign artifact_kind + artifact_format + render_engine + render_plan_id
2) Create/update Artifact Manifest in `.knowledge/artifacts/*.yml`
3) Extract semantic facts from the source artifact blob (prose/code/table) and store them
4) Render the artifact from facts using the render plan into `.knowledge/artifacts/rendered/`
5) Validate: compare rendered artifact back to the original source artifact
6) Persist validation results and mismatches for auditability

---

## Artifact Extraction and Rendering

This section defines how to extract atomic facts from rich artifacts (prose/code/structured blocks) and re-render deterministically.

### Extraction inputs

Artifact-bearing FieldFacts are identified via `role == artifact_root` and classified by `artifact_kind` from the Artifact Kind Registry, e.g.:
- prose/* (fields like text/summary/description/scope)
- code/* (fields like sample_code.code; or objects where a sibling `type: code` owns a `text` blob; example: `docs/development/general/general.python.docstrings-guide.yml`)
- diagram/mermaid.* (Mermaid text blobs such as those starting with `sequenceDiagram`, `flowchart`, or `graph`; example: `docs/architecture/event-flow.yml`)
- schema/* and data/* (YAML/JSON objects and schema-like subtrees rendered as dictionaries/tables; example: `docs/development/MODULE-DEFINITIONS.yml` for nested structures)
- directory/tree (filesystem layout artifacts)
  For each artifact root, the system:
1) creates/updates an Artifact Manifest
2) extracts semantic facts from the artifact content (above and beyond structural FieldFacts)

### Document-level semantic fact extraction (Iterative Sanitization)

Semantic fact extraction operates on artifact text as mutable state, driving extraction via an **Iterative Sanitization** loop:

`Discover Entities → Resolve → Extract Facts → Sanitize (rewrite-remove) → Repeat`

This replaces the previous per-sentence / per-target approach with a **document-state-driven** approach that naturally terminates when the Hunter cannot find further facts.

#### Artifact text state

For each `role==artifact_root`, define `state_text` initialized from the inline field (or referenced payload). This is the mutable document that the extraction loop operates on.

#### Chunking strategy (internal)

Chunking is allowed for runtime efficiency, but correctness is defined on the evolving `state_text`:
- Recommend "chunk IDs" (sentinel markers) to avoid brittle char-offset matching
- Chunks are an implementation detail; the loop semantics operate on `state_text` as a whole

#### Extraction loop (high-level)

1. **Entity discovery**: Hunter finds entities (or picks the most salient entity) in `state_text`.
2. **Entity resolution**: Resolve entity mentions to canonical entities (see Entity Resolution Rules).
3. **Fact extraction**: For one entity, Hunter extracts **as many explicit facts as possible** about it and identifies minimal span(s).
4. **Sanitization**: Surgeon rewrites each span to remove those facts for that entity, preserving Anchors (non-target information).
5. **Commit**: Commit rewrite(s) into `state_text`.
6. **Repeat**: Repeat until Hunter returns no more facts for that entity; then return to entity discovery.
7. **Terminate**: Terminate when entity discovery yields nothing and a final audit confirms no remaining facts.

#### Termination and safety

- **No-op detection**: If `hash(state_text)` repeats, break and escalate to fallback.
- **Hard iteration caps**: Apply iteration limits per artifact and per entity to prevent infinite loops.
- **Residue handling**: If text remains but Hunter returns no entities/facts, use strategy selection + Opus audit.

### LLM roles and contracts

The Iterative Sanitization loop is implemented by three distinct LLM roles with well-defined contracts.

#### Hunter

**Responsibilities:**
- **Entity discovery**: Return entities mentioned in the current `state_text` (optimize for recall).
- **Fact extraction**: For a chosen entity, return all explicit facts about that entity and the minimal span(s) that contain those facts.
- **Termination**: Return an explicit empty result when no entities / no facts remain.

**Output contract (JSON):**
```json
{
  "mode": "entities",
  "entities": [{"mention": "Alice", "type_hint": "person", "evidence_span_id": "span_001"}],
  "target_entity": {"mention": "Alice", "resolved_id": "entity:alice"},
  "facts": [{"fact_text": "Alice is 25 years old", "evidence_span_id": "span_001", "confidence": 0.95}],
  "spans": [{"span_id": "span_001", "original_text": "Alice and Bob are 25."}],
  "done": false,
  "reason": null
}
```

#### Surgeon

**Responsibilities:**
- Given an original span and a list of target facts for one entity, rewrite the span so those facts are impossible to infer while preserving all non-target (“Anchor”) information.
- Rewrite must be localized to the span(s) provided by the Hunter unless cross-span dependencies require grouping.
- If the span contains only target facts (no Anchors), output `[DELETE]`.

**Required behaviors:**
- **Anchor listing**: Explicitly enumerate `anchors_to_keep` (non-target facts to preserve) before producing the final rewrite.
- **Self-check**: Before outputting, verify `target_inferable == false`; if inferable, rewrite again.
- **Coreference safety**: If removing the target facts would strand pronouns or references elsewhere, inject the explicit referent (or mark spans for joint rewrite) before deletion.

**Output contract (JSON):**
```json
{
  "span_id": "span_001",
  "replacement_text": "Bob is 25.",
  "anchors_to_keep": ["Bob is 25 years old"],
  "targets_removed": ["Alice is 25 years old"],
  "self_check": {"target_inferable": false, "notes": null}
}
```

#### Auditor / Unknown-case handler

**Responsibilities:**
- **Residue audit**: Given final `state_text`, determine whether any extractable facts remain; if yes, return a structured report of what remains.
- **Stuck handling**: When the orchestrator detects oscillation/no-op, propose a safe remediation strategy (or an escalation decision).

**Output contract (JSON):**
```json
{
  "has_remaining_facts": false,
  "remaining_facts": [],
  "recommended_action": "terminate",
  "notes": null
}
```

### Artifact-level fact extraction orchestrator

The orchestrator implements the canonical control flow for artifact-level semantic fact extraction.

#### Input

- Artifact manifest: `artifact_id`, `source_file`, `source_element_id`, `field_path`, initial text

#### Orchestrator loop

```
INITIALIZE:
  state_text = load artifact text from manifest
  state_hash = hash(state_text)
  seen_hashes = {state_hash}
  entity_queue = []

MAIN LOOP:
  WHILE true:
    # Entity discovery phase
    IF entity_queue is empty:
      hunter_result = Hunter.discover_entities(state_text)
      IF hunter_result.done OR no entities found:
        BREAK to FINAL AUDIT
      entity_queue = hunter_result.entities

    # Fact extraction phase for current entity
    current_entity = entity_queue.pop()
    resolved_entity = resolve_entity(current_entity)

    WHILE true:
      hunter_result = Hunter.extract_facts(state_text, target_entity=resolved_entity)
      IF hunter_result.done OR no facts found:
        BREAK to next entity

      # Sanitization phase
      FOR each span in hunter_result.spans:
        surgeon_result = Surgeon.rewrite(span, hunter_result.facts)
        state_text = apply_rewrite(state_text, span, surgeon_result)

      # Commit and check for stuck state
      new_hash = hash(state_text)
      IF new_hash in seen_hashes:
        ESCALATE to Auditor for stuck handling
        BREAK
      seen_hashes.add(new_hash)

      # Persist pass record
      persist_pass(artifact_id, resolved_entity, span, facts_removed, state_hash, new_hash)
      state_hash = new_hash

FINAL AUDIT:
  auditor_result = Auditor.audit_residue(state_text)
  IF auditor_result.has_remaining_facts:
    persist_residue_report(artifact_id, auditor_result)
  persist_final_state(artifact_id, state_text)
```

#### Canonical CLI (planned)

- `uv run knowledge.extract-artifact-facts` (or similar)
- Uses: `fact_extraction.py` (or new orchestrator module), `movement_tracker.py`, embeddings validator

#### Debugging utilities

Sentence-level tools remain available as debugging utilities but are not the production path:
- `fact_extraction.py --sentence` for single-sentence extraction
- `fact_isolation.py --sentence` for single-sentence isolation

### Storage: extend `.knowledge/facts/extractions.csv` provenance

Add columns (append-only schema evolution):
- source_file
- source_element_id
- source_field_path
- artifact_id (optional but recommended)
- span_id (chunk/span identifier)
- pass_id (one Hunter→Surgeon commit)
- entity_mention (original mention)
- entity_id (resolved canonical entity id, when available)
- extraction_model, rewrite_model
- state_hash_before, state_hash_after

These columns link semantic extracted facts to the underlying FieldFacts and artifact manifests.

### Passes table (new)

Add `.knowledge/facts/passes.csv` to record each commit:
- pass_id
- artifact_id
- entity_id / entity_mention
- span_id
- span_before
- span_after
- facts_removed (serialized list or join table reference)
- similarity_score
- status / failure_reason

### Movements tracking update

Extend/clarify the relationship between movements and the new span/pass model:
- `movements/iterative_movements.csv` was sentence-level
- Options:
  - Becomes span-level (replacing sentence with span_id)
  - Remains per-fact but references `pass_id` and `span_id`

### Residue snapshots

Add `.knowledge/facts/residue/` storing:
- `<artifact_id>.before.txt` - original artifact text
- `<artifact_id>.after.txt` - final sanitized text
- (optional) intermediate `<artifact_id>.<pass_id>.txt` snapshots for debugging

### Fact identity and deduplication

Define a canonical fact identity so storage remains stable across passes and overlapping queries.

**Canonical identity key:**
- `fact_key = sha256(normalize(fact_text) + "|" + entity_id + "|" + artifact_id)`
- If `entity_id` is unavailable, use `entity_mention` in place of `entity_id` for keying.
- `normalize(fact_text)` should be deterministic (e.g., Unicode normalization, trim, collapse internal whitespace, and stable punctuation normalization).

**Deduplication rule:**
- The orchestrator/storage layer must avoid inserting a duplicate fact with the same `fact_key`.
- On duplicates, merge/append provenance instead of producing another canonical fact row.

**Provenance merge mechanism (recommended):**
- Treat `.knowledge/facts/extractions.csv` as the canonical fact table (one row per `fact_key`), and store multiple "where this came from" references in a separate join table such as `.knowledge/facts/fact_provenance.csv` with rows like:
  - `fact_id`, `fact_key`, `artifact_id`, `pass_id`, `span_id`, `source_file`, `source_element_id`, `source_field_path`, `extracted_at`, `confidence`

### Migration strategy for existing `.knowledge` data

Introduce the new artifact/span/pass concepts without breaking existing `.knowledge` data, and define how legacy sentence-level records are treated during rollout.

**High-level migration approach:**

**`facts/extractions.csv`:**
- Add the new columns (`artifact_id`, `span_id`, `pass_id`, plus any new provenance columns) as append-only schema evolution.
- Backfill legacy rows:
  - `pass_id`: set to the existing `fact_id` (each legacy extraction iteration becomes a pass).
  - `span_id`: set to a stable legacy marker (e.g., `legacy:sentence`), or a hash derived from `source_sentence` if you need uniqueness.
  - `artifact_id`: if legacy records have no artifact provenance, set to a stable synthetic identifier (e.g., `legacy:sentence:<sha256(source_sentence)>`). If provenance columns exist (file/element/field), prefer `sha256(source_file + ":" + source_element_id + ":" + source_field_path)`.

**Passes table initialization:**
- Create `.knowledge/facts/passes.csv` for the new pipeline.
- For legacy data, optionally backfill one pass row per legacy `fact_id`:
  - `pass_id = fact_id`
  - `span_before = source_sentence`
  - `span_after = rewritten_sentence`
  - `facts_removed[] = [fact_text]`
  - Mark with a legacy flag or status (e.g., `status=legacy_backfill`) to distinguish from new orchestrator passes.

**Existing movement records (`movements/iterative_movements.csv`):**
- Treat existing rows as legacy and either:
  - append new columns (`pass_id`, `span_id`, `artifact_id`, `schema_version`) and backfill them consistently, or
  - keep the legacy file unchanged and write new span/pass-aware movements to a new file (while documenting both as supported inputs during transition).
- If backfilling: set `pass_id = fact_id`, and derive `artifact_id`/`span_id` using the same rules as `facts/extractions.csv`. Tag legacy rows via `schema_version` (or equivalent) to prevent accidental mixing.

### Rendering artifacts from facts

Rendering uses:
- structural FieldFacts selected in the manifest
- semantic facts (fact_id references in the manifest)
- canonical terminology from the keyword variant system

Rendering is performed by an LLM following the referenced render_plan_id.
Render output is written to `.knowledge/artifacts/rendered/<artifact_id>.<ext>`.

### Validation: compare rendered artifact to source artifact

Validation compares:
- source artifact blob (from YAML field)
- rendered artifact output (from render plan)

Metrics:
- prose: semantic similarity (embedding cosine) + structural checks (no missing contributor facts)
- code: normalized diff (formatting-insensitive) + optional AST parse; semantic similarity as fallback
- dictionary/table: parsed structural equality (preferred) or normalized serialization comparison

Record validation outcomes and mismatches in:
- `.knowledge/artifacts/validations.csv`

validations.csv suggested columns:
- validation_id, artifact_id, source_file, source_element_id, field_path
- render_plan_id, projection_version
- source_hash, rendered_hash
- similarity_score, passed, mismatch_summary
- validated_at


### Non-text modalities (out of scope)

Images, audio, video, and any non-text artifacts are **out of scope** for this plan and must not be modeled as artifact roots/kinds. Any such references can remain as plain string metadata (or entity references) only.


---

## `.knowledge` Storage Layout

Planned `.knowledge` additions:
- `.knowledge/artifacts/`                 # artifact manifests (*.yml)
- `.knowledge/artifacts/kinds.*`          # artifact kind registry (append-only; schema-driven, LLM-extensible)
- `.knowledge/artifacts/render_plans/`    # deterministic render plans (textual only)
- `.knowledge/artifacts/rendered/`        # rendered textual artifacts (md, yml, json, mmd, txt, etc.)
- `.knowledge/artifacts/validations.csv`  # validation results + mismatch tracking

---

## Entity Resolution Rules

Entity resolution must be deterministic across:
- YAML id-bearing objects
- FieldFacts (entity_ref fields)
- keyword candidates + canonical forms (variant system)

### Entity identification (what becomes an entity)

1) YAML element entities:
- Any dict with a string `id` is an entity.
- Distinguish kinds:
    - section-like ids (containers with items/sections) vs item-like ids (rules/notes/examples)
    - store `entity_kind` as metadata; do not change the identity rule.

2) Keyword entities:
- Canonical keywords (post-variant resolution) are entities.
- Map to `entity_id` using the variant system's canonical linkage (e.g., `pair_id` where merge=true and validated=true as used by fact_store decoration).

### Entity references (how to detect links)

A FieldFact is an entity reference when:
- role == entity_ref OR value_kind == `$ref`
- OR key matches patterns: {entity, name, title, *_id} AND value_kind is scalar-str

Resolution procedure:
1) `$ref:<child_id>` resolves directly to the YAML element entity with id==child_id
2) string values:
    - exact match to existing YAML ids → YAML entity reference
    - exact/canonical match to keyword canonical form → keyword entity reference
    - otherwise unresolved; preserve as literal (do not hallucinate links)

### Containment edges become entity graph edges

ContainmentEdge(parent_id, child_id, field_path, source_file) implies an entity→entity relationship.
Represent this as a deterministic edge type in the graph layer (e.g., CONTAINS / HAS_COMPONENT).
Containment is used for:
- navigation "up/down" object hierarchy
- determining which constraints apply at which entity level
- excluding child content from parent hashing/projections (see Nested ID handling)

### Constraints attach to subject entities

- FieldFacts with role == constraint attach to the subject entity = FieldFact.element_id
- Constraint groups (shared group_id) should also be represented as a unit for reasoning/rendering:
    - group-level constraint unit attaches to subject entity
    - member FieldFacts remain as atomic constraint facts

### Consistency with Knowledge Graph schema

Populate:
- entities table: YAML entities + canonical keyword entities
- facts table: structural FieldFacts + semantic extracted facts
- MENTIONS edges: fact → referenced entities (from entity_ref FieldFacts or extracted semantic facts)
- containment edges: entity → entity (parent/child)

### Resolution of discovered entity mentions

When the Hunter discovers entity mentions during semantic extraction, resolve them using this precedence:

1. **Exact match to YAML `id` entities**: Direct element reference
2. **Exact match to canonical keywords**: Keyword entity reference
3. **Variant match via variant table**: Use validated merges (`merge=true AND validated=true`)
4. **Embedding similarity above threshold**: Candidate mapping (using Qwen3 or similar)
5. **Else**: Record as unresolved candidate (do not hallucinate identity)

### Entity candidate feedback channel

Create/update `.knowledge/entities/entity_candidates.csv` (or extend an existing candidates table) with:
- mention
- context
- artifact_id
- source_file
- confidence
- suggested_canonical

This becomes an input to the keyword/variant review workflow, enabling iterative refinement of the entity resolution system.

---

## 3. `extract_ids_and_text`: FieldFact text projection (required)

Both `resolution_tracker.py` and `candidate_extraction.py` still import `extract_ids_and_text` from `compare_yaml_docs`.

You can restore that function in `compare_yaml_docs.py` as the canonical text projection over the FieldFact slice.

### 3.1 New core helpers (in `compare_yaml_docs.py`)

Add these:

```python
from dataclasses import dataclass

@dataclass
class ElementContext:
    id: str
    obj: dict[str, Any]
    path: str                # YAML path of the element's dict
    ancestors: list[str]     # ancestor element ids, outermost → nearest

def _index_elements(
    data: YamlValue,
    path: str = "",
    ancestor_ids: list[str] | None = None,
) -> dict[str, ElementContext]:
    if ancestor_ids is None:
        ancestor_ids = []

    result: dict[str, ElementContext] = {}

    if isinstance(data, dict):
        element_id = data.get("id")
        if isinstance(element_id, str):
            ctx = ElementContext(
                id=element_id,
                obj=data,
                path=path or "$",
                ancestors=list(ancestor_ids),
            )
            result[element_id] = ctx
            ancestor_ids = ancestor_ids + [element_id]

        for key, value in data.items():
            child_path = f"{path}.{key}" if path else key
            result.update(_index_elements(value, child_path, ancestor_ids))

    elif isinstance(data, list):
        for idx, item in enumerate(data):
            child_path = f"{path}[{idx}]" if path else f"[{idx}]"
            result.update(_index_elements(item, child_path, ancestor_ids))

    return result
```

```python
def _slice_element(obj: dict[str, Any], root_id: str) -> dict[str, Any]:
    """Return a copy of obj where nested id-bearing dicts are replaced with refs."""
    def _recurse(node: YamlValue) -> YamlValue:
        if isinstance(node, dict):
            # Nested element → ref
            if isinstance(node.get("id"), str) and node.get("id") != root_id:
                return {"$ref": node["id"]}
            return {k: _recurse(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_recurse(item) for item in node]
        return node

    return _recurse(obj)  # type: ignore[return-value]
```

```python
def _iter_field_facts(
    node: YamlValue,
    *,
    element_id: str,
    ancestors: list[str],
    path: str = "",
) -> list[FieldFact]:
    facts: list[FieldFact] = []

    def is_scalar(x: Any) -> bool:
        return isinstance(x, (str, int, float, bool)) or x is None

    def classify_value(v: Any) -> str:
        if isinstance(v, dict) and "$ref" in v and isinstance(v["$ref"], str):
            return "ref"
        if isinstance(v, str):
            return "scalar-str"
        if isinstance(v, bool):
            return "scalar-bool"
        if isinstance(v, (int, float)):
            return "scalar-num"
        if v is None:
            return "scalar-null"
        if isinstance(v, list):
            # you can refine this if needed
            return "list-scalar" if all(is_scalar(i) for i in v) else "list-object"
        if isinstance(v, dict):
            return "object"
        return "scalar-str"

    def _walk(n: YamlValue, p: str) -> None:
        if isinstance(n, dict):
            for key, value in n.items():
                if key == "id":  # optional: exclude root id from facts
                    continue
                child_path = f"{p}.{key}" if p else key
                if is_scalar(value) or (
                    isinstance(value, dict)
                    and "$ref" in value
                    and isinstance(value["$ref"], str)
                ):
                    scope_path, _, _ = child_path.rpartition(".")
                    facts.append(
                        FieldFact(
                            element_id=element_id,
                            field_path=child_path,
                            key=key,
                            scope_path=scope_path,
                            value=value,
                            value_kind=classify_value(value),
                            ancestors=list(ancestors),
                            source_file="",
                        )
                    )
                else:
                    _walk(value, child_path)
        elif isinstance(n, list):
            for idx, item in enumerate(n):
                child_path = f"{p}[{idx}]"
                if is_scalar(item):
                    scope_path = p
                    facts.append(
                        FieldFact(
                            element_id=element_id,
                            field_path=child_path,
                            key=str(idx),
                            scope_path=scope_path,
                            value=item,
                            value_kind=classify_value(item),
                            ancestors=list(ancestors),
                            source_file="",
                        )
                    )
                else:
                    _walk(item, child_path)

    _walk(node, path)
    return facts
```

### 3.2 Text view over field-facts

Now define `extract_ids_and_text` as a light wrapper:

```python
def _fact_to_line(fact: FieldFact) -> str:
    chain = " > ".join(fact.ancestors + [fact.element_id]) if fact.ancestors else fact.element_id
    # Normalize scalar to string; you can tune this
    if isinstance(fact.value, dict) and "$ref" in fact.value:
        value_str = f"$ref:{fact.value['$ref']}"
    else:
        value_str = str(fact.value)
    return f"[{chain}] {fact.field_path} = {value_str}"

def extract_ids_and_text(data: YamlValue) -> dict[str, str]:
    """Return id → synthetic fact-line text projection derived from FieldFacts.

    The text is a join of structurally-anchored 'fact lines' that include:
    - ancestor element IDs (context),
    - the full field_path (including anonymous containers),
    - and the normalized value.
    """
    contexts = _index_elements(data)
    result: dict[str, str] = {}

    for element_id, ctx in contexts.items():
        sliced = _slice_element(ctx.obj, element_id)
        facts = _iter_field_facts(
            sliced,
            element_id=element_id,
            ancestors=ctx.ancestors,
            path="",
        )
        lines = [_fact_to_line(f) for f in facts]
        # Stable ordering: sort by field_path then line
        lines.sort()
        result[element_id] = "\n".join(lines)

    return result
```

This gives you:

* `id → text` is the canonical synthetic projection for NLP + hashing,
* but that "text" is now a deterministic, **structure-aware fact view**:

    * field names are literally in the text (`field_path`),
    * ancestor elements are in the text (`[ancestor > element]`),
    * nested entities appear only as `$ref:child_id`, not inlined.

---

## Contract Mapping: extract_ids_and_text → resolution_tracker + candidate_extraction

### extract_ids_and_text (old vs new)

Previous expectation (broken):
- returns {element_id → concatenated prose text}
- assumed a dominant "text" field and paragraph-like structure

New behavior (fieldfacts projection):
- returns {element_id → synthetic fact-line text}
- each line encodes:
    - ancestor chain / element_id context
    - field_path (field names are part of meaning)
    - normalized scalar value OR `$ref:<child_id>`
- content is generated from the **sliced element representation** (nested id-bearing dicts replaced by `{ "$ref": "<child_id>" }`)

This projection is versioned (e.g. `fieldfacts.v2`) and must be stored/traceable.

### resolution_tracker.py impact

resolved.csv stores hashes for change detection and auditing.

Required fields:
- original_text_hash
- split_text_hash
- projection_version

Definition:
- `*_text_hash` = sha256 of the synthetic fact-line projection produced by `extract_ids_and_text` under `projection_version`.

Recommended additional fields:
- original_content_hash
- split_content_hash

Definition:
- `*_content_hash` = sha256 of a canonical JSON serialization of the sliced FieldFact payload (field_path + value_kind + normalized value; child elements appear only as `$ref`).

### candidate_extraction.py impact

candidates.csv fields affected:
- start_char / end_char: now refer to positions in the **synthetic fact-line projection**, not raw YAML field text
- sentence: now reflects the synthetic "context line(s)" extracted from the projection

This remains acceptable for high-recall candidate discovery, but alignment back to structure requires extra columns.

Planned candidates.csv extensions (recommended):
- source_field_path: the FieldFact.field_path of the line containing the candidate span
- source_scope_path: FieldFact.scope_path
- projection_version: e.g. fieldfacts.v2
- field_role: FieldFact.role (constraint/entity_ref/artifact_root/metadata)
- artifact_kind: FieldFact.artifact_kind (when role==artifact_root)

Deduplication guidance:
- current dedup key (source_file, element_id, candidate_text) may over-dedup across different fields
- with new columns, dedup should include source_field_path (and optionally role)


---

## Projection Versioning Contract

`projection_version` identifies the deterministic contract for:
- element slicing (nested-id replacement with `{ "$ref": "<child_id>" }`)
- FieldFact extraction (including roles, grouping, and artifact root tagging)
- synthetic fact-line text projection (`extract_ids_and_text` formatting + ordering)

Naming convention:
- `fieldfacts.v<major>` (e.g., `fieldfacts.v2`)

Version bump rule:
- Increment `projection_version` when any of the following change:
    - slicing rules or `$ref` representation
    - FieldFact structure (fields, role rules, grouping rules, artifact tagging)
    - text projection format or ordering

Where `projection_version` MUST be recorded:
- Artifact manifests (`.knowledge/artifacts/*.yml`)
- candidates.csv (`.knowledge/keywords/candidates.csv`)
- resolved.csv (`.knowledge/resolutions/resolved.csv`)
- SurrealDB/graph ingestion outputs:
    - store on structural facts (`facts.projection_version`)
    - store on artifacts (`artifacts.projection_version`)
    - store on ingestion run metadata for auditability

Data evolution rule:
- Do not rewrite historical persisted data to “upgrade” it.
- Emit new records (or append new columns/fields) under the new `projection_version`.

---
## 4. Hashing in `resolution_tracker.py` (Q1)

`resolution_tracker` currently:

* calls `extract_text_for_id`, which uses `parse_yaml_file` + `extract_ids_and_text`,
* then hashes the returned text with `compute_text_hash`.

With the new `extract_ids_and_text`, **you don't need to change `resolution_tracker.py` at all** to get structurally accurate hashes:

* the "text" is now a canonical concatenation of field-facts for that element,
* nested elements have been replaced with `$ref` tokens, so parent hashes don't change when a child's internal fields change,
* any change to a field name, its value, or its presence/absence will change the text and therefore the hash.

If you want a more explicit content hash (optional refinement):

1. In `compare_yaml_docs.py`, add:

```python
def compute_element_content_hash(
    data: YamlValue,
    element_id: str,
) -> str:
    contexts = _index_elements(data)
    ctx = contexts[element_id]
    sliced = _slice_element(ctx.obj, element_id)
    facts = _iter_field_facts(
        sliced,
        element_id=element_id,
        ancestors=ctx.ancestors,
        path="",
    )
    payload = [
        {
            "field_path": f.field_path,
            "value_kind": f.value_kind,
            "value": f.value,
        }
        for f in sorted(facts, key=lambda f: f.field_path)
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

2. Option A (minimal change): keep using `compute_text_hash` in `resolution_tracker`, but know it's hashing the **fact text** produced by the above machinery.
3. Option B (schema change): add `original_content_hash` / `split_content_hash` columns to `resolved.csv` and populate them using `compute_element_content_hash`, keeping `*_text_hash` as the primary projection hash.

Either way, you are now effectively hashing the **semantic object content**, not a fragile "text field".

---

## 5. Candidate extraction (Q2): per-field context without changing CSV schema

`candidate_extraction.py` does:

* `ids_text = extract_ids_and_text(data)`
* For each `(element_id, text)`:

    * runs spaCy on the entire text string (chunked),
    * extracts candidates,
    * stores `(source_file, element_id, sentence, candidate_text, start_char, end_char, ...)`.

With the redesigned `extract_ids_and_text`:

* the `text` is now a join of **fact lines**: each line is one field-fact with full structural context,
* offsets (`start_char`/`end_char`) still make sense, they are relative to the concatenated lines,
* `sentence` is derived from the fact text via `get_sentence_context`, so it will include the `[ancestor > element] field_path = value` framing.

Thus, without touching `candidate_extraction.py`, Stage 1 now "sees":

* field names as part of the text (e.g. `summary`, `raises[0].status_code`),
* ancestor chain as part of the text (`[factory.create_app]` or `[project > factory.create_app]`),
* `$ref:child_id` as explicit references when relationships to nested elements appear.

That already addresses:

> field names themselves ARE ALSO part of the fact and the CONTEXT of that fact … is the object to which it is a member of and even potentially objects to which that object is a member of.

If you want to go further without changing the CSV schema:

* Keep `extract_ids_and_text` as defined.
* But construct each fact line more aggressively, e.g.:

```python
return (
    f"[elements: {', '.join(fact.ancestors + [fact.element_id])}] "
    f"[scope: {fact.scope_path or '<root>'}] "
    f"[field: {fact.key}] "
    f"value = {value_str}"
)
```

This ensures:

* "which object is the entity?" → appears in the `[elements: ...]` part.
* "which fields are constraints?" → field names and scope appear explicitly.
* Embedded prose in values is still available for SPA/E regex extraction.

---

## 6. Structural entity vs constraint roles

You also raised:

> Which object is the entity? Which fields are constraints? Which fields are entities? Some fields can also have embedded text that needs to be broken down.

You now have the raw material to let later stages decide:

1. **Entity candidates**

    * Every element id is an entity candidate (from YAML structure).
    * Values of fields like `name`, `title`, `summary`, `command`, `keyword`, etc. (configurable list) are also entity-like strings.
    * Nested elements referenced via `$ref` are entity relationships (parent/child, composition, etc.), matching the future SurrealDB entity graph in `scripts/knowledge/README.md`.

2. **Constraints**

    * Any `FieldFact` whose `value_kind` is not obviously an entity (e.g. numbers, booleans, enums) can be treated as a constraint on the subject element (and optionally grouped by `scope_path`).
    * E.g. facts sharing scope `raises[0]` combine into one "raises HTTPException with status_code=404 and description='…'".

3. **Embedded text**

    * For fields where `value_kind == "scalar-str"` and the value looks like prose or code, you can:

        * run your existing `fact_extraction.py` on those strings, but now with:

            * `entity` = either element id or keyword (e.g. `create_app`), and
            * extra metadata: `source_file`, `element_id`, `field_path`.
        * store extracted atomic facts in `.knowledge/facts/extractions.csv` as you already do, but extended with these structural columns.

This is where your "travel up and down objects" requirement is satisfied: when you resolve an entity, you look at:

* `element_id` (which object),
* `field_path` and `scope_path` (which part of the object),
* `ancestors` (which larger object this belongs to),
* and `$ref` edges (how it connects to other elements).

---

## Integration with Existing Fact Workflows

### Two-layer fact model

1) Structural facts (FieldFacts):
- Derived mechanically from YAML structure (sliced representation)
- Provide: field names, scope/grouping, containment, references
- Form the base layer for hashing, candidate extraction context, and artifact manifests

2) Semantic facts (sentence/code facts):
- Derived from artifact blobs (prose/code/table renderings)
- Produced by `fact_extraction.py` and stored in `.knowledge/facts/extractions.csv`
- Must include provenance back to the structural layer (source_file, source_element_id, source_field_path, artifact_id)

### Planned `.knowledge/facts/extractions.csv` extension

Append columns:
- source_file
- source_element_id
- source_field_path
- artifact_id (optional)

This does not break existing readers if queries select only the original columns.

### fact_store.py integration

Fact store YAML records should be extended to carry structural provenance when available:
- existing: source_file, source_element_id
- add: source_field_path, artifact_id, projection_version (recommended)

This allows:
- round-tripping from an artifact back to the specific FieldFacts + semantic facts that produced it
- stable linkage for re-render + validation

### What remains unchanged vs refactored

Unchanged:
- `fact_extraction.py` CLI semantics (extract facts about entity from sentence)
- existing fact isolation / iterative movement semantics remain valid

Extended:
- callers will supply sentences derived from artifact roots (`role == artifact_root`)
- storage gains provenance linking rows back to FieldFacts/artifacts
- later: artifact-aware orchestration command(s) can batch extraction + render + validate

Representation rule:
- avoid two incompatible representations by treating FieldFacts as base provenance and semantic facts as additive.
- do not replace semantic facts with FieldFacts; instead, link them via provenance fields.

---

## Documentation updates (required for consistency)

This plan intentionally only supports **fully-extractable textual artifacts** and defines a **schema-stable, data-driven Artifact Kind Registry**. To keep operational docs consistent, update:

- `.knowledge/README.md`
    - explicitly state ingestion/extraction/rendering only applies to fully-extractable textual artifacts (including mermaid diagrams and directory listings as text)
    - describe `.knowledge/artifacts/kinds.*` as **data-driven and extensible** (not a fixed enum)
    - include the canonical registry entry keys and requiredness:
        - required: `kind_id`, `content_form`, `structure_pattern`, `extraction_contract`, `rendering_contract`
    - document the governance loop and the validation trigger:
        - local: `uv run knowledge.validate-artifact-kinds`
        - CI: runs on kinds/render-plan changes; schema + sample execution failures are blocking

- `scripts/knowledge/README.md`
    - clarify the pipeline runs over YAML docs by projecting FieldFacts (textual-only); it must not assume a single `text` field
    - reference the same registry schema keys (single source of truth) and the governance/validation command

---

## Implementation Phases

1) Implement the FieldFact projection helpers in `compare_yaml_docs.py`
- `_index_elements`, `_slice_element`, `_iter_field_facts`, `_fact_to_line`
- implement `extract_ids_and_text` as the canonical synthetic projection (no more reliance on a single `text` field)

2) Add canonical hashing helper(s)
- `compute_element_content_hash` to hash canonical FieldFact payloads (recommended for resolution tracking)

3) Make CSV outputs projection-aware
- add/require `projection_version` on resolved.csv and candidates.csv outputs
- add `source_field_path`, `source_scope_path`, `field_role`, and `artifact_kind` on candidates.csv for structural alignment
- add `*_content_hash` on resolved.csv if you need stable hashes independent of text formatting

4) Update downstream queries and ingestion to assume projection awareness
- DuckDB queries and SurrealDB ingestion MUST prefer projection-aware fields and partition by `projection_version`
- do not use text hashes as identity keys; use (source_file, element_id, split_file) + projection_version

5) Implement orchestrator and stateful sanitization loop (artifact-level)
- Build the artifact-level extraction orchestrator implementing the Hunter/Surgeon/Auditor loop
- Integrate with movement tracking and fact storage

6) Implement Hunter adapter + prompts + JSON parsing
- Adapter for entity discovery and fact extraction
- JSON output parsing and validation

7) Implement Surgeon prompt and self-check + coreference rules
- Rewrite logic with anchor preservation
- Self-check for target inferability
- Coreference safety handling

8) Add pass-level persistence + schema evolution
- `.knowledge/facts/passes.csv` for commit tracking
- Schema evolution for `extractions.csv` with new columns
- Fact identity and deduplication

9) Add stuck detection + fallback strategy selection + audit
- State hash tracking for oscillation detection
- Fallback strategy selection
- Residue audit integration

10) Add tests for the new extraction system
- See "Testing / acceptance criteria" section

### Testing / acceptance criteria

1. **Idempotence**: Rerunning extraction on an already-sanitized artifact yields no new facts and no text changes.
2. **No overlap loss**: "Alice and Bob are 25" extracts both ages without losing either.
3. **Coreference safety**: Deletion doesn't strand pronouns; orphans are corrected.
4. **Stuck detection**: Repeated state hash triggers fallback path, never infinite loops.
5. **Residue audit**: Auditor confirms residue contains no extractable facts, or produces a structured "remaining facts" report.
6. **Provenance completeness**: Every extracted fact row links back to (artifact_id, file, element, field_path, span_id, pass_id).

---
## 7. How this changes each existing module concretely

### 7.1 `compare_yaml_docs.py`

* **Keep** `extract_ids_and_objects` as-is; it's used for dict-to-dict comparisons.
* **Add** the new helpers:

    * `_index_elements`
    * `_slice_element`
    * `_iter_field_facts`
    * `_fact_to_line`
    * `extract_ids_and_text`
    * (optionally) `compute_element_content_hash`
* No other behavior needs to change.

### 7.2 `resolution_tracker.py`

* **No signature changes**.
* `extract_text_for_id` still calls `parse_yaml_file` + `extract_ids_and_text`.
* `compute_text_hash` continues to hash that text.
* Semantics change from "hash of some text field" to "hash of canonical field-fact projection":

    * changes to any field name/value under that element change the hash,
    * changes to nested elements' internals do **not** (only the `$ref` changes if the relationship changes).

Optional: add new columns `original_content_hash` / `split_content_hash` later, populated from `compute_element_content_hash`, and treat existing `*_text_hash` as deprecated aliases.

### 7.3 `candidate_extraction.py`

* **No code changes required** to make it structurally aware, once `extract_ids_and_text` is replaced.

* It will now see a "document" per element that is:

    * line-based,
    * includes ancestor chain, field_path, and values,
    * and has nested entities represented as `$ref:...`.

* For future refinement you can:

    * add `field_path` / `scope_path` columns to `CandidateRecord` and the candidates CSV schema (breaking change, but straightforward).
    * change dedup key from `(source_file, element_id, candidate_text)` to `(source_file, element_id, candidate_text, sentence)` if you want to differentiate roles of the same word in different fields.

### 7.4 `fact_extraction.py` + `fact_store.py` (integration point, not strictly required now)

Right now they operate on generic sentences and don't know about YAML structure.

With your new field-fact model, you can:

* Treat **fact extraction** as operating on:

    * `source_sentence` = value of a specific text-bearing field,
    * `entity` = keyword candidate (from candidate pipeline) or element id,
    * plus metadata: `source_file`, `source_element_id`, `source_field_path`.

* Update `facts/extractions.csv` schema to add:

    * `source_file`,
    * `source_element_id`,
    * `source_field_path`.

* `fact_store.py` already expects to attach facts back to YAML via `source_file` and `source_element_id`; add `source_field_path` if you want fact-level precision.

This is where the **graph** emerges:

* Structural facts: all `FieldFact`s (per element).
* Textual facts: all `fact_extraction` records, each anchored to a `FieldFact` and/or element.
* Entities: element ids + canonical keywords.
* Edges:

    * containment (parent→child elements),
    * structural constraints (element→field facts),
    * textual facts (fact→entity via `entity` column),
    * keyword→entity mapping via your variant resolution pipeline.

---

## 8. Direct answers to your questions with this redesign

1. **Should `resolution_tracker` hash the entire object or "text content"?**
   Hash the **canonical field-fact projection** of the element:

    * Build element slice with nested ids replaced by refs.
    * Flatten to field-facts (field names + values).
    * Canonicalize (`field_path`, `value_kind`, normalized value).
    * Hash that canonical representation.

   This is logically "hashing the object", but via a stable, schema-aware projection rather than raw YAML bytes.

2. **Should `candidate_extraction` run NLP on each field separately or concatenate?**
   Use the synthetic fact-line projection to **concatenate structured fact lines** per element:

    * Each line encodes: ancestor chain, scope path, field key, and value.
    * NLP sees a synthetic "sentence" like

      `[project > factory.create_app] raises[0].status_code = 404`

   That gives it enough context to tell entities from constraints, while keeping your current CSV schema.

3. **How to handle nested objects with IDs?**

    * Treat every `id`-bearing dict as its own element.
    * In parent elements, **replace nested id objects with `{ "$ref": child_id }`** and record a `ContainmentEdge(parent_id, child_id, field_path)`.
    * Do not inline child content into the parent's facts or hashes.

This design:

* makes **field names first-class**,
* treats **object membership and ancestor chain as context**, not incidental,
* and gives you a clear path from YAML → field-facts → keyword candidates → entity/fact extraction.

---

## System changes required outside `fact_redesign.md`

This section documents required follow-ups in other parts of the codebase to implement this design.

### Agents (Claude)

- Update or replace `.claude/agents/fact-extractor.md`:
    - Either split into `fact-hunter` + `fact-surgeon` + `fact-auditor`
    - Or redefine `fact-extractor` as the Surgeon and add new agents for Auditor.

### Python orchestrator + models

- Update `scripts/knowledge/fact_extraction.py`:
    - Replace "extract facts from a sentence for a given entity" as the main path.
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
