### 7. Anchoring Unanchored Text

When reconstruction fails and produces uncovered text (via Python diff), that text is **unanchored** - no fact in the current set explains it.

**Example:**
- **Target T(S)**: "Replace partition-style span fragmentation with **work region tracking** over the canonical input string"
- **Reconstructed R(S)**: "Replace partition-style span fragmentation with **work region tracking**"
- **Uncovered text**: "over the canonical input string"
- **Status**: This phrase is UNANCHORED - we don't know what fact/entity explains it

**The Anchoring Operation:**

"Targeted extraction against uncovered words/phrases" is actually an **anchoring search**:

1. **Entity Position Index query**: Given the character position of the uncovered phrase, query the Entity
   Position Index (see Deduplication and Similarity Management) to find entities whose spans are
   positionally closest. These nearby entities provide context for what the uncovered phrase might relate
   to - they are the subjects/objects that appeared in the surrounding text.
2. **Existing fact search via nearby entities**: Using the entities found in step 1, search the fact graph
   for facts involving those entities. These facts may contain relations that explain the uncovered text.
   For example, if the uncovered phrase is "over the canonical input string" at position 100, and the
   Entity Position Index returns "work region tracking" at [80, 99], search for facts involving
   "work region tracking" to find potential explanations.
3. **Context expansion**: If the Entity Position Index and fact search don't yield explanations, expand
   to surrounding text in the source document for additional clues.
4. **New fact extraction**: Pass the uncovered phrase + nearby entities + expanded context to the detail
   extraction sub-agent (Haiku 4.5) to extract NEW details, which are then transformed into anchored
   facts by the fact construction sub-agent (Haiku 4.5).
5. **Anchor validation**: If new facts are extracted, re-run reconstruction to see if uncovered text shrinks.

**Anchoring Outcome Semantics:**

The anchoring search is the mechanism that distinguishes:
- **Missed facts** (anchoring succeeds → new facts reduce uncovered text → continue iteration)
- **Incomprehensible structure** (anchoring fails → no new facts anchor the text → Clarification Question)

**If Anchoring Fails:**

If after bounded attempts we CANNOT find an anchor for the uncovered text:
- The LLM was **unable to understand the structure** of the text
- This is NOT a "missed fact" - it is a structural comprehension failure
- The system MUST emit a **Clarification Question** asking the author what the unanchored text means/belongs to

Anchoring failure is the specific trigger for Clarification Question emission, not merely "stalled progress" in the abstract.
