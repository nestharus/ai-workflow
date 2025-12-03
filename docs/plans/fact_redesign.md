Here’s a redesign that fully treats:

* object IDs as entities,
* field names as part of the fact,
* and object membership (ancestor chain) as the core context.

I’ll start with the shared data model and then show how `extract_ids_and_text`, `resolution_tracker.py`, and `candidate_extraction.py` change, plus how this plugs into your fact pipeline.

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

* If you’re “viewing” element `E` (root id `E.id`), and you encounter a nested dict with its own `id`, you:

    * treat that nested dict as a separate element `C`,
    * record a **containment edge** from `E` to `C` at a specific field path,
    * and **do not inline C’s internals** when computing facts or hashes for `E`.

Containment edge structure:

```python
@dataclass
class ContainmentEdge:
    parent_id: str        # E
    child_id: str         # C
    field_path: str       # e.g. "items[2]" or "routes[0].handler"
    source_file: str      # for provenance
```

In the parent’s data, the nested object is replaced with a **reference**:

```yaml
items:
  - $ref: child_id
```

(concretely: a dict like `{"$ref": "child_id"}` or just `"child_id"`—pick one and standardize).

This solves your “nested objects with IDs” question: children are entities in their own right; parents only carry **edges** to them, not their internal content.

---

## 2. Field-facts: how to represent “facts” structurally

The unit of raw information is a **field-fact**:

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
```

Notes:

* `field_path` encodes **all anonymous containers** (`fields[0].constraints.min`) so you can travel “up and down” without needing synthetic IDs.
* Sibling fields that share the same `scope_path` form **constraint groups** (e.g. a `raises[0]` block where `type`, `status_code`, and `description` combine into one semantic constraint).
* The **field name is part of the fact**: “`status_code=404`” means nothing without the name `status_code` and the scope `raises[0]`.

Extraction algorithm (per element `E`):

1. Build the **element slice**: same dict, but nested `id`-bearing dicts replaced by `{"$ref": child_id}`; record a `ContainmentEdge` for each.
2. Flatten the slice into `FieldFact`s:

    * Skip root `id` if you don’t want it as a fact.
    * For dicts-without-id, recurse.
    * For lists, recurse; include indices in path.
    * When you hit a scalar or a ref, emit a `FieldFact`.

This gives you a pure structural representation that is:

* aware of field names,
* anchored in element ID,
* and can reconstruct constraint groups (anything sharing `scope_path`).

---

## 3. `extract_ids_and_text`: a compatibility layer over field-facts

Both `resolution_tracker.py` and `candidate_extraction.py` still import `extract_ids_and_text` from `compare_yaml_docs`.

You can restore that function in `compare_yaml_docs.py` as a **text view** over the new field-fact model without changing their signatures.

### 3.1 New core helpers (in `compare_yaml_docs.py`)

Add these:

```python
from dataclasses import dataclass

@dataclass
class ElementContext:
    id: str
    obj: dict[str, Any]
    path: str                # YAML path of the element’s dict
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
    """Return id → 'fact text' for compatibility with older code.

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

* `id → text` as before (so existing functions don’t break),
* but that “text” is now a deterministic, **structure-aware fact view**:

    * field names are literally in the text (`field_path`),
    * ancestor elements are in the text (`[ancestor > element]`),
    * nested entities appear only as `$ref:child_id`, not inlined.

---

## 4. Hashing in `resolution_tracker.py` (Q1)

`resolution_tracker` currently:

* calls `extract_text_for_id`, which uses `parse_yaml_file` + `extract_ids_and_text`,
* then hashes the returned text with `compute_text_hash`.

With the new `extract_ids_and_text`, **you don’t need to change `resolution_tracker.py` at all** to get structurally accurate hashes:

* the “text” is now a canonical concatenation of field-facts for that element,
* nested elements have been replaced with `$ref` tokens, so parent hashes don’t change when a child’s internal fields change,
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

2. Option A (minimal change): keep using `compute_text_hash` in `resolution_tracker`, but know it’s hashing the **fact text** produced by the above machinery.
3. Option B (schema change): add `original_content_hash` / `split_content_hash` columns to `resolved.csv` and populate them using `compute_element_content_hash`, keeping `*_text_hash` for backward compatibility.

Either way, you are now effectively hashing the **semantic object content**, not a fragile “text field”.

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

Thus, without touching `candidate_extraction.py`, Stage 1 now “sees”:

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

* “which object is the entity?” → appears in the `[elements: ...]` part.
* “which fields are constraints?” → field names and scope appear explicitly.
* Embedded prose in values is still available for SPA/E regex extraction.

---

## 6. Structural entity vs constraint roles

You also raised:

> Which object is the entity? Which fields are constraints? Which fields are entities? Some fields can also have embedded text that needs to be broken down.

You now have the raw material to let later stages decide:

1. **Entity candidates**

    * Every element id is an entity candidate (from YAML structure).
    * Values of fields like `name`, `title`, `summary`, `command`, `keyword`, etc. (configurable list) are also entity-like strings.
    * Nested elements referenced via `$ref` are entity relationships (parent/child, composition, etc.), matching the future SurrealDB entity graph in `KNOWLEDGE SYSTEM README.md`.

2. **Constraints**

    * Any `FieldFact` whose `value_kind` is not obviously an entity (e.g. numbers, booleans, enums) can be treated as a constraint on the subject element (and optionally grouped by `scope_path`).
    * E.g. facts sharing scope `raises[0]` combine into one “raises HTTPException with status_code=404 and description='…'”.

3. **Embedded text**

    * For fields where `value_kind == "scalar-str"` and the value looks like prose or code, you can:

        * run your existing `fact_extraction.py` on those strings, but now with:

            * `entity` = either element id or keyword (e.g. `create_app`), and
            * extra metadata: `source_file`, `element_id`, `field_path`.
        * store extracted atomic facts in `.knowledge/facts/extractions.csv` as you already do, but extended with these structural columns.

This is where your “travel up and down objects” requirement is satisfied: when you resolve an entity, you look at:

* `element_id` (which object),
* `field_path` and `scope_path` (which part of the object),
* `ancestors` (which larger object this belongs to),
* and `$ref` edges (how it connects to other elements).

---

## 7. How this changes each existing module concretely

### 7.1 `compare_yaml_docs.py`

* **Keep** `extract_ids_and_objects` as-is; it’s used for dict-to-dict comparisons.
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
* Semantics change from “hash of some text field” to “hash of canonical field-fact projection”:

    * changes to any field name/value under that element change the hash,
    * changes to nested elements’ internals do **not** (only the `$ref` changes if the relationship changes).

Optional: add new columns `original_content_hash` / `split_content_hash` later, populated from `compute_element_content_hash`, and treat existing `*_text_hash` as deprecated aliases.

### 7.3 `candidate_extraction.py`

* **No code changes required** to make it structurally aware, once `extract_ids_and_text` is replaced.

* It will now see a “document” per element that is:

    * line-based,
    * includes ancestor chain, field_path, and values,
    * and has nested entities represented as `$ref:...`.

* For future refinement you can:

    * add `field_path` / `scope_path` columns to `CandidateRecord` and the candidates CSV schema (breaking change, but straightforward).
    * change dedup key from `(source_file, element_id, candidate_text)` to `(source_file, element_id, candidate_text, sentence)` if you want to differentiate roles of the same word in different fields.

### 7.4 `fact_extraction.py` + `fact_store.py` (integration point, not strictly required now)

Right now they operate on generic sentences and don’t know about YAML structure.

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

1. **Should `resolution_tracker` hash the entire object or “text content”?**
   Hash the **canonical field-fact projection** of the element:

    * Build element slice with nested ids replaced by refs.
    * Flatten to field-facts (field names + values).
    * Canonicalize (`field_path`, `value_kind`, normalized value).
    * Hash that canonical representation.

   This is logically “hashing the object”, but via a stable, schema-aware projection rather than raw YAML bytes.

2. **Should `candidate_extraction` run NLP on each field separately or concatenate?**
   Use the compatibility layer to **concatenate structured fact lines** per element:

    * Each line encodes: ancestor chain, scope path, field key, and value.
    * NLP sees a synthetic “sentence” like

      `[project > factory.create_app] raises[0].status_code = 404`

   That gives it enough context to tell entities from constraints, while keeping your current CSV schema.

3. **How to handle nested objects with IDs?**

    * Treat every `id`-bearing dict as its own element.
    * In parent elements, **replace nested id objects with `{ "$ref": child_id }`** and record a `ContainmentEdge(parent_id, child_id, field_path)`.
    * Do not inline child content into the parent’s facts or hashes.

This design:

* makes **field names first-class**,
* treats **object membership and ancestor chain as context**, not incidental,
* and gives you a clear path from YAML → field-facts → keyword candidates → entity/fact extraction, without breaking existing callers of `extract_ids_and_text`.
