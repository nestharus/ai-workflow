### 8. Island Join Failures

When reconstruction operates on complex text, the system may successfully prove multiple independent segments (called **islands**) but fail to connect them. This is a distinct failure mode from unanchored text.

**Terminology:**
- **Island**: A segment of text that can be independently proven through reconstruction (all its words/phrases are anchored by facts)
- **Join anchor**: The connector that would link two adjacent islands - this could be a conjunction ("and"), preposition ("over", "from"), punctuation (comma), or a relation triplet connecting concepts across the boundary
- **Unanchored join**: Two proven islands with no join anchor between them
- **Boundary**: The character offset where one island ends and another begins

**Example:**
- **Target T(S)**: "Replace partition-style span fragmentation with work region tracking over the canonical input string red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce."
- **Island 1**: "Replace partition-style span fragmentation with work region tracking over the canonical input string" - PROVEN (technical facts anchor all words)
- **Island 2**: "red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce." - PROVEN (nonsense facts anchor all words)
- **Join failure**: No fact or relation connects "...input string" to "red flowers..." - the boundary between the two islands has no anchor

**Distinguishing Island Join Failures from Unanchored Text:**
- **Unanchored text**: A segment exists that no fact can explain (the anchoring operation fails to find facts for some words/phrases)
- **Unanchored join**: Both segments ARE explained by facts, but no fact/relation provides a JOIN between them

The key insight is that both islands are individually PROVEN - all their words/phrases are anchored. The failure occurs at the composition level: the system cannot explain why these two proven segments appear adjacent in the source text.

**What Unanchored Joins Indicate:**
The source text may be:
- Malformed or corrupted (accidental concatenation)
- Missing punctuation or explicit connectors that the author intended
- Concatenated from two unrelated sources without proper transition
- Containing an implicit semantic boundary the author did not mark

**System Response to Island Join Failures:**
When the system detects two proven islands that cannot be joined:
1. Record both islands as independently PROVEN with their respective fact anchors
2. Identify the JOIN boundary (character offset where Island 1 ends and Island 2 begins)
3. Attempt bounded join anchoring: search existing facts for any relation that could connect the terminal concept of Island 1 to the initial concept of Island 2
4. If join anchoring fails after bounded attempts, emit a **Clarification Question** specifically requesting: "What is the relationship between [Island 1 terminal phrase] and [Island 2 initial phrase]? These segments appear adjacent but no connecting relation was found."
5. The ReconstructionFailure artifact includes both proven islands and marks the unanchored boundary

This is NOT a case where more extraction would help - both islands already have complete fact coverage. The failure is structural: the source text lacks an explicit connector that the system requires to explain the composition.
