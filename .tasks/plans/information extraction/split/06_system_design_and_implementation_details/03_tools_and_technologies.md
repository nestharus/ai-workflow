### Tools and Technologies

```
Programming Language: Python 3.x will be used for deterministic helper scripts (grammar checks, string diffs, etc.).
Execution Harness: Claude Code orchestrates the entire pipeline as the execution harness.
Local Extraction Pipeline Models: The system uses a two-phase sequential pipeline with Claude sub-agents:
- **Haiku 4.5 (sub-agent 1)**: Detail extraction - scans source text for raw observations, statements, claims
- **Haiku 4.5 (sub-agent 2)**: Fact construction and anchoring - transforms details into anchored triplet-structured facts
- **Opus 4.5**: Orchestrates pipeline, runs reconstruction proofs, performs QA validation
Sub-agents communicate via file I/O to avoid filling orchestrator context. The pipeline is
sequential: detail extraction produces raw details (written to files), which are then read by fact construction
for anchoring and triplet structure validation (results written to files).
Reasoning Model (Minimized, Optional): A larger reasoning model may be invoked only when:
- Local models cannot adjudicate borderline dedup merges
- Deterministic rules cannot classify text as fluff vs meaningful
- High-quality Clarification Questions are needed (though template-driven is acceptable)
If local models + deterministic rules suffice, the reasoning model is NOT invoked. This keeps the
system local-first while allowing optional escalation for edge cases.
Embedding Model: Qwen-3 Embedding model (0.6B) via HuggingFace Transformers. Requires
torch and possibly transformers library. If the model is proprietary, the user must agree to its
license (the Qwen models are proprietary but free for research purposes, as of writing). Alternatively,
if license or model size is a concern, an open embedding model like SentenceTransformer or
OpenAI's text-embedding-ada-002 (if allowed locally via API) could be configured. But Qwen-3 is
chosen for its strong performance and local run capability.
Vector Database: SQLite with the sqlite-vss extension (installed via pip). This gives a simple
way to create a vector index in a local file and query it using SQL. The extension uses Faiss internally
for efficient similarity search, so it’s quite performant for our needs. The schema might look like: a
table facts(fact_id INTEGER PRIMARY KEY, fact_text TEXT, embedding VECTOR)
where VECTOR is a datatype provided by the extension (e.g., 1024-dimensional). We will use
statements like SELECT fact_id, fact_text, vss_similarity(embedding, ?) as sim
FROM facts ORDER BY sim DESC LIMIT 5; to get nearest neighbors to a given embedding
(passing the query embedding as a parameter).
Data Structures: In-memory, we will likely use Python lists or pandas DataFrames to hold facts
during processing. Each fact record contains dual representation: canonical fact text (for search/dedup)
and source context (for provenance). We will use interval data structures to track unprocessed work
regions and map source context (character offsets) to their associated facts. Source context is
provenance (where the system was looking when it discovered the fact), NOT text ownership.
Multiple facts may share the same source context; one fact may have multiple source contexts.
Agent Communication: Sub-agents communicate via file I/O to avoid filling orchestrator context:
- **Detail extraction sub-agent** writes raw details to files
- **Fact construction sub-agent** reads details from files and writes facts to files
- **Opus orchestrator** reads fact files and coordinates reconstruction proofs
- **Python helper scripts** are invoked as tools by agents for deterministic operations
The choice depends on hardware and deployment preferences. All support quantized models for
reduced memory footprint.
Documentation & Packaging: Markdown for README. Possibly small helper scripts like
run_extraction.py, run_deduplication.py, etc., which can be combined or sequentially
invoked. These will be documented so a user (or an LLM agent) knows how to execute the full
pipeline step by step.
Grammar Validation Layer (NLTK): NLTK is used as a deterministic pre-filter to FLAG potential
illegal fact fabrications before they enter the knowledge base. NLTK provides a fast, production-ready
grammar analysis layer that complements the Opus reconstruction proof mechanism. **NLTK's scope is
limited to syntax and grammar validation** - it does NOT validate logical inferences or semantic
relationships. Inference validation is handled by Opus as part of the reconstruction proof process.

**Why NLTK:**
- Production-ready, fast, well-documented NLP library with Python 3.14 support
- Provides POS tagging, chunking, and parsing capabilities
- Pure Python implementation (no binary wheel dependencies)
- Pluggable architecture - can integrate with Stanford CoreNLP for advanced parsing

**What NLTK Can Detect:**

| Illegal Fabrication | NLTK Detection Method |
|---------------------|------------------------|
| Hidden Copula Hallucination | No token with VB* POS tag in source, but LLM claims verb |
| Forced Subject Hallucination | No token with NN*/PRP tag before verb in source, but LLM claims subject exists |
| Pronoun Concord Violation | Singular/plural mismatch between noun tags (NN vs NNS) and pronoun patterns |
| Tense Fabrication | Verb POS tag (VBD=past, VBP/VBZ=present) doesn't match LLM's claimed tense |
| Missing Predicate | Source has only noun tags (no VB*), parsed as noun phrase not sentence |

**Configuration Modes (Speed/Accuracy Tradeoff):**

1. **Fast Mode (Default)** - For high-volume validation:
   ```python
   import nltk
   from nltk import pos_tag, word_tokenize
   tokens = word_tokenize(text)
   tagged = pos_tag(tokens)  # Averaged Perceptron Tagger
   # Speed: ~15,000+ words/sec CPU
   # Accuracy: ~97% POS tagging accuracy
   ```

2. **Accurate Mode** - For critical validation with parsing:
   ```python
   from nltk.parse import CoreNLPParser
   parser = CoreNLPParser()  # Requires Stanford CoreNLP server
   parse_tree = list(parser.parse(tokens))
   # Speed: ~500-1000 words/sec
   # Accuracy: State-of-the-art dependency parsing
   ```

**Important Limitations:**
NLTK is statistical, not ground truth:
- FLAGS potential violations, does NOT auto-reject triplets
- Complex/malformed sentences may parse incorrectly
- Flags trigger additional review or Clarification Questions
- User can override flags with justification

**Integration with Existing Concepts:**
- Flags feed into the Illegal Fact Fabrication detection pipeline
- Flagged facts go to Clarification Questions or human review
- Works alongside Inference Validation Layer and Opus reconstruction proof:
  - **NLTK validates SOURCE GRAMMAR** (syntax only - deterministic, rule-based)
  - **Inference Validation validates LOGICAL DERIVABILITY** (Opus-led - requires reasoning)
  - **Opus validates FACT DERIVATION** via reconstruction proof (requires reasoning)
- NLTK is a deterministic pre-filter that catches structural violations; it does NOT validate inferences or replace Opus reconstruction
```
