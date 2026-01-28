# Tech Plan: Integration — Scope & Terminology

* **Doc**: Tech_Plan__Integration/01_Scope_and_Terminology.md
* **Updated**: 2026-01-26
* **Shard**: Integration §1–§1.1
* **Libraries / packages**: `scripts/core/*` (cross-cutting)
* **Depends on**: `Tech_Plan__Core_Infrastructure.md` (global invariants)

## 1) Scope

This file defines how the runtime integrates with developer workflows and the codebase layout after migrating to:

* WSS (durable docs + artifacts)
* sharded JSONL logs (durable evidence)
* notifications + control actions queues (durable control plane)
* Patch-Stream (jj-backed ticket stacks)
* sandboxes (ephemeral tool execution)
* schema-validated user workflows (file-defined)
* a single auditable tool gateway (`workflow_engine`) for agents

**Single source of truth for global invariants**:
* Tech_Plan__Core_Infrastructure.md

This file specifies integration deltas: entrypoints, module boundaries, sandbox wiring, and workflow definition integration.

## 1.1 Terminology (WSS vs sandbox)

To avoid ambiguity:

* **WSS (Workspace State Store)**: the durable state store directory under the runtime root
  * Path example: `~/.workflow/repos/<repo_uid>/workspace/` (directory name is `workspace/`)
  * In text, always call this **WSS** or **WSS root**.

* **Sandbox**: an ephemeral environment used for tool execution (Integration §9).
  * In this system, a sandbox is implemented as a **jj workspace** created under the repo runtime root.

* **jj workspace**: the Jujutsu term for a working copy created by `jj workspace add`.
  * When referencing jj documentation, we keep the term "jj workspace"; otherwise we say "sandbox".

### 1.1.1 Linter Rule Specification

**Rule name**: `TERMINO001` - Bare workspace usage

**Description**: Flag bare workspace tokens except in the following allowed contexts:

1. When preceded by `"jj "` (Jujutsu tool references)
2. When followed by `"/"` (file path contexts)
3. When part of the phrases "Workspace State Store" or "WSS"

**Pattern**: Standalone word workspace is a violation unless:
* Preceded by `jj\s+` (e.g., "jj workspace", "jj workspace add")
* Followed by the path separator `\/` (e.g., "workspace/", "workspace/README.md")
* Inside "Workspace State Store" or its abbreviation "WSS"

**Implementation notes**:
* Linter implementation: `.tasks/plans/workflow engine 3/tools/terminology_linter.py`
* File extension scope: `.md` files only
* Severity: `error` (blocking; CI fails on violations to enforce strict terminology compliance)
* Linter is categorized under documentation/spec linting

**Reference**: See TERMINOLOGY_RULES.md for full rule documentation and enforcement wiring into CI pipeline.

### 1.1.2 Implementation: Terminology Linter Tool

**Location**: `.tasks/plans/workflow engine 3/tools/terminology_linter.py`

**Commands**:

```bash
# Scan directory and print violations to console
python3 ".tasks/plans/workflow engine 3/tools/terminology_linter.py" scan ".tasks/plans/workflow engine 3"

# Generate markdown compliance report
python3 ".tasks/plans/workflow engine 3/tools/terminology_linter.py" generate-report ".tasks/plans/workflow engine 3"

# Generate report to specific output file
python3 ".tasks/plans/workflow engine 3/tools/terminology_linter.py" generate-report ".tasks/plans/workflow engine 3" -o /path/to/report.md
```

**Output**:

* Console scan output: Color-coded violations with line/column information
* Markdown report: `TERMINOLOGY_COMPLIANCE_REPORT.md` in the scanned directory (or custom path)

**Report contents**:

* Summary statistics (files scanned, files with violations, total violations)
* Violations grouped by file with line/column references
* Remediation steps with guidance on correcting violations

**Architecture**:

The linter is implemented using a rule-based pattern matching system:

* `TerminologyRule`: Base class for all terminology rules
* `RuleTERMINO001`: Implements the bare workspace detection rule
* `TerminologyLinter`: Orchestrates scanning of directories and applies all rules
* `LinterResult`: Collects and formats violation data for reporting

Each rule implements a `check(content, file_path)` method that returns a list of `TerminologyViolation` objects. The linter can be extended by adding new rule classes that inherit from `TerminologyRule`.

### 1.1.3 Verification Workflow

**Pre-commit verification**:

Before documenting or changing terminology rules:

1. Run the linter: `python3 ".tasks/plans/workflow engine 3/tools/terminology_linter.py" generate-report ".tasks/plans/workflow engine 3"`
2. Review the `TERMINOLOGY_COMPLIANCE_REPORT.md` output
3. Address all violations or document intentional exceptions in TERMINOLOGY_RULES.md
4. Re-run the linter to verify compliance

**CI integration**:

The linter should be integrated into the CI pipeline to ensure ongoing compliance:

* Phase: Pre-merge validation
* Trigger: On all changes to `.tasks/plans/workflow engine 3/**`
* Action: Run `.tasks/plans/workflow engine 3/tools/terminology_linter.py scan` and fail on violations
* Severity: Blocking (non-zero exit code on violations)

**Adding new rules**:

To add a new terminology rule:

1. Define a new class in `.tasks/plans/workflow engine 3/tools/terminology_linter.py` inheriting from `TerminologyRule`
2. Set `rule_id`, `description`, and `severity` class attributes
3. Implement the `check()` method to detect violations
4. Register the rule by adding it to `TerminologyLinter.__init__()`
5. Document the rule in TERMINOLOGY_RULES.md
6. Update this file (01_Scope_and_Terminology.md) with rule specifics
7. Run the linter to baseline compliance and generate initial violations
