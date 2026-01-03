## Objectives and Goals

```
Comprehensive Fact Extraction: Parse an input document of arbitrary length (potentially hundreds of
pages) and extract base facts sufficient for reconstructing the text and deriving all implied facts.
Completeness is defined by derivability: the system must preserve base facts from which all
implications can be logically derived, not extract every possible implication explicitly. This includes
capturing all details, conditions, and relationships described in the text.
Atomic Information Units: Break down complex or compound sentences into atomic facts – each
fact represents a single, indivisible piece of information or a single relationship. No extracted fact
should contain an “and” or multiple assertions in one; each atomic fact should be one complete,
standalone truth.
Deduplication of Repeated Details: If the same fact or detail appears multiple times in the
document (even phrased differently), it should be extracted only once. The system will maintain
references to all locations where that fact appeared, instead of storing duplicates. This creates a
single source of truth for each fact.
Context and Conditional Relationships: Preserve contextual logic. If a fact is only true under
certain conditions (e.g. "If X, then Y"), the system must capture that conditional relationship by
linking the prerequisite fact (X) to the conditional fact (Y) instead of merging them into one
statement. This ensures that context-dependent facts are not lost but represented as such (with a
parent/child or dependency relation).
Traceability: For every extracted fact, provide traceability back to the original document. The output
must include references as character offsets into the canonical input string, indicating where each fact
was found in the source document. If the same fact came from multiple locations, all such character offset
references are recorded.
Ease of Updates: Make it straightforward to add, remove, or modify individual facts in the
knowledge base. Because each fact is stored once, updates to a fact (e.g. changing a requirement
value) can be done in one place and are inherently reflected in all original contexts. The system
should handle merging new information (when new documents or sections are added) by extracting
and deduplicating those new facts as well.
Output for LLM Consumption: Provide the resulting fact database in a format that can be easily
packaged (zipped) and supplied to an LLM or other tools. This includes a clear README/
documentation explaining the contents and how to use them. The facts could be stored as a CSV or
JSON list of facts (with metadata like references and context links), along with any vector index files,
making it easy for an LLM or developer to navigate and search the facts.
Local, Lightweight Implementation: All components should run on a local developer machine (no
cloud dependencies) and favor simplicity and a small footprint. The solution should use Python for
orchestration, and prioritize libraries that are easy to install and quick to initialize. We prefer local
models or open-source tools for NLP tasks. For example, use a local embedding model and an
embedded database instead of a heavy external service. The process should be as automated as
possible (script-driven) so a user can run it on a document file or folder and get the outputs without
manual intervention.
```
