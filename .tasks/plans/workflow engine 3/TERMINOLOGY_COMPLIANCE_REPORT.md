# Terminology Compliance Report

**Generated**: 2026-01-28 22:40 UTC
**Scanned path**: `.tasks/plans/workflow engine 3`

## Summary

| Metric | Value |
|--------|-------|
| Files scanned | 61 |
| Files with violations | 10 |
| Total violations | 34 |

## Violations by File

### `.tasks/plans/workflow engine 3/Epic_Brief__Multi-Layered_Project_Management_System.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 86 | 13 | TERMINO001 | The term **“workspace”** MUST be qualified as either **WSS**... |
| 86 | 121 | TERMINO001 | The term **“workspace”** MUST be qualified as either **WSS**... |

### `.tasks/plans/workflow engine 3/TERMINOLOGY_RULES.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 29 | 23 | TERMINO001 | ### TERMINO001: Bare "workspace" usage |
| 37 | 12 | TERMINO001 | Flag bare "workspace" tokens (case-insensitive) except in th... |
| 45 | 11 | TERMINO001 | The term "workspace" is overloaded in this system: |
| 51 | 13 | TERMINO001 | Using bare "workspace" creates ambiguity about which concept... |
| 66 | 8 | TERMINO001 | \| `the workspace contains the latest changes` \| Violation \| ... |
| 66 | 67 | TERMINO001 | \| `the workspace contains the latest changes` \| Violation \| ... |
| 67 | 4 | TERMINO001 | \| `workspace isolation is important` \| Violation \| Bare "wor... |
| 67 | 58 | TERMINO001 | \| `workspace isolation is important` \| Violation \| Bare "wor... |
| 73 | 6 | TERMINO001 | jj\s+workspace          # Preceded by "jj " |
| 74 | 1 | TERMINO001 | workspace\/             # Followed by "/" |
| 75 | 1 | TERMINO001 | Workspace\s+State\s+Store\h?  # Part of "Workspace State Sto... |
| 78 | 1 | TERMINO001 | workspace\s*Store       # Followed by " Store" |
| 90 | 22 | TERMINO001 | 2. Replace the bare "workspace" token with the appropriate t... |

### `.tasks/plans/workflow engine 3/Tech_Plan__Configuration_&_Onboarding.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 224 | 34 | TERMINO001 | ## Terminology (do not overload “workspace”) |

### `.tasks/plans/workflow engine 3/Tech_Plan__Core_Infrastructure/00_Foundation.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 69 | 5 | TERMINO001 | ### Workspace naming (avoid overload) |
| 70 | 11 | TERMINO001 | The word “workspace” is overloaded in tools and in English. ... |
| 72 | 148 | TERMINO001 | - **WSS root directory**: the directory named `workspace/` u... |

### `.tasks/plans/workflow engine 3/Tech_Plan__Core_Infrastructure/10_Configuration_System.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 58 | 9 | TERMINO001 | mode = "workspace"                 # workspace (default) |
| 58 | 38 | TERMINO001 | mode = "workspace"                 # workspace (default) |
| 61 | 65 | TERMINO001 | copy_fallback = true               # allow fallback when spa... |

### `.tasks/plans/workflow engine 3/Tech_Plan__Core_Infrastructure/14_Schema_Compatibility_and_Migrations.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 29 | 25 | TERMINO001 | - `applies_to` (enum): `workspace\|repo_runtime\|tickets\|proje... |

### `.tasks/plans/workflow engine 3/Tech_Plan__Enhanced_Rebase_&_Evaluation.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 543 | 64 | TERMINO001 | - **If sandbox exists**: Run checks directly in the sandbox ... |

### `.tasks/plans/workflow engine 3/Tech_Plan__Integration/01_Scope_and_Terminology.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 32 | 63 | TERMINO001 | * In text, always call this **WSS** or **WSS root** (never "... |
| 42 | 37 | TERMINO001 | **Rule name**: `TERMINO001` - Bare "workspace" usage |
| 44 | 29 | TERMINO001 | **Description**: Flag bare "workspace" tokens except in the ... |
| 50 | 32 | TERMINO001 | **Pattern**: Standalone word `"workspace"` (case-insensitive... |
| 96 | 42 | TERMINO001 | * `RuleTERMINO001`: Implements the bare "workspace" detectio... |

### `.tasks/plans/workflow engine 3/Tech_Plan__Integration/07_Workflows__Surface_and_Schema_v1.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 181 | 53 | TERMINO001 | - `copy` — inherit sparse rules from the parent workspace |
| 184 | 11 | TERMINO001 | - After workspace creation, the runner may still apply expli... |

### `.tasks/plans/workflow engine 3/Tech_Plan__Integration/09_Sandboxes__JJ_Workspaces.md`

| Line | Column | Rule | Text |
|------|--------|------|------|
| 25 | 53 | TERMINO001 | * <https://man.archlinux.org/man/extra/jujutsu/jj-workspace-... |
| 35 | 36 | TERMINO001 | A **sandbox** is an ephemeral `jj` workspace created under t... |
| 356 | 20 | TERMINO001 | 3. Create a `jj` workspace: |

## Remediation Steps

For each TERMINO001 violation:

1. Determine whether the reference is to:
   - The durable state store → use **WSS**
   - The ephemeral execution environment → use **sandbox**
   - A Jujutsu command or concept → qualify as **jj workspace**

2. Replace the bare "workspace" token with the appropriate term

3. Re-run the linter to verify compliance
