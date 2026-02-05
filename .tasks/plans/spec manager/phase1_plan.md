# Phase 1 Implementation Plan: Design-Alignment Harness

## Executive Summary

Phase 1 establishes an enforceable "definition of aligned" inside the repo through schemas, invariants, lints, and fixtures - without changing runtime behavior. This creates the foundation for contract-validated outputs (CON-0011) and 100% atom accounting (CON-0002).

---

## Current State Analysis

### Existing Infrastructure

1. **Schemas Module** (`scripts/spec_manager/spec_manager/schemas/`):
   - 20+ schema files for agent outputs (atoms, sections, tasks, etc.)
   - Pydantic-based validation with dataclasses
   - No centralized schema registry; schemas are imported directly

2. **Compliance Module** (`scripts/spec_manager/spec_manager/compliance/`):
   - `metrics.py`: ComplianceMetrics computation (format_compliance, annotation_coverage, id_normalization)
   - `scorer.py`: Scoring logic
   - No ContractValidationResult data structure (DS-COMP-0001 from design)

3. **QA/Lint Infrastructure**:
   - `bad_signatures.py`: Scans for known bad patterns in agent outputs
   - `contract_lint.py`: Lints agent prompts for legacy patterns
   - No "no-hardcoding policy" scanner for raw spec text

4. **Test Infrastructure**:
   - Tests in `tests/spec_refinement/` and `tests/spec_manager/`
   - Uses pyfakefs for filesystem isolation
   - No xfail tests for design invariants yet

5. **Design Schemas** (`.tasks/plans/spec manager/design/templates/`):
   - 8 JSON Schema files defining canonical output formats
   - Not yet imported into runtime code

---

## Work Item 1: Design Compliance Test Suite

### Goal
Create xfail tests that define what "aligned" means for CON-0011 (contract validation) and CON-0002 (100% atom accounting), plus invariant tests that must always pass.

### Files to Create

1. **`tests/spec_manager/compliance/test_design_invariants.py`**
   - Invariant tests for CON-0002 (100% atom accounting)
   - Tests that verify atom coverage reports correctly detect gaps
   - Tests that verify remainder queues are populated for unmapped atoms

2. **`tests/spec_manager/compliance/test_con_0011_contract_validation.py`**
   - xfail tests for CON-0011 (contract-validated outputs)
   - Test that invalid outputs are quarantined
   - Test that valid outputs pass through
   - Test ContractValidationResult structure

3. **`tests/spec_manager/compliance/test_con_0002_atom_accounting.py`**
   - xfail tests for CON-0002 (100% atom accounting)
   - Test that every atom is in exactly one state: mapped, remainder, or excluded
   - Test that coverage reports detect silent drops

4. **`tests/spec_manager/compliance/conftest.py`**
   - Shared fixtures for compliance tests
   - Sample valid/invalid artifacts
   - Mock atom manifests with known coverage states

### Key Integration Points

- Import existing `CoverageTracker` from `core/coverage.py` for atom accounting tests
- Use existing `ComplianceMetrics` from `core/data_structures.py`
- Follow test patterns from `tests/spec_refinement/conftest.py` (pyfakefs, monkeypatch)

### Specific Test Cases

```python
# CON-0002 Invariant: Every atom accounted
@pytest.mark.parametrize("scenario", ["all_mapped", "some_remainder", "some_excluded"])
def test_atom_accounting_invariant(scenario, atom_manifest):
    """Every atom must be in exactly one state."""
    result = verify_atom_accounting(atom_manifest)
    assert result.all_accounted
    assert result.unaccounted_atoms == []

# CON-0011 xfail: Invalid outputs quarantined (not yet implemented)
@pytest.mark.xfail(reason="DS-COMP-0001 ContractValidationResult not yet implemented")
def test_invalid_output_quarantined():
    """Invalid agent output must be quarantined, not written to authority."""
    invalid_output = {"elements": [{"missing_required_field": True}]}
    result = validate_and_route(invalid_output, schema_id="derived_elements")
    assert result.quarantined
    assert not result.written_to_authority
```

---

## Work Item 2: Schema Registry with ContractValidationResult

### Goal
Import/centralize design schemas and implement DS-COMP-0001 (ContractValidationResult) for contract validation gating.

### Files to Create

1. **`scripts/spec_manager/spec_manager/compliance/schema_registry.py`**
   - SchemaRegistry class that loads JSON schemas from design templates
   - Lazy loading of schemas on first access
   - Schema ID to file path mapping

2. **`scripts/spec_manager/spec_manager/compliance/validation.py`**
   - ContractValidationResult dataclass (DS-COMP-0001)
   - `validate_artifact_contract()` function (ALG-COMP-0001)
   - Integration with bad_signatures scanner

### Files to Modify

1. **`scripts/spec_manager/spec_manager/compliance/__init__.py`**
   - Export new ContractValidationResult, SchemaRegistry, validate_artifact_contract

### Data Structure: ContractValidationResult (DS-COMP-0001)

```python
@dataclass
class ContractValidationResult:
    """Result of validating an artifact against its contract schema."""
    artifact_id: str
    schema_id: str
    valid: bool
    errors: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "schema_id": self.schema_id,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }
```

### Schema Registry Design

```python
class SchemaRegistry:
    """Centralized registry for JSON schemas from design templates."""

    SCHEMA_DIR = Path(__file__).parents[5] / ".tasks/plans/spec manager/design/templates"

    SCHEMA_MAP = {
        "atoms": "atoms.schema.json",
        "section_map": "section_map.schema.json",
        "decomposition_output": "decomposition_output.schema.json",
        "library_labels": "library_labels.schema.json",
        "gap_element": "gap_element.schema.json",
        "task_plan": "task_plan.schema.json",
        "derived_elements": "derived_elements.schema.json",
        "tag_index_delta": "tag_index_delta.schema.json",
    }

    def __init__(self):
        self._loaded: dict[str, dict] = {}

    def get_schema(self, schema_id: str) -> dict:
        """Get schema by ID, loading from file if needed."""
        if schema_id not in self._loaded:
            self._loaded[schema_id] = self._load_schema(schema_id)
        return self._loaded[schema_id]

    def validate(self, artifact: dict, schema_id: str) -> ContractValidationResult:
        """Validate artifact against schema."""
        # Uses jsonschema library
        ...
```

### Integration Points

- Use `jsonschema` library for JSON Schema validation
- Integrate with existing `bad_signatures.scan_known_bad_signatures()`
- Follow ALG-COMP-0001 pseudocode from design doc

---

## Work Item 3: No-Hardcoding Policy Scanner (Report-Only)

### Goal
Add a lint that detects hardcoded phrases/regex used to parse raw spec text (violating CON-0003/CON-0004), running in report-only mode.

### Files to Create

1. **`scripts/spec_manager/spec_manager/compliance/hardcoding_scanner.py`**
   - Scanner for detecting prohibited hardcoding patterns
   - Report-only mode (warnings, not errors)
   - Integration with contract lint infrastructure

2. **`tests/spec_manager/compliance/test_hardcoding_scanner.py`**
   - Tests for the scanner
   - Sample code with violations
   - Sample code that follows the policy

### Prohibited Patterns (from design)

Per CON-0003 and the "No-Regex Compliance Review" doc:

1. **Scanning raw spec text for keywords** like "must/shall" to infer requirements
2. **Regex matching headings** like "##" to infer sections as primary logic
3. **Fixed lists of "banned libraries"** derived from content semantics

### Allowed Patterns (CON-0004)

1. System stamps and IDs (ATOM/SEC/EVID/LIB/REQ/...)
2. JSON schemas and explicit output formats
3. Projection pins and markers owned by the system

### Scanner Implementation

```python
@dataclass
class HardcodingFinding:
    """A potential hardcoding policy violation."""
    severity: str  # "warning" for report-only
    file: str
    line: int
    pattern_type: str  # "keyword_inference", "heading_parse", "semantic_list"
    message: str
    code_snippet: str

def scan_for_hardcoding_violations(
    source_paths: list[Path],
    allowlist: dict[str, list[str]] | None = None,
) -> list[HardcodingFinding]:
    """Scan Python source files for hardcoding policy violations."""
    findings = []

    # Patterns that suggest semantic inference from raw text
    KEYWORD_INFERENCE_RE = re.compile(
        r'(must|shall|should|required|mandatory)\s*["\']',
        re.IGNORECASE
    )

    # Patterns that suggest heading-based section inference
    HEADING_PARSE_RE = re.compile(
        r're\.(search|match|findall)\s*\([^)]*["\']#+'
    )

    # ... scan logic

    return findings
```

### Integration with Contract Lint

Add to `contract_lint.py`:

```python
def run_contract_lint(...) -> tuple[list[LintIssue], int]:
    # ... existing lint checks ...

    # Add hardcoding scanner (report-only)
    hardcoding_findings = scan_for_hardcoding_violations(source_paths)
    for finding in hardcoding_findings:
        issues.append(LintIssue(
            severity="warning",  # Report-only: warnings not errors
            file=finding.file,
            line=finding.line,
            message=f"[CON-0003] {finding.message}",
            hint="Consider using LLM-driven semantics instead of hardcoded patterns.",
        ))

    # ... rest of function ...
```

---

## Files to Create (Summary)

| File | Purpose |
|------|---------|
| `tests/spec_manager/compliance/__init__.py` | Test package init |
| `tests/spec_manager/compliance/conftest.py` | Shared fixtures |
| `tests/spec_manager/compliance/test_design_invariants.py` | Invariant tests |
| `tests/spec_manager/compliance/test_con_0011_contract_validation.py` | CON-0011 xfail tests |
| `tests/spec_manager/compliance/test_con_0002_atom_accounting.py` | CON-0002 xfail tests |
| `scripts/spec_manager/spec_manager/compliance/schema_registry.py` | Centralized schema registry |
| `scripts/spec_manager/spec_manager/compliance/validation.py` | ContractValidationResult + validation |
| `scripts/spec_manager/spec_manager/compliance/hardcoding_scanner.py` | No-hardcoding policy scanner |
| `tests/spec_manager/compliance/test_hardcoding_scanner.py` | Scanner tests |

## Files to Modify (Summary)

| File | Changes |
|------|---------|
| `scripts/spec_manager/spec_manager/compliance/__init__.py` | Export new classes |
| `scripts/spec_manager/spec_manager/refinement/qa/contract_lint.py` | Integrate hardcoding scanner |
| `docs/testing/spec-refinement-qa.md` | Add Phase 1 compliance test documentation |

---

## Implementation Sequence

1. **First**: Create `schema_registry.py` and `validation.py` (foundation)
2. **Second**: Create test fixtures in `conftest.py`
3. **Third**: Create xfail tests for CON-0011 and CON-0002
4. **Fourth**: Create invariant tests that must pass now
5. **Fifth**: Create `hardcoding_scanner.py` with tests
6. **Sixth**: Integrate scanner into contract lint (report-only)
7. **Last**: Update QA docs

---

## Success Criteria

- [ ] All invariant tests pass (CON-0002 accounting with existing CoverageTracker)
- [ ] xfail tests exist and are marked with clear reasons
- [ ] Schema registry loads all 8 design schemas
- [ ] ContractValidationResult matches DS-COMP-0001 spec
- [ ] Hardcoding scanner runs in report-only mode
- [ ] No runtime behavior changes to existing code
