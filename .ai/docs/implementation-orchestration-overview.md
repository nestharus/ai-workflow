# Implementation Orchestration Overview (Flattened)

This document shows the complete Implementation Orchestration (CREATE) with all sub-orchestrations expanded inline. Every agent and every gate is visible in a single view.

---

## SIEVE Pipeline Rules (Non-negotiable)

1. **Orchestrator routes only**: It must not perform research, implementation, or reviews. It delegates.
2. **CODE FIRST, TESTS AFTER**: Implement code, complete all code reviews, then tests.
3. **Loop until clean**: Any failing review re-enters the correct loop until PASS.
4. **Every agent writes a receipt**: Deviations/assumptions must be explicit.
5. **Pipeline Oversight is the enforcer**: Only the enforcer can clear justified deviations.

---

## Workspace Structure

```
.tmp/create/implementation/
├── 00_intake/           # Intent, acceptance criteria, constraints, unknowns
├── 10_research/         # Research findings, evidence, crawl artifacts
│   └── crawl_raw/       # Raw crawler outputs
├── 20_planning/         # Strategy, planning topics, implementation plan
├── 30_code/             # Step logs, lint outputs
├── 40_tests/            # Test strategy, test plan, pytest outputs
├── 90_audit/            # Audit reports (if triggered)
└── 99_receipts/         # All agent receipts
```

---

## Complete Flow Diagram

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║                        IMPLEMENTATION ORCHESTRATION (CREATE)                   ║
╚═══════════════════════════════════════════════════════════════════════════════╝
                                    │
┌───────────────────────────────────┼───────────────────────────────────────────┐
│                            STAGE 0: INTAKE                                    │
│                                                                               │
│  ┌─────────────────┐     ┌─────────────────┐                                 │
│  │ @intent-        │     │ @scope-triager  │                                 │
│  │   translator    │     │                 │                                 │
│  └────────┬────────┘     └────────┬────────┘                                 │
│           │                       │                                           │
│           └───────────┬───────────┘                                           │
│                       ▼                                                       │
│           ┌─────────────────────┐                                             │
│           │ @pipeline-oversight │ ◄── GATE                                   │
│           │     -enforcer       │                                             │
│           └─────────────────────┘                                             │
│                                                                               │
│  Outputs: intent.md, acceptance_criteria.md, constraints.md, unknowns.md     │
└───────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                          STAGE 1: STRATEGY                                    │
│                                                                               │
│  ┌────────────────────┐                                                       │
│  │ @strategy-planner  │ ◄── Planner slice (strategic)                        │
│  └─────────┬──────────┘                                                       │
│            ▼                                                                  │
│  ┌─────────────────────┐                                                      │
│  │ @pipeline-oversight │ ◄── GATE                                            │
│  │     -enforcer       │                                                      │
│  └─────────────────────┘                                                      │
│                                                                               │
│  Outputs: strategy.md                                                         │
└───────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║        STAGE 2: RESEARCH [Research Orchestration (CREATE) EXPANDED]          ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  ┌─────────────────────────┐                                                  ║
║  │ @research-question-     │ ◄── Planner slice                               ║
║  │    decomposer           │                                                  ║
║  └───────────┬─────────────┘                                                  ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE                                            ║
║  │     -enforcer       │                                                      ║
║  └───────────┬─────────┘                                                      ║
║              ▼                                                                ║
║  ╔═══════════════════════════════════════════════════════════════════╗        ║
║  ║            CRAWLER SWARM (parallel per question cluster)          ║        ║
║  ╠═══════════════════════════════════════════════════════════════════╣        ║
║  ║  ┌───────────┐ ┌───────────┐ ┌────────────────┐                   ║        ║
║  ║  │ @web-     │ │ @repo-    │ │ @dependency-   │                   ║        ║
║  ║  │  crawler  │ │  crawler  │ │  doc-crawler   │                   ║        ║
║  ║  └─────┬─────┘ └─────┬─────┘ └───────┬────────┘                   ║        ║
║  ║        │             │               │                             ║        ║
║  ║  ┌─────────────────┐ │ ┌────────────────────────┐                 ║        ║
║  ║  │ @repo-          │ │ │ @domain-structure-     │                 ║        ║
║  ║  │  integration-   │ │ │    crawler             │                 ║        ║
║  ║  │  crawler        │ │ └────────────┬───────────┘                 ║        ║
║  ║  └────────┬────────┘ │              │                             ║        ║
║  ║           └────┬─────┴──────────────┘                             ║        ║
║  ╚════════════════╧══════════════════════════════════════════════════╝        ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE                                            ║
║  │     -enforcer       │                                                      ║
║  └───────────┬─────────┘                                                      ║
║              ▼                                                                ║
║  ╔═══════════════════════════════════════════════════════════════════╗        ║
║  ║                     SYNTHESIS PHASE                               ║        ║
║  ╠═══════════════════════════════════════════════════════════════════╣        ║
║  ║  ┌───────────────────┐    ┌───────────────────┐                   ║        ║
║  ║  │ @research-        │    │ @research-        │                   ║        ║
║  ║  │   deduplicator    │    │   synthesizer     │                   ║        ║
║  ║  └─────────┬─────────┘    └─────────┬─────────┘                   ║        ║
║  ║            │                        │                             ║        ║
║  ║  ┌───────────────────┐              │                             ║        ║
║  ║  │ @structure-       │              │                             ║        ║
║  ║  │   synthesizer     │              │                             ║        ║
║  ║  └─────────┬─────────┘              │                             ║        ║
║  ║            └────────────┬───────────┘                             ║        ║
║  ╚═════════════════════════╧═════════════════════════════════════════╝        ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE                                            ║
║  │     -enforcer       │                                                      ║
║  └───────────┬─────────┘                                                      ║
║              ▼                                                                ║
║  ╔═══════════════════════════════════════════════════════════════════╗        ║
║  ║                 EVIDENCE BINDING + COVERAGE                       ║        ║
║  ╠═══════════════════════════════════════════════════════════════════╣        ║
║  ║  ┌────────────────┐     ┌──────────────────────────┐              ║        ║
║  ║  │ @evidence-     │     │ @research-coverage-      │              ║        ║
║  ║  │   binder       │     │    drift-review          │              ║        ║
║  ║  └───────┬────────┘     └────────────┬─────────────┘              ║        ║
║  ║          └───────────────┬───────────┘                            ║        ║
║  ╚══════════════════════════╧════════════════════════════════════════╝        ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE                                            ║
║  │     -enforcer       │                                                      ║
║  └─────────────────────┘                                                      ║
║                                                                               ║
║  Outputs: research_findings.md, evidence_table.md, open_gaps.md,             ║
║           domain_structure_candidates.md, repo_integration_map.md             ║
╚═══════════════════════════════════════════════════════════════════════════════╝
                                    │
                                    ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║     STAGE 3: PLAN INTEGRATION [Plan Integration Orchestration EXPANDED]       ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  ┌─────────────────────────┐                                                  ║
║  │ @planning-topic-        │ ◄── Decomposes into ordered topics              ║
║  │    decomposer           │                                                  ║
║  └───────────┬─────────────┘                                                  ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE                                            ║
║  │     -enforcer       │                                                      ║
║  └───────────┬─────────┘                                                      ║
║              ▼                                                                ║
║  ╔═══════════════════════════════════════════════════════════════════╗        ║
║  ║        ITERATIVE PLANNING (sequential, one topic at a time)       ║        ║
║  ╠═══════════════════════════════════════════════════════════════════╣        ║
║  ║            ┌─────────────────────────────────────────────┐        ║        ║
║  ║            │    FOR EACH topic in planning_topics.md:    │        ║        ║
║  ║            │                                             │        ║        ║
║  ║            │  ┌──────────────────┐                       │        ║        ║
║  ║            │  │ @integration-    │ ◄── Adds section to   │        ║        ║
║  ║            │  │    planner       │     implementation    │        ║        ║
║  ║            │  └────────┬─────────┘     plan              │        ║        ║
║  ║            │           │                                 │        ║        ║
║  ║            │           ▼                                 │        ║        ║
║  ║            │  [Validate plan structure after each]       │        ║        ║
║  ║            │                                             │        ║        ║
║  ║            └──────────────────┬──────────────────────────┘        ║        ║
║  ║                               │                                   ║        ║
║  ╚═══════════════════════════════╧═══════════════════════════════════╝        ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE (after all topics)                         ║
║  │     -enforcer       │                                                      ║
║  └───────────┬─────────┘                                                      ║
║              ▼                                                                ║
║  ╔═══════════════════════════════════════════════════════════════════╗        ║
║  ║                      PLAN REVIEW PHASE                            ║        ║
║  ╠═══════════════════════════════════════════════════════════════════╣        ║
║  ║  ┌───────────────────────┐   ┌────────────────────┐               ║        ║
║  ║  │ @plan-structure-      │   │ @pattern-plan-     │               ║        ║
║  ║  │    reviewer           │   │    review          │               ║        ║
║  ║  └──────────┬────────────┘   └─────────┬──────────┘               ║        ║
║  ║             │                          │                          ║        ║
║  ║  ┌────────────────────┐                │                          ║        ║
║  ║  │ @plan-drift-       │                │                          ║        ║
║  ║  │    reviewer        │                │                          ║        ║
║  ║  └──────────┬─────────┘                │                          ║        ║
║  ║             └──────────────┬───────────┘                          ║        ║
║  ╚════════════════════════════╧══════════════════════════════════════╝        ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE                                            ║
║  │     -enforcer       │                                                      ║
║  └─────────────────────┘                                                      ║
║                                                                               ║
║  Outputs: planning_topics.md, implementation_plan.md                          ║
╚═══════════════════════════════════════════════════════════════════════════════╝
                                    │
                                    ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║    STAGE 4: PLAN REVIEW [Artifact Review Orchestration EXPANDED for PLAN]     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  ╔═══════════════════════════════════════════════════════════════════╗        ║
║  ║                    REVIEW LOOP (until PASS)                       ║        ║
║  ╠═══════════════════════════════════════════════════════════════════╣        ║
║  ║  Artifact: implementation_plan.md                                 ║        ║
║  ║  Reviewers (sequential):                                          ║        ║
║  ║                                                                   ║        ║
║  ║  ┌────────────────────┐    ┌────────────────────┐                 ║        ║
║  ║  │ @architecture-     │ ─► │ @code-style-       │                 ║        ║
║  ║  │    review          │    │    review          │                 ║        ║
║  ║  └─────────┬──────────┘    └─────────┬──────────┘                 ║        ║
║  ║            └───────────────┬─────────┘                            ║        ║
║  ║                            ▼                                      ║        ║
║  ║                    ┌───────┴───────┐                              ║        ║
║  ║                    │               │                              ║        ║
║  ║                  PASS            FAIL                             ║        ║
║  ║                    │               │                              ║        ║
║  ║                    │               ▼                              ║        ║
║  ║                    │    ┌──────────────────┐                      ║        ║
║  ║                    │    │ @plan-patcher    │ ─► LOOP BACK         ║        ║
║  ║                    │    └──────────────────┘                      ║        ║
║  ║                    ▼                                              ║        ║
║  ╚════════════════════════════════════════════════════════════════════╝       ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE (per iteration)                            ║
║  │     -enforcer       │                                                      ║
║  └─────────────────────┘                                                      ║
╚═══════════════════════════════════════════════════════════════════════════════╝
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                      STAGE 5: CODE IMPLEMENTATION                             │
│                                                                               │
│  ┌──────────────────┐                                                         │
│  │ @implementor     │ ◄── Implementation slice                               │
│  │                  │     (NO tests, code only, follow plan literally)        │
│  └────────┬─────────┘                                                         │
│           ▼                                                                   │
│  ┌─────────────────────┐                                                      │
│  │ @pipeline-oversight │ ◄── GATE                                            │
│  │     -enforcer       │                                                      │
│  └─────────────────────┘                                                      │
│                                                                               │
│  Outputs: Code changes, step_log.md                                           │
└───────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                       STAGE 6: CODE DRIFT REVIEW                              │
│                                                                               │
│  ┌──────────────────────────┐                                                 │
│  │ @implementation-drift-   │ ◄── Drift Reviewer                             │
│  │    review                │     (Compare code vs implementation_plan.md)    │
│  └───────────┬──────────────┘                                                 │
│              │                                                                │
│         ┌────┴────┐                                                           │
│         │         │                                                           │
│       PASS      FAIL ─────► Route to REPAIR orchestration OR @implementor    │
│         │                   Then re-run drift review                          │
│         ▼                                                                     │
│  ┌─────────────────────┐                                                      │
│  │ @pipeline-oversight │ ◄── GATE                                            │
│  │     -enforcer       │                                                      │
│  └─────────────────────┘                                                      │
└───────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║    STAGE 7: CODE REVIEW [Artifact Review Orchestration EXPANDED for CODE]     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  ╔═══════════════════════════════════════════════════════════════════╗        ║
║  ║                    REVIEW LOOP (until PASS)                       ║        ║
║  ╠═══════════════════════════════════════════════════════════════════╣        ║
║  ║  Artifact: repository code (scoped to changed files)             ║        ║
║  ║  Reviewers (sequential; rerun ALL on any fail):                   ║        ║
║  ║                                                                   ║        ║
║  ║  ┌────────────────────┐    ┌────────────────────┐                 ║        ║
║  ║  │ @code-anatomical-  │ ─► │ @code-bug-         │                 ║        ║
║  ║  │    review          │    │    review          │                 ║        ║
║  ║  └─────────┬──────────┘    └─────────┬──────────┘                 ║        ║
║  ║            └───────────────┬─────────┘                            ║        ║
║  ║                            ▼                                      ║        ║
║  ║                    ┌───────┴───────┐                              ║        ║
║  ║                    │               │                              ║        ║
║  ║                  PASS            FAIL                             ║        ║
║  ║                    │               │                              ║        ║
║  ║                    │               ▼                              ║        ║
║  ║                    │    ┌──────────────────┐                      ║        ║
║  ║                    │    │ @code-patcher    │ ─► LOOP BACK         ║        ║
║  ║                    │    └──────────────────┘                      ║        ║
║  ║                    ▼                                              ║        ║
║  ╚════════════════════════════════════════════════════════════════════╝       ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE (per iteration)                            ║
║  │     -enforcer       │                                                      ║
║  └─────────────────────┘                                                      ║
║                                                                               ║
║  Pattern vocabulary: CODE-B (Anatomical), CODE-E (Bug/Error)                  ║
╚═══════════════════════════════════════════════════════════════════════════════╝
                                    │
                                    ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    CODE COMPLETE - PROCEED TO TESTS                           ║
╚═══════════════════════════════════════════════════════════════════════════════╝
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                       STAGE 8: TEST STRATEGY                                  │
│                                                                               │
│  ┌──────────────────────┐                                                     │
│  │ @testing-strategy    │ ◄── Planner slice                                  │
│  │                      │     (Identifies use-cases, components, codepaths)   │
│  └────────┬─────────────┘                                                     │
│           ▼                                                                   │
│  ┌─────────────────────┐                                                      │
│  │ @pipeline-oversight │ ◄── GATE                                            │
│  │     -enforcer       │                                                      │
│  └─────────────────────┘                                                      │
│                                                                               │
│  Outputs: testing_strategy.md                                                 │
└───────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  STAGE 9: TEST PLAN INTEGRATION [Plan Integration Orchestration EXPANDED]     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  ┌─────────────────────────┐                                                  ║
║  │ @planning-topic-        │ ◄── Decomposes test strategy into topics        ║
║  │    decomposer           │                                                  ║
║  └───────────┬─────────────┘                                                  ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE                                            ║
║  │     -enforcer       │                                                      ║
║  └───────────┬─────────┘                                                      ║
║              ▼                                                                ║
║  ╔═══════════════════════════════════════════════════════════════════╗        ║
║  ║       ITERATIVE TEST PLANNING (one topic at a time)               ║        ║
║  ╠═══════════════════════════════════════════════════════════════════╣        ║
║  ║            ┌─────────────────────────────────────────────┐        ║        ║
║  ║            │    FOR EACH topic in planning_topics.md:    │        ║        ║
║  ║            │                                             │        ║        ║
║  ║            │  ┌──────────────────┐                       │        ║        ║
║  ║            │  │ @integration-    │ ◄── Adds test section │        ║        ║
║  ║            │  │    planner       │                       │        ║        ║
║  ║            │  └────────┬─────────┘                       │        ║        ║
║  ║            │           │                                 │        ║        ║
║  ║            │           ▼                                 │        ║        ║
║  ║            │  [Validate plan structure after each]       │        ║        ║
║  ║            │                                             │        ║        ║
║  ║            └──────────────────┬──────────────────────────┘        ║        ║
║  ║                               │                                   ║        ║
║  ╚═══════════════════════════════╧═══════════════════════════════════╝        ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE                                            ║
║  │     -enforcer       │                                                      ║
║  └─────────────────────┘                                                      ║
║                                                                               ║
║  Outputs: test_implementation_plan.md                                         ║
╚═══════════════════════════════════════════════════════════════════════════════╝
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                      STAGE 10: TEST IMPLEMENTATION                            │
│                                                                               │
│  ┌──────────────────────┐                                                     │
│  │ @test-implementor    │ ◄── Implementation slice                           │
│  │                      │     (Follow test plan literally)                    │
│  └────────┬─────────────┘                                                     │
│           ▼                                                                   │
│  ┌─────────────────────┐                                                      │
│  │ @pipeline-oversight │ ◄── GATE                                            │
│  │     -enforcer       │                                                      │
│  └─────────────────────┘                                                      │
│                                                                               │
│  Outputs: Tests, test_step_log.md                                             │
└───────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                       STAGE 11: TEST DRIFT REVIEW                             │
│                                                                               │
│  ┌──────────────────────────┐                                                 │
│  │ @implementation-drift-   │ ◄── Drift Reviewer                             │
│  │    review                │     (Compare tests vs test_implementation_plan) │
│  └───────────┬──────────────┘                                                 │
│              │                                                                │
│         ┌────┴────┐                                                           │
│         │         │                                                           │
│       PASS      FAIL ─────► Route to REPAIR or @test-implementor             │
│         │                   Then re-run drift review                          │
│         ▼                                                                     │
│  ┌─────────────────────┐                                                      │
│  │ @pipeline-oversight │ ◄── GATE                                            │
│  │     -enforcer       │                                                      │
│  └─────────────────────┘                                                      │
└───────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║   STAGE 12: TEST REVIEW [Artifact Review Orchestration EXPANDED for TESTS]    ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  ╔═══════════════════════════════════════════════════════════════════╗        ║
║  ║                    REVIEW LOOP (until PASS)                       ║        ║
║  ╠═══════════════════════════════════════════════════════════════════╣        ║
║  ║  Artifact: tests (scoped to changed tests)                        ║        ║
║  ║  Reviewers (PARALLEL; rerun ALL on any fail):                     ║        ║
║  ║                                                                   ║        ║
║  ║  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             ║        ║
║  ║  │ @test-       │  │ @test-       │  │ @test-       │             ║        ║
║  ║  │   clarity-   │  │   structure- │  │   async-     │             ║        ║
║  ║  │   review     │  │   review     │  │   review     │             ║        ║
║  ║  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘             ║        ║
║  ║         └─────────────────┼─────────────────┘                     ║        ║
║  ║                           ▼                                       ║        ║
║  ║                   ┌───────┴───────┐                               ║        ║
║  ║                   │               │                               ║        ║
║  ║               ALL PASS        ANY FAIL                            ║        ║
║  ║                   │               │                               ║        ║
║  ║                   │               ▼                               ║        ║
║  ║                   │    ┌──────────────────┐                       ║        ║
║  ║                   │    │ @test-patcher    │ ─► LOOP BACK          ║        ║
║  ║                   │    └──────────────────┘                       ║        ║
║  ║                   ▼                                               ║        ║
║  ╚═══════════════════════════════════════════════════════════════════╝        ║
║              ▼                                                                ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE (per iteration)                            ║
║  │     -enforcer       │                                                      ║
║  └─────────────────────┘                                                      ║
║                                                                               ║
║  Pattern vocabulary: PAT-A, PAT-B, PAT-C, PAT-E, PAT-T                        ║
╚═══════════════════════════════════════════════════════════════════════════════╝
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                      STAGE 13: FINAL VERIFICATION                             │
│                                                                               │
│  ┌──────────────────────┐                                                     │
│  │ @verification-runner │ ◄── Implementation slice                           │
│  │                      │     (uv run lint && uv run pytest --cov)            │
│  └────────┬─────────────┘                                                     │
│           │                                                                   │
│      ┌────┴────┐                                                              │
│      │         │                                                              │
│    PASS      FAIL ─────────────────────────────────────────────────┐          │
│      │                                                             │          │
│      ▼                                                             │          │
│   ┌──────┐                                                         │          │
│   │ DONE │                                                         │          │
│   └──────┘                                                         │          │
│                                                                    ▼          │
│  ╔═══════════════════════════════════════════════════════════════════╗        │
│  ║      DEBUG & REPAIR [Debug & Repair Orchestration EXPANDED]       ║        │
│  ╠═══════════════════════════════════════════════════════════════════╣        │
│  ║                                                                   ║        │
│  ║  ┌──────────────────┐                                             ║        │
│  ║  │ @investigator    │ ◄── Investigator slice                      ║        │
│  ║  │                  │     (Isolated worktree, reproduce, fix)     ║        │
│  ║  └────────┬─────────┘                                             ║        │
│  ║           │                                                       ║        │
│  ║           ▼ Outputs: repair_root_cause.md, repair_patch_summary.md║        │
│  ║                                                                   ║        │
│  ║  Then invoke Artifact Review Orchestration for repaired artifact: ║        │
│  ║                                                                   ║        │
│  ║  ┌──────────────────────────────────────────────────────────┐     ║        │
│  ║  │ Run review set for repaired artifact (code or tests)     │     ║        │
│  ║  │ Loop until PASS                                          │     ║        │
│  ║  └──────────────────────────────────────────────────────────┘     ║        │
│  ║           │                                                       ║        │
│  ║           ▼                                                       ║        │
│  ║  ┌─────────────────────┐                                          ║        │
│  ║  │ @pipeline-oversight │ ◄── GATE                                ║        │
│  ║  │     -enforcer       │                                          ║        │
│  ║  └─────────────────────┘                                          ║        │
│  ║                                                                   ║        │
│  ╚═══════════════════════════════════════════════════════════════════╝        │
│           │                                                                   │
│           └───────────► Return to appropriate sieve layer                     │
│                         (drift -> review -> verify)                           │
│                                                                               │
│  ┌─────────────────────┐                                                      │
│  │ @pipeline-oversight │ ◄── GATE                                            │
│  │     -enforcer       │                                                      │
│  └─────────────────────┘                                                      │
└───────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║             ESCALATION: AUDIT [Process Audit Orchestration]                   ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Triggered when ANY of:                                                       ║
║  - >2 consecutive drift failures on same artifact                             ║
║  - >2 consecutive review loops with "no progress"                             ║
║  - Missing receipts                                                           ║
║  - Oversight flags suspicious instruction injection                           ║
║                                                                               ║
║  Inputs: receipts folder, drift reports, review reports, git history         ║
║  Output: audit_report.md (process-level misalignment analysis)               ║
║                                                                               ║
║  ┌─────────────────────┐                                                      ║
║  │ @pipeline-oversight │ ◄── GATE                                            ║
║  │     -enforcer       │                                                      ║
║  └─────────────────────┘                                                      ║
╚═══════════════════════════════════════════════════════════════════════════════╝

```

---

## Complete Agent Inventory

### Translator Slice (Stage 0)
| Agent | Role |
|-------|------|
| `@intent-translator` | Produces structured intent + acceptance criteria |
| `@scope-triager` | Identifies unknowns, risks, research topics |

### Planner Slice (Stages 1, 3, 8, 9)
| Agent | Role |
|-------|------|
| `@strategy-planner` | Strategic planning (what/won't/risks) |
| `@research-question-decomposer` | Decomposes research into question clusters |
| `@planning-topic-decomposer` | Decomposes acceptance criteria into topics |
| `@integration-planner` | Builds plan sections per topic |
| `@testing-strategy` | Identifies use-cases, components, codepaths |

### Crawler Slice (Stage 2 - Research)
| Agent | Role |
|-------|------|
| `@web-crawler` | External web research |
| `@repo-crawler` | Repository code research |
| `@dependency-doc-crawler` | Dependency documentation research |
| `@repo-integration-crawler` | Integration points in repo |
| `@domain-structure-crawler` | Domain structure candidates |

### Researcher Slice (Stage 2 - Research)
| Agent | Role |
|-------|------|
| `@research-deduplicator` | Deduplicates crawler outputs |
| `@research-synthesizer` | Synthesizes research findings |
| `@structure-synthesizer` | Synthesizes domain/integration structures |
| `@evidence-binder` | Maps claims to evidence pointers |
| `@research-coverage-drift-review` | Ensures questions are answered |

### Plan Reviewer Slice (Stage 3)
| Agent | Role |
|-------|------|
| `@plan-structure-reviewer` | Validates plan is executable/ordered |
| `@pattern-plan-review` | Checks pattern completeness |
| `@plan-drift-reviewer` | Ensures plan covers acceptance criteria |

### Implementation Slice (Stages 5, 10, 13)
| Agent | Role |
|-------|------|
| `@implementor` | Executes code implementation |
| `@test-implementor` | Executes test implementation |
| `@verification-runner` | Runs lint + pytest + coverage |

### Patcher Slice (Stages 4, 7, 12)
| Agent | Role |
|-------|------|
| `@plan-patcher` | Patches implementation plan |
| `@code-patcher` | Patches code files |
| `@test-patcher` | Patches test files |

### Drift Reviewer Slice (Stages 6, 11)
| Agent | Role |
|-------|------|
| `@implementation-drift-review` | Compares artifact vs plan |

### Code Artifact Reviewers (Stage 4, 7) - Pattern Vocabulary: CODE-*
| Agent | Pattern Set | Focus |
|-------|-------------|-------|
| `@architecture-review` | CODE-A | Layer compliance, dependency direction |
| `@code-style-review` | CODE-S | Naming, formatting, docstrings |
| `@code-anatomical-review` | CODE-B | Function composition, routing |
| `@code-bug-review` | CODE-E | Exceptions, edge cases, bugs |

### Test Artifact Reviewers (Stage 12) - Pattern Vocabulary: PAT-*
| Agent | Pattern Set | Focus |
|-------|-------------|-------|
| `@test-clarity-review` | PAT-C | Test readability, naming |
| `@test-structure-review` | PAT-A | AAA pattern, single assertion |
| `@test-async-review` | PAT-T | Async patterns, mocking |

### Investigator Slice (Debug & Repair)
| Agent | Role |
|-------|------|
| `@investigator` | Reproduces failure in worktree, fixes |

### Pipeline Oversight (All Stages)
| Agent | Role |
|-------|------|
| `@pipeline-oversight-enforcer` | Verifies receipts, flags deviations |

---

## Sub-Orchestration Summary

| Orchestration | Type | Used In Stages | Purpose |
|---------------|------|----------------|---------|
| Research Orchestration | CREATE | 2 | Crawler swarms + synthesis |
| Plan Integration Orchestration | INTEGRATE | 3, 9 | Topic decomposition + iterative planning |
| Artifact Review Orchestration | REVIEW | 4, 7, 12 | Review loop with patching |
| Debug & Repair Orchestration | REPAIR | 13 (on fail) | Investigator + isolated worktree |
| Process Audit Orchestration | AUDIT | Escalation | Misalignment analysis |

---

## Total Agent Count: 34 unique agents

- **Translators**: 2
- **Planners**: 5
- **Crawlers**: 5
- **Researchers**: 5
- **Plan Reviewers**: 3
- **Implementors**: 3
- **Patchers**: 3
- **Drift Reviewers**: 1 (used twice)
- **Code Reviewers**: 4
- **Test Reviewers**: 3
- **Investigator**: 1
- **Oversight**: 1 (used at every gate)
