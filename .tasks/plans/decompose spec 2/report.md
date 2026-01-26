Got it – I’ve updated the instructions accordingly.


You’re right to be blunt here. The fix is not “keep a broken/unreliable thing around and hope nobody uses it.” That **creates confusion and failure modes**.

### ✅ What I found (concrete, repo‑level reality)

1. **`alias-detector` wasn’t something I invented — it already existed in the baseline repo.**
   The baseline decomposition command (`.claude/commands/decompose-spec.md`) explicitly includes a **Phase 8: Alias Detection** and the repo contains `.agents/agents/alias-detector.md`. That directly conflicts with your updated guidance: alias detection is vague/unreliable and should be handled during implementation.

2. **Keeping it is confusing (your point), and it also misleads users because the command file suggests it’s part of the “official” workflow.**
   So yes: **it should be removed**, not left around as an “optional” step.

---

## ✅ What I’ve already done (in the working patch)

### 1) Removed the alias-detector agent file

I have **deleted**:

* `.agents/agents/alias-detector.md`

### 2) Removed alias-detector from the official workflow

I have edited:

* `.claude/commands/decompose-spec.md`

Changes made:

* **Removed Phase 8 “Alias Detection”**
* Added a clear note that:

  * alias resolution is deferred to implementation time
  * dependency resolution is also deferred/iterative as you described
* Added phases for:

  * tagging facts (`tag-facts`)
  * recomposing specs (`recompose`)
  * and pointing at `execute-spec` as the next step

### 3) Added a new command doc describing execution workflow

I added:

* `.claude/commands/execute-spec.md`

This document reflects your “continuous execution + gaps + hashes + partial/done IDs” model, and references agent execution style (see below).

---

## ✅ You also gave me agent-writing/execution rules — I’m aligning to those now

You provided two key docs:

* Agent format and routing system rules (frontmatter, routing logic, single router, etc.) fileciteturn0file0
* The correct way to run agents via `uv run python -m scripts.agents ...` fileciteturn0file1

I’m now treating those as **hard constraints** on how any agent additions or orchestration should be done.

---

# ⚠️ What is still incomplete (and why)

You asked for **broad changes**, and I started implementing them, but I have **not finished the full workflow refactor yet**. Specifically:

### Still in progress:

* Reworking remaining CLI commands so they fully match the workflow described in the prompt
* Implementing the **tagger** and **recomposer** commands in a *mechanical / no-rewrite* way
* Implementing **execute-spec scaffolding** (ledger, hashes, statuses, gaps, evidence mapping JSON, etc.)
* Updating `cmd_process_context` / relation handling to match the new “needle” style relation decomposition rules

### Why unfinished:

Because once I began fixing one failure, I discovered **multiple real workflow-breaking bugs already present in the baseline** (not theoretical). Example failures I confirmed while inspecting code:

* Several CLI commands look for staged files in the wrong directory (using `workspace/staging` instead of `workspace/staging/discovery`)
* Investigation staging returns only the “first file” even though it creates multiple files (so the investigation step silently ignores most inputs)
* Some commands embed IDs but don’t actually redact lines, causing extracted lines to reappear as “remaining” later
* Entity investigation processing was creating brand new entity IDs rather than appending to the existing entity, which is fundamentally wrong for your loop model

These are not “preferences.” They are **hard failures**.

---

# Immediate answer to your request

✅ **Yes** — keeping unreliable processes is confusing.
✅ **Yes** — alias-detector should be removed.
✅ **I removed it and removed it from the official command workflow**.

---

# Next steps (what I will deliver next)

You want broad changes, so the next patch I produce will include:

1. **Finish** the CLI pipeline fixes so decomposition actually runs end-to-end without structural failures
2. Add **tag-facts** and **recompose** commands that are mechanical, safe (no rewriting), and preserve all facts
3. Add **execute-spec** scaffolding:

   * ledger JSON
   * ID hashes
   * done/partial tracking
   * gap surfacing
   * implementor writes `.tmp/.../id_changes.json` mapping files → IDs
4. Remove/disable any other “confusing” workflow steps that don’t match your algorithm

---

If you want, I can also **compile a short “Removed/Deprecated” list** so nothing unreliable remains in the repo (not just alias-detector). But alias-detector removal is already done.

Just confirm one thing so I don’t guess:

### Do you want me to hard-delete *all* unused agents, or only those explicitly deemed unreliable (like alias-detector)?

Because “unused” and “unreliable” aren’t the same category, and broad cleanup can accidentally remove things you still want available later.
