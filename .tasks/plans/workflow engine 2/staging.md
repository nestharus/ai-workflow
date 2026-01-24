We ALWAYS avoid max iterations. I must note. This project is run locally on a user's machine. it is not a distribute system or a cloud process. it is only on a local user machine. The db files are not committed. The philosophy should be embedded in the specs so that you understand which tradeoffs you are going for. One thing that would be ideal is finding technologies that can suit our needs rather than implementing everything from scratch ourselves. Technologies that provide all of the features we are looking for without large footprints (servers, etc). We need to reduce friction as much as we can. The current implementation can easily be embedded into an application later and just work without any servers or heavy configuration. This isn't a software as a service ;).

---

Project Manager Workspace Scope
The project-manager command creates a workspace that accepts documentation and tickets. What is the primary source of this documentation?

Epic artifacts: Documentation comes from Traycer Epic specs/tickets (the current Epic mode we're in)
External files: User provides markdown files, PRDs, or other documents from their filesystem
Linear projects: Documentation is pulled from Linear project descriptions and attachments
Mixed sources: Combination of Epic artifacts, external files, and Linear data
A. Epic artifacts from Traycer

B. External files from filesystem

C. Linear projects and issues

D. Mixed sources (all of the above)

Worktree Hierarchy Structure
You mentioned that the project manager runs on its own worktree, and ticket managers run on worktrees based on the project manager's worktree. How should this hierarchy be structured?

Nested worktrees: Ticket worktrees are subdirectories within the project manager worktree
Sibling worktrees: All worktrees are siblings in .worktrees/, but ticket worktrees branch from project manager's branch
Separate locations: Project manager worktree in one location, ticket worktrees in another (e.g., .worktrees/project/ vs .worktrees/tickets/)
A. Nested worktrees (tickets inside project worktree)

B. Sibling worktrees (all in .worktrees/, branching relationship)

C. Separate locations (different parent directories)

Task Breakdown Mechanism
When a user passes a COMPLETE task with all steps to the ticket manager, how should the task be broken down into steps?

AI-driven decomposition: An agent analyzes the task and intelligently breaks it into logical steps
User-defined markers: User explicitly marks step boundaries in their task description (e.g., "Step 1:", "Step 2:")
Dependency analysis: System analyzes code dependencies and creates steps based on what needs to be implemented first
Hybrid approach: Combination of user hints and AI analysis
A. AI-driven decomposition (agent decides)

B. User-defined markers (explicit step boundaries)

C. Dependency analysis (code-based)

D. Hybrid approach (user hints + AI)

Step Context Preservation
You mentioned "These steps require context from prior steps" and "When an agent executes a step it runs git diffs to grab deltas from prior steps." How should this context be captured and passed between steps?

Git diffs only: Each step receives git diffs from all previous steps in the task
Execution summaries: Each step produces a summary that's passed to the next step along with diffs
Shared state file: Steps read/write to a shared JSON state file tracking progress and decisions
Full commit history: Each step has access to all previous commits with messages and diffs
A. Git diffs only

B. Execution summaries + diffs

C. Shared state file (JSON)

D. Full commit history

Evaluation Worktree Purpose
You mentioned creating an "evaluation worktree" that squashes all ticket commits into one big commit for final review. When should this evaluation worktree be created?

Per ticket: Created when a ticket is closed to review that ticket's work
Per project: Created once for the entire project to review all tickets together
On demand: User explicitly requests evaluation worktree creation at any time
Continuous: Maintained throughout the project, updated after each ticket
A. Per ticket (on ticket closure)

B. Per project (all tickets together)

C. On demand (user-triggered)

D. Continuous (updated after each ticket)

Linear Integration Scope
You mentioned storing specifications and tickets in Linear as project resources. What should be stored in Linear?

Final artifacts only: Only store the final specs/tickets after project completion
Progressive updates: Update Linear throughout the project as specs/tickets evolve
Commit-linked: Each commit references a Linear project with associated specs/tickets
Bidirectional sync: Changes in Linear sync back to local workspace and vice versa
A. Final artifacts only (at completion)

B. Progressive updates (throughout project)

C. Commit-linked (each commit has Linear reference)

D. Bidirectional sync (Linear ↔ workspace)

Enhanced Rebase Conflict Resolution
The enhanced rebase command should investigate conflicts between projects using git blame and project documentation. What level of automation should this have?

Fully automated: System automatically resolves conflicts based on project analysis
Recommendation engine: System provides recommendations, user makes final decision
Investigation only: System surfaces findings and tradeoffs, user resolves manually
Escalation-based: Attempts auto-resolution, escalates complex cases to user
A. Fully automated resolution

B. Recommendation engine (user decides)

C. Investigation only (user resolves)

D. Escalation-based (auto with fallback)

Ticket Scheduling and Parallelization
You mentioned that the project manager can schedule tickets and determine if some can run in parallel. How should parallel ticket execution work?

Independent worktrees: Multiple ticket worktrees can be worked on simultaneously by different agents
Sequential with planning: System identifies parallelizable tickets but executes them one at a time
User-controlled: User manually decides which tickets to work on in parallel
Dependency-based: System creates a dependency graph and executes tickets as dependencies are met
A. Independent worktrees (true parallelism)

B. Sequential with planning (identified but not executed in parallel)

C. User-controlled parallelization

D. Dependency-based execution

Agent Persistence Model
You mentioned "the agent stays active to manage that workspace" for the project manager. What does "stays active" mean in this context?

Long-running process: Agent runs as a persistent process/service that accepts commands
Session-based: Agent maintains state across multiple user interactions in a session
Stateful commands: Each command invocation loads previous state, executes, saves state
Workspace context: Agent is invoked fresh each time but operates within a persistent workspace directory
A. Long-running process/service

B. Session-based (multi-turn conversation)

C. Stateful commands (load/save state)

D. Workspace context (fresh invocation, persistent workspace)

Reconciliation Plan Creation
When rebase discovers conflicts that cannot be merged (e.g., two different implementations), you mentioned "a new plan can be created to reconcile." How should this reconciliation plan be created?

Back to Epic mode: System returns to Traycer Epic mode to create a new spec/plan
Inline planning: Rebase command itself creates a reconciliation plan document
Manual intervention: System surfaces the conflict, user creates plan manually
Automated proposal: System generates reconciliation options, user selects one
A. Back to Epic mode (new spec)

B. Inline planning (rebase creates plan)

C. Manual intervention (user creates plan)

D. Automated proposal (system generates options)

These questions will help me understand the architectural decisions, integration points, and workflow patterns you envision. Your answers will guide the creation of detailed specifications for the project-manager command, ticket-manager command, and enhanced rebase functionality.

---

1. A. Unless it can query traycer somehow I don't think that it cares. They'd have to go in as prompts because I don't think that there is any integration. They have to be manually loaded in.
2. B
3. The steps are numbered but AI will have to determine those numbers to decompose it. I don't think that they can be parsed.
4. A. They also need summaries of previous steps to understand what the git diffs mean. Previous steps state what to do. They need to know what was delivered and how it relates to them. We'll need a context agent for this using the glm model per .agents
5. Per final review. The final review can point out mistakes. The user would then create a new ticket given the gaps. We'd then have a new commit with that ticket. We'd then create a new evaluation to review.  The commits we are merging in are the ticket commits. This also means that we need to associate each ticket commit (in the commit message likely) with our overall project. We don't reference linear. Just the project. We could store it anywhere. It happens to be Linear right now.
6. There are specs. Then there are tickets. Then there are tasks. We want to store all of this. So we need to persist our tasks too. We already persist our tickets and our specs. We do it at completion.
7. Escalation. I specifically pointed out that some things require new tickets. It will surface those things so that the user can feed new tickets to the project manager.
8. Dependency-based *AND* independent worktrees. We already do things in independent worktrees for tickets. Our parallel execution needs to understand dependencies between tickets. Tickets can't be done until other tickets are done because things may not exist or they may be editing the same things.
9. Stay active just means a terminal an interactive terminal will be open. That's it. The user opens it and the agent is designed to continue to receive user input and work with the user rather than just execute a task. We need to be able to reopen projects too so the project manager may be opened in passive mode where it needs to look across all open projects and let the user open one of them. By default it opens in passive mode. It can ask "would you like to start a new project or reopen an existing one?" etc.
10. The system is NOT integrated with Traycer. It surfaces issues. The user has to take those issues to Traycer. That process is not in scope of the system. THat's up to the user. Then the user can go to the project manager with a new ticket. Etc. Then they can run next final review and then try to rebase it again. This will also involve removing all of the attached files on the project item in linear and attaching the new files (plans may have been changed). We technically do not need to remove tickets. We just need to remove plans.

---

Project Manager Workspace Structure
When the project-manager command creates a workspace, what should be stored in this workspace?

Workspace directory structure: A .tmp/project-{name}/ directory containing specs, tickets, tasks, and state files
Worktree with workspace: A git worktree (.worktrees/project-{name}/) with a .tmp/ subdirectory for workspace data
Database-backed: State stored in workflow.db with files in a workspace directory
Hybrid: Worktree for code changes + separate workspace directory for project metadata
A. Workspace directory only (.tmp/project-{name}/)

B. Worktree with embedded workspace

C. Database-backed (workflow.db)

D. Hybrid (worktree + separate workspace)

Task Persistence Format
You mentioned we need to persist tasks (in addition to specs and tickets). What format should tasks be stored in?

Markdown files: Each task as a separate .md file with metadata header
JSON files: Structured JSON with task steps, context, and execution state
Git commit messages: Tasks embedded in commit messages with special formatting
Database records: Tasks stored in workflow.db with relationships to tickets
A. Markdown files (.md)

B. JSON files (.json)

C. Git commit messages

D. Database records (workflow.db)

Context Agent Integration
You mentioned using a context agent with the GLM model (per .agents) to provide summaries of previous steps. How should this context agent be invoked?

Per-step invocation: Called before each step execution to summarize all prior steps
On-demand: Only called when a step explicitly needs context from previous steps
Continuous: Maintains running summary that's updated after each step completes
Batch mode: Called once at task start to analyze all steps and create context plan
A. Per-step invocation (before each step)

B. On-demand (when needed)

C. Continuous (running summary)

D. Batch mode (upfront analysis)

Ticket Commit Association
You mentioned associating each ticket commit with the overall project (in the commit message). What format should this association take?

Commit message prefix: [PROJECT-{id}] [TICKET-{id}] commit message
Commit message footer: Standard commit message with Project: {id} and Ticket: {id} footers
Git notes: Use git notes to attach project/ticket metadata to commits
Commit message body: Include project/ticket info in structured format in commit body
A. Commit message prefix ([PROJECT-{id}] [TICKET-{id}])

B. Commit message footer (Project: {id}, Ticket: {id})

C. Git notes (separate metadata)

D. Commit message body (structured format)

Project Reopening Mechanism
When project-manager opens in passive mode and lists existing projects, where should it look for these projects?

Worktrees directory: Scan .worktrees/ for project worktrees
Workspace directory: Scan .tmp/ for project workspace directories
Database query: Query workflow.db for active projects
Git branches: Look for branches with project naming convention
A. Worktrees directory (.worktrees/)

B. Workspace directory (.tmp/)

C. Database query (workflow.db)

D. Git branches (naming convention)

Ticket Manager Invocation
When the project manager tells the user to open a ticket manager, what command format should be used?

Direct command: /ticket-manager --project {project-id} --ticket {ticket-id}
Contextual command: User is already in project context, just /ticket-manager {ticket-id}
Interactive selection: /ticket-manager opens interactive menu to select project and ticket
Workspace-based: /ticket-manager --workspace {project-workspace-path} --ticket {ticket-id}
A. Direct command (--project and --ticket flags)

B. Contextual command (project context implied)

C. Interactive selection (menu-driven)

D. Workspace-based (--workspace flag)

Dependency Graph Representation
For dependency-based ticket execution, how should ticket dependencies be defined?

Manual specification: User explicitly declares dependencies when creating tickets
AI-inferred: System analyzes ticket descriptions to infer dependencies
File-based: System analyzes which files each ticket will modify to detect conflicts
Hybrid: User provides hints, system validates and suggests additional dependencies
A. Manual specification (user declares)

B. AI-inferred (from descriptions)

C. File-based (conflict detection)

D. Hybrid (user hints + AI validation)

Final Review Workflow
When the evaluation worktree is created for final review, what happens after the review identifies gaps?

Automatic ticket creation: System creates new tickets based on review findings
User creates tickets: Review outputs findings, user manually creates tickets in project manager
Interactive refinement: Review agent works with user to define new tickets
Gap report only: Review produces a report, user decides how to address gaps
A. Automatic ticket creation

B. User creates tickets manually

C. Interactive refinement (agent + user)

D. Gap report only (user decides)

Linear Attachment Management
You mentioned removing and re-attaching plan files on Linear project items. What should be attached to Linear?

Specs only: Only specification documents (plans)
Specs and tickets: Both specification and ticket documents
Full project state: Specs, tickets, tasks, and execution summaries
Specs and evaluation: Specification documents plus final evaluation report
A. Specs only (plans)

B. Specs and tickets

C. Full project state (specs, tickets, tasks, summaries)

D. Specs and evaluation report

Rebase Investigation Scope
When the enhanced rebase command investigates conflicts using git blame and project documentation, what documentation should it access?

Linear attachments: Fetch specs/tickets from Linear project items
Local workspace: Read from project workspace directory (specs, tickets, tasks)
Git history: Extract project metadata from commit messages and history
Hybrid: Check local workspace first, fall back to Linear if needed
A. Linear attachments (remote)

B. Local workspace (specs, tickets, tasks)

C. Git history (commit metadata)

D. Hybrid (local first, Linear fallback)

These questions focus on the concrete implementation details: data structures, file formats, command interfaces, and integration points. Your answers will help me define the exact specifications for each component of the system.

---

1. B
2. A. These will be stored in our project on linear at the end. One markdown file per task. We show the overall hierarchy in the project description in linear.
3. C. It looks at what the next step needs and refines prior summary with new additions and then removals of things next step may not care about. There may be deviations due to reviews. Some things may have been labeled differently. The context manager will need to look into the commits to understand everything that happened. These deviations also need to be reported alongside the task. So this context manager will be managing the context of the overall task (what gets reported at the end) and the context of individual steps (what gets reported to each step). Our review agent uses the task plan + deviations. Our ticket review agent also needs access to deviations to understand how things changed. This can also help the review agents understand why deviations were introduced rather than just saying NOT PART OF THE PLAN. These deviations also need to be surfaced to the final review agent that reviews the final implementation against planning docs. Our review agents tend to be chat gpt 5.2 xhigh.
4. A
5. worktrees for open projects. We'll need a python script to detect worktrees that have projects in them and determine if they are open or not.
6. Direct command. The user should be able to copy and paste to immediately get to where it needs to go. A ticket is not necessarily opened from scratch. It can be resumed. The worktrees would need to be checked for the ticket (python script) to determine if this is a fresh ticket or a resumed one.
7. B
8. D. The user would use the gap report to create the tickets and then go to the project manager to add them in. Ultimately the system doesn't care what the user does. They just need that report. We don't need an opinion that user must go to the project manager.
9. specs, tickets, tasks, and deviations
10. It relies on git history to get linear attachments. So this is a multi-way rebase. It has its OWN attachments for its OWN commit. The conflict has another commit that it is conflicting with though that has ITS own attachments. It needs both. On top of that it also need to produce a report attached to BOTH projects on conflict resolutions. Why? Conflicts can have additional consequences that are not necessarily in the scope of EITHER report. Like weaving things together. Another rebase can see that new state and have no idea why it is there because it is not part of the project it is looking at. We need a conflict resolution that it can find to figure out where stuff came from and then it can use that to look at the other project. We'd just have a list of conflict resolutions tied to the commit. We need this to pass projects through. We don't need this when we pick one or the other. We also don't need this when we have them side by side. We can trace git history further back to see the older lines. It's when we change the state of the lines that we need this. Any time we lose our ability to trace where something came from we need a conflict resolution file.

---

Project Manager (project-manager command)
Creates a git worktree with embedded workspace (.worktrees/project-{name}/ with .tmp/ subdirectory)
Operates in two modes:
Passive mode (default): Scans .worktrees/ for existing projects, lets user select to open or create new
Active mode: Interactive terminal session where user feeds documentation, specs, tickets, and tasks
Manages ticket ordering and dependency-based scheduling
Provides commands to open ticket managers with full context
Persists state throughout the session
2. Ticket Manager (ticket-manager command)
Invoked via: /ticket-manager --project {project-id} --ticket {ticket-id}
Creates worktree branching from project manager's worktree (sibling structure in .worktrees/)
Detects if ticket is fresh or resumed (via Python script checking worktrees)
Accepts complete tasks from user and breaks them into AI-determined steps
Context Manager (GLM model):
Maintains continuous running summary updated after each step
Provides step-specific context (what next step needs to know)
Tracks deviations from plan (different naming, implementation changes)
Reports deviations alongside task completion for review agents
Each step:
Receives git diffs from prior steps + context summary
Executes implementation
Creates individual commit
Updates context manager with results and deviations
After all steps: Squashes all step commits into single task commit
Runs implementation review (existing review-implementation.md workflow) with task plan + deviations
User can provide feedback → triggers update-pr.md workflow
On ticket closure:
Squashes all task commits into single ticket commit
Commit message format: [PROJECT-{id}] [TICKET-{id}] commit message
Runs ticket review against ticket requirements + deviations
Executes rebase.md workflow
Executes merge.md workflow
3. Enhanced Rebase (modifications to existing rebase.md)
No longer looks at Linear tickets directly
Looks at projects tied to commits (via commit message metadata)
On conflict:
Uses git blame to identify conflicting commits
Extracts project IDs from both commits
Fetches Linear attachments (specs, tickets, tasks, deviations) for BOTH projects via git history
Uses sub-agents to investigate conflicts
Determines dependencies and consequences
Escalation-based resolution:
Auto-resolves when possible
Surfaces issues requiring new tickets (user creates tickets in Traycer, adds to project manager)
Creates conflict resolution files when state changes lose traceability
Attached to BOTH Linear projects
Documents why lines were changed/merged (not just picked one side or kept side-by-side)
Enables future rebases to understand merged state origins
Produces comprehensive report of findings
4. Final Review & Evaluation
Creates evaluation worktree that squashes all ticket commits into one commit
Runs implementation review against all planning docs (specs, tickets, tasks)
Review agent (GPT-5.2 xhigh) receives deviations to understand why changes occurred
Produces gap report
User uses gap report to create new tickets in Traycer → feeds to project manager
New tickets create new commits
Process repeats: new evaluation → review → potential new tickets
5. Linear Integration
At project completion: Store to Linear project as attachments
Specs (markdown files)
Tickets (markdown files)
Tasks (markdown files, one per task)
Deviations (tracked throughout execution)
Conflict resolutions (when applicable)
Project description in Linear shows hierarchy/index
On updates: Remove old plan attachments, attach new ones (tickets/tasks/deviations remain)
6. Data Persistence
Tasks: Markdown files (.md), one per task
Worktree detection: Python script scans .worktrees/ for project worktrees
Ticket resumption: Python script checks if ticket worktree exists
Dependency graph: AI-inferred from ticket descriptions
Context: Continuous summary maintained by GLM-based context manager
Key Technical Details
Models:
Context Manager: GLM (claude-glm command)
Review Agents: GPT-5.2 xhigh (opencode run -m openai/gpt-5.2 --variant xhigh)
Worktree Structure: Sibling worktrees in .worktrees/, branching relationships maintained
Commit Association: [PROJECT-{id}] [TICKET-{id}] prefix in commit messages
Deviations: Tracked by context manager, reported to all review agents
Conflict Resolutions: Created when merging changes lose git history traceability
Requirements Confirmed ✓
All ambiguities have been resolved. The system is well-defined and ready for specification.

---

Project Manager Entry Point
When a user invokes the project-manager command, what should the initial interaction look like?

Immediate prompt: Opens directly into an interactive prompt asking "New project or reopen existing?"
List-first: Shows a list of existing projects (if any) with options to select one or create new
Command-driven: User specifies intent via flags (e.g., /project-manager --new or /project-manager --open {id})
Smart detection: If no projects exist, creates new; if projects exist, shows selection menu
A. Immediate prompt (always asks)

B. List-first (shows existing projects)

C. Command-driven (flags specify intent)

D. Smart detection (context-aware)

Feeding Documentation to Project Manager
Once the project manager is active, how does the user provide specs, tickets, and tasks?

Paste directly: User pastes markdown content directly into the terminal, agent parses and categorizes
File paths: User provides file paths (e.g., "load spec from /path/to/spec.md"), agent reads and imports
Structured commands: User uses commands like "add-spec", "add-ticket", "add-task" with content
Mixed mode: User can paste content OR provide file paths, agent handles both
A. Paste directly (inline content)

B. File paths (agent reads files)

C. Structured commands (add-spec, add-ticket, etc.)

D. Mixed mode (paste or file paths)

Ticket Ordering and Dependency Visualization
When the project manager determines ticket ordering and dependencies, how should this be communicated to the user?

Text list: Simple numbered list showing execution order (e.g., "1. Ticket A, 2. Ticket B, 3. Ticket C")
Dependency tree: ASCII tree showing parent-child relationships and which tickets can run in parallel
Interactive selection: User sees tickets and manually confirms/adjusts the proposed order
Automatic with summary: Agent decides order, shows brief summary (e.g., "3 tickets, 2 can run in parallel")
A. Text list (numbered order)

B. Dependency tree (ASCII visualization)

C. Interactive selection (user confirms)

D. Automatic with summary

Ticket Manager Task Input
When the user opens a ticket manager and provides a complete task, how should they format it?

Free-form text: User describes the task naturally, AI decomposes it into steps
Markdown with hints: User writes markdown with optional step hints (e.g., "## Step 1: ..."), AI refines
Structured format: User must follow a specific format (e.g., YAML or JSON with step definitions)
Conversational: User describes task, agent asks clarifying questions, then decomposes
A. Free-form text (natural language)

B. Markdown with hints (optional structure)

C. Structured format (YAML/JSON)

D. Conversational (agent asks questions)

Step Execution Visibility
As the ticket manager executes steps, what feedback should the user see?

Silent execution: Steps run in background, user only sees final summary
Progress indicators: Shows "Executing step 2/5..." with brief status updates
Detailed logs: Shows full output from each step (git diffs, context summaries, implementation details)
Milestone notifications: Only notifies when major events occur (step complete, deviation detected, review triggered)
A. Silent execution (summary only)

B. Progress indicators (status updates)

C. Detailed logs (full output)

D. Milestone notifications (key events)

Deviation Reporting
When the context manager detects deviations from the plan, how should these be surfaced to the user?

Real-time alerts: User is notified immediately when a deviation is detected during step execution
Step summary: Deviations are listed at the end of each step's execution
Task summary: All deviations are collected and shown when the task completes
On-demand: Deviations are tracked silently, user can query them with a command (e.g., "show deviations")
A. Real-time alerts (immediate notification)

B. Step summary (end of each step)

C. Task summary (end of task)

D. On-demand (query with command)

User Feedback Loop in Ticket Manager
After a task completes and implementation review runs, how does the user provide feedback?

Inline comments: User provides feedback as text, ticket manager triggers update-pr workflow
Structured feedback: User uses commands like "fix-issue" or "revise-step" with specific instructions
Review file: User edits a generated review file, ticket manager processes changes
Conversational: User describes issues naturally, agent interprets and applies fixes
A. Inline comments (text feedback)

B. Structured feedback (commands)

C. Review file (edit and process)

D. Conversational (natural language)

Ticket Closure Confirmation
When the user decides to close a ticket, what should the confirmation flow look like?

Immediate closure: User says "close ticket", agent immediately squashes commits and runs final review
Pre-flight check: Agent shows summary (X tasks, Y commits, Z deviations) and asks for confirmation
Staged closure: Agent runs ticket review first, shows results, then asks if user wants to proceed with rebase/merge
Automatic: After all tasks complete and reviews pass, ticket auto-closes without user intervention
A. Immediate closure (no confirmation)

B. Pre-flight check (summary + confirm)

C. Staged closure (review first, then confirm)

D. Automatic (no user action)

Enhanced Rebase Conflict Notification
When the enhanced rebase detects conflicts requiring investigation, how should the user be notified?

Blocking prompt: Rebase pauses and prompts user immediately with conflict details
Investigation report: Rebase completes investigation, then presents full report for user review
Escalation levels: Minor conflicts auto-resolve, major conflicts prompt user with recommendations
Async notification: Rebase continues, sends notification when investigation completes (user reviews later)
A. Blocking prompt (immediate pause)

B. Investigation report (full analysis first)

C. Escalation levels (auto-resolve minor)

D. Async notification (review later)

Evaluation Worktree Gap Report
After the evaluation worktree runs final review and produces a gap report, what should happen next?

Report display: Gap report is displayed in terminal, user manually creates tickets in Traycer
Interactive ticket creation: Agent shows gaps and offers to help draft ticket descriptions
File export: Gap report is saved to a file, user processes it offline
Actionable checklist: Gaps are presented as a checklist, user can mark items to convert to tickets
A. Report display (terminal output)

B. Interactive ticket creation (agent assists)

C. File export (offline processing)

D. Actionable checklist (mark and convert)

These questions focus on the interaction design and user experience for each major flow. Understanding how users enter, navigate, receive feedback, and exit each workflow will help us document clear, actionable user flows.

---

1. B
2. A and B
3. B
4. A. HOWEVER, the steps must be clearly labeled somehow. It can't just be long interconnected prose. The agent's primary purpose is to identify boundaries and then use scripts to split along those boundaries. This agent DOES NOT REWRITE. It dumps to a file, understands boundaries, and writes a script to split the file up. This is to avoid any and all mutations by the agent.
5. The ticket manager is not the one executing steps. The ticket manager is also not the one decomposing a task. It dumps it. There is a new workflow that executes a task. If we want to view things as they are done we'd need a separate window with a UI that can show things in flight. Then agents can write to files and the UI can detect workspaces and show things. I think that this would be very cool and I'd leave the design and user experience and UI completely up to you. I don't want to figure out anything. These agents run inside of claude code, gemini, and codex. If you want to capture logs you'd likely need to wrap them. This'd be part of agent runner (there's an agent runner system). Agent runner as a system would need to know where to store logs for running agents. We'd need to store state updates for when we execute agents and when we enter workflows. We'd also likely need much more robust workflow logging for all of our existing workflows (python ones). This'll allow us to understand what broke when bugs happen. To do this we very much likely wants sqlite or ladybug db (likely sqlite). We can't show things as they happen within our terminals. Our UI would show things as they get updated. I know I'm underspecifying a lot of this but I'd want you to figure out most of the user experience. i'm not that picky here. I just think it'd be nice if we had logging, if we could see how things got executed, and if our workflow repair agent had more to go on than vibes. If it could investigate logs to find workflow errors. We likely want a glm agent to review agent runs for errors that they encountered (bad commands etc) to monitor the system (was an agent run reviewed or not?). We can have agents repot when they ran into problems. They don't have to report the problems, just that the workflow didn't go as expected. Then we send our glm agent in to investigate the workflow and create a report of what happened. I'll leave this big system design up to you. In scripts/ you'll find various workflows. Our workflows are a combination of agents, commands, and scripts. Claude code commands execute these scripts. Scripts "should" theoretically all be state machines so that we can recompose/reconfigure them as needed. Ultimately we can slowly migrate features to this UI and fill it out. The UI would just start as a way to visually see what is happening. This UI can very much be rough and a prototype. I'd want it to use rust and react. What's much more important is the logging across our existing workflows and enhancing the workflow repair agent. Also .. if we are going to bring in sqlite for this, then we can just move all of our workspaces to sqlite and run queries on that. The workspaces still need to be scoped by worktrees. I think .db needs to be added to gitignore.
6. Deviations are fine. The thing that looks at them is our review agent. They will determine if deviations are acceptable. The user never really sees them.
7. D. However, the AGENT does not apply these fixes. It runs the update-pr workflow.
8. A user cannot close a ticket if there are gaps for that ticket. A user "attempts" to close a ticket and receives a report. The report will be in a file. ticket-manager does not read the file. It just presents the filepath "here's a file".
9. The user isn't notified unless the conflicts require a reconciliation plan. The ticket-manager/project-manager would present filepaths.
10. File export. The project manager needs to present the filepath to the user.

---

Logging System Scope
You mentioned comprehensive logging across workflows, agents, and commands. What should be the initial scope for this logging system?

Phase 1 only: Focus on project-manager, ticket-manager, and task execution workflows (new components)
Existing workflows: Retrofit logging into all existing Python workflows in scripts/ first
Agent runner integration: Start with agent runner system, then expand to workflows
Full system: Implement logging across all components simultaneously (agents, workflows, commands)
A. Phase 1 only (new components)

B. Existing workflows (retrofit scripts/)

C. Agent runner integration (start there)

D. Full system (all components)

SQLite Database Schema Design
You mentioned moving workspaces to SQLite and adding logging. How should the database be structured?

Single database: One workflow.db at repo root containing all workspaces, logs, and state
Per-worktree databases: Each worktree has its own .db file for isolation
Hybrid: Central workflow.db for global state, per-worktree .db for workspace-specific data
Separate databases: workflow.db for workspaces, logs.db for logging/monitoring
A. Single database (workflow.db at root)

B. Per-worktree databases (isolated)

C. Hybrid (central + per-worktree)

D. Separate databases (workflow.db + logs.db)

Rust+React UI Architecture
For the monitoring UI, what should the architecture look like?

Tauri app: Rust backend with Tauri framework, React frontend, runs as desktop app
Web server: Rust web server (Axum/Actix), React SPA, accessed via browser
CLI with TUI: Rust CLI that can launch a terminal UI (ratatui) or web UI
Embedded: Rust binary embedded in Python, launches React dev server on demand
A. Tauri app (desktop application)

B. Web server (browser-based)

C. CLI with TUI (terminal or web)

D. Embedded (Python-launched)

UI Real-Time Update Mechanism
How should the UI detect and display updates as workflows execute?

File watching: UI watches workspace directories for file changes, updates on detect
Database polling: UI polls SQLite database periodically for new log entries
WebSocket/SSE: Rust backend streams updates to React frontend in real-time
Hybrid: File watching for workspace files, database polling for logs/state
A. File watching (filesystem events)

B. Database polling (periodic queries)

C. WebSocket/SSE (real-time streaming)

D. Hybrid (file watching + DB polling)

Agent Runner Log Capture
You mentioned wrapping agents to capture logs. How should the agent runner capture and store logs?

Stdout/stderr capture: Wrap agent invocations, capture all output, write to SQLite
Structured logging: Agents emit structured JSON logs, runner collects and stores
File-based: Each agent writes to a log file, runner indexes file locations in DB
Hybrid: Structured logs for state transitions, stdout/stderr for debugging
A. Stdout/stderr capture (wrap invocations)

B. Structured logging (JSON logs)

C. File-based (log files + DB index)

D. Hybrid (structured + stdout/stderr)

Workflow Error Monitoring
You mentioned a GLM agent reviewing agent runs for errors. When should this monitoring agent run?

Continuous: Monitors all agent runs in real-time, flags issues immediately
On-failure: Only triggered when an agent reports a problem or exits with error
Scheduled: Runs periodically (e.g., every hour) to review recent agent runs
On-demand: User manually triggers review when they suspect issues
A. Continuous (real-time monitoring)

B. On-failure (error-triggered)

C. Scheduled (periodic review)

D. On-demand (user-triggered)

Workflow Repair Agent Enhancement
The workflow-repair agent currently operates on "vibes". With logging, what should it have access to?

Full execution trace: Complete log of all commands, outputs, and state transitions
Error context: Failed command + surrounding context (previous 5 commands, state before/after)
Workflow history: All previous runs of the same workflow for pattern analysis
All of the above: Full trace, error context, and historical patterns
A. Full execution trace

B. Error context (localized)

C. Workflow history (patterns)

D. All of the above

Task Decomposition Agent Behavior
You clarified that the decomposition agent dumps the task to a file, identifies boundaries, and writes a script to split it. What should this script output?

Numbered files: Creates step_1.md, step_2.md, etc. in a task directory
JSON manifest: Creates a task.json with step metadata and content references
Shell script: Generates a bash script that can be executed to split the file
Python script: Generates a Python script with step extraction logic
A. Numbered files (step_N.md)

B. JSON manifest (metadata + refs)

C. Shell script (bash splitting)

D. Python script (extraction logic)

Task Execution Workflow Scope
You mentioned a new workflow that executes tasks (separate from ticket-manager). What should this workflow be responsible for?

Step execution only: Executes steps sequentially, commits after each
Step + context: Executes steps and manages context manager interactions
Full task lifecycle: Decomposition, execution, context management, and review
Execution + deviation tracking: Executes steps and tracks deviations, delegates review
A. Step execution only

B. Step + context management

C. Full task lifecycle

D. Execution + deviation tracking

State Machine Migration Priority
You mentioned scripts "should" be state machines for reconfigurability. What's the priority for this migration?

New components only: Project-manager, ticket-manager, task execution are state machines from day 1
Critical paths first: Migrate review-implementation, update-pr, rebase workflows first
Gradual migration: Implement state machine framework, migrate workflows incrementally
Not a priority: Focus on logging/monitoring first, state machine migration later
A. New components only

B. Critical paths first

C. Gradual migration

D. Not a priority

---

1. A + C. You'd need to retrofit to any workflows / scripts that project-manager, ticket-manager, etc use. We have existing workflows that they make use of.
2. A. Logs mate ;).
3. A
4. B. Since we're getting rid of loose file workspaces it'll b e hitting up the database. We'll be polling on the Rust side and streaming updates to the UI side.
5. A. There's an example of this somewhere in the project. Either article writer or spec manager likely has this. There were some metadata issues and the like that were handled. That's right. There was a GLM context manager. We'd run steps in python and GLM would manage context between each step.
6. B
7. A. It'd start with a trace of a particular agent or python script. It can then move outwards. We'd need to track when workflows run as steps and when steps within workflows run. So each workflow has steps. Those steps can in turn be workflows. This is how our workflow repair agent navigates the traces. It doesn't just see a BIG stream.
8. See the update-pr workflow to understand how tasks are generally handled. update-pr essentially accepts feedback that it breaks down. It uses static python. Decomposition would create python scripts on the fly to break things up.
9. See implementation-review to understand how "most" of the workflow currently operates. It's missing the execution piece. The execution piece runs very similarly to update-pr. I'm wondering if update-pr can just be reused for both? What is an execution input other than task feedback where the task doesn't yet exist? ;D.
10. D. The real purpose of this is so that a user can go into a workflow and say "do this workflow but skip this step" or "I want this to be done" and agent pieces things together between two workflows. It's also so that workflows can be paused and resumed. Right now it's easier ot just throw state out and retry a workflow. The workflow repair agent can literally just execute functions within a workflow to inveestigate individual pieces of it. So we just don't need this. However, the workflow repair agnt does need to know that it can execute pieces of a workflow through JIT scripting. The workflow repair agent also doesn't need to be the agent anymore. It can run things normally. With log access it is just testing its changes. We don't write automated tests because models are expensive and slow. We don't want our tests hitting models up each run. Instead we do self-healing. As we run things we can see errors and fix them. We take the "break things" approach ;D.

---

Success Criteria (Epic Brief)

Gap: No explicit success criteria defined. How do we measure if this system solves the problems?
Impact: Without success criteria, it's unclear when the system is "done" or if it's working as intended.
Suggested Addition: Define measurable outcomes (e.g., "Developers can resume interrupted workflows without context loss" or "Conflict resolution rationale is documented in 100% of merge conflicts")
2. Error Recovery Patterns (Core Flows)

Gap: Flow 6 (Task Execution) mentions "If review fails: Run update-pr workflow" but doesn't specify what happens if update-pr also fails or if there are repeated failures.
Impact: Could lead to infinite loops or unclear escalation paths.
Question: What's the maximum retry limit? When should the system escalate to the user vs. auto-retry?
3. Workspace Migration Strategy (Core Flows)

Gap: The system moves from "loose file-based workspaces" to SQLite, but there's no mention of migrating existing workspaces.
Impact: Existing projects in .worktrees/ may not be compatible with the new system.
Question: Should the system detect and migrate old workspaces? Or is this a clean-slate implementation?
4. Monitoring UI Startup (Flow 12)

Gap: Flow 12 describes the UI but doesn't specify how users launch it or if it runs automatically.
Impact: Unclear user journey for accessing monitoring capabilities.
Question: Is the UI launched via command (e.g., /monitor)? Does it auto-start with workflows? Is it optional?
5. Linear API Failure Handling (Flow 15)

Gap: Flow 15 assumes Linear API calls succeed. No error handling for network failures, auth issues, or API limits.
Impact: Project completion could fail silently or leave system in inconsistent state.
Question: Should artifacts be stored locally as backup? Should Linear sync be retryable/resumable?
6. Concurrent Ticket Execution (Flow 4)

Gap: Flow 3 identifies tickets that "can run in parallel" but Flow 4 only describes opening one ticket manager at a time.
Impact: Unclear how parallel execution actually works in practice.
Question: Can users open multiple ticket-manager sessions simultaneously? How is worktree isolation maintained?
7. Task Decomposition Boundary Detection (Flow 5)

Gap: Flow 5 states boundaries "must be clearly labeled" but doesn't define what constitutes a clear label.
Impact: Decomposition agent may fail or produce incorrect splits if labels are ambiguous.
Question: What's the expected format? (e.g., "## Step 1:", "### Task:", numbered lists?) Should there be validation?

---

1. The problems are when bugs happen I can't see what is happening. I had an infinite loop but I had no idea what was happening. I just saw a timer. I had to have an agent QA through everything step by step but it kept going off-track in the workflows. If I had logs it would have found the issue. My workflows are very, very slow. I need to be able to execute them in parallel. I'm just using Traycer planning but want them executed in parallel. Because we are not using Linear tickets but rather Traycer tickets rebase needed updates. I want an agent to look at when agents encounter problems because I can have errors in my workflow but never realize that they even exist. The workflow continues to run but more slowly. It'd be even better we have an anomolous long-running process and an agent just automatically looks into it rather than me noticing it. Another issue I have is that we are spawning lots of subprocesses. We need to be able to kill these subprocesses if things go awry. So an agent sees something may be wrong. It checks logs. It sees something is definitely wrong. It kills the process. It passes logs off to repair workflow agent. Workflow gets repaired. Process gets resumed. So .. we likely need to edit a few more things :). I don't even want to have to notice when things go awry. When something looks suspicious. Agents can notice because a process is running longer than expected. If we have no history then we check every 10 minutes while we figure out how long it normally runs for. If errors resolve themselvs and I can run planning in parallel and my rebase still works then I am happy.
2. update-pr fails as an error and we get workflow repair agent. we never retry until we investigate first. otherwise update-pr does not fail. review steps happen outside of it.
3. we don't have any existing workspaces. don't worry.
4. user starts it. it is a readonly view. it doesn't have to be up and running. when it starts up it can gravb the current state of the world and then update from there. it can run on linux, mac, or windows. The great thing about this is that windows wsl can be running our agents and writing to sql while our UI lives in standard windows just reading the sql db.
5. these are just other errors. workflow repair investigates. if it tracks the error to something that cannot be fixed it will need to give instructions to the user for what it needs. New API key etc. So some errors cannot be fixed. This is a good point. We need to present these to the user. These get presented by the ticket manager/project manager terminals (wherever the workflow failed) by the root agent. For these failures we don't present a file. We actually give text. However, we could also get silent failures. The GLM monitoring agent would see these. How are these presented to the user? We'd need some kind of ! notification in the UI because these are managed by a background process. The user then opens up, sees instructions. They then open up a project manager and state what they did so that the project manager can run the workflow repair agent for the right ticket etc. So project manager can act as a QA. It's an  agent so it can adapt. It has the context to do whatever it needs for any project.
6. A user just opens multiple terminals at once? lol... tickets are tied to worktrees. a user doesn't open the same ticket multiple times. they open multiple tickets. you can't execute tasks underneath a single ticket in parallel. you execute tasks across tickets in parallel. each ticket does 1 task at a time.
7. There is no format. If the agent doesn't think it's absolutely obvious then the format failed.

---

Anomaly Detection Baseline
You mentioned checking every 10 minutes while building baseline for "normal" execution time. How should the system establish this baseline?

Per-workflow type: Track execution time per workflow type (e.g., review-implementation avg 5min, rebase avg 2min)
Per-step granularity: Track each step within workflows separately (e.g., "scope agent" avg 30sec, "reviewer agent" avg 3min)
Adaptive learning: Start with conservative thresholds (e.g., 30min), tighten as data accumulates
Hybrid: Per-workflow averages + per-step granularity for detailed anomaly detection
A. Per-workflow type (workflow-level averages)

B. Per-step granularity (step-level tracking)

C. Adaptive learning (conservative start)

D. Hybrid (workflow + step tracking)

Process Kill Authority
When the monitoring agent detects something wrong and decides to kill a process, should it require confirmation?

Autonomous kill: Agent kills process immediately without user confirmation
User confirmation: Agent notifies user via UI, waits for kill confirmation
Severity-based: Auto-kill for clear errors (infinite loops), confirm for suspicious cases
Grace period: Agent notifies user, auto-kills if no response within 2 minutes
A. Autonomous kill (no confirmation)

B. User confirmation required

C. Severity-based (auto for clear errors)

D. Grace period (notify + timeout)

Workflow Resume After Repair
After the workflow repair agent fixes an issue and the process is killed, how should resumption work?

Automatic resume: Repair agent applies fix and automatically resumes workflow from failure point
User-triggered resume: Repair agent applies fix, user manually triggers resume via command
Checkpoint resume: Workflow resumes from last successful checkpoint (not exact failure point)
Fresh restart: Workflow restarts from beginning with fix applied
A. Automatic resume (from failure point)

B. User-triggered resume (manual)

C. Checkpoint resume (last successful state)

D. Fresh restart (from beginning)

Silent Error Resolution Notification
When errors resolve themselves autonomously (monitoring agent detects, kills, repairs, resumes), how should the user be notified?

No notification: Completely silent, user only sees successful completion
Summary notification: After workflow completes, show "3 issues auto-resolved" summary
Real-time log: UI shows resolution events in real-time but doesn't interrupt user
Post-completion report: Generate report file with all auto-resolutions for audit trail
A. No notification (silent)

B. Summary notification (completion)

C. Real-time log (UI only)

D. Post-completion report (audit file)

Unfixable Error Presentation
When the GLM monitoring agent detects silent failures that require user action (API keys, permissions, etc.), how should these be presented?

Terminal output: Root agent (project-manager/ticket-manager) displays error text directly in terminal
UI notification + terminal: Alert in monitoring UI + text in terminal where workflow originated
File + notification: Write error to file, show notification in UI with filepath
Blocking prompt: Workflow pauses, terminal shows error and waits for user to fix and confirm
A. Terminal output only

B. UI notification + terminal

C. File + UI notification

D. Blocking prompt (wait for fix)

Process Tracking Granularity
To enable process killing, the system needs to track subprocess PIDs. At what granularity should processes be tracked?

Workflow-level: Track top-level workflow process only (killing it kills all children)
Agent-level: Track each agent invocation separately (can kill individual agents)
Step-level: Track each workflow step as separate process (fine-grained control)
Full tree: Track entire process tree with parent-child relationships
A. Workflow-level (top-level only)

B. Agent-level (per agent)

C. Step-level (per workflow step)

D. Full tree (parent-child tracking)

Project Manager QA Mode
When the user opens project manager to address a silent failure (after seeing UI notification), how does the QA interaction work?

Describe fix: User describes what they fixed (e.g., "added API key"), project manager triggers workflow repair for affected ticket
Automatic detection: Project manager detects what changed (env vars, config files), auto-triggers repair
Guided workflow: Project manager asks questions to understand fix, then determines which workflows to repair/resume
Manual targeting: User specifies which ticket/workflow to repair, project manager executes repair
A. Describe fix (conversational)

B. Automatic detection (detect changes)

C. Guided workflow (agent asks questions)

D. Manual targeting (user specifies)

These questions focus on the autonomous monitoring and self-healing capabilities. Your answers will help me update the specs to accurately capture the success criteria (autonomous error resolution), the process management requirements (subprocess tracking and killing), and the notification/escalation patterns for unfixable errors.

---

1. Per step BUT keep in mind that steps themselves are workflows and steps can encompass multiple steps. 5 steps may be ok but the workflow surrounding the steps (as a step) may bomb because it's just running those same 5 steps in an infinite loop. Steps and workflows are the same thing. It's just whether a step has N steps or whether a step is 1 step. The real only difference between the two is addressability. Workflows are what we use. Steps are what compose workflows. Steps can use workflows. Steps don't use steps. Each step is 1 atomic action. That atomic action can be a workflow. The point is that we track steps. We don't need to care about how workflows could spawn N steps in parallel etc. We just care about the step that governs a workflow. We can represent claude code commands (root workflows) as an individual step (user calls) that executes a workflow.
2. A. This is a self-repair process. The process will resume if it can. The process will "eventually" resume. The state is there. We'd need to store suspended processes though. Not their state. That's already stored. Just what processes are suspended and when we can resume them. Errors are tied to these processes so ultimately they are always resumed with a workflow repair agent that tries to push through the error. The workflow repair agent can then just run an agent to finish out the process from where it left off. The critical thing here is that some agent was running this process. Like project-manager or ticket-manager. They need to be able to see that the process was killed. We'd then need to wrap the "pending process" with another process to let the agent wait. If the process cannot be repaired then their wrapper process will close out and they will present the error to the user and then resume it etc. Our passive repair can surface things that no agent is currently running. Those things have to be surfaced in a separate thing (our UI). When it finds things that are running those things can be surfaced in the agent running them to the user. Multiple agents may encounter the same error. The user would need to go through each 1 to say "fixed error" etc.
3. I think I covered this already. Automatic resume. ^. I went into a lot more detail too.
4. D
5. Via logs. UI will pick these up. I covered historical errors that are not running vs actively running errors. These are shown differently.
6. We kill the process right underneath workflow/ticket manager. So we continue to let the TOP level agents run. I covered this in another bullet point. We kill the full tree though underneath them. We don't kill the root though. The root is the interactive layer that the user interacts with.
7. We need an error ID. Well, not an error ID. Some kind of ID that the user needs to act upon. The user just references the ID. Like ID fixed. ID resolved.

---

Success Criteria Definition
What are the measurable success criteria for this system? How do we know it's working as intended?

Autonomous resolution rate: X% of errors auto-resolve without user intervention
Parallel execution: User can run N Traycer planning workflows simultaneously without manual coordination
Zero manual debugging: User never needs to manually investigate workflow failures (agents handle it)
All of the above: Combination of autonomous resolution, parallel execution, and zero manual debugging
A. Autonomous resolution rate (X% auto-resolved)

B. Parallel execution (N simultaneous workflows)

C. Zero manual debugging (agents handle all)

D. All of the above

Error ID Format
When the system generates error IDs for user action, what format should these IDs take?

Sequential numbers: ERR-001, ERR-002, etc. (simple, short)
Timestamp-based: ERR-20260122-143052 (sortable, unique)
UUID short form: ERR-a3f9c2 (first 6 chars of UUID, collision-resistant)
Workflow-scoped: PROJ-123-ERR-1 (scoped to project/ticket context)
A. Sequential numbers (ERR-001)

B. Timestamp-based (ERR-20260122-143052)

C. UUID short form (ERR-a3f9c2)

D. Workflow-scoped (PROJ-123-ERR-1)

Monitoring UI Launch Mechanism
How should users launch the monitoring UI?

Command: User runs command like /monitor or uv run monitor
Standalone binary: Separate executable (e.g., ./workflow-monitor) independent of Python
Auto-launch: UI auto-starts when any workflow begins, stays in background
IDE integration: UI launches from IDE (VS Code extension, etc.)
A. Command (e.g., uv run monitor)

B. Standalone binary (./workflow-monitor)

C. Auto-launch (background process)

D. IDE integration (extension)

UI Notification System
When the UI shows notifications (e.g., "!" for unfixable errors), what interaction should they support?

Click to view: User clicks notification, opens detailed error view with instructions
Inline display: Notification expands inline to show error details
Notification center: Notifications accumulate in a center/panel, user reviews batch
Toast + detail: Brief toast notification, persists in error dashboard for later review
A. Click to view (opens detail)

B. Inline display (expands)

C. Notification center (batch review)

D. Toast + dashboard (brief + persistent)

Suspended Process Storage
When a process is killed and suspended pending repair, what information needs to be stored?

Minimal: Process ID, workflow ID, timestamp, error ID
Context: Minimal + last successful step, current step, failure reason
Full state: Context + all workflow state variables, environment, command line args
Resumption package: Full state + repair instructions, resume command
A. Minimal (PID, workflow ID, timestamp, error ID)

B. Context (+ steps and failure reason)

C. Full state (+ all variables and environment)

D. Resumption package (+ repair instructions)

---

1. I already answered this. Check conversation and get back to me if my answer was not sufficient.
2. A
3. Just execute it. It's an application. You need to add "project folders" to it though or it won't know what to monitor. This means it can monitor multiple projects :).
4. Notification center.
5. We already have all of the state. Each step execution needs its own ID for that specific execution. We just need that ID to get the state. This is obvious because we need somewhere to store state, like an ID :p.

---

SQLite Schema Extension Strategy
I see file:scripts/article_writer/tools/workflow/models.py uses SQLAlchemy with a clean model-based approach. I'm assuming we'll:

Extend the existing workflow.db schema with new tables (workspaces, step_timings, suspended_processes, errors)
Reuse the Database class pattern from file:scripts/article_writer/tools/workflow/database.py
Use SQLAlchemy ORM for all database operations
Question: Should we create a separate database module for the project management system, or extend the article_writer database models?

2. Agent Runner Wrapping Approach
I see file:scripts/dev/agent_runner.py provides an abstract base class with provider-specific implementations. For logging integration, I'm assuming we'll:

Create a new LoggingAgentRunner wrapper that delegates to existing runners
Wrap at the AgentRunner.run() level to capture all invocations
Store step execution ID before invocation, capture output after
Question: Should logging be integrated into the base AgentRunner class, or should we create a separate wrapper class?

3. Workflow State Machine Reuse
I see file:scripts/article_writer/tools/workflow/state_machine.py implements a phase-based state machine. For project-manager and ticket-manager, I'm assuming we'll:

Create new state machines following the same pattern
Define phases for each workflow (project-manager: init, loading, ordering, active; ticket-manager: init, decomposition, execution, review, closure)
Store state in SQLite using the same Workflow model pattern
Question: Should we create separate state machine classes for each workflow type, or generalize the existing StateMachine class?

4. Worktree Management Integration
I see file:scripts/pr/git_dao.py and file:scripts/pr/commands/setup_worktree_command.py handle worktree operations. For project worktrees, I'm assuming we'll:

Reuse existing git_dao functions for worktree creation/detection
Create new Python scripts for project worktree detection (similar to ticket worktree detection)
Store worktree metadata in SQLite instead of loose files
Question: Should project worktrees use the same naming convention as ticket worktrees (.worktrees/{branch-name}), or a different pattern (.worktrees/project-{id})?

5. Process Management Architecture
For subprocess tracking and killing, I'm assuming we'll:

Extend agent runner to capture and store process IDs
Create a process manager that tracks parent-child relationships
Use Python's psutil library for cross-platform process management
Kill process trees using psutil.Process.children(recursive=True)
Question: Should process management be part of the agent runner, or a separate service that monitors the database?

---

1. that one was built specifically for the article_writer system. We just want to make sure that we don't include article_writing things in what we do. article_writer does have a lot of workflow stuff in it that we can absolutely utilize.
2. Integrate. AgentRunner is something we should use. That's the specific process that we wrap. However, steps are NOT just agent executions. There are other workflows that agents utilize that are python. Python in turn has multiple python steps.
3. Generalize
4. Project name and project-ticketname. Our tickets aren't in linear and aren't fully defined when we start working on them.
5. We need a process manager. When our root claude code commands execute python, it needs to wrap a subprocess that runs in the background and polls. It can be as simple as another CLI that does this and wraps the uv call or whatever call the agent tried to make. So we can do monitored subprocess calls and regular calls. We want this to be visible and managed in the root agent layer. The claude code commands. We don't want to pass flags all over the place.

---

Generalized Workflow Infrastructure (Extending article_writer patterns)
Assumption: We'll create a generalized workflow system that:

Reuses the SQLAlchemy + SQLite pattern from article_writer
Creates new models for project management (separate from article-specific models)
Uses the same Database class pattern with WAL mode
Generalizes the StateMachine class to support multiple workflow types (not just article-writer phases)
Key Decision: Should we:

Option A: Create a new scripts/workflow/ module with generalized base classes, then have article_writer and project_manager as separate implementations?
Option B: Keep article_writer isolated, create parallel scripts/project_manager/ with similar patterns but independent code?
Option C: Create scripts/core/workflow/ for shared infrastructure, both article_writer and project_manager depend on it?
My recommendation: Option C - shared core infrastructure avoids duplication while keeping domain logic separate.

2. Agent Runner Integration for Logging
Assumption: We'll extend the AgentRunner base class to add logging capabilities:

Add before_run() and after_run() hooks to base class
Subclasses call these hooks to capture execution metadata
Hooks write to SQLite with step execution ID
Process ID captured from subprocess
Key Decision: How to handle Python workflows (not just agent invocations)?

Option A: Create a WorkflowRunner wrapper that tracks Python script execution similarly to AgentRunner
Option B: Instrument Python workflows directly with logging calls at key points
Option C: Use a decorator pattern that wraps any callable (agent or Python function) with logging
My recommendation: Option A - WorkflowRunner provides consistent interface for both agents and Python scripts.

3. Process Management Architecture
Assumption: We need a process manager that:

Wraps subprocess calls at the Claude Code command level
Tracks process trees (parent-child relationships)
Can kill process trees while preserving root interactive agents
Stores suspended process metadata in SQLite
Key Decision: How should Claude Code commands invoke monitored processes?

Option A: Create a monitored-run CLI wrapper: monitored-run uv run pr review-loop ...
Option B: Modify agent runner to automatically wrap all subprocess calls
Option C: Create a Python context manager that agents use: with ProcessMonitor(): subprocess.run(...)
My recommendation: Option A - CLI wrapper is explicit, visible to users, and doesn't require modifying existing code extensively.

4. SQLite Schema Design
Assumption: Single workflow.db at repo root with these new tables:

projects: Project metadata (id, name, worktree_path, status, created_at)
tickets: Ticket metadata (id, project_id, worktree_path, status)
tasks: Task metadata (id, ticket_id, decomposed_steps_path)
step_executions: Step execution tracking (id, parent_id, workflow_type, start_time, end_time, process_id, status)
deviations: Deviation tracking (id, task_id, step_id, description, severity)
suspended_processes: Killed processes pending repair (id, step_execution_id, error_id, killed_at)
errors: Unfixable errors (id, error_code, description, instructions, created_at)
conflict_resolutions: Rebase conflict documentation (id, commit_sha, project_ids, resolution_text)
Key Decision: How to handle hierarchical step tracking (steps containing steps)?

Option A: Self-referential parent_id in step_executions table
Option B: Separate workflow_hierarchy table with parent-child relationships
Option C: Store hierarchy as JSON in step_executions.metadata
My recommendation: Option A - self-referential foreign key is standard SQL pattern, queryable, and efficient.

5. Monitoring UI Architecture
Assumption: Tauri desktop app with:

Rust backend using sqlx for SQLite queries
React frontend with TypeScript
Polling-based updates (500ms interval)
Internal IPC for streaming updates to frontend
Key Decision: How should the UI discover projects to monitor?

Option A: User manually adds project folders via file picker
Option B: UI scans for workflow.db files in common locations (home dir, workspace dirs)
Option C: UI reads a config file (.workflow-monitor.json) that lists project paths
My recommendation: Option A initially (explicit), with Option C for persistence (save added projects to config).

6. Task Decomposition Approach
Assumption: Decomposition agent:

Reads task file
Identifies step boundaries (must be "absolutely obvious")
Generates Python script that splits file using line ranges
Does NOT rewrite content (mutation-free)
Key Decision: How should the generated Python script work?

Option A: Script uses regex to find boundaries, splits on matches
Option B: Script uses line numbers identified by agent, splits at those lines
Option C: Script uses markdown heading detection (e.g., ## Step 1:)
My recommendation: Option B - agent provides explicit line numbers, script is simple and deterministic.

7. Context Manager Integration
Assumption: GLM-based context manager (similar to article_writer's context_summarizer):

Runs after each step completes
Reviews git diffs from prior steps
Generates summary for next step
Tracks deviations from plan
Stores summaries and deviations in SQLite
Key Decision: How should context manager access git diffs?

Option A: Context manager calls git diff directly via subprocess
Option B: Step execution stores diffs in SQLite, context manager reads from DB
Option C: Context manager receives diffs as input from task execution workflow
My recommendation: Option A - context manager is autonomous, can investigate commits independently.

8. Worktree Naming Convention
Assumption: Based on your clarification:

Project worktrees: .worktrees/project-{name}/
Ticket worktrees: .worktrees/project-{name}-{ticket-name}/
Key Decision: How to handle ticket name sanitization?

Option A: Use ticket ID only: .worktrees/project-myproj-TICKET-123/
Option B: Use ticket title (sanitized): .worktrees/project-myproj-add-feature/
Option C: Hybrid: .worktrees/project-myproj-TICKET-123-add-feature/
My recommendation: Option C - includes both ID (unique) and title (human-readable), truncated to 50 chars total.

9. Rebase Enhancement Strategy
Assumption: Enhanced rebase:

Extracts project IDs from commit messages ([PROJECT-{id}] prefix)
Queries git history to find Linear project attachments
Uses sub-agents to investigate conflicts
Creates conflict resolution files when merging changes
Key Decision: How should conflict resolution files be stored?

Option A: As git notes attached to merge commits
Option B: As files in .conflict-resolutions/ directory, referenced in commit message
Option C: In SQLite conflict_resolutions table, attached to Linear projects
My recommendation: Option C - SQLite provides queryability, Linear attachment provides auditability.

10. Workflow Repair Enhancement
Assumption: Workflow repair agent:

Queries execution trace from SQLite by step execution ID
Navigates hierarchical workflow structure
Can execute individual steps via JIT scripting
Tests fixes before applying
Key Decision: How should JIT scripting work?

Option A: Generate Python scripts on-the-fly, execute via uv run python
Option B: Use eval() with sandboxing to execute Python code
Option C: Generate bash scripts that call existing CLI commands
My recommendation: Option A - generated Python scripts are auditable, safe, and can use existing modules.

---

1. C
2. python workflows need to log themselves B. is this how article_writer handled logs for agents? it was designed to capture everything an agent did.
3. A
4. track what spawned the step and then add context of the function. only parents spawn steps. At the very top, entry into process manager, our parent will be the claude code command that spawned us.
5. A
6. Agent identifies a pattern or multiple patterns. Agent creates regex for these patterns. Agent does *dry runs* to determine which splits were encountered and checks the lines to see if those are real splits. Some other things may utilize those patterns that it did not expect. Worst case scenario it uses the regex to surface all of the candidates, inspects each candidate 1 by 1 to see whcih ones are real, and then splits by line numbers. The agent would likely use a python script that will present to it each "candidate". It can approve a candidate (split it) or not approve it (don't split it). That's actually an interactive way for the agent to split everything AND it forces the agent to handle each candidate. I think I like this idea the most. The agent writes scripts to surface candidates and splits that way. Next we run an agent on each split file to make sure that the files don't contain multiple parents. If they do then the agents run scripts to split the files again. Each file is approved/denied. We maintain a list of denied files that we haven't released yet. We have a python script I think loop over these denied files and run agents on them to split them further (replace the file with split children) or approve them. We keep going until there are no denied files remaining. So we need a python script to wrap and call our agent repeatedly. We don't execute this agent directly ;).
7. A
8. We don't have IDs. These aren't in linear. We'd need to have ID management in our sqlite db to produce our IDs. Then we'd need to track which kind of ID it is. Is it a linear ticket ID or a sqlite ID? We can do that by the ID type. SQL-### for example or LOC-###. the remote id is whatever we use in linear. Can be anything. What we really need is a table that defines where IDs come from. Like ID types. So we'd want a project id too. We don't need names in our worktree branchesl Just the IDs. For ticket ID we just use the ticket. For project id we just uset he project. It'd be good to have a source id because ticket ids could potentially collide. So our ticket id is source id + ticket id and source id + project id. Like LIN-1-NES-123.
9. We only need to store them in sqlite now. We don't need to store them in linear anymore.
10. A

---

Python Workflow Logging (Your answer: B - self-logging)
You mentioned article_writer was designed to capture everything an agent did. Let me verify my understanding:

In article_writer, I see:

ContextLogger captures agent output by parsing stdout from subprocess
Agents don't explicitly log - the runner captures their output
This works because agents run as subprocesses
For Python workflows (like pr review-loop, pr discover-scope-files):

These are Python scripts, not agent subprocesses
They need to log themselves explicitly
Question: Should Python workflows:

Option A: Import and use ContextLogger directly, calling log_event() at key points?
Option B: Use a decorator pattern: @log_step that wraps functions and auto-logs?
Option C: Use a context manager: with StepLogger("step_name"): ... that logs entry/exit?
Which pattern do you prefer for Python workflow self-logging?

2. Task Decomposition Interactive Splitting
Your clarification describes a sophisticated multi-pass approach:

Agent identifies patterns, creates regex
Agent writes Python script to surface candidates
Python script presents each candidate to agent for approval/denial
Approved candidates become split files
Another pass: agents verify each split file doesn't contain multiple steps
If multiple steps found, repeat splitting process
Continue until all files approved (no denied files remaining)
Question: This requires a Python orchestration script that:

Runs the pattern-finding agent
Executes the candidate-surfacing script
Runs the approval agent on each candidate
Runs the verification agent on each split file
Loops until convergence
Should this orchestration script be:

Option A: Part of the task execution workflow (embedded in task-executor)
Option B: A standalone script: uv run task decompose {task_file}
Option C: Integrated into ticket-manager command (ticket-manager calls it)
My recommendation: Option B - standalone script provides testability and reusability.

3. ID Management System
Your clarification introduces a comprehensive ID system:

ID types table (defines sources: LINEAR, LOCAL, etc.)
Composite IDs: {source}-{project_id}-{ticket_id} (e.g., LIN-1-NES-123)
Worktree naming uses IDs only: .worktrees/LIN-1/ and .worktrees/LIN-1-NES-123/
Question: For the ID types table, should it store:

Option A: Just source metadata (name, prefix, description)?
Option B: Source metadata + ID counter (for LOCAL IDs)?
Option C: Source metadata + ID counter + validation rules (regex patterns)?
My recommendation: Option C - validation rules ensure ID consistency.

Follow-up: For LOCAL IDs (SQLite-generated), what prefix should we use?

LOC-{counter} (e.g., LOC-1, LOC-2)
SQL-{counter} (e.g., SQL-1, SQL-2)
WF-{counter} (e.g., WF-1, WF-2 for "workflow")
4. Step Execution Parent Tracking
Your clarification: "track what spawned the step and then add context of the function. only parents spawn steps."

Question: What should the "context of the function" include?

Option A: Just function name (e.g., "parent_function": "review_implementation")
Option B: Function name + file path (e.g., "parent_function": "scripts.pr.review_loop.main")
Option C: Function name + file path + line number (e.g., "parent_function": "scripts.pr.review_loop.main:142")
My recommendation: Option B - provides traceability without being too brittle (line numbers change).

5. Conflict Resolution Storage
You clarified: "We only need to store them in sqlite now. We don't need to store them in linear anymore."

Confirmed: Conflict resolutions stored only in SQLite conflict_resolutions table.

Question: How should rebase access these conflict resolutions?

Option A: Query SQLite directly during rebase (rebase script reads DB)
Option B: Export conflict resolutions to files before rebase, rebase reads files
Option C: Rebase queries SQLite, caches results in memory
My recommendation: Option A - direct SQLite queries keep single source of truth.

---

1. A amd B. We can auto log entries/exits. We can also log info things like we'd normally log. Like adding additional info etc. Doing particular actions.
2. B. The user does not call this though! This script is used within ticket-manager. I just don't know which particular script uses it. It's part of a larger workflow, but ticket manager is not the one that calls it.
3. C. I think local we can use LOC.
4. None. Step execution ID. Step execution ID in turn has our context, which would be function name + filepath.
5. A

---

[MOST IMPORTANT] Linear Integration Contradiction
There's a fundamental contradiction between the Epic Brief and Tech Plan regarding Linear integration:

Epic Brief states: "The system persists all artifacts (specs, tickets, tasks, deviations, conflict resolutions) to Linear for auditability"

Core Flows (Flow 9) states: "Query git history to find Linear project attachments for both projects. Fetch specs, tickets, tasks, deviations from Linear for both projects"

Tech Plan (Architectural Approach #9) states: "Store conflict resolutions in SQLite only (no Linear attachment)"

Tech Plan (Component Architecture #10) states: Linear integration syncs artifacts "on completion"

The Issue: The rebase workflow (Flow 9) needs to fetch project documentation from Linear during conflict resolution, but the Tech Plan stores everything in SQLite only. This creates a chicken-and-egg problem:

If artifacts are only synced to Linear on project completion, they won't be available during rebase (which happens before completion)
If conflict resolutions are SQLite-only, future rebases can't access them from Linear
The rebase flow explicitly queries Linear for project docs, but the Tech Plan doesn't support this
Why This Matters: This is a fundamental architectural gap that will block the rebase workflow from functioning as designed. The conflict resolution flow depends on accessing project documentation, but the storage strategy doesn't support this access pattern.

Question: How should project artifacts be stored and accessed?

Option A: Store everything in SQLite only, rebase queries SQLite directly (requires all projects to be in same repo)

Option B: Sync artifacts to Linear progressively (after each ticket), rebase fetches from Linear (supports cross-repo conflicts)

Option C: Hybrid: SQLite for active projects, Linear for completed projects, rebase checks both

Option D: Store in SQLite, export to Linear on completion, rebase only works within single project (no cross-project conflict resolution)

A. Option A: SQLite only, rebase queries SQLite

B. Option B: Progressive Linear sync, rebase fetches from Linear

C. Option C: Hybrid (SQLite + Linear), rebase checks both

D. Option D: SQLite only, no cross-project conflict resolution

[MOST IMPORTANT] Autonomous Monitoring False Positive Risk
The autonomous monitoring system kills processes based on anomaly detection (duration > baseline + 2σ), but this has significant false positive risk:

Scenario 1 - First-Time Workflows: When a workflow type runs for the first time, there's no baseline. The Tech Plan says "start with 10min check interval" but doesn't specify what happens if a legitimate workflow takes 15 minutes on first run. Does it get killed?

Scenario 2 - Variable Workloads: Some workflows have highly variable execution times based on input size:

review-implementation with 5 files: 2 minutes
review-implementation with 500 files: 30 minutes
Both are legitimate, but the 30-minute run would be flagged as anomaly
Scenario 3 - Cascading Kills: If monitoring agent kills a process, investigates, and determines it was a false positive, the damage is done. The workflow must restart from scratch, losing all progress.

Current Mitigation: Tech Plan acknowledges "Risk of false positives (killing healthy long-running processes)" but doesn't provide a solution.

Why This Matters: False positives in autonomous process killing are catastrophic:

Lost work (hours of agent execution)
Wasted API costs (re-running expensive LLM calls)
User frustration (workflows randomly killed)
Potential data corruption (killed mid-commit)
Question: How should the system handle false positive risk?

Option A: Require user confirmation before killing (defeats "autonomous" goal but prevents false positives)

Option B: Use workload-aware baselines (track input size metrics, adjust thresholds dynamically)

Option C: Implement "grace period" - flag as anomaly, continue monitoring, only kill if still anomalous after 2x baseline

Option D: Start conservative (only kill on extreme anomalies: 5x baseline), tighten thresholds as confidence grows

Option E: Combination of B + C (workload-aware + grace period)

A. Option A: User confirmation required

B. Option B: Workload-aware baselines

C. Option C: Grace period before kill

D. Option D: Conservative thresholds initially

E. Option E: Combination (B + C or B + D)

[SIGNIFICANT] Thread-Local Context Initialization Gap
The dual logging strategy relies on thread-local context to store the current step execution ID, but the Tech Plan doesn't specify how this context is initialized:

The Pattern:

python

@log_step(step_name="discover_scope_files")
def discover_scope_files(working_dir: str, start_commit: str):
    logger = get_step_logger()  # Gets step ID from thread-local
    logger.log_event("scope_discovery", {"files_found": 42})
The Problem: Who sets the thread-local context? When? What happens if it's not set?

Scenario 1 - Entry Point: monitored-run wraps the subprocess. Does it set thread-local context before invoking the subprocess? How does it pass the step execution ID to the subprocess?

Scenario 2 - Nested Calls: If review-implementation calls update-pr, which calls discover_scope_files, each needs its own step execution ID. How is the parent-child relationship maintained through thread-local context?

Scenario 3 - Multiprocessing: If a workflow uses multiprocessing.Pool, each worker process needs its own thread-local context. How is this initialized?

Why This Matters: Without clear initialization rules, logging will fail silently or produce incorrect hierarchies. This is a foundational pattern that must work correctly for the entire system.

Question: How should thread-local context be initialized and propagated?

Option A: monitored-run sets environment variable with step ID, each Python process reads it on startup

Option B: Explicit initialization: every workflow entry point must call init_step_context(parent_id)

Option C: Decorator-based: @log_step creates step execution record and sets thread-local automatically

Option D: Context manager: with StepContext(parent_id): ... sets thread-local for the block

A. Option A: Environment variable propagation

B. Option B: Explicit initialization required

C. Option C: Decorator-based automatic initialization

D. Option D: Context manager pattern

[SIGNIFICANT] Task Decomposition Convergence Guarantee
The interactive multi-pass task decomposition has a "convergence guarantee (max iterations: 10)" but doesn't specify what happens if convergence isn't reached:

The Workflow:

Pattern discovery agent identifies boundaries
Approval agent approves/denies each candidate
Verification agent checks split files for multiple steps
If multiple steps found, repeat splitting
Loop until all files approved (no denied files)
The Problem: What if after 10 iterations, there are still denied files?

Scenario 1 - Ambiguous Task: User provides a task with genuinely ambiguous step boundaries. After 10 iterations, 3 files are still flagged as "contains multiple steps" but the approval agent can't find clear split points.

Scenario 2 - Agent Disagreement: Approval agent keeps denying splits that verification agent keeps flagging. Infinite loop between "split this" and "don't split this".

Scenario 3 - Malformed Input: User provides a task that's actually a single step but written in a way that triggers false positives in verification.

Current Mitigation: Tech Plan says "max iterations: 10" but doesn't specify the failure mode.

Why This Matters: Task decomposition is a critical entry point. If it fails, the entire ticket workflow is blocked. Users need clear guidance on what to do when decomposition fails.

Question: What should happen when task decomposition doesn't converge?

Option A: Fail fast - return error to user with diagnostic report, user must rewrite task

Option B: Best effort - return partially decomposed task, user manually splits remaining files

Option C: Escalate to human - present denied files to user, user provides split instructions

Option D: Fallback - treat entire task as single step (no decomposition), execute as-is

A. Option A: Fail fast with diagnostic

B. Option B: Best effort partial decomposition

C. Option C: Escalate to human for manual split

D. Option D: Fallback to single-step execution

[SIGNIFICANT] Worktree Branching Strategy Ambiguity
The Tech Plan specifies worktree naming (.worktrees/LIN-1-NES-123/) but doesn't specify the git branching strategy:

Core Flows states: "Ticket worktrees branch from project worktree" and "Worktrees are opened based on the current checked out branch and are merged back to the checked out branch"

The Ambiguity: What branch does each worktree use?

Scenario 1 - Project Worktree: User creates project LIN-1. What branch does .worktrees/LIN-1/ use?

Option A: Creates new branch project/LIN-1 from current branch
Option B: Uses current branch directly (e.g., main)
Option C: Creates new branch LIN-1 from current branch
Scenario 2 - Ticket Worktree: User creates ticket LIN-1-NES-123. What branch does .worktrees/LIN-1-NES-123/ use?

Option A: Creates new branch ticket/LIN-1-NES-123 from project worktree's branch
Option B: Creates new branch LIN-1-NES-123 from project worktree's branch
Option C: Uses project worktree's branch directly (no new branch)
Scenario 3 - Merge Back: When ticket closes, where does it merge?

If project worktree uses project/LIN-1 branch, ticket merges to project/LIN-1
If project worktree uses main branch, ticket merges to main
What happens to the ticket branch after merge? Delete it?
Why This Matters: The branching strategy affects:

Git history organization
Conflict resolution (which branches can conflict?)
Cleanup (which branches to delete?)
Parallel execution (can multiple tickets work on same project branch?)
Question: What is the git branching strategy for worktrees?

Please specify:

What branch does project worktree use?
What branch does ticket worktree use?
Where do tickets merge back to?
What happens to branches after merge?
A. Provide branching strategy details

[MODERATE] Monitoring UI Database Locking
The monitoring UI polls workflow.db every 500ms while workflows are actively writing to it. SQLite's WAL mode helps, but there are still potential locking issues:

The Pattern:

Workflows write to workflow.db (via Python + SQLAlchemy)
Monitoring UI reads from workflow.db (via Rust + sqlx)
Both happen concurrently
Potential Issues:

Issue 1 - Write Starvation: If UI polls every 500ms and holds read locks, workflows may experience write delays. SQLAlchemy's default timeout is 5 seconds - if UI holds lock longer, workflows fail.

Issue 2 - Checkpoint Blocking: WAL mode requires periodic checkpoints (merging WAL into main DB). If UI holds read lock during checkpoint, checkpoint blocks, WAL grows unbounded.

Issue 3 - Cross-Platform Differences: WAL mode behavior differs between Linux, macOS, and Windows. Windows has stricter file locking, may cause more contention.

Current Mitigation: Tech Plan specifies WAL mode and "busy_timeout=5000" but doesn't address concurrent read/write patterns.

Why This Matters: Database locking issues are subtle and hard to debug. They manifest as intermittent failures under load, which is exactly when the system is most valuable.

Question: How should the monitoring UI handle concurrent database access?

Option A: Read-only connection with PRAGMA query_only=1 (prevents accidental writes, reduces lock contention)

Option B: Shorter polling interval with timeout (poll every 200ms, timeout after 100ms, skip if locked)

Option C: Separate read replica (UI reads from copy, background process syncs every 1s)

Option D: Event-based updates (workflows write to message queue, UI subscribes, no polling)

A. Option A: Read-only connection

B. Option B: Shorter polling with timeout

C. Option C: Separate read replica

D. Option D: Event-based updates (message queue)

[MODERATE] Context Manager Git Diff Performance
The context manager runs after each step to review git diffs from all prior steps. As tasks grow, this becomes expensive:

The Pattern (from Tech Plan):

Context manager calls git diff directly via subprocess
Reviews diffs from all prior steps
Generates summary for next step
Performance Concern:

Scenario: Task with 20 steps

Step 1: Review 0 diffs (0 git diff calls)
Step 2: Review 1 diff (1 git diff call)
Step 3: Review 2 diffs (2 git diff calls)
...
Step 20: Review 19 diffs (19 git diff calls)
Total: 190 git diff calls for one task
Each git diff call:

Spawns subprocess (overhead)
Reads git objects from disk (I/O)
Computes diff (CPU)
Returns potentially large output (memory)
Compounding Factors:

GLM context manager must process all diffs (token costs)
Diffs may be large (refactoring steps)
Context manager runs synchronously (blocks step execution)
Why This Matters: As tasks grow, context management becomes a bottleneck. A 20-step task could spend more time on context management than actual implementation.

Question: How should context manager optimize git diff access?

Option A: Batch diffs - single git diff step-1..step-N call instead of N individual calls

Option B: Cache diffs - store diffs in SQLite on first access, reuse for subsequent steps

Option C: Incremental diffs - only review diff from previous step, maintain running summary

Option D: Parallel processing - fetch all diffs concurrently, process in parallel

Option E: Lazy loading - only fetch diffs when context manager determines they're relevant

A. Option A: Batch diffs (single call)

B. Option B: Cache diffs in SQLite

C. Option C: Incremental diffs only

D. Option D: Parallel processing

E. Option E: Lazy loading

---

1. A
2. The agent looks at the process first. Processes are normally long because of infinite loops. It needs to look for patterns. Is it doing the same thing over and over again? What you did point out that is important is that aborted executions must not count towards average runtimes. We don't kill without looking and seeing if there's a potential infinite loop. Investigation is about fixing that loop. We're pretty positive there's an infinite loop happening at that point. If it did the same actions for 45 minutes over and over again then it's probably an infinite loop. So what we really want to do is track cycles. We want to track inputs and outputs and determine if we're stuck in a cycle. Cycles can happen because of bugs, infinite retries (broken integration), etc. We're looking for repeated actrions though with repeated inputs where we're executing on the same state over and over and over again. We also track what we expect vs what we got. We expect a bunch of states that look highly similar (a counter) but we got a bunch of states that look the same (same counter) or that oscillated between some numbers or that used the same 5 counters repeteadly. We're looking for cycles.

1. No max iterations. We don't do max iterations anywhere. We detect cycles and fix bugs. We don't try to hide bugs with max iterations. THat's not a plan. If an agent denies a file but doesn't perform a split we track that. The next time the file runs we state "no split was performed but the file was denied. determine why and ascertain whether to approve the file or figure out how to split it. you must verify that you split the file. if you give up you must state why you gave up and mark it as a problem and then approve the file as is". Also track the why in split this vs don't split this. The split this will have to accept the "don't split htis" but mark a problem. They need to see the history that the file went through if the state did not change. I was assuming one agent was doing it. If multiple are doing it we need a history and the "split this" must eventually accept "don't split this" and mark the problem.
2. Scenario 1: A, Scenario 2: A
3. The UI is readonly but doesn't ened to be actually. What we likely want is a message queue. The queue isn't "consumed". We read from the queue from a point onwards to see events. When we start we first track position in message queue and then we grab all current state. After that we rely on message queue updates. We compare the events to the state we have as we process (is our state newer for that event?) and we keep going. We always see if an event is newer than what we currently have. This will be "user required notifications" and "state updates."
4. I am pretty sure I already said that it's incremental diff calls.. you don't recall the same git diff over and over again... are we dropping details? You can review the conversation and search it. We literally discussed exactly this already. Did you lose information for how it manages context too?

1. No idea. This requires research into best practices. I'd normally say do it on the log_step but the log_step is for logging. That's mixing up concerns. For a web server you do it around your API endpoints automatically. What I would say is to change log_step into step. The step is just automatically logged. Then we solve both problems.

---

Cycle Detection Implementation Details
You clarified that autonomous monitoring detects cycles by tracking inputs/outputs and looking for repeated actions with same inputs. I need to understand the implementation details:

What to Track:

Inputs: Function arguments, environment state, file contents?
Outputs: Return values, stdout, file changes, git commits?
State: What constitutes "state" for comparison? (e.g., git HEAD, file checksums, DB records?)
Cycle Detection Logic:

How many repetitions constitute a cycle? (e.g., same input/output 3 times in a row?)
How do we handle legitimate retries? (e.g., network request fails, retry with same input is expected)
What's the window for cycle detection? (last N actions? last N minutes?)
Example Scenario: review-implementation workflow

Iteration 1: Reviews 5 files, finds 3 issues, runs update-pr
Iteration 2: Reviews 5 files, finds 3 issues (same issues), runs update-pr
Iteration 3: Reviews 5 files, finds 3 issues (same issues), runs update-pr
Is this a cycle? Or is it legitimate if the issues are genuinely not fixed?

Question: What are the specific rules for cycle detection?

Option A: Hash-based - hash (function_name + inputs + outputs), detect if same hash appears 3+ times consecutively

Option B: State-based - track git HEAD + file checksums, detect if state doesn't change after 3+ actions

Option C: Semantic - GLM agent reviews action history, determines if actions are "meaningfully different"

Option D: Hybrid - hash-based for fast detection, GLM review for confirmation before kill

A. Option A: Hash-based detection

B. Option B: State-based detection

C. Option C: Semantic (GLM review)

D. Option D: Hybrid (hash + GLM)

Message Queue Technology Choice
You clarified that the monitoring UI should use a message queue instead of polling. The queue is append-only, UI reads from position onwards.

Requirements:

Append-only (workflows write events)
Position-based reading (UI tracks last read position)
Persistent (survives process restarts)
Cross-platform (Linux, macOS, Windows)
Works with WSL (Windows UI reads from WSL queue)
Question: What message queue technology should we use?

Option A: SQLite table as queue (events table with auto-increment ID, UI tracks last_read_id)

✅ Already using SQLite, no new dependency
✅ Cross-platform, works with WSL
⚠️ Not optimized for queue workload (append-heavy)
Option B: Redis Streams (append-only log with consumer groups)

✅ Designed for this use case
✅ High performance
⚠️ Requires Redis server running
⚠️ Additional operational complexity
Option C: File-based queue (append to .workflow-events.log, UI tracks byte offset)

✅ Simple, no dependencies
✅ Cross-platform
⚠️ Manual parsing, no structured queries
⚠️ File locking issues on Windows
Option D: ZeroMQ or nanomsg (lightweight message queue library)

✅ Lightweight, embeddable
✅ Cross-platform
⚠️ Requires separate broker process
⚠️ Persistence requires additional setup
A. Option A: SQLite table as queue

B. Option B: Redis Streams

C. Option C: File-based queue

D. Option D: ZeroMQ/nanomsg

Worktree Merge Strategy and Cleanup
You confirmed the branching strategy:

Project worktree: branch project/LIN-1 from current branch
Ticket worktree: branch ticket/LIN-1-NES-123 from project/LIN-1
I need clarification on merge and cleanup:

Scenario: User working on main branch

Creates project LIN-1 → worktree at .worktrees/LIN-1/ on branch project/LIN-1
Creates ticket LIN-1-NES-123 → worktree at .worktrees/LIN-1-NES-123/ on branch ticket/LIN-1-NES-123
Completes ticket → runs rebase and merge
Questions:

Ticket merge target: Does ticket/LIN-1-NES-123 merge into project/LIN-1 or main?
Project merge target: Does project/LIN-1 merge into main at project completion?
Branch cleanup: After merge, do we delete the ticket/project branches?
Worktree cleanup: After merge, do we delete the worktree directories?
Option A: Hierarchical merge

Ticket merges to project branch (ticket/LIN-1-NES-123 → project/LIN-1)
Project merges to original branch (project/LIN-1 → main)
Delete branches and worktrees after merge
Option B: Direct merge

Ticket merges directly to original branch (ticket/LIN-1-NES-123 → main)
Project branch is just for organization, never merged
Keep branches for history, delete worktrees
Option C: Squash merge

Ticket squashes to project branch (single commit)
Project squashes to original branch (single commit)
Delete branches and worktrees after merge
A. Option A: Hierarchical merge (ticket→project→main)

B. Option B: Direct merge (ticket→main directly)

C. Option C: Squash merge (single commits)

@step Decorator Scope and Behavior
You clarified that @log_step should be renamed to @step and it both logs AND manages context automatically. I need to understand the full behavior:

What @step Does:

Creates step execution record in SQLite
Sets thread-local context with step execution ID
Logs entry (function name, args)
Executes function
Logs exit (return value, duration)
Clears thread-local context
Questions:

Q1 - Nested @step calls: If function A (decorated with @step) calls function B (also decorated with @step), how does parent-child relationship work?

Does B's @step automatically use A's step execution ID as parent?
Or does B need explicit parent_id parameter?
Q2 - Exception handling: If decorated function raises exception, does @step:

Log the exception to context_logs?
Mark step execution as 'failed'?
Re-raise the exception?
All of the above?
Q3 - Return value capture: Does @step capture return values?

If yes, how are large return values handled? (e.g., function returns 10MB string)
If no, how do we track what a step produced?
Q4 - Async functions: Does @step support async functions?

python

@step(step_name="async_task")
async def async_task():
    await some_operation()

---

1. When I say state I mean inputs/outputs into functions. GLM won't see that though. We won't have the information we need to detect cycles. We can see "STEP" cycles but we can't see internal infinite loops that just execute code (a very long running step). If there are no logs on it then we have no idea what is happening. So that's less about cycle detection and more there is a black box and we don't know what it is doing and it is very long. So .. we kill it.. add observability.. then we resume it.. if we still don't understand we kill it again, add more observability, and then resume it.. and I'm saying no understand as in we don't even know if there is a potential bug or if it's just a really long running process. We could add some metrics inside to see which step precisely is taking a LONG time. If it turns out to be something like a giant persist or a call to a code review agent then that makes sense. It's just a long call. We need to be defensive around these calls though by determining where our time is coming from. Is it coming from a cycle or a long call? Now these long calls hapepn to always be their own steps. We just need to also track metrics (runtime), which I think that we do. We also need to track step executions within a context. Like in our context, which steps have we run and what states did they have? This'll tell us about cycles. If a step is just running forever and there's no logging or information about it, do we own that step or is it an external step? Like the coderabbit agent call. If we own the step, does the step loop at all or anything? We can run a simulation on the step without interfering with the process. This may actually be a better bet. We can take that step and run a simulation to see how it behaves in general. We can even just capture the inputs as they are and change the target or do a more dry run to simulate the step with our metrics, logging, etc. This way we don't kill steps. We actually test them in parallel. We have all the state so we can do precisely this. This allows us to investigate without killing things. We can then tie the step in its precise state to a comment about it. When we change the step around and what not, we can look at historical comments and see if they are still relevant... we can actually do this before our final review. We can examine all conclusions related to what we edited and then determine if they still hold. I think I like this a lot more than just killing processes. We come up with a hypothesis first and see if we can figure out what is happening. If it turns out to be an actual issue THEN WE KILL IT and push it through, fixing as we go on live states.
2. D
3. We always merge to where we branched from. Always.
4. I don't understand the question. We just use a stack. An async is a fork with its own stack. Exception is failed, which requires repair. We do not log exceptions. We do not bubble exceptions. We do not try/catch. We only try/catch for things like connections. Agents will see the exceptions. The agents will mark the problem. The agents might silently try to work around the exceptions or they might bomb out and then the root agent will deal with it via workflow repair. What am I missing with the stack though?

---

Parallel Investigation Simulation Environment
You clarified that instead of killing long-running steps, we run parallel simulations to investigate. I need to understand the simulation environment:

The Approach:

Detect long-running step
Capture current state (inputs, context, environment)
Run simulation in parallel with enhanced observability
Form hypothesis
Kill only if hypothesis confirms bug
Questions about Simulation:

Q1 - Isolation: How is the simulation isolated from the real process?

Does it run in a separate worktree?
Does it use a separate SQLite database?
Does it have network access (for API calls)?
Can it write to filesystem?
Q2 - State Capture: What constitutes "current state"?

Function inputs (arguments)
Environment variables
File system state (which files? snapshots?)
Database state (SQLite snapshot?)
Git state (current HEAD, working tree changes?)
Q3 - Dry Run vs Real Run: You mentioned "change the target or do a more dry run". What does this mean?

Does simulation execute real code with mocked I/O?
Does simulation execute real code with real I/O but in isolated environment?
Does simulation execute instrumented code (added logging/metrics)?
Q4 - Simulation Termination: When does simulation stop?

After fixed duration (e.g., 5 minutes)?
When it reaches same duration as real process?
When hypothesis is formed (GLM agent decides)?
When it completes or fails?
Example Scenario: Real process: review-implementation running for 15 minutes (expected: 5 minutes)

Option A: Snapshot worktree, run in separate worktree with instrumented code, terminate after 5 minutes or completion

Option B: Fork process with same inputs, mock file I/O, run until completion or 10 minute timeout

Option C: Analyze execution trace (no actual re-run), GLM agent reviews logs and forms hypothesis

Option D: Run in container with same state, real I/O, network isolated, terminate when hypothesis formed

Which approach aligns with your vision?

A. Option A: Snapshot worktree, separate worktree, instrumented

B. Option B: Fork process, mock I/O, timeout

C. Option C: Analyze trace only (no re-run)

D. Option D: Container, real I/O, network isolated

E. Provide custom approach

---

1. Separate worktree. We copy state over to a different worktree and execute it there. It will absolutely hit everything like normal like an integration test.
2. We have all of the state in sqlite. We need to copy state relevant to our workflow over. We have the step calls, state files that things are working in etc. What we probably want is state that also has a "worktree" value. Which worktree does it exist in? Or branch rather. If it's in the main branch that is also fine. We can copy the state of any branch as a whole to a new branch. Everything's mixed up into the same tables but we can copy branch states by going through all tables and keying off of the branch column. Branch is tied to repository as well, which is tied to foundry. So this will not conflict.
3. We don't need to do a dry run. Just real.
4. We essentially do a step-through of the process. All function calls get logged with all of their states. This will tell us how it's running. We can examine this to detect patterns. We can create JIT scripts if we think a cycle might be at play to examine the call graph. I think we can actually just exmaine the call graph as a whole and look for cycles. We can also track how long each call took. Yea, we can analyze the call graph with python. That seems like the best call. We can do continuous analysis as it runs with our python script. We're looking for long calls, exceptions/retries, cycles, etc. When we detect something we stop. If it's just a long call we just let it run. Like a long library call. ChatGPT can research the long-running library call on the web to see if it's expected to be that long and what can cause it to be that long. It can look up the source code if available to see if this is some kind of poison pill. If there's no source code it can read through the documentation to understand the behavior and look at the inputs to form a hypothesis as to what is happening. Ultimately it's trying to detect poison pills. I'm wondering if we can even do a debug thing in memory to examine how memory is changing and what is being called like windebug?

---

[MODERATE] Message Queue vs SQLite for Event Storage
The Tech Plan now specifies ZeroMQ/nanomsg for the message queue, but there's an architectural question about event storage:

Current Design:

Workflows write events to context_logs table in SQLite
Workflows also write events to ZeroMQ/nanomsg queue
UI reads from message queue for real-time updates
UI can query SQLite for historical data
The Question: Are we writing events to BOTH SQLite and message queue?

Option A: Dual write

Workflows write to both SQLite (persistence) and message queue (real-time)
✅ UI gets real-time updates
✅ Historical data queryable
⚠️ Double write overhead
⚠️ Potential inconsistency if one write fails
Option B: SQLite only, queue from SQLite

Workflows write to SQLite only
Background process tails SQLite, publishes to message queue
✅ Single source of truth
✅ No inconsistency risk
⚠️ Additional background process
⚠️ Slight latency (tail lag)
Option C: Queue only, persist from queue

Workflows write to message queue only
Background process consumes queue, writes to SQLite
✅ Workflows don't block on SQLite writes
✅ Natural backpressure handling
⚠️ Risk of data loss if queue crashes before persistence
Which approach aligns with your vision?

A. Option A: Dual write (SQLite + queue)

B. Option B: SQLite only, tail to queue

C. Option C: Queue only, persist from queue

[MODERATE] Investigation Worktree Cleanup
The parallel investigation creates a separate worktree for each long-running step investigation. Over time, this could accumulate many investigation worktrees:

Scenario: User runs 10 projects, each with 5 tickets, each with 3 tasks, each with 5 steps. If 10% of steps trigger investigation:

Total steps: 10 × 5 × 3 × 5 = 750 steps
Investigations: 750 × 0.10 = 75 investigation worktrees
Questions:

When should investigation worktrees be cleaned up?
Should investigation results be preserved after cleanup?
How do we handle disk space constraints?
Option A: Immediate cleanup

Delete investigation worktree as soon as hypothesis is formed
Store conclusion in investigation_conclusions table
✅ Minimal disk usage
⚠️ Can't re-examine investigation if needed
Option B: Lazy cleanup

Keep investigation worktrees until disk space threshold (e.g., 10GB)
Clean oldest first when threshold reached
✅ Can re-examine recent investigations
⚠️ Requires disk monitoring
Option C: User-controlled

Investigation worktrees persist indefinitely
User manually cleans via command (e.g., /cleanup-investigations)
✅ Maximum flexibility
⚠️ User must remember to clean up
Option D: Time-based

Delete investigation worktrees after 7 days
Store conclusions permanently in SQLite
✅ Balances disk usage and re-examination
⚠️ Arbitrary time threshold
Which cleanup strategy should we use?

A. Option A: Immediate cleanup

B. Option B: Lazy cleanup (disk threshold)

C. Option C: User-controlled

D. Option D: Time-based (7 days)

[MODERATE] @step Decorator and monitored-run Interaction
There's a potential overlap between @step decorator and monitored-run wrapper:

Both capture:

Process ID
Start/end time
Function context
Status (running/completed/failed)
The Question: When a function decorated with @step is invoked via monitored-run, do we get duplicate step execution records?

Example:

bash

# User runs:
monitored-run uv run pr review-loop --ticket NES-123
# Inside review_loop.py:
@step(step_name="run_reviewer")
def run_reviewer(...):
    pass
Scenario 1: monitored-run creates step execution for pr review-loop Scenario 2: @step decorator creates step execution for run_reviewer

This is correct (parent-child relationship). But what if:

bash

monitored-run uv run python -m scripts.pr.review_loop
And review_loop.main() is also decorated with @step? Do we get:

Step 1: monitored-run → python -m scripts.pr.review_loop
Step 2: @step → scripts.pr.review_loop.main
Is this duplication or correct hierarchy?

Option A: Duplication is correct - monitored-run tracks subprocess, @step tracks function

✅ Complete hierarchy (subprocess → function)
⚠️ Extra database records
Option B: monitored-run detects @step and skips its own logging

✅ No duplication
⚠️ Complex detection logic
Option C: @step is only for internal functions, entry points use monitored-run only

✅ Clear separation
⚠️ Requires discipline (don't decorate entry points)
Which approach is correct?

A. Option A: Duplication is correct (subprocess + function)

B. Option B: monitored-run detects @step

C. Option C: Separate concerns (entry vs internal)

[MINOR] Composite ID Parsing in Commit Messages
The Tech Plan specifies commit message format: [PROJECT-{id}] [TICKET-{id}] {description}

With composite IDs, this becomes: [PROJECT-LIN-1] [TICKET-LIN-1-NES-123] {description}

Observation: The ticket ID already contains the project ID (LIN-1-NES-123), making the project prefix redundant.

Option A: Keep both (as specified)

Commit: [PROJECT-LIN-1] [TICKET-LIN-1-NES-123] Implement feature
✅ Explicit project reference
⚠️ Redundant information
Option B: Ticket ID only

Commit: [TICKET-LIN-1-NES-123] Implement feature
✅ No redundancy
✅ Shorter commit messages
⚠️ Must parse ticket ID to extract project ID
Option C: Structured footer

Commit message body, then footer:

Implement feature
Project: LIN-1
Ticket: LIN-1-NES-123
✅ Cleaner subject line
✅ Structured metadata
⚠️ Requires footer parsing
Which format should we use?

A. Option A: Keep both [PROJECT-X] [TICKET-Y]

B. Option B: Ticket ID only [TICKET-X]

C. Option C: Structured footer

---

1. Can't we use WAL to push sqlite to queue?
2. We clean up an investigation worktree when we're done evaluating the error. We pass our findings on to workflow agent that actually fixes it by persisting.
3. monitored-run shouldn't create any context. We wrap agent runner in @step. monitored run creates our safe wrapper.
4. We only use the ticket id then for the commit message

---

Final conclusions (source of truth) + drift report + integration fixes

This document has three parts:

1) **Final decisions & constraints** as established by the conversation (including pivots).

2) **Plan drift**: where the three plan documents disagree with the final decisions.

3) **Proposed fixes**: concrete updates to bring plans back in sync (with light research where relevant).

## 1) Final decisions & constraints (from the conversation)

### 1.1 Non-negotiable constraints / scope

- **Local-only dev-machine project** (not distributed; DB files not committed). (User note in current request.)

- `workflow.db` must be **gitignored** (and therefore also its `-wal/-shm` files). fileciteturn9file5L1-L1

- **No Traycer integration**: documentation must be loaded manually (pasted or via file paths). fileciteturn7file13L30-L30 fileciteturn8file12L2-L2

### 1.2 Persistence & “Linear” (major pivot)

**Final state:** store project artifacts in **SQLite only**; **do not store/sync to Linear**. fileciteturn5file16L1-L3  

(There is earlier text that proposed storing artifacts in Linear fileciteturn7file1L39-L40, but it is superseded by the later pivot above.)

### 1.3 Worktrees, branches, merge-back

- Branching:

  - Project: `project/{PROJECT-ID}` from the user’s current branch fileciteturn7file16L12-L15

  - Ticket: `ticket/{TICKET-ID}` from the project branch fileciteturn7file16L13-L15

- Merge-back: **always merge to where we branched from** (ticket → project → original). fileciteturn7file16L15-L18 fileciteturn7file14L3-L3

- Cleanup: delete branches after merge. fileciteturn7file16L18-L18

- Reopen/resume:

  - Project discovery uses scanning for worktrees/open projects (plus python helper). fileciteturn7file6L3-L4

  - Ticket resume checks whether the ticket worktree exists (python helper). fileciteturn7file6L4-L4

- Project manager and ticket managers: project manager has its own worktree; ticket worktrees branch from it. fileciteturn7file4L63-L64

### 1.4 Ticket manager vs task execution (role separation)

- **Ticket manager is not the workflow that calls the decomposition script**; it’s part of a larger workflow. fileciteturn10file9L7-L7

- Users interactively add tasks until attempting to close ticket; close runs reviews + rebase + merge. fileciteturn7file4L37-L40

### 1.5 Task input format & decomposition behavior

- Task input is **free-form natural language**; there is **no rigid format**, but step boundaries must be “obvious enough” for the decomposition pipeline to split without rewriting. fileciteturn9file1L20-L27

- **No max-iterations** for decomposition convergence. fileciteturn9file13L1-L3 fileciteturn10file14L89-L90

  - Track file-level split/deny history; if the system cannot improve, it must mark the problem and move on. fileciteturn7file15L1-L1

### 1.6 Context & deviations

- Context manager uses **incremental diffs** (not recomputing all prior diffs each step). fileciteturn6file4L38-L39

- Deviations are tracked for review agents; users typically do **not** see them directly. fileciteturn9file5L2-L2

### 1.7 Logging, @step, monitored-run (major pivot)

- Rename `@log_step` → `@step`; it both logs and manages context automatically. fileciteturn6file4L6-L6 fileciteturn10file1L7-L8

- `monitored-run` must **not** create step context; agent runner is wrapped in `@step`; `monitored-run` is only the safe wrapper. fileciteturn10file14L86-L87

- Exceptions:

  - Don’t broadly try/catch; exceptions should be visible to agents; only catch connection-like issues. fileciteturn7file14L4-L4

### 1.8 Monitoring: from “cycle detection” → “investigate first” → “trace escalation”

- Monitoring/UI update pattern:

  - Use an **append-only queue** semantics; UI reads from a position onward (not “consumed”). fileciteturn9file13L3-L3

- False-positive avoidance: investigate before kill (do not kill purely on “long time”). fileciteturn7file14L1-L1

- Latest pivot: workflows/steps can start in **trace mode**, and trace can be increased for selected steps/workflows; this reduces need for isolated simulations. fileciteturn10file14L89-L90

### 1.9 UI interaction decisions

- UI is a standalone application; user must add project folders to monitor. fileciteturn9file8L47-L47

- Notifications: “notification center”. fileciteturn9file8L48-L48

### 1.10 Commit message format (pivot)

- Commit message prefix uses **ticket ID only**. fileciteturn10file14L87-L87  

(Tech Plan already reflects this fileciteturn7file16L20-L22; Core Flows does not.)

## 2) Drift analysis (plans vs final decisions)

### 2.1 Epic Brief drift (Epic_Brief__Multi-Layered_Project_Management_System.md)

1) **Still claims artifacts are persisted to Linear**  

- Epic Brief: “persists all artifacts … to Linear” fileciteturn8file0L5-L5  

- Final decision: SQLite only; no Linear fileciteturn5file16L1-L3

2) **Overstates “integrated” planning bridge**  

- Epic Brief frames a “bridge” with Traycer/Linear that reads like deep integration fileciteturn8file0L5-L5  

- Final decision: no Traycer integration; docs manually loaded fileciteturn7file13L30-L30 fileciteturn8file12L2-L2

### 2.2 Core Flows drift (Core_Flows__Project_Management_&_Autonomous_Monitoring.md)

1) **Linear integration present**

- “Exit: Project archived, Linear updated” fileciteturn8file8L1-L3  

- Final decision: no Linear fileciteturn5file16L1-L3

2) **Rebase flow still fetches from Linear**

- Rebase sequence: “Rebase → Linear: Fetch project docs (both)” fileciteturn9file7L15-L19  

- Final decision: rebase queries SQLite; no Linear fileciteturn7file16L1-L11 fileciteturn5file16L1-L3

3) **UI uses polling every 500ms**

- “Backend polls databases every 500ms for new log entries” fileciteturn9file11L10-L15  

- Final decision: message-queue semantics (not polling) fileciteturn10file1L1-L2 fileciteturn9file13L3-L3

4) **Ticket manager explicitly invokes decomposition agent**

- Flow 5: “Ticket manager invokes decomposition agent” fileciteturn8file5L23-L33  

- Final decision: ticket manager is not the component that calls that decomposition script; it’s inside a larger workflow fileciteturn10file9L7-L7

5) **Logging capture ownership: agent-runner creates IDs**

- Core Flows states AgentRunner assigns step execution IDs and stores logs fileciteturn8file8L21-L28  

- Final decision: `@step` is the mechanism that creates step context automatically; monitored-run should not create step context fileciteturn10file14L86-L87

6) **Monitoring still kills based on anomaly timing baseline**

- Core Flows monitoring: “Detect anomalies when step exceeds expected duration” and then kill/repair fileciteturn9file11L45-L57  

- Final decision/pivot: investigate first; tracing escalation; kill only after evidence fileciteturn7file14L1-L1 fileciteturn10file14L89-L90

7) **Commit message format mismatch**

- Core Flows still describes `[PROJECT-{id}] [TICKET-{id}]` prefix (in multiple places; e.g. “Commit message format: [PROJECT-{id}] [TICKET-{id}] …” fileciteturn7file9L35-L37)  

- Final decision: ticket-only prefix fileciteturn10file14L87-L87

### 2.3 Tech Plan drift (Tech_Plan__Multi-Layered_Project_Management_&_Autonomous_Monitoring.md)

1) **Internal contradiction: “No external API dependencies” but “synced to Linear”**

- “✅ No external API dependencies” and also “⚠️ Artifacts only synced to Linear on project completion” fileciteturn10file5L39-L43  

- Final decision: no Linear fileciteturn5file16L1-L3

2) **Rebase flow still says project IDs come from `[PROJECT-{id}]` prefix**

- “Extract project IDs from commit messages (`[PROJECT-{id}]` prefix)” fileciteturn7file16L6-L7  

- But commit message format is ticket-only fileciteturn7file16L20-L22

3) **WAL described as “uncommitted changes”**

- “WAL file contains uncommitted changes” fileciteturn10file7L8-L11  

- SQLite WAL is an append-only log for WAL-mode operation; it is part of the persistent DB state, and should be treated as such rather than a directly parsed “uncommitted” stream. citeturn0search0turn0search4

4) **UI concurrency decision missing**

- Conversation chose read-only connection to reduce contention (PRAGMA query_only=1). fileciteturn10file0L11-L27  

- Tech Plan does not explicitly include `query_only`/read-only connection as a first-class requirement (in the cited sections).

5) **Parallel “investigation worktree” is still the default diagnostic strategy**

- Tech Plan includes “Create investigation worktree … execute with instrumentation” fileciteturn9file3L8-L13  

- Latest pivot: tracing escalation can eliminate many “isolated simulations”. fileciteturn10file14L89-L90

6) **monitored-run responsibilities**

- Conversation: monitored-run should not create context; @step wraps agent runner fileciteturn10file14L86-L87  

- Tech Plan needs a crisp statement that monitored-run never creates step records, only safety/process control.

## 3) Proposed fixes (integrate correct answers into plans)

### 3.1 Global edits (apply to all docs)

1) **Explicitly scope the project as local-only**

- Add a “Scope/Assumptions” block: local dev machines only; DB files not committed; no cloud/distributed components; no external brokers.

2) **Standardize persistence**

- Replace all “persist to Linear” / “sync to Linear” / “fetch from Linear” with:

  - Persist artifacts in `workflow.db` only (and export to files for user consumption when needed).

  - Rebase reads conflict documentation from `workflow.db` (same repo constraint remains).

3) **.gitignore**

- Add `workflow.db`, `workflow.db-wal`, `workflow.db-shm` (and/or `*.db*`) to `.gitignore`.  

  Rationale: WAL mode uses sidecar files and SQLite warns WAL is part of persistent DB state. citeturn0search0

### 3.2 Replace “Linear integration” with “artifact export”

Where the plans previously updated Linear, replace with an **export pipeline**:

- `export_project.py --project {id} --out .tmp/exports/{id}/` produces:

  - `specs/`, `tickets/`, `tasks/`, `deviations/`, `conflict_resolutions/`, plus an `index.md`

- Project manager / rebase surfaces **file paths** to the user instead of pushing into Linear. This aligns with “file export; present filepath”. fileciteturn9file5L6-L6

### 3.3 UI updates: implement “queue semantics” without polling and without parsing WAL

**Problem:** Core Flows polls every 500ms fileciteturn9file11L10-L15, while the conversation expects queue semantics. fileciteturn9file13L3-L3

**Research-based recommendation:**

- Do **not** attempt to parse WAL frames directly; SQLite documents WAL format but it’s low-level and WAL is part of the DB’s persistent state. citeturn0search0turn0search4

- Do **not** rely on `sqlite3_update_hook` for cross-process notifications; it is connection-local. citeturn0search9turn0search17

- Preferred: keep the queue **in SQLite tables** and use a lightweight change signal.

**Concrete design (works on a single dev machine + WSL):**

1) Add a monotonic, append-only table for UI events (or treat `context_logs` as that queue):

   - `event_id INTEGER PRIMARY KEY AUTOINCREMENT`

   - `event_type`, `payload_json`, `created_at`, `(project_id, ticket_id, step_execution_id)` keys as needed.

2) UI maintains `{project_id -> last_event_id}` cursor.

3) UI uses **one** of these wake mechanisms:

   - **File-watch** `.db-wal` changes (debounced), then query for new rows. Tauri supports file watching via plugin APIs. citeturn0search15

   - Or **PRAGMA data_version** on a dedicated read-only connection; it changes when other connections commit, including across processes. citeturn1search0turn1search2

4) UI connection should be **read-only** (`PRAGMA query_only=1`) per the conversation. fileciteturn10file0L11-L27

**Doc updates required:**

- Core Flows Flow 12: replace polling loop with “wait for change signal, then fetch `event_id > last_event_id`”.

- Tech Plan §8: revise language:

  - WAL is a **signal** (or use `data_version`), not the message queue contents.

### 3.4 Fix monitored-run vs @step ownership

**Target state:** monitored-run is safety only; `@step` creates step execution records and context. fileciteturn10file14L86-L87

**Implementation guidance to encode in Tech Plan/Core Flows:**

- `@step`:

  - creates `step_executions` row

  - pushes/pops a thread-local stack for nesting

  - logs start/end + explicit `logger.log_*` events

- monitored-run:

  - starts a subprocess in its own process group

  - captures PID/PGID for kill

  - (optional) prints PID and forwards stdout/stderr

  - **does not** write `step_executions` rows

### 3.5 Update task/ticket workflow responsibilities (Ticket Manager vs Task Executor)

Adjust Core Flows Flow 5/6:

- Ticket manager:

  - accepts task input

  - writes `task_input.md`

  - invokes **task executor workflow**

- Task executor workflow:

  - runs decomposition agent + splitting script

  - runs step execution loop + context manager + review

This matches the “script is inside a larger workflow; ticket manager is not the one that calls it” pivot. fileciteturn10file9L7-L7

### 3.6 Monitoring: align to “investigate first” + “trace escalation”

Update Core Flows Flow 13:

- Replace “kill on anomaly duration” with:

  1) detect “long-running” (time is just a trigger)

  2) **increase tracing** for that workflow/step (function call tracing + timing) fileciteturn10file14L89-L90

  3) evaluate evidence (long call vs stuck loop vs exception/retry pattern)

  4) kill only if bug confirmed fileciteturn7file14L1-L1

- Keep “investigation worktree” as **optional** (e.g., for reproducing a fix), and always cleanup when done fileciteturn10file14L85-L85

### 3.7 Commit parsing + rebase metadata fix

To resolve Tech Plan inconsistency:

- Rebase should not depend on `[PROJECT-{id}]` when commit prefix is ticket-only. fileciteturn7file16L6-L7 fileciteturn7file16L20-L22  

**Fix options (pick one and write it into the Tech Plan/Core Flows):**

- Preferred: store `{commit_sha -> ticket_id, project_id}` in SQLite at ticket-close time; rebase uses SQLite lookup by commit_sha.

- Minimum: parse `[TICKET-{ticket_id}]` from commit subject and derive project_id from the ticket_id prefix.

## 4) “Open” items (asked, not answered explicitly)

The last conversation introduces a question rather than a finalized answer:

- “Can’t we use WAL to push sqlite to queue?” fileciteturn10file14L84-L84

Given the local-only constraint plus the research above, the recommended interpretation is:

- **Use WAL (or PRAGMA data_version) as a change signal**, but keep the actual queue as an **append-only SQLite table**. citeturn0search0turn0search4turn1search0turn1search2

---

P0 risks and concrete fixes

1) Windows UI ↔ WSL repo + SQLite WAL is a high-risk combination

Risk: Your UI plan explicitly targets “Windows UI can monitor WSL workflows” while also relying on SQLite WAL mode and direct file access to workflow.db inside the repo. WAL relies on shared-memory coordination (-shm/-wal), and SQLite explicitly warns WAL “does not work over a network filesystem” because readers coordinate via shared memory. (SQLite) Observed gap: There are real-world failures where Windows GUI tools can’t reliably open SQLite DBs stored in WSL via \\wsl$\... even though copying the DB to a Windows path works. (GitHub) Fix options (pick one as the “supported” path):

1. Run the Tauri UI inside WSL/Linux (same filesystem semantics as the writers). Most reliable with WAL.
2. Keep repos + DB on the Windows filesystem (e.g., C:\...) and run both writers + UI against that DB path (avoid \\wsl$).
3. Split the system into “local-only bridge”: keep DB in WSL, but run a small local process inside WSL that reads the DB and streams events to the Windows UI via localhost IPC. This stays “local machine only” while avoiding cross-filesystem WAL edge cases.
4. If you insist on \\wsl$ direct reads: drop WAL for those repos (use DELETE journal mode) and accept reduced concurrency/performance. (This conflicts with the current plan assumptions and will ripple into monitoring reliability.) (SQLite)

2) UI “read-only connection” conflicts with UI actions that write

Risk: The UI plan sets PRAGMA query_only = 1 and intends a read-only monitoring connection, but the same design includes commands like acknowledge_error() which implies updating DB state. This is a direct contradiction that will either fail at runtime or silently force you into “write-capable UI connections” and contention. (SQLite) Fix: Make a hard architectural choice:

- Option A (recommended): UI is truly read-only. Store UI-only state (acknowledged errors, dismissed banners, UI filters) in ~/.workflow-monitor.json (or a separate UI-local sqlite). Never write to workflow.db from the UI.
- Option B: UI can write, but only through a dedicated “control” channel with strict scoping and short transactions; do not share the same long-lived read connection. Open a second connection just-in-time for single updates, with busy_timeout and immediate close. (SQLite)

3) SQLite write contention from “high-frequency logging across many processes”

Risk: The DB is the single event pipeline. Multiple terminal processes (ticket-manager, monitor, rebase agent, etc.) will produce a lot of context_logs rows. SQLite WAL allows concurrent readers and writers, but only one writer at a time, so bursts of log writes can cause SQLITE_BUSY / “database is locked” and/or slowdowns. (SQLite) Fixes:

- Batch log writes: buffer events in-process and flush in a single transaction per step / per second (instead of commit per row).
- Keep write transactions extremely short and never hold write transactions open while doing LLM calls / subprocess work.
- Ensure every writer sets busy_timeout (you already propose this) and also implement retry-with-jitter for writes (because busy_timeout is not a universal guarantee). (SQLite)
- Add journal_size_limit to prevent WAL from ballooning when checkpoints are starved. (SQLite)
- If you use SQLAlchemy for logging, consider disabling pooling for file DBs via NullPool to reduce cross-thread surprises and stale connections. (SQLAlchemy)

4) WAL checkpoint starvation from long-lived readers

Risk: If the UI or monitor holds long read transactions, checkpoints can’t complete; WAL can grow and read performance degrades. SQLite WAL docs explicitly call this out (“a long-running read transaction can prevent a checkpointer from making progress”). (SQLite) Fix:

- In the UI, never use explicit BEGIN for polling. Make each poll query a single statement and ensure it completes quickly.
- If you do “streaming reads”, page by id and complete the statement quickly; do not keep cursors open.
- Consider manual checkpoints only during idle; otherwise rely on wal_autocheckpoint (default ~1000 pages) but monitor WAL size. (SQLite)

5) Process suspension/resume semantics are under-defined

Risk: You plan to “suspend_process(process_id)” and later “resume workflow from suspension point.” If suspension is implemented by killing processes (or even pausing), the “resume” behavior needs an explicit model:

- You cannot “resume” a killed process; you can only restart the workflow step from an idempotent checkpoint.
- If you pause, cross-platform support differs (Windows vs POSIX). Fix: Add explicit concepts to the data model and runner:
- step_executions.attempt (or retry_of_step_execution_id) so you can restart the same logical step and keep lineage.
- workflow_run_id (root execution group) so restarts don’t fragment UI views.
- Define “suspend” as (a) pause (best-effort) or (b) stop + mark checkpoint + restart from last safe step. Pick one and enforce it.

6) Cross-platform process-tree control will be brittle without process groups / job objects

Risk: Your monitoring/self-healing depends on reliably suspending/killing “child processes while leaving the root process alive.” That requires strong guarantees about process tree grouping on each OS. Best-practice guidance:

- psutil’s own “kill process tree” recipe relies on children(recursive=True) and wait_procs(). (Psutil Documentation)
- On Windows, console control signals require the target to be a process group; you generally need CREATE_NEW_PROCESS_GROUP at spawn time. (Discussions on Python.org) Fix: Standardize subprocess launch wrappers:
- POSIX: start_new_session=True (or setsid) so each step has a killable group.
- Windows: set creationflags=CREATE_NEW_PROCESS_GROUP for anything you’ll signal; for hard-kill, use psutil kill.
- Store both pid and a stable create_time (or equivalent) to avoid PID reuse bugs when resuming/repairing.

7) “Avoid max iterations” needs a different safety mechanism (looping risk)

Risk: Multiple docs explicitly avoid max-iteration limits (decomposition loops, repair loops, evaluation loops). That increases the risk of:

- endless refinement loops
- self-healing oscillations (fix → new error → revert → repeat)
- ticket planning thrash Fix (no max-iteration cap required): implement “progress-based circuit breakers”:
- State hash + repetition detection: compute a hash of the plan/spec/artifact each cycle; if the hash repeats with no new evidence added, transition to BLOCKED_NEEDS_HUMAN.
- Novelty requirement: each iteration must either (a) add a new acceptance criterion, (b) reduce an explicit unresolved list, or (c) produce a new reproduction result. If not, stop.
- Failure signature escalation: if the same error signature occurs after an attempted fix (same stack + same failing command), stop and surface “human decision required”. These are termination conditions based on lack of progress, not an arbitrary iteration count.

P1 improvements that will materially raise reliability

8) Normalize terminology: “repo”, “project”, and “project_id” are overloaded

Risk: The UI config calls monitored items “projects” (paths), but the DB has projects (tracked work items), and other docs refer to project_id as the conceptual root for tickets. This will cause API confusion and incorrect UI behaviors (especially in multi-repo). Fix: Rename and reframe:

- UI config: repositories: [{ repo_root, display_name, last_log_id }]
- DB: keep projects as project-management entities inside a repo
- IPC: add_repository(path) not add_project(path); get_projects(repo_root) returns DB projects.

9) Use PRAGMA data_version as your primary UI “change detector”

Your UI already proposes it as option B; make it the default. SQLite explicitly documents PRAGMA data_version for interactive programs to detect when the DB changed and they need to refresh UI state. (SQLite) Why it’s better than filesystem watching:

- works even when WAL is overwritten/recycled
- avoids platform-dependent file notification semantics
- avoids missing “change” events when only -shm mutates

Implementation detail: compare data_version on the same connection; SQLite states it’s only meaningful that way. (SQLite)

10) Add schema versioning + migrations even though DB is local and not committed

Risk: Local DBs persist across runs; schema drift will break older tools and UIs, and you’ll be forced into “delete DB” as the only recovery. Fix:

- Create schema_migrations(version INTEGER PRIMARY KEY, applied_at)
- On startup: migrate forward deterministically
- Provide workflow-db reset (wipe) and workflow-db export (debug bundle)

11) Add indexes for the queries you explicitly plan to run

Risk: UI polling and monitor polling will become slow as context_logs grows. Fix: minimum index set

- context_logs(step_execution_id, id) (for paging)
- context_logs(id) already implied by PK; keep AUTOINCREMENT if you need monotonicity
- context_logs(timestamp) if you query by time
- step_executions(status, start_time) for “stuck running”
- errors(acknowledged, created_at) for UI/monitor views
- tickets(project_id, status) for project views

12) Make event schemas explicit (and versioned)

Risk: context_logs.data is JSON with no schema. Over time, you’ll accumulate unparseable and inconsistent payloads; UI breakage will follow. Fix:

- Define event_type enum list + JSON schema per type (even if informal)
- Add schema_version integer column to context_logs
- Add redaction rules (mask secrets) before writing logs

P2 improvements (lower risk, still worthwhile)

13) Git metadata: commit message trailers are a better ticket-linking mechanism than parsing subjects

Your conflict-resolution and evaluation plans depend heavily on extracting ticket IDs from commits. That’s fragile if you squash/rewrite or if subject lines change. Best practice: Use Git trailers (RFC-822-like footer lines) for structured metadata; Git has first-class tooling to parse/add trailers. (Git SCM) Example:

Ticket-ID: TICKET-123 Project-ID: PROJ-01 

If you need metadata without changing commit hashes, Git Notes exist (but require extra handling to push/share). (Git SCM)

14) Worktree lifecycle: enforce cleanup rules and handle “unclean worktree” behavior

You will create many worktrees (tickets, investigation, evaluation). Git’s worktree remove only removes clean worktrees unless forced. (Git SCM) Fix:

- Standardize a worktree gc command:
  - checks status
  - archives patches if dirty
  - then removes (with --force only if explicitly allowed)

Gaps that are not explicitly addressed in the docs (and solutions)

Gap A) No single “workflow run” entity

You rely on step_executions hierarchy, but there’s no explicit workflow_runs table to group related attempts, restarts, evaluation runs, etc. Solution: Add:

- workflow_runs(run_id TEXT PK, repo_root, project_id, ticket_id, created_at, status)
- step_executions.run_id FK This makes UI grouping and “resume” semantics deterministic.

Gap B) Error IDs + concurrency

You propose human-friendly IDs like ERR-001. With concurrent writers, generating sequential strings safely is non-trivial. Solution: Use an integer PK and generate the formatted ID as a view/computed string (or store both). Example:

- errors(id INTEGER PRIMARY KEY, error_id TEXT UNIQUE GENERATED …) (or generated in code from id)

Gap C) UI “acknowledged” is ambiguous: user preference vs system state

If “acknowledged” affects monitor behavior, it’s system state and belongs in DB. If it’s just UI noise suppression, it belongs in UI-local state. Solution: Split:

- errors.resolution_state (system) vs ui_ack_state (local UI)

Gap D) Context stack implementation should be async-safe

Your StepLogger/context stack approach describes a stack; if any part of the system becomes async (or uses thread pools), thread-local stacks will leak context across tasks. Solution: Use contextvars for trace context propagation (safe across async tasks), and only fall back to thread-local where needed.

Gap E) Safety boundaries for self-healing code execution

You plan JIT scripts and auto-apply fixes. Without strict boundaries, a bad repair can damage the repo or dev machine. Solution set:

- Run JIT scripts in a temp sandbox directory
- Disallow writes outside repo/worktree root
- Deny modifying .git/
- Require every repair to produce a patch + commit, never direct working tree mutation
- Record “repair provenance” (inputs, prompt hash, tool outputs) in DB for audit

Best-practice settings and patterns to adopt (aligned to your design)

SQLite PRAGMAs (writers)

- journal_mode=WAL for concurrency (SQLite)
- foreign_keys=ON because SQLite defaults to OFF and shouldn’t be relied on (SQLite)
- busy_timeout=5000+ (and still do retry/backoff) (SQLite)
- Consider synchronous=NORMAL for WAL if performance matters and you accept reduced durability across power loss (still safe from corruption in WAL) (SQLite)
- Keep wal_autocheckpoint default or tune it; understand it’s PASSIVE and may not complete if readers are active (SQLite)
- Add journal_size_limit to control WAL file growth (SQLite)

SQLite change detection (UI)

- PRAGMA data_version as the primary “did anything change?” signal (SQLite)
- PRAGMA query_only=1 to enforce no writes (SQLite)

WAL file handling (copying/moving DBs, worktrees, exports)

- The WAL file is part of the persistent database state; separating it from the DB can lose committed transactions or corrupt the DB. (SQLite) This matters for any “copy state to investigation worktree” logic and for exporting debug bundles.

Tauri IPC security hardening (even for local-only apps)

Your UI will cross a trust boundary (WebView ↔ Rust core). Tauri emphasizes defining boundaries and restricting IPC command access with capabilities/permissions/scopes. (Tauri) Minimum: scope file access to repo roots only; deny everything else by default.

Prioritized implementation backlog

P0 (do first)

1. Decide and document the supported WSL/Windows topology (recommended: UI runs where DB lives).
2. Resolve the UI read-only vs writes contradiction (move “ack” to UI-local state or add a separate short-lived write connection).
3. Add progress-based circuit breakers for all “no max iteration” loops (decomposition, repair, evaluation).
4. Standardize subprocess spawning for process-group/job control across OSes; store additional identity fields to avoid PID reuse. (Discussions on Python.org)

P1

1. Add schema versioning + migrations.
2. Add core indexes + log batching.
3. Introduce workflow_run_id + step attempt lineage to make suspend/resume and evaluation deterministic.

P2

1. Adopt Git trailers for Ticket-ID/Project-ID metadata; stop relying on commit subject parsing. (Git SCM)
2. Build a single worktree gc tool and enforce cleanup rules. (Git SCM)

---

PostgreSQL vs SQLite+daemon (given your actual intent)

Given “many independent processes” (many agents) will all write to the same store, PostgreSQL is the better fit than SQLite behind a daemon. SQLite is fundamentally a single-writer database; you can hide that behind a daemon, but then you’ve re-created a central coordinator and all writers are no longer truly independent.

PGDATA is not a single file

PostgreSQL persists data as a data directory containing many files. In Docker, you persist that directory via a volume or bind mount, not a single file. The official image also has version-specific PGDATA behavior in PostgreSQL 18+ and guidance on where to mount volumes depending on major version. (Docker Hub)

If you want a “single file artifact” for portability/debug:

- use pg_dump to a single dump file (plain SQL or custom format). (That’s backup/export, not live storage.)

Answers to all P0 decisions/questions (updated for PostgreSQL)

P0-1: What is the supported WSL/Windows topology?

Answer / Decision: Run one local Postgres instance (Docker container is fine), and have all agents + UI connect over TCP. Do not share DB files between WSL and Windows.

Why this matches your design intent:

- still local-only on one dev machine
- supports many concurrent writers
- avoids all cross-filesystem locking/WAL semantics

Concrete implementation:

- Pin a Postgres major version (e.g., 17 or 18) to avoid surprise changes.
- Persist data with a Docker volume at the image’s expected mount point (see PGDATA notes above). (Docker Hub)

Design gap you must address when you centralize the DB: Repo identity and paths become ambiguous across WSL and Windows.

- Agents in WSL will report /home/.../repo
- Windows UI will want C:\... or may not access the repo filesystem at all

Solution (no questions, just the recommended approach):

- Introduce a repositories table keyed by a stable repo_id and store multiple path aliases:
  - repo_id
  - wsl_root (nullable)
  - windows_root (nullable)
  - display_name
- Agents upsert (repo_id, wsl_root); UI optionally upserts (repo_id, windows_root).
- Any “open file” UI feature uses the correct root for that platform; monitoring itself does not require filesystem access.

P0-2: Should the UI be read-only or allowed to write?

Answer / Decision: UI remains read-mostly, and any “write-ish” actions become append-only control requests, not direct mutation of operational tables.

This resolves your earlier contradiction (read-only connection vs acknowledge_error()).

Implementation pattern (recommended):

- Create a control_actions table:
  - id bigserial pk
  - repo_id
  - action_type (ACK_ERROR, SET_TRACE_LEVEL, RESTART_STEP, SUSPEND_PROCESS, …)
  - payload jsonb
  - requested_by
  - created_at
  - status (PENDING, APPLIED, REJECTED, FAILED)
  - applied_at, error_message
- UI writes: INSERT into control_actions only
- Monitoring agent (or process supervisor) reads and applies actions, and is the only component that updates:
  - errors lifecycle
  - suspended_processes
  - any “restart/resume” bookkeeping

Why this is better than letting UI directly UPDATE tables:

- avoids race conditions with agents that own a given row
- keeps UI privileges minimal
- works cleanly across WSL/Windows (UI doesn’t need to spawn/kill processes itself)

If you want real-time responsiveness: after inserting a control action, emit a NOTIFY with just the action id (see monitoring changes below). Keep payload tiny. (PostgreSQL)

P0-3: How do we prevent “write contention becomes constant” with many writers?

Postgres handles concurrent writers, but you can still shoot yourself in the foot with connection storms and chatty writes.

Answer / Decision:

1. Batch log writes (especially context_logs)
2. Keep transactions short
3. Control connection counts

Concrete rules (no max-iteration rules involved):

- Each agent process holds one long-lived connection (or a very small local pool of 1–2).
- Log inserts are buffered and flushed:
  - at step boundary, or
  - on a short time slice (e.g., 100–250ms), or
  - when buffer exceeds N rows/bytes
- Each flush is one transaction with multi-row insert (or COPY if you want maximum throughput later).

If you discover you’re hitting Postgres max_connections:

- add a local connection pooler like pgBouncer (still local, still not “distributed”), or
- enforce “1 connection per process” and reuse it.

P0-4: What replaces SQLite WAL signaling / data_version? How does monitoring change?

Answer / Decision: Use LISTEN/NOTIFY for low-latency hints + cursor-based polling as correctness backbone.

Why:

- NOTIFY is great for “wake up and fetch,” but payload size is limited, and notifications can be missed if a listener is disconnected.
- Polling by an ever-increasing id is simple and correct.

Best-practice wiring

- Writers append rows (logs / status changes).
- At the end of a batch transaction, the writer sends:
  - NOTIFY workflow_events, '<tiny payload>'

Payload must be < 8000 bytes by default; don’t send the full log JSON, send ids/high-water marks. (PostgreSQL)

UI backend behavior

- Maintain per-repo cursors:
  - last_context_log_id
  - last_error_id
  - last_step_update_ts (or last_step_event_id if you add an event table)
- On NOTIFY: query WHERE id > cursor ORDER BY id LIMIT … and stream to frontend.
- Also poll every ~500ms–2s as a safety net.

P0-5: What is the suspend/resume semantic (since “resume” isn’t OS-level reliable)?

Answer / Decision: “Suspend” means stop execution + record checkpoint + restart from last safe step, not “pause a process and resume it later.”

Data model changes you should make immediately:

- Add workflow_runs (explicit run grouping)
- Add step_execution_attempts or attempt column:
  - every restart is a new attempt referencing the prior attempt
- suspended_processes should point to a run/step and record:
  - why it was suspended
  - what the safe restart point is
  - who requested it (monitor vs user)

This makes “resume” deterministic and cross-platform.

P0-6: How do we make process-tree control reliable cross-platform?

Answer / Decision: Standardize subprocess launch so every step has a killable group, and store enough identity to avoid PID reuse bugs.

Concrete standards:

- POSIX/WSL: spawn with a new session/process group (so you can terminate the tree).
- Windows: spawn with a new process group when you need console signals; otherwise rely on process-tree termination by enumeration.

Also store:

- pid
- started_at
- optionally create_time (from psutil) to disambiguate reused pids

P0-7: If you “always avoid max iterations,” how do you stop runaway loops safely?

Answer / Decision: Use progress-based circuit breakers and repeat detection, not iteration caps.

These are deterministic stop conditions:

- State hash repeat: hash the plan/spec/artifact + “evidence set”; if the same hash appears again without new evidence, stop and escalate.
- Novelty requirement: every cycle must reduce an explicit “open issues” set or add new reproducible evidence (new failing test, new trace segment, new minimized repro). If not, stop.
- Oscillation detection: detect revert/redo patterns (A→B→A) in patches or in step outcomes; stop and require human decision.
- Failure signature repetition: if the same failure signature occurs after an attempted fix and verification shows no delta, stop.

Record the reason for stopping in DB so UI can show “why the system halted.”

Answers to all P1 decisions/questions (updated for PostgreSQL)

P1-8: How do we fix the “repo vs project vs project_id” overload?

Answer / Decision: Rename and separate concepts:

- Repository: a codebase root (what UI currently calls “project folder”)
- Project: your internal managed project entity
- Ticket: unit of work under a project

Concrete actions:

- UI: add_repository() not add_project()
- DB: add repositories table and make projects.repo_id a foreign key

P1-9: What is the primary UI change detector now?

Answer / Decision: LISTEN/NOTIFY for wakeups + cursor polling for correctness. (SQLite data_version is gone.) (PostgreSQL)

P1-10: Do we still need schema versioning and migrations?

Answer / Decision: Yes, and it becomes more important with Postgres because you’ll have a real shared DB across many tools.

Concrete approach:

- Use Alembic (if staying with SQLAlchemy) and require:
  - “schema version must be current on startup”
  - automatic upgrade path for dev (or a one-liner workflow db migrate)
- Keep schema_migrations / alembic version table and never require “delete DB to fix.”

P1-11: What indexes/retention do we need (now that logs can grow fast)?

Answer / Decision: Add indexes for your hot paths and implement retention.

Minimum indexes (based on your query patterns):

- context_logs (repo_id, id)
- context_logs (step_execution_id, id)
- step_executions (repo_id, status, start_time)
- errors (repo_id, status, created_at)
- tickets (project_id, status)

Retention (highly recommended):

- For context_logs, implement:
  - “keep last N days” or
  - “keep last N runs per repo”
- Do deletion in batches to avoid big spikes.

This avoids the UI and monitor degrading over time on long-lived dev machines.

P1-12: How do we make event/log schemas stable?

Answer / Decision: Treat event payloads as versioned contracts.

Concrete rules:

- Every log row has:
  - event_type
  - schema_version
  - data jsonb
- Maintain a registry in code:
  - expected keys
  - redaction rules
  - backward-compat parsing in UI

P1: Postgres-specific “gotcha” you must handle: long-running transactions

In Postgres, long-running or “idle in transaction” sessions can block cleanup and contribute to bloat; timeouts exist specifically to prevent this. (Google Cloud)

Answer / Decision: Enforce short transactions and set timeouts for UI/monitor roles:

- idle_in_transaction_session_timeout for UI connections (terminate stuck UI sessions holding locks). (PostgreSQL)
- Keep UI in autocommit; do not hold explicit transactions open while rendering/polling.

Answers to all P2 decisions/questions (still applicable)

P2-13: How should commits link to tickets reliably?

Answer / Decision: Use Git commit trailers for structured metadata (not subject parsing).

- Ticket-ID: LIN-1-NES-123
- Project-ID: LIN-1

This is robust under squash/rebase and easy to parse with Git tooling.

P2-14: How do we manage worktree lifecycle safely (especially dirty worktrees)?

Answer / Decision: Implement a single worktree gc command that:

- enumerates worktrees
- detects dirty state
- auto-archives a patch (or refuses unless forced)
- removes worktree + branch safely

This prevents “worktree sprawl” from evaluation/investigation flows.

Additional changes implied by choosing PostgreSQL (to keep your design coherent)

Replace “copy SQLite DB to investigation worktree”

Your state_copier.py concept must change.

Recommended replacement (fits your design intent):

- “Run Snapshot Export”:
  - export a run (or ticket) slice from Postgres to a JSON artifact bundle
  - include: step tree, logs, errors, deviations, conclusions
- Store it under the investigation/evaluation worktree as an artifact (not a live DB copy)
- UI can load it as an offline “replay” view if desired

Monitoring architecture (final recommended shape)

1. All writers write to Postgres (batched inserts, short transactions).
2. Writers optionally NOTIFY workflow_events with {repo_id, high_water_mark_ids} only. Payload must stay small. (PostgreSQL)
3. UI backend:
  - one connection LISTENing
  - one pooled connection for queries
  - cursor polling fallback
4. Monitor agent:
  - LISTENs for control_actions (or polls)
  - applies actions and writes resulting state changes

This directly answers the earlier “options” question: file watching and SQLite PRAGMAs are replaced by database-native async notifications plus cursors.

If you want the minimal “diff” against your current specs: it is primarily (1) swap SQLite URLs/PRAGMAs for Postgres connections/roles, (2) replace WAL watchers with LISTEN/NOTIFY + cursors, (3) introduce repositories + workflow_runs + control_actions, and (4) replace DB-file copying with run-snapshot exports.

---

Here's the feedback that needs to be applied to my changes (current issues).



Expected state from the conversation patches (canonical)

- DB: single local PostgreSQL instance (often Docker), persisted as a PGDATA directory/volume; no “shared DB files” between WSL and Windows.
- Cross-platform: all agents + UI connect to Postgres over TCP (localhost / host.docker.internal); repo identity is a stable repo_id with path aliases (windows_root, wsl_root).
- UI updates: LISTEN/NOTIFY = wakeup only, with cursor reads for correctness.
- UI writes: UI is read-mostly; operational writes are append-only requests (INSERT control_actions). UI “acknowledge/hide” is local-only preference (not DB mutation).
- Suspend/resume: “Suspend” = terminate + checkpoint + restart from last safe step; lineage tracked via workflow runs + step attempts.
- No max-iteration caps: use progress-based circuit breakers (repeat/novelty/oscillation/signature stop conditions).
- Git metadata: ticket/project linkage via commit trailers (machine-parseable). Legacy subject parsing is fallback only.
- Reliability extras that must be present in plans:
  - worktree lifecycle GC (worktree gc)
  - log retention/pruning for context_logs
  - Postgres connection timeouts/hygiene for UI/monitor
  - safety boundaries for self-healing (sandbox + patch/commit trail + deny .git/ writes)
  - Tauri IPC hardening (scoped capabilities)

I captured the above as a “no drift baseline” document you can keep as an anchor:

- Download Conclusions__Expected_State.md

Verification: the big architectural patch landed correctly (no drift)

All the major docs consistently reflect the Postgres pivot and the core signaling/write model:

- Local-only Postgres + PGDATA volume semantics are explicit in the core infrastructure plan.
- LISTEN/NOTIFY + cursor reads are explicitly the UI change mechanism.
- Integration/file structure plan aligns to Postgres + no external brokers/queues.
- Monitoring/self-healing is written assuming Postgres-backed logs + run snapshot export (not DB-file copying).
- Epic brief aligns at the high level with the same local-only + UI concept.

So: no SQLite/WAL/WSL-filesystem drift remains in the uploaded plans.

Deviations found (where the uploaded plans diverge from the expected state)

1) Git metadata: several plans still rely on [TICKET-...] subject parsing (and trailer keys are inconsistent)

What the patched conversation expects

- Use commit trailers (e.g., Ticket-ID: / Project-ID:). Subject parsing is fallback only.

Drift found

- Core Flows: ticket closure commit format is explicitly [TICKET-{id}] {description}, and enhanced rebase flow extracts ticket IDs from [TICKET-{id}] prefix.
- Enhanced Rebase plan: flow step 3 extracts ticket IDs from [TICKET-{id}] prefix.
- Core Infrastructure plan: trailers are “preferred,” but the keys are Ticket: / Project: (not the canonical Ticket-ID: / Project-ID:), creating a cross-doc inconsistency.

Why this matters

- Rebase/conflict tooling becomes brittle under squash/rewrite; it’s exactly the failure mode the patch was trying to remove.

Fix

- Standardize on trailer keys (Ticket-ID, Project-ID) everywhere.
- Update rebase/conflict investigation to parse trailers first; fallback to legacy [TICKET-...] only for older commits.
- Add a shared trailers.py helper (parse + emit) so tools don’t reimplement parsing differently.

2) Task decomposition orchestration: Core Flows describes a single-pass “decomposition agent,” not the multi-pass orchestrator

What the patched conversation expects

- Decomposition is a multi-pass orchestrator (pattern discovery → candidate surfacing → approval → verification → recursion) with progress-based circuit breakers, invoked by the task execution workflow.

Drift found

- Core Flows: Flow 5 says the ticket manager directly invokes a decomposition agent that generates a split script, then ticket manager starts execution. This omits the orchestrator + multi-pass approval/verification loop and contradicts the more detailed project/ticket plan.
- Project & Ticket Management plan: explicitly says orchestrator is called by task execution workflow, not by ticket-manager directly.

Fix

- Update Core Flows Flow 5 so decomposition is the first phase of task execution and is implemented via the orchestrator.

3) Diff discipline: Core Flows says “diffs from all prior steps,” which conflicts with the incremental-diff design

What the patched conversation expects

- Context manager reviews incremental diffs to avoid quadratic growth.

Drift found

- Core Flows: Flow 6 says the step agent receives “Git diffs from all prior steps.”
- Core Infrastructure plan: explicitly advocates incremental diff review as a key pattern.

Fix

- Update Core Flows Flow 6 to specify incremental diff delivery (prev step → current).

4) Worktree lifecycle GC is missing from the plans (despite being a stated P2 decision in the patch)

What the patched conversation expects

- A single worktree gc tool that:
  - detects dirty worktrees
  - archives patches (or refuses unless forced)
  - removes worktrees/branches safely

Drift found

- No worktree gc command/spec is present in the integration/file structure or the project/ticket manager plan (they create/scan worktrees, but don’t define lifecycle cleanup rules).

Fix

- Add scripts/core/git/worktree_gc.py (or equivalent) to file structure + describe the command in the plans.

5) Log retention/pruning is missing (context_logs will grow without bound)

What the patched conversation expects

- A retention policy (keep N days or N runs) + batch deletion + a CLI entry point.

Drift found

- Core infrastructure defines context_logs as append-only but does not define a retention/pruning policy anywhere.

Fix

- Add retention policy + workflow db prune command to plans.

6) Postgres “idle in transaction” / timeouts are not specified in plans

What the patched conversation expects

- UI/monitor connections set statement_timeout and idle_in_transaction_session_timeout, and UI uses autocommit.

Drift found

- UI plan describes short-lived reads/autocommit behavior, but does not specify the timeout defaults as a requirement (role defaults or connection params).
- Core infrastructure plan does not define timeout policies.

Fix

- Add explicit DB timeout defaults for UI/monitor roles.

7) Self-healing safety boundaries (sandbox + deny .git/ writes + patch/commit trail) are underspecified

What the patched conversation expects

- Strong constraints: sandbox JIT scripts, deny out-of-root writes, deny .git/ mutation, require patch/commit trail, record provenance.

Drift found

- Monitoring/self-healing plan defines JIT scripts and convergence guards, but does not define the “do not damage repo/machine” boundaries in a concrete rule set.

Fix

- Add an explicit “Safety Boundaries for Self-Healing” section with enforceable constraints.

8) Tauri IPC security hardening is not described

What the patched conversation expects

- Even local-only, WebView ↔ Rust is a trust boundary; IPC commands should be scoped/capability-restricted.

Drift found

- Monitoring UI plan does not specify IPC/capability scoping or path validation rules (repo-root-only file access).

Fix

- Add “Security & IPC Hardening” requirements to the UI plan.

9) Minor internal inconsistency: control_actions suggests “ack” while UI “acknowledge” is local-only

What the patched conversation expects

- UI “hide/ack” is local preference; operational actions are control_actions.

Drift found

- Core infrastructure states acknowledge/hide is UI-local, but the control_actions.action_type comment lists ack as an action type, creating ambiguity.

Fix

- Rename/remove ack from control action taxonomy, or explicitly distinguish:
  - UI-local acknowledged (hide)
  - operational resolve_error / retry_after_fix (control action)

Proposed integrations (concrete) and patched plan files

I implemented the above corrections directly into patched copies of the plans (so you can diff them against the originals).

Patched plan documents (downloads)

- Core_Flows__Project_Management_&_Autonomous_Monitoring.patched.md
- Tech_Plan__Enhanced_Rebase_&_Evaluation.patched.md
- Tech_Plan__Core_Infrastructure_&_Data_Model.patched.md
- Tech_Plan__Integration_&_File_Structure.patched.md
- Tech_Plan__Monitoring_&_Self-Healing.patched.md
- Tech_Plan__Monitoring_UI_(Tauri).patched.md
- Tech_Plan__Project_&_Ticket_Management.patched.md

What changed (high signal)

1. Core Flows

- Flow 5 updated to: decomposition orchestrator is part of task execution (multi-pass + circuit breakers).
- Flow 6 updated to: incremental diffs, not “all prior diffs.”
- Flow 8 updated to: trailer-based commit metadata (Ticket-ID, Project-ID).
- Flow 9 updated to: trailer-first ticket extraction, prefix fallback.

1. Enhanced Rebase

- Trailer-first ticket extraction, prefix fallback.

1. Core Infrastructure & Data Model

- Trailer keys standardized to Ticket-ID / Project-ID.
- control_actions.action_type comment changed to avoid ambiguous “ack.”
- Added:
  - log retention/pruning requirements
  - Postgres connection hygiene/timeouts section
  - process_create_time column for PID reuse defense

1. Integration & File Structure

- Added scripts/core/git/ with:
  - trailers.py
  - worktree_gc.py
- Added a “Worktree Lifecycle GC” section.

1. Monitoring & Self-Healing

- Added explicit self-healing safety boundaries (sandbox, deny .git/, patch trail, provenance, destructive-action gate).

1. Monitoring UI

- Added IPC security hardening + DB timeout defaults.

If you want the fastest “integration checklist” (code implications)

- Create scripts/core/git/trailers.py and migrate:
  - commit creation (ticket/task closure)
  - rebase enhanced conflict analysis
- Implement worktree gc (one command; used by project manager + evaluation/investigation cleanup).
- Add workflow db prune to enforce context_logs retention.
- Add DB role defaults or connection parameters for UI:
  - autocommit
  - statement_timeout
  - idle_in_transaction_session_timeout
- Enforce self-healing boundaries in workflow-repair:
  - sandbox
  - out-of-root denylist
  - .git/ denylist
  - patch/commit required
  - provenance logging

This addresses every deviation listed above and aligns the plans to the patched conversation state.

---

Remaining Concerns (5 Issues)
Concern #1: Missing scripts/core/git/ Module in File Structure [MODERATE]
Issue: The Integration & File Structure spec describes worktree GC and trailers.py in the "Worktree Lifecycle Management" section, but the file structure tree doesn't include scripts/core/git/ directory.

Impact: Implementers may miss these critical components.

Current State:

✅ Worktree GC documented in prose
✅ trailers.py documented in prose
❌ scripts/core/git/ missing from file structure tree
Fix Required: Add to file structure in spec:1b2cab25-f5f3-4cdd-bce6-21b16a9e68b3/e1b2db49-9472-4be3-9af5-9e92a059fa85:


├── core/
│   ├── git/
│   │   ├── __init__.py
│   │   ├── trailers.py          # Git trailer parsing + emission
│   │   ├── worktree_gc.py       # Worktree lifecycle management
│   │   └── worktree_detection.py  # Detect project/ticket worktrees
Concern #2: Git Trailer Keys Inconsistency [MODERATE]
Issue: Core Infrastructure spec uses Ticket: / Project: while Core Flows uses Ticket-ID: / Project-ID:. This creates parsing ambiguity.

Current State:

Core Infrastructure (line ~180): "Trailer: Ticket-ID: {TICKET-ID}"
Core Flows (line ~120): "Ticket-ID: LIN-1-NES-123"
✅ Consistent in most places
⚠️ Need to verify trailers.py implementation uses correct keys
Recommendation: Standardize on Ticket-ID: and Project-ID: (with hyphen) everywhere. This is already mostly correct.

Concern #3: Missing ticket_dependencies Table in Schema [MODERATE]
Issue: Ticket 1 acceptance criteria mentions ticket_dependencies table (P1-6), but the Core Infrastructure spec doesn't define this table in the schema section.

Current State:

✅ Mentioned in Ticket 1 scope
❌ Not in Core Infrastructure spec schema section
Fix Required: Add to Core Infrastructure spec after tickets table:

sql

CREATE TABLE ticket_dependencies (
    id BIGSERIAL PRIMARY KEY,
    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,
    ticket_id TEXT NOT NULL,
    depends_on_ticket_id TEXT NOT NULL,
    dependency_type TEXT NOT NULL DEFAULT 'blocks',  -- blocks|related|parallel_safe
    inferred BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (repo_id, ticket_id) REFERENCES tickets (repo_id, ticket_id),
    FOREIGN KEY (repo_id, depends_on_ticket_id) REFERENCES tickets (repo_id, ticket_id),
    UNIQUE (repo_id, ticket_id, depends_on_ticket_id)
);
CREATE INDEX ticket_deps_repo_ticket_idx ON ticket_dependencies (repo_id, ticket_id);
Concern #4: repair_provenance Table Missing from Schema [MODERATE]
Issue: Monitoring & Self-Healing spec shows repair_provenance table in the Safety Boundaries section, but Core Infrastructure spec doesn't include it in the main schema section.

Current State:

✅ Shown in Monitoring & Self-Healing spec
✅ Mentioned in Ticket 1
❌ Not in Core Infrastructure spec's main schema section
Fix Required: Add to Core Infrastructure spec after investigation_conclusions table:

sql

CREATE TABLE repair_provenance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,
    step_execution_id UUID NOT NULL REFERENCES step_executions(step_execution_id) ON DELETE CASCADE,
    repair_type TEXT NOT NULL,
    inputs JSONB NOT NULL,
    prompt_hash TEXT NOT NULL,
    outputs JSONB NOT NULL,
    patch_path TEXT,
    commit_sha TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX repair_prov_repo_step_idx ON repair_provenance (repo_id, step_execution_id);
Concern #5: ProcessGroupManager Not Fully Specified [LOW]
Issue: Ticket 2 mentions ProcessGroupManager with platform-specific flags, but the Monitoring & Self-Healing spec doesn't provide implementation details.

Current State:

✅ Mentioned in Ticket 2 with platform-specific flags
⚠️ No implementation details in specs
Recommendation: This is acceptable - implementation details can be determined during development. The requirements are clear (process groups, PID reuse detection, cross-platform).

---

# Updated Analysis Report v3

## Robust file-backed pivot + Patch-Stream code-change model (jj) + minimal optional UI

Last updated: 2026-01-23

This document supersedes **Updated_Analysis_Report.md** by incorporating the **robust file-backed pivot** and the **Patch‑Stream (jj-backed) methodology** as the target state. It also integrates the remaining open protocol questions raised after v2.

> Scope note: This is a **design analysis + final-state spec overlay**. It is not an implementation plan, and it is not a migration of a running system. The “migration” here is the documentation set.

## 0) What changed since Analysis v2

v2 had already pivoted away from PostgreSQL toward a filesystem-backed Workspace State Store (WSS) + sharded JSONL logs + filesystem queues, with a minimal optional UI. fileciteturn1file12

The new target state adds/locks in three major things:

1) **Robustness wins over “pipes-only / RAM-only workspace”**  

   Logs and workspace state are explicitly persisted to disk for crash/power-loss tolerance. fileciteturn1file0

2) **Patch‑Stream remains the code-change model** (jj-backed change graph)  

   Worktrees are no longer the primary “unit of workspace”; instead, code changes are a patch stack, and file state is hydrated on demand. fileciteturn1file0

3) **Root orchestration is flatter and Pause is mandatory**  

   Root manages a flat set of child step/agent processes (no “grandchildren” at the orchestration layer), and PAUSE must be honored promptly with enforcement inside each process. fileciteturn1file0

## 1) Consolidated constraints and invariants (final)

### 1.1 System-level constraints

- **Local-only**, single-machine execution. Not distributed, not cloud. fileciteturn1file0

- Runtime artifacts are **not committed to git**. fileciteturn1file0

- Prefer **robustness over micro-optimizing I/O**. fileciteturn1file0

- The system must support **many concurrent writers** (many step/agent processes emitting logs and writing state), without a single-writer bottleneck.

### 1.2 UX constraints (highest priority)

- User experience must be **snappy** for:

  - listing/selecting projects/tickets

  - seeing/responding to out-of-band notifications

  - core workflow execution feedback loops

- Minimal footprint:

  - avoid always-on heavyweight services

  - avoid port conflicts / firewall prompts

  - keep runtime files under a single predictable root

### 1.3 Logging/tracing invariants

- **Step logging is always on** (step enter/exit + key events). fileciteturn1file0

- **Dynamic tracing is optional**, function-call level, enabled **per-step when needed**. fileciteturn1file0

- Users do **not** search logs by text; logs are retrieved and navigated by **IDs**.

### 1.4 Orchestration invariants

- **No grandchildren in orchestration**: root directly owns/controls the flat set of step/agent processes. Steps may spawn tool subprocesses internally, but root does not track those as first-class children. fileciteturn1file0

- **Pause is mandatory**, no “safe/unsafe” pause levels. On PAUSE, processes must stop promptly; enforcement is inside each process (control/watchdog threads), not via root killing PIDs. fileciteturn1file0

- We ALWAYS avoid max iterations (no hard “max loops” as a termination mechanism).

## 2) Re-evaluating the “in-memory worktree / virtual FS” idea

### 2.1 The core question

“Do we need to embed agents and fake bash commands against an in-memory filesystem to get ‘in-memory worktrees’ and avoid git/worktree overhead?”

### 2.2 Conclusion

No—**embedding agents + a fully virtual filesystem is not the best or only way** to reach the performance/footprint goals.

A full virtual FS implies:

- intercepting a wide surface of UNIX tooling semantics (search, permissions, path ops, temp files, file watchers)

- emulating a “real repo” for arbitrary tools

- a large correctness burden when tools behave unexpectedly

That is the wrong place to spend risk if the only goal is to avoid heavy persistent worktrees.

### 2.3 What *does* match the goals

The Patch‑Stream model already achieves “no persistent worktree copies”:

- code is stored as an **anchor revision + patch stack**

- files are **hydrated** (reconstructed) on demand for reads

- tools that require a filesystem run in **ephemeral sandboxes**

- the durable truth is patches in the change graph + robust workspace/log files

This yields the “sparse / delta-only” benefits without having to emulate a complete UNIX filesystem in memory.

**Implication:** “Embedding agents” remains a future optimization, not a prerequisite for the final state described here. (And per instruction, the `embedding agents.md` file stays out of scope.)

## 3) Final recommended architecture (target state)

### 3.1 Components (minimal, local, robust)

1) **Patch Graph Store (PGS)**: a jj-backed change graph (Patch‑Stream)  

   - Tickets/changes are patch stacks

   - Rebase is pointer arithmetic, conflicts become data/jobs

2) **Workspace State Store (WSS)**: durable, sharded files/folders  

   - hierarchical workspace state (repo/project/ticket/task/step/run)

   - mutations via JSON Merge Patch semantics

3) **Logs Store**: durable, sharded JSONL logs per step/process  

4) **Notifications + Control Actions**: filesystem queues (durable, multi-writer)

5) **Ephemeral Sandboxes**: for lint/tests/build and any tooling that requires a “real filesystem repo”

6) **Optional UI**: notifications-only (does not gate workflows)

This matches the robust pivot: durable logs + durable workspace state, while keeping root-level monitoring/eventing lightweight. fileciteturn1file0

### 3.2 Runtime footprint control (single root)

All runtime artifacts live under one predictable root (example):

```

~/.workflow/

  repos/<repo_uid>/

    repo.json

    workspace/           # WSS

    logs/                # sharded JSONL

    notifications/

    control_actions/

    vcs/                 # jj repo state / metadata pointers

    sandboxes/

    conclusions/

    caches/

```

This “one root” rule is important to avoid loose-file sprawl and to keep deletion/backup simple.

## 4) Code-change model: Patch‑Stream (jj-backed)

The new target state explicitly commits to:

- Patch‑Stream methodology remains (jj-backed change graph)

- Virtual hydration for reading “future state” without persistent worktrees

- Lint/tests/build run in ephemeral sandboxes (queued execution)

- Conflicts are first-class; resolver jobs handle them fileciteturn1file0

### 4.1 Ticket/work item representation

- A ticket corresponds to a **named change stack** in jj (one or many patch changes).

- “Draft work” is patches, not mutable files on disk.

- A “release candidate” is a stack that has passed sandbox validation.

### 4.2 Virtual hydration: what it really means operationally

Hydration is a pure function:

`hydrate(file_path, revision_id) -> bytes`

Implementation can be:

- ask jj for the file at a revision (anchor + patches already applied in the content graph)

- stream content back to the caller

**Key property:** The system can show the “future state” without requiring a checkout of that state. fileciteturn1file0

### 4.3 How LLMs edit without a checkout

There are two viable modes:

#### Mode A: “Blind patch editor” (no sandbox)

- LLM requests hydrated content for specific files/functions.

- LLM emits a patch object (unified diff or structured hunks).

- System records patch into jj as a new change on the stack.

#### Mode B: “Ephemeral workspace editor” (sandbox)

- System creates a sandbox view of the repo at the patch stack.

- Tools run normally (`rg`, `sed`, formatters).

- System captures resulting diff and commits it as a patch change.

**Recommendation:** Support both. Use Mode A for fast iterative edits; fall back to Mode B when the agent needs heavy tooling or broad search.

### 4.4 Conflicts and rebasing

- jj can represent conflicts as first-class objects (“conflicted commits”) rather than breaking the repo.

- Conflict resolution is a job:

  - read conflict markers/objects

  - decide merge

  - produce a resolving patch on top

Rebase is pointer arithmetic:

- move the base of a stack to a new parent

- replay patches

- conflicts become resolver jobs fileciteturn1file0

### 4.5 Final merge/integration

Even though the workflow is patch-stack driven, you still need a final “target branch update” step:

- export the validated stack to the target branch as:

  - (a) a linear series of commits, or

  - (b) one squashed commit, depending on your policy

- run final integration tests in a sandbox

- update the repo pointer

## 5) Lint/tests/build: sandboxed, queued, and selective

The Patch‑Stream methodology explicitly pushes verification into sandboxes. fileciteturn1file0

### 5.1 Two-stage linting

1) **Hunk lint (fast reject):**

   - validate patch format

   - run syntax-level checks on changed files only (where possible)

2) **Sandbox lint (complete):**

   - hydrate patch stack into sandbox

   - run full lint toolchain

### 5.2 Test strategy (local, minimal pain)

A dependency graph–selected test strategy is ideal, but it’s not required on day one.

A pragmatic progression:

- Start with:

  - “changed-package tests” (by path heuristics)

  - plus smoke tests

- Later add:

  - reverse dependency mapping (symbol → tests)

  - to drive selective test execution

### 5.3 Sandbox construction without copying the whole repo

You want a “sparse worktree” effect inside the sandbox:

- base anchor is read-only

- only modified files are written into an overlay/upper layer

- sandbox is disposable

Whether this uses overlay mounts, reflinks/hardlinks, or jj’s own workspace mechanisms is an implementation choice; the doc-level invariant is:

> Sandboxes must not require copying the entire repo to run a check.

## 6) Durable storage design (robust pivot)

### 6.1 Logs Store: sharded JSONL (durable)

- Sharded JSONL logs on disk. fileciteturn1file0

- Each process/step writes to its own shard to avoid writer contention. fileciteturn1file2

- Root may tail/index shards, but root does not own all log emission. fileciteturn1file2

- Tool output is stored as JSON fields (chunked records), not raw lines. fileciteturn1file2

- Durability knobs:

  - flush on step boundaries and ERROR (minimum)

  - optional fsync for power-loss tolerance at those boundaries fileciteturn1file2

#### Required log discipline: JSONL schema versioning

Without a stable schema, future UI/analyzers/replay will rot.

**Hard requirement**: a minimal versioned JSON schema and never breaking changes.

(See Section 7.1.)

### 6.2 Workspace State Store (WSS): durable files/folders

- Workspace state is file-backed because it may include tool-derived results not reproducible from logs/inputs. fileciteturn1file2

- Workspace layout is standard folders/files, sharded to maintain low contention. fileciteturn1file2

- Updates are expressed as JSON Merge Patch (RFC 7396). fileciteturn1file2

- Correctness must not rely on “flush only at end”; state needed for resume/forensics must be persisted as produced. fileciteturn1file2

## 7) The remaining gaps (now must be locked down)

The new file correctly identifies that remaining work is:

- protocol discipline,

- atomic file handling,

- and documenting invariants. fileciteturn1file3

This section turns those into concrete decisions.

### 7.1 JSONL schema discipline (mechanical, mandatory)

**Decision:** define `schema_version = 1` and a minimal event schema.

#### 7.1.1 Base event schema (v1)

Required fields (all events):

- `schema_version`: int (start at 1)

- `event_type`: string enum

- `ts`: int (unix epoch ms) or RFC3339 string (choose one and lock it)

- `run_id`: string

- `step_execution_id`: string (or null for root-level events)

- `writer_id`: string (process-unique)

- `seq`: int (monotonic per shard file)

- `data`: object (event payload)

Optional but recommended:

- `repo_uid`

- `project_id`, `ticket_id`, `task_id`, `step_id` (definition ids)

- `parent_step_execution_id` (logical nesting; process ownership remains flat)

- `trace_id` / `span_id` for tool and trace correlation

- `severity` for error/warn/info

#### 7.1.2 Event types (minimum set)

- `step_start`

- `step_stop`

- `stdout_chunk`

- `stderr_chunk`

- `tool_start`

- `tool_stop`

- `trace` (function-call trace frame; enabled per-step)

- `error`

- `notification_raised`

- `pause_requested` / `pause_ack` / `resume_requested` / `resume_ack` (or keep pause a control-plane-only protocol; see 7.4)

#### 7.1.3 Ordering guarantee

- Within a shard file, `seq` is strictly increasing and never reused.

- Consumers must treat `(writer_id, seq)` as the canonical ordering key.

### 7.2 Workspace atomicity on writes (boring, mandatory)

**Decision:** Every workspace write is atomic:

1) write `<file>.tmp.<random>`

2) `fsync(tmp)`

3) rename(tmp → target)

4) `fsync(directory)`

Readers ignore `*.tmp.*`.

This applies to:

- workspace JSON/MD docs

- notification/control action files

- conclusion files

(For JSONL append-only shards: each writer uses its own file; the durability policy is flush/fsync at boundaries.)

### 7.3 Merge-patch edge cases (define once; never argue later)

You already chose JSON Merge Patch semantics. fileciteturn1file2  

Now define edge-case behavior:

**Decision set (recommended conservative rules):**

- Patch root MUST be a JSON object; otherwise reject the patch (error).

- Patching into non-object targets:

  - if target is non-object and patch value is object → overwrite target with object

- Deleting missing keys (`null` on absent key) → no-op

- Type mismatches:

  - object → scalar overwrite allowed (patch wins)

  - scalar → object overwrite allowed (patch wins)

- Arrays are treated as scalars (replace entirely)

Also lock the invariant:

- `null` is reserved for deletion and cannot be a legal business value in persisted workspace docs.

### 7.4 Pause ACK protocol (small, but must be explicit)

The missing piece is: “what does paused mean?”

**Decision (minimal, robust definition):**

- “Paused” means:

  1) the step process is **not executing any tool subprocess**

  2) the step process is **not mutating workspace state**

  3) the step process is **sitting in a control loop** waiting for RESUME/STOP

  4) it has flushed required state/log boundaries for safe continuation

**Protocol sketch (filesystem control-plane):**

- Root writes a pause request file:

  - `control_actions/inbox/pause.<request_id>.json`

- Each step process:

  - detects pause request (poll or inotify)

  - transitions to paused state within a deadline

  - writes:

    - `control_actions/ack/pause.<request_id>.<step_execution_id>.json`

  - and optionally emits `pause_ack` in its log shard

Root considers the system paused when it has ack files for all targeted steps.

**Enforcement:** if a process cannot pause within deadline, the process triggers the investigator path (7.5) rather than root killing by default. fileciteturn1file3

### 7.5 Tool conclusions lifecycle (avoid re-investigation, but don’t over-generalize)

The robust pivot includes persisting tool conclusions with a promotion lifecycle. fileciteturn1file4

Lock down:

- **scope** (default per-repo; optional global library)

- **fingerprinting** (tool path + version + args class + env)

- **invalidation** (tool version changes; inputs/config changes; repo signature changes)

- **promotion rules**:

  - draft → confirmed requires reproduction across distinct runs/contexts

  - confirmed → promoted requires successful remediation outcomes and stable signature

Store:

- `conclusions/tools/<tool_fingerprint>/<conclusion_id>.json`

- `conclusions/perf/<step_signature>/<conclusion_id>.json` (same lifecycle)

### 7.6 Investigator LLM contract (so it’s repeatable)

The robust pivot assumes step processes can spawn an investigator job when stuck. fileciteturn1file3

Define a strict contract:

**Trigger conditions (examples):**

- pause deadline exceeded

- tool subprocess exceeded duration threshold + no progress

- repeated identical failures in a short window

**Investigator inputs:**

- pointers to:

  - step log shard

  - relevant workspace docs

  - current patch stack / revision id

  - tool command + env

  - last N events (bounded)

**Investigator outputs (machine-readable):**

- `classification`: {resolved, needs_user, needs_retry, needs_shutdown}

- `actions`: list of concrete operations (kill tool pid, delete temp files, write resume script)

- `resume_plan`: path to resume script + required state patch(es)

- `conclusion_updates`: optional new/updated tool conclusions with confidence state

- `evidence_refs`: run_id/step_execution_id/seq ranges

This keeps the investigator repeatable and prevents “magic reasoning” from becoming untestable behavior.

## 8) Monitoring: lightweight root + durable evidence

The robust pivot says:

- root keeps canonical step metrics and uses them for hang detection

- long-term bottleneck detection uses distribution shift

- root can trigger trace escalation on future runs

- event routing can be internal; no persistent server required fileciteturn1file4

**Design note:** This is compatible with the existing “investigate-first” posture in the Monitoring spec, but it changes the mechanics:

- “suspend = kill + restart” should be replaced with **pause mandatory + process-owned enforcement**. fileciteturn1file11

## 9) Open parameters (explicitly acknowledged)

The new file lists remaining parameters to finalize. fileciteturn1file3  

For the doc set, record them as “Open Parameters” with defaults:

1) Durability policy: flush/fsync cadence  

   - default: flush on step boundary + error; fsync on error; optional fsync on step boundary

2) Workspace persistence strategy  

   - default: atomic shard writes (simpler)

   - later: patch journal + compaction if write rates become extreme

3) Log chunk sizing and retention  

   - default: chunk tool output at fixed byte size; per-run retention configurable; keep last N runs

4) Conclusion promotion criteria  

   - default: conservative, promote only after repeated reproduction + successful remediation

5) Pause enforcement thresholds  

   - default: short deadline for “pause requested → paused ack”, with investigator escalation

## 10) Summary: “right tool for the job” alignment

- PostgreSQL is removed because it is a heavyweight “convenient hammer” for a problem that is fundamentally local, ID-centric, and multi-writer by nature.

- Persistent git worktrees are replaced by Patch‑Stream + virtual hydration, because worktrees are the wrong tool for “many parallel AI edits + frequent rebases”.

- File-backed sharded logs and file-backed workspace state are chosen because they minimize footprint (no ports) while maximizing robustness (crash/power tolerance).

- The remaining hard work is protocol discipline and invariants: JSONL schema, atomic writes, merge patch semantics, pause/ack, conclusions lifecycle, investigator contract.



# Updated Migration Guide v3

## Migrate specs to “robust file-backed pivot + Patch‑Stream (jj) + minimal optional UI”

Last updated: 2026-01-23

This guide supersedes **Updated_Migration_Guide.md** by updating the target state to match:

- robust durable **sharded JSONL logs** + **file-backed workspace state** fileciteturn1file0

- **Patch‑Stream methodology (jj-backed change graph)** with **virtual hydration** (no persistent worktrees required) fileciteturn1file0

- lint/tests/build in **ephemeral sandboxes** (queued execution) fileciteturn1file0

- **Pause is mandatory** and enforcement is inside each process fileciteturn1file0

- UI simplified to **notifications-only**, optional, and does not gate workflows (portless via WSL helper)

> This is still a **documentation migration guide**. It tells you how to rewrite the Epic Brief, Core Flows, and Tech Plans so they match the final state.

---

## 0) Add a shared “Constraints & Invariants” section to ALL spec docs

Add directly under “Summary” (Epic Brief) or “Overview” (Tech Plans), and near the top of Core Flows.

### 0.1 Template text (copy/paste)

**Constraints & Invariants**

- Local-only, single-machine execution. Not distributed, not cloud.

- Runtime artifacts are local and not committed to git.

- Prefer robustness over micro-optimizing I/O.

- Step logging is always on (step enter/exit + key events).

- Dynamic tracing is optional and enabled per-step when needed.

- Root orchestration is flat: root directly owns/controls all step/agent processes (no grandchildren).

- Pause is mandatory (no safe/unsafe): on PAUSE, processes must stop promptly; enforcement is inside each process.

- Patch‑Stream code-change model (jj-backed change graph). Worktrees are not required for the system to function.

- Lint/tests/build run in ephemeral sandboxes (queued).

- UI is optional and must not gate workflows; MVP UI surfaces out-of-band notifications only.

- Users do not search logs by text; logs are retrieved by IDs.

- Keyword/fuzzy search is sufficient for project/ticket lookup; no embedding-model requirement.

- We ALWAYS avoid max iterations (no fixed iteration caps as termination criteria).

### 0.2 Spec alignment rule

Any architectural decision later in the doc must be consistent with this section. If not, rewrite the spec.

## 1) Introduce canonical terms (used across all docs)

Add a shared “Terminology” subsection to the Core Infrastructure plan and reference it elsewhere.

### 1.1 Workspace State Store (WSS)

A filesystem-backed hierarchical document store for mutable workspace state (repo/project/ticket/task/step/run).

### 1.2 Logs Store

Durable, sharded JSONL event logs, written per step/process to avoid writer contention.

### 1.3 Notifications Store + Control Actions Queue

Filesystem queues for:

- out-of-band notifications

- control requests (UI → workflow runtime)

- pause/resume requests and ack files (if using FS control-plane)

### 1.4 Patch Graph Store (PGS)

A jj-backed change graph used as the canonical store of code changes:

- ticket = change stack

- patch = atomic change object

- rebase = moving the parent pointer of the stack

### 1.5 Virtual hydration

On-demand reconstruction of file content for a given revision (future state) without checking it out.

### 1.6 Sandbox

A disposable environment where tools run against a hydrated view of the repo (anchor + patch stack).

## 2) File-by-file migration instructions

### 2.1 Epic_Brief__Multi-Layered_Project_Management_System.md

Update the brief so it describes the right primitives.

**Replace in Summary / Assumptions**

- Remove PostgreSQL as system of record.

- Remove “LISTEN/NOTIFY” and DB-centric UI assumptions.

**Add**

- WSS + Logs Store as durability boundary.

- PGS (jj change graph) as the code-change backbone.

- Sandboxes for lint/test/build.

- Flat orchestration + mandatory Pause.

**Add new section**

**Durability boundary**

- What is persisted: WSS docs + log shards + conclusions.

- What is ephemeral: sandboxes, hydrated workspaces, caches.

### 2.2 Core_Flows__Project_Management_&_Autonomous_Monitoring.md

This file must be rewritten to change the “actors” and “state transitions”.

#### 2.2.1 Replace DB interactions everywhere

Replace flows that do:

- “register repo in DB”

- “query tables for state”

- “listen/notify for UI”

With:

- create/update WSS docs

- append to log shards

- emit notifications to filesystem inbox

- use control actions queue for user responses

#### 2.2.2 Replace “worktrees per ticket” with “jj change stacks”

Where flows currently mention:

- create worktree for ticket

- apply changes in a branch/worktree

Rewrite as:

- create a jj change stack for ticket

- agent produces patch objects on that stack

- “future state” reads use hydration, not checkout

#### 2.2.3 Replace rebase flows with Patch‑Stream rebasing

Replace:

- “git rebase across worktrees”

With:

- `jj rebase` stack pointer move

- conflicts become resolver jobs

#### 2.2.4 Update monitoring flows for mandatory Pause

Replace:

- suspend = kill + restart semantics

With:

- root sends PAUSE request

- step process acks paused state

- if cannot pause: investigator job is spawned by the process

- root coordinates outcomes

### 2.3 Tech_Plan__Core_Infrastructure_&_Data_Model.md

This becomes the “source of truth” spec for storage + protocol discipline.

#### 2.3.1 Replace PostgreSQL-centric sections

Remove:

- SQL schema tables

- SQLAlchemy/Alembic assumptions

- DB URL/service setup

Replace with:

- WSS directory + document schemas

- Logs Store JSONL schema (versioned)

- Notifications/control queues schemas

- Patch Graph Store (jj) integration surface

#### 2.3.2 Add a new “Protocol Discipline” chapter

Must include:

1) JSONL schema version + event types + required fields + ordering guarantees

2) Atomic write protocol (tmp + fsync + rename + fsync dir)

3) Merge patch semantics and edge cases

4) Pause/ACK protocol

5) Tool conclusions lifecycle

These are the “boring but mandatory” invariants that prevent rot.

#### 2.3.3 Add “Ownership & contention rules”

For every persisted artifact:

- who writes it

- who reads it

- what happens on conflict

- whether optimistic concurrency is used

#### 2.3.4 Add “Repo identity + root paths”

Lock:

- `repo_uid` derivation

- single root folder location

- no scattering files in repo working tree unless explicitly justified

### 2.4 Tech_Plan__Project_&_Ticket_Management.md

#### 2.4.1 Replace worktree discovery

If this plan currently scans `.worktrees/`, rewrite:

- project/ticket discovery comes from WSS docs + jj stack metadata, not from filesystem worktrees.

#### 2.4.2 Ticket lifecycle

- ticket creation:

  - create WSS ticket docs

  - create jj change stack linked to ticket_id

- ticket execution:

  - steps emit log shards

  - steps update WSS state via merge patches

- ticket completion:

  - ticket stack validated in sandbox

  - exported/merged into target branch policy

#### 2.4.3 Keyword search

Explicitly define:

- project/ticket search is over WSS metadata (title/name), not logs

- fuzzy match (case-insensitive) is enough

- no embeddings required

### 2.5 Tech_Plan__Monitoring_&_Self-Healing.md

This spec needs a conceptual shift while preserving the intent (“investigate-first”).

#### 2.5.1 Replace suspend/resume semantics

Remove:

- “Suspend means terminate the process and later restart from DB state”

Replace with:

- Pause mandatory, ack protocol, enforcement inside each process

- investigator job spawned by process on timeouts

#### 2.5.2 Replace trace toggles stored in DB

Replace with:

- trace override docs in WSS (or control queue messages)

- step processes poll these at safe points

- dynamic tracing enabled per-step

#### 2.5.3 Replace DB queries with log+workspace reads

- step history = step metrics + log shards

- evidence gathering = copy WSS + logs for {run_id, step_execution_id} into an investigation bundle

#### 2.5.4 Add “Conclusions lifecycle”

Document storage + promotion of:

- tool conclusions

- performance conclusions (bottleneck detection)

### 2.6 Tech_Plan__Monitoring_UI_(Tauri).md

This spec must be simplified to match the MVP visuals constraint.

#### 2.6.1 Replace architectural decision

Remove:

- “Postgres LISTEN/NOTIFY + Cursor Reads” fileciteturn0file6

Replace with:

**Decision: UI consumes Notifications stream (no DB, no ports)**

- UI spawns a WSL helper:

  - `wsl.exe workflowctl notifications tail --jsonl`

- UI renders notifications only

- UI sends actions back by writing to Control Actions queue (via helper)

#### 2.6.2 Drop components from MVP

Remove from MVP:

- Workflow list / execution timeline

- log viewer / log search

Keep:

- NotificationCenter

- minimal ack/resolve flows

### 2.7 Tech_Plan__Enhanced_Rebase_&_Evaluation.md

Rewrite this plan to be jj-stack-based, not worktree-based.

#### 2.7.1 Enhanced rebase

Replace:

- conflict detection via `git status` + worktree state

- Postgres queries for project/ticket metadata

With:

- jj rebase stack operation

- conflict object detection in jj

- metadata read from WSS docs

Conflict resolution records:

- store in WSS: `rebase/conflicts/<resolution_id>.md`

- link to evidence: run_id + step_execution_id + log shard ranges

#### 2.7.2 Evaluation sandboxes

Replace “evaluation worktree” with:

- “evaluation sandbox” (ephemeral)

- sandbox hydrates patch stack

- runs lints/tests

- emits gap reports as files stored under WSS `evaluation/`

### 2.8 Tech_Plan__Integration_&_File_Structure.md

This file should describe the new module boundaries.

#### 2.8.1 Remove deprecated file tree entries

Remove:

- `.dev/postgres/` and DB setup

- UI backend modules that assume DB connections

- git worktree GC/detection as a core dependency (may remain as an optional legacy tool)

#### 2.8.2 Add new core modules (example names)

Add:

- `scripts/core/storage/wss.py`

- `scripts/core/storage/logs.py`

- `scripts/core/storage/queues.py` (notifications/control)

- `scripts/core/vcs/jj_adapter.py`

- `scripts/core/sandbox/runner.py`

- `scripts/core/protocol/schema_v1.py` (JSONL schema definitions)

- `scripts/core/protocol/merge_patch.py`

- `scripts/core/protocol/pause.py`

- `scripts/core/conclusions/store.py`

- `scripts/core/investigation/investigator_contract.py`

#### 2.8.3 Update CLI surface

Add/replace:

- `workflowctl hydrate <ticket_id> <path>` (read file at revision)

- `workflowctl apply-patch <ticket_id> <patch>` (commit patch into jj stack)

- `workflowctl sandbox run <ticket_id> -- lint|test|build`

- `workflowctl notifications tail --jsonl`

- `workflowctl control ack/resolve ...`

## 3) Cross-cutting updates (must be applied everywhere)

### 3.1 Replace “tables” language with “docs + shards”

Every reference to:

- insert/update/select

becomes:

- read/write docs, append shards, move queue files

### 3.2 Replace “worktree path = project state” with “WSS + jj stack”

Worktrees become optional/ephemeral at most.

The durable truth is:

- WSS docs

- log shards

- jj patch graph

### 3.3 Replace “DB migrations” with “schema versioning”

Every persisted artifact must include:

- `schema_version`

- compatibility rules (forward/back)

### 3.4 Add GC/cleanup story per subsystem

For each writer:

- where it writes

- retention policy

- cleanup command

- safety rules (never delete active run artifacts)

## 4) Doc quality checklist (gap closure)

After updating the docs, verify:

1) No references to:

   - PostgreSQL

   - SQLAlchemy/Alembic

   - LISTEN/NOTIFY

   - “persistent worktree required”

2) Every spec has Constraints & Invariants.

3) Every stored artifact has:

   - location

   - schema_version

   - ownership rule

   - atomic write rules

4) Pause semantics are explicit:

   - request

   - ack

   - definition of “paused”

5) JSONL schema is explicit:

   - event types

   - required fields

   - ordering guarantee

6) Tool conclusions lifecycle is specified:

   - scope

   - invalidation

   - promotion

7) UI is optional and notification-only.

---

# Analysis: Hardening Overlay, Deprecations, and Dropped Details (v4)

Last updated: 2026-01-23

This document is a **hardening + cleanup overlay** across the current spec set. It does **not** rewrite the specs; it enumerates what must be added back, what is deprecated, and what needs hardening to meet the stated philosophy (local-only, minimal footprint, durable evidence, ID-driven UX, and **no fixed max-iteration caps**).

Primary inputs (current spec set):

- Tech Plan: Core Infrastructure & Data Model

- Tech Plan: Enhanced Rebase & Evaluation

- Tech Plan: Integration & File Structure

- Tech Plan: Monitoring & Self-Healing

- Tech Plan: Monitoring UI (Tauri)

- Tech Plan: Project & Ticket Management

- Core Flows: Project Management & Autonomous Monitoring

- Epic Brief: Multi-Layered Project Management System

- Analysis Report v3

## 1) Clarifications / new decisions to embed (authoritative going forward)

### 1.1 No UI required (Tauri can be removed)

The system must function fully via CLI + durable artifacts. The optional Tauri notification center is no longer necessary.

**Implications**

- Remove UI as an actor from flows.

- Control Actions and Notifications remain useful as durable, decoupled primitives, but must be consumable entirely via CLI (Project/Ticket Manager + workflowctl).

- Any “created_by = ui” examples should become generic (`created_by = client|cli|agent|root`).

### 1.2 No standalone background monitor/daemon (including any “LLM monitor”)

There is no separate long-lived “monitor process” that watches files and makes decisions.

Monitoring and self-healing responsibilities are split between:

- the **root runtime** (already running when workflows execute), and

- each **step process** (control loop + investigator spawning as needed).

**Implications**

- Remove `monitor.py` as a separate background service concept.

- Keep the monitoring logic as libraries callable from root/steps (anomaly detection, investigator contract, repair agent).

### 1.3 Agents do not directly spawn agents (preserve flat orchestration)

The invariant “no orchestration-level grandchildren” remains.

To allow “agents spawning agents” without violating flat orchestration:

- agents request spawning via the workflow engine control plane, and

- the **root runtime** performs the actual spawn.

### 1.4 Single MCP tool: workflow engine gateway (one tool, many subcommands)

Agents must not run Python or arbitrary commands directly.

All execution goes through the workflow engine via **one** MCP tool that exposes only the workflow-engine CLI gateway.

**Key requirement**

- The MCP tool must not be “run arbitrary shell”. It must be an allowlisted gateway that only accepts workflow-engine subcommands with typed arguments.

## 2) Dropped details to reinstate (explicitly requested)

These were present in Analysis v3 but are not hardened as requirements in the current tech plans.

### 2.1 Two-stage linting (fast reject + full sandbox lint)

Reintroduce as a required pattern:

1) **Hunk lint (fast reject)**

- Validate patch structure/format.

- Run lightweight, changed-files-only checks when possible.

2) **Sandbox lint (complete)**

- Hydrate the stack into a sandbox and run the full lint toolchain.

**Why**

- Enables faster feedback loops (UX) without sacrificing correctness.

- Reduces expensive sandbox runs when the patch is obviously invalid.

**Hardening requirements**

- Both stages must emit durable evidence:

  - log events (tool_start/stop + outputs)

  - WSS artifacts (a “lint report” object that links evidence ranges)

- No “max tries”; use novelty/signature rules (see §6).

### 2.2 Selective tests progression (pragmatic → graph-driven later)

Reintroduce as a roadmap requirement:

- Phase 1 (now): “changed-package tests” by path heuristics + smoke tests.

- Phase 2 (later): reverse dependency mapping / smarter selection.

**Hardening requirements**

- Always record “test selection rationale” as a WSS artifact for auditability.

### 2.3 Sandbox construction backends (approved approaches + fallback)

The invariant “don’t copy entire repo” is necessary but insufficient.

Reintroduce as an explicit backend selection policy (ordered):

1) overlay/union (when available)

2) reflink clone (when FS supports)

3) hardlink clone (when safe)

4) last resort: full copy with explicit warning + strict retention limits

**Hardening requirements**

- The sandbox runner must record which backend was used (and why) in logs/WSS.

- The system must remain usable cross-platform (including WSL scenarios) without silent footguns.

### 2.4 Runtime root layout alignment (`vcs/` + conclusions placement)

Analysis v3’s runtime root example included a top-level `vcs/` and `conclusions/`.

The current Core Infrastructure plan example does not include `vcs/` and places conclusions under `workspace/conclusions/`.

**Hardening requirement**

- Choose one canonical layout and enforce it consistently across docs and code.

- Recommendation (to reduce ambiguity):

  - add top-level `vcs/` for jj metadata/pointers

  - keep conclusions in one place only (either `workspace/conclusions/` as part of WSS *or* top-level `conclusions/`, not both)

## 3) Deprecations and removals (spec-level cleanup)

### 3.1 Deprecate/remove: Monitoring UI (Tauri)

- The entire UI spec becomes deprecated.

- Remove UI-specific flows and integration references.

- Replace with CLI equivalents:

  - `workflowctl notifications list|tail`

  - `workflowctl control write|send`

  - Project Manager “QA mode” surfaces pending notifications.

### 3.2 Deprecate/remove: Background monitor process (`monitor.py`)

- Remove “Root monitor (optional background)” as a standalone process concept.

- Keep:

  - investigator contract

  - anomaly detection logic

  - workflow repair agent

- Reframe as **in-process services** used by root runtime and step processes.

### 3.3 Audit for any remaining deprecated DB assumptions

Current specs already remove DB as a requirement, but the migration should:

- ensure no residual “DB wakeups / DB watchers” are required for any flow

- ensure no runtime artifacts are expected to be committed

## 4) P0 hardening gaps (must address)

### 4.1 Workflow shape visibility (graphing / introspection) is still missing

You explicitly called out the inability to understand hybrid workflows:

- agents defined in markdown

- python scripts invoked by agents

- agents execute scripts, but the markdown “control flow” is not machine-readable

**Required capability**

A local CLI tool that outputs workflow diagrams without any UI:

- `workflowctl graph --workflow <name>` (static best-effort)

- `workflowctl graph --run <run_id>` (dynamic ground truth)

- output: Mermaid text + JSON graph

#### 4.1.1 Dynamic graph (ground truth): derive from durable evidence

This should be the first implementation because it avoids interpreting markdown:

- step_start/stop + tool_start/stop + run/step docs are sufficient to build a run graph

- spawn requests (see §4.2) become explicit edges

Store graphs as WSS artifacts under:

- `workspace/runs/<run_id>/artifacts/graphs/`

#### 4.1.2 Static graph: deterministic extraction first, LLM interpretation second

Static graph for “what this workflow *will* do” should be layered:

1) deterministic extraction:

   - parse python (AST) to find `workflowctl` invocations / @step blocks

   - parse markdown for explicit, standardized script/tool call syntax

2) LLM interpreter (optional):

   - must emit **evidence-backed edges** (line ranges/snippets)

   - must output `unknown` nodes/edges rather than guessing

   - must produce machine-readable JSON stored as an artifact with provenance

**No max iterations**

- if extraction is incomplete, emit an “unknown edges” section and stop.

### 4.2 “Agents spawn agents” safely via control-plane requests (no grandchildren)

Introduce a first-class control action:

- `action_type = spawn_step` (or `spawn_agent`)

**Mechanics**

- The requesting agent writes a spawn request (control action file).

- Root runtime receives it and spawns the new step/agent process.

- Root writes an ACK record (or updates run state) containing:

  - new `step_execution_id`

  - linkage metadata (parent logical id)

**Waiting**

- Provide `workflowctl wait --step_execution_id ...` that waits on:

  - WSS step doc status change, and/or

  - log shard step_stop event

**Hardening**

- Spawn requests must be idempotent via `request_id`.

- Spawn must be auditable (log events + WSS link).

### 4.3 MCP gateway hardening (single tool, allowlisted, typed)

A single “run workflowctl” tool is acceptable only if it is constrained.

**Required properties**

- allowlisted subcommands only

- typed arguments (JSON in, JSON out) to eliminate shell injection classes

- explicit target scoping: run_id / step_execution_id / repo_uid where relevant

- consistent logging: every gateway call emits tool_start/tool_stop with args class + fingerprints

**Why**

MCP ecosystems have had real-world security issues when tools allow broad filesystem or command execution. The safest stance is least privilege and narrow tool surfaces.

### 4.4 Filesystem queue semantics need claim/processing states

Current specs define inbox/archive/applied/failed but not a safe multi-consumer claim mechanism.

**Required queue discipline (Maildir-like)**

- Producers write to `tmp/`, fsync, atomic rename into `inbox/`.

- Consumers atomically rename into `processing/<consumer_id>/` to claim.

- Outcomes go to `applied/failed/archive/`.

**Requeue**

- A stuck item in processing (no heartbeat beyond TTL) is moved back to inbox once.

- If repeated with same signature, escalate and stop.

**Idempotency**

- `request_id` and/or `notification_id` is the dedupe key.

### 4.5 Filename safety (RFC3339 in filenames is risky on Windows)

Keep RFC3339 inside JSON fields; filenames must be filesystem-safe:

- prefer ULID or unix_ms prefixes

- avoid colon characters in filenames

### 4.6 WSS multi-writer correctness: enforce ownership + detect contention

Even with conventions, lost updates will happen eventually.

**Hardening requirements**

- enforce doc ownership mechanically (writers refuse to patch docs they don’t own)

- add an optional monotonic `rev` for optimistic concurrency:

  - patch includes `expected_rev`

  - mismatch fails once and escalates (no retry loops)

### 4.7 Step attempt identity semantics must be unambiguous

Define one of:

- **Option A (recommended)**: one `step_execution_id` == one attempt (retry creates new step_execution_id + writer_id)

- Option B: step_execution_id stable; attempt increments (harder to reason about)

The evidence model (logs + step docs + graphs) is cleaner with Option A.

### 4.8 Log shard corruption tolerance (truncated JSONL record)

Readers must define behavior:

- ignore trailing partial line

- treat mid-file corruption as an error with a durable notification + evidence pointer

### 4.9 Schema evolution rules (prevent tool rot)

You already version schemas. Add a compatibility policy:

- unknown fields are ignored by readers

- breaking changes require a major version + a migration tool

- writers must not emit v2 until readers exist (or gate by config)

## 5) P1 hardening gaps (should address soon)

### 5.1 Enhanced Rebase needs convergence guards (no “retry forever”)

Rebase conflict resolution attempts must use progress signatures:

- conflict signature: paths + conflict object ids + parent rev + patch ids

- if the same signature repeats without new evidence, escalate and stop

### 5.2 Derived indexes and scalability

Directory scans are fine until they aren’t.

Keep indexes disposable, but define:

- who owns them (single-writer: root/project manager)

- how to rebuild

- when to invalidate

Optional technology (fits “no servers”):

- SQLite / FTS5 as a derived index (NOT source of truth) if JSON indexes become too slow.

### 5.3 Redaction / sensitive output policy

Local-only is not the same as safe-to-log.

Define minimal rules:

- mark events/artifacts as `sensitive: true`

- redact common secret patterns at emission time (best-effort)

- keep raw tool output chunked, but optionally store redacted copies for UI/printing

## 6) “Avoid max iterations” enforcement (system-wide termination patterns)

The principle exists; it must be applied uniformly.

**Standard pattern**

- define a stable “progress signature”

- if signature repeats with no novelty, stop and escalate with a consolidated evidence bundle

Apply to:

- task decomposition (already present)

- monitoring/self-healing loops

- enhanced rebase conflict resolution loops

- queue reprocessing / requeue loops

- markdown workflow interpretation (unknown edges rather than guessing)

## 7) Technology leverage (minimize bespoke complexity)

Where possible, prefer existing standards/libraries:

- JSON Merge Patch: use an RFC7396-compliant library or a well-tested implementation.

- IDs: ULID library with monotonic option for time-ordered IDs.

- Filesystem watching: watchdog (optional), but polling is acceptable when correctness is more important than immediacy.

- Graph outputs: generate Mermaid/DOT text; optionally render with Graphviz if installed.

- Atomic write helpers: use `os.replace` semantics for cross-platform replace and pair with fsync policy.

## 8) New/updated “analysis-level requirements” summary (checklist)

**Must**

- remove UI dependency entirely

- remove standalone background monitor/daemon

- add workflow graph CLI (dynamic from logs; static via extractor + optional LLM interpreter)

- add spawn_step control action so agents can request spawning without violating flat orchestration

- harden MCP gateway (single tool, allowlisted, typed)

- define robust queue claim/requeue/idempotency semantics

- fix filename timestamp hazards

- enforce WSS ownership + optional optimistic concurrency

- clarify step attempt identity semantics

- define log corruption handling

- reintroduce two-stage lint + selective tests progression

- reintroduce sandbox backend selection policy

- unify runtime root layout (`vcs/` + one conclusions location)

**Should**

- add schema evolution policy

- add redaction rules

- tighten rebase convergence guards

- define index rebuild rules

## 9) Open parameters (defaults recommended)

- Pause deadline defaults: short; if exceeded → investigator; never infinite waiting.

- Processing TTL for queue items: conservative (minutes) + single requeue, then escalate.

- Retention defaults: keep last N runs and N days, refuse to delete active runs.

- Sandbox backend selection: choose best available, record backend choice.





# Migration Guide: Align Current Specs to the Hardening Overlay (v4)

Last updated: 2026-01-23

This guide lists **specific changes** needed to bring the current spec set into alignment with:

- the clarified decisions (no UI, no daemon monitor, MCP gateway, no agent→agent direct spawning)

- the reinstated dropped details (two-stage lint/tests, sandbox backends, runtime root alignment)

- the hardening gaps identified in the overlay

This is a documentation + design migration guide (not a code diff).

## 0) Quick outcomes (what “done” looks like)

- The spec set no longer requires (or mentions) a Tauri UI for any flow.

- The spec set no longer describes a standalone background monitor/daemon process.

- Agents have **one** tool: a constrained workflow-engine gateway (MCP → workflowctl).

- Agents cannot spawn agents directly; they request spawns via control actions; root spawns.

- There is a CLI tool to produce workflow graphs (dynamic + static).

- Two-stage linting + selective test progression are explicitly specified.

- Sandbox construction backend policy is explicitly specified.

- Runtime root layout is consistent everywhere (includes `vcs/` and one conclusions location).

- Queue semantics are hardened (tmp/inbox/processing/outcomes + idempotency + requeue rules).

- WSS multi-writer correctness is enforceable (ownership + optional optimistic concurrency).

- “Avoid max iterations” is enforced uniformly with progress signatures.

## 1) Deprecations/removals to apply across the docs

### 1.1 Remove UI (Tauri) as a dependency everywhere

**Primary doc to deprecate**

- `UPDATED_Tech_Plan__Monitoring_UI_(Tauri).md`

**Edits to make**

- Mark the entire document as deprecated or remove it from the active spec set.

- Remove “UI” as an actor and any UI-driven flows.

**Docs that reference the UI and must be updated**

- Epic Brief: remove UI references from summary/solution components.

- Core Flows: remove Flow 13 (Optional Monitoring UI) and any UI actor references.

- Integration & File Structure: remove the `ui/` directory block and any Tauri references.

- Core Infrastructure: remove language that implies a UI must exist; keep notifications/control actions as CLI-consumable.

**Replacement UX**

- Project Manager and Ticket Manager become the primary notification “frontends”.

- `workflowctl notifications list|tail` replaces “UI consumes notifications stream”.

### 1.2 Remove the standalone background monitor/daemon concept

**Primary locations**

- `UPDATED_Tech_Plan__Monitoring_&_Self-Healing.md`: remove/rewrite “Root monitor (optional background)” as a separate process.

- `UPDATED_Tech_Plan__Integration_&_File_Structure.md`: remove `monitoring/monitor.py` as an “optional background monitor”.

**Replace with**

- “Root runtime monitoring loop” (in-process) that runs within:

  - Project Manager session when active

  - Ticket Manager session when executing runs

- Step processes keep their control loop + investigator spawning responsibilities.

## 2) Reintroduce dropped details (must add back)

### 2.1 Two-stage linting + selective tests strategy

**Where to add**

- Add a dedicated section in:

  - Core Infrastructure (as a required sandbox-run pattern), and/or

  - Project & Ticket Management (as part of ticket completion policy), and/or

  - Enhanced Rebase & Evaluation (as part of evaluation runs)

**What to specify**

- “Hunk lint” stage and outputs (fast reject).

- “Sandbox lint” stage and outputs (full).

- Test selection roadmap:

  - now: changed-package + smoke tests

  - later: reverse-dep mapping

- Required artifacts:

  - lint report artifact path(s)

  - test selection rationale artifact path(s)

### 2.2 Sandbox backend selection policy

**Where to add**

- Core Infrastructure: Sandboxes section (currently only states invariant).

- Integration & File Structure: sandbox runner module responsibilities.

**What to specify**

- Ordered backend selection + fallback behavior.

- Required logging of backend choice + reason.

- Explicit retention and cleanup rules for the fallback “full copy” case.

### 2.3 Runtime root layout alignment (`vcs/` and conclusions location)

**Where to reconcile**

- Analysis v3 vs Core Infrastructure runtime root example.

**What to do**

- Pick and document one canonical layout across:

  - Analysis v3 (or superseding analysis file)

  - Core Infrastructure tech plan

  - Integration plan

- Add `vcs/` explicitly for jj metadata/pointers.

- Choose one conclusions location and update all paths consistently.

## 3) Add the new hardening requirements (by spec)

This section tells you *where* each hardening change belongs.

### 3.1 Workflow graph / introspection CLI (new spec section or new doc)

**Add**

- A “Workflow Introspection & Graphing” section (or new Tech Plan file).

**Must specify**

- `workflowctl graph --run <run_id>` (dynamic, derived from logs + WSS)

- `workflowctl graph --workflow <name>` (static best-effort)

- Outputs:

  - Mermaid text

  - JSON graph

- Artifact storage:

  - `workspace/runs/<run_id>/artifacts/graphs/`

- Static graph pipeline:

  - deterministic extraction first

  - optional LLM interpreter with evidence-backed edges and `unknown` nodes

**Docs to update to reference it**

- Integration & File Structure (new module boundary)

- Core Flows (add a flow for “generate graph”)

- Monitoring & Self-Healing (use graphs as investigation evidence)

### 3.2 Spawn-step control action (agent→root spawn requests)

**Update**

- Core Infrastructure: Control Actions Queue schema (add `spawn_step` action type).

- Integration: orchestration + step instrumentation (how spawn is requested/acked).

- Core Flows: update any “agent spawns agent” narrative to use spawn requests.

**Must specify**

- request schema fields:

  - `request_id`, `action_type`, `target` (run_id), payload (workflow/agent name, inputs), `parent_step_execution_id` (logical)

- ack behavior (written by root) returning `step_execution_id`

- `workflowctl wait` behavior for dependent steps

### 3.3 MCP gateway as the only agent tool (execution through workflow engine)

**Add**

- A clear “MCP Tool Gateway” section (ideally in Integration plan).

**Must specify**

- Only one MCP tool: workflowctl gateway.

- Allowlisted subcommands only.

- Typed args (JSON) and JSON outputs.

- Every gateway call is logged as tool_start/tool_stop with a fingerprinted args class.

- Python execution:

  - agents run python scripts via workflow engine (not direct interpreter)

  - python invocations are captured as tools/steps (auditable, pausable)

### 3.4 Queue semantics hardening (claim/requeue/idempotency)

**Update**

- Core Infrastructure: Notifications Store + Control Actions Queue sections.

**Must specify**

- tmp/ → inbox/ → processing/ → outcomes

- atomic claim via rename into processing

- requeue TTL and single requeue rule

- dedupe/idempotency keys

### 3.5 Filename safety hardening

**Update**

- Core Infrastructure: notification filename pattern (replace RFC3339 filename usage)

- Any other places that embed timestamps in filenames

### 3.6 WSS ownership + optimistic concurrency (optional rev)

**Update**

- Core Infrastructure: WSS document requirements + update semantics

- Integration: wss helper behavior (refuse patch when not owner)

- Monitoring: investigator output may include WSS patches; must respect expected_rev semantics

### 3.7 Step attempt identity semantics

**Update**

- Core Infrastructure: run/step doc schema and retry semantics

- Monitoring: progress signatures keyed by step_execution_id/attempt semantics

- Graphing: attempts become distinct nodes (recommended)

### 3.8 Log corruption tolerance

**Update**

- Core Infrastructure: Logs Store reader contract (ignore trailing partial line; error on mid-file corruption)

### 3.9 Schema evolution policy

**Update**

- Core Infrastructure: add compatibility rules for schema_version

- Integration: schema helpers enforce rules

### 3.10 Rebase convergence guards

**Update**

- Enhanced Rebase & Evaluation:

  - add conflict signature definition

  - apply progress-signature repeat/novelty rules

  - no open-ended retry loops

### 3.11 Redaction/sensitive output policy

**Update**

- Core Infrastructure: log/event fields allow `sensitive: true` + redaction guidance

- Monitoring: ensure evidence bundles can include redacted summaries

## 4) Spec-by-spec change checklist (practical)

### 4.1 `UPDATED_Tech_Plan__Monitoring_UI_(Tauri).md`

- Deprecate/remove doc from active set.

- Move any remaining useful concepts into CLI documentation (notifications/control actions).

### 4.2 `UPDATED_Tech_Plan__Monitoring_&_Self-Healing.md`

- Remove “Root monitor (optional background)” as a separate process.

- Reframe as:

  - root runtime monitoring loop (in-process)

  - step control thread (unchanged)

  - investigator job (unchanged)

  - workflow repair agent (unchanged)

- Ensure all loops use progress signatures (no max iterations).

### 4.3 `UPDATED_Tech_Plan__Integration_&_File_Structure.md`

- Remove `monitoring/monitor.py` from file layout.

- Remove `ui/` directory block.

- Add module boundaries for:

  - workflow graph generator

  - MCP gateway wrapper (optional directory)

- Add explicit rule:

  - “agents execute python/tools only via workflow engine gateway”

### 4.4 `UPDATED_Tech_Plan__Core_Infrastructure_&_Data_Model.md`

- Add:

  - queue claim/requeue/idempotency semantics

  - filename safety rule for notification/control filenames

  - step attempt identity rule

  - log shard corruption tolerance

  - schema evolution policy

  - sandbox backend selection policy

  - two-stage linting + test strategy (or link to where it lives)

  - spawn_step control action type

  - runtime root layout reconciliation (`vcs/`, conclusions location)

### 4.5 `UPDATED_Tech_Plan__Enhanced_Rebase_&_Evaluation.md`

- Add:

  - rebase conflict progress signatures + convergence guards

  - explicit “stop + escalate” rules (no infinite retries)

- Ensure evaluation artifacts include:

  - lint/test selection rationale and evidence refs

### 4.6 `UPDATED_Tech_Plan__Project_&_Ticket_Management.md`

- Ensure:

  - notifications are handled in CLI (Project Manager QA mode)

  - any mentions of UI are removed

  - decomposition rules are consistent with progress signatures

  - task execution and python scripts run through workflow engine (gateway)

- Add reference to:

  - workflow graph tool usage for debugging and comprehension

### 4.7 `UPDATED_Core_Flows__Project_Management_&_Autonomous_Monitoring.md`

- Remove UI actor and UI flow.

- Remove standalone Monitor actor (or rename to “in-process monitoring loop”).

- Add flow:

  - “generate workflow graph for run_id” and “static workflow graph for command file”.

### 4.8 `UPDATED_Epic_Brief__Multi-Layered_Project_Management_System.md`

- Remove UI component from the “five integrated components” list.

- Clarify monitoring is in-process (root + step processes).

- Add “workflow introspection/graphing” as a success criterion.

## 5) Ordering (recommended migration sequence)

1) Deprecate/remove UI references across all docs.

2) Remove standalone monitor references across all docs.

3) Add spawn_step control action + wait semantics.

4) Add MCP gateway section (single tool, allowlisted, typed; python execution via engine).

5) Add workflow graph tooling spec (dynamic first).

6) Add queue hardening semantics + filename safety.

7) Add WSS ownership + optimistic rev.

8) Reintroduce two-stage lint/tests + sandbox backend policy + runtime root alignment.

9) Add remaining P1 items (schema evolution, redaction, index rules, rebase convergence).

---

[CRITICAL] jj Change Stack Lifecycle - Creation, Promotion, and Cleanup
The specs describe tickets as "jj change stacks" and mention "export stack to target branch policy" but don't specify the complete lifecycle:

Gap 1 - Stack Creation: Flow 5 says "create jj change stack for the ticket" but doesn't specify:

What is the parent/base of this stack? (current branch HEAD? project stack? user's working branch?)
Where does the jj repo live? (shadow base checkout? separate jj repo?)
How is the stack named/identified in jj?
Gap 2 - Promotion/Export: Flow 9 says "export stack to target branch policy (squash or linear)" but doesn't specify:

Does "export" mean creating real git commits on the shadow base checkout?
What happens to the jj stack after export? (deleted? marked promoted? kept for history?)
If multiple tickets export to the same target branch, how are conflicts handled?
Gap 3 - Cleanup: No flow describes when/how jj stacks are cleaned up:

Are old stacks kept indefinitely?
Is there a GC policy for promoted stacks?
What happens to stacks for abandoned tickets?
Why This Matters: The jj change stack is the core primitive for code changes. Without clear lifecycle semantics, implementers won't know how to create, manage, or clean up stacks correctly.

Question: Please specify the complete jj change stack lifecycle from creation through cleanup.

A. Provide complete jj stack lifecycle specification

[CRITICAL] Virtual Hydration Implementation - How Does It Actually Work?
Flow 7 mentions "Context manager hydrates files from the ticket stack (virtual hydration)" but the mechanism is underspecified:

Gap 1 - Hydration API: How do agents request file hydration?

Do they call workflowctl hydrate <ticket_id> <path>?
Does the context manager automatically hydrate files mentioned in the step plan?
Do agents get a "virtual filesystem" where reads are automatically hydrated?
Gap 2 - Hydration Scope: What can be hydrated?

Only files modified in the ticket stack?
Any file in the repo (base + stack)?
Can agents hydrate files at specific revisions/commits in the stack?
Gap 3 - Hydration Performance: For large files or many files:

Is there caching?
Are there size limits?
What happens if hydration fails (file doesn't exist in stack)?
Gap 4 - Patch Creation: Flow 7 mentions "Mode A: blind patch editor" and "Mode B: sandbox editor" but doesn't specify:

How does the agent choose between modes?
In Mode A, how does the agent create a patch without seeing the full file context?
In Mode B, how is the sandbox created from the stack?
Why This Matters: Virtual hydration is a core mechanism that agents will use constantly. Without clear semantics, agents won't know how to read files or create patches correctly.

Question: Please specify the virtual hydration API, scope, performance characteristics, and how it integrates with patch creation.

A. Provide complete virtual hydration specification

[CRITICAL] Decomposition Orchestrator - Multi-Pass Approval Gates
Flow 6 mentions "decomposition orchestrator (multi-pass, approval gated)" but the actual process is not documented in Core Flows:

Missing Details:

What are the passes? (pattern discovery → candidate surfacing → approval → verification → recursion?)
Who approves? (agent? user? automated validation?)
What are the approval criteria?
How are denied files handled?
What is the convergence condition? (all files approved? progress signature?)
Where is the orchestrator logic documented?
Current State:

Epic Brief mentions "decomposes tasks into steps with approval gates"
Flow 6 says "invoke decomposition orchestrator"
No flow describes what the orchestrator actually does
Why This Matters: Task decomposition is the entry point for all ticket work. Without understanding the multi-pass approval process, users won't know what to expect or how to handle decomposition failures.

Question: Should the decomposition orchestrator process be documented as a separate flow in Core Flows, or is it detailed in one of the Tech Plans?

A. Add detailed decomposition flow to Core Flows

B. Reference existing Tech Plan section (specify which)

C. Decomposition details deferred to implementation

[SIGNIFICANT] Mandatory PAUSE Protocol - Request, ACK, and Enforcement
The constraints state "Pause is mandatory: on PAUSE, processes must stop promptly; enforcement is inside each process" but the actual protocol is not documented in the flows:

Missing Protocol Details:

How is PAUSE requested? (control action file? signal? API call?)
What does "ACK PAUSE" mean? (write ACK file? update step status? log event?)
What is "promptly"? (deadline in seconds? immediate?)
What happens if a step cannot pause within the deadline?
How does RESUME work? (another control action? automatic after investigation?)
Can individual steps be paused, or only entire runs?
Current State:

Constraints mention mandatory pause
Flow 14 mentions "Request PAUSE for the step or run" and "Step must ACK PAUSE promptly"
No flow documents the complete pause/resume protocol
Why This Matters: Mandatory pause is a core control mechanism. Without a clear protocol, implementers won't know how to build pause enforcement into step processes.

Question: Please specify the complete PAUSE/RESUME protocol including request format, ACK format, deadlines, and enforcement mechanisms.

A. Provide complete PAUSE/RESUME protocol specification

[SIGNIFICANT] Spawn-Step Control Action - Agent Spawning Without Grandchildren
The constraints state "Root orchestration is flat: root directly owns/controls all step/agent processes (no grandchildren)" but the flows don't explain how agents spawn other agents without violating this:

The Contradiction:

Constraint says "no grandchildren" (agents can't spawn agents directly)
But agents need to spawn sub-agents for investigation, decomposition, etc.
The v4 overlay mentions spawn_step control action but it's not in the flows
Missing Details:

How does an agent request spawning another agent?
What information must be in the spawn request?
How does the requesting agent wait for the spawned agent to complete?
How is the parent-child relationship tracked (for graphs and evidence)?
What happens if spawn fails?
Current State:

No flow documents agent-to-agent spawning
No flow shows how spawn_step control action works
Why This Matters: Many workflows require sub-agents (decomposition, investigation, repair). Without a clear spawning mechanism, the flat orchestration constraint cannot be satisfied.

Question: Please document the spawn-step control action flow, including request format, root handling, waiting mechanism, and parent-child linkage.

A. Add spawn-step flow to Core Flows

B. Document in Tech Plan only (specify which)

[SIGNIFICANT] MCP Gateway - Single Tool Constraint
The v4 overlay states "Agents must not run Python or arbitrary commands directly. All execution goes through the workflow engine via ONE MCP tool" but this is not reflected in the flows:

Missing Details:

What is the MCP tool called? (workflow_engine? workflowctl?)
What subcommands are allowlisted?
How do agents execute Python scripts? (via workflowctl run-script?)
How are arguments validated/typed?
What happens if an agent tries to use a non-allowlisted command?
Current State:

No flow mentions MCP tools or execution constraints
Flows assume agents can execute arbitrary operations
No documentation of the allowlisted command surface
Why This Matters: This is a fundamental security and auditability constraint. Without documenting the MCP gateway, implementers won't know how to constrain agent execution correctly.

Question: Please specify the MCP gateway tool name, allowlisted subcommands, argument validation, and how agents execute Python/tools through it.

A. Provide MCP gateway specification

[MODERATE] Workflow Graph Generation - Static vs Dynamic
The v4 overlay requires workflow graph generation (workflowctl graph) but this capability is not documented in the flows:

Missing Flow:

How does a user generate a workflow graph?
What's the difference between static graph (from workflow definition) and dynamic graph (from run execution)?
Where are graphs stored?
What format are they in? (Mermaid? DOT? JSON?)
When should users generate graphs? (debugging? planning? always?)
Current State:

No flow describes graph generation
No mention of workflowctl graph command
No explanation of how graphs help users
Why This Matters: Workflow graphs are critical for understanding complex hybrid workflows (markdown + Python + agents). Without documenting when and how to use them, users won't leverage this capability.

Question: Should I add a new flow "Generate Workflow Graph" to Core Flows, or is this documented elsewhere?

A. Add new flow to Core Flows

B. Document in Tech Plan only

C. Defer to implementation (not user-facing)

[MODERATE] Two-Stage Linting - When and How
The v4 overlay requires two-stage linting (hunk lint + sandbox lint) but this is not reflected in the flows:

Missing Details:

When does hunk lint run? (after each step? after each patch? on demand?)
When does sandbox lint run? (after all steps? before ticket closure? on demand?)
What happens if hunk lint fails? (block patch creation? raise notification?)
What happens if sandbox lint fails? (block ticket closure? create new task?)
Are both stages mandatory or optional?
Current State:

Flow 7 mentions "run sandbox validation (as configured)"
Flow 9 mentions "run final sandbox validation"
No mention of hunk lint or two-stage approach
Why This Matters: Two-stage linting is a key UX optimization (fast feedback). Without documenting when each stage runs, users won't understand the validation workflow.

Question: Should I add two-stage linting details to Flow 7 (Task Execution) and Flow 9 (Ticket Completion)?

A. Yes, add to Flow 7 and Flow 9

B. Document in Tech Plan only (not user-facing)

C. Make it configurable (user chooses when to lint)

I've identified 8 critical gaps in the requirements. These questions focus on the most important areas:

jj change stack lifecycle - Core primitive, must be fully specified
Virtual hydration - Core mechanism, agents need clear API
Decomposition orchestrator - Entry point, must be documented
PAUSE protocol - Core control mechanism, needs complete specification
Spawn-step control action - Enables flat orchestration, must be clear
MCP gateway - Security constraint, must be documented
Workflow graph generation - Debugging capability, needs user guidance
Two-stage linting - UX optimization, needs clear timing
Once these are clarified, I'll update the specs and continue with the remaining phases of the v4 migration. are clarified, I'll update the specs and continue with the remaining phases of the v4 migration.

---

Below are concrete, end-to-end answers for all 8 gaps, written to be directly “spec‑insertable” later, but presented here as analysis (no doc edits).

1) [CRITICAL] jj change stack lifecycle (creation → promotion/export → cleanup)

1.1 Definitions (what a “ticket stack” is in jj)

A ticket stack is represented as:

- A linear chain of jj changes whose base parent is a chosen base revision, and whose tip is tracked by a dedicated bookmark.
- Each patch produced by step execution corresponds to one jj change (one “patch change”) appended on top of the stack.
- The stable identifier for patch items should be jj change IDs, not commit hashes, because change IDs remain stable across rewrites. (JJ VCS Docs)

This matches “Ticket = change stack” and “Patch = atomic change object” in the PGS adapter surface.

1.2 Where the jj repo lives (PGS repo placement)

Support two modes, with a single “resolved jj repo path” stored in runtime metadata:

Mode 1 (default): colocated jj repo in the user’s repo

- Assumes the repo is a git repo and is initialized for jj colocated operation (jj alongside .git).
- Lowest friction for local operation and aligns with using existing repo without maintaining a second checkout.
- jj supports colocated init and treats it as default behavior in typical configurations. (Arch Manual Pages)

Mode 2 (optional): sidecar jj repo under runtime root

- Store jj state under ~/.workflow/repos/<repo_uid>/vcs/jj/.
- Use jj’s “backed by an existing git repo” pattern (--git-repo) to avoid “modifying” the main repo directory with jj metadata. (Arch Manual Pages)
- Use this when you want to enforce “single runtime root” strictly.

PGS runtime metadata (authoritative) Store (or derive and then persist) in: ~/.workflow/repos/<repo_uid>/vcs/pgs.json (this is the “vcs/” directory that needs to be added back)

Example:

{   "schema_version": 1,   "repo_uid": "…",   "pgs_backend": "jj",   "jj_mode": "colocated",   "jj_repo_path": "/home/me/src/repo",   "git_repo_path": "/home/me/src/repo",   "bookmark_prefix": "wf/" } 

1.3 Stack naming and identification in jj

Use jj bookmarks as the canonical “locator” for stacks. Bookmarks are named pointers to revisions and can be moved/updated. (JJ VCS Docs)

Naming convention (deterministic, collision-resistant):

- Ticket tip bookmark: wf/ticket/<ticket_id>
- Export bookmark (optional): wf/export/<ticket_id>
- Baseline bookmark: wf/baseline/<project_id> (or wf/baseline/default if you don’t want per-project)

If ticket IDs contain characters you don’t want in bookmark names, apply a reversible encoding (e.g., replace / with __).

Ticket WSS metadata (minimum required) workspace/tickets/<ticket_id>/ticket.json stores:

- ticket_bookmark (string)
- base_rev (jj revset string or resolved change/commit id)
- tip_rev (resolved id at last update; informational)
- jj_mode + repo path pointer (or indirect pointer to vcs/pgs.json)

This aligns with “stores stack metadata in ticket.json”.

1.4 Stack creation (Gap 1 answers)

Flow 5 says “create jj change stack for the ticket” but not how. Here is the complete spec:

Inputs

- ticket_id
- project_id
- Optional: base_ticket_id (for stacked tickets)
- Project baseline policy (baseline_ref)

Parent/base selection (deterministic)

1. If ticket.json declares base_ticket_id (explicit dependency stack):
  - parent_rev = resolve_tip(base_ticket_id)
2. Else:
  - parent_rev = resolve_project_baseline(project_id)

Baseline definition

- Default baseline is the configured “target branch head” (e.g., main) at ticket creation time, not “whatever branch the user currently has checked out”. This is consistent with Ticket Manager: “parent revision is the project baseline (or selected branch head)”.

Creation procedure

1. Resolve parent_rev in jj.
2. Create a new empty change on top of parent_rev (this is the stack root).
3. Create/move bookmark wf/ticket/<ticket_id> to that new change.
4. Persist ticket.json stack metadata.

Result: a ticket stack exists and is addressable by wf/ticket/<ticket_id>.

1.5 Patch application (how the stack evolves)

Each step that produces a patch:

1. Creates a new jj change on top of current wf/ticket/<ticket_id> tip.
2. Applies the patch diff into that new change.
3. Moves wf/ticket/<ticket_id> bookmark to the new tip.
4. Records the new patch change ID in:
  - the step execution evidence (tool_stop data + WSS step doc metadata), and optionally
  - a ticket-level patch list.

This is the operational meaning of apply_patch(stack_id, patch) -> patch_id.

1.6 Promotion / “export stack to target branch policy” (Gap 2 answers)

Flow 9 says “export stack to target branch policy (squash or linear)” but doesn’t define semantics. Here is the complete spec:

Export = “materialize the ticket stack into a Git branch/ref according to policy”

- The result must be a normal Git branch pointer (or equivalent) that users can:
  - inspect with git tooling,
  - push, PR, merge, etc.

Important jj fact

- jj git export updates the underlying git repo with jj changes; in a colocated workspace export happens automatically. (JJ VCS Docs) (You still need to decide what Git ref/branch to move to point at the exported commit(s).)

Export targets

Two supported export target policies:

Policy A (recommended default): per-ticket branch

- Export the ticket stack onto a branch like: wf/ticket/<ticket_id>
- This avoids cross-ticket export conflicts by construction.

Policy B (optional): shared integration branch

- Export multiple tickets onto a shared branch (e.g., wf/integration/<project_id>)
- Requires serialization + rebase discipline (see conflicts below).

Export modes

Mode: linear

- Preserve each patch change as a distinct commit in the exported branch.
- Commit message policy:
  - default: step title + ticket id + patch index
  - include change-id and evidence refs in message footer if desired.

Mode: squash

- Produce exactly one commit for the entire stack (diff from base_rev → tip_rev).
- Commit message policy:
  - ticket title + ticket id
  - include linkable evidence refs.

Conflicts when exporting to a shared target branch

If multiple tickets export to the same target branch, enforce:

1. Branch lock (serialize mutations)

- Use a runtime lock file under: ~/.workflow/repos/<repo_uid>/vcs/locks/branch.<branch>.lock
- Only one export to a given branch can run at once.

1. Precondition check (do not “merge during export”)

- Export must refuse if:
  - target branch head ≠ ticket’s expected base (or expected baseline)
- If refused:
  - require rebase of the ticket stack onto the current target head (conflicts handled by Enhanced Rebase).

1. Conflict handling is a rebase concern, not an export concern

- Conflicts are resolved via the “conflicts are data / resolver jobs” rebase flow, producing patches and durable records.

What happens to the jj stack after export

Do not delete immediately. Define post-export states:

- active: not exported or reopened
- exported: exported successfully; stack still present
- archived: no longer active; kept for retention
- gc_eligible: safe to delete bookmark and allow pruning

Minimum required behavior:

- Mark in ticket.json:
  - export.status = success
  - export.mode = squash|linear
  - export.target_branch
  - export.exported_at
  - export.exported_commit_ids (git SHAs) and/or export.tip_change_id

This matches “record export metadata in ticket.json”.

1.7 Cleanup / GC (Gap 3 answers)

Define a deterministic cleanup policy and a single GC entrypoint (workflowctl gc already exists as a referenced command).

Ticket abandonment

- Ticket status transitions to abandoned in WSS.
- Action:
  - rename bookmark wf/ticket/<ticket_id> → wf/abandoned/<ticket_id> (preferred), or delete it.
- Result: abandoned stacks are not mixed with active stacks.

Promoted/exported ticket retention

- Keep exported stacks for at least:
  - retention_days_exported (default e.g., 30) OR
  - retention_runs_exported (default e.g., last 50)
- After retention:
  - delete/rename ticket bookmark to archive namespace
  - mark gc_eligible = true

GC procedure (workflowctl gc)

1. Refuse to run if any active runs are executing for this repo.
2. Enumerate tickets in WSS:
  - identify done|abandoned and old enough.
3. For each gc-eligible ticket:
  - delete or archive its bookmark
  - optionally invoke jj’s internal GC (implementation detail)
4. Emit a GC report artifact under: workspace/conclusions/ or workspace/runs/<run_id>/artifacts/gc/…

Safety invariant

- Never GC:
  - stacks referenced by in_progress tickets
  - stacks referenced by active runs
  - stacks referenced by unresolved investigation bundles

2) [CRITICAL] Virtual hydration implementation (API, scope, performance, patch creation integration)

Your Core Infrastructure plan defines “virtual hydration” and includes adapter ops and a minimal CLI surface, but it needs the operational semantics filled in.

2.1 Hydration API (how agents request file content)

Do not implement a magic virtual filesystem. Keep hydration explicit.

Canonical API surfaces

A) CLI (human + scripts)

- workflowctl hydrate <ticket_id> <path> [--rev base|tip|<change_id>] [--out <file>] [--slice <line_range>]

B) MCP (agents)

- All hydration requests go through the single MCP gateway tool (see section 6).
- The MCP wrapper calls the same allowlisted workflowctl hydrate subcommand.

C) Internal runtime

- Step context manager calls PGS:
  - hydrate_file(stack_id, path)
  - hydrate_tree(stack_id, paths[]) as already listed.

Return shape (for agent-friendly usage)

Hydrate returns structured JSON:

{   "ok": true,   "ticket_id": "…",   "path": "src/foo.py",   "rev": "tip",   "resolved_rev": "kntqzsqt",    "content_encoding": "utf-8",   "content": "…",   "content_hash": "blake3:…",   "size_bytes": 12345 } 

If too large, return:

- content: null
- blob_ref: "caches/hydration/blobs/<hash>" and require chunk reads via workflowctl blob read --offset --len … (allowlisted).

2.2 Hydration scope (what can be hydrated)

Hydration must support:

1. Any file at the hydrated revision

- Not only modified files.
- Agents often need “unchanged context” to make correct edits.

1. Revision selectors

- base: the ticket’s current base parent revision
- tip: the ticket stack tip
- <change_id>: any patch change in the stack (to inspect intermediate states) This is consistent with “anchor + patch stack” and “hydrate at a given revision”.

1. Nonexistent file behavior

- If file does not exist at the requested revision:
  - return ok=false, error_code="NOT_FOUND", and include:
    - whether it exists at base or tip
    - a list of nearby paths (simple prefix match)
- This must be a “single-shot” failure (no retries / no max-iteration loop).

2.3 Hydration performance (caching, limits, failures)

Hydration is invoked constantly; you need predictable behavior.

Caching

- Cache hydrated blobs under: ~/.workflow/repos/<repo_uid>/caches/hydration/blobs/<content_hash>
- Cache key: (resolved_rev, path) → content_hash
- Cache is disposable and never the source of truth.

Size limits

- Default:
  - inline return limit: 256 KiB
  - above that: return blob_ref and require chunk reads
- For very large files (e.g., > 5 MiB), recommend Mode B sandbox editing automatically.

Failure semantics

- If hydration fails due to jj/VCS error:
  - return structured error with a stable error_id
  - emit a notification only if user action is required
  - do not auto-loop

2.4 Patch creation integration (Mode A vs Mode B)

These modes already exist in Integration.

Mode selection (no max iterations)

Default policy:

- Prefer Mode A unless any of these triggers are true:
  - agent needs repo-wide search (rg) or formatter/test tool feedback
  - change spans “many files” (threshold configurable)
  - any requested hydration exceeds size threshold
  - patch fails hunk-lint twice with the same failure signature (progress guard)

Mode selection is allowed to change once evidence changes, never by dumb iteration.

Mode A: blind patch editor (precise spec)

1. Agent requests hydration for specific paths (full file or slices).
2. Agent produces a unified diff (or structured hunks).
3. Engine runs hunk lint (see section 8).
4. If hunk lint passes:
  - workflowctl apply-patch <ticket_id> --diff <patch_file>
5. Engine records patch_change_id and evidence refs.

Key hardening:

- If patch doesn’t apply cleanly, reject fast; do not “try again N times”.

Mode B: sandbox editor (precise spec)

1. Engine creates an ephemeral sandbox hydrated from ticket stack tip:
  - workflowctl sandbox run <ticket_id> -- <tooling>
2. Agent runs allowed tooling inside sandbox (through workflow engine).
3. Engine captures resulting diff vs hydrated baseline.
4. Engine runs hunk lint; if passes, applies patch to stack.

Sandbox creation backend options (add-back dropped detail #2) Declare “approved sandbox backends” (selection order):

1. overlay/union (where supported)
2. reflink clone (where supported)
3. hardlink clone (safe subset)
4. fallback full copy only with explicit warning and retention cap (Analysis v3 recommended documenting this list; it was dropped.)

3) [CRITICAL] Decomposition orchestrator (multi-pass approval gates)

You already have the components named, but not a user-visible flow. The decomposition system is partially described in Project & Ticket Management and in the Integration module map.

Answer to the “where should it live” question

Choose: A. Add detailed decomposition flow to Core Flows. Because it is the entry point to all ticket work (Flow 6 calls it but doesn’t define it).

Also reference the existing Tech Plan sections as implementation mapping, but Core Flows needs the behavior.

3.1 Complete decomposition process specification (passes + approval + convergence)

Inputs

- ticket_id, task_id
- task_input_md
- optional constraints: “files must remain together”, “prefer module boundaries”, etc.

Outputs

- steps/step_<n>.md files
- decomposition artifact bundle:
  - candidate_set.json
  - approval_decision.json
  - verification_report.json
- durable logging in run shards

Pass 0: Normalize + fingerprint

- Compute task_input_hash.
- Emit decomposition_start event with hash.

Pass 1: Pattern discovery (agent)

Goal: propose boundary rules. (Already described.) Output: surfacing_rules.json (e.g., “split by module”, “group tests with implementation”).

Pass 2: Candidate surfacing (script)

Goal: apply surfacing rules to propose step boundaries. (Already described.) Output: candidate_set.json containing:

- ordered steps
- per-step file list (or file patterns if too many)
- explicit dependencies between steps

Pass 3: Approval gate (agent + optional user)

Approval has three outcomes:

- approved
- denied_with_edits (approved after rewriting plan)
- needs_user (cannot safely decide)

Who approves

- Default: approval agent approves automatically.
- If approval agent returns needs_user, emit a notification and block until user provides an approval control action or edits step files. (No UI required; CLI is enough.)

Approval criteria

- Each file assigned to one step unless explicitly marked “multi-touch”
- Steps are coherent and testable
- Cross-step dependencies form a DAG
- No “giant step” unless explicitly justified

Pass 4: Verification (agent)

Verification checks:

- file overlap violations
- “multi-step file” detection
- missing prerequisites
- obvious ordering problems

Convergence / termination (no max iterations)

Use the progress guards already specified in concept, but make them explicit here.

- Define progress_signature = hash(task_input_hash + candidate_set + approval_decision + verification_result)
- If the same progress_signature repeats:
  - mark unsplittable
  - write decomposition_problem_record.md
  - raise notification and stop (no further passes)
- Novelty rule:
  - any repeat pass must add new evidence or terminate

4) [SIGNIFICANT] Mandatory PAUSE / RESUME protocol (request, ACK, deadlines, enforcement)

Core Infrastructure defines the control queue and sketches pause/ack but leaves key details open. Monitoring reinforces that PAUSE is mandatory and enforced inside each process.

4.1 Request format (authoritative)

PAUSE/RESUME are control action files in: control_actions/inbox/ with the existing schema.

- action_type: "pause" or "resume"
- target can be:
  - a single step_execution_id
  - a whole run_id (fan-out semantics)

4.2 ACK format (authoritative)

ACK is a file written by the target step process:

Path:

- control_actions/ack/pause.<request_id>.<step_execution_id>.json
- control_actions/ack/resume.<request_id>.<step_execution_id>.json

Body:

{   "schema_version": 1,   "request_id": "…",   "action_type": "pause",   "run_id": "…",   "step_execution_id": "…",   "ack_ts": "2026-01-23T00:00:00Z",   "result": "acknowledged",   "details": {     "tool_subprocesses_stopped": true,     "logs_flushed": true,     "wss_mutations_stopped": true   } } 

Also emit log events:

- pause_requested, pause_ack, resume_requested, resume_ack as already enumerated.

4.3 What “paused” means (locked definition)

Use the definition already stated, but make it strict:

A step is paused only when all are true:

1. no tool subprocess running
2. no WSS mutation in progress
3. step is in control loop waiting for RESUME/STOP
4. log shard boundary flushed

(Your Core Infrastructure doc already defines this; treat it as a hard contract.)

4.4 Deadlines (“promptly”) and enforcement

Define two deadlines (configurable, with defaults):

- pause_check_interval_ms (default: 250ms) Max time between “safe points” where a step must check for pause.
- pause_ack_deadline_ms (default: 2000ms if idle, 10000ms if draining tools) Max time from observing pause request → writing pause ACK.

If cannot ACK by deadline

- Step must spawn an investigator job (same mechanism as monitoring) and emit:
  - pause_ack with result="investigating" (or raise an error event)
- Root may escalate only if investigator returns needs_shutdown.

4.5 RESUME semantics

- RESUME is symmetrical:
  - on resume request, step writes resume ACK and continues from a defined safe continuation point (usually “continue current step attempt” unless the step recorded a resume plan artifact).

4.6 Scope: pause step vs pause run

- If target is a run:
  - Root should write one pause request targeting the run_id.
  - Each step process checks for run-level requests and ACKs individually.
  - Root considers run paused when all active steps have acked.

No UI/daemon required for any of this; it works with only file queues and the root runtime.

5) [SIGNIFICANT] Spawn-step control action (flat orchestration, no grandchildren)

This is required to reconcile “no grandchildren” with “agents need sub-agents”. The step doc already has parent_step_execution_id, which is the correct linkage primitive.

Answer to “where documented”

Choose: A. Add spawn-step flow to Core Flows (it is a core orchestration invariant).

5.1 Control action type: spawn_step

Write request file into control_actions/inbox/:

{   "schema_version": 1,   "request_id": "…",   "ts": "…",   "created_by": "step_process",   "action_type": "spawn_step",   "target": { "run_id": "…" },   "payload": {     "parent_step_execution_id": "…",     "child_workflow_type": "agent|python_script",     "entrypoint": "path/or/registered_id",     "args": { "…": "…" },     "ticket_id": "…",     "task_id": "…",     "purpose": "investigation|decomposition|repair|other",     "wait": true   } } 

5.2 Root handling

Upon receiving spawn_step:

1. Validate:
  - run exists and is not paused
  - parent_step_execution_id is valid
2. Allocate:
  - child_step_execution_id
  - writer_id
3. Create child step execution doc with:
  - parent_step_execution_id = parent
4. Spawn OS process as a direct child of root (flat ownership)
5. Write ACK:
  - control_actions/ack/spawn_step.<request_id>.json with child_step_execution_id

5.3 Waiting mechanism (parent side)

Parent should not busy-loop. Provide a single primitive (CLI and MCP):

- workflowctl wait-step <child_step_execution_id> [--timeout …] This blocks by:
- watching the child step doc status in WSS
- tailing shard as needed (optional)

5.4 Failure behavior

- If spawn fails:
  - root writes failed ack with reason
  - parent treats as terminal failure (or escalates) — no retries without novelty
- If child fails:
  - parent receives terminal status via wait-step
  - parent may:
    - raise notification,
    - request repair,
    - or stop.

This gives you the graph edges you need for visualization (see #7) without violating flat orchestration.

6) [SIGNIFICANT] MCP gateway (single tool constraint)

This is a hard security + auditability boundary and should be specified explicitly (even if UI/daemon are removed).

6.1 Tool name + single-tool rule

Define exactly one MCP tool, e.g.:

- Tool name: workflow_engine
- One method: invoke(payload: JSON) -> JSON

All agent execution goes through it:

- hydration
- patch application
- sandbox runs
- spawning sub-agents
- running python scripts (as workflow steps)

6.2 Allowlisted subcommands (recommended minimum set)

Expose subcommands as structured payloads (no shell strings):

- help / docs (returns schema and examples)
- hydrate
- apply_patch
- sandbox_run
- spawn_step
- wait_step
- control_write (pause/resume/trace/retry)
- graph_static
- graph_run
- run_python_script (registered scripts only)

6.3 Python execution rule (critical)

Agents must not run arbitrary Python code strings.

Instead:

- run_python_script can only run:
  - scripts under a registered allowlist, e.g. scripts/manifest.json, or
  - entrypoints referenced by workflow definitions (known safe set)

Each script has a strict argument schema.

6.4 Argument validation / typing

For each subcommand:

- validate payload against a JSON schema (or Pydantic model)
- reject unknown fields
- enforce repo-relative paths (deny absolute paths and ..)
- enforce max sizes (patch size, hydration size, etc.)

6.5 Non-allowlisted command behavior

If an agent tries an unknown command:

- return { ok:false, error_code:"NOT_ALLOWED" }
- emit error + notification_raised only if it indicates a misconfigured workflow

This aligns with “protocol discipline prevents rot” and “ID-driven evidence”.

7) [MODERATE] Workflow graph generation (static vs dynamic)

Given your “we don’t understand the shape of our workflow” constraint, this should be treated as a first-class capability.

Answer to “should it be a new flow”

Choose: A. Add new flow “Generate Workflow Graph” to Core Flows. Because it’s the only way to operationalize the “workflow observability” gap.

7.1 Two graphs: static and dynamic

Dynamic graph (canonical truth)

- Generated from durable evidence:
  - WSS run/step docs + log shard events (step_start/stop, tool_start/stop, spawn_step, etc.)
- This graph answers: “what actually happened?”

Static graph (best-effort intent)

- Generated from:
  - python AST call graph
  - markdown workflow definitions (agent definitions)
- This graph answers: “what should happen?” / “what could happen?”

Static graph must allow unknown edges (do not hallucinate).

7.2 CLI/API

- workflowctl graph run <run_id> --format json|mmd|dot --out <path>
- workflowctl graph static --workflow <id-or-path> --format json|mmd|dot --out <path>

7.3 Storage locations

- Dynamic:
  - workspace/runs/<run_id>/artifacts/graphs/workflow.json
  - workspace/runs/<run_id>/artifacts/graphs/workflow.mmd
- Static:
  - workspace/projects/<project_id>/artifacts/graphs/static_<workflow_id>.json

This fits the WSS artifact pattern already used for investigations/evaluations.

7.4 Markdown “LLM interpreter” mode (on-demand, not a daemon)

To solve “agents in markdown are opaque”:

- Provide an optional step:
  - workflowctl graph static --with-llm
- It produces:
  - a JSON graph where every edge has evidence refs (markdown line ranges)
  - unknown edges when insufficient evidence exists

No background monitor is required; this is invoked as a normal workflow step.

8) [MODERATE] Two-stage linting (hunk lint + sandbox lint)

Analysis v3 calls for two-stage linting; current flows only mention sandbox validation.

Answer to “where to document”

Choose: A. Yes, add to Flow 7 and Flow 9. Flow 7 should mention the fast stage; Flow 9 should require the full stage.

8.1 Stage 1: Hunk lint (fast reject) — mandatory

When

- Immediately after patch generation (Mode A or Mode B capture), before applying patch to stack.

What it does

- Validate patch format
- Validate patch applies cleanly to the hydrated base (dry-run apply)
- Optional fast syntax checks on changed files only (configurable)

Failure behavior

- Reject patch; step fails fast with a clear error record.
- Progress guard: if the same patch fails with the same signature twice, force Mode B (or escalate) — no blind looping.

8.2 Stage 2: Sandbox lint/test/build (complete) — mandatory for completion

When

- After task execution (Flow 7): “as configured”
- Before ticket closure (Flow 9): always required

Failure behavior

- Write sandbox report artifacts under WSS and block completion.
- Create follow-up ticket/task based on gap report (no repeated attempts unless new evidence).

8.3 Configurability

- hunk_lint.enabled: default true
- sandbox_validation.on_step: default false
- sandbox_validation.on_task_complete: default true
- sandbox_validation.on_ticket_close: locked true

Quick mapping to Traycer’s multiple-choice items

- jj lifecycle: A (provided above)
- virtual hydration: A (provided above)
- decomposition orchestrator: A (add detailed flow to Core Flows; reference Tech Plan for module mapping)
- PAUSE protocol: A (provided above)
- spawn-step control action: A (add flow to Core Flows; provided above)
- MCP gateway: A (provided above)
- workflow graph generation: A (add new flow to Core Flows; provided above)
- two-stage linting: A (add to Flow 7 + Flow 9; provided above)

---

We removed the background monitor LLM process (the standalone that just reads files) if that's what you were talking about. In fact, we can remove the UI altogether! It is no longer necessary for anything! The tauri ui.

---

We need to be careful. Are the monitors you found the threads running in the processes or is it that daemon?

---

Is the "Monitor (optional)" actor in Core Flows referring to:

Option A: The standalone daemon (should be removed entirely)

Option B: The in-process monitoring loop within root runtime (should be kept but clarified as "in-process")

Option C: Both (standalone is optional, in-process is always present)

Please clarify so I can make the correct updates without accidentally removing the in-process monitoring logic. separate long-lived process that watches files

Runs independently of Project/Ticket Manager
This is what we deprecated
Interpretation B: In-process monitoring loop (should be KEPT)

The control thread/loop inside root runtime
Runs within Project Manager or Ticket Manager session
This is what we want
Looking at Flow 14's trigger: "Optional monitor runs continuously or root applies basic detection" - this suggests it could be either a standalone daemon OR in-process monitoring.

My Question to You
Is the "Monitor (optional)" actor in Core Flows referring to:

Option A: The standalone daemon (should be removed entirely)

Option B: The in-process monitoring loop within root runtime (should be kept but clarified as "in-process")

Option C: Both (standalone is optional, in-process is always present)

---

According to documents from January 23, 2026, the specs intend flat orchestration (no grandchildren), but the monitoring/agent-spawn wording is currently ambiguous and internally inconsistent.

1) Answer to the “Monitor (optional)” ambiguity

“Monitor (optional)” should be interpreted as an in-process root-owned monitor loop (a thread or loop inside the root runtime), not a standalone daemon.

Why:

- The system invariants explicitly require flat orchestration: “root directly owns/controls all step/agent processes (no grandchildren)”.
- Yet Core Flows lists a separate “Monitor (optional)” actor described as a “background watcher”, which is ambiguous about whether it’s a daemon or an in-process component.
- The Monitoring & Self-Healing plan separately defines a “Root monitor (optional background)” that watches runs and applies control actions, which fits the “optional actor” concept—but should be clarified as root-owned/in-process, not a daemon.

So the correct resolution is:

- Keep: in-process monitoring/control loops (especially the per-step control thread).
- Keep (optional): a root monitor thread (advanced anomaly detection) that runs only while the root runtime is running.
- Remove: any standalone daemon monitor concept.

2) Was the external daemon removed?

In the provided plan/spec documents, there is no explicit “external daemon” or “LLM daemon” described anymore. What remains is an optional monitor component and a monitor.py module in the target repo layout, described as an “optional background monitor”.

That means:

- Spec-level: the deprecated daemon is not explicitly present, but the wording is still loose enough that someone could implement monitor.py as a long-lived daemon (which you do not want).
- Implementation-level: I cannot verify whether an old daemon script/service still exists because I do not have your repo/services/process list—only the documents you uploaded.

Practical verification checklist (to confirm the daemon is actually gone)

Run these in your repo/system environment:

Repo/code search

- Search for old entrypoints and launch patterns:
  - monitor, daemon, watcher, supervisor, systemd, launchd, cron, nohup, tmux, screen
- Confirm there is no CLI entrypoint like workflowctl monitor --daemon (or similar) and no background “forever loop” invoked outside root runtime.

OS-level autostart

- systemd user services: systemctl --user list-units | grep -i workflow and systemctl --user list-unit-files | grep -i workflow
- cron: crontab -l | grep -i workflow
- launchd (macOS): launchctl list | grep -i workflow
- running processes: ps aux | grep -i workflow / pgrep -af workflow

If any of the above still launches a monitor independently of the root runtime lifecycle, that’s the daemon to remove.

3) The bigger inconsistency: “agents spawning agents” is still implied in the docs

You stated: agents do not spawn agents directly; everything is a direct child of the root script.

The specs currently contradict that in multiple places:

- Core Flows (Flow 14) says: “If step cannot pause: step spawns investigator job …”
- Monitoring & Self-Healing says: “If the step cannot pause within deadline, it spawns an investigator job.”
- Core Infrastructure says: “When a step process is stuck … it spawns an investigator job …”

But those same documents also insist on flat orchestration (no grandchildren):

So as written, the plan is not fully aligned with your “root spawns everything” rule.

4) Concrete doc fixes to remove ambiguity and align with your current architecture

These are minimal, surgical edits that make the intent unambiguous:

A) Core Flows – Actors section

Current: “Monitor (optional): background watcher …”

Replace with something like:

- Root monitor thread (optional, in-process): background loop owned by Root runtime; starts/stops with the root runtime session (no standalone daemon). Raises notifications and writes control actions.

B) Core Flows – Flow 14 trigger line

Current trigger: “Optional monitor runs continuously or root applies basic detection”

Replace with:

- “Root runtime always applies basic liveness/progress detection. If enabled, the root monitor thread runs continuously during the root runtime session.”

C) Core Flows – Flow 14 “step spawns investigator job”

Current: step spawns investigator.

Replace with:

- “If step cannot pause within deadline:
  - step records pause_deadline_exceeded / needs_investigation in its step doc + logs
  - root runtime spawns investigator job as a direct child (sibling process), consumes bounded evidence, emits classification”

This preserves flat orchestration.

D) Monitoring & Self-Healing – “step spawns investigator”

Current: step spawns investigator.

Replace with:

- “If the step cannot pause within deadline, it requests investigation; root runtime spawns the investigator job (no grandchildren).”

Also adjust “Step process control thread” wording so “escalates to investigator” becomes “emits investigation request” (same meaning, correct ownership).

E) Core Infrastructure – Investigator contract

Current: step spawns investigator job.

Replace with:

- “When a step is stuck … root spawns an investigator job with bounded inputs …”

This keeps the “investigator contract” intact but fixes ownership.

F) Integration & File Structure – monitor.py comment

Current: monitor.py # optional background monitor

Replace with:

- monitor.py # optional root-monitor thread (in-process; not a standalone daemon)

Bottom line

- Answer: “Monitor (optional)” should mean an in-process root monitor thread, not a standalone daemon.
- Was the daemon removed?
  - From the docs: there is no explicit external daemon described anymore, but the wording still allows accidental reintroduction as a daemon (needs clarification).
  - From the actual system: cannot be confirmed from the provided artifacts; use the checklist above.
- Agents spawning agents: the docs currently still imply this via “step spawns investigator job” language, which directly conflicts with flat orchestration; update ownership to “root spawns investigator”.

---

jj (Jujutsu) as VCS backend - New technology with learning curve
File-based queues for control plane - Atomicity and concurrency concerns
Virtual hydration without persistent checkouts - Performance and caching strategy
Flat orchestration with spawn-step - Complexity vs benefit trade-off
Mandatory PAUSE protocol - Enforcement and deadline handling
WSS JSON Merge Patch semantics - Multi-writer correctness
Ephemeral sandboxes with backend selection - Performance and platform support
Critical Concerns (Ordered by Importance)
[MOST IMPORTANT] jj Adoption Risk - New Technology Without Validation
The architecture depends fundamentally on jj (Jujutsu VCS) for the Patch Graph Store, but jj is a relatively new technology (first release 2022) with significant adoption risk:

Technical Risks:

Learning curve: Team must learn jj's change-based model (vs git's commit-based model)
Tooling gaps: Limited IDE integration, fewer Stack Overflow answers, smaller community
API stability: jj is pre-1.0, APIs may change
Performance unknowns: No validation that jj operations (rebase, hydrate, export) are actually faster than git
Debugging complexity: When jj behaves unexpectedly, fewer resources available
Integration Complexity:

The PGS adapter must map conceptual operations to jj commands
Virtual hydration depends on jj's ability to efficiently reconstruct files
Rebase depends on jj's conflict representation
Export depends on jj git interop
Current Mitigation: None documented. The specs assume jj will work as expected.

Alternative Approaches:

Option A: Use git with a patch management layer (git format-patch, git am, git rebase)

✅ Well-understood, mature tooling
✅ Existing team knowledge
✅ Rich ecosystem
⚠️ May require more complex worktree management
Option B: Implement a minimal POC with jj before committing the architecture

✅ Validates assumptions about performance and usability
✅ Identifies integration issues early
⚠️ Delays implementation by 1-2 weeks
Option C: Proceed with jj but document fallback plan

✅ Allows moving forward
✅ Provides safety net
⚠️ Fallback may require significant rework
Question: What is your risk tolerance for adopting jj? Have you validated that jj's performance and capabilities meet your needs, or should we build a POC first?

A. Proceed with jj (accept risk)

B. Build jj POC first (validate assumptions)

C. Use git instead (reduce risk)

D. Proceed with jj but document fallback plan

[MOST IMPORTANT] File-Based Queue Atomicity Under Concurrent Load
The architecture uses file-based queues for notifications and control actions with a Maildir-like pattern (tmp → inbox → processing → outcomes). Under concurrent load, this has atomicity risks:

The Pattern (from Core Infrastructure):

Producer writes to tmp/, fsync, atomic rename to inbox/
Consumer atomically renames to processing/<consumer_id>/ to claim
Outcomes go to applied/failed/archive/
Concurrency Risks:

Risk 1 - Race on claim: Two consumers try to claim the same file simultaneously

Both attempt rename(inbox/file → processing/consumer1/file) and rename(inbox/file → processing/consumer2/file)
On POSIX, rename is atomic, so one succeeds and one fails with ENOENT
✅ This is safe IF consumers handle ENOENT gracefully
⚠️ Specs don't document this error handling requirement
Risk 2 - Orphaned processing files: Consumer crashes after claiming but before completing

File stuck in processing/<consumer_id>/ forever
Specs mention "requeue TTL" but don't specify:
Who monitors processing/ for orphans?
How is TTL determined? (file mtime? heartbeat file?)
What prevents infinite requeue loops?
Risk 3 - Notification ID collisions: Multiple producers create notifications simultaneously

If notification_id is ULID with millisecond precision, collisions are possible under high concurrency
Specs use ULID but don't specify monotonic mode or collision handling
Risk 4 - Directory fsync portability: The atomic write protocol requires fsync(directory) after rename

This is POSIX-specific; Windows doesn't support directory fsync
Specs don't address cross-platform atomicity
Current Mitigation: Specs mention "atomic rename" and "idempotency" but don't address these specific failure modes.

Question: How should the system handle these concurrency edge cases? Should we:

Document explicit error handling for ENOENT on claim?
Specify who monitors orphaned processing files and how?
Use ULID monotonic mode to prevent ID collisions?
Define Windows-specific atomicity guarantees?
A. Add explicit error handling and monitoring specs

B. Simplify to single-consumer queues (reduce concurrency)

C. Accept risks as acceptable for local-only system

[MOST IMPORTANT] Virtual Hydration Performance - Unvalidated Assumptions
The architecture assumes virtual hydration (on-demand file reconstruction from jj stacks) will be fast enough for interactive agent workflows, but this is unvalidated:

Performance Concerns:

Concern 1 - Hydration latency: Each workflowctl hydrate call must:

Invoke jj subprocess
Reconstruct file from anchor + patch stack
Return content to agent
For a 20-step task with 5 file reads per step = 100 hydration calls
If each call takes 100ms, that's 10 seconds of pure hydration overhead
Concern 2 - Cache effectiveness: Specs mention caching but don't specify:

Cache hit rate assumptions
Cache invalidation strategy (when patches are added to stack)
Cache size limits
What happens when cache is cold (first run)?
Concern 3 - Large file handling: Specs mention "blob refs" for files > 256 KiB but don't specify:

How common are large files in typical workflows?
Does chunked reading add significant complexity?
What's the performance impact of chunk reads vs inline content?
Concern 4 - Concurrent hydration: Multiple step processes may hydrate the same files simultaneously

Does jj handle concurrent reads efficiently?
Is there lock contention in jj's internal state?
Should hydration be serialized or is parallel safe?
Current Mitigation: Specs mention caching and size limits but don't provide performance targets or fallback strategies.

Alternative Approaches:

Option A: Validate hydration performance with benchmarks before committing architecture
Option B: Add fallback to materialized checkouts when hydration is too slow
Option C: Pre-hydrate common files at task start (eager caching)
Option D: Accept that first iteration may be slow, optimize later based on real data
Question: What are your performance requirements for hydration? Should we validate jj's hydration performance before proceeding, or accept that optimization will happen iteratively?

A. Validate with benchmarks first

B. Add fallback to materialized checkouts

C. Pre-hydrate common files (eager caching)

D. Accept iterative optimization (start simple)

[SIGNIFICANT] Flat Orchestration Complexity - Is spawn-step Worth It?
The architecture enforces flat orchestration (no grandchildren) by requiring agents to request spawning via control actions. This adds significant complexity:

Complexity Added:

Control action protocol: Agents write spawn requests, wait for ACKs, poll for completion
Waiting mechanism: workflowctl wait-step must poll WSS or tail logs
Error handling: Spawn failures, timeout handling, orphaned spawn requests
Debugging: Parent-child relationships are logical (in metadata) not OS-level (process tree)
Benefits Claimed:

Root has visibility into all processes
Can pause/kill entire workflow cleanly
Process tree is flat and manageable
Alternative Approach: Allow agents to spawn child processes directly, but:

Register children with root via heartbeat/registration
Root tracks full process tree (including grandchildren)
PAUSE propagates down the tree
This would:

✅ Simplify agent code (no control action dance)
✅ Reduce latency (no file I/O for spawning)
✅ Use OS process tree (easier debugging)
⚠️ Require more sophisticated process tracking in root
Question: Is flat orchestration worth the added complexity? The benefits (visibility, control) could be achieved with process tree tracking without requiring the spawn-step control action protocol.

What specific problems does flat orchestration solve that justify this complexity?

A. Keep flat orchestration (complexity justified)

B. Allow direct spawning with registration (simpler)

C. Hybrid: direct spawn for tools, control action for agents

[SIGNIFICANT] Mandatory PAUSE Enforcement - Deadline Violations
The architecture requires all step processes to honor PAUSE within strict deadlines (2-10 seconds), but enforcement mechanisms are underspecified:

The Requirement:

Step must check for PAUSE every 250ms (pause_check_interval_ms)
Step must ACK PAUSE within 2-10 seconds (pause_ack_deadline_ms)
If cannot ACK, step spawns investigator
Enforcement Gaps:

Gap 1 - Long-running tool subprocesses: If a step is running a tool that takes 5 minutes (e.g., full test suite), how does it pause?

Must it kill the tool subprocess?
Can it wait for tool to complete?
What if tool doesn't respond to signals?
Gap 2 - Agent LLM calls: If a step is waiting for an LLM response (30-60 seconds), how does it pause?

LLM APIs don't support cancellation mid-request
Must the step wait for response before pausing?
Does this violate the 2-10 second deadline?
Gap 3 - Investigator spawning: If step cannot pause, it "spawns investigator"

But flat orchestration says steps can't spawn (only root can)
This is a contradiction with the spawn-step control action requirement
Should it be "step requests investigation via control action"?
Gap 4 - Deadline violation consequences: What happens if step doesn't ACK within deadline?

Does root kill the process?
Does root spawn investigator anyway?
Is there a grace period?
Current Mitigation: Specs mention deadlines and investigator spawning but don't resolve these contradictions.

Question: How should PAUSE handle long-running operations that cannot be interrupted? Should we:

Allow "best-effort pause" with extended deadlines for certain operations?
Require all operations to be interruptible (may be impractical)?
Clarify that "step spawns investigator" means "step requests investigation via control action"?
A. Allow best-effort pause with extended deadlines

B. Require all operations interruptible (strict)

C. Clarify investigation request mechanism

D. Combination of above

[SIGNIFICANT] WSS Multi-Writer Correctness - Lost Update Risk
The WSS uses JSON Merge Patch with optional optimistic concurrency (expected_rev), but the enforcement is unclear:

The Pattern:

Multiple step processes may update the same WSS document (e.g., run.json)
Updates use JSON Merge Patch semantics
Optional expected_rev for optimistic concurrency
Lost Update Scenarios:

Scenario 1 - Concurrent metric updates: Two steps update run.json metrics simultaneously

Step A reads run.json (rev 5), adds metric, writes patch
Step B reads run.json (rev 5), adds different metric, writes patch
Both patches apply successfully (JSON Merge Patch merges objects)
✅ No lost update (both metrics present)
But what if they update the same metric key?
Scenario 2 - Status transitions: Two processes try to update run.json status

Step A: status: "running" → status: "paused"
Step B: status: "running" → status: "failed"
Last write wins (no conflict detection)
❌ Lost update (one status overwrites the other)
Scenario 3 - Optional rev not enforced: Specs say optimistic concurrency is "optional"

If writers don't include expected_rev, lost updates are possible
Who enforces that critical updates use expected_rev?
What happens if a writer forgets?
Current Mitigation: Specs mention "ownership enforcement" (writers refuse to patch docs they don't own) but don't specify:

How is ownership determined? (by document type? by field?)
Is ownership enforced mechanically or by convention?
What happens when ownership is violated?
Question: Should we:

Make expected_rev mandatory for all WSS updates (strict)?
Define clear ownership rules per document type (e.g., only root updates run.json status)?
Accept that some lost updates are acceptable for non-critical fields?
A. Make expected_rev mandatory (strict)

B. Define ownership rules per document type

C. Accept lost updates for non-critical fields

D. Combination (ownership + optional rev for metrics)

[SIGNIFICANT] Sandbox Backend Selection - Platform Support Matrix
The specs require "sandboxes must not copy entire repo" and mention backend selection (overlay → reflink → hardlink → copy) but don't specify platform support:

Platform Support Matrix (needs documentation):

Backend	Linux	WSL2	macOS	Windows
overlayfs	✅ Native	⚠️ Requires kernel support	❌ Not available	❌ Not available
fuse-overlayfs	✅ Available	⚠️ Requires /dev/fuse	⚠️ Requires macFUSE	❌ Not available
reflink	✅ btrfs/xfs	⚠️ Depends on WSL FS	✅ APFS	✅ ReFS (limited)
hardlink	✅ Available	✅ Available	✅ Available	⚠️ Limited (NTFS)
copy	✅ Fallback	✅ Fallback	✅ Fallback	✅ Fallback
Critical Questions:

Q1 - WSL2 support: Your constraints say "Linux/WSL only for the engine"

Does this mean Windows native is not supported?
If WSL2, which filesystem? (ext4 in virtual disk? Windows filesystem via 9p?)
Overlay/reflink support varies significantly based on WSL filesystem choice
Q2 - Fallback behavior: When all fast backends fail, specs say "full copy with explicit warning"

What is the warning mechanism? (notification? log event? stderr?)
What are the "strict retention limits" for copy-based sandboxes?
Should the system refuse to run if only copy is available?
Q3 - Backend detection: How does the system detect which backends are available?

Runtime detection (try each backend, use first that works)?
Configuration file (user specifies available backends)?
Platform-based defaults (assume overlayfs on Linux)?
Current State: Specs mention backend selection order but don't specify platform support matrix or detection mechanism.

Question: Should we document the platform support matrix and backend detection strategy, or is this an implementation detail?

A. Document platform support matrix in specs

B. Defer to implementation (runtime detection)

C. Simplify: require overlayfs/reflink, fail if unavailable

---

1. Just use jj

2) File-based queue atomicity under concurrent load

Answer: A — add explicit error handling + monitoring specs (do not simplify to single-consumer; do not accept silent risk).

Reason: queues are explicitly described as durable, multi-writer safe primitives, and they are part of the control plane (PAUSE/ACK), so edge cases must be specified, not implied.

Tech_Plan__Core_Infrastructure_…

Tech_Plan__Core_Infrastructure_…

Tech_Plan__Core_Infrastructure_…

Spec additions that close the gaps:

1. Claim race handling (ENOENT)

- When claiming via rename from inbox/ → processing/<consumer_id>/, consumers MUST treat:
  - ENOENT as “lost the race” and continue (no error log spam, no retry storm).
- Put this in the shared queues.py helper so every consumer is correct by default (the repo layout already anticipates a queue helper module).
  Tech_Plan__Integration_&_File_S…

1. Orphaned processing files (consumer crash)

- Define a single “reaper” responsibility:
  - Root runtime (or the optional root monitor thread) periodically scans processing/** and re-queues stale items (or quarantines them after N attempts).
- Define lease/TTL mechanism:
  - either mtime on the claimed file is refreshed by the consumer heartbeat, or a sidecar lease.json is refreshed.
- Define attempt counter:
  - include attempt in the JSON body or filename; after N retries move to failed/ and raise a notification.

1. ID collision avoidance

- Require monotonic ULID generation (or equivalent) per-process for notification_id / request_id, since filenames embed IDs and producers are concurrent.
  Tech_Plan__Core_Infrastructure_…
  Tech_Plan__Core_Infrastructure_…

1. Durability guarantees / platform statement

- Your durability protocol already mandates fsync patterns for WSS writes (tmp → fsync → rename → fsync(dir)).
  Tech_Plan__Core_Infrastructure_…
- Apply the same principle to queue writes (producer write+fsync before publish, and fsync(dir) after publish) and explicitly state the supported platform semantics (POSIX; and what is/ isn’t guaranteed on Windows).

1. Just do it. No poc. For cache implement batching (hydrate_tree) + caching under ~/.workflow/.../caches/, .

The specs already include the right lever to avoid “100 hydrate calls”:

- the PGS adapter includes hydrate_tree(stack_id, paths[]), so steps can batch hydrate once per step (or once per phase), not per file read.
  Tech_Plan__Core_Infrastructure_…

Built-in fallback already exists conceptually

- The Integration plan explicitly defines:
  - Mode A: hydrate specific files/functions (workflowctl hydrate) and patch
  - Mode B: hydrate a sandbox and run tools; capture diff and apply as a patch
  - and says Mode B is the fallback for heavy tooling/broad search.
    Tech_Plan__Integration_&_File_S…

use Mode B when the workload is inherently “many reads / broad search”.



1. A keep flat orchestration (complexity justified), with the existing hybrid rule: steps may spawn tool subprocesses internally, but agent/step processes remain root-owned.
  Reason: “no grandchildren” is stated as a core invariant across the specs, and the integration plan already permits tool subprocesses while keeping orchestration flat.
  Core_Flows__Project_Management_…
  Tech_Plan__Integration_&_File_S…
  What flat orchestration solves (specific, not vague):
  - PAUSE correctness boundary: if all step/agent processes are direct children, the root can reason about “what must be paused” without relying on every child to correctly register descendants. (PAUSE is a correctness requirement in the core philosophy.)
    Tech_Plan__Core_Infrastructure_…
  - Evidence + lifecycle integrity: step execution docs and log shards are keyed by run_id / step_execution_id / writer_id, and the root is the natural allocator/owner of those lifecycles. Flat orchestration makes those ownership rules enforceable rather than “best effort.”
    Tech_Plan__Core_Infrastructure_…
    Tech_Plan__Core_Infrastructure_…
  - Operational cleanup: runtime artifacts live under a single root for cleanup/backup; leaked/untracked agent processes undermine that goal.
    Tech_Plan__Core_Infrastructure_…
  How to reduce the “control action dance” without changing the invariant
  - Provide a single helper API (or workflowctl spawn-step) that:
    - writes the spawn request,
    - waits on WSS/log evidence for completion,
    - returns the spawned step’s IDs. This keeps the architecture invariant but hides boilerplate in one well-tested primitive (which matches your “agents don’t spawn agents directly; root spawns everything” rule).

According to a document from January 23, 2026, PAUSE is a correctness requirement and a step is only “paused” once it is no longer running tool subprocesses, is not mutating WSS, and has flushed boundaries, then ACKs via the control_actions queue. If it can’t meet the deadline, it should escalate via the investigator path (not “root kills by default”).

5) Mandatory PAUSE enforcement — answer and what to change

Decision: D (combination).

- C (clarify investigation mechanism) is required to reconcile “investigator spawning” with flat orchestration.
- B (require interruptibility) is required to actually meet the PAUSE deadline.
- A (best-effort + extended deadlines) should exist, but only as an explicit per-operation/per-step parameter (bounded), not as an open-ended loophole.

What the specs already say (and imply)

- Every step has a control loop that polls control actions and must honor PAUSE within a deadline, explicitly including “stops tool subprocesses … stops WSS mutations … writes pause ACK file … escalates to investigator on inability to pause.”
- The monitoring plan explicitly treats PAUSE as the default control-plane primitive (“PAUSE replaces kill + restart as the default”), and says killing is only an option when the investigator classifies needs_shutdown or a tool is confirmed hung and can’t be stopped cleanly.

Concrete answers to Traycer’s “gaps”

Gap 1 — Long-running tool subprocesses (tests, builds, etc.) Specification-level resolution:

1. All long-running work must run as a tracked tool subprocess (or a small set of them) so the control loop can stop it. This is already implied by the definition of “paused” (“not executing any tool subprocess”).
2. On PAUSE, the step must stop tool subprocesses before ACK. That’s already stated in both the Monitoring plan and Integration plan (“stop tool subprocesses … write ACK … wait for RESUME”).
3. Add one missing spec detail: stop policy and escalation ladder (e.g., graceful signal → short grace → forced kill) and ensure tool PIDs are recorded in logs/WSS so the investigator can act on them.

Gap 2 — LLM calls that don’t support mid-flight cancellation Given your constraint (“agents do not spawn agents directly; everything is a direct child of root”), the safest spec-level rule is:

- LLM calls must be executed via a cancellable “tool subprocess” boundary (e.g., a workflowctl subcommand or wrapper process). Then PAUSE can terminate that subprocess and ACK can still be timely. This matches the step-control-loop model (“stops tool subprocesses”) and flat orchestration (steps may spawn tool subprocesses, but orchestration stays flat).

Gap 3 — “Step spawns investigator” contradicts flat orchestration This needs a spec clarification, because multiple docs literally say “step spawns investigator job.” To stay consistent with “everything is a direct child of root” and “no orchestration-level grandchildren”:

- Interpret/clarify “spawns investigator job” as: Step transitions into “pause_failed / stuck” state + emits evidence pointers, and Root (or the optional root monitor) is the entity that spawns the investigator step/job.
- Mechanically: the step can write a durable “investigation requested” artifact (or a control action request targeted at root), and the root monitor picks it up and spawns the investigator as a sibling process (flat). This preserves the “investigate-first” strategy without violating flat orchestration.

Gap 4 — Consequences if step misses the PAUSE ACK deadline Already implied by the monitoring plan:

- Missing ACK triggers the investigator path (default), not immediate root kill.
- Root kill is a last resort when investigator says needs_shutdown or tool is confirmed hung and cannot be stopped cleanly.

What to add to specs (minimal but sufficient)

- Define a standard “tool stop ladder” and a bounded “pause cleanup budget” that must fit inside pause_ack_deadline_ms, with per-tool overrides (still bounded).
- Add one explicit line: “Investigator job is spawned by root (or root monitor) to preserve flat orchestration; steps only request/escalate.”

6) WSS multi-writer correctness — answer and what to change

Decision: D (combination: ownership rules + optimistic concurrency where it matters).

What the specs already contain (good foundation)

- WSS docs “MUST include … writer/ownership fields where relevant (for multi-writer correctness).”
- Updates use JSON Merge Patch (RFC 7396) and “arrays are treated as scalars (replace entirely).”
- Ownership rules are explicitly stated:
  - Step owns its step execution doc updates (metrics, status)
  - Root owns run.json lifecycle transitions and other long-lived docs/indexes

The concrete policy to prevent “lost update” bugs

1. Make document ownership enforceable, not advisory.
  - Enforce at the WSS helper layer: e.g., wss.patch_run_json_status(...) only callable from root runtime; step-side calls reject.
  - This resolves the dangerous “two writers set run status differently” scenario by design, because only root can write run.json.status.
2. Add a rev field and require expected_rev for critical transitions.
  - JSON Merge Patch is fine for additive metrics, but status transitions are “last write wins” unless you add CAS.
  - Make expected_rev mandatory for:
    - run.json.status, ended_at, and other lifecycle fields owned by root
    - any doc that can be touched by multiple interactive sessions (indexes, ticket metadata) even if “logically owned”
  - This is the smallest change that closes the lost-update hole without turning WSS into a DB.
3. Avoid arrays in multi-writer docs (or treat them as single-writer only).
  - Because arrays replace entirely under Merge Patch, arrays are a high-risk shape for concurrent edits.
  - Prefer maps keyed by stable IDs (writer_id, step_execution_id, etc.), which merge cleanly when writers touch different keys.
4. Keep “multi-writer” where it’s safe and already designed that way
  - Logs are already sharded per writer to avoid contention; that’s the right way to scale evidence.

7) Sandbox backend selection — answer + all sub-questions

Decision: A (document a platform support matrix in the specs), plus a short, explicit backend detection strategy. Reason: sandboxes are a core primitive (tools run in them), and the spec already treats them as an invariant (“must not require copying the entire repo”). If you don’t document platform/backend expectations, you’ll get unpredictable behavior and performance regressions that look like “random CI flakiness.”

What the specs already say (the contract)

- Sandboxes are disposable directories under sandboxes/.
- Key invariant: “Sandboxes must not require copying the entire repo.”
- They are part of the minimum CLI surface (workflowctl sandbox run …).

Q1 — WSL2 support: what to specify

Specs currently don’t define OS/platform constraints explicitly (beyond “local-only”). So you should add:

- Supported platforms for the engine: Linux (primary).
- WSL2: supported only when the repo lives on the Linux filesystem (ext4-in-VHD), not on /mnt/c-style Windows filesystems, because sandbox backends (especially overlay) may not behave correctly there.
- If the repo is on a filesystem that can’t support the required backend, the system must either:
  - refuse to create a sandbox with a clear error (strict invariant), or
  - require an explicit opt-in to a slower/fallback mode (see Q2).

Q2 — Fallback behavior + warning mechanism + retention limits

To reconcile the “must not require copying the entire repo” invariant with real-world platform gaps, define two modes:

Mode 1 (default): strict

- If no non-copy backend is available, sandbox creation fails with a notification + log event, instructing the user what to change (filesystem move, enable overlay, etc.).

Mode 2 (explicit opt-in): copy-fallback

- Allow full-copy sandbox only when explicitly enabled (config flag), and enforce strict retention:
  - max total sandbox bytes
  - max number of concurrent copy-based sandboxes
  - aggressive TTL cleanup
- Warning mechanism should be a notification file (severity warn), since notifications are the standard user-visible channel in the architecture.

Q3 — Backend detection: runtime probing vs config

Do both, but keep it simple:

- Runtime detection (default): sandbox.runner tries backends in priority order, using a fast probe (create tiny sandbox, attempt operation, destroy). This matches the spec’s bias for robustness over micro-optimizing I/O.
- Config override: allow pinning a backend or disabling fallback modes for predictable behavior.

One important correction to bake into the spec

If you include hardlink as a backend, you must restrict it, because hardlinks do not provide isolation for write-in-place tools. A safe spec is:

- Writable sandboxes: overlayfs or reflink only.
- Read-only tooling sandboxes: may use hardlink only if you can guarantee tools will not modify tracked source files (or you have an enforcement mechanism). If you can’t guarantee/enforce that, remove hardlink from the supported backend list and keep the invariant strict.

If you want these answers translated into concrete spec edits, they map cleanly to:

- a clarification patch in Monitoring & Self-Healing (“investigator spawn mechanism is root-spawned to preserve flat orchestration”)
- a short WSS concurrency section under Core Infrastructure (ownership + rev/expected_rev)
- a Sandbox backend appendix (platform matrix + backend probing + fallback policy) anchored on the existing sandbox invariant

---

[MODERATE] MCP Gateway Single Tool - Allowlist Maintenance Burden
The architecture requires all agent execution to go through a single MCP tool (workflow_engine) with allowlisted subcommands. This creates a maintenance burden:

The Constraint:

Agents can only call allowlisted workflowctl subcommands
Python scripts must be registered in a manifest
No arbitrary command execution
Maintenance Concerns:

Concern 1 - Allowlist updates: Every time a new workflow needs a new operation:

Must update the allowlist
Must update MCP tool schema
Must update documentation
Risk of "allowlist becomes a bottleneck"
Concern 2 - Python script registration: Specs say "registered scripts only" but don't specify:

Where is the manifest? (scripts/manifest.json?)
Who maintains it? (manual? auto-generated?)
What happens when a script is added but not registered?
Concern 3 - Debugging friction: When developing new workflows:

Must register every new script before testing
Cannot quickly prototype with ad-hoc scripts
May slow down iteration
Current Mitigation: Specs mention allowlist and registration but don't address maintenance burden.

Alternative Approaches:

Option A: Keep strict allowlist (security first, accept maintenance)
Option B: Allow "dev mode" with relaxed restrictions for local development
Option C: Auto-register scripts in certain directories (e.g., scripts/workflows/)
Option D: Use capability-based permissions instead of allowlist (more flexible)
Question: How should we balance security/auditability with development velocity? Is the allowlist maintenance burden acceptable?

A. Keep strict allowlist (security first)

B. Add dev mode with relaxed restrictions

C. Auto-register scripts in certain directories

D. Use capability-based permissions

[MODERATE] Workflow Graph Generation - Static Extraction Feasibility
Core Flows includes workflow graph generation with "deterministic extraction first, optional LLM interpreter second" but the feasibility of deterministic extraction is questionable:

The Challenge:

Workflows are hybrid: markdown agent definitions + Python scripts + dynamic control flow
Markdown is unstructured prose (not machine-readable)
Python may have dynamic imports, conditional execution, runtime decisions
Deterministic Extraction Limitations:

Limitation 1 - Markdown parsing: Agent definitions in markdown have no standard format

How do you deterministically extract "this agent calls this script"?
What if the markdown is ambiguous or uses natural language?
Specs say "parse markdown for explicit, standardized script/tool call syntax" but no such syntax is defined
Limitation 2 - Python AST limitations: AST can find workflowctl calls but not:

Dynamic command construction (cmd = "hydrate" if x else "apply-patch")
Calls through indirection (getattr(workflowctl, method_name)())
Conditional execution (if config.enabled: workflowctl.run())
Limitation 3 - Unknown edges: Specs say "emit unknown nodes/edges rather than guessing"

If most edges are unknown, is the graph useful?
Does this defeat the purpose of static graph generation?
Current State: Specs require static graph but don't define:

What "standardized script/tool call syntax" means for markdown
How much unknown is acceptable before graph is useless
Whether static graph is actually achievable
Question: Should we:

Define a strict markdown syntax for agent definitions (makes static extraction possible)?
Accept that static graphs will be mostly unknown (limited usefulness)?
Focus only on dynamic graphs (from execution evidence)?
Simplify to "graph generation is best-effort, unknown edges are normal"?
A. Define strict markdown syntax for agents

B. Accept mostly-unknown static graphs

C. Focus only on dynamic graphs

D. Best-effort with unknown edges normal

[MODERATE] Codebase Fit - Existing Patterns vs New Architecture
The new architecture introduces several patterns that may conflict with existing codebase patterns. I need to verify fit with the actual codebase:

New Patterns Introduced:

File-based WSS with JSON Merge Patch
Sharded JSONL logs (one per writer)
File-based queues (Maildir-like)
jj for VCS operations
@step decorator with file-backed state
Flat orchestration with spawn-step control actions
Existing Patterns (from 
 and visible structure):

uv run for Python execution
Agent definitions in markdown (.claude/commands/, .agents/)
Existing workflow scripts in scripts/
Git-based workflows (worktrees, branches)
Potential Conflicts:

Conflict 1 - Existing workflows use git: Files like .claude/commands/review-implementation.md and .claude/commands/update-pr.md likely assume git operations

How do these integrate with jj-based stacks?
Do they need complete rewrites or can they be adapted?
Conflict 2 - Agent definitions in markdown: Existing agents are defined in markdown without structured syntax

New architecture requires "standardized script/tool call syntax" for static graphs
Does this mean rewriting all existing agent definitions?
Conflict 3 - No existing @step pattern: The codebase doesn't currently use @step decorator

Is this a new pattern being introduced?
How much existing code needs to be retrofitted?
Question: I need to examine the existing codebase to validate fit. Should I:

Review existing workflow files to understand current patterns?
Identify specific integration points that need adaptation?
Assess the scope of retrofitting required?
A. Yes, review existing workflows for fit assessment

B. Assume clean-slate implementation (minimal retrofit)

C. Defer codebase fit to implementation phase

---

According to a document from January 23, 2026, PAUSE is a correctness requirement and a step is only “paused” once it is no longer running tool subprocesses, is not mutating WSS, and has flushed boundaries, then ACKs via the control_actions queue. If it can’t meet the deadline, it should escalate via the investigator path (not “root kills by default”).

5) Mandatory PAUSE enforcement — answer and what to change

Decision: D (combination).

- C (clarify investigation mechanism) is required to reconcile “investigator spawning” with flat orchestration.
- B (require interruptibility) is required to actually meet the PAUSE deadline.
- A (best-effort + extended deadlines) should exist, but only as an explicit per-operation/per-step parameter (bounded), not as an open-ended loophole.

What the specs already say (and imply)

- Every step has a control loop that polls control actions and must honor PAUSE within a deadline, explicitly including “stops tool subprocesses … stops WSS mutations … writes pause ACK file … escalates to investigator on inability to pause.”
- The monitoring plan explicitly treats PAUSE as the default control-plane primitive (“PAUSE replaces kill + restart as the default”), and says killing is only an option when the investigator classifies needs_shutdown or a tool is confirmed hung and can’t be stopped cleanly.

Concrete answers to Traycer’s “gaps”

Gap 1 — Long-running tool subprocesses (tests, builds, etc.) Specification-level resolution:

1. All long-running work must run as a tracked tool subprocess (or a small set of them) so the control loop can stop it. This is already implied by the definition of “paused” (“not executing any tool subprocess”).
2. On PAUSE, the step must stop tool subprocesses before ACK. That’s already stated in both the Monitoring plan and Integration plan (“stop tool subprocesses … write ACK … wait for RESUME”).
3. Add one missing spec detail: stop policy and escalation ladder (e.g., graceful signal → short grace → forced kill) and ensure tool PIDs are recorded in logs/WSS so the investigator can act on them.

Gap 2 — LLM calls that don’t support mid-flight cancellation Given your constraint (“agents do not spawn agents directly; everything is a direct child of root”), the safest spec-level rule is:

- LLM calls must be executed via a cancellable “tool subprocess” boundary (e.g., a workflowctl subcommand or wrapper process). Then PAUSE can terminate that subprocess and ACK can still be timely. This matches the step-control-loop model (“stops tool subprocesses”) and flat orchestration (steps may spawn tool subprocesses, but orchestration stays flat).

Gap 3 — “Step spawns investigator” contradicts flat orchestration This needs a spec clarification, because multiple docs literally say “step spawns investigator job.” To stay consistent with “everything is a direct child of root” and “no orchestration-level grandchildren”:

- Interpret/clarify “spawns investigator job” as: Step transitions into “pause_failed / stuck” state + emits evidence pointers, and Root (or the optional root monitor) is the entity that spawns the investigator step/job.
- Mechanically: the step can write a durable “investigation requested” artifact (or a control action request targeted at root), and the root monitor picks it up and spawns the investigator as a sibling process (flat). This preserves the “investigate-first” strategy without violating flat orchestration.

Gap 4 — Consequences if step misses the PAUSE ACK deadline Already implied by the monitoring plan:

- Missing ACK triggers the investigator path (default), not immediate root kill.
- Root kill is a last resort when investigator says needs_shutdown or tool is confirmed hung and cannot be stopped cleanly.

What to add to specs (minimal but sufficient)

- Define a standard “tool stop ladder” and a bounded “pause cleanup budget” that must fit inside pause_ack_deadline_ms, with per-tool overrides (still bounded).
- Add one explicit line: “Investigator job is spawned by root (or root monitor) to preserve flat orchestration; steps only request/escalate.”

6) WSS multi-writer correctness — answer and what to change

Decision: D (combination: ownership rules + optimistic concurrency where it matters).

What the specs already contain (good foundation)

- WSS docs “MUST include … writer/ownership fields where relevant (for multi-writer correctness).”
- Updates use JSON Merge Patch (RFC 7396) and “arrays are treated as scalars (replace entirely).”
- Ownership rules are explicitly stated:
  - Step owns its step execution doc updates (metrics, status)
  - Root owns run.json lifecycle transitions and other long-lived docs/indexes

The concrete policy to prevent “lost update” bugs

1. Make document ownership enforceable, not advisory.
  - Enforce at the WSS helper layer: e.g., wss.patch_run_json_status(...) only callable from root runtime; step-side calls reject.
  - This resolves the dangerous “two writers set run status differently” scenario by design, because only root can write run.json.status.
2. Add a rev field and require expected_rev for critical transitions.
  - JSON Merge Patch is fine for additive metrics, but status transitions are “last write wins” unless you add CAS.
  - Make expected_rev mandatory for:
    - run.json.status, ended_at, and other lifecycle fields owned by root
    - any doc that can be touched by multiple interactive sessions (indexes, ticket metadata) even if “logically owned”
  - This is the smallest change that closes the lost-update hole without turning WSS into a DB.
3. Avoid arrays in multi-writer docs (or treat them as single-writer only).
  - Because arrays replace entirely under Merge Patch, arrays are a high-risk shape for concurrent edits.
  - Prefer maps keyed by stable IDs (writer_id, step_execution_id, etc.), which merge cleanly when writers touch different keys.
4. Keep “multi-writer” where it’s safe and already designed that way
  - Logs are already sharded per writer to avoid contention; that’s the right way to scale evidence.

7) Sandbox backend selection — answer + all sub-questions

Decision: A (document a platform support matrix in the specs), plus a short, explicit backend detection strategy. Reason: sandboxes are a core primitive (tools run in them), and the spec already treats them as an invariant (“must not require copying the entire repo”). If you don’t document platform/backend expectations, you’ll get unpredictable behavior and performance regressions that look like “random CI flakiness.”

What the specs already say (the contract)

- Sandboxes are disposable directories under sandboxes/.
- Key invariant: “Sandboxes must not require copying the entire repo.”
- They are part of the minimum CLI surface (workflowctl sandbox run …).

Q1 — WSL2 support: what to specify

Specs currently don’t define OS/platform constraints explicitly (beyond “local-only”). So you should add:

- Supported platforms for the engine: Linux (primary).
- WSL2: supported only when the repo lives on the Linux filesystem (ext4-in-VHD), not on /mnt/c-style Windows filesystems, because sandbox backends (especially overlay) may not behave correctly there.
- If the repo is on a filesystem that can’t support the required backend, the system must either:
  - refuse to create a sandbox with a clear error (strict invariant), or
  - require an explicit opt-in to a slower/fallback mode (see Q2).

Q2 — Fallback behavior + warning mechanism + retention limits

To reconcile the “must not require copying the entire repo” invariant with real-world platform gaps, define two modes:

Mode 1 (default): strict

- If no non-copy backend is available, sandbox creation fails with a notification + log event, instructing the user what to change (filesystem move, enable overlay, etc.).

Mode 2 (explicit opt-in): copy-fallback

- Allow full-copy sandbox only when explicitly enabled (config flag), and enforce strict retention:
  - max total sandbox bytes
  - max number of concurrent copy-based sandboxes
  - aggressive TTL cleanup
- Warning mechanism should be a notification file (severity warn), since notifications are the standard user-visible channel in the architecture.

Q3 — Backend detection: runtime probing vs config

Do both, but keep it simple:

- Runtime detection (default): sandbox.runner tries backends in priority order, using a fast probe (create tiny sandbox, attempt operation, destroy). This matches the spec’s bias for robustness over micro-optimizing I/O.
- Config override: allow pinning a backend or disabling fallback modes for predictable behavior.

One important correction to bake into the spec

If you include hardlink as a backend, you must restrict it, because hardlinks do not provide isolation for write-in-place tools. A safe spec is:

- Writable sandboxes: overlayfs or reflink only.
- Read-only tooling sandboxes: may use hardlink only if you can guarantee tools will not modify tracked source files (or you have an enforcement mechanism). If you can’t guarantee/enforce that, remove hardlink from the supported backend list and keep the invariant strict.

If you want these answers translated into concrete spec edits, they map cleanly to:

- a clarification patch in Monitoring & Self-Healing (“investigator spawn mechanism is root-spawned to preserve flat orchestration”)
- a short WSS concurrency section under Core Infrastructure (ownership + rev/expected_rev)
- a Sandbox backend appendix (platform matrix + backend probing + fallback policy) anchored on the existing sandbox invariant

---

[MODERATE] MCP Gateway Single Tool - Allowlist Maintenance Burden
The architecture requires all agent execution to go through a single MCP tool (workflow_engine) with allowlisted subcommands. This creates a maintenance burden:

The Constraint:

Agents can only call allowlisted workflowctl subcommands
Python scripts must be registered in a manifest
No arbitrary command execution
Maintenance Concerns:

Concern 1 - Allowlist updates: Every time a new workflow needs a new operation:

Must update the allowlist
Must update MCP tool schema
Must update documentation
Risk of "allowlist becomes a bottleneck"
Concern 2 - Python script registration: Specs say "registered scripts only" but don't specify:

Where is the manifest? (scripts/manifest.json?)
Who maintains it? (manual? auto-generated?)
What happens when a script is added but not registered?
Concern 3 - Debugging friction: When developing new workflows:

Must register every new script before testing
Cannot quickly prototype with ad-hoc scripts
May slow down iteration
Question: How should we balance security/auditability with development velocity?

A. Keep strict allowlist (security first)

B. Add dev mode with relaxed restrictions

C. Auto-register scripts in certain directories

D. Use capability-based permissions

[MODERATE] Workflow Graph Generation - Static Extraction Feasibility
Core Flows includes workflow graph generation with "deterministic extraction first, optional LLM interpreter second" but the feasibility of deterministic extraction is questionable:

The Challenge:

Workflows are hybrid: markdown agent definitions + Python scripts + dynamic control flow
Markdown is unstructured prose (not machine-readable)
Python may have dynamic imports, conditional execution, runtime decisions
Deterministic Extraction Limitations:

Markdown has no standard format for agent definitions
Python AST can't handle dynamic command construction
Most edges may be "unknown"
Question: Should we define a strict markdown syntax for agent definitions, or accept that static graphs will be mostly unknown?

A. Define strict markdown syntax for agents

B. Accept mostly-unknown static graphs

C. Focus only on dynamic graphs

D. Best-effort with unknown edges normal

[MODERATE] Codebase Fit - Review Existing Patterns?
Should I review existing workflow files (.claude/commands/review-implementation.md, .claude/commands/update-pr.md, etc.) to:

Understand current patterns
Identify specific integration points
Assess retrofitting scope
Or should we assume this is a clean-slate implementation with minimal retrofit?

A. Yes, review existing workflows for fit assessment

B. Assume clean-slate implementation (minimal retrofit)

C. Defer codebase fit to implementation phase

---

According to a document from January 23, 2026, the monitoring/investigator flow already assumes the system will write ad‑hoc scripts, specifically a resume script referenced by resume_plan (“path to resume script + WSS patches”), and even lists “write resume script” as a possible investigator action.

That means a “registered scripts only / no ad‑hoc scripts” rule is incompatible with the existing plan and with your stated reality (“agents write scripts whenever”). The fix is to treat scripts as auditable artifacts executed through a small set of stable primitives, not as allowlist entries.

Handling custom scripts (including workflow repair “resume scripts”)

1) Make scripts first‑class run artifacts

Store any generated script under WSS run artifacts (or investigation bundle artifacts), with:

- script_id
- created_by (agent/step role)
- language (py/sh)
- sha256 of content
- created_at
- declared capabilities needed (see next section)

This aligns with the existing “investigation bundle” pattern that may already include a reproduction script as an artifact under workspace/runs/<run_id>/artifacts/investigation/<bundle_id>/…

2) Execute scripts only as tool subprocesses (so PAUSE works)

The step control loop is explicitly required to stop tool subprocesses, flush outputs, stop WSS mutations, and then ACK PAUSE. And “paused” is defined as “not executing any tool subprocess.”

So script execution should always be:

- a tracked tool subprocess (PID known to the step)
- wrapped in tool_start / tool_stop logging (already part of the core evidence model)

3) Resume scripts: root-controlled application, not “bypass”

The existing contract says investigator output includes resume_plan (resume script + WSS patches). Treat that as:

- script is produced by repair/investigation
- root applies it (or requests step to apply it) as part of a controlled RESUME/RETRY flow, with full audit trail

This preserves the “repairs must be auditable” safety boundary (repairs as patches; control actions have durable audit trails; no destructive ops without explicit user action).

[MODERATE] MCP Gateway Single Tool — allowlist maintenance vs velocity

Decision: D — capability-based permissions

Reason: you cannot operationally support “agents write scripts whenever” with a per-script registration bottleneck, and the specs already emphasize a small number of boring primitives and that steps manage their internal tool subprocesses.

How to implement D without losing auditability

Keep the allowlist small and stable (primitive operations), and gate power via capabilities rather than enumerating scripts.

1. Allowlist primitives, not scripts The Core Infrastructure spec already lists a minimal workflowctl surface (hydrate/apply-patch/sandbox run/tail notifications/send control/gc). Extend (once) with one generic “run a tool in sandbox” primitive if needed (or broaden sandbox run beyond lint|test|build), because scripting implies arbitrary tooling.
2. Capabilities (role → capability set) Examples:

- sandbox_exec (run arbitrary command inside sandbox)
- wss_write_artifacts (write run artifacts)
- apply_patch (submit patch to stack)
- control_send (write control actions)
- resume_apply (apply resume plan) restricted to root / repair-role

No “role bypass allowlist.” Instead:

- the same allowlisted primitive is used
- runtime checks capability before executing

1. Auto-register scripts per run Remove the “global manifest must be updated” requirement for ad‑hoc scripts:

- a script becomes “registered” by being written as a WSS artifact with hash+metadata
- execution references that artifact path + hash in tool_start/tool_stop log events

1. Debugging / prototyping This falls out naturally:

- agent can emit a script artifact and run it via the generic sandbox/tool primitive
- everything is logged and reproducible

[MODERATE] Workflow graph generation — static extraction feasibility

Decision: D — best-effort static graphs; unknown edges normal; dynamic graph is authoritative

Reason: you already have a durable event stream with explicit lifecycle and tool boundaries (step_start/stop, tool_start/stop) that can generate a dynamic execution graph reliably.

Recommended split:

1. Static graph (best-effort)

- Extract what is explicitly declared (known steps, known scripts/tools) when syntax is present
- Emit unknown edges for everything else (by design)

1. Optional strict markdown syntax for new agent definitions

- Define a minimal machine-readable block (e.g., a fenced yaml “calls:” list) to make deterministic extraction possible going forward
- Do not require rewriting existing markdown; accept unknown edges

1. Dynamic graph (primary)

- Build from logs + WSS run/step docs; it’s already the architecture’s evidence backbone.

[MODERATE] Codebase fit — existing patterns vs new architecture

Decision: A — yes, review existing workflows for fit assessment

The Integration plan explicitly anticipates retrofitting existing workflows (review/update-pr/rebase/merge) rather than a clean slate, and lists concrete retrofit requirements: wrap entrypoints in step runtime, add PAUSE handling, replace DB calls with WSS+logs, and replace worktree editing with patch/sandbox modes.

What this implies for your fit assessment:

1. Identify where existing workflows assume:

- git worktrees / direct editing
- untracked subprocess execution
- no pause checkpoints

1. Map each workflow segment to the two supported execution modes:

- Mode A (hydrate → generate patch → apply patch)
- Mode B (sandbox → run tools/scripts normally → capture diff → apply patch)

1. Keep legacy helpers optional Worktree helpers can remain as optional legacy tooling, but they’re not required for the system to function under the new model.

Bottom line changes to the plan (to resolve your “agents write scripts constantly” reality)

1. Replace “registered scripts only” with:

- “scripts are allowed if stored as run artifacts with hashes + executed via sandbox/tool primitives”

1. Replace “role bypass allowlist” with:

- “capability-gated primitives; special roles get extra capabilities; no bypass path”

1. Make dynamic execution evidence the source of truth for workflow graphs, with best-effort static extraction.

All of this is consistent with: (a) steps managing tool subprocesses while root keeps orchestration flat, (b) mandatory PAUSE semantics, and (c) the explicit resume-script concept already in the investigator contract.

---

