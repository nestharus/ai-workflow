# Change Management Constraints

- CON-CHG-0001  New evidence arrives as patches (new file revisions); old revisions retained
- CON-CHG-0002  Derived layer updates are replayable from operation logs + manifests
- CON-CHG-0003  Merges are non-destructive: superseded content is retained as remainder with lineage
- CON-CHG-0004  Strategy changes require:
  - version bump
  - fixture set
  - coverage + audit pass on fixtures
