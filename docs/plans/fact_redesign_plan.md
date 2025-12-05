# Phase Breakdown

## Task 1: Implement element slicing with containment edges and $ref replacement

Implement `ContainmentEdge` dataclass in `scripts/knowledge/compare_yaml_docs.py` per lines 77-86 of `docs/plans/fact_redesign.md`
Implement Element boundaries: define Element as any dict with string `id` field, track ancestor IDs per lines 57-65
Apply containment rule: nested dicts with `id` become separate elements, record containment edge, do not inline child internals per lines 67-76
Standardize reference replacement syntax: `{"$ref": "child_id"}` per lines 87-98 (pick one format and standardize)
Use `docs/development/MODULE-DEFINITIONS.yml` as canonical example for deep nesting per lines 101-104
Update `extract_ids_and_objects()` to detect nested ID-bearing dicts and replace with `{"$ref": "<child_id>"}` per lines 105-134
Emit `ContainmentEdge` records for each replacement with (parent_id, child_id, field_path, source_file)
Create `.knowledge/graph/containment_edges.csv` storage with DuckDB per line 127
Update `resolution_tracker.py` and `candidate_extraction.py` to use sliced representations (child content excluded) per lines 131-133

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\compare_yaml_docs.py`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\resolution_tracker.py`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\candidate_extraction.py`
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\development\MODULE-DEFINITIONS.yml`


## Task 2: Implement FieldFact extraction with role assignment and constraint grouping

Implement `FieldFact` dataclass per lines 143-178 (YAML spec) and 180-202 (Python dataclass) of `docs/plans/fact_redesign.md` with all fields (element_id, field_path, key, scope_path, value, value_kind, ancestors, source_file, role, artifact_kind, artifact_format, artifact_locator, artifact_uri, group_key, group_id)
Document notes on field_path encoding for anonymous containers, constraint groups via shared scope_path, and field names as part of fact semantics per lines 203-209
Implement deterministic role assignment rules per lines 210-235: entity_ref for `$ref`, metadata for id/version_hint/etc, artifact_root for artifact fields, constraint as default
Implement constraint grouping with discriminator-based group_key per lines 236-260: default `scope_path`, discriminator patterns for `http_method_defaults[*]` (method) and `sample_code` (language)
Create extraction algorithm per lines 261-272: slice element, flatten to FieldFacts, assign roles, compute group_key/group_id (sha256)
Validate extraction produces structural representation per lines 273-279: field-name-aware, element-anchored, scope/group reconstructable, role-distinguished
Add helper to iterate FieldFacts from sliced element in `compare_yaml_docs.py`

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\compare_yaml_docs.py`
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\development\general\general.rest.api-patterns.yml`
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\development\general\general.python.docstrings-guide.yml`


## Task 3: Create Artifact Kind Registry with schema validation and storage

Create `.knowledge/artifacts/kinds.*` storage (YAML/JSONL) per lines 341-369 of `docs/plans/fact_redesign.md`
Implement registry entry schema with required fields: kind_id, content_form, structure_pattern, extraction_contract, rendering_contract per lines 350-362
Add optional metadata fields: default_format, aliases, supersedes, examples, modality, extraction_mode per lines 363-369
Include example entry for diagram/mermaid.sequence per lines 370-392: kind_id, content_form=text_blob, structure_pattern (root_path, sibling_constraints, content_sniff), extraction_contract, rendering_contract (render_plan_id, output_mime, validation)
Create initial registry entries for: discriminator-grouped tables (general.rest.api-patterns.yml), prose-plus-code blocks (general.python.docstrings-guide.yml), nested hierarchies (MODULE-DEFINITIONS.yml), Mermaid diagrams (event-flow.yml) per lines 394-429
Implement `uv run knowledge.validate-artifact-kinds` command per lines 434-479: schema checks, sample execution checks, determinism checks, duplicate detection

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\development\general\general.rest.api-patterns.yml`
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\development\general\general.python.docstrings-guide.yml`
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\development\MODULE-DEFINITIONS.yml`
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\architecture\event-flow.yml`


## Task 4: Implement artifact root detection and manifest creation

Document Artifact Layer rationale per lines 282-295: Artifacts are irreducible user-facing views rendered from facts; not edited directly; exist because dense integrated facts require extraction→render→compare loop
Implement artifact root detection by applying Artifact Kind Registry `structure_pattern` rules over sliced elements per lines 327-337 of `docs/plans/fact_redesign.md`
Create `Artifact` object model per lines 296-323: artifact_id (sha256 of source_file:element_id:field_path:artifact_kind), artifact_kind, artifact_format, source_file, source_element_id, field_path, source_locator, source_uri, render_engine, render_plan_id, projection_version, modality, extraction_mode
Create artifact manifest storage in `.knowledge/artifacts/*.yml` per lines 481-521 with structure: artifact_id, artifact_kind, artifact_format, source, render_plan_id, projection_version, contributors (structural FieldFacts + semantic facts), entities, rendered path, validation
Implement artifact lifecycle per lines 561-569: detect roots, create/update manifests, extract semantic facts, render artifacts, validate, persist results
Add V1 participation rule: only `modality=text AND extraction_mode=full` per lines 36-42
Document supported artifact scope per lines 11-24: inline text fields, structured text formats (Mermaid), YAML subtrees renderable to text, directory listings
Document out-of-scope items per lines 25-35: images/audio/video, query-only artifacts, partially-extractable artifacts; reserved schema hooks for modality/extraction_mode

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\compare_yaml_docs.py`


## Task 5: Create render plans and implement artifact rendering infrastructure

Create `.knowledge/artifacts/render_plans/*.yml` storage per lines 522-560 of `docs/plans/fact_redesign.md`
Implement render plan schema: render_plan_id, render_engine (text_llm | none), artifact_kind, inputs (use_structural_fieldfacts, use_semantic_facts), determinism (ordering rules), steps (gather, normalize, order, render, self_check) per lines 536-560
Create render plans for initial artifact kinds: prose.paragraph.v1, discriminator-grouped tables, prose-plus-code blocks, nested hierarchies, Mermaid diagrams
Implement rendering logic that follows render plan steps: gather contributor facts, normalize terminology, order by role/group_id/field_path, render artifact, self-check per lines 938-946
Implement validation comparator per rendering_contract: normalized_text, normalized_rows_by_discriminator, structure+leaf_text per lines 948-967 (semantic similarity for prose, normalized diff for code, structural equality for tables)
Store rendered artifacts in `.knowledge/artifacts/rendered/<artifact_id>.<ext>`
Create `.knowledge/artifacts/validations.csv` per lines 959-967: validation_id, artifact_id, source_file, source_element_id, field_path, render_plan_id, projection_version, source_hash, rendered_hash, similarity_score, passed, mismatch_summary, validated_at
Document non-text modalities out of scope per lines 970-973: images/audio/video not modeled as artifact roots/kinds
Document `.knowledge` storage layout per lines 977-985: artifacts/, artifacts/kinds.*, render_plans/, rendered/, validations.csv

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`


## Task 6: Implement multi-agent extraction pipeline (Hunter, Surgeon, Auditor)

Implement design invariants as runtime assertions per lines 43-52: (1) text-is-state, (2) monotonic extraction, (3) localized rewrites, (4) non-target preservation mandatory, (5) unified entity/fact discovery
Document Surgeon reliability risks and mitigations per lines 586-614: sub-agent decomposition, Qwen3 embedding validation, explicit contracts, monotonic safety, edge-case testing (coreference, overlapping facts, nested refs, multi-entity spans), fallback strategy
Create `scripts/knowledge/ministral_hunter.py` using HF Transformers for `mistralai/Ministral-3-8B-Instruct-2512` per lines 572-581: load model, run inference, parse JSON output per Hunter contract (lines 671-689)
Implement Hunter responsibilities per lines 671-689: entity discovery with recall optimization, fact extraction with minimal spans, explicit termination signal with JSON output contract
Implement extraction inputs per lines 617-632: artifact root classification by artifact_kind (prose/*, code/*, diagram/mermaid.*, schema/*, directory/tree), create/update artifact manifest, extract semantic facts
Implement Iterative Sanitization loop per lines 633-666: artifact text state, chunking strategy with chunk IDs, extraction loop (entity discovery → resolution → fact extraction → sanitization → commit → repeat), termination/safety (no-op detection, hard iteration caps, residue handling)
Implement Surgeon as multi-sub-agent pipeline per lines 691-762:
- Organizer sub-agent: group spans by overlap per lines 702-705
- Planner sub-agent: plan rewrite with anchors_to_keep per lines 707-709
- Rewriter sub-agent: apply rewrite preserving anchors per lines 711-713
- Validator (Qwen3): embedding score_drop check per lines 715-719
- Reviewer sub-agent (optional): review low-confidence rewrites per lines 721-723
- Required behaviors: anchor listing, self-check, coreference safety per lines 725-728
- Invariants: fail-to-remove passes to next iteration, remove-too-much rejects immediately per lines 730-732
- Implementation tasks per lines 734-750: create sub-agent files, surgeon_orchestrator.py, Qwen3 validator integration, fallback handling
- Output contract per lines 752-762
Implement Auditor/unknown-case handler per lines 764-778: residue audit, stuck handling, JSON output contract
Implement artifact-level extraction orchestrator per lines 780-836: canonical control flow with INITIALIZE, MAIN LOOP (entity discovery → fact extraction → sanitization → commit), FINAL AUDIT
Implement canonical CLI per lines 838-841: `uv run knowledge.extract-artifact-facts` using fact_extraction.py, movement_tracker.py, embeddings validator
Document debugging utilities per lines 843-847: `fact_extraction.py --sentence` and `fact_isolation.py --sentence` remain available but not production path
Extend `.knowledge/facts/extractions.csv` with provenance columns per lines 849-863: source_file, source_element_id, source_field_path, artifact_id, span_id, pass_id, entity_mention, entity_id, extraction_model, rewrite_model, state_hash_before, state_hash_after
Create passes table `.knowledge/facts/passes.csv` per lines 865-876: pass_id, artifact_id, entity_id/entity_mention, span_id, span_before, span_after, facts_removed, similarity_score, status/failure_reason
Update movements tracking per lines 878-884: extend iterative_movements.csv to span-level (replace sentence with span_id) or add pass_id/span_id references
Create residue snapshots storage `.knowledge/facts/residue/` per lines 886-891: <artifact_id>.before.txt, <artifact_id>.after.txt, optional intermediate <artifact_id>.<pass_id>.txt
Implement fact identity and deduplication per lines 893-908: canonical fact_key = sha256(normalize(fact_text) + "|" + entity_id + "|" + artifact_id), deduplication rule (merge provenance on duplicates), fact_provenance.csv join table
Implement migration strategy for existing `.knowledge` data per lines 910-936: append-only schema evolution for extractions.csv, backfill legacy rows (pass_id=fact_id, span_id=legacy:sentence), passes table initialization with legacy_backfill status, movement records handling
Create Claude sub-agents in `.claude/agents/`: `fact-surgeon-organizer.md`, `fact-surgeon-planner.md`, `fact-surgeon-rewriter.md`, `fact-surgeon-reviewer.md` (Haiku), `fact-auditor.md` (Opus) per lines 577-582
Implement Qwen3 embedding validation per lines 586-599: score_drop check (cosine_sim(fact_emb, orig_emb) - cosine_sim(fact_emb, new_emb) >= 0.2), reuse `load_qwen_embedding_model()` from `variant_resolver.py`
Update `scripts/knowledge/fact_isolation.py` for span/commit isolation aligned with pass_id per lines 821-824
Update `scripts/knowledge/movement_tracker.py` for pass-level records per lines 824-826

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\fact_extraction.py`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\fact_isolation.py`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\movement_tracker.py`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\variant_resolver.py`
- `c:\Users\xteam\IdeaProjects\ai-workflow\.claude\agents\fact-extractor.md`


## Task 7: Update compare_yaml_docs.py with new text projection helpers

Implement new canonical text projection helpers per lines 1068-1258 of `docs/plans/fact_redesign.md`:
- Element indexing: build id→element map with ancestor tracking per lines 1086-1120
- Slicing with `$ref` replacement: `_slice_element()` per lines 1123-1136
- FieldFact iteration: `_iter_field_facts()` per lines 1139-1216
- Fact-line formatting: `_fact_to_line()` per lines 1224-1231
Implement `extract_ids_and_text()` producing deterministic, structure-aware synthetic text per element per lines 1233-1258: iterate FieldFacts, format as fact-lines, join with newlines
Document output characteristics per lines 1259-1270: id→text canonical synthetic projection for NLP+hashing; structure-aware with field_path, ancestor elements, $ref tokens
Update projection versioning rules per lines 1271-1327: version slicing logic, FieldFact extraction, text projection separately; Contract Mapping for resolution_tracker and candidate_extraction
Implement Surgeon Orchestrator Contract per lines 1329-1355: invocation pattern (claude --agent ...), orchestrator responsibilities (parse JSON, chain outputs, handle failures, persist pass records), sub-agent file locations
Implement Qwen3 Validator Contract per lines 1356-1395: validate_removal() function, threshold guidance (0.1/0.2/0.3), referred implementations (variant_resolver.py, qwen_scoring.py)
Implement Projection Versioning Contract per lines 1398-1427: fieldfacts.v<major> naming, version bump rules, where projection_version must be recorded (manifests, candidates.csv, resolved.csv, SurrealDB), data evolution rules
Update hashing to use sliced representation (child content excluded) per lines 1428-1476: `compute_element_content_hash()` implementation
Document candidate extraction impact per lines 1478-1524: fact-line projection, offset semantics, field names/ancestor chain/refs visible to NLP, aggressive fact-line formatting option
Document structural entity vs constraint roles per lines 1527-1562: entity candidates (element ids, field values like name/title), constraints (non-entity FieldFacts grouped by scope_path), embedded text extraction (prose/code fields to fact_extraction.py)
Implement two-layer fact model per lines 1565-1613: structural FieldFacts (mechanical from YAML) + semantic facts (from artifact blobs), extractions.csv extension, fact_store.py integration (provenance fields), unchanged vs extended behaviors, representation rule (FieldFacts as base, semantic as additive)
Document required documentation updates per lines 1616-1632: .knowledge/README.md and scripts/knowledge/README.md updates for textual-only artifacts, registry schema, governance/validation command
Document implementation phases per lines 1635-1679: 10-phase breakdown (FieldFact helpers → hashing → CSV projection-aware → downstream queries → orchestrator → Hunter adapter → Surgeon pipeline → pass persistence → stuck detection → tests)
Document testing/acceptance criteria per lines 1683-1691: idempotence, no overlap loss, coreference safety, stuck detection, residue audit, provenance completeness
Document module-level changes per lines 1693-1767: compare_yaml_docs.py (keep extract_ids_and_objects, add new helpers), resolution_tracker.py (no signature changes, semantics change), candidate_extraction.py (no code changes, future refinements), fact_extraction.py + fact_store.py (integration with provenance)

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\compare_yaml_docs.py`


## Task 8: Integrate structural and semantic facts with provenance in fact_store.py

Update `scripts/knowledge/fact_store.py` per lines 1428-1767 of `docs/plans/fact_redesign.md` to store both structural FieldFacts and semantic facts
Add provenance tracking: source_file, source_element_id, field_path for structural facts; artifact_id, pass_id, iteration for semantic facts
Implement fact identity and deduplication: structural facts by (element_id, field_path, value), semantic facts by (artifact_id, fact_text, entity)
Store facts in `.knowledge/facts/<primary_domain>.<pattern>.facts.yml` where primary_domain = first tag from domain array or 'mixed'
Export to `.knowledge/facts/facts.jsonl` (JSONL format, domain as array, traceable to YAML source) per lines 1428-1767
Include optional edge list for fact relationships (containment edges, entity references)

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\fact_store.py`


## Task 9: Implement Entity Resolution Rules

Implement deterministic entity resolution across YAML id-bearing objects, FieldFacts, and keyword candidates per lines 988-993 of `docs/plans/fact_redesign.md`
Implement entity identification per lines 995-1005:
- YAML element entities: any dict with string `id`, distinguish section-like vs item-like, store entity_kind as metadata per lines 997-1001
- Keyword entities: canonical keywords post-variant resolution, map to entity_id via variant system's canonical linkage per lines 1003-1005
Implement entity reference detection per lines 1007-1018: role==entity_ref OR value_kind==$ref OR key matches {entity, name, title, *_id} with scalar-str
Implement resolution procedure: $ref:<child_id> → YAML element, string values → exact YAML id match OR keyword canonical match OR unresolved (no hallucinated links)
Convert containment edges to entity graph edges per lines 1020-1027: ContainmentEdge implies CONTAINS/HAS_COMPONENT edge type, used for hierarchy navigation, constraint level determination, hashing exclusion
Implement constraint attachment per lines 1029-1034: role==constraint attaches to subject entity (element_id), constraint groups (shared group_id) as units for reasoning/rendering
Populate Knowledge Graph schema per lines 1036-1042: entities table (YAML + keyword entities), facts table (structural + semantic), MENTIONS edges (entity_ref FieldFacts), containment edges (parent/child)
Implement resolution of discovered entity mentions per lines 1044-1052: precedence (YAML id → canonical keyword → variant table validated merges → embedding similarity → unresolved candidate)
Create entity candidate feedback channel `.knowledge/entities/entity_candidates.csv` per lines 1054-1063: mention, context, artifact_id, source_file, confidence, suggested_canonical

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\compare_yaml_docs.py`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\variant_resolver.py`


## Task 10: Update documentation alignment for new system

Document direct answers to design questions per lines 1768-1802:
- resolution_tracker hashing: hash canonical field-fact projection (sliced with $ref replacement) per lines 1771-1779
- candidate_extraction NLP: use synthetic fact-line projection per element per lines 1781-1789
- Nested objects with IDs: treat as separate elements, replace with $ref, record ContainmentEdge per lines 1791-1795
- Design benefits: field names first-class, object membership as context, clear YAML→FieldFacts→candidates→entity/fact extraction path per lines 1797-1802
Document system changes required per lines 1805-1832:
- Agents (Claude): update/split fact-extractor.md into fact-hunter/fact-surgeon/fact-auditor per lines 1809-1813
- Python orchestrator: update fact_extraction.py for artifact-level loop, add ministral_hunter.py, update fact_isolation.py for span/commit, update movement_tracker.py for pass-level per lines 1815-1826
- Qwen validation: pass-level similarity check, optional reranker per lines 1827-1831
Update `.knowledge/README.md` per lines 1833-1838 of `docs/plans/fact_redesign.md` to document: new orchestrator command, new CSV columns/tables (containment_edges.csv, artifact manifests, render plans), updated meaning of iterative movements (pass-level records)
Update `scripts/knowledge/README.md` with same changes
Update `docs/processes/information-migration.yml` to document fact-based migration workflow: artifact-level extraction, Hunter/Surgeon/Auditor roles, pass-level tracking, validation loop
Add examples of FieldFact extraction, artifact detection, and multi-agent orchestration
Document projection versioning rules and hashing improvements

Relevant Files:
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\plans\fact_redesign.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\.knowledge\README.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\scripts\knowledge\README.md`
- `c:\Users\xteam\IdeaProjects\ai-workflow\docs\processes\information-migration.yml`
- `c:\Users\xteam\IdeaProjects\ai-workflow\.claude\agents\fact-extractor.md`