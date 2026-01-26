# Tech Plan: Integration — `workflow_engine` Gateway

- **Doc**: Tech_Plan__Integration/08_Workflow_Engine_Gateway.md
- **Updated**: 2026-01-26
- **Shard**: Integration §8
- **Libraries / packages**:
  - `workflow_engine` (single auditable tool gateway)
  - `scripts/core/protocol/schema_v1.py` (request/response schemas)
  - `scripts/core/protocol/redaction.py` (secret scanning + redaction)
- **Depends on**:
  - `Tech_Plan__Core_Infrastructure.md` (capability model + durability)
  - Integration §9 (`09_Sandboxes__JJ_Workspaces.md`) for sandbox lifecycle semantics

## 8) `workflow_engine` gateway (single tool constraint)

### Purpose
All agent execution goes through one constrained, auditable gateway. Agents do not run arbitrary commands directly.

### Interface
Tool: `workflow_engine.invoke(payload: JSON) -> JSON`

### Allowlisted subcommands (v1)

| Subcommand | Purpose | Capability |
|---|---|---|
| `help` | schemas + examples | none |
| `hydrate` | virtual hydration (Mode A) | `read_stack` |
| `apply_patch` | apply patch to ticket stack | `apply_patch` |
| `sandbox_create` | create sandbox (jj workspace) | `sandbox_exec` |
| `sandbox_run` | run tool in sandbox/workspace | `sandbox_exec` |
| `sandbox_destroy` | cleanup sandbox (jj workspace) | `sandbox_exec` |
| `llm_call` | cancellable LLM call wrapper | `net_llm` |
| `spawn_step` | request child step | `spawn_child` |
| `wait_step` | wait for step completion | none |
| `control_write` | write control actions | `control_send` |
| `export_scrub` | build scrubbed bundle | `export_scrub` |
| `graph_static` | generate static graph | none |
| `graph_run` | generate dynamic graph | none |
| `run_python_script` | run registered script artifact | `script_exec` |

### Subcommand `hydrate` (Mode A)

`hydrate` reconstructs file content at a given revision **without** creating a working copy.

It is used to support Mode A step execution (Core Flows Flow 8).

#### Request

```json
{
  "subcommand": "hydrate",
  "repo_uid": "<repo_uid>",
  "run_id": "<run_id>",
  "rev": "<revset or commit id>",
  "paths": ["path/to/file.ext", "dir/"],
  "mode": "file|tree",
  "max_inline_bytes": 65536,
  "text_encoding": "utf-8",
  "slices": [
    { "path": "path/to/file.ext", "start_line": 1, "end_line": 200 }
  ]
}
```

Rules:

- `paths` are repo-relative (validated; no absolute paths, no `..`).
- `mode=file` treats each entry in `paths` as a file path.
- `mode=tree` treats each entry as a directory prefix and hydrates all files under it (subject to size limits).
- `slices` are optional; if present, the gateway returns only the requested line ranges for those paths.

#### Response

```json
{
  "ok": true,
  "resolved_rev": "<commit id>",
  "items": [
    {
      "path": "path/to/file.ext",
      "status": "ok|not_found|binary|too_large|error",
      "size_bytes": 1234,
      "sha256": "sha256:<hex>",
      "is_binary": false,
      "content": "…optional inline text…",
      "slice": { "start_line": 1, "end_line": 200 }
    }
  ],
  "errors": []
}
```

Response rules:

- If `size_bytes <= max_inline_bytes` and the file is text, `content` SHOULD be included.
- If `size_bytes > max_inline_bytes`, the gateway MUST:
  - set `status: "too_large"`
  - include `sha256` and `size_bytes`
  - omit `content` unless the caller requested `slices`
- If a file is binary, the gateway MUST:
  - set `status: "binary"`
  - omit `content` (unless a future binary-slice mode is added)
- The gateway MUST be deterministic: identical `(rev, path, slice)` requests yield identical `sha256`.

#### Implementation (jj backend; normative baseline)

This section defines a baseline implementation for a `jj`-backed repo. Implementations MAY optimize, but MUST preserve semantics.

- Resolve `rev` to a single commit id using `jj` (error if ambiguous).
- For `mode=file`:
  - For each `path`, obtain content via `jj file show --revision <rev> --template '' -- <path>`
- For `mode=tree`:
  1. List files under the directory prefix via:
     - `jj file list --revision <rev> --template '{path}\n' -- <dir>`
  2. For each returned file path, call `jj file show` as above.

Binary detection:

- Treat a file as binary if:
  - it contains NUL bytes, OR
  - it fails UTF‑8 decoding after applying `text_encoding`

Large file handling:

- The gateway MUST stream `jj` output and compute `sha256` as bytes are read.
- Inline content is capped by `max_inline_bytes` (default 64 KiB). Callers that need more must request `slices` or use a sandbox.

Caching:

- The gateway MAY cache hydrated results for the duration of a run keyed by `(resolved_rev, path, slice)`.



### Validation (mandatory)
For every invocation:
- validate against JSON schema
- reject unknown fields
- enforce repo-relative paths (deny absolute and `..`)
- enforce max sizes (patch, hydration, stdout chunk)
- enforce privacy policy:
  - for `llm_call`, secret scan + network_mode checks
  - for `export_scrub`, secret scan + scrub policy

### Python execution rule (registered artifacts only)
- Agent-authored scripts are stored as run artifacts: `workspace/runs/<run_id>/artifacts/scripts/<script_id>.py`.
- A script is “registered” by:
  - writing it as an artifact
  - recording `sha256` in a sidecar manifest
- Execution references script path + expected hash; gateway logs both `tool_start` and `tool_stop` including hashes.
