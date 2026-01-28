# Tech Plan: Integration — Patch-Stream Integration

* **Doc**: Tech_Plan__Integration/06_Patch_Stream_Integration.md
* **Updated**: 2026-01-26
* **Shard**: Integration §6
* **Libraries / packages**:
  * `scripts/core/vcs/jj_adapter.py` (ticket stack operations)
  * Patch-Stream (jj-backed ticket stacks)
  * `scripts/core/protocol/merge_patch.py` + hunk-lint helpers (apply semantics + safety)
* **Depends on**:
  * `Tech_Plan__Core_Infrastructure.md` (evidence + durable state)

## 6) Patch-Stream integration (Mode A vs Mode B)

### Mode A — "blind patch editor" (preferred default)

1. Hydrate required files (virtual hydration; no checkout).
2. Produce patch (unified diff).
3. Run hunk-lint (format + dry-run apply).
4. Apply to ticket stack (jj change).
5. Persist evidence (patch id + refs) into WSS/logs.

### Mode B — "sandbox editor" (fallback)

1. Create ephemeral sandbox (jj workspace) hydrated from ticket stack tip.
2. Run tools normally (formatters/tests/search).
3. Capture diff vs baseline.
4. Run hunk-lint and apply patch to ticket stack.
5. Persist tool outputs as artifacts (durable), not as "truth".

Selection policy:

* Prefer Mode A unless repo-wide tooling is required, hydration is too large/slow, or repeated hunk-lint failures occur.
