# AI Agent Instructions

This file provides conventions and operational rules for AI agents running orchestrations in VS Code GitHub Copilot.

## SIEVE Pipeline Overview

All orchestrations follow the SIEVE pipeline:

```
Intake → Research → Plan → Implement → Review → Verify
```

Each layer has:
- Entry gate (Pipeline Oversight validation)
- Agent execution
- Exit gate (Pipeline Oversight validation)
- Loop-back on failure

### Pipeline Rules (Non-Negotiable)

1. **Orchestrator routes only**: Never implements or reviews, only delegates
2. **CODE FIRST, TESTS AFTER**: Implement code, complete code reviews, then tests
3. **Loop until clean**: Any failing review re-enters loop until PASS
4. **Every agent writes receipt**: Deviations/assumptions must be explicit
5. **Pipeline Oversight enforces**: Only enforcer can clear justified deviations

## Agent File Structure

- **Agent Definitions**: `.agent.md` files in `.github/agents/`
- **Orchestrations**: Multi-step workflows in `.github/orchestrations/`
- **User Prompts**: Invokable commands in `.github/prompts/`

### Agent File Format

```markdown
---
name: agent-name
description: Brief description of agent's role
tools: ["read", "search", "edit", "shell"]
target: vscode
model: Claude Opus 4.5 (Preview)
---

# Agent Instructions

[Detailed instructions for the agent...]
```

### Model Assignments

| Model | Role | Agents |
|-------|------|--------|
| **Claude Haiku 4.5** | Crawling, Simple runners | web-crawler, repo-crawler, domain-structure-crawler, repo-integration-crawler, dependency-doc-crawler, verification-runner |
| **GPT-5.1 (Preview)** | Reviews, Synthesis, Decomposition | All `*-review` agents, pipeline-oversight-enforcer, research-synthesizer, research-deduplicator, structure-synthesizer, evidence-binder, planning-topic-decomposer, pattern librarians |
| **GPT-5.1-Codex (Preview)** | Coding | implementor, test-implementor, code-patcher, plan-patcher, test-patcher |
| **Claude Opus 4.5 (Preview)** | Planning, Debugging (hard/big tasks) | strategy-planner, goal-planner, integration-planner, test-implementation-planner, testing-strategy, investigator, intent-translator, scope-triager |

### Invoking Sub-Agents

Reference other agents using `#agent:agent-name` syntax:

```markdown
Delegate to #agent:implementor for code execution.
Hand off to #agent:code-bug-review for defect analysis.
```

## Receipt System (Required)

**Every agent must produce a receipt** documenting its execution. Store receipts in `99_receipts/` subdirectory.

### Receipt Format

```markdown
## Receipt: [Agent Name] - [Timestamp]

### Inputs Used
- [List all inputs consumed]

### Outputs Produced
- [List all artifacts created]

### Deviations
- [List deviations from plan, or "None"]

### Assumptions
- [List assumptions made]

### Next Action
- [What should happen next]
```

### Why Receipts Matter

- Pipeline Oversight validates receipts at every gate
- Missing receipts trigger audit escalation
- Deviations without justification cause FAIL
- Receipts enable traceability and debugging

## Workspace Conventions

### Session Workspace Pattern

Structure: `.tmp/UUID_name/`

Example for implementation orchestration:
```
.tmp/create/implementation/
├── 00_intake/           # Intent, acceptance criteria, constraints
├── 10_research/         # Research findings, evidence, crawl artifacts
├── 20_planning/         # Strategy, planning topics, implementation plan
├── 30_code/             # Step logs, lint outputs
├── 40_tests/            # Test strategy, test plan, pytest outputs
├── 90_audit/            # Audit reports (if triggered)
└── 99_receipts/         # All agent receipts
```

### Workspace Rules

1. **Isolation**: Each session gets its own UUID-based workspace
2. **Preservation**: Preserve workspace on errors for debugging
3. **Artifacts**: All agent outputs go to structured folders
4. **Receipts**: Always stored in `99_receipts/` subdirectory
5. **Cleanup**: `.tmp/` is gitignored, can be manually cleaned

### File Output Pattern

Agents should:
1. Capture command outputs to files in workspace
2. Read/summarize files rather than dumping raw logs
3. Tag state with agent/step names for tracking
4. Use consistent naming (e.g., `test_output.txt`, `lint_results.log`)

## Agent Roles

| Role | Purpose | Example Agents |
|------|---------|----------------|
| **Translator** | Convert user intent into structured requirements | `#agent:intent-translator` |
| **Planner** | Create strategic and implementation plans | `#agent:strategy-planner`, `#agent:integration-planner` |
| **Crawler** | Search for patterns/information (parallel swarms) | `#agent:web-crawler`, `#agent:repo-crawler` |
| **Researcher** | Synthesize, deduplicate, organize information | `#agent:research-synthesizer` |
| **Implementor** | Execute plans literally (code or tests) | `#agent:implementor`, `#agent:test-implementor` |
| **Reviewer** | Enforce domain rules on artifacts | `#agent:architecture-review`, `#agent:code-bug-review` |
| **Drift Reviewer** | Compare artifacts against specifications | `#agent:implementation-drift-review`, `#agent:plan-drift-reviewer` |
| **Patcher** | Fix artifacts based on review feedback | `#agent:code-patcher`, `#agent:plan-patcher` |
| **Investigator** | Debug and repair in isolated environments | `#agent:investigator` |
| **Pipeline Oversight** | Verify receipts, detect deviations | `#agent:pipeline-oversight-enforcer` |

## Available Orchestrations

| Orchestration | Purpose | File |
|--------------|---------|------|
| **Implementation (CREATE)** | Full feature implementation pipeline | `implementation-orchestration.prompt.md` |
| **Research** | Crawler swarms + synthesis | `research-orchestration.prompt.md` |
| **Plan Integration (INTEGRATE)** | Topic decomposition + iterative planning | `plan-integration-orchestration.prompt.md` |
| **Artifact Review (REVIEW)** | Review loop with patching until PASS | `artifact-review-orchestration.prompt.md` |
| **Debug & Repair (REPAIR)** | Isolated debugging + fix application | `debug-repair-orchestration.prompt.md` |
| **Process Audit (AUDIT)** | Process misalignment analysis | `process-audit-orchestration.prompt.md` |

### Implementation Orchestration Flow

```
User Input
    ↓
Translator (intent → structure)
    ↓
Strategy Planner
    ↓
Research (if needed)
    ↓
Plan Integration
    ↓
Plan Review Loop
    ↓
Implementation (code only)
    ↓
Code Drift Review
    ↓
Code Review Loop
    ↓
Test Strategy
    ↓
Test Plan Integration
    ↓
Test Implementation
    ↓
Test Drift Review
    ↓
Test Review Loop
    ↓
Final Verification
    ↓
    ├─ PASS → Done
    └─ FAIL → Debug & Repair → Loop back
```

## Do's and Don'ts

### DO

1. **Produce receipts**: Document inputs, outputs, deviations, assumptions
2. **Follow plans literally**: Implementors execute plans exactly as written
3. **Use workspace isolation**: Store temporary files in `.tmp/UUID_name/`
4. **Loop until PASS**: Reviews must pass before proceeding
5. **Flag deviations**: Explicitly document any deviation in receipts
6. **Code first, tests after**: Complete code reviews before writing tests
7. **Tag agent outputs**: Use clear prefixes for state tracking (e.g., `[Step3Result]:`)

### DON'T

1. **Don't skip receipts**: Every agent must produce a receipt
2. **Don't create unauthorized stubs**: Implement everything unless plan defers
3. **Don't mix concerns**: Implementors don't plan, planners don't implement
4. **Don't bypass reviews**: All artifacts must pass review loops
5. **Don't hide deviations**: Pipeline oversight will flag missing receipts
6. **Don't commit .tmp/**: Workspace folders are gitignored
7. **Don't write tests during code implementation**: Tests come after code reviews pass
8. **Don't try to trick other agents**: Pipeline oversight detects instruction injection
9. **Don't skip gates**: Every stage has entry/exit validation

## Agent Best Practices

### For Implementors

1. Read plan file completely before starting
2. Implement everything requested (no unauthorized stubs)
3. Keep changes minimal and targeted
4. Output exactly: `SUCCESS`, `TESTS: [list]`, or `FAIL: <what>, <what>, <what>`

### For Reviewers

1. Focus on assigned domain (architecture, style, bugs, etc.)
2. Use pattern vocabulary (CODE-A, CODE-B, CODE-E, PAT-A, PAT-C, etc.)
3. Output PASS or FAIL with specific issues
4. Don't fix issues (delegate to patchers)
5. Rerun ALL reviews after any patch

### For Planners

1. Strategic planners define "what" and "won't"
2. Integration planners build detailed steps
3. Plans must be executable and ordered
4. Include acceptance criteria mapping
5. Flag unknowns and risks

### For Orchestrators

1. Route, don't implement
2. Validate gates (pipeline oversight)
3. Manage workspace state
4. Track agent receipts
5. Escalate to audit on repeated failures

## Troubleshooting

### Agent Not Following Plan

1. Check receipt for documented deviations
2. Review agent inputs (was plan clear?)
3. Verify agent has correct tools enabled
4. Check for instruction injection (pipeline oversight)
5. Escalate to audit if pattern persists

### Workspace Issues

1. Verify `.tmp/` structure matches conventions
2. Check file permissions
3. Look for orphaned sessions (manual cleanup OK)
4. Ensure gitignore includes `.tmp/`

### Review Loop Not Exiting

1. Check if patcher is actually fixing issues
2. Verify reviewers are using correct pattern vocabulary
3. Look for oscillating fixes (fix A breaks B, fix B breaks A)
4. Escalate to audit after 3 iterations
