### Example Walk-through: Island Join Failure

To illustrate the Island Join Failure mode, consider this malformed input text:

```
Replace partition-style span fragmentation with work region tracking over the canonical input
string red flowers scattered across the pavement, erupting from the palms of its hands also
buffalo sauce.
```

Assume we have two sets of facts from different sources:
- **Technical facts**: (Work region tracking, replaces, partition-style span fragmentation), (Work region tracking, operates over, canonical input string), etc.
- **Nonsense facts**: (Red flowers, are scattered across, the pavement), (Red flowers, erupting from, palms of hands), (Hands, also have, buffalo sauce), etc.

The system would process this as follows:

**Phase 1 - Two-Phase Extraction Pipeline:** The detail extraction sub-agent (Haiku 4.5 sub-agent 1) scans
the text and extracts raw details from both segments. The fact construction sub-agent (Haiku 4.5 sub-agent 2)
transforms these into anchored facts. Due to the concatenated nature, technical facts are extracted from the
first part, nonsense facts from the second.

**Phase 2 - Opus-Led Formal Proof Reconstruction:**
- Initial span: entire text
- Opus attempts reconstruction...
- Opus identifies two independently reconstructable segments:

**Island 1 Discovery:**
  - Text: "Replace partition-style span fragmentation with work region tracking over the canonical input string"
  - Char offsets: [0, 104)
  - Facts used: [TechFact1, TechFact2, TechFact3]
  - Reconstruction proof succeeds: all words/phrases anchored
  - Status: PROVEN

**Island 2 Discovery:**
  - Text: "red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce."
  - Char offsets: [105, 203)
  - Facts used: [NonsenseFact1, NonsenseFact2, NonsenseFact3]
  - Reconstruction proof succeeds: all words/phrases anchored
  - Status: PROVEN

**Join Failure Detection:**
  - Boundary offset: 104 (between "...input string" and "red flowers...")
  - Terminal phrase of Island 1: "canonical input string"
  - Initial phrase of Island 2: "red flowers"
  - Join anchor search:
    - Check all facts for relation connecting "canonical input string" to "red flowers": NONE FOUND
    - Check for valid conjunctions/prepositions at boundary: NONE PRESENT
    - Check grammar rules for valid noun phrase concatenation: INVALID (two noun phrases cannot be adjacent without connector)
  - Result: UNANCHORED JOIN detected

**Phase 3 - ReconstructionFailure Artifact Produced:**
```json
{
  "span_id": "span_001",
  "original_text": "Replace partition-style span fragmentation with work region tracking over the canonical input string red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce.",
  "reconstructed_text": null,
  "uncovered_words_phrases": [],
  "island_join_failure": {
    "failure_type": "ISLAND_JOIN_FAILURE",
    "islands": [
      {
        "island_id": "island_001",
        "text": "Replace partition-style span fragmentation with work region tracking over the canonical input string",
        "char_offsets": [0, 104],
        "status": "PROVEN",
        "anchoring_facts": ["TechFact1", "TechFact2", "TechFact3"]
      },
      {
        "island_id": "island_002",
        "text": "red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce.",
        "char_offsets": [105, 203],
        "status": "PROVEN",
        "anchoring_facts": ["NonsenseFact1", "NonsenseFact2", "NonsenseFact3"]
      }
    ],
    "unanchored_boundaries": [
      {
        "boundary_offset": 104,
        "island_before_id": "island_001",
        "island_after_id": "island_002",
        "terminal_phrase": "canonical input string",
        "initial_phrase": "red flowers",
        "join_anchoring_attempts": [
          {
            "attempt_number": 1,
            "relations_searched": ["(canonical input string, ?, red flowers)", "(input string, ?, flowers)"],
            "connectors_searched": ["and", "or", "with", ",", ";"],
            "join_anchor_found": false
          }
        ]
      }
    ]
  },
  "facts_used": ["TechFact1", "TechFact2", "TechFact3", "NonsenseFact1", "NonsenseFact2", "NonsenseFact3"],
  "proof_trace": "Islands proven independently. Join anchor search failed at boundary 104."
}
```

**Phase 4 - Clarification Question Emitted:**
```json
{
  "doc_id": "doc_001",
  "region_offsets": [0, 203],
  "original_text": "Replace partition-style span fragmentation with work region tracking over the canonical input string red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce.",
  "failure_type": "ISLAND_JOIN_FAILURE",
  "failure_statement": "The system can explain each segment independently but cannot determine the relationship between them.",
  "clarification_request": "What is the relationship between 'canonical input string' and 'red flowers'? These segments appear adjacent but no connecting relation was found.",
  "island_context": {
    "islands": [
      {"text": "Replace partition-style span fragmentation with work region tracking over the canonical input string", "status": "PROVEN"},
      {"text": "red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce.", "status": "PROVEN"}
    ],
    "boundary_offset": 104,
    "terminal_phrase": "canonical input string",
    "initial_phrase": "red flowers"
  },
  "author_response": null
}
```

**Key Observations:**
1. This is NOT an unanchored text failure - every word in both islands has fact coverage
2. The failure is at the JOIN level - no relation or connector explains why these segments are adjacent
3. The system correctly identifies this as likely source text corruption (concatenation from unrelated sources)
4. The Clarification Question targets the specific boundary, not the entire text
5. A valid author response might be: "These are two unrelated sentences that were accidentally merged. They should be separated." or "Missing comma - should read '...input string, and red flowers...'"

This example demonstrates that Island Join Failures require a different diagnostic approach than standard unanchored text failures. The system must track islands separately and explicitly test join anchors at boundaries.
