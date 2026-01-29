# Library: Risk Register (`risk`)

| Risk | Severity | Control(s) |
|---|---:|---|
| Multiple interactive sessions editing same ticket | Medium | `expected_rev` + ticket lock; loud mismatch failure |
| Decomposition “analysis paralysis” | Medium | progress signature + novelty + explicit give-up record |
| Toolchain drift between machines | Medium | env capture + tool fingerprints; workflow-defined commands |
| Users cannot debug runs | Low | ID-first CLI helpers: tail by run/step, show shard slices; scrubbed export bundles |
| Workflow customization breaks invariants | Medium | workflow schema validation + capability gating; dangerous actions require ack |

### R-TM-04: Concurrent ticket file conflicts

**Risk**: Multiple tickets modifying the same files may produce merge conflicts at export time

**Likelihood**: Medium (common in active development)

**Impact**: Medium (blocks export; requires manual resolution)

**Mitigation**:
- Early-warning detection via `workflowctl tickets detect-overlap --active`
- Encourage users to declare dependencies when tickets are related
- Document conflict resolution workflow in user guide

**Residual risk**: Acceptable (conflicts are inherent to concurrent work; tooling provides visibility)
