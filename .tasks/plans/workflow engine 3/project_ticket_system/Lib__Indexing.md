# Library: Search/Indexing (`indexer`)

- **Primary responsibility**: Provide “snappy CLI listing” via a derived index that is safe to rebuild locally.
- **Depends on**: `wss_surfaces`
- **Used by**: `pm`, `cli`

## 1) Derived index file

- Path: `workspace/index.json`
- Ownership: root-owned derived artifact (safe to delete + rebuild)

Minimal schema:

```json
{
  "schema_version": 1,
  "built_at": "<rfc3339>",
  "projects": [
    { "project_id": "...", "title": "...", "status": "...", "updated_at": "..." }
  ],
  "tickets": [
    { "ticket_id": "...", "project_id": "...", "title": "...", "status": "...", "updated_at": "..." }
  ]
}
```

## 2) Dirty marker & rebuild trigger (normative)

Index rebuild is driven by an explicit dirty marker:
- Marker path: `workspace/index.dirty`

When any writer modifies:
- `workspace/projects/**/project.json`, or
- `workspace/tickets/**/ticket.json`

it MUST also (atomically) write/update `workspace/index.dirty` with:

```json
{ "schema_version": 1, "dirty_at": "<rfc3339>", "reason": "project_or_ticket_change" }
```

Rebuild rule (normative):
- On any CLI command that needs listings/search:
  - if `workspace/index.json` is missing OR `workspace/index.dirty` exists:
    - rebuild index
    - on success: delete `workspace/index.dirty`

## 3) Failure behavior (normative)

If the index is missing or stale and rebuild fails:
- CLI MUST fall back to scanning `workspace/projects/` and `workspace/tickets/`
- CLI MUST emit a `warn` notification with the rebuild error and evidence refs

Index rebuild failure MUST NOT block ticket execution.

## 4) Manual rebuild

Provide:
- `workflowctl index rebuild`

This command:
- rebuilds `workspace/index.json`
- clears `workspace/index.dirty` on success
- prints a summary of indexed counts
