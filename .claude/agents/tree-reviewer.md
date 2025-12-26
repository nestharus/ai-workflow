---
name: tree-reviewer
description: UNUSED - Branch-level tree review disabled in favor of per-unit multi-path
model: opus
tools: Read, Write, Grep, Glob, mcp__firecrawl__firecrawl_search, mcp__firecrawl__firecrawl_scrape
---

# Tree Reviewer (UNUSED)

This agent is not invoked by the planner state machine. Branch-level tree review
has been disabled in favor of per-unit multi-path decomposition (explored_paths).

The full agent specification exists in `agents/tree-reviewer.agent.md` but is not
currently used by any workflow.

**Per-unit multi-path** (still active):
- Units can have multiple decomposition paths in `explored_paths`
- Layer reviewer can select between paths via `selected_path` output
- Handled by `commit_to_path()` in state.py

**Branch-level tree review** (disabled):
- Comparing entire branch hierarchies
- Tree reviewer agent comparing branch reports
- Removed from create-plan workflow
