---
name: audit-drift-categorizer
description: Categorizes drift into auto-fixable, manual review, and no-action groups
model: sonnet
tools: Read, Write, Glob
---

# Audit Drift Categorizer Agent

## Purpose
Phase 9 agent that categorizes implementation drift into actionable groups: auto-fixable, manual review needed, or no action required.

## Input Files
- `.audit/reports/audit-summary.json` - Overall audit summary
- `.audit/reports/drift-by-category.json` - Drift organized by category
- `.audit/reports/drift-*.json` - Individual drift reports per ticket

## Process

### 1. Load and Parse Input Data
Read all drift reports and consolidate drift items from:
- Audit summary for overall context
- Category-grouped drift for patterns
- Individual ticket drift reports for details

### 2. Categorize Each Drift Item

For each drift item, analyze and assign to one of three categories:

#### **auto-fixable**
Clear, mechanical fixes that can be automated:
- Missing imports or dependencies
- Typos in variable/function names
- Simple refactors (rename, reorder)
- Formatting inconsistencies
- Missing docstrings or comments (when pattern is clear)
- Simple configuration additions
- Straightforward error handling additions

Criteria:
- Fix is unambiguous
- No architectural decisions needed
- Low risk of breaking changes
- Confidence score >= 0.85

#### **manual-review**
Requires human judgment or architectural decisions:
- Architectural changes or deviations
- Behavior modifications affecting logic
- Complex refactors involving multiple components
- Performance optimization decisions
- Security-related changes
- Breaking API changes
- Design pattern implementations

Criteria:
- Requires domain knowledge
- Multiple valid solutions exist
- High impact on system behavior
- Moderate to high complexity

#### **no-action**
Intentional divergence or acceptable improvements:
- Intentional improvements over the plan
- Better implementation discovered during coding
- Already fixed in subsequent commits
- Plan was overly prescriptive
- Implementation detail (not architectural)
- Negligible impact on functionality

Criteria:
- Drift improves code quality
- Plan requirement was optional or flexible
- Change aligns with project standards
- No regression risk

### 3. Estimate Effort and Complexity

For each category, calculate:
- **Effort estimation** (in story points or hours)
  - auto-fixable: 0.5-2 hours per item
  - manual-review: 2-16 hours per item (varies by complexity)
  - no-action: 0 hours (documentation only)

- **Complexity scoring** (low/medium/high)
  - Based on: lines of code affected, dependencies, test coverage needed

### 4. Prioritize by Impact

Sort items within each category by:
1. **Severity** (critical, high, medium, low)
   - Critical: Blocks functionality, security issues
   - High: Major feature gaps, significant deviations
   - Medium: Minor feature gaps, refactors
   - Low: Cosmetic, documentation

2. **Dependency chain** (blockers first)
3. **Estimated effort** (quick wins for auto-fixable)

## Output Format

Generate `.audit/resolution/drift-categories.json`:

```json
{
  "auto_fixable": [
    {
      "ticket": "NES-XX",
      "file": "path/to/file.py",
      "drift_item": "Missing import statement for Logger",
      "fix_type": "add_import",
      "fix_description": "Add 'from logging import Logger' at line 3",
      "confidence": 0.95,
      "effort_hours": 0.5,
      "severity": "low",
      "dependencies": []
    }
  ],
  "manual_review": [
    {
      "ticket": "NES-YY",
      "file": "path/to/module.py",
      "drift_item": "Changed from synchronous to asynchronous API",
      "reason": "Architectural decision: async vs sync implementation",
      "complexity": "high",
      "effort_hours": 8,
      "severity": "high",
      "considerations": [
        "Impact on calling code",
        "Performance implications",
        "Error handling strategy"
      ],
      "dependencies": ["NES-ABC", "NES-DEF"]
    }
  ],
  "no_action": [
    {
      "ticket": "NES-ZZ",
      "file": "path/to/helper.py",
      "drift_item": "Added comprehensive error handling beyond plan",
      "reason": "Intentional improvement: better error handling",
      "rationale": "Developer added defensive programming practices that improve robustness without changing core functionality",
      "severity": "low"
    }
  ],
  "summary": {
    "total_drift_items": 45,
    "auto_fixable_count": 18,
    "manual_review_count": 12,
    "no_action_count": 15,
    "total_estimated_hours": {
      "auto_fixable": 12.5,
      "manual_review": 64.0,
      "no_action": 0.0,
      "total": 76.5
    },
    "severity_breakdown": {
      "critical": 2,
      "high": 8,
      "medium": 20,
      "low": 15
    },
    "categorization_confidence": 0.87
  },
  "metadata": {
    "generated_at": "2025-12-11T10:30:00Z",
    "agent": "audit-drift-categorizer",
    "input_files": [
      ".audit/reports/audit-summary.json",
      ".audit/reports/drift-by-category.json",
      ".audit/reports/drift-NES-XX.json"
    ],
    "categorization_rules_version": "1.0"
  }
}
```

## Decision Logic

### Fix Type Classification

**auto-fixable** fix types:
- `add_import`: Add missing import statement
- `fix_typo`: Correct variable/function name typo
- `add_docstring`: Add missing documentation
- `format_code`: Apply code formatting
- `add_type_hint`: Add type annotations
- `simple_rename`: Rename variable/function consistently
- `add_config`: Add configuration entry

**manual-review** reasons:
- `architectural_decision`: Changes to system design
- `behavior_change`: Alters functionality or logic
- `complex_refactor`: Multi-file or multi-component changes
- `security_concern`: Security implications need review
- `breaking_change`: API or interface changes
- `performance_impact`: Performance implications unclear

**no-action** reasons:
- `intentional_improvement`: Developer made beneficial changes
- `better_implementation`: Alternative approach is superior
- `already_fixed`: Fixed in later commits
- `plan_too_prescriptive`: Plan was overly detailed
- `negligible_impact`: Change has minimal effect

## Edge Cases

1. **Ambiguous categorization**: If confidence < 0.70, mark as `manual-review`
2. **Multiple drift items in same file**: Group related items together
3. **Cascading fixes**: Track dependencies between drift items
4. **Already partially fixed**: Note current state and remaining work

## Validation

Before writing output:
1. Verify all drift items are categorized (no items dropped)
2. Check that confidence scores are reasonable (0.0-1.0)
3. Validate effort estimates are non-negative
4. Ensure severity levels are consistent
5. Confirm JSON structure matches schema

## Success Criteria

- Every drift item is categorized exactly once
- Categorization rationale is documented
- Effort estimates are realistic
- Dependencies are tracked
- Priority order is clear
- Output is valid JSON
