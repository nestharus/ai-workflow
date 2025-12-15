## Workflow Overview

```
┌─────────────────┐
│  PR Comments    │
│  or Feature Req │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Research Phase │ ◄── Web + Codebase Research
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Implementation  │ ◄── Write to .tmp/implementation-plan.md
│     Plan        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Architecture   │ ◄── @architecture-review
│    Review       │     Updates plan in-place
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
  PASS      FAIL ───► Update plan, re-review
    │
    ▼
┌─────────────────┐
│  Code Style     │ ◄── @code-style-review
│    Review       │     Updates plan in-place
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
  PASS      FAIL ───► Update plan, re-review
    │
    ▼
┌─────────────────┐
│  Implementation │ ◄── Execute CODE ONLY step-by-step
│    Execution    │     (NO tests yet)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Drift Review   │ ◄── @implementation-drift-review (GPT 5.1)
│  (Code)         │     Compare code to implementation plan
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
  PASS      FAIL ───► Fix drift, re-review
    │
    ▼
╔═══════════════════════════════════════════════════╗
║           CODE REVIEW LOOP                        ║
║  All reviews must PASS before proceeding to tests ║
╚═══════════════════════════════════════════════════╝
         │
         ▼
┌─────────────────┐
│  Anatomical     │ ◄── @code-anatomical-review
│  Review (Code)  │     Function composition, routing, boolean avoidance
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
  PASS      FAIL ───► Refactor code, re-review ALL code reviews
    │
    ▼
┌─────────────────┐
│  Bug Review     │ ◄── @code-bug-review
│  (Code)         │     Exceptions, edge cases, subtle misses
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
  PASS      FAIL ───► Fix bugs, re-review ALL code reviews
    │
    ▼
╔═══════════════════════════════════════════════════╗
║         CODE REVIEWS COMPLETE                      ║
║  Now proceed to test planning                      ║
╚═══════════════════════════════════════════════════╝
         │
         ▼
┌─────────────────┐
│ Testing Strategy│ ◄── @testing-strategy
│                 │     Identifies use-cases, components, codepaths
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Test Impl.     │ ◄── @test-implementation-planner
│    Planner      │     Defines assertions, patterns, fixtures
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Test           │ ◄── Execute tests step-by-step
│  Implementation │     Following test implementation plan
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Drift Review   │ ◄── @implementation-drift-review (GPT 5.1)
│  (Tests)        │     Compare tests to test plan
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
  PASS      FAIL ───► Fix drift, re-review
    │
    ▼
╔═══════════════════════════════════════════════════╗
║           TEST REVIEW LOOP                         ║
║  All reviews must PASS (run in parallel)           ║
╚═══════════════════════════════════════════════════╝
         │
    ┌────┴────┬─────────────┐
    │         │             │
    ▼         ▼             ▼
┌────────┐ ┌────────┐ ┌────────┐
│Clarity │ │Structure│ │ Async  │ ◄── Run in PARALLEL
│ Review │ │ Review │ │ Review │
└────┬───┘ └───┬────┘ └───┬────┘
     │         │          │
     └────┬────┴──────────┘
          │
    ┌─────┴─────┐
    │           │
  ALL PASS    ANY FAIL ───► Fix tests, re-review ALL test reviews
    │
    ▼
┌─────────────────┐
│  Lint & Test    │ ◄── uv run lint && uv run pytest
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
  PASS      FAIL
    │         │
    ▼         ▼
┌───────┐ ┌─────────────────┐
│ Done! │ │ Error Investigator│ ◄── @error-investigator
└───────┘ └────────┬────────┘
                   │
                   ▼
          ┌─────────────────┐
          │  Debug Worktree │ ◄── Create from current, fix, compare
          └────────┬────────┘
                   │
                   ▼
          ╔════════════════════════════════════════╗
          ║    FIX VALIDATION LOOP                 ║
          ║  All reviews must PASS                 ║
          ╚════════════════════════════════════════╝
                   │
          ┌────────┼────────┐
          │        │        │
          ▼        ▼        ▼
       ┌──────┐ ┌──────┐ ┌──────┐
       │Arch  │ │Style │ │Anatom│ ◄── Sequential
       │Review│ │Review│ │Review│
       └──┬───┘ └──┬───┘ └──┬───┘
          │        │        │
          └────┬───┴────────┘
               │
          ┌────┴────┐
          │         │
        PASS      FAIL ───► Loop to Debug Worktree
          │
          ▼
       ┌──────┐
       │ Bug  │ ◄── @code-bug-review
       │Review│
       └──┬───┘
          │
     ┌────┴────┐
     │         │
   PASS      FAIL ───► Loop to Debug Worktree
     │
     ▼
┌────────────────────────────┐
│ Test Reviews (Parallel)    │ ◄── @test-clarity, @test-structure, @test-async
└────────────┬───────────────┘
             │
        ┌────┴────┐
        │         │
    ALL PASS   ANY FAIL ───► Loop to Debug Worktree
        │
        ▼
┌─────────────────┐
│  Merge Fix      │
└─────────────────┘
```