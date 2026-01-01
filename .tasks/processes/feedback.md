You first start with your requirements.
What is it precisely that you want to do?
What do you want to achieve?

This is your requirements document

Then you go into algorithms

How do you achieve what you want to achieve?
You just have a list of algorithms that are essentially functions
Mimimal organization
Just functions

You refine your algorithms with Gemini
```
You are an expert algorithmic auditor for an autonomous, self-healing software agent system. Your task is to review the provided flowchart for logical defects, race conditions, and constraint violations. You are also to review the logic for algorithmic improvements. You are to provide feedback on how to fix and improve the algorithms.

CRITICAL CONSTRAINTS (DO NOT VIOLATE):

NO MANUAL INTERVENTION: The system is fully autonomous. Never suggest or allow a "Manual Intervention" step.

NO MAX RETRIES: Do not introduce counters or hard limits on loops. Infinite loops are intended and correct behavior as long as the file is being modified ("ping-ponging" between actors).

NO HARD STOPS: The workflow never exits while errors exist, unless a specific file is deemed "Unlintable."

REQUIRED LOGIC & STATE TRANSITIONS: Adhere to these specific truths when analyzing the flow:

Agent Success: If the Agent runs and modifies the file, it keeps ownership. It must retry (re-lint) immediately.

Agent Stall (Investigator Trigger): The only condition to move a file to the Investigator is: The Agent ran, errors persist, AND the file content hash did not change.

Investigator Success: If the Investigator runs and modifies the file, it releases the file back to the Agent (or general pool) for the next pass.

Investigator Failure (NO_OP): If the Investigator runs and returns NO_OP (no changes), the file is "Unlintable". It must be ejected from the workflow entirely (returned to orchestrator for debugging). Do not retry. Do not loop.

Async State: The Investigator runs asynchronously. The main loop must handle "waiting" states without blocking the processing of other files.

YOUR TASK: Analyze the algorithm provided below. Output a strict "Feedback List" of errors where the flowchart violates the constraints or logic above. Specifically look for:

Any instance of MAX_RETRIES or retry counters.

Any logic that exits to "Manual Intervention."

Any logic that incorrectly triggers the Investigator (e.g., sending changed files to Investigator instead of retrying Agent).

Any logic that incorrectly handles Agent Stalls (e.g., failing instead of escalating).
```
You patch them in with ChatGPT

This system continues to grow until it gets too large. At this point
you can begin to recognize structure and components.

Bottom up of your process doesn't necessarily work because your
algorithms can be spliced by yhour design paradigm.

You define your design paradigm. You use Opus for this.

Example algorithm to search for design paradigms
```
I have an algorithm. I would like to start splitting the algorithm up into pieces that are loosely coupled
to further optimize the algoirthm and find bugs. Right now the algorithm is growing too complex so I need to
break it down. Let's identify some large pieces here to try and isolate components of the algorithm without
breaking anything. You're going to try various candidate large bucket solutions to determine how the
algorithm splits up. You can store candidates in ".tasks/plans/parallel linter/linter algorithm candidates".
You can
use sub-agents to try out ideas and explore potential patterns given existing ideas.

.tasks/plans/parallel linter/linter algorithm.md
```

Next you use ChatGPT to analyze and select from your design paradigms for a final paradigm

First create a prompt with Opus
```
I will be passing this to an analyzer to determine risks and select a final solution from your summary and
  analysis. I need a prompt for it to output its solution and understand the candidates, summary, etc.```
```


Then pass it to chatgpt xhigh with candidates, summary, and algorithm file
```
# Linter Algorithm Decomposition Analysis

You are analyzing a complex parallel linter algorithm to select the best decomposition strategy for reducing coupling, improving testability, and enabling incremental optimization.

## Input Files

1. **linter algorithm.md** - The complete algorithm specification as a Mermaid flowchart with detailed annotations
2. **linter algorithm candidates/** - A folder containing:
    - `README.md` - Summary comparison of all candidates
    - `candidate-1-data-flow-pipeline.md` - Pipeline decomposition (11 stages)
    - `candidate-2-domain-driven.md` - Domain decomposition (5 domains)
    - `candidate-3-layered.md` - Layered architecture (5 layers)
    - `candidate-4-state-machine.md` - State machine decomposition (6 states)
    - `candidate-5-process-centric.md` - Process-centric decomposition (5 concerns)
    - `cross-cutting-concerns.md` - Shared abstractions needed across all approaches

## Your Task

Analyze all candidates and produce a final recommendation. Your analysis must include:

### 1. Risk Assessment

For each candidate, evaluate:
- **Implementation Risk** - How likely is the refactoring to introduce bugs?
- **Scope Creep Risk** - How likely is this to expand beyond initial boundaries?
- **Integration Risk** - How difficult is it to integrate extracted components?
- **Regression Risk** - How likely are existing behaviors to break?
- **Complexity Risk** - Does this add more complexity than it removes?

### 2. Trade-off Analysis

Compare candidates on:
- Testability improvements vs. abstraction overhead
- Isolation benefits vs. interface proliferation
- Platform abstraction vs. performance impact
- Explicit control flow vs. code verbosity

### 3. Critical Path Identification

Identify which parts of the algorithm are:
- Most error-prone and would benefit most from isolation
- Most tightly coupled and hardest to extract
- Most likely to change in the future
- Most critical for correctness (e.g., snapshot restoration, shutdown coordination)

### 4. Final Recommendation

Provide:
- **Selected Strategy** - Which candidate (or hybrid) to pursue
- **Rationale** - Why this choice minimizes risk while maximizing benefit
- **First Extraction Target** - Which component to extract first
- **Extraction Order** - Sequence for subsequent extractions
- **Success Criteria** - How to verify the decomposition succeeded
- **Rollback Plan** - How to recover if extraction causes problems

## Output Format

Structure your response as:

Risk Assessment Summary

[Table of candidates vs. risk categories: Low/Medium/High]

Critical Coupling Points

[List of tightest couplings that require careful handling]

Recommendation

Selected Strategy: [Name]

Rationale: [Why]

Extraction Plan:

1. [First component] - [Why first]
2. [Second component] - [Dependencies on first]
3. ...

Success Criteria:

- Criterion 1
- Criterion 2
  ...

Risks to Monitor:


## Context

The goal is to break down a growing, complex algorithm into loosely coupled pieces to:
1. Find bugs more easily through isolation
2. Optimize individual components independently
3. Test components in isolation
4. Reduce cognitive load when making changes

The algorithm manages parallel linter execution with:
- Multiple file discovery modes (git-based)
- Linter scheduling with resource conflict detection
- Mutating vs. read-only linter phases
- Process tree management (POSIX/Windows)
- Snapshot/restore for crash recovery
- Fail-fast and SIGINT handling
- Ordered output buffering
- ARG_MAX chunking

Prioritize **safety and incremental progress** over ambitious restructuring.
```

next, pass selected paradigm to chatgpt xhigh to reorganize algorithm to fill
out paradigm

```
I have a file .tasks/plans/parallel linter/lint dispatcher/everything.md
    I need this file to be diced up into component files. Then we need a plan organized by dependencies (which
    component files to implement and when).

    Thjis is the plan document template
    .tasks/processes/plan.md

    This is the design map structure template (we are currently missing contracts)
    .tasks/processes/design map structure.md
```


This will NOT decompose your problem into every required layer
This will simply reorganize your algorithm into the "large" system
Various components can be further decomposed into smaller subsystems
This decomposition can happen down to the functional level
We do large systems and then we refine the algorithms again.

As we need to decompose one component we go to opus and rerun algorithm
to create subsystems out of that component

We continue to refine algorithms and decompose until there is nothing left
to refine or decompose.



The limit of complexity for Gemini to handle is 200 lines of pure algorithms
At 200 lines there should be enough information to decompose the system with Opus

This is an iterative process


At each iteration you continue to fill out the plan as new surfaces emerge
The plan is for transparency
Don't actually need the plan. Can do the plan last.
However, the plan allows a user to see where the AI is going as it decomposes.

You still have one *master* algorithm, it is just filled with substitutions
The algorithm is slotted into a paradigm
Components can be ripped out and remade from the paradigm to redefine the algorithm


This feedback applies to our templates (our planning is completely different now)
.tasks/processes/design map structure.md
.tasks/processes/plan.md
.tasks/processes/prd structure.md
.tasks/processes/adr/ADR-000-template.md

This feedback also applies to our algorithms
.tasks/plans/prd planner mvp
.tasks/plans/prd planner
.tasks/plans/implementation planner