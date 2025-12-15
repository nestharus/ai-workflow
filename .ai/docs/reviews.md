The Top Layer (The Interface & Collaboration)
The Translator Agent (UI Layer):
Role: The sole interface between the Human and the system.
Responsibilities: Identifies intent, cleans input, organizes thoughts, and asks clarifying questions to resolve initial ambiguity.
Output: Structured intent for the backend agents.
The Goal & Strategy Agents (The Workers):
Role: They perform the actual work of defining the direction.
Collaboration: They work with the Human (via the Translator) to produce the Goal List and Strategy Artifacts.
Workflow: Bidirectional. The AI suggests/guides; the Human directs/confirms.

The Hierarchy of Truth (Strict Separation of Concerns)
Layer 1: Strategy (The Pattern):
Definition: The "What" and the High-Level "How."
Content: Architectural patterns (e.g., "Event-Based"), Design patterns (e.g., "Singleton"), Algorithms, Technology choices.
Layer 2: The Plan (The Wiring):
Definition: Integration of Strategy into the Codebase Structure.
Content: The specific topology. "Where does this piece go?" (e.g., "Inject the Notification Service into the Checkout Function").
Gap Filling: The AI must determine exactly where to wire components when the Strategy is high-level.
Layer 3: The Artifact (The Mechanics/Injection Layer):
Definition: Implementation of the Wiring in syntax.
Content: The nitty-gritty execution. Exceptions, Retries, Unit Logic, Syntax, Conventions (AAA Tests, Variable Naming).
Auto-Integration: These details are injected automatically during the Plan-to-Code translation.

The Filtering System (The Classification Engine)
Mechanism: Every generated item (from initial build to bug fix) passes through three distinct filters.
Filter 1: The Blacklist (Global Known Bad):
Source: Predictive heuristics based on globally known failures.
Content: Anti-patterns, Vulnerabilities, Deprecated methods, Circular dependencies.
Action: Immediate Block.
Filter 2: The Whitelist (High Confidence Laws):
Source: Authoritative Documentation (Language Specs, Library Docs, Internal Golden Standards).
Constraint: Web patterns are not laws. Only strict API documentation qualifies.
Action: Auto-Approve (Silent).
Filter 3: The Risk Profile (The Gray Area):
Definition: Patterns that are neither Known Bad nor Law.
Classification Logic:
Is this a "Good Practice" we simply haven't chosen yet? (Novelty).
Is this a "Bad Practice" that isn't strictly blacklisted? (Risk).
Action: Flag as Suspicious.

Automated Gatekeepers (The Silent Guardians)
Drift Reviewer: Mathematically verifies that the Artifact matches the Plan's intent. (Did we wire it where we said we would?)
Artifact Reviewer: Verifies that injected conventions (AAA, Naming, Style) were applied correctly.
Pipeline Oversight: Scans for AI Laziness. (e.g., Detects "TODO", "Deferred", or placeholders).

The QA Lab (Verification & Reporting)
Separation of Concerns:
Test Generation: Specialized agents create rigorous tests based on the Strategy.
QA Execution: The Lab runs the generated tests against the generated code.
The Investigator Agent (The Fixer):
Trigger: Activated upon test failure.
Protocol: Non-Destructive. It clones the artifact and patches the copy.
Reporting: It does not just fix it. It reports a structured payload back to the Planner:
What Failed: (Root Cause).
How it was Fixed: (The Patch Strategy).

The Feedback Loop (The Universal Flow)
Scope: This loop applies to everything: Initial Builds, Bug Fixes, Conflict Resolutions, Optimizations.
Conflict Resolution:
We do not merge code/git branches.
We merge Strategies and Histories.
Resolution: The Plan is regenerated from the unified Strategy.
Bug Fix Integration:
The Planner receives the Investigator's report.
The Planner integrates the fix into a new Plan.
Crucial Step: The New Plan runs through the Filters again. (A fix can be rejected if it introduces a Blacklisted pattern).

Pattern Classification (The Boundaries)
Strategy Level: Classification of Patterns/Directions (e.g., "Shift to Event-Based").
Plan Level: Classification of Wiring/Topology (e.g., "Wire event trigger to Checkout").
Artifact Level: Classification of Mechanics (e.g., "Use Exponential Backoff," "Use try/catch").

Integration (The Human Role)
The Pivot: We do not "Approve" (binary Yes/No on code). We Integrate (Strategic placement).
The Workflow:
The AI aggregates "Suspicious/Gray Area" patterns.
The AI suggests a Classification (Strategy, Plan, or Artifact).
The Human reviews the Classified Pattern.
The Targets:
Target: Strategy: Updates the Strategy Document (e.g., "We now officially use Redis").
Target: Plan: Updates Plan Heuristics (e.g., "Always wire events this way").
Target: Artifact: Updates Artifact Heuristics (e.g., "Always use this Retry logic").
Approval Logic:
Strategy Integration: Must be approved every single time. Never automated.
Plan/Artifact Integration: Once approved, added to automation whitelist/heuristics for future auto-approval.

The Core Metaphor
The Printer: Code is the printout. Strategy/Plan is the document.
The Rule: You never debug the printout with a pen. You update the document and reprint.