# Handled File Recovery Log

This file tracks which files from logs.md have been verified/recovered to prevent regressions.

## Status Legend
- RECOVERED: File was missing and has been recreated
- VERIFIED: File exists and matches expected state
- NOT_WIPED: File was untracked and survived the wipe
- EXTERNAL: File is outside project directory (untracked, survived)

## Recovery Summary

### Recovered Files (Session 1)

#### scripts/mcp-agent/ - RECOVERED
- package.json
- tsconfig.json
- src/index.ts
- Built and installed (npm install && npm run build)

#### scripts/mcp-bash/ - RECOVERED
- package.json
- tsconfig.json
- src/index.ts
- Built and installed

#### .agents/*.toml - RECOVERED (23 files)
- claude-haiku.toml, claude-sonnet.toml, claude-opus.toml
- gpt-5.2-{low,medium,high,xhigh}.toml
- gpt-5.2-codex-{low,medium,high,xhigh}.toml
- gpt-5.1-codex-mini-{medium,high}.toml
- gemini-3-pro-{high,low}.toml
- gemini-3-flash-{high,medium,low,minimal}.toml
- minimax.toml, glm.toml
- smollm2-135.toml, smollm2-360.toml

#### docker/ollama/ - RECOVERED
- Dockerfile (ollama with smollm2:135m and smollm2:360m pre-loaded)
- docker-compose.yml (standalone testing)

#### docker-compose.dev.yml - RECOVERED
- Added ollama-smol service
- Added ollama_storage volume
- Added log command in header

### Files NOT Wiped (Untracked)

#### .tasks/plans/agent/ - NOT_WIPED
All files survived (untracked by git):
- requirements.md, plan.md, feedback*.md
- ticket-*.md, steps/*.md

#### External Files - NOT_WIPED (EXTERNAL)
All survived (outside repo):
- ~/.codex/config.toml - Has MCP server configs for agent/bash
- ~/.gemini/settings.json - Has gemini model aliases
- ~/.local/bin/ollama-* - Wrapper scripts
- ~/.local/bin/mcp-* - MCP wrapper scripts

## Recovery Complete
All files from logs.md have been accounted for.
