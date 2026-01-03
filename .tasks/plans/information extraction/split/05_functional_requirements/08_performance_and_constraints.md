### Performance and Constraints

```
Local Execution: The entire pipeline (extraction, embedding, storage, querying) must run locally on
a developer's machine. It should not require any cloud services. The system uses Claude Code as the
execution harness with Claude sub-agents for fact extraction:
- **Haiku 4.5 (sub-agent 1)** performs detail extraction, scanning source text for raw observations, statements, and claims
- **Haiku 4.5 (sub-agent 2)** performs fact construction, transforming details into anchored atomic facts with triplet structure
- **Opus 4.5** orchestrates the pipeline, runs reconstruction proofs, and performs QA validation
- Sub-agents communicate via file I/O to avoid filling orchestrator context
- Python scripts are invoked as tools by agents for deterministic operations
- If local models + deterministic rules suffice, the reasoning model is not invoked.
Startup Time: Tools and models chosen should favor fast initialization. For example, SQLite starts
near-instantly. The Qwen-3 0.6B embedding model, while not tiny, is reasonably sized and can load
on CPU or GPU without excessive delay (compared to very large models). We avoid heavy
frameworks that require lengthy setup. The embedding and database libraries will be added to the
project's Python environment (e.g., listed in pyproject.toml) so they can be installed easily. This
includes transformers (for the Qwen model), torch, sqlite-vss (for vector search), and
nltk (for grammar validation). NLTK model loading is fast and the averaged perceptron tagger
can be cached between validation runs. For higher accuracy, NLTK can integrate with Stanford
CoreNLP or use the more sophisticated parsing models available in the library.
Memory/Storage Footprint: All data (embeddings, facts, indices) will be stored either in memory or
lightweight files. The SQLite DB ensures the entire vector index can reside in a single file (which
could be a few MBs to hundreds of MBs depending on number of facts and vector size). The fact list
CSV/JSON will be as large as the information content of the source document, which is unavoidable, but
eliminating duplicates means it could be smaller than the original document if there were many
repetitions.
Accuracy Priority: The system favors accuracy over speed. It is acceptable if the extraction and
consolidation take multiple passes or LLM calls, as long as the final result meets the reconstruction
threshold. For instance, multiple iterations of LLM extraction (per span) will be used to ensure
**sufficient facts for reconstruction are extracted**. We acknowledge this may be time-consuming on a
very large document, but reaching the sufficiency threshold is critical.
The process can be semi-automated such that an orchestrating script or agent handles the multi-
step pipeline without user intervention (the user only waits for the final outputs).
No UI (Script-Driven): There will be no graphical user interface. The system will be operated via
scripts/command-line or through an AI agent interface (for example, an LLM with tool use abilities
could trigger the scripts). This means all interactions are via files and console logs. For example, a
developer or an agent provides the input file path to a script, the script runs extraction and outputs
the files, and then perhaps the agent or developer reviews the results. The lack of UI is acceptable
because the primary consumer of this output might be another LLM or a developer doing analysis.
```
