# Tech Plan: Integration — Repo Code Layout (Target)

- **Doc**: Tech_Plan__Integration/10_Repo_Code_Layout_Target.md
- **Updated**: 2026-01-26
- **Shard**: Integration §10
- **Libraries / packages**: all (this is the target module boundary map)

## 10) Repo code layout (target)

```text
scripts/
  core/
    protocol/
      schema_v1.py
      merge_patch.py
      atomic_write.py
      journals.py                 # write-ahead journal helpers
      pause.py
      redaction.py                # secret scanning + redaction
      config.py                   # config loading + schema validation
      locks.py                    # lock helpers
    storage/
      wss.py
      logs.py
      queues.py
    secrets/
      keyring_store.py            # secrets get/set/delete
      fallback_store.py
    vcs/
      jj_adapter.py
    sandbox/
      workspace_runner.py         # jj workspace-based sandboxes
    workflows/
      registry.py                 # load/merge workflows from precedence
      runner.py                   # execute workflow steps (DAG)
      schema.py                   # workflow YAML schema
    conclusions/
      store.py
    investigation/
      bundle.py
      contract.py
    runtime/
      root.py
      step.py
      ids.py
      doctor.py
      fsck.py
      recover.py
  project_manager/
    cli.py
    project_index.py
  ticket_manager/
    cli.py
    task_decomposition/
      orchestrator.py
      agents/
        pattern_discovery.md
        approval.md
        verification.md
      candidate_surfacing.py
    task_executor.py
  pr/
    review_implementation.py
    update_pr.py
    rebase_enhanced.py
    merge.py
  monitoring/
    monitor_thread.py
    anomaly_detector.py
    workflow_repair.md

workflowctl/
  main.py
```
