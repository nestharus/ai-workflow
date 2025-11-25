# Inter-Domain Handoffs

Handoffs between domains are automated via orchestrator message routing based on workflow
definitions. Agents do not need to manage handoffs manually.

## Handoff Chains

* **Product R1** -> **UX R1**
* **UX R1** -> **Technical R1**

## Automation Mechanism

The orchestrator routes messages based on workflow definitions that specify:

* Which domain should receive work after another domain completes
* What context and artifacts should be passed along
* When a handoff should occur based on workflow state

## Agent Responsibilities

Agents focus on completing their assigned tasks within their domain. When their work is
complete, they submit a result message to the orchestrator, which handles routing to the
next domain automatically.
