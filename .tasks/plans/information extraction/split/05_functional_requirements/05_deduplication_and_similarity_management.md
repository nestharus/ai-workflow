### Deduplication and Similarity Management

```
Embedding-Based Similarity: The system shall use semantic embedding to compare facts and find
duplicates or near-duplicates. Each extracted fact (as text) will be converted into a high-dimensional
vector representation using a pre-trained embedding model. We will use the Qwen-3 Embedding
model (by Alibaba/QwenLM) for this purpose, leveraging its strong semantic representation
capabilities. This model provides state-of-the-art text embeddings and can capture nuances
in meaning, ensuring that semantically identical facts (even if worded differently) are mapped to
similar vectors in the embedding space.
Local Embedding Computation: The embedding model will be run locally via PyTorch. The Qwen-
series has various sizes (0.6B, 4B, 8B parameters); for a balance of speed and accuracy on a dev
machine, we can start with the 0.6B model variant which yields 1024-dimensional embeddings.
PyTorch will load this model (likely via HuggingFace Transformers), and compute embeddings for
each fact string. This step requires that the system’s environment has the model files (which can be
downloaded or cached) and a capable CPU/GPU. (A GPU is optional but would accelerate embedding
computation).
Vector Database Storage: All fact embeddings will be stored in a vector database to enable
efficient similarity search. We will use an embedded database solution to keep everything local.
SQLite with the sqlite-vss extension is a strong candidate, as it allows storing vectors and
performing k-nearest-neighbor similarity searches directly in a lightweight database file. This
provides privacy (all data is local), simplicity, and portability (a single SQLite file), aligning with
our local-first requirement. The vector DB will maintain columns for: the fact ID, the canonical fact
text, the embedding vector (computed from canonical text), and source context references (character
offsets as provenance markers, NOT ownership claims). An index will be built on the embedding column
(the sqlite-vss extension uses FAISS internally for efficient similarity queries). Note: embeddings
are computed on canonical fact text (not source context) to enable semantic similarity operations on
normalized, self-contained facts.
Entity Position Index: Alongside the semantic vector database, the system maintains a **positional
index** mapping entities to their character offset spans in the canonical input string. This index
enables spatial nearest neighbor search - finding entities that are positionally close to a given
location in the text, regardless of semantic similarity.

The entity position index stores:
- **entity_id**: Unique identifier for each entity (subjects and objects from extracted facts)
- **entity_text**: The normalized entity string (e.g., "the device", "dog")
- **spans**: List of `[start_char, end_char)` ranges where this entity appears in the canonical string
- **fact_ids**: List of facts in which this entity participates

**Spatial Nearest Neighbor Search**: Given a character position X, the index returns entities whose
spans are closest to X, sorted by distance. Distance is computed as `min(|X - span_start|, |X - span_end|)`
for each span. This is fundamentally different from semantic embedding similarity - it finds entities
that are **positionally proximate** in the source text.

**Use Cases**:
1. **Coreference Resolution**: When encountering a pronoun "it" at position 100, query the index for
   entities with spans ending before position 100. The closest entity (e.g., "dog" at [80, 83]) is the
   most likely antecedent candidate.
2. **Anchoring Unanchored Text**: When text at position X cannot be explained by existing facts,
   find nearby entities in the position index. These entities provide context for what the unanchored
   text might relate to.
3. **Island Join Resolution**: When two proven islands cannot be connected, find entities near the
   boundary offset to identify potential bridging concepts.

The position index is built incrementally as facts are extracted. Each fact's subject and object
entities are indexed with their source context spans. This enables efficient positional lookups
without rescanning the source text.
Duplicate Fact Detection: For each fact in the extracted list, the system will query the vector
database for similar entries. Using cosine similarity on embeddings , it will retrieve the nearest
neighbors – i.e., other facts that are potentially semantically identical or overlapping. A similarity
threshold (for example, >0.9 cosine similarity) or a top-K approach will be used to shortlist
candidates. This finds facts that might be duplicates of the current one.
LLM-Assisted Consolidation: The candidate similar facts will be passed to the fact construction
sub-agent for a final determination. The Haiku 4.5 sub-agent will receive
the list of a fact and its nearest neighbors and will analyze their meanings to decide which ones are
truly identical in meaning:
If two or more facts express the same thing, the LLM will label them as duplicates. In that case, those
facts should be consolidated into one. The system will keep one canonical instance of the fact and
remove the others from the list (and from the vector index) to eliminate redundancy.
Prior to removal, all references from the duplicate facts are merged into the canonical fact's
reference list (so no source information is lost). For example, if Fact X and Fact Y are judged identical,
and Fact X came from pages 3 and 10 of the document while Fact Y came from page 15, the unified Fact X
entry will note references to pages 3, 10, and 15.
If the LLM determines the facts are similar but not actually identical in meaning or scope, then they
remain as separate entries. (The similarity search might sometimes group things that are related but
not true duplicates; the LLM can use its understanding to make the call.)
Iterative Duplicate Removal: The deduplication process will iterate through all facts. Each fact
serves as the "query" to find duplicates, which are then consolidated. The order of iteration will be
managed such that once a fact is consolidated and marked as canonical, it won't be processed again
as a duplicate of something else (to avoid bouncing back and forth). By the end of this process, every
remaining fact in the list should be unique in content. This approach, combining embeddings and an
LLM, ensures high accuracy in deduplication – we leverage the speed of vector similarity to narrow
candidates and the judgment of an LLM to handle nuanced cases, rather than relying on a simple
threshold alone.
No Information Loss: Deduplication must not drop any unique information. This means if two
statements differ in any detail (even subtle), they should not be merged. Only truly identical facts (or
ones where one is a rephrasing of another) get merged. The LLM comparison helps guard against
mistakenly merging non-identical facts. All original fact references and context are preserved as
noted.
Transitive Anchors and Context-Aware Deduplication: Per Invariant #12 (Transitive Anchors), the
same fact appearing under different contextual conditions is NOT automatically a duplicate. For
example, if "the system allows deletion" appears under condition A ("if user is admin") and also under
condition B ("if user is superuser"), these are the SAME fact with different transitive anchors (contextual
relations). The fact is stored once, and both conditions reference it. However, if the fact content itself
differs (e.g., "system allows deletion" vs "system allows modification"), these are DIFFERENT facts
even if they share the same conditions. The deduplication process must consider:
- **Fact content deduplication**: Merge identical fact content regardless of transitive anchors
- **Condition deduplication**: Merge identical conditions appearing in multiple contexts (per Invariant #12)
- **Preserve transitive anchor relationships**: Maintain all condition-to-fact and condition-to-condition links
This ensures that "same fact, different contexts" relationships are preserved without information loss,
enabling future editing systems to handle context-specific fact variants (see "Scope Boundary: Extraction
vs Editing" in Ambiguities and Assumptions).
```
