### 12. Transitive Anchors (Contextual Relations)

Facts can have **transitive anchors** - relations that provide contextual meaning without being part of the fact itself.

**Structure:**
```
Section A conditions ──┐
                       ├──→ Fact D
Section B conditions ──┘
```

The same fact can appear under different condition groups:
- Group A conditions (from Section A) → Fact D
- Group B conditions (from Section B) → Fact D

**Key Properties:**
- Transitive nodes are relations that change the contextual meaning of facts
- Some transitive nodes are conditional (if X then Y applies to Fact D)
- Transitive nodes can be chained (conditions tied to other conditions)
- A fact can present itself under particular groups of conditions
- **Condition groups are deduplicated** - if the same condition appears in multiple sections, it's stored once with multiple references
- This preserves the "same fact, different contexts" relationship without losing information

**Example:**
```
Source text:
  Section A: "If the user is an admin, the system allows deletion."
  Section B: "If the user is an admin, the system allows modification."

Extracted structure:
  Condition: (user, is, admin) [referenced by Section A, Section B]
  Fact 1: (system, allows, deletion) [under Condition]
  Fact 2: (system, allows, modification) [under Condition]
```

The condition is deduplicated; the facts are distinct but share the transitive anchor.

**Implications for Deduplication:**
- When the same condition appears in multiple contexts, it is stored once with pointers to all contexts where it appears
- Facts that appear under the same conditions are not automatically duplicates - they may be distinct facts that share contextual conditions
- The deduplication process (described in "Deduplication and Similarity Management") must consider both fact content AND transitive anchors to determine true duplicates

**Relationship to Reconstruction:**
- Transitive anchors must be preserved during reconstruction - a fact reconstructed in a specific context must include its contextual conditions
- Reconstruction success for a region that contains conditional facts requires reproducing both the facts AND their transitive anchors
- When anchoring unanchored text, the system must consider whether missing transitive anchors (rather than missing facts) are causing reconstruction failures

---
