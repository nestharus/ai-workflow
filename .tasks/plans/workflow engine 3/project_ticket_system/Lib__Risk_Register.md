# Library: Risk Register (`risk`)

| Risk | Severity | Control(s) |
|---|---:|---|
| Multiple interactive sessions editing same ticket | Medium | `expected_rev` + ticket lock; loud mismatch failure |
| Decomposition “analysis paralysis” | Medium | progress signature + novelty + explicit give-up record |
| Toolchain drift between machines | Medium | env capture + tool fingerprints; workflow-defined commands |
| Users cannot debug runs | Low | ID-first CLI helpers: tail by run/step, show shard slices; scrubbed export bundles |
| Workflow customization breaks invariants | Medium | workflow schema validation + capability gating; dangerous actions require ack |
