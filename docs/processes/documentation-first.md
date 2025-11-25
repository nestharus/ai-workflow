# Documentation-First Approach

When an agent makes a mistake, corrections are made by updating the Knowledge Graph
(via R1 agents) rather than editing output directly. This ensures the system learns
and maintains a single source of truth.

## Core Principle

Documentation in `docs/` serves as the authoritative reference for all agent behavior.
When patterns or standards need correction, the documentation is updated first, and
agents then follow the updated documentation.

## Benefits

* **System Learning**: Corrections persist and improve future agent behavior
* **Single Source of Truth**: All agents reference the same authoritative documentation
* **Consistency**: Updated documentation ensures consistent behavior across all agents
* **Traceability**: Changes to standards are tracked in version control

## Process

1. An agent makes a mistake or a pattern needs correction
2. R1 agents identify the relevant documentation file
3. The documentation is updated to clarify or correct the standard
4. All agents follow the updated documentation going forward

## R1 Agent Responsibility

R1 (Strategy Planner) agents are responsible for maintaining the Knowledge Graph. When
corrections are needed, R1 agents update the relevant documentation files rather than
applying ad-hoc fixes to individual agent outputs.
