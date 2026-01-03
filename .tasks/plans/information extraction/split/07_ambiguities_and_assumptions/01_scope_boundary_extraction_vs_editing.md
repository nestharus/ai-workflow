### Scope Boundary: Extraction vs Editing

This system focuses exclusively on **extraction** from source text. Editing operations (modifying facts after extraction) are explicitly **out of scope**.

**Extraction vs Editing:**

| Concern | In Scope? | Description |
|---------|-----------|-------------|
| Fact extraction | YES | Extract facts from source text |
| Transitive anchors | YES | Capture contextual relations |
| Condition deduplication | YES | Dedupe shared conditions |
| **Fact splitting** | NO | When editing diverges a fact in one context |

**Fact Splitting (Out of Scope):**

When a user edits a fact within a specific context, the fact may need to "split" - diverging from its shared form into context-specific variants. This is an **editing concern**, not an extraction concern.

Example of fact splitting (out of scope):
```
Before edit:
  Condition A → Fact D
  Condition B → Fact D  (same fact)

After edit (user changes Fact D only in context B):
  Condition A → Fact D  (original)
  Condition B → Fact D' (modified variant)
```

This splitting behavior is part of a future editing system, not the extraction system.

**Key Invariant:**

The extraction structure must NOT lose information. All transitive anchors and condition groups must be preserved (per Invariant #12: Transitive Anchors) so that editing can be implemented later without information loss.

**Why This Matters:**

- The extraction system's job is to preserve all information from the source text in a structured form
- Editing concerns (like fact splitting, variant management, edit propagation) require different semantics and are deferred to future work
- The current system guarantees that no information is lost during extraction, making future editing systems possible
- Transitive anchors (Invariant #12) enable this by preserving "same fact, different contexts" relationships

---
