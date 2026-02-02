# Structured Outputs

This document describes how structured outputs are generated and consumed for JSON-outputting agents.

## Overview

Structured outputs provide deterministic JSON compliance by enforcing schemas at generation time via
SDK-based API calls. Agents that declare `output_format: json` in frontmatter are executed with the
structured output runner instead of the CLI wrappers. The result is validated against Pydantic
schemas and returned as JSON.

## How Structured Outputs Work

1. `uv run agents <agent> <prompt>` loads agent frontmatter.
2. If `output_format: json` is set and a schema is registered, `scripts/agents/structured_output.py`
   calls the provider SDK directly.
3. The SDK enforces the JSON schema at generation time.
4. The output is validated with Pydantic and written to stdout as JSON.

## Structured Agents

The following agents are configured for structured JSON output:

* `glm-library-evidence-mapper`
* `chatgpt-library-spec-gap-judge`
* `opus-architecture-proposer`
* `chatgpt-architecture-tradeoff-judge`
* `glm-file-library-labeler`
* `glm-library-spec-integrator`
* `glm-architecture-brief-extractor`

## Adding a New Structured Agent

1. **Create a schema** in `scripts/spec_manager/spec_manager/schemas/` using Pydantic.
2. **Export the schema** in `scripts/spec_manager/spec_manager/schemas/__init__.py`.
3. **Register the schema** in `scripts/agents/__main__.py` under `AGENT_SCHEMAS`.
4. **Set agent frontmatter** in `.agents/agents/<agent>.md`:

```yaml
---
description: ...
model: ...
output_format: json
---
```

1. **Update workflows** to call `run_agent(..., structured_schema=YourSchema)`.

## Schema Guidelines

* Use `pydantic.BaseModel` with explicit field types.
* Prefer simple JSON primitives (string, number, boolean, list, object).
* Use `Field(ge=..., le=...)` for numeric bounds.
* Keep schemas minimal and focused on workflow needs.

## Fallback Behavior

Parsers in `scripts/spec_manager/spec_manager/refinement/formats.py` attempt structured validation first.
If validation fails, they fall back to tolerant JSON extraction (`_extract_json_payload`) and
legacy validation logic. A warning is logged when fallback parsing is used.

## Environment Variables

Structured output execution requires provider API keys:

* `OPENAI_API_KEY` (OpenAI models, including OpenAI-compatible endpoints)
* `ANTHROPIC_API_KEY` (Anthropic models)
* `CEREBRAS_API_KEY` (Cerebras OpenAI-compatible endpoint for GLM mappings)
