# Library: Risk Register (`risk`)

| Risk | Severity | Control(s) |
|---|---:|---|
| Multiple interactive sessions editing same ticket | Medium | `expected_rev` + ticket lock; loud mismatch failure |
| Decomposition “analysis paralysis” | Medium | progress signature + novelty + explicit give-up record |
| Toolchain drift between machines | Medium | env capture + tool fingerprints; workflow-defined commands |
| Users cannot debug runs | Low | ID-first CLI helpers: tail by run/step, show shard slices; scrubbed export bundles |
| Workflow customization breaks invariants | Medium | workflow schema validation + capability gating; dangerous actions require ack |
| User accidentally resets to wrong revision | Medium | explicit confirmation + safety bookmark |
| Concurrent rollback operations cause conflicts | Medium | ticket lock + optimistic concurrency (`expected_rev`) |
| Evidence loss during rollback | Low | append-only `ticket.json.history[]`; never delete artifacts |
| jj rollback operation fails mid-rollback | Medium | safety bookmarks + loud failure with evidence |

### R-TM-04: Concurrent ticket file conflicts

**Risk**: Multiple tickets modifying the same files may produce merge conflicts at export time

**Likelihood**: Medium (common in active development)

**Impact**: Medium (blocks export; requires manual resolution)

**Mitigation**:
- Early-warning detection via `workflowctl tickets detect-overlap --active`
- Encourage users to declare dependencies when tickets are related
- Document conflict resolution workflow in user guide

**Residual risk**: Acceptable (conflicts are inherent to concurrent work; tooling provides visibility)

### R-TM-05: Accidental reset to wrong revision

**Risk**: User accidentally resets a ticket stack to the wrong revision

**Likelihood**: Medium

**Impact**: High (lost working position; confusion; potential rework)

**Mitigation**:
- Require explicit confirmation for resets (flag or interactive prompt)
- Create a safety bookmark before moving the ticket stack pointer
- Display current tip + target + unreachable patch count before confirming

**Residual risk**: Acceptable (recovery via safety bookmark is deterministic)

### R-TM-06: Concurrent rollback conflicts

**Risk**: Concurrent rollback operations on the same ticket cause state conflicts

**Likelihood**: Low

**Impact**: Medium (failed operations; user confusion)

**Mitigation**:
- Ticket-level locking (`locks/ticket.<ticket_id>.lock`)
- Optimistic concurrency control via `expected_rev` + loud mismatch failure

**Residual risk**: Acceptable (conflicts fail loudly and preserve evidence)

### R-TM-07: Evidence loss during rollback

**Risk**: Rollback operations overwrite or delete prior evidence artifacts

**Likelihood**: Low

**Impact**: High (breaks auditability and recovery)

**Mitigation**:
- Append-only `ticket.json.history[]` with evidence refs
- Never delete or overwrite prior run/step artifacts
- Always write new rollback evidence under a new `run_id` + `history_id`

**Residual risk**: Low (mechanical policy, easy to audit)

### R-TM-08: jj operations fail mid-rollback

**Risk**: Underlying jj operations fail (tool missing, revset errors, repository corruption)

**Likelihood**: Medium

**Impact**: Medium (rollback cannot complete; ticket remains inconsistent until manual action)

**Mitigation**:
- Capture raw jj output as evidence on every attempt
- Create safety bookmarks before destructive pointer moves
- Fail loudly with actionable error + recovery instructions

**Residual risk**: Acceptable (recovery is evidence-driven; failures are detectable)
