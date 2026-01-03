### 1. Byte-exact Provenance and Reconstruction

- The "source text" is the **canonical input string produced by the ingestion step** (after any one-time format decoding, e.g., PDF to text).
- Every reference back to the source document is stored as **character offsets** into that canonical string (source context for provenance, not ownership claims).
- Reconstruction is an **explanation test**, not a coverage proof:
  - The system attempts to **re-explain the original text region** using its current internal understanding (anchors + facts + links).
  - Reconstruction succeeds only if the system can reproduce the **exact original substring** (byte-for-byte), without paraphrasing or inference.
  - Reconstruction never assigns text ownership to facts.
  - **Reconstruction success is a sufficiency test, not a completeness test**: Successful reconstruction proves the system has **enough facts to rebuild the original text**, NOT that it has extracted **every fact** the text expresses or implies. The reconstruction threshold is the minimum set of facts needed to reproduce the original text byte-for-byte.
- If reconstruction fails for a region, the system knows only one thing: **the current understanding is insufficient to explain the text.**
- If reconstruction remains impossible after bounded attempts, the system must emit a **Clarification Question** artifact (see Output and Storage section).
