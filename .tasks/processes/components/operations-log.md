# Operations Log

Component packages MAY include an operations log to track structural changes over time.
This provides an audit trail for decomposition and recomposition decisions.

## Template

Add this section to `architecture.md` to track component graph evolution:

```markdown
## Operations Log

| Timestamp | Operation | Affected Nodes | Trigger | Result |
|-----------|-----------|----------------|---------|--------|
| YYYY-MM-DD | SPLIT COM-XX | COM-XX → COM-XX-a, COM-XX-b | Divergence: CAP clusters | Success |
| YYYY-MM-DD | MERGE COM-XX, COM-YY | COM-XX, COM-YY → COM-ZZ | Overlap: CAP-XX | Success |
| YYYY-MM-DD | MOVE ALG-XX | ALG-XX: COM-AA → COM-BB | Recomposition | Success |
| YYYY-MM-DD | CREATE COM-XX | COM-XX, SUR-XX | New capability needed | Success |
| YYYY-MM-DD | REMOVE COM-XX | COM-XX | CAP redistributed | Success |
```

## Log Entry Fields

| Field | Description |
|-------|-------------|
| **Timestamp** | When the operation was executed |
| **Operation** | One of: CREATE, MODIFY, REMOVE, SPLIT, MERGE, MOVE (see feedback.md Part II) |
| **Affected Nodes** | Node IDs that were created, modified, or removed |
| **Trigger** | What analysis triggered this operation (overlap, divergence, pattern, etc.) |
| **Result** | Success, Failed (with reason), or Rolled Back |

## Cross-Reference

For full operation specifications with Mermaid flowcharts, see:
`.tasks/plans/algorithm decomposition/feedback.md` Part II: Operations Specification
