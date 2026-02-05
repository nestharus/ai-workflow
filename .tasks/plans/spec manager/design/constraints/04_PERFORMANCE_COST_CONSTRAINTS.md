# Performance / Cost Constraints

- CON-PERF-0001  Default processing is linear in number of atoms per file revision (O(n))
- CON-PERF-0002  Files fit in context windows; no chunking required; one LLM call per file
- CON-PERF-0003  Expensive auditors are escalation-only (risk-triggered)
- CON-PERF-0004  All intermediate artifacts persisted to disk to avoid rework
- CON-PERF-0005  Parallelism is permitted where it does not violate determinism of ID allocation
- CON-PERF-0006  Deterministic re-runs: identical inputs + config → identical manifests and IDs
