### Update and Maintenance Requirements

```
Adding New Documents: The system should allow new documents or updated documents to be
processed and merged into the existing fact base. This means the extraction pipeline can be re-run
on new input, yielding new facts which are then compared (via embeddings) against the existing
facts to integrate without duplication. The output should remain a single consolidated fact list.
(Internally, we might either re-run the entire extraction on the combined old+new corpus or do an
incremental extraction on just the new text and then deduplicate against the stored facts.)
Removing/Modifying Facts: If a fact is identified as outdated or incorrect, one should be able to
remove or edit that fact in the fact list. Because the facts are atomic and referenced, removal/edit is
straightforward: e.g., delete or change the entry in the CSV/JSON, and then update the vector store
accordingly (remove or recompute that vector). The documentation will include instructions for this.
There should be scripts or functions to facilitate these updates (for instance, a script to regenerate
the SQLite index from the CSV after manual edits).
No Duplication on Re-run: If the extraction is re-run on the same document (or overlapping
documents), the system should not create duplicate fact entries. This implies either the
deduplication step must recognize and merge them, or the extraction process itself can be made
aware of an existing facts database to avoid extracting something already known. A simpler
implementation is to always run extraction fresh and then rely on the dedup step to merge
duplicates, ensuring idempotency over multiple runs.
Conflict Detection (Future): While not in the initial scope, the groundwork laid by this system will
make it easier to detect contradictory facts in the future. Once all facts are unique and atomic, one
can programmatically or via LLM check for logical conflicts (e.g., Fact A says the limit is 5, Fact B says
the limit is 10). The system’s design should not preclude adding such a feature later. (At present,
contradiction resolution is not handled – similar academic efforts note that conflict resolution may
require additional logic .)
```
