---
description: (CREATE) Research workspace sub-orchestration using crawler swarms + researcher synthesis + evidence artifacts.
name: Research Orchestration (Create)
agent: agent
tools: ['search', 'fetch', 'usages', 'githubRepo', 'editFiles']
model: Claude Opus 4.5 (Preview)
---

# Research Orchestration (CREATE)

## Contract
Input:
- `intent.md`
- `strategy.md`
- `unknowns.md`
  Workspace root:
- `.tmp/create/implementation/10_research/`

Output:
- `research_findings.md` (synthesized answers)
- `evidence_table.md` (claims -> evidence pointers)
- `open_gaps.md` (what remains unknown / blocked)
- `domain_structure_candidates.md` (candidate domain structures)
- `repo_integration_map.md` (integration points in repo)
- receipts per step

## Step 1: Research plan (delegate)
CALL AGENT:
- `@research-question-decomposer` (Planner slice)
  Outputs:
- `research_questions.md`
- `crawl_plan.md`
- Receipt

Gate: `@pipeline-oversight-enforcer`

## Step 2: Crawler swarms (delegate)
For each question cluster in crawl_plan.md, run swarms:
CALL AGENTS (parallel wave per cluster):
- `@web-crawler` (Crawler slice) -> raw notes to `crawl_raw/web_<n>.md`
- `@repo-crawler` (Crawler slice) -> raw notes to `crawl_raw/repo_<n>.md`
- `@dependency-doc-crawler` (Crawler slice) -> raw notes to `crawl_raw/deps_<n>.md`
- `@repo-integration-crawler` (Crawler slice) -> raw notes to `crawl_raw/repo_integration_<n>.md`
- `@domain-structure-crawler` (Crawler slice) -> raw notes to `crawl_raw/domain_structure_<n>.md`

Outputs:
- `crawl_raw/` folder populated
- Receipt per crawler wave

Gate: `@pipeline-oversight-enforcer`

## Step 3: Synthesis + dedup (delegate)
CALL AGENTS:
- `@research-deduplicator` (Researcher slice) -> `deduped_notes.md`
- `@research-synthesizer` (Researcher slice) -> `research_findings.md`
- `@structure-synthesizer` (Researcher slice) -> `domain_structure_candidates.md`, `repo_integration_map.md`

Receipt(s)

Gate: `@pipeline-oversight-enforcer`

## Step 4: Evidence binding + coverage drift check (delegate)
CALL AGENTS:
- `@evidence-binder` (Researcher slice)
    - Produces `evidence_table.md` mapping each key claim -> supporting snippet link / source pointer
- `@research-coverage-drift-review` (Drift Reviewer slice)
    - Compares `research_questions.md` (spec) vs `research_findings.md` (artifact)
    - Ensures each question is answered or explicitly moved to open_gaps.md

Outputs:
- `evidence_table.md`
- `open_gaps.md`
- Drift report
- Receipt(s)

Gate: `@pipeline-oversight-enforcer`
