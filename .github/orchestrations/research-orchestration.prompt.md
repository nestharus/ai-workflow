---
name: research-orchestration
description: (CREATE) Research workspace sub-orchestration using crawler swarms + researcher synthesis + evidence artifacts.
tools: ["read", "search", "edit", "fetch", "custom-agent"]
target: vscode
---

# Orchestration: Research (CREATE)

## Plan
1. Create research plan from unknowns
2. Run crawler swarms in parallel waves
3. Synthesize and deduplicate findings
4. Bind evidence and check coverage
5. Exit with research findings + evidence table + open gaps

## Instructions

### Contract
Input:
- `intent.md`
- `strategy.md`
- `unknowns.md`
  Workspace root:
- `.tmp/UUID_implementation/10_research/`

Output:
- `research_findings.md` (synthesized answers)
- `evidence_table.md` (claims -> evidence pointers)
- `open_gaps.md` (what remains unknown / blocked)
- `domain_structure_candidates.md` (candidate domain structures)
- `repo_integration_map.md` (integration points in repo)
- receipts per step

---

### Step 1: Research plan (delegate)

CALL AGENT:
- `#agent:research-question-decomposer` (Planner slice)
  Outputs:
- `research_questions.md`
- `crawl_plan.md`
- Receipt

Gate: `#agent:pipeline-oversight-enforcer`

---

### Step 2: Crawler swarms (delegate)

For each question cluster in crawl_plan.md, run swarms:
CALL AGENTS (parallel wave per cluster):
- `#agent:web-crawler` (Crawler slice) -> raw notes to `crawl_raw/web_<n>.md`
- `#agent:repo-crawler` (Crawler slice) -> raw notes to `crawl_raw/repo_<n>.md`
- `#agent:dependency-doc-crawler` (Crawler slice) -> raw notes to `crawl_raw/deps_<n>.md`
- `#agent:repo-integration-crawler` (Crawler slice) -> raw notes to `crawl_raw/repo_integration_<n>.md`
- `#agent:domain-structure-crawler` (Crawler slice) -> raw notes to `crawl_raw/domain_structure_<n>.md`

Outputs:
- `crawl_raw/` folder populated
- Receipt per crawler wave

Gate: `#agent:pipeline-oversight-enforcer`

---

### Step 3: Synthesis + dedup (delegate)

CALL AGENTS:
- `#agent:research-deduplicator` (Researcher slice) -> `deduped_notes.md`
- `#agent:research-synthesizer` (Researcher slice) -> `research_findings.md`
- `#agent:structure-synthesizer` (Researcher slice) -> `domain_structure_candidates.md`, `repo_integration_map.md`

Receipt(s)

Gate: `#agent:pipeline-oversight-enforcer`

---

### Step 4: Evidence binding + coverage drift check (delegate)

CALL AGENTS:
- `#agent:evidence-binder` (Researcher slice)
    - Produces `evidence_table.md` mapping each key claim -> supporting snippet link / source pointer
- `#agent:research-coverage-drift-review` (Drift Reviewer slice)
    - Compares `research_questions.md` (spec) vs `research_findings.md` (artifact)
    - Ensures each question is answered or explicitly moved to open_gaps.md

Outputs:
- `evidence_table.md`
- `open_gaps.md`
- Drift report
- Receipt(s)

Gate: `#agent:pipeline-oversight-enforcer`
