# Pattern Specification for Gen3 RAG Patches

## Canonical Label Formats

### Goals
- **Format**: `G#` where # is a global sequential number
- **Range**: G1-G5 (plan.md), G6-G8 (P1), G9-G11 (P2), G12-G16 (P4), G17-G21 (P5), G22-G29 (P6), G30-G35 (P7), G36-G41 (P9), G42-G50 (P10)

### Invariants
- **Format**: `P#I#` where first # is patch number, second # is sequential within patch
- **Examples**: P1I1, P4I3, P9I6

### Claims/Proofs
- **Format**: `P#C#` where first # is patch number, second # is sequential within patch
- **Examples**: P1C1, P5C4, P7C3

### Math Sections
- **Format**: `P#.#` where first # is patch number, second # is sequential within patch
- **Examples**: P1.1, P6.3, P9.5
- **Note**: P10 uses `P10.M#` - needs normalization to `P10.#`

### Algorithms
- **Format**: `Algorithm #` where # is a global sequential number
- **Range**: Algorithm 1-5 (plan.md), Algorithm 6-9 (P2), Algorithm 10-16 (P4), Algorithm 17-23 (P5), Algorithm 24-32 (P6), Algorithm 33-38 (P7), Algorithm 39-47 (P9), Algorithm 48-59 (P10)
- **Note**: P1 uses `P1.# name` for algorithms - needs normalization
- **Note**: P8 uses `P7.#` - needs normalization to proper sequence

### Data Structures
- **Format**: PascalCase name
- **Examples**: ObservationRecord, NodeState, Workspace
- **No numeric prefix**

### Gaps
- **Format**: `Gap G#.#` where first # is patch number, second # is sequential within patch
- **Examples**: Gap G2.1, Gap G9.3

### Lean Skeletons
- **Format**: `Lean #` where # is a global sequential number within patch
- **Examples**: Lean 1, Lean 2
- **Note**: P1 uses "Track A/B", P2 uses "Lean A/B" - needs normalization

### Dragons (Spec Gaps/Proof Obligations)
- **Format**: `D#` where # is sequential
- **Examples**: D1, D2 (only in P9 currently)

### Components
- **Format**: `#. ComponentName (ABBREV)`
- **Examples**: 1. Workspace Manager (WSM)

---

## Irregularities to Normalize

### P1 Specific
| Current | Should Be | Location |
|---------|-----------|----------|
| I1, I2, I3, I4, I5 | P1I1, P1I2, P1I3, P1I4, P1I5 | Invariants section |
| P1.1-P1.5 (algorithms) | Algorithm 1-5 | Algorithms section |
| Track A, Track B | Lean 1, Lean 2 | Lean skeletons section |

### P2 Specific
| Current | Should Be | Location |
|---------|-----------|----------|
| Lean A, Lean B | Lean 3, Lean 4 | Lean skeletons section |

### P8 Specific
| Current | Should Be | Location |
|---------|-----------|----------|
| P7.1-P7.5 (algorithms) | Algorithm 39-43 | Algorithms section |
| Numbered sections 1-10 | G36-G45 or keep as-is | Goals section |

### P10 Specific
| Current | Should Be | Location |
|---------|-----------|----------|
| P10.M1-P10.M4 | P10.1-P10.4 | Math notes section |

---

## Label Extraction Regex Patterns

```python
PATTERNS = {
    'goal': r'^[*#\s]*G(\d+)[.\s]',
    'invariant': r'^[*#\s]*(P\d+I\d+|I\d+)',
    'claim': r'^[*#\s]*P(\d+)C(\d+)',
    'math': r'^[*#\s]*P(\d+)\.(\d+|M\d+)',
    'algorithm': r'^[*#\s]*(Algorithm\s+\d+|P\d+\.\d+)',
    'gap': r'^[*#\s]*Gap\s+G(\d+)\.(\d+)',
    'dragon': r'^[*#\s]*D(\d+)',
    'lean': r'^[*#\s]*(Lean\s+\d+|Track\s+[A-Z])',
    'data_structure': r'^##\s+([A-Z][a-zA-Z]+)',
}
```

---

## Cross-Patch Label Registry

This tracks all labels across patches for collision detection.

### Goals (Global Sequence)
- plan.md: C1-C5 (Claims in original)
- P1: G6-G8
- P2: G9-G11
- P4: G12-G16
- P5: G17-G21
- P6: G22-G29
- P7: G30-G35
- P9: G36-G41
- P10: G42-G50

### Algorithms (Global Sequence)
- plan.md: Algorithm 1-5
- P2: Algorithm 6-9
- P4: Algorithm 10-16
- P5: Algorithm 17-23
- P6: Algorithm 24-32
- P7: Algorithm 33-38
- P8: Algorithm 39-43 (needs renumbering from P7.1-P7.5)
- P9: Algorithm 44-52 (needs renumbering - currently 24-32 collision)
- P10: Algorithm 53-64 (needs renumbering - currently 31-42 collision)
