# Terminology Rules Reference

This document defines all terminology rules enforced by the terminology linter for the Workflow Engine 3 specification.

## Overview

The terminology linter (implemented in `.tasks/plans/workflow engine 3/tools/terminology_linter.py`) enforces consistent use of domain-specific terminology across the specification. This prevents ambiguity and ensures clear communication between developers, implementers, and users.

## Running the Linter

```bash
# Quick scan with console output
python3 ".tasks/plans/workflow engine 3/tools/terminology_linter.py" scan ".tasks/plans/workflow engine 3"

# Generate comprehensive markdown report
python3 ".tasks/plans/workflow engine 3/tools/terminology_linter.py" generate-report ".tasks/plans/workflow engine 3"
```

## Enforcement

* **Scope**: All `.md` files in `.tasks/plans/workflow engine 3/` and subdirectories
* **CI integration**: Pre-merge validation (failing on violations)
* **Severity levels**: `warn` (non-blocking) and `error` (blocking)

---

## Rules

### TERMINO001: Bare "workspace" usage <!-- TERMINO001: intentional violation for section heading explaining the rule -->

**ID**: TERMINO001
**Severity**: error
**Category**: Domain terminology

**Description**:

Flag bare "workspace" tokens <!-- TERMINO001: intentional violation for documentation explaining the rule --> (case-insensitive) except in the following allowed contexts:

1. When preceded by `"jj "` (Jujutsu tool references)
2. When followed by `"/"` (file path contexts like `workspace/` or `workspace/README.md`)
3. When part of the phrases "Workspace State Store", "WSS", or "Workspace-State-" compound terms

**Rationale**:

The term "workspace" <!-- TERMINO001: intentional violation for documentation explaining the rule --> is overloaded in this system:

* **WSS (Workspace State Store)**: The durable state store directory under the runtime root (e.g., `~/.workflow/repos/<repo_uid>/workspace/`)
* **Sandbox**: An ephemeral environment for tool execution, implemented as a jj workspace
* **jj workspace**: The Jujutsu-specific term for a working copy created by `jj workspace add`

Using bare "workspace" <!-- TERMINO001: intentional violation for documentation explaining the rule --> creates ambiguity about which concept is being referenced. Always use specific terminology:

* Use **WSS** when referring to the durable state store
* Use **sandbox** when referring to the ephemeral execution environment
* Use **"jj workspace"** when referencing Jujutsu documentation or commands

**Examples**:

| Text | Status | Reason |
|------|--------|--------|
| `the sandbox provides isolated execution` | Compliant | Uses "sandbox" correctly |
| `the WSS contains durable state` | Compliant | Uses "WSS" correctly |
| `jj workspace add` creates a new sandbox | Compliant | "jj " prefix makes this a reference to Jujutsu command |
| `~/.workflow/repos/123/workspace/` | Compliant | "/" suffix indicates path context |
| `Workspace State Store stores artifacts` | Compliant | Part of "Workspace State Store" phrase |
| `the workspace contains the latest changes` <!-- TERMINO001: intentional violation for illustration --> | Violation | Bare "workspace" should be "sandbox" or "WSS" |
| `workspace isolation is important` <!-- TERMINO001: intentional violation for illustration --> | Violation | Bare "workspace" should be "sandbox" |

**Allowed Patterns**:

<!-- TERMINO001: intentional violation for documentation showing allowed patterns -->

```regex
# Allowed contexts (not violations)
jj\s+workspace          # Preceded by "jj " <!-- TERMINO001: intentional violation for pattern documentation -->
workspace\/             # Followed by "/" <!-- TERMINO001: intentional violation for pattern documentation -->
Workspace\s+State\s+Store\h?  # Part of "Workspace State Store" <!-- TERMINO001: intentional violation for pattern documentation -->
WSS\s*                  # Preceded by "WSS"
Workspace-State-        # Part of hyphenated compound
workspace\s*Store       # Followed by " Store" <!-- TERMINO001: intentional violation for pattern documentation -->
```

**Remediation**:

When a TERMINO001 violation is detected:

1. Determine whether the reference is to:
   * The durable state store → use **WSS**
   * The ephemeral execution environment → use **sandbox**
   * A Jujutsu command or concept → keep but qualify as "jj workspace"

2. Replace the bare "workspace" token <!-- TERMINO001: intentional violation for documentation explaining the rule --> with the appropriate term

3. Re-run the linter to verify compliance

---

## Adding New Rules

To add a new terminology rule:

1. Create a new class in `.tasks/plans/workflow engine 3/tools/terminology_linter.py`:

```python
class RuleTERMINOXXX(TerminologyRule):
    rule_id = "TERMINOXXX"
    description = "Description of the violation"
    severity = "warn"  # or "error"

    def check(self, content: str, file_path: str) -> list[TerminologyViolation]:
        violations = []
        # Implement detection logic
        return violations
```

2. Register the rule in `TerminologyLinter.__init__()`:

```python
def __init__(self) -> None:
    self.rules: list[TerminologyRule] = [
        RuleTERMINO001(),
        RuleTERMINOXXX(),  # Add new rule here
    ]
```

3. Document the rule in this file (TERMINOLOGY_RULES.md)
4. Update `Tech_Plan__Integration/01_Scope_and_Terminology.md` with rule context
5. Run the linter to generate baseline violations and update compliance report

---

## Compliance Report History

The linter generates `TERMINOLOGY_COMPLIANCE_REPORT.md` in the scanned directory to track violation status over time.

| Date | Files Scanned | Violations | Notes |
|------|---------------|------------|-------|
| 2026-01-28 | 60 | 28 | Initial baseline created |

---

## Contact and Maintenance

* **Tool location**: `.tasks/plans/workflow engine 3/tools/terminology_linter.py`
* **Primary documentation**: This file (TERMINOLOGY_RULES.md)
* **Scope definition**: `Tech_Plan__Integration/01_Scope_and_Terminology.md`

When updating terminology rules:

1. Consider the impact on existing documentation
2. Update this reference guide with the new rule
3. Update the scope definition file with rationale
4. Generate updated compliance report to track remediation