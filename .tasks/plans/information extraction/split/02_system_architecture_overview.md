## System Architecture Overview

The system uses **Claude Code as the execution harness** with a **two-phase extraction pipeline** followed by validation:

| Role | Model | Function |
|------|-------|----------|
| Detail Extraction | Haiku 4.5 (sub-agent 1) | Scans source text for raw details |
| Fact Construction | Haiku 4.5 (sub-agent 2) | Constructs triplets, anchors details, reasons about structure |
| Orchestration & Reconstruction | Opus 4.5 | Orchestrates pipeline, runs reconstruction proofs, QA validation |

**Execution Model:**
- **Claude Code is the harness** - all agents are Claude Code sub-agents (no separate services or Python workflow orchestration needed)
- **Sub-agents communicate via file I/O** - to avoid filling orchestrator context, sub-agents write outputs to files and the orchestrator reads them
- **Python scripts are invoked as tools by agents** - helpers for deterministic operations (grammar checks, string diffs, etc.)
- **QA mode** - agents can QA themselves during validation runs

**Key Distinctions:**
- **Details** (Phase 1): Raw observations extracted from text - may be incomplete, unanchored, or not yet in triplet form
- **Facts** (Phase 2): Anchored, validated, triplet-structured atomic statements with source context
- **Anchoring** (Phase 2): The sub-agent connects raw details to source text and validates triplet structure
- **This is NOT an ensemble**: The pipeline is sequential, not parallel. Phase 2 depends on Phase 1 output.
