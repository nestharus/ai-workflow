# Strategies

This document describes strategy implementations used by the spec manager workflow.
Strategies are executed during workflow phases to normalize input, mitigate risks,
and emit evidence for downstream auditing.

## Strategy Catalog

### format_repair

**Purpose**: Normalize LLM outputs with format violations (code fences, preambles, invalid JSON).

**When it runs**:
- Content contains code fences (triple-backtick blocks)
- Content includes `[agent-exec]` noise
- Content has leading or trailing commentary around a JSON payload

**Evidence recorded**:
- `Format repair: extracted JSON payload for <unit_id>`
- `Format repair: removed code fences from <unit_id>`
- `Format repair: stripped preamble from <unit_id>`
- `Format repair: normalized JSON for <unit_id>` (repair agent invoked)

**Integration**:
- Uses the existing repair pipeline in `scripts/spec_refinement/workflows/repair.py`
- Uses tolerant JSON extraction from `scripts/spec_refinement/workflows/formats.py`

**Example evidence records**:

```json
{
  "category": "format",
  "type": "code_fence_removal",
  "details": {
    "original_length": 120,
    "cleaned_length": 98,
    "extraction_method": "code_fence_removal",
    "location": "parse_library_labeler_output"
  }
}
```

```json
{
  "category": "format",
  "type": "repair_agent_invoked",
  "details": {
    "artifact_type": "spec_patches",
    "error_count": 2,
    "model_used": "gpt-5.2-low",
    "latency_ms": 412.7
  }
}
```

### truncation_guard

**Purpose**: Enforce max content length to prevent truncation in downstream processing.

**When it runs**:
- Unit content exceeds `max_unit_content_length` in workflow config

**Evidence recorded**:
- `Truncation guard: truncated <unit_id> from <original_length> to <cap> chars`
- Severity encoded in the issue string (`ERROR` if >2x cap, otherwise `WARNING`)

**Example evidence records**:

```json
{
  "severity": "warning",
  "message": "WARNING: Truncation guard: truncated U-123 from 120000 to 50000 chars (removed 70000)",
  "location": "truncation_guard",
  "detector": "strategy:truncation_guard",
  "details": {}
}
```

## Evidence Categories

### format

Used for JSON extraction and repair operations.

- `json_extraction`: Generic extraction when JSON is isolated from mixed output
- `code_fence_removal`: JSON extracted from fenced code blocks
- `preamble_stripping`: Leading commentary removed before JSON
- `repair_agent_invoked`: Repair agent used to fix non-compliant output

### truncation

Used when content is capped to prevent downstream truncation.

- `content_truncation`: Content length exceeds configured cap (encoded in
  `strategy:truncation_guard` evidence messages)
