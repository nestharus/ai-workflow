flowchart TD

subgraph Init["Initialization"]
A[Start] --> B[Run initial lint (native scope per linter)]
B --> C{Success?}
C -->|Yes| Z[Exit: No errors]
C -->|No| D[Extract errors_by_linter (targets = file paths + <PROJECT> pseudo-target)]
D --> E[Initialize passed_linters = empty]
E --> F[Initialize investigation_futures = empty]
F --> F1[Initialize pending_investigation_targets = empty<br/>(target -> {error_snapshot, agent_output_snapshot})]
F1 --> F2[Initialize unlintable_targets = empty (target, reason)]
F2 --> F3[Initialize stale_linters = empty (linter -> STALE/SUSPENDED + blocked_by)]
F3 --> F4[Initialize seen_hashes = empty (target -> set of hashes/fingerprints in current processing window)]
end

subgraph MainLoop["Main Loop: while errors_by_linter OR investigation_futures"]
F4 --> G[Main loop tick]

subgraph InvCheck["Check Completed Investigations"]
G --> H{Any investigations<br/>completed?}
H -->|Yes| I[Get completed investigation result]
I --> I2[Remove current future from investigation_futures]
I2 --> I2A[Update stale_linters blocked_by (remove completed target)]
I2A --> I2B{Any stale linter<br/>unblocked? (blocked_by empty)}
I2B -->|Yes| I2C[Mark unblocked stale_linters as PENDING_REFRESH (blocked_by empty); keep excluded until refreshed]
I2C --> J
I2B -->|No| J{Investigator<br/>status?}

J -->|MODIFIED| J0{Still safe to apply?<br/>(current hash/fingerprint == investigation start)}
J0 -->|No| JDROP[Discard result as STALE (external change detected); set changed_files/project_changed from current state; clear candidate_stalled_*; unlintable_targets -= changed_files; pending_investigation_targets -= changed_files; seen_hashes -= changed_files]
JDROP --> AC
J0 -->|Yes| J1{Any actual diff?<br/>(new hash/fingerprint != investigation start)}
J1 -->|No| LIE1[Mark targets as UNLINTABLE (reason: Investigator MODIFIED but no diff)]
LIE1 --> LIEP{target ==<br/><PROJECT>?}
LIEP -->|Yes| ABORT[Abort: <PROJECT> unrecoverable (UNLINTABLE)]
LIEP -->|No| NOOP2
J1 -->|Yes| K[Record new hash/fingerprint in seen_hashes; clear state for modified targets (errors, passed)]
K --> K3[Set changed_files = truly modified file targets; set project_changed = true if <PROJECT> truly modified; clear candidate_stalled_*; pending_investigation_targets -= changed_files]
K3 --> AC

J -->|NO_OP| NOOP0{Still safe to trust?<br/>(current hash/fingerprint == investigation start)}
NOOP0 -->|No| JDROP
NOOP0 -->|Yes| NOOPP{target ==<br/><PROJECT>?}
NOOPP -->|Yes| NOOPPROJ[Mark <PROJECT> as UNLINTABLE (reason: Investigator NO_OP)]
NOOPPROJ --> ABORT
NOOPP -->|No| NOOP1[Mark target as UNLINTABLE (reason: Investigator NO_OP)]
NOOP1 --> NOOP2[Remove target diagnostics from errors_by_linter]
NOOP2 --> NOOP3[Clear passed_linters for target]
NOOP3 --> H

J -->|FAILURE| FAIL0{Still safe to trust?<br/>(current hash/fingerprint == investigation start)}
FAIL0 -->|No| JDROP
FAIL0 -->|Yes| FAILP{target ==<br/><PROJECT>?}
FAILP -->|Yes| FAILPROJ[Mark <PROJECT> as UNLINTABLE (reason: Investigator FAILURE)]
FAILPROJ --> ABORT
FAILP -->|No| FAIL1[Mark target as UNLINTABLE (reason: Investigator FAILURE)]
FAIL1 --> FAIL2[Remove target diagnostics from errors_by_linter]
FAIL2 --> FAIL3[Clear passed_linters for target]
FAIL3 --> H

H -->|No| N[Continue to main processing]
end

subgraph ErrorCheck["Check Error Files"]
N --> NREF{Any stale linter<br/>PENDING_REFRESH?<br/>(blocked_by empty)}
NREF -->|Yes| NREF0[Refresh-only tick:<br/>set changed_files = empty; project_changed = false;<br/>candidate_stalled_files = empty; candidate_stalled_targets = empty]
NREF0 --> AC
NREF -->|No| O2[inv_files = keys(investigation_futures)]
O2 --> O3[unlintable = keys(unlintable_targets)]
O3 --> O3A[pending = keys(pending_investigation_targets)]
O3A --> O3P{<PROJECT> in<br/>unlintable_targets?}
O3P -->|Yes| ABORT
O3P -->|No| O0[actionable_errors_by_linter = errors_by_linter excluding stale_linters AND unlintable (do not act on suspended/unlintable diagnostics)]
O0 --> O[Get all_error_targets from actionable_errors_by_linter (includes <PROJECT> if project-level errors present)]
O --> O4[actionable_targets = all_error_targets - inv_files - pending]
O4 --> O4A{pending non-empty AND<br/>stale_linters empty?}
O4A -->|Yes| O4B[Reserve pending in investigation_futures (snapshot start hashes/fingerprint NOW);<br/>dispatch async using stored {error_snapshot, agent_output_snapshot}; clear pending_investigation_targets]
O4B --> G
O4A -->|No| O5{inv_files<br/>empty?}
O5 -->|No| O6[actionable_targets = actionable_targets - {<PROJECT>} (project fixes blocked by locked files); log/status: Waiting for locks to clear before fixing Project]
O5 -->|Yes| O7[Proceed]
O6 --> O8[actionable_files = actionable_targets - {<PROJECT>}]
O7 --> O8
O8 --> P{actionable_targets<br/>empty?}
P -->|Yes| Q{Pending<br/>investigations?}
Q -->|Yes| WAIT2[Non-blocking wait/select (file watcher priority):<br/>re-check futures; if still waiting, yield/sleep and return to G]
WAIT2 -->|Future completed| G
WAIT2 -->|Still waiting| G
WAIT2 -->|External change| EXT[Refresh: detect externally modified files; set changed_files + project_changed; clear candidate_stalled_*; unlintable_targets -= changed_files; pending_investigation_targets -= changed_files; seen_hashes -= changed_files; go to AC]
EXT --> AC
Q -->|No| Q2{actionable_errors_by_linter empty AND<br/>stale_linters empty?}
Q2 -->|Yes| SUCCESS[Success: No actionable errors remain]
Q2 -->|No| Q3{stale_linters non-empty OR<br/>pending_investigation_targets non-empty?}
Q3 -->|Yes| G
Q3 -->|No| Q4[Invariant violation (should be unreachable): actionable errors exist but nothing actionable<br/>→ log state (likely path normalization / set logic bug) + abort]
Q4 --> FATAL[Abort: invariant violation]
end

subgraph AgentPhase["Agent Phase"]
P -->|No| R0[agent_input_files = actionable_files ∪ (project_context_files if <PROJECT> in actionable_targets)<br/>project_context_files = key build/lint configs (e.g., package.json, pom.xml, tox.ini, pyproject.toml)]
R0 --> R[Snapshot agent_input_files BEFORE agent (hash files) + project fingerprint (key configs); never hash <PROJECT>]
R --> R1[Update seen_hashes for agent_input_files hashes + project fingerprint]
R1 --> R2[Build agent input: agent_input_files contents + relevant errors + project errors (exclude stale_linters)]
R2 --> S[Invoke lint-fixer agent (CAS-protected writes: verify hashes/fingerprint from R immediately before write)]
S --> S0{Pre-write check passed?<br/>(hash/fingerprint unchanged since R)}
S0 -->|No| EXT
S0 -->|Yes| S2[Capture agent output (for investigator context)]
S2 --> T[Snapshot agent_input_files AFTER agent]
T --> U[Detect changes via diff: changed_files (agent_input_files hashes) + project_changed (project fingerprint); never hash <PROJECT>]
U --> U1[Update seen_hashes for changed_files hashes + project fingerprint (post-agent)]
U1 --> V[candidate_stalled_files = actionable_files - changed_files]
V --> V2[candidate_stalled_targets = candidate_stalled_files ∪ ({<PROJECT>} if <PROJECT> in actionable_targets AND project_changed = false)]
end

subgraph ProcessLinters["Process Each Linter's Errors"]
V2 --> AC[Clear passed_linters for changed_files; if project_changed then clear all passed_linters]
AC --> AD[new_errors = copy(errors_by_linter)]
AD --> AE[For each configured linter]
AE --> AF[Determine linter_scope = PROJECT if diagnostics depend on whole-project context, else FILES]
AF --> AG{linter_scope<br/>PROJECT?}

AG -->|Yes| AG0[blocking_files_for_linter = inv_files (or linter-specific subset)]
AG0 --> AG1{blocking_files_for_linter empty OR<br/>linter supports excluding blocking_files_for_linter?}
AG1 -->|Yes| AH[Run linter once on project (or with blocking_files_for_linter excluded)]
AH --> AI[Update this linter's diagnostics for non-locked targets (preserve inv_files + unlintable)]
AI --> AI0[Filter out diagnostics for inv_files + unlintable (do not overwrite their state)]
AI0 --> AI0A[Clear stale_linters entry for this linter (wake-up is post-refresh)]
AI0A --> AI2[files_with_errors = extract files from linter output]
AI2 --> AI3[files_that_passed = (changed_files ∪ candidate_stalled_files) - files_with_errors]
AI3 --> AI3A[files_that_passed = files_that_passed - {<PROJECT>}]
AI3A --> AJ[Record this linter in passed_linters for files_that_passed]
AJ --> AL[Next linter]
AG1 -->|No| AG2[Skip project run; mark this linter's diagnostics as STALE/SUSPENDED (blocked by blocking_files_for_linter)]
AG2 --> AG2A[Upsert stale_linters entry (blocked_by = blocking_files_for_linter)]
AG2A --> AL

AG -->|No| AM0{project_changed<br/>true?}
AM0 -->|Yes| AM1[files_to_check = ALL_TRACKED_FILES (refind from filesystem)<br/>- inv_files - unlintable - {<PROJECT>}]
AM0 -->|No| AM2[files_to_check = (changed_files ∪ candidate_stalled_files) - inv_files - unlintable - {<PROJECT>}]
AM1 --> AN
AM2 --> AN
AN[Run linter once on files_to_check]
AN --> AO[Ingest diagnostics for all files returned by linter output (not just files_to_check);<br/>clear diagnostics for files_to_check not in output; preserve inv_files + unlintable]
AO --> AO2[files_with_errors = extract files from linter output]
AO2 --> AO3[files_that_passed = files_to_check - files_with_errors]
AO3 --> AP[Record this linter in passed_linters for files_that_passed]
AP --> AL

AL --> AR{More linters?}
AR -->|Yes| AE
AR -->|No| AS[Done processing linter errors]
end

subgraph UpdateState["Update State"]
AS --> BG[errors_by_linter = new_errors]
BG --> BG0[verified_error_targets = extract targets from errors_by_linter excluding stale_linters (includes <PROJECT>)]
BG0 --> BG0A[pending_investigation_targets = filter keys to verified_error_targets (drop resolved)]
BG0A --> BG1[confirmed_stalled_targets = candidate_stalled_targets ∩ verified_error_targets (errors persist)]
BG1 --> BG1A[stalled_targets_ready = confirmed_stalled_targets ∪ keys(pending_investigation_targets)]
BG1A --> BG2{stalled_targets_ready<br/>empty?}
BG2 -->|No| BG2A[Granular gating: partition stalled_targets_ready into targets_to_defer and targets_to_submit<br/>(target required_linter in stale_linters)]
BG2A --> BG2B[Upsert pending_investigation_targets for targets_to_defer (store {error_snapshot, agent_output_snapshot});<br/>clear candidate_stalled_targets for targets_to_defer]
BG2B --> BG2C{targets_to_submit<br/>empty?}
BG2C -->|Yes| G
BG2C -->|No| BG3[Build per-target investigation context for targets_to_submit:<br/>use pending snapshot if present; else {error_snapshot, agent_output_snapshot} from this tick]
BG3 --> BG3A[Snapshot investigation start hashes/fingerprint NOW (exact version sent)]
BG3A --> BG4[Add to investigation_futures (track start hashes/fingerprint per target)]
BG4 --> BG4A[Dispatch targets_to_submit async (payload includes per-target {error_snapshot, agent_output_snapshot})]
BG4A --> BG5[Remove targets_to_submit from pending_investigation_targets; clear candidate_stalled_targets for targets_to_submit;<br/>clear passed_linters for targets_to_submit; if <PROJECT> in targets_to_submit then clear all passed_linters]
BG2 -->|Yes| BH
BG5 --> BH
BH{errors_by_linter empty AND stale_linters empty AND<br/>investigation_futures empty?}
BH -->|Yes| SUCCESS
BH -->|No| G
end
end

subgraph Cleanup["Cleanup"]
SUCCESS --> BI[Collect investigation reports]
ABORT --> BI
FATAL --> BI
BI --> BK[Print final report (include unlintable_targets + reasons)]
BK --> END[Exit]
end

style Init fill:#e1f5fe
style MainLoop fill:#fff3e0
style InvCheck fill:#f3e5f5
style ErrorCheck fill:#e8f5e9
style AgentPhase fill:#fff8e1
style ProcessLinters fill:#e3f2fd
style UpdateState fill:#e0f2f1
style Cleanup fill:#fafafa

Key concepts:

1. Errors can be cross-file - Linter output is authoritative within its native scope (PROJECT vs FILES)
2. passed_linters tracking - Records which linters each file has passed (cleared when file changes; clear all when project config changes)
3. Project-level errors are modeled as <PROJECT> - Treat fatal/crash/"unknown" linter failures as a pseudo-target (never hash it as a file)
4. Agent input includes project context - Agent receives actionable file content + project_context_files (e.g., package.json, pom.xml, tox.ini, pyproject.toml) when <PROJECT> errors are actionable + relevant errors (exclude stale_linters) and any non-stale project-level errors
5. Agent overwrite protection - Agent writes are CAS-protected; if hash/fingerprint changed since R, discard the agent write as STALE and refresh like EXT
6. Investigator trigger is state-based - Agent ran, target was in actionable_targets (sent to agent), target did not change (file hash or project fingerprint), AND a post-agent lint confirms errors still persist
7. Investigation payload includes context - Provide per-target error_snapshot (errors_by_linter excluding stale_linters) + agent_output_snapshot from the agent tick that produced the stall (store snapshots in pending_investigation_targets when deferring)
8. UNLINTABLE targets are first-class - Investigator NO_OP/FAILURE removes a target from the workflow with a recorded reason (unless stale per #15)
9. Investigation lockout - actionable_targets excludes targets reserved in investigation_futures to prevent concurrent edits (reserve synchronously before dispatch)
10. Locked-target state preservation - Never wipe diagnostics for targets in investigation_futures when building the next errors_by_linter
11. Project-scoped lint safety - If a PROJECT linter must be skipped due to locks, mark its diagnostics as STALE/SUSPENDED and record blocked_by; do not act on them until refreshed
12. Stale linter refresh gating - On investigation completion, update blocked_by; if blocked_by becomes empty, keep the linter in stale_linters as PENDING_REFRESH and force a refresh-only lint tick before its diagnostics become actionable
13. Granular stale-linter gating - Only defer stalled targets whose required_linter is STALE/SUSPENDED/PENDING_REFRESH (required_linter = the linter producing the remaining actionable errors for the target); submit unrelated stalled targets immediately and keep deferrals in pending_investigation_targets with context
14. External change refresh - Clear candidate_stalled_*; unlintable_targets -= changed_files; pending_investigation_targets -= changed_files; seen_hashes -= changed_files; then re-enter ProcessLinters
15. Investigator staleness protection - Drop investigator results (MODIFIED/NO_OP/FAILURE) if hashes/fingerprint changed since investigation start; treat as external change and re-lint
16. Investigator cycle protections - If Investigator returns MODIFIED but no diff, treat as UNLINTABLE; otherwise accept modifications (no max retries / ping-pong allowed)
17. No hot loop - WAIT2 is a non-blocking selector; check futures immediately, then yield/sleep and return to G; external changes trigger refresh immediately (mark changed_files/project_changed, then re-enter ProcessLinters)
18. Termination uses actionable errors - When nothing is actionable and no investigations are pending, exit when actionable_errors_by_linter is empty AND stale_linters empty
19. Post-lint escalation - Only submit stalled_targets_ready (including <PROJECT>) after a post-agent lint verifies errors still persist (exclude stale_linters)
20. <PROJECT> UNLINTABLE implication - Abort the workflow (global failure) to avoid "slow death" file-by-file ejections when project config is broken
21. Investigator truthfulness - Investigator should return NO_OP if it cannot produce a real diff (do not claim MODIFIED without changes)
22. Candidate stall debouncing - When stalled targets are deferred or submitted, remove them from candidate_stalled_targets to prevent re-submission spam when AgentPhase is skipped by locks
23. Dynamic file tracking - When project_changed is true, refind ALL_TRACKED_FILES from the filesystem before building files_to_check (captures agent-created files)
24. Target normalization - Normalize file paths/target identifiers before all set operations (case, separators, relative vs absolute) to preserve invariants and avoid Q4
25. Optional optimization - Cache per-linter blocking file rules in Init to avoid recomputing blocking_files_for_linter mapping each tick
