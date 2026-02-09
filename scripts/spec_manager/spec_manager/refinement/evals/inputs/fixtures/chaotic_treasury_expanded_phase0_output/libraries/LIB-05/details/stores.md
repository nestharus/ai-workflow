# Event Infrastructure: DETAIL — STORE


([=STO-LIB-05-001])
<!-- source: event_pipeline.md:5-5 -->
The topic configuration is:


([=STO-LIB-05-002])
<!-- source: event_pipeline.md:7-27 -->
```yaml
topics:
  - name: settlement.confirmed
    partitions: 8
    retention_days: 30
  - name: settlement.rejected
    partitions: 4
    retention_days: 7
  - name: risk.breach
    partitions: 2
    retention_days: 90
  - name: reconciliation.break
    partitions: 4
    retention_days: 90
  - name: audit.snapshot
    partitions: 1
    retention_days: 365
  - name: validation.duplicate
    partitions: 2
    retention_days: 7
```
