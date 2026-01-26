---
description: Break down large specifications into isolated, ID-tracked documents
allowed-tools: Read, Write, Bash, Task, Glob, Grep
---

# Specification Decomposition

Break down large specifications into isolated entity documents using GLM sub-agents.

## Core Principles

1. **Needle in Haystack**: LLMs find WHERE something is with high accuracy
2. **No Categorization**: Never ask "is this X or Y?" - list comparison fails
3. **Theorize with Evidence**: Agents guess and provide line numbers as proof
4. **Files Not Returns**: Agents write to files, return only filename
5. **Orchestrator Loops, Not Agents**: Each agent is ONE forward pass

## Extraction Hierarchy

1. **Entity extraction** (within files) → entity orphans
2. **File extraction** (cross-file, files become entities) → file orphans
3. **Project investigation** (against entire project) → final orphans
4. **Value assessment** → drop orphans that add no value

## Input

$ARGUMENTS - Path to specification file(s)

## Workflow

### Phase 1: Initialize Workspace

```bash
uv run python -m scripts.spec_decomposition init "$ARGUMENTS" --workspace .tmp/spec_decomposition
```

### Phase 2-3: Entity Discovery and Extraction

Iterative entity discovery within each file:

```
WHILE entities found:
    A: entity-finder on discovery staging
    FOR each entity:
        B: entity-investigator (fresh staging) - what IS it
        C: context-finder (redacted, iterative) - what does it FIT INTO
```

**Step A: Entity Discovery**

```bash
# 1. Format discovery content
uv run python -m scripts.spec_decomposition format-discovery \
  --workspace .tmp/spec_decomposition \
  --output .tmp/spec_decomposition/discovery_input.txt

# 2. Run entity-finder agent
uv run python -m scripts.agents entity-finder <<EOF
content: |
$(cat .tmp/spec_decomposition/discovery_input.txt)

output_file: .tmp/spec_decomposition/entities_found.json
EOF

# 3. For each entity found, extract to workspace
uv run python -m scripts.spec_decomposition extract-entity \
  --workspace .tmp/spec_decomposition \
  --entity "<EntityName>" \
  --evidence '[{"file": "<source>", "line": <num>, "text": "<text>"}]' \
  --keywords '["keyword1", "keyword2"]'
```

**Step B: Entity Investigation (for each entity)**

```bash
# 1. Create fresh staging from originals
uv run python -m scripts.spec_decomposition create-investigation-staging \
  --workspace .tmp/spec_decomposition \
  --entity "<EntityName>"

# 2. Run entity-investigator agent
uv run python -m scripts.agents entity-investigator <<EOF
entity_name: <EntityName>

content: |
$(cat .tmp/spec_decomposition/staging/investigation/<EntityName>_combined_investigation.md)

output_file: .tmp/spec_decomposition/investigation_<EntityName>.json
EOF

# 3. Process findings
uv run python -m scripts.spec_decomposition process-investigation \
  --workspace .tmp/spec_decomposition \
  --findings .tmp/spec_decomposition/investigation_<EntityName>.json \
  --redact-discovery
```

**Step C: Context Extraction (iterative until empty)**

```bash
# 1. Run context-finder agent on redacted investigation content
uv run python -m scripts.agents context-finder <<EOF
entity_name: <EntityName>

entity_info: |
$(cat .tmp/spec_decomposition/entities/<EntityID>.md)

content: |
$(cat .tmp/spec_decomposition/staging/investigation/<EntityName>_combined_investigation.md)

output_file: .tmp/spec_decomposition/context_<EntityName>.json
EOF

# 2. Process context findings
uv run python -m scripts.spec_decomposition process-context \
  --workspace .tmp/spec_decomposition \
  --findings .tmp/spec_decomposition/context_<EntityName>.json \
  --entity "<EntityName>"

# 3. Repeat until no more context found
```

### Phase 4: Entity-Level Orphan Investigation

Orphans that might relate to known entities.

```bash
# 1. Prepare orphan investigation input
uv run python -m scripts.spec_decomposition investigate-orphans \
  --workspace .tmp/spec_decomposition \
  --level entity

# 2. Run orphan-investigator agent
uv run python -m scripts.agents orphan-investigator <<EOF
orphan_lines: |
$(cat .tmp/spec_decomposition/orphans_entity_input.json)

known_entities: |
$(cat .tmp/spec_decomposition/orphans_entity_context.json)

output_file: .tmp/spec_decomposition/orphan_entity_analysis.json
EOF

# 3. Process orphan findings
uv run python -m scripts.spec_decomposition process-orphans \
  --workspace .tmp/spec_decomposition \
  --findings .tmp/spec_decomposition/orphan_entity_analysis.json
```

Links orphans to entities or marks as file-level orphans.

### Phase 5: File-Level Extraction (Cross-File)

Files become entities. For each file, extract information from OTHER files.

```
FOR each file:
    WHILE info found:
        file-extractor on OTHER files (not the file itself)
        Extract what other files say about this file
        Redact from other files
```

**Agent Input (file-extractor):**
- `file_name`: The file we're finding info about
- `content`: Content from OTHER files (numbered lines)
- `output_file`: Where to write findings

This captures:
- References to this file from other files
- Cross-file dependencies
- Shared concerns across files

### Phase 6: Project-Level Orphan Investigation

Remaining orphans investigated against entire project:

```bash
uv run python -m scripts.spec_decomposition investigate-orphans \
  --workspace .tmp/spec_decomposition \
  --level project
```

Run project-investigator with:
- Remaining orphan lines
- Entire project context (all entities, all files)
- Looking for any connection or meaning

### Phase 7: Value Assessment

Final orphans assessed for value:

```bash
uv run python -m scripts.spec_decomposition assess-orphan-value \
  --workspace .tmp/spec_decomposition
```

Run value-assessor agent on each final orphan:
- Does this statement add any value?
- Is it actionable information?
- Or is it noise (e.g., "you did well", "good job")?

Drop orphans with no value. Keep valuable standalone statements.

### Phase 8: Fact Tagging

The decomposer produces evidence-heavy docs, but they are not directly usable as implementable specs.
Tagging assigns stable IDs to **source lines** (facts) so duplicates can be referenced consistently.

```bash
uv run python -m scripts.spec_decomposition tag-facts --workspace .tmp/spec_decomposition
```

This creates:
- `facts.json` (canonical fact store keyed by `F-###`)
- `fact_id` annotations inside `id_map.json` entries

### Phase 9: Recomposition

Recomposition turns the decomposed artifacts into **implementable** specs without rewriting content
(pure regrouping/moving by IDs).

```bash
uv run python -m scripts.spec_decomposition recompose --workspace .tmp/spec_decomposition
```

This writes a recomposed bundle under `output/recomposed/` including:
- `spec.json` (machine-friendly)
- `facts.md` and `entities.md` (human-friendly)

### Phase 10: Alias Handling

Alias detection is inherently heuristic. Treat any alias output as *a hypothesis*, not truth.
The reliable place to resolve aliases is **during implementation**, when real integration work
reveals that two components are the same system.

### Dependency Ordering Note

Dependencies are often implicit in specs. The relation graph and any inferred ordering should be treated
as a hint only.

Implementation should proceed iteratively:
- Implement what you can from the recomposed bundle.
- When blocked, record the missing need as a gap (with the IDs you were working on).
- Implement whatever fills that need next, then resume.
- Track "complete" vs "partial" IDs, and attach the implementation files for each ID so other work can build on partials.

### Phase 11: Finalize

```bash
uv run python -m scripts.spec_decomposition finalize --workspace .tmp/spec_decomposition
```

## Output

- Entity documents with evidence
- Relations/context for each entity
- File-level cross-references
- Valuable orphan statements
- Dropped no-value content (logged)
