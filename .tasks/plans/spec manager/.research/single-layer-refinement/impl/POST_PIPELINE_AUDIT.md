# Post-Pipeline Constraint Audit Plan

## When
After pipeline.sh completes all 31 files (3-33).

## What
The pipeline has no constraint/tradeoff alignment step. Violations are
expected in the raw implementation output. A separate audit pass fixes them.

## Steps

1. **Collect commits**: `git log fe6b8bb..HEAD --oneline` (fe6b8bb = file 1 commit)
2. **Collect changed files**: `git log fe6b8bb..HEAD --name-only --pretty=format:"" | sort -u`
3. **For each file**, write an audit prompt checking against:
   - `LONG_TERM_GOALS.md` design principles (especially "When introducing anything new")
   - `proposal.md` Section constraints (forward-only phases, no backtracking, etc.)
   - `core/language.py` — no hardcoded Python assumptions
   - No extraction (route instead), no language-specific parsing (LLM only)
   - Graph operations not code operations, dynamic structures not rigid types
4. **Run audits with codex-high2** (preserve codex-high quota for other work):
   ```bash
   uv run agents --model gpt-5.3-codex-high2 --file "<audit-prompt>"
   ```
5. **Fix violations** — edit files to compliance
6. **Re-audit** until clean pass
7. **Commit + push** fixes

## Audit Prompt Template
```markdown
# Constraint Audit: <file>

## Your Task
Audit this file for violations of the project's design principles.

## Files to Read
- Target: `<file-path>`
- Design principles: `.tasks/plans/spec manager/LONG_TERM_GOALS.md`
- Proposal: `.tasks/plans/spec manager/.research/single-layer-refinement/proposal.md`
- Language config: `scripts/spec_manager/spec_manager/core/language.py`

## Checklist
For EACH design principle, check if this file violates it.
Report: principle, violation (with line numbers), severity, fix suggestion.

## Key Violations to Watch For
- Hardcoded Python assumptions (should use core/language.py)
- Extraction where routing is required
- Language-specific parsing where LLM should be used
- Rigid types where dynamic structures are expected
- Direct editing where promotion is required
- Silent defaults where blocking on ambiguity is required
```
