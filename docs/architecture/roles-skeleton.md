# The 5-Role Skeleton

The system implements a 5-role skeleton that defines agent responsibilities and workflow
positions. All handoffs between roles are mediated by the orchestrator.

## R1: Strategy Planner

Defines "big phases" using deep research. Reviews R2's detailed plan and performs final
review after R4 passes output. R1 agents are also responsible for updating the Knowledge
Graph when corrections are needed.

## R2: Planner

Breaks phases into discrete tasks. Reviews R3's implementation (diff) before it moves to
R4. Ensures task granularity is appropriate for single-task execution.

## R3: Implementor/Editor

Executes a single task at a time. Performs the actual code changes, documentation updates,
and other implementation work as directed by the plan from R2.

## R4: Quality Reviewer

Performs automated checks (cloud-based, e.g., CodeRabbit) that apply feedback labels.
Feedback is routed by the orchestrator back to appropriate roles for resolution.

## R5: QA & Maintenance

Monitors production metrics (cloud-based) and feeds issues back to R1 via the orchestrator.
Ensures system health and identifies patterns requiring process improvements.
